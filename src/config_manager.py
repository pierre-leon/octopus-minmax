import threading
import re
import config

_config_lock = threading.Lock()

def get_config():
    """Get current configuration as dictionary (thread-safe)"""
    with _config_lock:
        return {
            'api_key': config.API_KEY,
            'acc_number': config.ACC_NUMBER,
            'base_url': config.BASE_URL,
            'execution_time': config.EXECUTION_TIME,
            'early_run': config.EARLY_RUN,
            'early_switch_multiplier': config.EARLY_SWITCH_MULTIPLIER,
            'switch_threshold': config.SWITCH_THRESHOLD,
            'tariffs': config.TARIFFS,
            'one_off_run': config.ONE_OFF_RUN,
            'one_off_executed': config.ONE_OFF_EXECUTED,
            'dry_run': config.DRY_RUN,
            'notification_urls': config.NOTIFICATION_URLS,
            'batch_notifications': config.BATCH_NOTIFICATIONS,
            'send_comparison_chart': config.SEND_COMPARISON_CHART,
        }


def update_config(new_values):
    """Update configuration at runtime (called by web UI) - thread-safe"""
    with _config_lock:
        previous_one_off = config.ONE_OFF_RUN

        if 'api_key' in new_values and new_values['api_key']:
            config.API_KEY = new_values['api_key']
        if 'acc_number' in new_values and new_values['acc_number']:
            config.ACC_NUMBER = new_values['acc_number']
        if 'base_url' in new_values and new_values['base_url']:
            config.BASE_URL = new_values['base_url']
        if 'execution_time' in new_values:
            config.EXECUTION_TIME = new_values['execution_time']
        if 'early_run' in new_values:
            config.EARLY_RUN = str(new_values['early_run']).lower() in ['true', '1', 'yes', 'on']
        else:
            config.EARLY_RUN = False
        if 'early_switch_multiplier' in new_values:
            config.EARLY_SWITCH_MULTIPLIER = int(new_values['early_switch_multiplier'])
        if 'switch_threshold' in new_values:
            config.SWITCH_THRESHOLD = int(new_values['switch_threshold'])
        if 'tariffs' in new_values:
            config.TARIFFS = new_values['tariffs']
        if 'one_off_run' in new_values:
            config.ONE_OFF_RUN = str(new_values['one_off_run']).lower() in ['true', '1', 'yes', 'on']
        else:
            config.ONE_OFF_RUN = False
        if 'dry_run' in new_values:
            config.DRY_RUN = str(new_values['dry_run']).lower() in ['true', '1', 'yes', 'on']
        else:
            # Checkbox not checked means False
            config.DRY_RUN = False
        if 'notification_urls' in new_values:
            config.NOTIFICATION_URLS = new_values['notification_urls']
        if 'batch_notifications' in new_values:
            config.BATCH_NOTIFICATIONS = str(new_values['batch_notifications']).lower() in ['true', '1', 'yes', 'on']
        else:
            # Checkbox not checked means False
            config.BATCH_NOTIFICATIONS = False
        if 'send_comparison_chart' in new_values:
            config.SEND_COMPARISON_CHART = str(new_values['send_comparison_chart']).lower() in ['true', '1', 'yes', 'on']
        else:
            config.SEND_COMPARISON_CHART = False

        if config.ONE_OFF_RUN and not previous_one_off:
            config.ONE_OFF_EXECUTED = False



def validate_config(config_dict):
    """Validate config values before saving"""
    errors = []

    # Validate execution_time format (HH:MM)
    if 'execution_time' in config_dict:
        if not re.match(r'^([0-1][0-9]|2[0-3]):[0-5][0-9]$', config_dict['execution_time']):
            errors.append("Execution time must be in HH:MM format (00:00 to 23:59)")

    # Validate switch_threshold is positive integer
    if 'switch_threshold' in config_dict:
        try:
            val = int(config_dict['switch_threshold'])
            if val < 0:
                errors.append("Switch threshold must be positive")
        except ValueError:
            errors.append("Switch threshold must be a number")

    if 'early_switch_multiplier' in config_dict:
        try:
            val = int(config_dict['early_switch_multiplier'])
            if val < 1:
                errors.append("Early switch multiplier must be at least 1")
        except ValueError:
            errors.append("Early switch multiplier must be a number")

    return errors
