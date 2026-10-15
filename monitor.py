"""Coleta estatística de sinais OTC. Não envia ordens e não simula preços de execução."""
import csv
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

SYMBOL = os.getenv('OTCHARTS_SYMBOL', 'BRLUSD_otc')
OUT = Path('data/monitor_usdbrl_otc.csv')
FIELDS = ['fim_sinal_utc', 'simbolo', 'direcao', 'preco_sinal', 'preco_proximo_fechamento', 'resultado_teorico']


def get_candles(key, tf):
    r = requests.get('https://otcharts.com/v1/candles', headers={'Authorization': f'Bearer {key}'}, params={'venue': 'quotex', 'symbol': SYMBOL, 'tf': tf, 'limit': 120}, timeout=30)
    r.raise_for_status()
    df = pd.DataFrame(r.json().get('candles', []))
    if df.empty or not {'open', 'high', 'low', 'close'}.issubset(df):
        raise ValueError(f'Candles ausentes ou incompletos ({tf})')
    time_col = next((c for c in ('time', 'timestamp', 'ts', 't') if c in df.columns), None)
    if not time_col:
        raise ValueError('Sem timestamps')
    num = pd.to_numeric(df[time_col], errors='coerce')
    if num.notna().all():
        df['inicio'] = pd.to_datetime(num, unit='ms' if num.abs().median() > 1e11 else 's', utc=True, errors='coerce')
    else:
        df['inicio'] = pd.to_datetime(df[time_col], utc=True, errors='coerce')
    if df.inicio.isna().any():
        raise ValueError('Timestamps inválidos')
    rounded = df.inicio.dt.round(f'{tf}s')
    if ((df.inicio - rounded).abs() > pd.Timedelta(seconds=2)).any():
        raise ValueError('Candles fora da grade temporal')
    df['inicio'] = rounded
    for c in ('open', 'high', 'low', 'close'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    if df[['open', 'high', 'low', 'close']].isna().any().any():
        raise ValueError('Preços inválidos')
    dup = df[df.inicio.duplicated(keep=False)]
    for _, group in dup.groupby('inicio'):
        if len(group[['open', 'high', 'low', 'close']].drop_duplicates()) > 1:
            raise ValueError('Candles duplicados com preços conflitantes')
    df = df.sort_values('inicio').drop_duplicates('inicio')
    if ((df.high < df[['open', 'low', 'close']].max(axis=1)) | (df.low > df[['open', 'high', 'close']].min(axis=1))).any():
        raise ValueError('OHLC inconsistente')
    df['fim'] = df.inicio + pd.Timedelta(seconds=tf)
    now = pd.Timestamp.now(tz='UTC')
    df = df[df.fim <= now - pd.Timedelta(seconds=5)].copy()
    if len(df) < 30:
        raise ValueError('Candles insuficientes')
    if (now - df.fim.iloc[-1]) > pd.Timedelta(seconds=tf + 180):
        raise ValueError('Dados desatualizados')
    if (df.inicio.tail(25).diff().dropna() != pd.Timedelta(seconds=tf)).any():
        raise ValueError('Lacunas nos candles recentes')
    return df.reset_index(drop=True)


def indicators(df):
    df = df.copy()
    df['mm9'] = df.close.rolling(9).mean()
    df['mm21'] = df.close.rolling(21).mean()
    delta = df.close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    rsi.loc[(loss == 0) & (gain > 0)] = 100
    rsi.loc[(loss == 0) & (gain == 0)] = 50
    up = (df.mm9 > df.mm21) & (df.close > df.mm9) & (rsi > 50) & (rsi < 70)
    down = (df.mm9 < df.mm21) & (df.close < df.mm9) & (rsi > 30) & (rsi < 50)
    df['direcao'] = np.select([up, down], ['ALTA', 'BAIXA'], default='INDEFINIDA')
    return df


def main():
    key = os.getenv('OTCHARTS_API_KEY')
    if not key:
        raise ValueError('Configure OTCHARTS_API_KEY nos GitHub Actions Secrets')
    frames = {tf: indicators(get_candles(key, tf)) for tf in (300, 900, 3600)}
    m5 = frames[300].sort_values('fim')
    for tf, name in ((900, 'm15'), (3600, 'h1')):
        ref = frames[tf][['fim', 'direcao']].rename(columns={'fim': 'fim_ref', 'direcao': name}).sort_values('fim_ref')
        m5 = pd.merge_asof(m5.sort_values('fim'), ref, left_on='fim', right_on='fim_ref', direction='backward').drop(columns='fim_ref')
    existing = set()
    if OUT.exists():
        with OUT.open(encoding='utf-8', newline='') as f:
            existing = {r['fim_sinal_utc'] for r in csv.DictReader(f)}
    rows = []
    # Apenas sinais com candle M5 seguinte efetivamente fechado e disponível.
    for i in range(25, len(m5) - 1):
        current, nxt = m5.iloc[i], m5.iloc[i + 1]
        if nxt.inicio - current.inicio != pd.Timedelta(minutes=5):
            continue
        direction = current.direcao
        if direction not in ('ALTA', 'BAIXA') or direction != current.m15 or direction != current.h1:
            continue
        stamp = current.fim.strftime('%Y-%m-%dT%H:%M:%SZ')
        if stamp in existing:
            continue
        a, b = float(current.close), float(nxt.close)
        result = 'EMPATE' if a == b else ('ACERTO' if (b > a) == (direction == 'ALTA') else 'ERRO')
        rows.append({'fim_sinal_utc': stamp, 'simbolo': SYMBOL, 'direcao': 'CALL' if direction == 'ALTA' else 'PUT', 'preco_sinal': a, 'preco_proximo_fechamento': b, 'resultado_teorico': result})
    if rows:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        is_new = not OUT.exists() or OUT.stat().st_size == 0
        with OUT.open('a', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            if is_new:
                writer.writeheader()
            writer.writerows(rows)
    print(f'{SYMBOL}: {len(rows)} resultados teóricos novos. Nenhuma ordem executada.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Monitor interrompido: {exc}', file=sys.stderr)
        sys.exit(1)
