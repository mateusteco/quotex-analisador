"""Teste integrado offline: ticks sinteticos, M1, indicadores e alertas."""
import unittest
from unittest.mock import patch
from fluxo_alertas_m1 import FluxoM1

class TestFluxo(unittest.TestCase):
    def test_sem_aquecimento_sem_alerta(self):
        fluxo = FluxoM1()
        for minuto in range(10):
            self.assertIsNone(fluxo.tick(minuto * 60, 1 + minuto * 0.0001))

    def test_fluxo_com_alerta_teorico_sem_rede(self):
        fluxo = FluxoM1()
        mensagens = []
        # Oscilacao gradual evita RSI saturado e permite sinais condicionais.
        precos = [1.0]
        for i in range(1, 100):
            precos.append(precos[-1] + (0.0006 if i % 5 != 0 else -0.0011))
        for minuto, preco in enumerate(precos):
            resultado = fluxo.tick(minuto * 60, preco)
            if resultado:
                mensagens.append(resultado)
        self.assertGreater(len(mensagens), 0)
        self.assertTrue(all("SIMULACAO" in m for m in mensagens))
        self.assertTrue(all(("CALL" in m or "PUT" in m) for m in mensagens))

    def test_telegram_desligado_por_padrao(self):
        with patch("fluxo_alertas_m1.enviar_alerta", side_effect=AssertionError("rede proibida")):
            fluxo = FluxoM1()
            for i in range(100):
                fluxo.tick(i * 60, 1.0 + i * 0.0001)

if __name__ == "__main__":
    unittest.main()
