from apprise import Apprise

import atexit
import config
import signal
import sys

notifications = []

# FIXME this was existing code (refactored) but do we need to create a new object for each invocation?
def get_apprise():
    apprise = Apprise()

    if config.NOTIFICATION_URLS:
        for url in config.NOTIFICATION_URLS.split(','):
            apprise.add(url.strip())

    return apprise

def batch_message():
    return "\n".join(notifications)

def send_notification(message, title="", error=False):
    """Sends a notification using Apprise.

    Args:
        message (str): The message to send.
        title (str, optional): The title of the notification.
        error (bool, optional): Whether the message is a stack trace. Defaults to False.
    """
    print(message)

    apprise = get_apprise()

    if not apprise:
        print("No notification services configured. Check config.NOTIFICATION_URLS.")
        return

    if error:
        message = f"```py\n{message}\n```"

    if config.BATCH_NOTIFICATIONS:
        notifications.append(message)
    else:
        apprise.notify(body=message, title=title)

def cleanup():
    """For cases where the script exits normally, use atexit"""
    print("Cleaning up before exit...")
    get_apprise().notify(body=batch_message(), title=config.BATCH_NOTIFICATIONS_TITLE)

atexit.register(cleanup)

def handle_exit(signal_received, frame):
    """Use the signal module to catch SIGINT (Ctrl+C)"""
    print("Caught Ctrl+C! Cleaning up...")
    get_apprise().notify(body=batch_message(), title=config.BATCH_NOTIFICATIONS_TITLE)
    sys.exit(0)  # Ensures normal exit

signal.signal(signal.SIGINT, handle_exit)

def handle_sigterm(signal_received, frame):
    """If running in a production environment (e.g., Docker, systemd), it may receive SIGTERM"""
    print("Received SIGTERM. Cleaning up...")
    get_apprise().notify(body=batch_message(), title=config.BATCH_NOTIFICATIONS_TITLE)
    sys.exit(0) # Ensures normal exit

signal.signal(signal.SIGTERM, handle_sigterm)


