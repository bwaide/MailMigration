#!/usr/bin/env python3
import imaplib
import re
import sys
import base64
import time
import os
import json
import argparse
from dotenv import load_dotenv
from email import message_from_bytes
from tqdm import tqdm  # Progress bar
import shlex
import logging

def load_config(config_path="config.json"):
    with open(config_path, "r") as file:
        return json.load(file)

config = load_config()

# -------------------------------
# Logging Setup (as before)
# -------------------------------
log_file = config.get("log_file", "migration.log")  # see below for config loading
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s",
                              datefmt="%Y-%m-%d %H:%M:%S")
file_handler.setFormatter(formatter)
#console_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# -------------------------------
# Configuration Loading
# -------------------------------
if not load_dotenv(override=True):
    print("ERROR: No credentials found in .env file. Please rename '.env_template' to '.env'.")
    sys.exit(0)

SOURCE_IMAP_SERVER = os.getenv("SOURCE_IMAP_SERVER")
SOURCE_EMAIL = os.getenv("SOURCE_EMAIL")
SOURCE_PASSWORD = os.getenv("SOURCE_PASSWORD")
DEST_IMAP_SERVER = os.getenv("DEST_IMAP_SERVER")
DEST_EMAIL = os.getenv("DEST_EMAIL")
DEST_PASSWORD = os.getenv("DEST_PASSWORD")

CHECKPOINT_FILE = "migration_checkpoint.json"

print(SOURCE_EMAIL)

# These keys come from the config file
FOLDER_MAPPING = config["folder_mapping"]
DEFAULT_ARCHIVE_FOLDER = config["archive_folder"]
FOLDER_PREFIX = config["folder_prefix"] 
ROOT_FOLDER = config["root_folder"] 
DEBUG_DELAY = config["debug_delay"]

# Global variable defining labels that should be treated as "\Flagged" in IMAP
LABELS_AS_FLAGGED = config["labels_as_flagged"]


def load_checkpoint():
    """Loads the last processed email index and counters from a checkpoint file."""
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r") as file:
                checkpoint_data = json.load(file)
                return (
                    checkpoint_data.get("last_processed_index", 0),
                    checkpoint_data.get("total_size_mb", 0),
                    checkpoint_data.get("skipped", 0)
                )
        except json.JSONDecodeError:
            logger.warning("⚠️ Checkpoint file is corrupted. Starting from the beginning.")

    return 0, 0, 0  # Start from the beginning if no valid checkpoint exists

def save_checkpoint(index, total_size_mb, skipped):
    """Saves the last successfully processed email index and counters to a checkpoint file."""
    with open(CHECKPOINT_FILE, "w") as file:
        json.dump({
            "last_processed_index": index,
            "total_size_mb": total_size_mb,
            "skipped": skipped
        }, file)

def delete_checkpoint():
    """Deletes the checkpoint file upon successful migration completion."""
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        logger.info("✅ Migration completed successfully. Checkpoint file deleted.")

def translate_labels_to_flags(gmail_labels):
    """
    Translates special Gmail labels into IMAP flags.
    
    If any label in LABELS_AS_FLAGGED is found in the email's labels, 
    the \Flagged IMAP status is added.
    
    Args:
        gmail_labels (list): List of Gmail labels applied to an email.
    
    Returns:
        list: Updated list of IMAP flags.
    """
    flags = []
    
    # Check if any of the special labels exist in the Gmail labels
    if any(label in LABELS_AS_FLAGGED for label in gmail_labels):
        flags.append("\\Flagged")  # Mark as important in IMAP

    return flags

