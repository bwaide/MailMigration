
# IMAP Email Migration Script
A Python-based email migration tool designed to migrate emails from a Gmail inbox (or other IMAP sources) to another IMAP mailbox. The script is highly configurable and extensible, featuring folder mapping, attachment extraction (with external storage and link replacement), checkpointing for restartability, and detailed logging and statistics.

![Starting a migration](https://waide.de/public/Mail_Migration.gif)
---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [.env File](#env-file)
- [config.json](#configjson)
- [Usage](#usage)
- [Simulation Mode](#simulation-mode)
- [Live Mode](#live-mode)
- [Folder Mapping & Label Translation](#folder-mapping--label-translation)
- [Attachment Extraction](#attachment-extraction)
- [Checkpointing and Resuming](#checkpointing-and-resuming)
- [Logging and Statistics](#logging-and-statistics)
- [Error Handling and Reconnection](#error-handling-and-reconnection)
- [Extensibility](#extensibility)
- [License](#license)

---

## Overview

This migration script uses IMAP to fetch emails from a source (typically Gmail) and appends them into a destination mailbox. It preserves metadata such as flags, internal dates, and folder structure. Additionally, the script includes features for:

-  **Folder mapping:** Converting Gmail’s label-based folder structure to a traditional IMAP folder structure.

-  **Attachment extraction:** Optionally extracting attachments that match certain criteria (file type and size), storing them externally, and replacing the attachments in the migrated email with file links.

-  **Checkpointing:** Saving progress to resume migration if the process is interrupted.

-  **Statistics collection:** Recording various metrics (e.g., number of emails per sender or folder).

-  **Robust error handling and reconnection:** Automatically reconnecting if the IMAP connection is lost.

-  **Detailed logging:** Logging output to both console (INFO level) and a file (DEBUG level).

---

## Features

**Folder Mapping:**

- Uses a mapping function to translate Gmail labels to destination folder names.

- Prepares missing destination folders automatically based on the source structure.

**Attachment Extraction:**

- Extracts attachments of specific file types and sizes.

- Saves extracted attachments in a structured folder hierarchy (e.g., organized by month based on email sent date).

- Replaces attachments in the migrated email with a file:// link.

**Checkpointing & Resume:**

- Automatically saves progress (including counters and last processed email index) to a JSON file.

- Resumes migration from the last checkpoint if the script is interrupted.


**Statistics Collection (Expandable):**

- Uses helper functions (e.g. `add_statistic()`) to record information such as file extensions, source folders, and senders.

- Stores statistics in a JSON file for later analysis.


**Robust Logging:**

- Logs are written to a file and INFO-level messages are also printed to the console.

- Logs include details about folder mapping, email processing, reconnections, and errors.


**Error Handling & Reconnection:**

- Automatically reconnects on connection failures using exponential backoff.

- Handles CTRL+C gracefully, performing cleanup before exit.

---

## Prerequisites

**Python 3.7+**

- The following Python modules (most are part of the standard library):

-  `imaplib`

-  `email`

-  `json`

-  `os`

-  `time`

-  `base64`

-  `hashlib`

-  `argparse`

-  `shlex`

-  `logging`

**Third-party modules:**

-  `python-dotenv` (for loading the `.env` file)

-  `tqdm` (for progress bars)

-  `python-dateutil` (for date parsing)


Install third-party modules via pip:

```bash

pip  install  python-dotenv  tqdm  python-dateutil

```

Alternative

```bash

pip  install  -r  requirements.txt

```

  

# Installation

  

**Clone the Repository:**

```bash

git  clone  https://github.com/bwaide/MailMigration.git

cd  mailmigration

```

  

**Set Up a Virtual Environment (Recommended):**

```bash
python  -m  venv  venv
source  venv/bin/activate  # On Windows: venv\Scripts\activate
```

  

**Install Dependencies:**
```bash
pip  install  -r  requirements.txt
```

## Configuration

The migration script is configured via environment variables (loaded from a `.env` file) and a JSON configuration file (`config.json`).

### GMail Account
Google doesn't allow login via IMAP with your user password for security reasons. You therefore have to create an Application password to be used just for the migration. It is strongly advised to delete the app password after the migration is done.
You can create the Application password here:
https://myaccount.google.com/apppasswords

_Note:_ You have to have Two-Factor-Authentication (2FA) turned on to be able to create application passwords.

### .env File

Create a `.env` file (or rename the provided `.env_template` to `.env`) with the following variables:

```ini
SOURCE_IMAP_SERVER=imap.gmail.com
SOURCE_EMAIL=yourgmail@example.com
SOURCE_PASSWORD=yourpassword
DEST_IMAP_SERVER=imap.destination.com
DEST_EMAIL=yourdest@example.com
DEST_PASSWORD=yourdestpassword
```

### config.json

The configuration file contains global settings and module-specific settings. Pay attention to the `root_folder`, as this name differs between different locales.
Example configuration:

```json
{
  "global": {
    "folder_mapping": {
      "Inbox": "INBOX",
      "Gesendet": "Gesendete Objekte",
      "Sent Mail": "Gesendete Objekte",
      "Sent": "Gesendete Objekte",
      "Alle Nachrichten": "Archive",
      "All Mail": "Archive",
      "Important": "INBOX",
      "Markiert": "INBOX",
      "Starred": "INBOX",
      "Wichtig": "INBOX",
      "Papierkorb": null,
      "Trash": null,
      "Spam": null,
      "Entwürfe": null,
      "Drafts": null,
      "Draft": null
    },
    "archive_folder": "Archive",
    "folder_prefix": "INBOX.",
    "log_file": "migration.log",
    "root_folder": "[Gmail]/All Mail",
    "debug_delay": 0.0,
    "labels_as_flagged": [
      "Important",
      "[Gmail]/Important",
      "Starred",
      "[Gmail]/Starred"
    ]
  },
  "extract_attachments": {
    "enabled": true,
    "attachment_whitelist": [".pdf", ".zip", ".docx", ".xlsx"],
    "max_attachment_size": 10240,
    "external_storage_path": "/Users/bwaide/Documents/Development/GoogleMigration/downloads",
    "storage_url": "file:///Users/bwaide/Documents/Development/GoogleMigration/downloads"
  }
}
```
_Note:_ You can expand this configuration with additional modules or plugins as needed.

----------

## Usage

### Command-Line Arguments

Run the script from the command line. It supports a simulation mode:

-   **Simulation Mode:**  
    Runs the migration without actually transferring emails. Check for warnings and errors in `migration.log` afterwards. Use the output in `statistics.json` to adjust the configuration, especially the folder mapping and settings for attachment extraction.
    
```bash
    python migrate.py --simulate` 
```
    
-   **Live Mode:**  
    Runs the migration for real. You will be prompted to confirm before actual migration begins.
    
```bash
    python migrate.py
```    

_Note:_ For larger mailboxes the migration can take hours. From my experience running this script on a laptop performs at roughly 2 - 4 mails/second. For mailboxes with 10,000 mails this means 1 hour.

----------

## Folder Mapping & Label Translation

The script converts Gmail’s label-based folder structure into a destination folder structure using a centralized mapping function.

-   **Mapping Rules:**
    
    1.  If the input contains `[Gmail]/Inbox` (or cleans to "INBOX"), the destination is `"INBOX"`.
    2.  If a label exists in the global `folder_mapping` (from `config.json`), that value is used.
    3.  Otherwise, the script chooses the most specific (deepest) label and prepends the global `folder_prefix`.
    4.  If no label is available, it falls back to `archive_folder`.
-   **Implementation:**  
    The function `map_labels_to_destination(gmail_labels)` is used throughout the script for both folder creation and email migration. This ensures consistency.
    

----------

## Attachment Extraction

If enabled in the configuration, the script will:

1.  **Examine each email for attachments.**
2.  **For attachments that meet criteria (file extension, size):**
    -   Save them to an external location.
    -   Organize them into month-based subfolders (e.g., `"2023_10"`).
    -   Replace the attachment in the email with a link starting with `file://` pointing to the saved file.
3.  **For attachments that don’t meet the criteria:**  
    They are kept as part of the email.

----------

## Checkpointing and Resuming

-   **Checkpoint File:**  
    The script saves its progress (last processed email index, total size, and skipped count) to a file (default: `migration_checkpoint.json`).
    
-   **Resumption:**  
    On start, the script loads the checkpoint and resumes from the last processed email.
    
-   **Automatic Cleanup:**  
    The checkpoint file is automatically deleted if the migration completes successfully.
    

----------

## Logging and Statistics

-   **Logging:**  
    Logging is configured to write DEBUG-level messages to a file and INFO-level messages to the console.  
    Log messages include details about folder mapping, email processing, errors, and reconnections.
    
-   **Statistics (Expandable):**  
    The script can be extended to collect statistics (for example, counts of emails per sender, file extensions, etc.) via helper functions like `add_statistic(category, key, amount)`.
    

----------

## Error Handling and Reconnection

-   The script handles `KeyboardInterrupt` (CTRL+C) gracefully and performs cleanup.
-   If an IMAP connection is lost (e.g., due to a system error), the script automatically attempts to reconnect using exponential backoff.
-   In case of an unexpected crash, the checkpoint file allows the migration to resume without duplicating emails.

----------

## Extensibility

The configuration system is modular, with a nested JSON structure supporting multiple modules (global settings and module-specific settings such as for attachment extraction).  
You can extend the system by adding new sections to the JSON config and writing corresponding helper functions.

----------

## License

MIT License
See https://github.com/bwaide/MailMigration/blob/main/LICENSE for details.

----------

## Contact

Björn Waide
Contact me at mailto:bjoern.waide@net-positive-ventures.com
