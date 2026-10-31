"""Teste isolado do Telegram: nenhum envio externo, sem ordens."""
import os
import unittest
from unittest.mock import patch
from alertas_simulacao import enviar_resultado
from fluxo_alertas_m1 import FluxoM1
from stream_m1 import Candle

class Resposta:
    def raise_for_status(self): pass
    def json(self): return {"ok": True}

class Sessao:
    def __init__(self): self.envios = []
    def post(self, url, json, timeout):
        self.envios.append((url, json, timeout))
        return Resposta()

class TesteTelegramResultado(unittest.TestCase):
    def test_envia_resultado_simulado(self):
        sessao = Sessao()
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token-teste", "TELEGRAM_CHAT_ID": "chat-teste"}):
            self.assertTrue(enviar_resultado({"mensagem": "🏆 WIN SIMULADO"}, sessao=sessao))
        self.assertEqual(len(sessao.envios), 1)
        self.assertEqual(sessao.envios[0][1]["text"], "🏆 WIN SIMULADO")

    def test_fluxo_desligado_nao_envia(self):
        sessao = Sessao()
        fluxo = FluxoM1(enviar_telegram=False, sessao=sessao)
        fluxo.apurador.registrar_sinal({"inicio": 60, "sinal_teorico": "CALL"})
        fluxo.builder.atual = Candle(120, 1.0, 1.1, 1.0, 1.1)
        fluxo.tick(180, 1.2)
        self.assertEqual(len(fluxo.apurador.resultados), 1)
        self.assertEqual(sessao.envios, [])

    def test_fluxo_habilitado_envia_resultado(self):
        sessao = Sessao()
        fluxo = FluxoM1(enviar_telegram=True, sessao=sessao)
        fluxo.apurador.registrar_sinal({"inicio": 60, "sinal_teorico": "CALL"})
        fluxo.builder.atual = Candle(120, 1.0, 1.1, 1.0, 1.1)
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token-teste", "TELEGRAM_CHAT_ID": "chat-teste"}):
            fluxo.tick(180, 1.2)
        self.assertEqual(len(sessao.envios), 1)
        self.assertIn("WIN", sessao.envios[0][1]["text"])

if __name__ == "__main__":
    unittest.main()
