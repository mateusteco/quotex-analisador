import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import futures_engine as e
from futures_worker import run_cycle

FIXTURE = Path(__file__).with_name('binance_snapshot.json')

class FuturesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = e.DATA_DIR
        e.DATA_DIR = Path(self.tmp.name)
        self.s = json.loads(FIXTURE.read_text())
        self.m = dict(blocks=[],sources=[],headlines=[],calendar_ok=True,events=[],coverage='test only')
    def tearDown(self):
        e.DATA_DIR = self.old
        self.tmp.cleanup()
    def signal(self):
        now=self.s['now']
        return dict(symbol='BTCUSDT',signal_id='sample', checked_at=now, expires_at=now+120000, action='COMPRA', plan=dict(entry=100.,stop=98.,target1=102.,target2=104.,atr=2.,risk=2.,sign=1))
    def paperbars(self, start, opening=100., high=105., low=97., close=102.):
        return [[start,str(opening),str(high),str(low),str(close),'10',start+299999,'0',1,'5','0','0']]
    def test_real_binance_snapshot_is_processed(self):
        result=e.analyze(self.s,self.m)
        self.assertEqual(result['action'],'AGUARDAR')
        self.assertEqual(len(result['readings']),4)
        self.assertIsNone(result['probability'])
        self.assertTrue(result['blocks'])
    def test_open_candle_excluded(self):
        rows=e.candles(self.s['5m'],'5m',self.s['now'])
        self.assertTrue(all(r['end']<=self.s['now']-2000 for r in rows))
    def test_future_candle_never_changes_signal(self):
        before=e.analyze(self.s,self.m)
        after=copy.deepcopy(self.s)
        row=after['5m'][-1]
        self.assertGreater(row[6],after['now'])
        row[1:5]=['90000','99999','1','90000']
        self.assertEqual(before['readings'],e.analyze(after,self.m)['readings'])
    def test_missing_bar_blocks(self):
        del self.s['5m'][-5]
        with self.assertRaises(e.DataError): e.analyze(self.s,self.m)
    def test_duplicate_blocks(self):
        self.s['1h'].append(self.s['1h'][-2])
        with self.assertRaises(e.DataError): e.analyze(self.s,self.m)
    def test_invalid_ohlc_blocks(self):
        self.s['5m'][-2][2]='1'
        with self.assertRaises(e.DataError): e.analyze(self.s,self.m)
    def test_nan_blocks(self):
        self.s['5m'][-2][4]='NaN'
        with self.assertRaises(e.DataError): e.analyze(self.s,self.m)
    def test_stale_snapshot_blocks(self):
        self.s['now']+=1000000
        with self.assertRaises(e.DataError): e.analyze(self.s,self.m)
    def test_stale_derivatives_block(self):
        self.s['oi'][-1]['timestamp']-=9999999
        with self.assertRaises(e.DataError): e.analyze(self.s,self.m)
    def test_crossed_book_blocks(self):
        self.s['book']['asks'][0][0]=self.s['book']['bids'][0][0]
        with self.assertRaises(e.DataError): e.analyze(self.s,self.m)
    def test_macro_block_propagates(self):
        self.m['blocks']=['FOMC in blackout']
        r=e.analyze(self.s,self.m)
        self.assertIn('FOMC in blackout',r['blocks'])
        self.assertEqual(r['action'],'AGUARDAR')
    def test_rsi_rising_and_flat(self):
        rows=[dict(open=i+1,high=i+2,low=i+.5,close=i+1,volume=10,time=i) for i in range(300)]
        self.assertEqual(e.technical(rows)['rsi'],100)
        for row in rows: row.update(open=100,high=101,low=99,close=100)
        self.assertEqual(e.technical(rows)['rsi'],50)
    def test_dedup_and_single_active(self):
        signal=self.signal()
        self.assertTrue(e.save_signal(signal))
        self.assertFalse(e.save_signal(signal))
        signal['signal_id']='other'
        self.assertFalse(e.save_signal(signal))
        self.assertEqual(len(e.history()),1)
    def test_wait_not_saved(self):
        signal=self.signal();signal['action']='AGUARDAR'
        self.assertFalse(e.save_signal(signal))
    def test_stop_first_when_both_hit(self):
        s=self.signal();e.save_signal(s)
        start=(s['checked_at']//300000+1)*300000
        e.paper_update(self.paperbars(start),start+305000)
        row=e.history()[0]
        self.assertEqual(row['status'],'STOP')
        self.assertLess(row['pnl_r_before_funding'],-1)
    def test_entry_drift_cancels(self):
        s=self.signal();e.save_signal(s)
        start=(s['checked_at']//300000+1)*300000
        e.paper_update(self.paperbars(start,opening=101),start+305000)
        self.assertEqual(e.history()[0]['status'],'CANCELLED_DRIFT')
    def test_open_candle_cannot_close_paper(self):
        s=self.signal();e.save_signal(s)
        start=(s['checked_at']//300000+1)*300000
        # supply a completed previous bar as normal collection does
        bars=self.paperbars(start-300000,high=101,low=99,close=100)+self.paperbars(start)
        e.paper_update(bars,start+100000)
        self.assertEqual(e.history()[0]['status'],'PENDING')
    def test_missing_entry_history_is_flagged(self):
        s=self.signal();e.save_signal(s)
        start=(s['checked_at']//300000+2)*300000
        e.paper_update(self.paperbars(start),start+305000)
        self.assertEqual(e.history()[0]['status'],'DATA_GAP')
    def test_funding_long_short_and_partial_coverage(self):
        for sign in (1,-1):
            r=dict(payload=dict(paper_entry_at=100,paper_exit_at=300,plan=dict(sign=sign,stop=98)),entry=100,pnl_r_before_funding=2)
            f=[dict(fundingTime=200,fundingRate='.001',markPrice='100')]
            out=e.settle_funding([r],f,0,400)[0]
            self.assertAlmostEqual(out['pnl_r'],2-sign*.05)
            self.assertNotIn('pnl_r',e.settle_funding([r],f,150,400)[0])
    def test_no_telegram_without_credentials(self):
        with patch.dict('os.environ',{},clear=True),patch.object(e,'request') as request:
            self.assertIn('não configurado',e.notify_pending(self.s['now']))
            request.assert_not_called()
    def test_telegram_dedup_and_expiration(self):
        s=self.signal();e.save_signal(s)
        with patch.dict('os.environ',{'TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHAT_ID':'1'}),patch.object(e,'request',return_value={'ok':True}) as req:
            e.notify_pending(s['checked_at']);e.notify_pending(s['checked_at'])
            self.assertEqual(req.call_count,1)
        with e.connect() as db: db.execute('UPDATE signals SET notified=0')
        with patch.dict('os.environ',{'TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHAT_ID':'1'}),patch.object(e,'request') as req:
            e.notify_pending(s['expires_at']+1);req.assert_not_called()
    def test_telegram_error_hides_token(self):
        s=self.signal();e.save_signal(s)
        with patch.dict('os.environ',{'TELEGRAM_BOT_TOKEN':'SECRET','TELEGRAM_CHAT_ID':'1'}),patch.object(e,'request',side_effect=RuntimeError('https://tokenSECRET')):
            self.assertNotIn('SECRET',e.notify_pending(s['checked_at']))
    def test_worker_fail_closed(self):
        with patch.object(e,'collect',side_effect=e.DataError('Fonte indisponível')):
            state=run_cycle()
        self.assertFalse(state['ok'])
        self.assertEqual(state['action'],'AGUARDAR')
        self.assertFalse(json.loads((e.DATA_DIR/'status.json').read_text())['ok'])
    def test_valid_setup_can_emit_long_and_short(self):
        for sign in (1,-1):
            snapshot=copy.deepcopy(self.s)
            now=(snapshot['now']//14400000)*14400000+10000
            snapshot['now']=now
            for tf,step in e.INTERVALS.items():
                end=now//step*step
                snapshot[tf]=[[end-(300-i)*step,'80000','80050','79950','80000','10',end-(299-i)*step-1] for i in range(300)]
                if tf=='5m':
                    # Swing allows 1.5ATR stop without a barrier to target.
                    for row in snapshot[tf][-6:]:row[2:4]=['80100','79900']
            snapshot['mark']['time']=now
            snapshot['mark']['lastFundingRate']='.00001'
            snapshot['book'].update(T=now,bids=[['79999.9','1']],asks=[['80000.1','1']])
            snapshot['oi'][-2].update(timestamp=now-300000,sumOpenInterest='100')
            snapshot['oi'][-1].update(timestamp=now,sumOpenInterest='101')
            snapshot['taker'][-1].update(timestamp=now,buyVol='60' if sign==1 else '40',sellVol='40' if sign==1 else '60')
            snapshot['ratio'][-1]['timestamp']=now
            reading=dict(close=80000,trend='ALTA' if sign==1 else 'BAIXA',rsi=60 if sign==1 else 40,atr=400,ema20=80000,volume_ratio=1.5)
            with patch.object(e,'technical',return_value=reading):
                result=e.analyze(snapshot,self.m)
            self.assertEqual(result['action'],'COMPRA' if sign==1 else 'VENDA',result['blocks'])
    def test_feeds_failure_blocks_and_calendar_expires(self):
        with patch('urllib.request.urlopen',side_effect=OSError()):
            macro=e.macro_context(self.s['now'])
        self.assertFalse(macro['calendar_ok'])
        self.assertTrue(macro['blocks'])

if __name__=='__main__': unittest.main()
