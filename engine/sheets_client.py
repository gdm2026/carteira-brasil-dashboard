"""
Cliente da planilha "Carteira Brasil - Ordens" (Google Sheets) para o
Carteira Viva.

Lê e escreve na planilha que já existe hoje (continua sendo a fonte de
verdade enquanto a Fase 3 não estiver rodando de ponta a ponta). Usa uma
service account do Google — o caminho do JSON de credenciais vem da
variável de ambiente GOOGLE_SHEETS_CREDENTIALS, nunca hardcode.

Depende de `gspread` e `google-auth` (ver requirements.txt).
"""

from __future__ import annotations

import os
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

ABA_PONTUACAO = "Pontuação"
ABA_DASHBOARD = "Dashboard"
ABA_CARTEIRA_EUA = "Carteira EUA"

# Mesma ordem de linhas já usada na planilha hoje (linha 14 = primeiro
# ativo, linha 23 = último) — ver registro em Notion de 25/11/2026.
LINHA_INICIAL_PONTUACAO = 14
TICKERS_NUCLEO = [
    "ITUB4", "BBDC4", "TAEE11", "WEGE3", "VALE3",
    "BBSE3", "SBSP3", "RDOR3", "VIVA3", "CYRE3",
]


def _credenciais_path() -> str:
    caminho = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    if not caminho:
        raise RuntimeError(
            "GOOGLE_SHEETS_CREDENTIALS não está configurado. "
            "Aponte para o arquivo JSON da service account — nunca hardcode o conteúdo."
        )
    return caminho


def _spreadsheet_id() -> str:
    spreadsheet_id = os.environ.get("CARTEIRA_SPREADSHEET_ID")
    if not spreadsheet_id:
        raise RuntimeError("CARTEIRA_SPREADSHEET_ID não está configurado.")
    return spreadsheet_id


def conectar() -> gspread.Spreadsheet:
    credenciais = Credentials.from_service_account_file(_credenciais_path(), scopes=SCOPES)
    cliente = gspread.authorize(credenciais)
    return cliente.open_by_key(_spreadsheet_id())


def ler_pontuacao(planilha: Optional[gspread.Spreadsheet] = None) -> list[dict]:
    """Lê a aba Pontuação (colunas A-O) e devolve uma lista de dicts, um
    por ativo, na ordem em que aparecem na planilha. Não assume nenhuma
    classe/ticker fixo além do que estiver realmente escrito lá — assim,
    se o investidor adicionar um ativo novo na planilha, o código já lê
    sem precisar mudar código."""
    sh = planilha or conectar()
    aba = sh.worksheet(ABA_PONTUACAO)
    cabecalho = aba.row_values(13)  # linha 13 = cabeçalho, linha 12 = título
    linhas = aba.get(f"A{LINHA_INICIAL_PONTUACAO}:O{LINHA_INICIAL_PONTUACAO + len(TICKERS_NUCLEO) - 1}")

    ativos = []
    for linha in linhas:
        linha_completa = linha + [""] * (len(cabecalho) - len(linha))
        ativos.append(dict(zip(cabecalho, linha_completa)))
    return ativos


def escrever_filtro_tecnico(sh: gspread.Spreadsheet, resultados_por_ticker: dict[str, str]) -> None:
    """Escreve a coluna N (Filtro Técnico) respeitando a ordem de
    TICKERS_NUCLEO. `resultados_por_ticker` é {ticker: texto_da_celula}.
    Não escreve nada para um ticker que não vier no dict (fica como está,
    não apaga dado por engano)."""
    aba = sh.worksheet(ABA_PONTUACAO)
    valores = []
    for i, ticker in enumerate(TICKERS_NUCLEO):
        if ticker in resultados_por_ticker:
            valores.append([resultados_por_ticker[ticker]])
        else:
            linha_atual = LINHA_INICIAL_PONTUACAO + i
            valores.append([aba.acell(f"N{linha_atual}").value or ""])
    aba.update(f"N{LINHA_INICIAL_PONTUACAO}:N{LINHA_INICIAL_PONTUACAO + len(TICKERS_NUCLEO) - 1}", valores)


def ler_dashboard(planilha: Optional[gspread.Spreadsheet] = None) -> list[dict]:
    """Lê a aba Dashboard (posições da carteira Brasil, com % e teto já
    calculados pela planilha)."""
    sh = planilha or conectar()
    aba = sh.worksheet(ABA_DASHBOARD)
    todas_linhas = aba.get_all_values()
    if len(todas_linhas) < 4:
        return []
    cabecalho = todas_linhas[2]  # linha 3 = cabeçalho (ver estrutura real da aba)
    posicoes = []
    for linha in todas_linhas[3:]:
        if not linha or not linha[0] or linha[0] == "Total":
            continue
        linha_completa = linha + [""] * (len(cabecalho) - len(linha))
        posicoes.append(dict(zip(cabecalho, linha_completa)))
    return posicoes
