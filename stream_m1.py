"""Agregacao de ticks em candles M1 para testes; nao envia ordens."""
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite

@dataclass
class Candle:
    inicio: int
    open: float
    high: float
    low: float
    close: float
    ticks: int = 1

class M1Builder:
    def __init__(self):
        self.atual = None

    def adicionar(self, timestamp, preco):
        """Retorna candle fechado ao mudar de minuto, ou None."""
        ts = int(timestamp)
        price = float(preco)
        if not isfinite(price) or price <= 0:
            raise ValueError("Preco invalido")
        minuto = (ts // 60) * 60
        if self.atual is None:
            self.atual = Candle(minuto, price, price, price, price)
            return None
        if minuto < self.atual.inicio:
            return None  # Ignora tick atrasado para nao alterar candle historico.
        if minuto > self.atual.inicio:
            fechado = self.atual
            self.atual = Candle(minuto, price, price, price, price)
            return fechado
        c = self.atual
        c.high = max(c.high, price)
        c.low = min(c.low, price)
        c.close = price
        c.ticks += 1
        return None

if __name__ == "__main__":
    b = M1Builder()
    assert b.adicionar(120, 0.19500) is None
    assert b.adicionar(121, 0.19508) is None
    assert b.adicionar(122, 0.19503) is None
    c = b.adicionar(180, 0.19510)
    assert (c.inicio, c.open, c.high, c.low, c.close, c.ticks) == (120, 0.19500, 0.19508, 0.19500, 0.19503, 3)
    assert b.adicionar(150, 0.19400) is None
    print("Teste local de agregacao M1 aprovado; nenhuma ordem enviada.")