# Consolidated mapping function that implements all the rules in one place.
def map_labels_to_destination(gmail_labels):
    """
    Given a Gmail folder name or a list of Gmail labels, returns the destination folder name.

    Rules:
      1. If "[Gmail]/Inbox" is present or any label cleans to "INBOX", return "INBOX".
      2. Otherwise, if any cleaned label exists in FOLDER_MAPPING with a non-null value, return that.
      3. Otherwise, if any labels are present, choose the one with the highest depth and prepend FOLDER_PREFIX (with "/" replaced by ".").
      4. Otherwise, return DEFAULT_ARCHIVE_FOLDER.
    """
    # Ensure we are working with a list.
    if isinstance(gmail_labels, str):
        gmail_labels = [gmail_labels]

    # Rule 0: Check for [Gmail]
    if "[Gmail]" in gmail_labels:
        return None
     
    # Rule 1: Check for Inbox.
    if "[Gmail]/Inbox" in gmail_labels or any(clean_gmail_label(lbl).upper() == "INBOX" for lbl in gmail_labels):
        return "INBOX"

    # Clean the labels.
    cleaned_labels = [clean_gmail_label(lbl) for lbl in gmail_labels]

    # Rule 2: Check predefined mapping.
    for label in cleaned_labels:
        if label in FOLDER_MAPPING:
            return FOLDER_MAPPING[label]

    # Rule 3: If there are any cleaned labels, pick the one with the highest depth.
    if cleaned_labels:
        # The label with the most "/" characters is considered the most specific.
        deepest = sorted(cleaned_labels, key=lambda x: x.count("/"), reverse=True)[0]
        # Build the destination folder using the folder prefix; replace "/" with "."
        return f"{FOLDER_PREFIX}{deepest}".replace("/", ".")

    # Rule 4: Fallback.
    return DEFAULT_ARCHIVE_FOLDER


# Example helper to clean Gmail labels.
def clean_gmail_label(label):
    """
    Removes the "[Gmail]/" prefix and any leading backslashes from a Gmail label.
    """
    label = label.replace("[Gmail]/", "")
    return label.lstrip("\\")

# -------------------------------
# Other Utility Functions (encoding, connection, etc.)
# (Keep these largely unchanged)
# -------------------------------
def decode_imap_utf7(s):
    s = s.replace('&-', '&')
    def decode_match(m):
        b64 = m.group(1).replace(',', '/')
        padding = '=' * ((4 - len(b64) % 4) % 4)
        b64 += padding
        decoded_bytes = base64.b64decode(b64)
        return decoded_bytes.decode('utf-16-be')
    decoded = re.sub(r'&([^-]+)-', decode_match, s)
    return decoded

def encode_imap_utf7(s):
    s = s.replace('&', '&-')
    def encode_match(m):
        text = m.group(0)
        b = text.encode('utf-16-be')
        b64 = base64.b64encode(b).decode('ascii').replace('/', ',').rstrip('=')
        return '&' + b64 + '-'
    encoded = re.sub(r'([\u0080-\uffff]+)', encode_match, s)
    if " " in encoded or any(ord(char) > 127 for char in encoded):
        encoded = f'"{encoded}"'
    return encoded

def encode_folder(name):
    try:
        encoded_name = encode_imap_utf7(name)
        encoded_name = encoded_name.replace("/", ".")
        return encoded_name
    except Exception as e:
        logger.error(f"Error encoding folder name '{name}': {e}")
        return name

def reconnect_imap(server, email, password, max_retries=5):
    """
    Reconnects to the IMAP server with exponential backoff in case of a failure.
    """
    attempt = 0
    while attempt < max_retries:
        try:
            logger.info(f"🔄 Attempting to reconnect to {server} (Attempt {attempt + 1}/{max_retries})...")
            conn = imaplib.IMAP4_SSL(server)
            conn.login(email, password)
            logger.info(f"Reconnected successfully to {server}")
            return conn
        except imaplib.IMAP4.abort as e:
            logger.warning(f"Reconnect attempt {attempt + 1} failed: {e}")
            time.sleep(2 ** attempt)  # Exponential backoff
            attempt += 1
    logger.error(f"Could not reconnect to {server} after {max_retries} attempts. Exiting.")
    sys.exit(1)

