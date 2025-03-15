import os

BOT_VERSION = "v0.6.0"
# Add your stuff here
API_KEY = os.getenv("API_KEY", "")
# Your Octopus Energy account number. Starts with A-
ACC_NUMBER = os.getenv("ACC_NUMBER", "")
BASE_URL = os.getenv("BASE_URL", "https://api.octopus.energy/v1")
# Comma-separated list of Apprise notification URLs
NOTIFICATION_URLS = os.getenv("NOTIFICATION_URLS", "")
EXECUTION_TIME = os.getenv("EXECUTION_TIME", "23:00")

# List of tariff IDs to compare
TARIFFS = os.getenv("TARIFFS", "go,agile,flexible")

# Whether to just run immediately and exit
ONE_OFF_RUN = os.getenv("ONE_OFF", "false") in ["true", "True", "1"]

# Whether to notify the user of a switch but not actually switch
DRY_RUN = os.getenv("DRY_RUN", "false") in ["true", "True", "1"]
