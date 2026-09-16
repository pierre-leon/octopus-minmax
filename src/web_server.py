from flask import Flask, render_template, request, redirect, flash, Response
from functools import wraps
import config_manager
import config
import logging
import octopus_web
import web_session
from query_service import QueryService

logger = logging.getLogger('octobot.web_server')

app = Flask(__name__)
app.secret_key = 'octobot-tool'

def is_ingress_request():
    # Skip auth for ingress requests
    return bool(request.headers.get('X-Ingress-Path') or request.headers.get('X-Hassio-Ingress'))

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if is_ingress_request():
            return f(*args, **kwargs)
        auth = request.authorization
        if not auth or not (auth.username == config.WEB_USERNAME and auth.password == config.WEB_PASSWORD):
            return Response(
                'Authentication required',
                401,
                {'WWW-Authenticate': 'Basic realm="OctoBot Login Required"'}
            )
        return f(*args, **kwargs)
    return decorated


@app.route('/')
@require_auth
def index():
    """Homepage - Dashboard with navigation buttons"""
    return render_template('index.html', auth_status=web_session.public_status())


def _clean_cookie(raw: str) -> str:
    """Accept the cookie however it was copied: bare, name=value, or a header."""
    value = (raw or '').strip().strip('"').strip("'")
    if 'octosession=' in value:
        value = value.split('octosession=', 1)[1]
    return value.split(';', 1)[0].strip()


def _store_session(raw: str) -> None:
    cookie = _clean_cookie(raw)
    if not cookie:
        raise Exception('Paste the octosession cookie value.')

    # Ask Octopus before saving, so a bad paste fails here and not at 11pm.
    client = octopus_web.OctopusWebClient(cookie, config.ACC_NUMBER)
    session = client.check_session()
    if not session.get('isLoggedIn'):
        raise Exception(
            'Octopus does not recognise that session. Make sure you are logged in and copy the '
            'current octosession value.'
        )

    expires_at = web_session.assumed_expiry()
    web_session.save(cookie, expires_at, email=session.get('selectedAccount') or config.ACC_NUMBER)
    flash(
        f"Session accepted for account {session.get('selectedAccount') or config.ACC_NUMBER}. "
        f"Good until about {expires_at.strftime('%d/%m/%Y %H:%M UTC')}.",
        'success',
    )


@app.route('/auth', methods=['GET', 'POST'])
@require_auth
def auth_page():
    if request.method == 'POST':
        try:
            _store_session(request.form.get('octosession') or '')
        except Exception as e:
            logger.error(f"Storing Octopus session failed: {e}")
            flash(f'{e}', 'error')
        return redirect('auth')

    return render_template(
        'auth.html',
        status=web_session.public_status(),
        renewal_lead_days=config.SESSION_RENEWAL_LEAD_DAYS,
        lifetime_days=web_session.LIFETIME_DAYS,
    )


@app.route('/auth/logout', methods=['POST'])
@require_auth
def auth_logout():
    web_session.clear()
    QueryService.invalidate_token_cache()
    flash('Octopus session removed.', 'success')
    return redirect('auth')


@app.route('/config', methods=['GET', 'POST'])
@require_auth
def config_page():
    if request.method == 'POST':
        # Validate input
        errors = config_manager.validate_config(request.form.to_dict())
        if errors:
            for error in errors:
                flash(error, 'error')
        else:
            # Update config
            try:
                submitted_values = request.form.to_dict()
                logger.info(f"Config update submitted: {submitted_values}")

                config_manager.update_config(request.form.to_dict())

                new_config = config_manager.get_config()
                logger.info(f"Config updated successfully. New state: {new_config}")

                flash('Configuration updated successfully! (Will reset on container restart)', 'success')
            except Exception as e:
                flash(f'Error updating config: {str(e)}', 'error')
                logger.error(f"Config update failed: {e}")

        return redirect('config')

    current_config = config_manager.get_config()
    return render_template('config.html', config=current_config)


@app.route('/logs')
@require_auth
def logs():
    log_lines = tail_file('logs/octobot.log', None)  # None = read entire file
    log_entries = group_log_entries(log_lines)
    return render_template('logs.html', log_entries=log_entries)


def tail_file(filepath, n):
    """Read last n lines from file, or entire file if n is None"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            if n is None:
                return lines  # Return entire file
            return lines[-n:] if len(lines) > n else lines
    except FileNotFoundError:
        return ["Log file not found. The bot may not have started yet."]
    except Exception as e:
        logger.error(f"Error reading log file: {e}")
        return [f"Error reading log file: {str(e)}"]


def group_log_entries(log_lines):
    """Group log lines into entries based on timestamp pattern"""
    import re

    # Pattern matches timestamp
    timestamp_pattern = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')

    entries = []
    current_entry = []

    for line in log_lines:
        if timestamp_pattern.match(line):
            # New log entry starts
            if current_entry:
                entries.append(''.join(current_entry))
            current_entry = [line]
        else:
            # Continuation of previous entry
            if current_entry:
                current_entry.append(line)
            else:
                # Edge case: file starts without timestamp
                current_entry.append(line)

    if current_entry:
        entries.append(''.join(current_entry))

    return entries


def run_server():
    logger.info(f"Web server starting on http://localhost:{config.WEB_PORT}")
    app.run(host='0.0.0.0', port=config.WEB_PORT, debug=False, use_reloader=False)
