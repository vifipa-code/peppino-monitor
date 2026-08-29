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
import urllib.request
import urllib.parse
from datetime import datetime, timezone

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
try:
    with open(STATE_FILE, 'r', encoding='utf-8') as f:
        prev = json.load(f)
except Exception:
    prev = {}

now = datetime.now(timezone.utc).strftime('%d/%m %H:%M UTC')
new = dict(prev)

# 1) Auto-repair index.php if broken
healthy, msg = index_php_is_healthy()
print('index.php:', msg)
if healthy is False:
    ok = repair_index_php()
    if ok:
        tg('AUTO-REPARADO: <b>index.php</b>\n' + msg + '\nRestaurado.\n' + now)
    else:
        tg('FALLO al reparar index.php\n' + msg + '\n' + now)

# 2) HTTP checks
for name, url, ms in CHECKS:
    ok, msg = check(url, ms)
    new[name] = ok
    print(name, '->', 'OK' if ok else 'FAIL', '|', msg)
    was_ok = prev.get(name, True)
    if not ok and was_ok:
        tg('CAIDA: <b>' + name + '</b>\n' + url + '\n' + msg + '\n' + now)
    elif ok and not was_ok:
        tg('RECUPERADO: <b>' + name + '</b>\n' + msg + '\n' + now)

with open(STATE_FILE, 'w', encoding='utf-8') as f:
    json.dump(new, f, indent=2)
