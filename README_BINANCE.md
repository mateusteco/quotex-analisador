# Nexus — BTCUSDT Futures

Migração do analisador Quotex para **sinais manuais em BTCUSDT perpétuo USDⓈ-M**.
Não acessa conta, não pede chave Binance e não envia ordens. Estratégia experimental,
sem taxa de acerto comprovada. Primeira etapa: coleta prospectiva em simulação.

## Iniciar no computador/servidor Linux

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python deploy/start.py
```

Abra http://localhost:8501. O supervisor inicia painel e monitor independente.
Também é possível iniciar `python futures_worker.py` e `streamlit run app.py`
em dois terminais. Para executar uma consulta: `python futures_worker.py --once`.
O monitor consulta REST público a cada 15 segundos; não é streaming por tick.
As entradas são avaliadas usando apenas candles fechados, com margem de 2 segundos.
Se o servidor for reiniciado, o histórico SQLite é retomado.

## Hospedagem contínua

Em hospedagem onde Binance Futures seja permitido e os endpoints estejam acessíveis:

```sh
cp .env.example .env
# Configure senha e, quando disponível, Telegram no .env.
docker compose up -d --build
docker compose logs --tail 50 -f
```

O painel fica em `127.0.0.1:8501`, sem exposição pública automática. Para acesso remoto,
use um túnel SSH (`ssh -L 8501:localhost:8501 usuario@servidor`) ou proxy HTTPS autenticado.
O volume `nexus-data` conserva sinais e agenda. Faça backup dele. Não apague o volume.
Não use GitHub Actions para manter o monitor 24/7: agendamentos podem atrasar.
Streamlit Community Cloud pode adormecer; serve para demonstração, não garante alertas contínuos.
HTTP 451 significa bloqueio regional, não erro de credencial. Não contorne o bloqueio;
a implantação precisa usar infraestrutura e disponibilidade permitidas pela Binance.

## Telegram — conectar junto com Mateus

1. Criar um bot no `@BotFather` com `/newbot`.
2. Guardar o token apenas em `TELEGRAM_BOT_TOKEN` no `.env` do servidor.
3. Abrir o bot no Telegram e enviar `/start`.
4. Obter o ID do chat pelo método oficial `getUpdates` e configurar `TELEGRAM_CHAT_ID`.
5. Reiniciar `docker compose up -d --force-recreate`.

Nunca postar token em commit, captura pública ou documentação. Se exposto, revogar no BotFather.
O bot só envia **novos sinais válidos**, não envia AGUARDAR e não reapresenta sinais expirados.
Há deduplicação persistente por vela/direção/versão e apenas um sinal ativo em simulação.
Uma falha de rede após entrega, antes da confirmação, pode ocasionar duplicata no retry;
o ID no alerta permite identificá-la. Não há garantia de entrega exatamente uma vez.
O fuso dos alertas é UTC explícito; o painel usa Brasília.

## Estratégia v1 — regras fixas, sem porcentagens inventadas

- Tendência: preço, EMA20, EMA50 e EMA200 ordenados em H4, H1, M15 e M5;
  EMA50 também precisa apontar na direção nos últimos 3 intervalos.
- Momentum M15: RSI 52–68 para compra ou 32–48 para venda.
- Volume M5 >=1,1× a média das 20 velas anteriores.
- OI crescente no intervalo e participação agressora >=55% na direção.
- Spread máximo 2 bps, funding absoluto máximo 0,05% por intervalo.
- Entrada até 2 minutos após fechamento M5; afastamento do fechamento <=0,5 ATR;
  afastamento da EMA20 M5 <=1,5 ATR.
- Stop estrutural de 6 velas, com mínimo 1,5 ATR e máximo 3 ATR; alvo 2R;
  barreiras H1 dos últimos 48 candles podem bloquear a entrada.
- Custo hipotético total de ida/volta 0,14%; distância do stop deve superar 3× esse custo.
- OHLCV, continuidade, finitude, relógio, símbolo e atualidade validados.
- Nenhum parâmetro foi otimizado para alegar rentabilidade. O par também não foi
  comprovado como o de maior previsibilidade.

## Fundamentos: cobertura e ação necessária

A versão implementa **filtro macro**, não avaliação fundamentalista completa:
RSS oficiais de política monetária do Fed e notícias do BLS, com bloqueio por uma hora
após comunicados relevantes; mais agenda de eventos com bloqueio de 30 min antes
até 60 min depois. A agenda é revisada no painel e expira após 24h.
**Sem agenda revisada ou com feed indisponível, não há novos sinais.**
A revisão vazia é válida apenas após conferir que não existem eventos relevantes nas
próximas 24h. Não confirme sem conferir. As fontes não cobrem todos os acontecimentos;
notícias imprevistas podem não ser detectadas. A v1 não integra fluxos de ETFs,
indicadores on-chain, sentimento de notícias ou calendário automático de todos os países.
Funding, OI e fluxo são dados de derivativos; não são substitutos de fundamentos.

## Simulação e métricas

O alerta dá preço de referência do livro no momento da análise. A simulação, por ser
conservadora e reprodutível, usa **abertura do próximo M5**, cancelando se afastar >0,25 ATR.
Pode diferir da entrada manual do usuário. Apenas uma posição virtual por vez.
Stop e alvo na mesma vela: considera stop primeiro. Gap contra o stop usa abertura
pior. Tempo máximo: 48 velas M5 (4h). Alvo 1 é referência visual, sem realização parcial.
Não calcula saldo alavancado, margem, liquidação ou retorno real de conta.

As taxas e deslizamento são hipotéticos (0,07% por lado), ajustados sobre os preços de
entrada/saída. Funding é conciliado usando os horários/taxas e mark prices efetivos
retornados pela Binance, sem supor periodicidade fixa de 8h. Dados conciliados limitados
aos últimos 7 dias. Registros anteriores ou falhas não ganham resultado líquido estimado:
aparecem somente como resultado antes do funding. Funding do candle de saída incluído
conservadoramente. Interrupção longa sem vela de entrada marca DATA_GAP e exclui a operação.

O painel mostra resultado em R, maior queda acumulada e acerto da amostra conciliada.
Não são métricas de um backtest completo nem prova de vantagem estatística. Ainda é
necessário acumular amostra ao vivo, testar outras condições de mercado e fazer
validação histórica fora da amostra antes de considerar operação real.

## Verificação reproduzível

```sh
python -m unittest discover -s tests -v
FUTURES_DATA_DIR=runtime-replay python futures_worker.py --replay tests/binance_snapshot.json
```

O fixture contém captura pública real da Binance obtida via integração em 05/11/2026 UTC.
Replay é rotulado OFFLINE, não consulta notícias atuais e não envia Telegram nem grava sinais.
As demais massas sintéticas nos testes verificam regras, não medem rentabilidade.

Documentação dos endpoints: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data
Telegram: https://core.telegram.org/bots/api#sendmessage