def connect_imap(server, email_addr, password):
    try:
        logger.info(f"Login to {server}...")
        conn = imaplib.IMAP4_SSL(server)
        conn.login(email_addr, password)
        return conn
    except Exception as e:
        logger.error(f"Failed to connect/login to {server} for {email_addr}: {e}")
        sys.exit(1)

def list_folders(conn):
    typ, data = conn.list()
    if typ != 'OK':
        logger.error("Error listing folders")
        sys.exit(1)
    folders = []
    for line in data:
        if isinstance(line, bytes):
            line = line.decode('utf-8')
        m = re.search(r' "([^"]+)"$', line)
        if m:
            folder = m.group(1)
            try:
                folder_decoded = decode_imap_utf7(folder)
            except Exception:
                folder_decoded = folder
            folders.append(folder_decoded)
    return folders

def create_folder_if_not_exists(conn, folder_name, simulation=False):
    if folder_name.upper() == "INBOX":
        return
    encoded_folder = encode_folder(folder_name)
    logger.debug(f"Creating folder: {folder_name} ({encoded_folder})")
    if not simulation:
        typ, data = conn.create(encoded_folder)
        if typ != 'OK':
            error_message = " ".join([d.decode("utf-8") if isinstance(d, bytes) else str(d) for d in data])
            if "ALREADYEXISTS" in error_message:
                logger.debug(f"Folder '{folder_name}' already exists, skipping creation.")
            else:
                logger.error(f"Failed to create folder {folder_name}: {error_message}")
        else:
            typ, data = conn.subscribe(encoded_folder)
            if typ == 'OK':
                logger.debug(f"Folder '{folder_name}' subscribed successfully.")
            else:
                logger.debug(f"Could not subscribe to folder '{folder_name}'.")

def convertDate(date):
    from dateutil import parser
    date_obj = parser.parse(date)
    return imaplib.Time2Internaldate(date_obj.timestamp())

def convertFlags(flags):
    # Ensure flags are unique
    flags = list(set(flags)) 
    formatted_flags = " ".join(flags)
    return formatted_flags

def extract_gmail_labels(msg_data):
    labels = []
    for response_part in msg_data:
        if isinstance(response_part, tuple):
            header = response_part[0].decode(errors="ignore")
            match = re.search(r'X-GM-LABELS \((.*?)\)', header)
            if match:
                raw_labels = match.group(1)
                labels = shlex.split(raw_labels)
                break
    return labels

