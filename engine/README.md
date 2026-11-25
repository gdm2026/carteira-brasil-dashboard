# Carteira Viva — motor de análise

Código do "motor" que hoje é feito manualmente (navegador + planilha):
Graham, filtro técnico (MM50 + mínima de 10 pregões), concentração vs.
teto e nota 0-100 por classe de ativo.

**Nada aqui executa ordem nenhuma.** Só lê dado (brapi.dev, Google
Sheets) e escreve de volta na planilha. A decisão de aportar, reduzir ou
vender continua sendo sempre do investidor.

## Arquivos

- `carteira_viva_motor.py` — as contas em si (Graham, filtro técnico,
  concentração, nota 0-100 por classe). Sem dependência externa, roda
  sozinho. `python carteira_viva_motor.py` roda um autoteste que valida
  os cálculos contra números já conferidos manualmente em 25/11/2026.
- `brapi_client.py` — busca cotação e histórico na API da brapi.dev.
  Trata 401/403/404/429 (respeitando `Retry-After`), nunca inventa valor
  para o que falhar.
- `sheets_client.py` — lê e escreve na planilha "Carteira Brasil -
  Ordens" via Google Sheets API (service account).
- `atualizar_pontuacao.py` — script que liga os três: busca histórico de
  cada ativo do núcleo, calcula o filtro técnico, grava na planilha.

## Variáveis de ambiente necessárias

| Variável | O que é |
|---|---|
| `BRAPI_TOKEN` | Token da API brapi.dev (plano Pro ativo) |
| `GOOGLE_SHEETS_CREDENTIALS` | Caminho do JSON de uma service account com acesso de edição na planilha |
| `CARTEIRA_SPREADSHEET_ID` | `1MnciZch8pB_2Tq_T3yPjF6ef6CwspAuGGFXQO7NNbdg` |

Nenhuma chave é lida de outro lugar — nunca hardcode nenhuma delas.

## Estado atual (25/11/2026)

- Lógica validada por autoteste (`carteira_viva_motor.py`), 8/8 ativos
  conferidos.
- `brapi_client.py` testado contra a API real a partir do navegador
  (Claude in Chrome) — funciona. **Chamada direta de servidor pro
  brapi.dev é bloqueada pela política de rede do ambiente de trabalho
  usado para desenvolver isso** (não é um problema do código — num
  ambiente de produção normal, como o Vercel, essa chamada funciona sem
  essa restrição).
- `sheets_client.py` ainda não testado contra a planilha real — falta
  criar a service account do Google e dar acesso de edição a ela na
  planilha (passo da Fase 3, ainda não feito).
- Isso ainda não está rodando em produção — é o ponto de partida do
  motor da Fase 3 (site com login via Vercel + Supabase). Enquanto isso,
  a tarefa agendada (trigger) que já atualiza a planilha continua
  funcionando como está; este código não substitui aquela tarefa ainda,
  é a versão que vai substituir quando o site existir de verdade.

## Repositório público — cuidado

Este repositório hospeda hoje o dashboard público
(`gdm2026.github.io/carteira-brasil-dashboard`). Nada nesta pasta
(`engine/`) contém chave, senha ou posição real de carteira — só
fórmulas e faixas de pontuação. Continue assim: nenhum segredo ou dado
pessoal deve ser commitado aqui enquanto o repositório for público.
