"""
Monitor + auto-repair de peppinopizza.es
- Cada 5 min: check HTTP de home/panel/carta + verifica que index.php
  no haya sido roto por Imunify. Si detecta corrupcion, lo restaura por FTP.
- Avisa por Telegram solo cuando cambia el estado o cuando repara.
"""
import json
import os
import io
import ssl
import ftplib
import html
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

TOKEN = os.environ['TG_TOKEN']
CHAT_ID = os.environ['TG_CHAT']
FTP_HOST = os.environ.get('FTP_HOST', 'ftp.peppinopizza.es')
FTP_USER = os.environ['FTP_USER']
FTP_PASS = os.environ['FTP_PASS']

CHECKS = [
    ('Home',  'https://www.peppinopizza.es/',               50_000),
    ('Panel', 'https://www.peppinopizza.es/panel-pedidos/', 30_000),
    ('Carta', 'https://www.peppinopizza.es/carta/',         30_000),
]
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'
TIMEOUT = 25
STATE_FILE = 'state.json'

INDEX_PHP_GOOD = (
    "<?php\n"
    "/**\n"
    " * Front to the WordPress application.\n"
    " */\n"
    "define( 'WP_USE_THEMES', true );\n"
    "require __DIR__ . '/wp-blog-header.php';\n"
)
INDEX_PATH = '/public_html/index.php'


def tg(text):
    data = urllib.parse.urlencode({
        'chat_id': CHAT_ID,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': 'true',
    }).encode()
    try:
        urllib.request.urlopen(
            'https://api.telegram.org/bot' + TOKEN + '/sendMessage',
            data=data, timeout=15,
        ).read()
    except Exception as e:
        print('[tg fail]', e)


def check(url, min_size):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        r = urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context())
        body = r.read()
        if r.getcode() != 200:
            return False, 'HTTP %d' % r.getcode()
        if len(body) < min_size:
            return False, 'tamano %d bytes (esperado >= %d)' % (len(body), min_size)
        return True, 'OK (%d bytes)' % len(body)
    except Exception as e:
        return False, 'error: %s: %s' % (type(e).__name__, str(e)[:120])


def ftp_connect():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ftp = ftplib.FTP_TLS(FTP_HOST, FTP_USER, FTP_PASS, context=ctx, timeout=30)
    ftp.prot_p()
    ftp.set_pasv(True)
    return ftp


def index_php_is_healthy():
    """Descarga index.php por FTP y verifica que contenga el require de wp-blog-header."""
    try:
        ftp = ftp_connect()
        buf = io.BytesIO()
        ftp.retrbinary('RETR ' + INDEX_PATH, buf.write)
        ftp.quit()
        content = buf.getvalue().decode('utf-8', 'replace')
        if 'wp-blog-header' in content and len(content) >= 100:
            return True, 'OK (%d bytes)' % len(content)
        return False, 'CORRUPTO (%d bytes, sin wp-blog-header)' % len(content)
    except Exception as e:
        return None, 'error FTP: %s: %s' % (type(e).__name__, str(e)[:120])


def repair_index_php():
    try:
        ftp = ftp_connect()
        ftp.storbinary('STOR ' + INDEX_PATH, io.BytesIO(INDEX_PHP_GOOD.encode('utf-8')))
        ftp.quit()
        return True
    except Exception as e:
        print('[repair fail]', e)
        return False


# --- run ---
REMINDER_MIN = 15  # re-avisa cada 15 min mientras siga caido

try:
    with open(STATE_FILE, 'r', encoding='utf-8') as f:
        prev_raw = json.load(f)
except Exception:
    prev_raw = {}

# Backwards compat: old format was {"Home": true, ...}
def norm(v):
    if isinstance(v, bool):
        return {'ok': v, 'since': None, 'last_alert': None}
    return {'ok': v.get('ok', True), 'since': v.get('since'), 'last_alert': v.get('last_alert')}

prev = {k: norm(v) for k, v in prev_raw.items()}

now_dt = datetime.now(timezone.utc)
# Show Madrid time (roughly UTC+2 in summer, UTC+1 in winter)
_madrid = timezone(timedelta(hours=2))  # España horario verano
now = now_dt.astimezone(_madrid).strftime('%d/%m %H:%M h')
new = {}

# 1) Auto-repair index.php if broken
healthy, msg = index_php_is_healthy()
print('index.php:', msg)
if healthy is False:
    ok = repair_index_php()
    if ok:
        tg('AUTO-REPARADO: <b>index.php</b>\n' + html.escape(msg) + '\nRestaurado.\n' + now)
    else:
        tg('FALLO al reparar index.php\n' + html.escape(msg) + '\n' + now)

# 2) HTTP checks
for name, url, ms in CHECKS:
    ok, msg = check(url, ms)
    print(name, '->', 'OK' if ok else 'FAIL', '|', msg)
    p = prev.get(name, {'ok': True, 'since': None, 'last_alert': None})
    entry = {'ok': ok, 'since': p['since'], 'last_alert': p['last_alert']}

    if not ok and p['ok']:
        # Just went down
        entry['since'] = now_dt.isoformat()
        entry['last_alert'] = now_dt.isoformat()
        tg('CAIDA: <b>' + html.escape(name) + '</b>\n' + html.escape(url) + '\n' + html.escape(msg) + '\n' + now)
    elif not ok and not p['ok']:
        # Still down: re-alert every REMINDER_MIN
        last_alert = p['last_alert']
        try:
            la = datetime.fromisoformat(last_alert) if last_alert else None
        except Exception:
            la = None
        should_alert = (la is None) or ((now_dt - la).total_seconds() >= REMINDER_MIN * 60)
        if should_alert:
            try:
                since_dt = datetime.fromisoformat(p['since']) if p['since'] else now_dt
                mins = int((now_dt - since_dt).total_seconds() // 60)
            except Exception:
                mins = 0
            entry['last_alert'] = now_dt.isoformat()
            tg('SIGUE CAIDA (' + str(mins) + ' min): <b>' + html.escape(name) + '</b>\n' + html.escape(url) + '\n' + html.escape(msg) + '\n' + now)
    elif ok and not p['ok']:
        # Recovered
        try:
            since_dt = datetime.fromisoformat(p['since']) if p['since'] else now_dt
            mins = int((now_dt - since_dt).total_seconds() // 60)
        except Exception:
            mins = 0
        entry['since'] = None
        entry['last_alert'] = None
        tg('RECUPERADO: <b>' + html.escape(name) + '</b>\nEstuvo caida ' + str(mins) + ' min\n' + html.escape(msg) + '\n' + now)

    new[name] = entry

with open(STATE_FILE, 'w', encoding='utf-8') as f:
    json.dump(new, f, indent=2)
