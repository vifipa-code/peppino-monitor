"""
Monitor peppinopizza.es - se ejecuta desde GitHub Actions cada 5 min.
Guarda el estado en state.json (versionado en el repo) para avisar solo
cuando algo cambia (evita spam durante una caida prolongada).
"""
import json
import os
import urllib.request
import urllib.parse
import ssl
from datetime import datetime, timezone

TOKEN = os.environ['TG_TOKEN']
CHAT_ID = os.environ['TG_CHAT']

CHECKS = [
    ('Home',  'https://www.peppinopizza.es/',               50_000),
    ('Panel', 'https://www.peppinopizza.es/panel-pedidos/', 30_000),
    ('Carta', 'https://www.peppinopizza.es/carta/',         30_000),
]
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'
TIMEOUT = 25
STATE_FILE = 'state.json'


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
        return False, 'error: %s' % type(e).__name__ + ': ' + str(e)[:120]


try:
    with open(STATE_FILE, 'r', encoding='utf-8') as f:
        prev = json.load(f)
except Exception:
    prev = {}

now = datetime.now(timezone.utc).strftime('%d/%m %H:%M UTC')
new = {}
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
