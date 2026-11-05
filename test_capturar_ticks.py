"""Testa persistência de cotações sem rede nem credenciais reais."""
import csv
import io
import unittest
from unittest.mock import patch
import requests
from capturar_ticks import capturar, gravar_eventos
from otcharts_stream import SYMBOL


class TestCaptura(unittest.TestCase):
    def test_registra_timestamp_preco_recebimento_e_filtra_outros_pares(self):
        eventos = [('connected', {}), ('tick', {'symbol': 'AUDUSD_otc', 'time': 120, 'price': 9}),
                   ('tick', {'symbol': SYMBOL, 'time': 120, 'price': 'NaN'}),
                   ('tick', {'symbol': SYMBOL, 'time': 1793836800125, 'price': '0.81933'})]
        arquivo = io.StringIO()
        total = gravar_eventos(eventos, arquivo, relogio=lambda: 1793836800.875)
        self.assertEqual(total, 1)
        arquivo.seek(0)
        row = list(csv.DictReader(arquivo))[0]
        self.assertEqual(row['preco'], '0.81933')
        self.assertEqual(row['latencia_ms'], '750.0')
        self.assertEqual(row['horario_tick_utc'], '2026-11-05T00:00:00.125+00:00')
        self.assertEqual(row['recebido_utc'], '2026-11-05T00:00:00.875+00:00')

    def test_interrupcao_nao_aprova_captura(self):
        with self.assertRaisesRegex(RuntimeError, 'parcial'):
            gravar_eventos([('dropped', {})], io.StringIO())

    @patch.dict('os.environ', OTCHARTS_API_KEY='falso')
    @patch('capturar_ticks.requests.get', side_effect=requests.Timeout('segredo-falso'))
    def test_erro_de_rede_nao_expoe_credenciais(self, cliente):
        with self.assertRaises(RuntimeError) as erro:
            capturar(10, '/tmp/nexus-test-captura/ticks.csv')
        self.assertNotIn('segredo-falso', str(erro.exception))
