"""Apuração de uma única vela M1 posterior ao sinal, apenas em simulação."""
from alertas_simulacao import formatar_resultado

class ApuradorM1:
    def __init__(self):
        self.pendente = None
        self.resultados = []

    def registrar_sinal(self, leitura):
        direcao = leitura.get("sinal_teorico")
        if direcao not in ("CALL", "PUT") or self.pendente is not None:
            return False
        self.pendente = {"direcao": direcao, "inicio_esperado": int(leitura["inicio"]) + 60}
        return True

    def processar_candle(self, candle):
        if self.pendente is None:
            return None
        esperado = self.pendente["inicio_esperado"]
        if candle.inicio < esperado:
            return None
        if candle.inicio > esperado:
            # Falta de dados: não inventar preço de entrada ou resultado.
            self.pendente = None
            return None
        direcao = self.pendente["direcao"]
        entrada, saida = float(candle.open), float(candle.close)
        resultado = "EMPATE" if entrada == saida else (
            "WIN" if (saida > entrada) == (direcao == "CALL") else "LOSS"
        )
        registro = {"inicio": candle.inicio, "direcao": direcao,
                    "entrada": entrada, "saida": saida, "resultado": resultado,
                    "mensagem": formatar_resultado(direcao, entrada, saida)}
        self.resultados.append(registro)
        self.pendente = None
        return registro
