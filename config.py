import os

# Add your stuff here
API_KEY = "" or os.environ["API_KEY"]
# Your Octopus Energy account number. Starts with A-
ACC_NUMBER = "" or os.environ["ACC_NUMBER"]
BASE_URL = "https://api.octopus.energy/v1" or os.environ["BASE_URL"]
DISCORD_WEBHOOK = "" or os.environ["DISCORD_WEBHOOK"]
OCTOPUS_LOGIN_EMAIL = "" or os.environ["OCTOPUS_LOGIN_EMAIL"]
OCTOPUS_LOGIN_PASSWD = "" or os.environ["OCTOPUS_LOGIN_PASSWD"]
