"""Testes unitarios do agregador de candles M1."""
import unittest
from stream_m1 import M1Builder

class TestM1(unittest.TestCase):
    def test_virada_de_minuto(self):
        b = M1Builder()
        self.assertIsNone(b.adicionar(120, 1.0))
        self.assertIsNone(b.adicionar(125, 1.2))
        self.assertIsNone(b.adicionar(130, 0.9))
        c = b.adicionar(180, 1.1)
        self.assertEqual((c.inicio, c.open, c.high, c.low, c.close, c.ticks), (120, 1.0, 1.2, 0.9, 0.9, 3))

    def test_atrasado_ignorado(self):
        b = M1Builder()
        b.adicionar(180, 1.0)
        self.assertIsNone(b.adicionar(120, 2.0))
        self.assertEqual(b.atual.close, 1.0)

    def test_preco_invalido(self):
        b = M1Builder()
        with self.assertRaises(ValueError):
            b.adicionar(120, -1)

if __name__ == "__main__":
    unittest.main()
