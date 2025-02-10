import json
import logging

def load_config(config_path="config.json"):
    with open(config_path, "r") as file:
        return json.load(file)

my_config = load_config()

def get_config(section, parameter, default):
    return my_config.get(section, {}).get(parameter, default)

# -------------------------------
# Logging Setup
# -------------------------------
log_file = get_config("general", "log_file", "migration.log")  # see below for config loading

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s",
                              datefmt="%Y-%m-%d %H:%M:%S")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.addHandler(console_handler)