"""Read-only BTCUSDT Futures analysis. No Binance account/order endpoints."""
from __future__ import annotations
import hashlib
import json
import math
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

SYMBOL = 'BTCUSDT'
INTERVALS = {'5m': 300_000, '15m': 900_000, '1h': 3_600_000, '4h': 14_400_000}
VERSION = 'btc-trend-v1'
DATA_DIR = Path(os.environ.get('FUTURES_DATA_DIR', 'runtime'))

class DataError(Exception):
    pass


def fetch_json(path, params=None):
    url = 'https://fapi.binance.com' + path
    if params:
        url += '?' + urllib.parse.urlencode(params)
    return request(url)


def request(url, data=None):
    req = urllib.request.Request(url, data=data, headers={'User-Agent': 'NexusFutures/1.0', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            payload = response.read(4_000_000)
        return json.loads(payload)
    except urllib.error.HTTPError as exc:
        if exc.code == 451:
            raise DataError('Binance bloqueou a região do servidor (HTTP 451). Use hospedagem onde o serviço seja permitido.') from None
        raise DataError(f'Fonte indisponível: HTTP {exc.code}; nenhum sinal liberado.') from None
    except (OSError, ValueError) as exc:
        raise DataError(f'Falha de conexão/dados: {type(exc).__name__}; nenhum sinal liberado.') from None


def finite(value):
    x = float(value)
    if not math.isfinite(x):
        raise DataError('Valor não finito na fonte.')
    return x


def candles(raw, interval, now_ms, minimum=220):
    step = INTERVALS[interval]
    parsed = []
    seen = set()
    for row in raw:
        t, end = int(row[0]), int(row[6])
        if t % step or end != t + step - 1:
            raise DataError(f'{interval}: grade temporal inválida.')
        values = [finite(row[i]) for i in (1, 2, 3, 4, 5)]
        o, h, l, c, v = values
        if min(o, h, l, c) <= 0 or v < 0 or h < max(o, c, l) or l > min(o, c, h):
            raise DataError(f'{interval}: OHLCV inválido.')
        if t in seen:
            raise DataError(f'{interval}: candle duplicado.')
        seen.add(t)
        if end <= now_ms - 2000:
            parsed.append(dict(time=t, end=end, open=o, high=h, low=l, close=c, volume=v))
    parsed.sort(key=lambda x: x['time'])
    if len(parsed) < minimum:
        raise DataError(f'{interval}: histórico insuficiente ({len(parsed)}).')
    if any(b['time'] - a['time'] != step for a, b in zip(parsed, parsed[1:])):
        raise DataError(f'{interval}: lacuna no histórico.')
    age = now_ms - (parsed[-1]['end'] + 1)
    if age < 0 or age > step + 60_000:
        raise DataError(f'{interval}: dados atrasados.')
    return parsed


def ema(values, n):
    result, current = [], values[0]
    alpha = 2 / (n + 1)
    for x in values:
        current = alpha * x + (1 - alpha) * current
        result.append(current)
    return result


def technical(rows):
    closes = [r['close'] for r in rows]
    e20, e50, e200 = (ema(closes, n) for n in (20, 50, 200))
    tr = [rows[0]['high'] - rows[0]['low']]
    gains, losses = [], []
    for prev, row in zip(rows, rows[1:]):
        tr.append(max(row['high'] - row['low'], abs(row['high'] - prev['close']), abs(row['low'] - prev['close'])))
        diff = row['close'] - prev['close']
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    def wilder(values):
        a = sum(values[:14]) / 14
        for x in values[14:]:
            a = (a * 13 + x) / 14
        return a
    gain, loss = wilder(gains), wilder(losses)
    rsi = 50 if gain == loss == 0 else 100 if loss == 0 else 100 - 100 / (1 + gain / loss)
    last = rows[-1]
    trend = 'ALTA' if closes[-1] > e20[-1] > e50[-1] > e200[-1] and e50[-1] > e50[-4] else 'BAIXA' if closes[-1] < e20[-1] < e50[-1] < e200[-1] and e50[-1] < e50[-4] else 'LATERAL'
    vol_base = sum(r['volume'] for r in rows[-21:-1]) / 20
    return dict(trend=trend, rsi=rsi, atr=wilder(tr), ema20=e20[-1], ema50=e50[-1], ema200=e200[-1], volume_ratio=last['volume'] / vol_base if vol_base else 0, close=closes[-1], candle=last['time'])


FEEDS = {
    'Federal Reserve': 'https://www.federalreserve.gov/feeds/press_monetary.xml',
    'BLS — inflação e emprego': 'https://www.bls.gov/feed/bls_latest.rss',
}


def macro_context(now_ms):
    """Official releases are an event-risk filter, not a sentiment predictor.
    RSS cannot anticipate unscheduled headlines. Coverage is explicit in output.
    """
    sources, headlines, blocks = [], [], []
    for name, url in FEEDS.items():
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'NexusFutures/1.0 (public economic releases)'})
            with urllib.request.urlopen(req, timeout=10) as response:
                root = ET.fromstring(response.read(1_000_000))
            items = root.findall('.//item')
            if not items:
                raise DataError('Feed vazio')
            sources.append({'source': name, 'ok': True, 'checked_at': now_ms})
            for item in items[:15]:
                title = item.findtext('title', '').strip()
                published = item.findtext('pubDate', '')
                dt = parsedate_to_datetime(published)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                stamp = int(dt.timestamp() * 1000)
                headlines.append({'source': name, 'title': title, 'url': item.findtext('link', url), 'published': stamp})
                key = title.lower()
                important = any(k in key for k in ('fomc', 'federal funds', 'monetary policy', 'consumer price', 'employment situation', 'producer price'))
                if important and -60_000 <= now_ms - stamp <= 3_600_000:
                    blocks.append(f'Publicação macro recente: {title}')
        except Exception:
            sources.append({'source': name, 'ok': False, 'checked_at': now_ms})
    if not all(s['ok'] for s in sources):
        blocks.append('Cobertura macro indisponível; sinais bloqueados.')
    path = DATA_DIR / 'events.json'
    events = []
    calendar_ok = False
    if path.exists():
        try:
            config = json.loads(path.read_text())
            reviewed = int(config['reviewed_at'])
            calendar_ok = 0 <= now_ms - reviewed < 24 * 3_600_000
            events = config['events']
            for event in events:
                ts = int(event['time'])
                if ts - 30 * 60_000 <= now_ms <= ts + 60 * 60_000:
                    blocks.append('Janela de evento: ' + str(event['name']))
        except (ValueError, KeyError, TypeError):
            calendar_ok = False
    if not calendar_ok:
        blocks.append('Agenda macro precisa ser revisada nas últimas 24h no painel.')
    return dict(sources=sources, headlines=sorted(headlines, key=lambda x: x['published'], reverse=True)[:12], blocks=blocks, calendar_ok=calendar_ok, events=events, coverage='Fed/BLS + agenda revisada. Sem fluxos de ETFs, on-chain, sentimento ou cobertura completa de notícias.')


