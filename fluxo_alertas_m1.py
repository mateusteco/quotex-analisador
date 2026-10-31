"""Fluxo M1: ticks -> vela fechada -> indicadores -> sinais e resultados simulados.
Nenhuma ordem real. Telegram de sinais somente quando habilitado explicitamente.
Resultados são armazenados em memória, sem envio automático.
"""
from stream_m1 import M1Builder
from indicadores_m1 import IndicadoresM1
from alertas_simulacao import formatar_alerta, enviar_alerta
from apuracao_simulada_m1 import ApuradorM1

class FluxoM1:
    def __init__(self, enviar_telegram=False, sessao=None):
        self.builder = M1Builder()
        self.indicadores = IndicadoresM1()
        self.apurador = ApuradorM1()
        self.enviar_telegram = enviar_telegram
        self.sessao = sessao
        self.ultimo_alerta = None

    def tick(self, timestamp, preco):
        candle = self.builder.adicionar(timestamp, preco)
        if candle is None:
            return None
        # Apura a vela posterior antes de avaliar um novo sinal.
        self.apurador.processar_candle(candle)
        leitura = self.indicadores.processar(candle)
        if leitura is None:
            return None
        mensagem = formatar_alerta(leitura)
        if mensagem is None:
            return None
        chave = (leitura["inicio"], leitura["sinal_teorico"])
        if chave == self.ultimo_alerta:
            return None
        # Evita sinais sobrepostos enquanto a vela de avaliação não encerrou.
        if not self.apurador.registrar_sinal(leitura):
            return None
        if self.enviar_telegram:
            enviar_alerta(leitura, sessao=self.sessao)
        self.ultimo_alerta = chave
        return mensagem
