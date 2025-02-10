import os
import json

# Global dictionary to store statistics.
STATISTICS = {}

def add_statistic(category, key, amount=1):
    """
    Increments the count for a given key under a given category by 'amount'.
    
    If the category or key does not exist, they are created.
    
    For example:
      add_statistic("file_extensions", ".pdf", 1)
      add_statistic("source_folder", "Archive", 1)
      add_statistic("sender", "bjoern@waide.de", 1)
    """
    if category not in STATISTICS:
        STATISTICS[category] = {}
    if key not in STATISTICS[category]:
        STATISTICS[category][key] = 0
    STATISTICS[category][key] += amount

def save_statistics_file(statistics_file="statistics.json"):
    """
    Writes the STATISTICS dictionary to a JSON file with indentation.
    """
    try:
        with open(statistics_file, "w") as f:
            json.dump(STATISTICS, f, indent=4)
        print(f"Statistics saved to {statistics_file}")
    except Exception as e:
        print(f"ERROR: Could not save statistics to {statistics_file}: {e}")

def load_statistics_file(statistics_file="statistics.json"):
    """
    Loads the statistics from the given JSON file and pre-fills the global STATISTICS variable.
    If the file does not exist or an error occurs, STATISTICS remains an empty dict.
    
    Returns:
        None
    """
    global STATISTICS
    if os.path.exists(statistics_file):
        try:
            with open(statistics_file, "r") as f:
                loaded_stats = json.load(f)
            # You can choose to either replace STATISTICS or merge with the existing one.
            # Here we replace it:
            STATISTICS = loaded_stats
            print(f"Statistics loaded from {statistics_file}")
        except Exception as e:
            print(f"ERROR: Could not load statistics from {statistics_file}: {e}")
    else:
        STATISTICS = {}
        print(f"No statistics file found. Starting with an empty statistics dictionary.")

def format_statistics():
    """
    Returns a formatted string representation of the STATISTICS dictionary.
    
    For each category in STATISTICS, the keys are sorted in decreasing order
    by their associated count.
    """
    lines = []
    # Optionally, sort the categories alphabetically.
    for category, data in sorted(STATISTICS.items()):
        lines.append(f"Category: {category}")
        # Sort the items (key, count) in decreasing order by count.
        sorted_items = sorted(data.items(), key=lambda item: item[1], reverse=True)
        for key, count in sorted_items:
            lines.append(f"   {key}: {count}")
        lines.append("")  # Add an empty line between categories for readability

    return "\n".join(lines)