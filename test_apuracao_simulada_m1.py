"""Testes offline da apuração sem ordens e sem Telegram."""
import unittest
from stream_m1 import Candle
from apuracao_simulada_m1 import ApuradorM1
from alertas_simulacao import formatar_alerta

def vela(inicio, abertura, fechamento):
    return Candle(inicio, abertura, max(abertura, fechamento),
                  min(abertura, fechamento), fechamento)

class TesteApuracao(unittest.TestCase):
    def test_win_call(self):
        a = ApuradorM1()
        self.assertTrue(a.registrar_sinal({"inicio": 60, "sinal_teorico": "CALL"}))
        r = a.processar_candle(vela(120, 1.0, 1.1))
        self.assertEqual(r["resultado"], "WIN")
        self.assertIn("WIN", r["mensagem"])

    def test_loss_put(self):
        a = ApuradorM1()
        a.registrar_sinal({"inicio": 60, "sinal_teorico": "PUT"})
        self.assertEqual(a.processar_candle(vela(120, 1.0, 1.1))["resultado"], "LOSS")

    def test_empate(self):
        a = ApuradorM1()
        a.registrar_sinal({"inicio": 60, "sinal_teorico": "CALL"})
        self.assertEqual(a.processar_candle(vela(120, 1.0, 1.0))["resultado"], "EMPATE")

    def test_nao_duplicar(self):
        a = ApuradorM1()
        a.registrar_sinal({"inicio": 60, "sinal_teorico": "CALL"})
        self.assertFalse(a.registrar_sinal({"inicio": 60, "sinal_teorico": "PUT"}))
        a.processar_candle(vela(120, 1.0, 1.1))
        self.assertIsNone(a.processar_candle(vela(120, 1.0, 1.1)))
        self.assertEqual(len(a.resultados), 1)

    def test_lacuna_sem_resultado(self):
        a = ApuradorM1()
        a.registrar_sinal({"inicio": 60, "sinal_teorico": "CALL"})
        self.assertIsNone(a.processar_candle(vela(180, 1.0, 1.1)))
        self.assertEqual(a.resultados, [])

    def test_mensagem_simulacao(self):
        mensagem = formatar_alerta({"inicio": 60, "sinal_teorico": "PUT",
                                    "preco": 1.0, "mm9": 1.1, "mm21": 1.2, "rsi14": 40})
        self.assertIn("SEM MARTINGALE", mensagem)
        self.assertIn("SIMULAÇÃO", mensagem)
        self.assertIn("Brasília", mensagem)

if __name__ == "__main__":
    unittest.main()
