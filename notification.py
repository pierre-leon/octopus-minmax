from apprise import Apprise
import config
from datetime import datetime

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

def send_notification(message, title="", error=False, batchable=True, image_path=None):
    """Sends a notification using Apprise.

    Args:
        message (str): The message to send.
        title (str, optional): The title of the notification.
        error (bool, optional): Whether the message is a stack trace. Defaults to False.
        batchable (bool, optional): Whether the message can be batched.
        image_path (str, optional): path to image
    """
    print(message)

    apprise = get_apprise()

    if not apprise:
        print("No notification services configured. Check config.NOTIFICATION_URLS.")
        return

    if error:
        message = f"```py\n{message}\n```"


    if config.BATCH_NOTIFICATIONS and batchable:
        notifications.append(message)
    else:
        if image_path:
            apprise.notify(body=message, title=title, attach=image_path)
        else:
            apprise.notify(body=message, title=title)

def send_batch_notification():
    now = datetime.now()
    title = now.strftime(f"Octopus MinMax Results - %a %d %b {config.EXECUTION_TIME if not config.ONE_OFF_RUN else now.strftime('%H:%M:%S')}")
    get_apprise().notify(body=batch_message(), title=title)

    # Clear all notifications
    global notifications
    notifications = []


