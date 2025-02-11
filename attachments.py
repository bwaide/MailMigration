from email import message_from_bytes
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import os
import hashlib
from email.utils import parsedate_to_datetime
from pathlib import Path
from datetime import datetime
import re

from config import get_config
from config import logger
from stats import add_statistic

# Global variable: Define which attachment types and sizes should be extracted
EXTRACT_ATTACHMENTS = get_config("extract_attachments", "enabled", False)
ATTACHMENT_WHITELIST = get_config("extract_attachments", "attachment_whitelist", [".pdf", ".zip", ".docx", ".xlsx"]) # Allowed file types
MIN_ATTACHMENT_SIZE = get_config("extract_attachments", "min_attachment_size", 0 * 1024) # Min size for attachments to have to be downloaded
MAX_ATTACHMENT_SIZE = get_config("extract_attachments", "max_attachment_size", 100 * 1024 * 1024)  # Max size per attachment in Bytes

download_folder = os.path.expanduser("~")+"/Downloads/"
EXTERNAL_STORAGE_PATH = get_config("extract_attachments", "external_storage_path", download_folder)  # Path to store extracted files

def normalize_filename(filename):
    """
    Normalizes the filename by removing any trailing query string or extra characters
    from the file extension. For example:
      "document.pdf?=" becomes "document.pdf"
    """
    if '?' in filename:
        filename = filename.split('?')[0]
    return filename.strip()

def get_normalized_extension(filename):
    """
    Returns the normalized file extension (in lower-case) for the given filename.
    """
    filename = normalize_filename(filename)
    return os.path.splitext(filename)[1].lower()


def should_extract_attachment(part):
    """Decide whether an attachment should be extracted based on type and size."""
    filename = part.get_filename()
    if not filename:
        return False
    
    # Normalize filename and extension.
    filename = normalize_filename(filename)
    file_ext = get_normalized_extension(filename)
    file_size = len(part.get_payload(decode=True))  # File size in bytes

    add_statistic("attachment_types", file_ext)

    return file_ext in ATTACHMENT_WHITELIST and file_size < MAX_ATTACHMENT_SIZE and file_size > MIN_ATTACHMENT_SIZE

# Helper function to sanitize filenames
def make_filename_safe(filename):
    """
    Sanitizes a filename by:
      - Removing any "file://" prefix.
      - Replacing characters not allowed on most systems (< > : " / \ | ? *) with an underscore.
      - Stripping leading/trailing whitespace.
    
    Args:
        filename (str): The original filename.
    
    Returns:
        str: A safe filename.
    """
    # Remove any URL scheme if present
    filename = filename.replace("file://", "")
    # Replace illegal characters with underscore
    safe_filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    return safe_filename.strip()

def save_attachment(part, email_date_str, simulation):
    """
    Save an extracted attachment to disk in a month-based folder (e.g., "2023_10")
    and return a file:// URL pointing to the stored file.
    
    Args:
        part: The email attachment part.
        email_date_str: The email's sent date as a string 
                        (e.g., "Mon, 09 Oct 2023 12:34:56 -0400" or '"10-Feb-2025 07:56:34 +0100"')
    
    Returns:
        A file:// URL to the stored attachment, or None if filename is missing.
    """
    filename = part.get_filename()
    if not filename:
        return None

    # Normalize the filename (if you have a normalize_filename function, otherwise, use the safe version)
    # Here we simply sanitize the filename.
    filename = make_filename_safe(filename)

    # Strip extra quotes from the date string, if present.
    date_str = email_date_str.strip('"')
    
    # Parse the email date string into a datetime object.
    try:
        email_date = parsedate_to_datetime(date_str)
    except Exception as e:
        try:
            email_date = datetime.strptime(date_str, "%d-%b-%Y %H:%M:%S %z")
        except Exception as e2:
            print(f"Date parsing failed for: {date_str}")
            print(e2)
            email_date = datetime.now()

    # Create a folder name based on the email's date (e.g., "2023_10")
    month_folder = email_date.strftime("%Y_%m")
    storage_dir = os.path.join(EXTERNAL_STORAGE_PATH, month_folder)

    if (not simulation):
        os.makedirs(storage_dir, exist_ok=True)

    # Generate a unique filename using a hash prefix to avoid collisions.
    hash_prefix = hashlib.md5(filename.encode()).hexdigest()[:8]
    storage_filename = f"{hash_prefix}_{filename}"
    storage_path = os.path.join(storage_dir, storage_filename)

    if (not simulation):
        # Write the attachment data to disk.
        file_data = part.get_payload(decode=True)
        with open(storage_path, "wb") as f:
            f.write(file_data)

    add_statistic("attachments", "extracted")
    logger.debug(f"Attachment successfully extracted to {storage_path}")

    # Create a file:// URL pointing to the stored file using pathlib.
    file_url = Path(storage_path).as_uri()
    return file_url

def extract_and_replace_attachments(raw_msg, email_date_str, simulation):
    """
    Extracts attachments meeting the criteria and replaces them with a link.
    Reassembles the email so that the body appears only once.

    Args:
        raw_msg (bytes): Raw email message in bytes.
        email_date_str: Sent date of the message (used for organizing storage).

    Returns:
        bytes: The modified email message (as bytes) with attachments replaced by links.
    """
    # Parse the raw message into an email object
    email_msg = message_from_bytes(raw_msg)
    
    # If the message isn't multipart, return it unchanged
    if not email_msg.is_multipart():
        return raw_msg

    # Create a new email container (multipart/mixed)
    new_email = MIMEMultipart("mixed")
    # Copy key headers from the original message
    for header in ["Subject", "From", "To", "Date"]:
        if email_msg[header]:
            new_email[header] = email_msg[header]

    # Initialize lists to store parts
    body_parts = []         # For text parts (the email body)
    keep_parts = []         # For attachments that should not be extracted
    attachment_links = []   # For links to extracted attachments

    # Walk through all parts (leaf nodes) of the email
    for part in email_msg.walk():
        # Skip container parts
        if part.is_multipart():
            continue

        # Check if the part has a filename (i.e. it's an attachment)
        filename = part.get_filename()
        if filename:
            # This part is an attachment.
            if should_extract_attachment(part):
                link = save_attachment(part, email_date_str, simulation)
                if link:
                    attachment_links.append(link)
            else:
                # Keep attachments that don't meet extraction criteria.
                keep_parts.append(part)
        else:
            # If there is no filename, assume it's a body (text) part.
            body_parts.append(part)

    # Choose a single body part: Prefer "text/plain" if available.
    selected_body = None
    for part in body_parts:
        if part.get_content_type() == "text/plain":
            selected_body = part
            break
    if not selected_body and body_parts:
        selected_body = body_parts[0]

    # Assemble the new email.
    if selected_body:
        new_email.attach(selected_body)
    # Attach any attachments that should be kept intact.
    for part in keep_parts:
        new_email.attach(part)
    # If any attachments were extracted, add a summary text part with links.
    if attachment_links:
        links_text = "\n\n[Attachments extracted and stored separately:]\n" + "\n".join(attachment_links)
        new_email.attach(MIMEText(links_text, "plain"))
    
    return new_email.as_bytes()