"""
Monitor de peppinopizza.es
Comprueba cada 5 minutos que la home y el panel funcionan.
Avisa al grupo Telegram si algo falla, y avisa cuando vuelve.
"""
import time
import urllib.request
import urllib.parse
import ssl

TOKEN = '8643617097:AAFc0cU8pw-MmsJ0XEo0sKtw7h7Fm4Dw2Mw'
CHAT_ID = '-5269363100'

CHECKS = [
    ('Home',   'https://www.peppinopizza.es/',              50_000),
    ('Panel',  'https://www.peppinopizza.es/panel-pedidos/', 30_000),
    ('Carta',  'https://www.peppinopizza.es/carta/',         30_000),
]
INTERVAL = 300  # 5 minutos
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'
TIMEOUT = 20
CTX = ssl.create_default_context()


def tg(text):
    try:
        data = urllib.parse.urlencode({
            'chat_id': CHAT_ID,
            'text': text,
            'parse_mode': 'HTML',
        }).encode()
        urllib.request.urlopen(
            'https://api.telegram.org/bot' + TOKEN + '/sendMessage',
            data=data, timeout=10,
        ).read()
    except Exception as e:
        print('[tg fail]', e)


def check(name, url, min_size):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        r = urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX)
        body = r.read()
        code = r.getcode()
        if code != 200:
            return False, 'HTTP %d' % code
        if len(body) < min_size:
            return False, 'tamano %d bytes (esperado >= %d)' % (len(body), min_size)
        return True, 'OK %d bytes' % len(body)
    except Exception as e:
        return False, 'error: %s' % e


state = {name: True for name, _, _ in CHECKS}  # empezamos asumiendo OK

print('Monitor peppinopizza.es iniciado. Intervalo:', INTERVAL, 's')
tg('Monitor de la web arrancado. Avisara si algo se cae.')

while True:
    for name, url, ms in CHECKS:
        ok, msg = check(name, url, ms)
        prev = state[name]
        print(time.strftime('%H:%M:%S'), name, msg)
        if not ok and prev:
            tg('CAIDA: <b>' + name + '</b>\n' + url + '\n' + msg)
            state[name] = False
        elif ok and not prev:
            tg('RECUPERADO: <b>' + name + '</b>\n' + msg)
            state[name] = True
    time.sleep(INTERVAL)
