"""Continuous worker. Polls public REST every 15s; never places orders."""
import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
import futures_engine as engine


def run_cycle(snapshot=None, macro=None):
    state_path = engine.DATA_DIR / 'status.json'
    try:
        snapshot = snapshot or engine.collect()
        now = snapshot['now']
        # A saved snapshot is for tests only, never silently a live source.
        macro = macro or engine.macro_context(now)
        result = engine.analyze(snapshot, macro)
        engine.paper_update(snapshot['5m'], now)
        active = [r for r in engine.history() if r['status'] in ('PENDING', 'OPEN')]
        if result['action'] != 'AGUARDAR' and active:
            result['blocks'].append('Já existe um sinal em acompanhamento na simulação.')
            result['action'] = 'AGUARDAR'
        new_signal = engine.save_signal(result)
        notification = engine.notify_pending(now)
        records = engine.history()
        funding_from = now - 7 * 24 * 3_600_000
        funding_error = None
        if records and snapshot.get('live', True):
            try:
                funding_rows = engine.fetch_json('/fapi/v1/fundingRate', {'symbol': engine.SYMBOL, 'startTime': funding_from, 'endTime': now, 'limit': 1000})
                if len(funding_rows) >= 1000:
                    raise engine.DataError('Histórico de funding incompleto')
                records = engine.settle_funding(records, funding_rows, funding_from, now)
            except Exception:
                funding_error = 'Funding não conciliado; resultado líquido indisponível.'
        result.update(ok=True, live=snapshot.get('live', True), notification=notification, new_signal=new_signal, history=records, funding_error=funding_error, prices=snapshot['5m'][-100:])
        engine.write_json(state_path, result)
        return result
    except Exception as exc:
        # Sanitize unexpected errors: no URLs/tokens/stack traces in public status.
        message = str(exc) if isinstance(exc, engine.DataError) else f'Falha de processamento ({type(exc).__name__}); sinais bloqueados.'
        state = dict(ok=False, live=True, checked_at=int(time.time()*1000), action='AGUARDAR', blocks=[message], validation='EXPERIMENTAL')
        engine.write_json(state_path, state)
        return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--replay', type=Path, help='Análise offline; sem Telegram ou gravação de sinais')
    args = parser.parse_args()
    if args.replay:
        snapshot = json.loads(args.replay.read_text())
        macro = {'blocks':['REPLAY OFFLINE — não é sinal ao vivo.'], 'headlines':[], 'sources':[], 'calendar_ok':False, 'events':[], 'coverage':'Replay de dados históricos, sem notícias da época.'}
        result = engine.analyze(snapshot, macro)
        result.update(ok=True, live=False, history=[], prices=snapshot['5m'][-100:], notification='Desativado em replay')
        engine.write_json(engine.DATA_DIR/'status.json', result)
        print(json.dumps({k: result[k] for k in ('action','checked_at','blocks','readings')}, ensure_ascii=False, indent=2))
        return
    engine.DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Prevent two monitor processes from sending the same alert.
    import fcntl
    with open(engine.DATA_DIR/'worker.lock','w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Já há um worker usando este diretório.')
        while True:
            state = run_cycle()
            print(datetime.now(timezone.utc).isoformat(), state['action'], 'OK' if state['ok'] else state['blocks'][0], flush=True)
            if args.once:
                break
            time.sleep(15 if state['ok'] else 60)


if __name__ == '__main__':
    main()
