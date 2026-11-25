"""
Script de orquestração: lê cotação + histórico da brapi.dev, calcula o
filtro técnico com carteira_viva_motor, e escreve de volta na planilha.

Isto substitui, em código versionável, o que hoje roda como instrução em
texto dentro da tarefa agendada (trigger) do Claude. A tarefa agendada
pode continuar existindo como está até este script rodar de fato em
algum lugar (Fase 3) — os dois não são excludentes, são duas formas de
fazer a mesma coisa enquanto a Fase 3 não está pronta.

Uso:
    BRAPI_TOKEN=... GOOGLE_SHEETS_CREDENTIALS=... CARTEIRA_SPREADSHEET_ID=... \
        python atualizar_pontuacao.py

Nada aqui decide comprar, vender ou reforçar nada — só lê dado e grava
número. A decisão continua sendo sempre do investidor.
"""

from __future__ import annotations

import sys

from brapi_client import BrapiError, buscar_historico, com_retry
from carteira_viva_motor import filtro_tecnico
from sheets_client import TICKERS_NUCLEO, conectar, escrever_filtro_tecnico


def _descrever_status(resultado) -> str:
    if resultado.status == "SIM":
        return "SIM — queda ativa (abaixo da MM50 E nova mínima de 10 pregões)"
    if resultado.status == "ATENCAO":
        condicao = "abaixo da MM50" if resultado.abaixo_mm50 else "nova mínima de 10 pregões"
        return f"ATENÇÃO — só 1 condição ({condicao})"
    return "NÃO — acima da MM50 e não é mínima de 10 pregões"


def main() -> int:
    resultados: dict[str, str] = {}
    falhas: list[str] = []

    for ticker in TICKERS_NUCLEO:
        try:
            closes = com_retry(buscar_historico, ticker)
            resultado = filtro_tecnico(closes)
            resultados[ticker] = _descrever_status(resultado)
        except BrapiError as exc:
            # Nunca inventa valor para quem falhar — fica de fora do
            # dict, e escrever_filtro_tecnico mantém o que já estava lá.
            falhas.append(f"{ticker}: {exc}")

    if resultados:
        sh = conectar()
        escrever_filtro_tecnico(sh, resultados)
        print(f"Filtro técnico atualizado para {len(resultados)} ativo(s).")

    if falhas:
        print("Falhas (mantido o valor anterior na planilha):", file=sys.stderr)
        for f in falhas:
            print(f"  - {f}", file=sys.stderr)

    return 1 if falhas and not resultados else 0


if __name__ == "__main__":
    raise SystemExit(main())