def collect():
    started = int(time.time() * 1000)
    now = int(fetch_json('/fapi/v1/time')['serverTime'])
    if abs(now - started) > 60_000:
        raise DataError('Relógio local difere mais de 60s da Binance.')
    jobs = {tf: ('/fapi/v1/klines', {'symbol': SYMBOL, 'interval': tf, 'limit': 300}) for tf in INTERVALS}
    jobs.update(mark=('/fapi/v1/premiumIndex', {'symbol': SYMBOL}), book=('/fapi/v1/depth', {'symbol': SYMBOL, 'limit': 20}), oi=('/futures/data/openInterestHist', {'symbol': SYMBOL, 'period': '5m', 'limit': 3}), taker=('/futures/data/takerlongshortRatio', {'symbol': SYMBOL, 'period': '5m', 'limit': 3}), ratio=('/futures/data/globalLongShortAccountRatio', {'symbol': SYMBOL, 'period': '5m', 'limit': 3}))
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {k: pool.submit(fetch_json, *v) for k, v in jobs.items()}
        result = {k: f.result() for k, f in futures.items()}
    ended = int(time.time() * 1000)
    if ended - started > 45_000:
        raise DataError('Coleta demorou demais; snapshot descartado.')
    result['now'] = now + ended - started
    result['symbol'] = SYMBOL
    result['collected_at'] = ended
    return result


