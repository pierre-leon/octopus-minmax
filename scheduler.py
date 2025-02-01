# Get execution time from environment variable
import os
import time
from datetime import datetime

from main import run_tariff_compare

EXECUTION_TIME = os.getenv("EXECUTION_TIME", "23:00")  # Default to 11PM

# Track last execution date to ensure we only run once per day
last_execution_date = None

print(f"Welcome to Octopus MinMax Bot. I will run your comparisons at {EXECUTION_TIME}")

while True:
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    current_date = now.date()

    if current_time == EXECUTION_TIME and last_execution_date != current_date:
        print(f"Executing tariff comparison at {current_time}...")
        last_execution_date = current_date
        run_tariff_compare()

    time.sleep(30)  # Check time every 30 seconds
