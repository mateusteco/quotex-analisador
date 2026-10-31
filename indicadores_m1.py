"""Indicadores exploratorios para candles M1 fechados. Sem ordens."""
from collections import deque

class IndicadoresM1:
    def __init__(self):
        self.fechamentos = deque(maxlen=120)

    def processar(self, candle):
        self.fechamentos.append(float(candle.close))
        p = list(self.fechamentos)
        if len(p) < 22:
            return None
        mm9 = sum(p[-9:]) / 9
        mm21 = sum(p[-21:]) / 21
        mudancas = [p[i] - p[i-1] for i in range(len(p)-14, len(p))]
        ganhos = sum(max(v, 0) for v in mudancas) / 14
        perdas = sum(max(-v, 0) for v in mudancas) / 14
        rsi = 100.0 if perdas == 0 and ganhos > 0 else (50.0 if ganhos == perdas == 0 else 100 - 100 / (1 + ganhos / perdas))
        direcao = None
        if mm9 > mm21 and p[-1] > mm9 and 50 < rsi < 70:
            direcao = "CALL"
        elif mm9 < mm21 and p[-1] < mm9 and 30 < rsi < 50:
            direcao = "PUT"
        return {"inicio": candle.inicio, "preco": p[-1], "mm9": mm9, "mm21": mm21, "rsi14": rsi, "sinal_teorico": direcao}

if __name__ == "__main__":
    from stream_m1 import Candle
    i = IndicadoresM1()
    for n in range(30):
        preco = 1.0 + n * 0.001
        saida = i.processar(Candle(n*60, preco, preco, preco, preco))
    assert saida is not None and 0 <= saida["rsi14"] <= 100
    print("Indicadores M1: teste basico aprovado; sem ordens.")
