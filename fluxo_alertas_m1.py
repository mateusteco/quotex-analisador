"""Ticks recentes -> alertas retrospectivos e resultados exclusivamente simulados."""
import time
from math import isfinite
from stream_m1 import M1Builder
from indicadores_m1 import IndicadoresM1
from alertas_simulacao import formatar_alerta, enviar_alerta, enviar_resultado
from apuracao_simulada_m1 import ApuradorM1
from otcharts_stream import SYMBOL, timestamp_segundos


class FluxoM1:
    def __init__(self, enviar_telegram=False, sessao=None, *, simbolo=SYMBOL,
                 relogio=time.time, max_atraso=5.0):
        if not isfinite(max_atraso) or max_atraso < 0:
            raise ValueError("Limite de atraso inválido")
        self.builder = M1Builder()
        self.indicadores = IndicadoresM1()
        self.apurador = ApuradorM1(simbolo=simbolo)
        self.enviar_telegram = enviar_telegram
        self.sessao = sessao
        self.simbolo = simbolo
        self.relogio = relogio
        self.max_atraso = max_atraso
        self.ultimo_alerta = None
        self.ultima_leitura = None
        self.metricas = {"ticks_aceitos": 0, "ticks_rejeitados": 0,
                         "latencia_tick_ms": None, "latencia_fechamento_ms": None,
                         "latencia_tick_max_ms": None, "processamento_ms": None,
                         "telegram_ms": None, "telegram_confirmados": 0,
                         "telegram_falhas": 0}

    def _enviar(self, funcao, dado):
        inicio = time.monotonic()
        try:
            if funcao(dado, sessao=self.sessao):
                self.metricas["telegram_confirmados"] += 1
        except RuntimeError:
            # Sem retry automático: timeout pode ter ocorrido depois da entrega.
            self.metricas["telegram_falhas"] += 1
        finally:
            self.metricas["telegram_ms"] = (time.monotonic() - inicio) * 1000

    def tick(self, timestamp, preco, *, recebido_em=None):
        inicio = time.monotonic()
        ts = timestamp_segundos(timestamp)
        recebido = float(self.relogio() if recebido_em is None else recebido_em)
        atraso = recebido - ts
        if not isfinite(recebido):
            raise ValueError("Horário de recepção inválido")
        if (atraso < 0 or atraso > self.max_atraso or
                (self.builder.ultimo_timestamp is not None and
                 ts < self.builder.ultimo_timestamp)):
            self.metricas["ticks_rejeitados"] += 1
            return None
        candle = self.builder.adicionar(ts, preco)
        self.metricas["ticks_aceitos"] += 1
        self.metricas["latencia_tick_ms"] = atraso * 1000
        self.metricas["latencia_tick_max_ms"] = max(
            self.metricas["latencia_tick_max_ms"] or 0, atraso * 1000)
        if candle is None:
            return None
        self.metricas["latencia_fechamento_ms"] = (recebido - candle.inicio - 60) * 1000
        resultado = self.apurador.processar_candle(candle)
        if resultado is not None:
            resultado["apurado_em"] = recebido
            resultado["latencia_fechamento_ms"] = self.metricas["latencia_fechamento_ms"]
            if self.enviar_telegram:
                self._enviar(enviar_resultado, resultado)
        leitura = self.indicadores.processar(candle)
        gerado = max(recebido, self.relogio())
        # Não emitir sinal da vela anterior a uma lacuna, nem muito após o fechamento.
        if (leitura is None or int(ts // 60) * 60 != candle.inicio + 60 or
                gerado - candle.inicio - 60 > self.max_atraso):
            return None
        leitura.update(simbolo=self.simbolo, recebido_em=recebido,
                       gerado_em=gerado, timestamp_tick=ts,
                       latencia_tick_ms=atraso * 1000,
                       latencia_fechamento_ms=self.metricas["latencia_fechamento_ms"],
                       retrospectivo=True)
        self.ultima_leitura = leitura
        mensagem = formatar_alerta(leitura, self.simbolo)
        if mensagem is None:
            return None
        chave = (leitura["inicio"], leitura["sinal_teorico"])
        if chave == self.ultimo_alerta or not self.apurador.registrar_sinal(leitura):
            return None
        self.ultimo_alerta = chave
        self.metricas["processamento_ms"] = (time.monotonic() - inicio) * 1000
        if self.enviar_telegram:
            self._enviar(enviar_alerta, leitura)
        return mensagem