# -------------------------------
# Centralized Migration Function
# -------------------------------
def migrate_all(source_conn, dest_conn, simulation=False):
    source_folder = f'"{ROOT_FOLDER}"'
    logger.info(f"\n🔍 Scanning {source_folder}...")

    current_email, total_size_mb, skipped_emails = load_checkpoint()

    try:
        status, _ = source_conn.select(source_folder, readonly=True)
        if status != 'OK':
            logger.error(f"ERROR: Cannot select source folder {source_folder}.")
            return 0, 0, 0

        typ, data = source_conn.search(None, 'ALL')
        if typ != 'OK':
            logger.error(f"ERROR: Failed to search messages in folder {source_folder}")
            return 0, 0, 0

        msg_nums = data[0].split()
        total_emails = len(msg_nums)
        logger.info(f"📩 Found {total_emails} emails in {source_folder}.")
        if current_email > 0:
            logger.info(f"🔄 Resuming from email {current_email + 1}...")
        
        # Initialize tqdm progress bar
        progress_bar = tqdm(total=total_emails, desc="Processing emails", unit="email")

        while current_email < len(msg_nums):
            num = msg_nums[current_email]
            try:
                typ, msg_data = source_conn.fetch(num, '(FLAGS X-GM-LABELS INTERNALDATE RFC822.SIZE RFC822)')
                if typ != 'OK':
                    logger.error(f"ERROR: Failed to fetch message {num} in {source_folder}")
                    skipped_emails += 1
                    current_email += 1
                    progress_bar.update(1) 
                    continue

                raw_msg, flags, internal_date, email_size = None, [], None, 0
                labels = extract_gmail_labels(msg_data)

                for response_part in msg_data:
                    if isinstance(response_part, bytes):
                        response_text = response_part.decode('utf-8', errors='ignore')
                    elif isinstance(response_part, tuple):
                        response_text = response_part[0].decode('utf-8', errors='ignore')
                        raw_msg = response_part[1]

                    size_match = re.search(r'RFC822.SIZE (\d+)', response_text)
                    if size_match:
                        email_size = int(size_match.group(1))
                        total_size_mb += email_size

                    flag_match = re.search(r'FLAGS \((.*?)\)', response_text)
                    flags = flag_match.group(1).split() if flag_match else []

                    # Translate Gmail labels into IMAP flags
                    flags.extend(translate_labels_to_flags(labels))

                    date_match = re.search(r'INTERNALDATE "([^"]+)"', response_text)
                    if date_match:
                        internal_date = date_match.group(1)
                    else:
                        internal_date = time.strftime('%d-%b-%Y %H:%M:%S +0000', time.gmtime())

                if raw_msg:
                    formatted_internal_date = convertDate(internal_date)
                    formatted_flags = convertFlags(flags)
                
                    destination_folder = map_labels_to_destination(labels)

                    if (destination_folder is None):
                        logger.debug(f"WARNING: Skipping mail #{num.decode()} from labels {labels} due to missing target folder configuration.")
                        skipped_emails += 1
                        current_email += 1
                        progress_bar.update(1) 
                        continue
                    
                    logger.debug(f"Migrating mail #{num.decode()} from labels {labels} to destination folder '{destination_folder}'...")
                    if not simulation:
                        encoded_destination_folder = encode_folder(destination_folder)
                        res = dest_conn.append(encoded_destination_folder, formatted_flags, formatted_internal_date, raw_msg)
                        if res[0] != 'OK':
                            skipped_emails += 1
                            logger.debug(f"ERROR: Failed to append message {num} to folder {destination_folder}")
                else:
                    skipped_emails += 1
                    logger.debug(f"WARNING: No raw message found for mail #{num}")

                progress_bar.update(1)
                
                # 🛑 **Save checkpoint every 100 emails**
                if current_email % 100 == 0:
                    save_checkpoint(current_email, total_size_mb, skipped_emails)

                # **Reduce IMAP request rate** (prevent timeouts/rate limiting)
                time.sleep(DEBUG_DELAY)  # Adjust delay if needed

                current_email += 1

            except imaplib.IMAP4.abort as e:
                logger.error(f"IMAP connection lost during migration (mail #{num}). Error: {e}")
                source_conn = reconnect_imap(SOURCE_IMAP_SERVER, SOURCE_EMAIL, SOURCE_PASSWORD)
                dest_conn = reconnect_imap(DEST_IMAP_SERVER, DEST_EMAIL, DEST_PASSWORD)

                # Re-select the folder after reconnecting
                source_conn.select(source_folder, readonly=True)

        progress_bar.close()

        # Delete checkpoint on successful completion
        delete_checkpoint()

        total_size_mb = round(total_size_mb / (1024 * 1024), 2)
    except Exception as e:  # Catch any unexpected crash
        logger.error(f"🚨 Unexpected error: {e}. Saving checkpoint before exiting.")
        save_checkpoint(current_email, total_size_mb, skipped_emails)
        raise  # Re-raise the exception so it can be handled by the main script
    
    return total_emails, total_size_mb, skipped_emails