def analyze(snapshot, macro):
    now = int(snapshot['now'])
    if snapshot.get('symbol') != SYMBOL:
        raise DataError('Símbolo inesperado.')
    frames = {tf: candles(snapshot[tf], tf, now) for tf in INTERVALS}
    readings = {tf: technical(rows) for tf, rows in frames.items()}
    mark, book = snapshot['mark'], snapshot['book']
    if mark.get('symbol') != SYMBOL:
        raise DataError('Mark price de outro contrato.')
    if not 0 <= now - int(mark['time']) <= 60_000 or not 0 <= now - int(book['T']) <= 60_000:
        raise DataError('Preço/livro atrasado ou no futuro.')
    bid, ask = finite(book['bids'][0][0]), finite(book['asks'][0][0])
    if bid <= 0 or ask <= bid:
        raise DataError('Livro de ofertas cruzado ou inválido.')
    for name in ('oi', 'taker', 'ratio'):
        rows = snapshot[name]
        if len(rows) < 2 or not 0 <= now - int(rows[-1]['timestamp']) <= 900_000:
            raise DataError(f'{name}: dados ausentes/atrasados.')
    oi_a, oi_b = (finite(x['sumOpenInterest']) for x in snapshot['oi'][-2:])
    if min(oi_a, oi_b) <= 0:
        raise DataError('Open interest inválido.')
    buy, sell = (finite(snapshot['taker'][-1][key]) for key in ('buyVol', 'sellVol'))
    if buy < 0 or sell < 0 or buy + sell == 0:
        raise DataError('Fluxo taker inválido.')
    buy_share = buy / (buy + sell)
    funding = finite(mark['lastFundingRate'])
    spread = (ask - bid) / ((ask + bid) / 2) * 10_000
    oi_change = (oi_b / oi_a - 1) * 100
    long_short = finite(snapshot['ratio'][-1]['longShortRatio'])
    blocks = list(macro['blocks'])
    if spread > 2:
        blocks.append('Spread acima de 2 pontos-base.')
    if abs(funding) > .0005:
        blocks.append('Funding extremo (>0,05% por intervalo).')
    trend = readings['4h']['trend']
    if trend not in ('ALTA', 'BAIXA') or any(r['trend'] != trend for r in readings.values()):
        blocks.append('H4, H1, M15 e M5 sem alinhamento de tendência.')
    m5, m15 = readings['5m'], readings['15m']
    sign = 1 if trend == 'ALTA' else -1
    if not ((52 <= m15['rsi'] <= 68) if sign == 1 else (32 <= m15['rsi'] <= 48)):
        blocks.append('Momentum M15 fora da faixa da estratégia.')
    if m5['volume_ratio'] < 1.1:
        blocks.append('Volume M5 abaixo de 1,1× a média anterior.')
    if oi_change <= 0:
        blocks.append('Contratos em aberto sem expansão no último intervalo.')
    if not (buy_share >= .55 if sign == 1 else buy_share <= .45):
        blocks.append('Fluxo agressor não confirma a direção.')
    price = ask if sign == 1 else bid
    atr = m5['atr']
    if atr <= 0:
        raise DataError('ATR inválido.')
    if abs(price - m5['close']) > .5 * atr:
        blocks.append('Preço já se afastou do fechamento M5.')
    if abs(price - m5['ema20']) > 1.5 * atr:
        blocks.append('Entrada esticada em relação à EMA20 M5.')
    swing = min(r['low'] for r in frames['5m'][-6:]) if sign == 1 else max(r['high'] for r in frames['5m'][-6:])
    distance = max(1.5 * atr, sign * (price - swing) + .2 * atr)
    if distance > 3 * atr:
        blocks.append('Stop estrutural distante demais (>3 ATR).')
    # 0.10% fees + 0.04% slippage round trip; actual tier/funding can differ.
    cost = price * .0014
    if distance < cost * 3:
        blocks.append('Movimento projetado insuficiente frente ao custo estimado.')
    tp2 = price + sign * 2 * distance
    levels = [r['high'] if sign == 1 else r['low'] for r in frames['1h'][-48:]]
    barriers = [x for x in levels if .3 * atr < sign * (x - price) < 2 * distance]
    if barriers:
        blocks.append('Barreira H1 antes do alvo de 2R.')
    end = frames['5m'][-1]['end'] + 1
    if now - end > 120_000:
        blocks.append('Janela de entrada expirou: mais de 2 minutos do fechamento M5.')
    signal_id = hashlib.sha256(f'{VERSION}:{SYMBOL}:{end}:{trend}'.encode()).hexdigest()[:20]
    return dict(version=VERSION, symbol=SYMBOL, checked_at=now, candle_close=end, expires_at=end+120_000, signal_id=signal_id, action=('COMPRA' if sign == 1 else 'VENDA') if not blocks else 'AGUARDAR', blocks=blocks, readings=readings, market=dict(bid=bid, ask=ask, spread_bps=spread, funding=funding, oi_change_pct=oi_change, buy_share=buy_share, long_short=long_short), plan=dict(entry=price, stop=price-sign*distance, target1=price+sign*distance, target2=tp2, risk=distance, atr=atr, sign=sign), macro=macro, probability=None, validation='EXPERIMENTAL — taxa de acerto não validada')


