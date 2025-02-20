import time
from datetime import datetime
import random
import config
from main import run_tariff_compare

# Track last execution date to ensure we only run once per day
last_execution_date = None

if config.ONE_OFF_RUN:
    print(f"Welcome to Octopus MinMax Bot. Executing a one off comparison.")
    run_tariff_compare()
else:
    print(f"Welcome to Octopus MinMax Bot. I will run your comparisons at {config.EXECUTION_TIME}")

    while True:
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        current_date = now.date()

        if current_time == config.EXECUTION_TIME and last_execution_date != current_date:
            print(f"Executing tariff comparison at {current_time}...")
            last_execution_date = current_date
            time.sleep(random.randint(10,600)) #10 Sec - 10 Min Random Delay to prevent all users attempting to access API at same time
            run_tariff_compare()

        time.sleep(30)  # Check time every 30 seconds
