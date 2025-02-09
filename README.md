# Installation
pip install tqdm

Copy .env_template to .env and fill out your credentials for source and destination IMAP server

Check config.json for the right mapping.

# Run
The following command runs a simulation, logging into both servers, checking the number of emails and total data volume to be migrated. Highly recommended to run the script first in simulation mode.

python migrate.py --simulate

If everything looks fine, run:
python migrate.py

Be aware: for larger mailboxes this might run hours.