def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA_DIR / 'signals.sqlite', timeout=20)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS signals (id TEXT PRIMARY KEY, created INTEGER, payload TEXT, status TEXT, entry REAL, exit REAL, pnl_r REAL, notified INTEGER DEFAULT 0)')
    return db


def save_signal(result):
    if result['action'] == 'AGUARDAR':
        return False
    with connect() as db:
        if db.execute("SELECT 1 FROM signals WHERE status IN ('PENDING','OPEN')").fetchone():
            return False
        cursor = db.execute('INSERT OR IGNORE INTO signals(id,created,payload,status) VALUES(?,?,?,?)', (result['signal_id'], result['checked_at'], json.dumps(result), 'PENDING'))
        return cursor.rowcount == 1


def paper_update(raw, now_ms):
    """Paper: fill next 5m open, max 0.25 ATR drift; 2R exit, stop first.
    No real orders. Fees/slippage 0.14% round trip; funding uses signal rate
    at EACH actual funding timestamp supplied separately by funding_history.
    """
    # Use only completed bars; ignore current candle.
    rows = candles(raw, '5m', now_ms, minimum=1)
    with connect() as db:
        active = db.execute("SELECT id,payload,status,entry FROM signals WHERE status IN ('PENDING','OPEN')").fetchall()
        for sid, payload, status, entry in active:
            signal = json.loads(payload)
            plan = signal['plan']
            start = (signal['checked_at'] // 300_000 + 1) * 300_000
            eligible = [r for r in rows if r['time'] >= start]
            if not eligible:
                continue
            if eligible[0]['time'] != start:
                db.execute('UPDATE signals SET status=? WHERE id=?', ('DATA_GAP', sid))
                continue
            if status == 'PENDING':
                entry = eligible[0]['open']
                if abs(entry - plan['entry']) > .25 * plan['atr']:
                    db.execute('UPDATE signals SET status=? WHERE id=?', ('CANCELLED_DRIFT', sid))
                    continue
                db.execute('UPDATE signals SET status=?,entry=? WHERE id=?', ('OPEN', entry, sid))
            sign = plan['sign']
            for i, bar in enumerate(eligible):
                stop, target = plan['stop'], plan['target2']
                hit_stop = bar['low'] <= stop if sign == 1 else bar['high'] >= stop
                hit_target = bar['high'] >= target if sign == 1 else bar['low'] <= target
                if hit_stop:
                    exit_price = min(stop, bar['open']) if sign == 1 else max(stop, bar['open'])
                    state = 'STOP'
                elif hit_target:
                    exit_price, state = target, 'TARGET'
                elif i >= 47:
                    exit_price, state = bar['close'], 'TIME_EXIT'
                else:
                    continue
                risk = abs(entry - stop)
                # No funding estimate disguised as actual: report price return only;
                # settlement funding is computed later in settled_results().
                pnl = (sign * (exit_price-entry) - (entry+exit_price)*.0007) / risk
                signal['paper_exit_at'] = bar['end'] + 1
                signal['paper_entry_at'] = start
                db.execute('UPDATE signals SET status=?,entry=?,exit=?,pnl_r=?,payload=? WHERE id=?', (state,entry,exit_price,pnl,json.dumps(signal),sid))
                break


def history():
    with connect() as db:
        rows = db.execute('SELECT id,created,payload,status,entry,exit,pnl_r,notified FROM signals ORDER BY created DESC LIMIT 1000').fetchall()
    return [dict(id=r[0],created=r[1],payload=json.loads(r[2]),status=r[3],entry=r[4],exit=r[5],pnl_r_before_funding=r[6],notified=r[7]) for r in rows]


def settle_funding(records, funding_rows, covered_from, covered_to):
    """Funding charged on marked notional at actual settlement times; no fixed 8h assumption."""
    result = []
    for record in records:
        row = dict(record)
        signal = row['payload']
        if (row['pnl_r_before_funding'] is not None
                and covered_from <= signal['paper_entry_at'] <= signal['paper_exit_at'] <= covered_to):
            start = signal['paper_entry_at']
            end = signal['paper_exit_at']
            # Funding at an exit candle's close is included conservatively.
            charge = sum(finite(f['fundingRate'])*finite(f['markPrice'])*signal['plan']['sign'] for f in funding_rows if start <= int(f['fundingTime']) <= end)
            risk = abs(row['entry']-signal['plan']['stop'])
            row['funding_per_btc'] = charge
            row['pnl_r'] = row['pnl_r_before_funding'] - charge/risk
        result.append(row)
    return result


def telegram_text(s):
    p = s['plan']
    return (f"NEXUS • {s['symbol']} • {s['action']}\nEXPERIMENTAL • sinal para análise manual\n"
            f"Entrada de referência: {p['entry']:,.2f}\nStop: {p['stop']:,.2f}\nAlvo 1 (referência): {p['target1']:,.2f}\nAlvo 2: {p['target2']:,.2f}\n"
            f"Válido até: {datetime.fromtimestamp(s['expires_at']/1000, timezone.utc).isoformat()}\n"
            f"H4/H1/M15/M5 alinhados; fluxo e OI confirmados.\nID: {s['signal_id']}\nSem execução automática; sem taxa de acerto comprovada.")


def notify_pending(now_ms):
    token, chat = os.environ.get('TELEGRAM_BOT_TOKEN'), os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat:
        return 'Telegram não configurado'
    with connect() as db:
        rows = db.execute('SELECT id,payload FROM signals WHERE notified=0').fetchall()
        for sid, payload in rows:
            s = json.loads(payload)
            if now_ms > s['expires_at']:
                db.execute('UPDATE signals SET notified=-1 WHERE id=?', (sid,))
                continue
            try:
                response = request(f'https://api.telegram.org/bot{token}/sendMessage', json.dumps({'chat_id':chat,'text':telegram_text(s),'disable_web_page_preview':True}).encode())
                if not response.get('ok'):
                    raise DataError('Telegram não confirmou entrega')
            except Exception:
                # Do not expose exception URLs (which contain a bot credential).
                return 'Falha no Telegram; nova tentativa no próximo ciclo (pode duplicar se houver timeout após entrega)'
            db.execute('UPDATE signals SET notified=1 WHERE id=?', (sid,))
    return 'Telegram configurado'


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    tmp.replace(path)
