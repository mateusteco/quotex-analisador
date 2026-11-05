"""Regressões temporais e contrato de integração, sempre offline."""
import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, MagicMock, patch
import requests
from alertas_simulacao import enviar_alerta, formatar_resultado
from fluxo_alertas_m1 import FluxoM1
from indicadores_m1 import IndicadoresM1
from otcharts_stream import SYMBOL, timestamp_segundos, normalizar_tick, eventos_sse
from stream_m1 import Candle, M1Builder
from teste_integrado_m1 import executar

BASE = 1793836800  # 2026-11-05 UTC, alinhado com o minuto
LEITURA = dict(inicio=BASE, preco=1, mm9=1, mm21=1, rsi14=60, sinal_teorico='CALL')


class TestTemporal(unittest.TestCase):
    def fluxo(self, **kwargs):
        f = FluxoM1(relogio=lambda: BASE + 61, **kwargs)
        f.indicadores.processar = Mock(return_value=dict(LEITURA))
        f.tick(BASE, 1, recebido_em=BASE)
        return f

    def test_normalizacao_segundos_ms_iso(self):
        for valor in (BASE, str(BASE), BASE * 1000, '2026-11-05T00:00:00Z'):
            self.assertEqual(timestamp_segundos(valor), BASE)
        for valor in (None, True, -1, 'NaN', 'inf', '2026-11-05T00:00:00', 1e18):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                timestamp_segundos(valor)

    def test_simbolo_e_precos(self):
        self.assertEqual(normalizar_tick(dict(symbol=SYMBOL, time=BASE*1000, price='1.1')), (BASE, 1.1))
        self.assertIsNone(normalizar_tick(dict(symbol='BRLUSD_otc', time=BASE, price=1)))
        for preco in (True, None, 'NaN', 'inf', 0, -1):
            with self.subTest(preco=preco), self.assertRaises(ValueError):
                normalizar_tick(dict(symbol=SYMBOL, time=BASE, price=preco))

    def test_sse_limites_multilinha_heartbeat(self):
        linhas = [': ping', 'event: connected', 'data: {"symbols": ["AUDUSD_otc"]}', '',
                  'event: tick', 'data: {"symbol": "AUDUSD_otc",',
                  'data: "time": 123, "price": 1}', '', 'data: {"x": 1}', '']
        eventos = list(eventos_sse(linhas))
        self.assertEqual([x[0] for x in eventos], ['connected', 'tick', 'message'])
        self.assertEqual(eventos[1][1]['time'], 123)
        with self.assertRaises(ValueError):
            list(eventos_sse(['data: inválido', '']))

    def test_ticks_atrasados_futuros_nao_alteram_estado(self):
        f = self.fluxo()
        for ts, recebido in ((BASE + 60, BASE + 66), (BASE + 70, BASE + 69), (BASE - 1, BASE)):
            self.assertIsNone(f.tick(ts, 2, recebido_em=recebido))
        self.assertEqual(f.builder.atual.close, 1)
        self.assertEqual(f.metricas['ticks_rejeitados'], 3)
        self.assertIsNone(f.apurador.pendente)

    def test_horarios_latencia_e_texto_retrospectivo(self):
        f = self.fluxo()
        m = f.tick(BASE + 60.25, 1.1, recebido_em=BASE + 61)
        self.assertIn('NZDCAD_otc', m)
        self.assertNotIn('AUDUSD_otc', m)
        self.assertIn('2026-11-04 21:01:00.000 UTC-03:00', m)
        self.assertIn('Não é entrada futura', m)
        self.assertNotIn('Entrada única', m)
        self.assertEqual(f.metricas['latencia_tick_ms'], 750)
        self.assertEqual(f.metricas['latencia_fechamento_ms'], 1000)
        self.assertEqual(f.ultima_leitura['recebido_em'], BASE + 61)
        self.assertIsNone(f.tick(BASE + 61, 1.2, recebido_em=BASE + 61))

    def test_tick_recente_nao_reabilita_sinal_de_vela_antiga(self):
        f = self.fluxo()
        self.assertIsNone(f.tick(BASE + 70, 1.1, recebido_em=BASE + 70))
        self.assertIsNone(f.apurador.pendente)

    def test_lacuna_nao_produz_sinal(self):
        f = self.fluxo()
        self.assertIsNone(f.tick(BASE + 120, 1.1, recebido_em=BASE + 120))
        self.assertIsNone(f.apurador.pendente)
        i = IndicadoresM1()
        for n in range(22):
            i.processar(Candle(BASE + n*60, 1, 1, 1, 1))
        self.assertIsNone(i.processar(Candle(BASE + 24*60, 1, 1, 1, 1)))
        self.assertEqual(len(i.fechamentos), 1)

    def test_builder_nao_reverte_close_dentro_do_minuto(self):
        b = M1Builder()
        b.adicionar(BASE + 0.9, 1)
        b.adicionar(BASE + 0.1, 9)
        self.assertEqual(b.atual.close, 1)
        for ts in (float('nan'), float('inf'), -1):
            with self.assertRaises(ValueError):
                b.adicionar(ts, 1)

    @patch.dict(os.environ, TELEGRAM_BOT_TOKEN='segredo-falso', TELEGRAM_CHAT_ID='chat')
    def test_telegram_sinal_resultado_simbolo_horarios(self):
        sessao = Mock()
        sessao.post.return_value.json.return_value = {'ok': True}
        f = self.fluxo(enviar_telegram=True, sessao=sessao)
        f.tick(BASE + 60, 1.1, recebido_em=BASE + 61)
        f.indicadores.processar.return_value = None
        f.tick(BASE + 90, 1.2, recebido_em=BASE + 91)
        f.tick(BASE + 120, 1.3, recebido_em=BASE + 121)
        self.assertEqual(sessao.post.call_count, 2)
        mensagens = [c.kwargs['json']['text'] for c in sessao.post.call_args_list]
        self.assertTrue(all(SYMBOL in m for m in mensagens))
        self.assertIn('WIN', mensagens[1])
        self.assertIn('Vela avaliada', mensagens[1])
        self.assertEqual(f.metricas['telegram_confirmados'], 2)

    @patch.dict(os.environ, TELEGRAM_BOT_TOKEN='segredo-falso', TELEGRAM_CHAT_ID='chat')
    def test_falha_http_sem_vazar_token_nem_duplicar(self):
        sessao = Mock()
        sessao.post.side_effect = requests.Timeout('https://api.telegram.org/botsegredo-falso/sendMessage')
        with self.assertRaises(RuntimeError) as erro:
            enviar_alerta(LEITURA, sessao=sessao)
        self.assertNotIn('segredo-falso', str(erro.exception))
        f = self.fluxo(enviar_telegram=True, sessao=sessao)
        self.assertIsNotNone(f.tick(BASE + 60, 1.1, recebido_em=BASE + 61))
        self.assertIsNone(f.tick(BASE + 61, 1.2, recebido_em=BASE + 62))
        self.assertEqual(f.metricas['telegram_falhas'], 1)
        self.assertEqual(f.metricas['telegram_confirmados'], 0)

    @patch.dict(os.environ, TELEGRAM_BOT_TOKEN='segredo-falso', TELEGRAM_CHAT_ID='chat')
    def test_telegram_ok_false_e_json_invalido(self):
        sessao = Mock()
        sessao.post.return_value.json.return_value = {'ok': False}
        with self.assertRaises(RuntimeError):
            enviar_alerta(LEITURA, sessao=sessao)
        sessao.post.return_value.json.side_effect = ValueError('corpo secreto')
        with self.assertRaises(RuntimeError) as erro:
            enviar_alerta(LEITURA, sessao=sessao)
        self.assertNotIn('corpo secreto', str(erro.exception))

    def test_resultado_rejeita_precos_nao_finitos(self):
        for preco in (float('nan'), float('inf'), 0):
            with self.assertRaises(ValueError):
                formatar_resultado('CALL', preco, 1)

    @patch.dict(os.environ, OTCHARTS_API_KEY='chave-falsa', ENVIAR_TELEGRAM_SIMULACAO='0')
    def test_sondagem_integrada_offline_e_contrato_http(self):
        cliente = MagicMock()
        resposta = cliente.get.return_value.__enter__.return_value
        linhas = ['event: connected', 'data: {}', '']
        for n in range(10):
            linhas += ['event: tick', f'data: {{"symbol":"{SYMBOL}","time":{BASE+n},"price":1}}', '']
        resposta.iter_lines.return_value = iter(linhas)
        with redirect_stdout(io.StringIO()):
            r = executar(cliente=cliente, relogio=Mock(side_effect=[BASE] + [BASE+n for n in range(10)]), exigir_m1=False)
        self.assertEqual(r['ticks_aceitos'], 10)
        self.assertEqual(cliente.get.call_args.kwargs['params'], {'venue': 'quotex', 'symbol': SYMBOL})
        self.assertEqual(cliente.get.call_args.kwargs['headers']['Authorization'], 'Bearer chave-falsa')
        cliente.post.assert_not_called()

    @patch.dict(os.environ, OTCHARTS_API_KEY='chave-falsa', ENVIAR_TELEGRAM_SIMULACAO='1',
                TELEGRAM_BOT_TOKEN='token-falso', TELEGRAM_CHAT_ID='chat')
    def test_ciclo_integrado_sse_m1_telegram_offline(self):
        cliente = MagicMock()
        cliente.post.return_value.json.return_value = {'ok': True}
        resposta = cliente.get.return_value.__enter__.return_value
        agora = [BASE]
        def linhas():
            yield 'event: connected'
            yield 'data: {}'
            yield ''
            preco = 1.0
            for n in range(100):
                if n:
                    preco += 0.0006 if n % 5 != 0 else -0.0011
                agora[0] = BASE + n*60
                yield 'event: tick'
                yield f'data: {{"symbol":"{SYMBOL}","time":{agora[0]},"price":{preco}}}'
                yield ''
        resposta.iter_lines.return_value = linhas()
        with redirect_stdout(io.StringIO()):
            r = executar(cliente=cliente, relogio=lambda: agora[0], monotonic=lambda: 0)
        self.assertGreaterEqual(r['candles_fechados'], 22)
        self.assertGreaterEqual(r['resultados'], 1)
        self.assertGreaterEqual(r['telegram_confirmados'], 2)
        self.assertEqual(r['telegram_falhas'], 0)
        self.assertEqual(r['latencia_tick_ms'], 0)

    @patch.dict(os.environ, OTCHARTS_API_KEY='chave-falsa')
    def test_stream_vazio_nao_aprova_integracao(self):
        cliente = MagicMock()
        cliente.get.return_value.__enter__.return_value.iter_lines.return_value = []
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'inconclusivo'):
            executar(cliente=cliente, exigir_m1=False)
