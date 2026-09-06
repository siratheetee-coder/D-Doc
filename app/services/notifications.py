"""Private, persistent notification recipient for the seller."""
import json
import os
import re
import uuid
from app.database import get_data_dir


def notification_email():
    from app.seller_config import SELLER
    try:
        saved = json.loads((get_data_dir() / 'notification-settings.json').read_text(encoding='utf-8'))
        if saved.get('email'):
            return str(saved['email'])
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return (os.environ.get('DDOC_NOTIFY_EMAIL') or SELLER.get('notify_email') or SELLER.get('email') or '').strip()


def save_notification_email(email):
    email = email.strip()
    if len(email) > 254 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', email):
        raise ValueError('กรุณาระบุอีเมลที่ถูกต้อง 1 ที่อยู่')
    directory = get_data_dir()
    temporary = directory / ('notification-' + uuid.uuid4().hex + '.json')
    temporary.write_text(json.dumps({'email': email}), encoding='utf-8')
    temporary.replace(directory / 'notification-settings.json')
