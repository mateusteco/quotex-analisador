import json
import sys
import tempfile
import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import futures_engine as e

class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=e.DATA_DIR
        e.DATA_DIR=Path(self.tmp.name)
    def tearDown(self):
        e.DATA_DIR=self.old
        self.tmp.cleanup()
    def test_no_worker_shows_waiting(self):
        app=AppTest.from_file(str(ROOT/'app.py')).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(any('Aguardando' in x.value for x in app.info))
    def test_offline_is_explicit_and_chart_renders(self):
        snapshot=json.loads((ROOT/'tests/binance_snapshot.json').read_text())
        macro=dict(blocks=['REPLAY OFFLINE'],sources=[],headlines=[],calendar_ok=False,events=[],coverage='Offline')
        data=e.analyze(snapshot,macro)
        data.update(ok=True,live=False,history=[],prices=snapshot['5m'][-100:])
        e.write_json(e.DATA_DIR/'status.json',data)
        app=AppTest.from_file(str(ROOT/'app.py')).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(any('REPLAY OFFLINE' in x.value for x in app.error))
        self.assertEqual(len(app.dataframe),1)
    def test_calendar_form_writes_review(self):
        app=AppTest.from_file(str(ROOT/'app.py')).run(timeout=30)
        app.checkbox[0].check()
        app.text_area[0].set_value('2026-11-06 10:30 | Teste de agenda')
        app.button[0].click().run(timeout=30)
        self.assertFalse(app.exception)
        config=json.loads((e.DATA_DIR/'events.json').read_text())
        self.assertEqual(config['events'][0]['name'],'Teste de agenda')
        self.assertGreater(config['reviewed_at'],0)

if __name__=='__main__':unittest.main()