# -------------------------------
# Now update your get_folder_mapping_info to use the consolidated function.
def get_folder_mapping_info(source_conn, dest_conn):
    """
    Retrieves the source folder structure and, for each source folder,
    uses map_labels_to_destination() to determine the destination folder.
    
    Compares the computed destination folder with the destination's actual folder list,
    returning a dictionary where each source folder maps to:
       {"destination": <dest folder>, "missing": <True|False>}
    """
    source_folders = list_folders(source_conn)
    logger.debug(f"Source folders: {source_folders}")
    
    dest_folders = set(list_folders(dest_conn))
    logger.debug(f"Destination folders: {dest_folders}")
    
    mapping_info = {}
    for src in source_folders:
        # Get the destination folder using the consolidated function.
        dest = map_labels_to_destination([src])
        # Skip folders that explicitly map to null.
        if dest is None:
            logger.debug(f"Skipping source folder '{src}' because its mapping is set to null.")
            continue
        
        # Assume INBOX always exists.
        missing = (dest.upper() != "INBOX") and (dest not in dest_folders)
        mapping_info[src] = {"destination": dest, "missing": missing}
    return mapping_info


def print_folder_mapping_info(mapping_info):
    """
    Prints the source-to-destination folder mapping.
    An asterisk (*) is appended to destination folders that are missing on the destination.
    """
    logger.info("\n=== Folder Mapping ===")
    logger.info(f"{'Source Folder':<30} → {'Destination Folder'}")
    logger.info("-" * 50)
    for src, info in sorted(mapping_info.items()):
        marker = "*" if info["missing"] else ""
        logger.info(f"{src:<30} → {info['destination']}{marker}")
    logger.info("-" * 50)
    logger.info("Destination folder with an asterisk (*) at the end are missing and will be created")


def prepare(source_conn, dest_conn, simulation):
    
    # Get the consolidated folder mapping information
    mapping_info = get_folder_mapping_info(source_conn, dest_conn)
    print_folder_mapping_info(mapping_info)

    # Create missing folders on the destination
    for _, info in mapping_info.items():
        if info["missing"]:
            create_folder_if_not_exists(dest_conn, info["destination"], simulation=simulation)


def migrate(source_conn, dest_conn, simulation):
    # Create destination folders based on the consolidated logic.
    # For each source folder (or label) we might create a destination folder.
    total_emails, total_size_mb, skipped = migrate_all(source_conn, dest_conn, simulation=simulation)

    logger.info("\n=== FINAL SUMMARY ===")
    logger.info(f"Total emails: {total_emails}")
    logger.info(f"Skipped emails: {skipped}\t(Check migration log for details)")
    logger.info(f"Total size: {total_size_mb} MB")

def prepare_and_migrate(simulation):
    logger.info("\n" + ("SIMULATION MODE: Scanning mailbox" if simulation else "LIVE MODE: Starting migration"))
    
    source_conn = connect_imap(SOURCE_IMAP_SERVER, SOURCE_EMAIL, SOURCE_PASSWORD)
    dest_conn = connect_imap(DEST_IMAP_SERVER, DEST_EMAIL, DEST_PASSWORD)
    
    prepare(source_conn, dest_conn, simulation)

    migrate(source_conn, dest_conn, simulation)
    
    try:
        source_conn.logout()
        dest_conn.logout()
    except imaplib.IMAP4.abort as e:
        logger.debug("Logout failed probably due to inactivty during simulation. Should be no issue.")

def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="IMAP Email Migration Script")
    parser.add_argument("--simulate", action="store_true", help="Run in simulation mode (no actual migration)")
    return parser.parse_args()

def main():
    args = parse_args()
    simulation = args.simulate

    if not simulation:
        confirm = input("\n⚠️  WARNING: You are about to start the actual migration. This will transfer emails to the destination mailbox.\nDo you want to continue? (yes/no): ").strip().lower()
        
        if confirm not in ["yes", "y"]:
            logger.info("Migration aborted. Use command line argument '-simulate' to start a read-only simulation.")
            sys.exit(0)  # Exit the script safely
    
    prepare_and_migrate(simulation)

if __name__ == '__main__':
    main()