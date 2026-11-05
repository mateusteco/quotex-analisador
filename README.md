# Nexus OTC

Pesquisa e simulação de sinais, sem execução de ordens reais e sem martingale.

O fluxo streaming M1 usa `NZDCAD_otc` na OTCharts (venue `quotex`). Os horários são derivados dos ticks do provedor e apresentados com data e fuso de Brasília. São aceitos timestamps Unix em segundos/milissegundos ou ISO com fuso. Ticks com mais de 5 segundos de atraso, timestamps futuros e ticks fora de ordem são descartados. Esse limite conservador depende de relógios sincronizados; a latência mede a diferença entre o timestamp do provedor e a recepção local, não apenas a rede.

Cada alerta descreve uma vela já fechada: **é retrospectivo e nunca uma entrada futura**. Uma leitura demora 22 velas contíguas para aquecer. Lacunas reiniciam os indicadores e impedem sinais da vela anterior à lacuna. O resultado é a comparação open/close dos ticks observados na vela seguinte; não representa execução, payout, rentabilidade ou preço disponível após a entrega do Telegram.

## Testes offline

```bash
python -m pip install requests
python -m unittest discover -v
python stream_m1.py
python indicadores_m1.py
python -m compileall -q .
```

A regressão automática não recebe secrets e não envia mensagens externas. Inclui SSE, normalização de timestamps, latência, sinais e resultados simulados, rejeição de dados antigos, lacunas e falhas Telegram.

## Validação ao vivo

Execute na ramificação `desenvolvimento-streaming-m1` pelo GitHub Actions:

- **Teste OTCharts Streaming**: sondagem curta, requer ao menos dez ticks recentes de NZD/CAD OTC.
- **Teste integrado streaming M1**: até 30 minutos; exige 22 velas e leitura de indicadores.
- **Teste ponta a ponta OTCharts Telegram M1**: mesma janela, com envio de sinais e resultados exclusivamente simulados. A validação exige um ciclo apurado e confirmação de ao menos duas mensagens, sem falhas.

Esses workflows reutilizam os secrets existentes `OTCHARTS_API_KEY`, `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`, sem copiá-los ou alterá-los. Localmente, `python teste_integrado_m1.py` usa as mesmas variáveis; Telegram somente com `ENVIAR_TELEGRAM_SIMULACAO=1`.

O resumo JSON registra ticks aceitos/rejeitados, latência do último tick, maior latência de tick, atraso do último fechamento, tempo de processamento do último alerta, duração da última chamada Telegram e contadores de confirmação/falha. Confirmação da API Telegram não mede chegada ao dispositivo. Timeout não é reenviado automaticamente, pois a mensagem pode ter sido entregue. Falhas de envio são contadas e não impedem o fluxo de dados; o teste ponta a ponta falha ao final se ocorrerem.

Sem sinal dentro da janela, indisponibilidade do provedor ou dados insuficientes deixam a validação inconclusiva; nenhum resultado é inventado. O estado é mantido em memória, sem recuperação após reinício ou garantia de entrega exatamente uma vez. Os monitores e páginas de pesquisa históricos mantêm seus próprios ativos e não são executores M1.

Não mesclar com `main` sem revisão.

## Comparação com gravação da Quotex

No workflow **Teste OTCharts Streaming**, marque `capturar` e escolha entre 10 e 600 segundos. Espere a etapa de captura indicar `CAPTURA INICIADA` antes de gravar o gráfico NZD/CAD OTC. O arquivo CSV fica nos artefatos da execução por três dias; contém preço, timestamp do provedor, recepção UTC e atraso por tick. Esse workflow somente lê cotações e não envia mensagens ou ordens. Localmente: `CAPTURA_SEGUNDOS=120 python -u capturar_ticks.py` com a chave no ambiente.

Confirme o fuso/data do relógio do gráfico e mantenha nome do ativo, preço e relógio visíveis no vídeo. Sem sobreposição temporal, a comparação é inconclusiva. A amostra permite verificar correspondência nos pontos observados, sem comprovar igualdade contínua ou precisão subsegundo do relógio visual. Valores com atraso negativo ou alto permanecem no arquivo como evidência da captura; não são sinais. Capturas interrompidas podem deixar CSV parcial, identificado pela falha da etapa.
