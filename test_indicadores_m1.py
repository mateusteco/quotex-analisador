"""Testes de regressao dos indicadores com velas sinteticas."""
import unittest
from indicadores_m1 import IndicadoresM1
from stream_m1 import Candle

class TestIndicadoresM1(unittest.TestCase):
    def test_aquecimento(self):
        calc = IndicadoresM1()
        for minuto in range(21):
            preco = 1.0 + minuto * 0.0001
            self.assertIsNone(calc.processar(Candle(minuto * 60, preco, preco, preco, preco)))

    def test_valores_calculados(self):
        calc = IndicadoresM1()
        resultado = None
        for minuto in range(30):
            preco = 1.0 + minuto * 0.0001
            resultado = calc.processar(Candle(minuto * 60, preco, preco, preco, preco))
        self.assertIsNotNone(resultado)
        self.assertAlmostEqual(resultado["preco"], 1.0029)
        self.assertGreater(resultado["mm9"], resultado["mm21"])
        self.assertEqual(resultado["rsi14"], 100.0)
        self.assertIsNone(resultado["sinal_teorico"])

    def test_mercado_lateral(self):
        calc = IndicadoresM1()
        for minuto in range(30):
            resultado = calc.processar(Candle(minuto * 60, 1.0, 1.0, 1.0, 1.0))
        self.assertEqual(resultado["rsi14"], 50.0)
        self.assertIsNone(resultado["sinal_teorico"])

if __name__ == "__main__":
    unittest.main()
