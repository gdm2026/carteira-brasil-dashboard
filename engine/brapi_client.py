"""
Cliente da API brapi.dev para o Carteira Viva.

Só lê dados (cotação e histórico). Nunca executa ordem nenhuma.
A chave vem sempre da variável de ambiente BRAPI_TOKEN — nunca hardcode,
nunca coloque no frontend, nunca logue o valor da chave em texto.

Licença (checada em 25/11/2026, ver Notion): a brapi.dev permite exibir
os dados dentro do próprio produto para os próprios usuários. NÃO permite
redistribuir os dados, nem criar um proxy/espelho público da API deles —
então este cliente nunca deve expor um endpoint que devolva o JSON cru
da brapi para fora da aplicação.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

import requests

BRAPI_BASE_URL = "https://brapi.dev/api/v2"


class BrapiError(Exception):
    """Erro de alto nível da API brapi.dev, já traduzido pro chamador."""

    def __init__(self, message: str, status_code: Optional[int] = None, retry_after: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


def _token() -> str:
    token = os.environ.get("BRAPI_TOKEN")
    if not token:
        raise BrapiError(
            "BRAPI_TOKEN não está configurado nas variáveis de ambiente. "
            "Nunca hardcode a chave — configure a variável de ambiente antes de rodar."
        )
    return token


def _request(path: str, params: dict) -> dict:
    url = f"{BRAPI_BASE_URL}{path}"
    headers = {"Authorization": f"Bearer {_token()}"}
    response = requests.get(url, headers=headers, params=params, timeout=15)

    if response.status_code == 401:
        raise BrapiError("Token inválido ou não enviado (401). Confira a variável BRAPI_TOKEN.", status_code=401)
    if response.status_code == 403:
        raise BrapiError("Plano atual não cobre esse dado (403). Pode exigir upgrade de plano.", status_code=403)
    if response.status_code == 404:
        raise BrapiError(f"Ativo ou endpoint não encontrado (404): {params}", status_code=404)
    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", "60"))
        raise BrapiError(
            f"Limite de requisições excedido (429). Esperar {retry_after}s antes de tentar de novo.",
            status_code=429,
            retry_after=retry_after,
        )
    response.raise_for_status()
    return response.json()


def buscar_cotacoes(tickers: list[str]) -> dict[str, Optional[dict]]:
    """Busca cotação atual de vários tickers numa única chamada
    (parâmetro symbols aceita lista separada por vírgula).
    Retorna {ticker: dado_ou_None}. Nunca inventa número para quem falhar —
    fica None, e quem chamar decide como tratar (ex.: "n/d" na planilha).
    """
    simbolos = ",".join(tickers)
    try:
        dados = _request("/stocks/quote", {"symbols": simbolos})
    except BrapiError:
        raise

    resultados: dict[str, Optional[dict]] = {t: None for t in tickers}
    for item in dados.get("results", []):
        ticker = item.get("symbol") or item.get("requestedSymbol")
        if ticker:
            resultados[ticker] = item
    return resultados


def buscar_historico(ticker: str, intervalo: str = "1d", periodo: str = "6mo") -> list[float]:
    """Retorna os preços de fechamento (`close`) em ordem crescente de
    data (mais antigo primeiro) — pronto para `filtro_tecnico()` do
    carteira_viva_motor. Levanta BrapiError se o ativo não tiver dado
    suficiente; nunca completa com valor inventado.
    """
    dados = _request("/stocks/historical", {"symbols": ticker, "range": periodo, "interval": intervalo})
    resultados = dados.get("results", [])
    if not resultados:
        raise BrapiError(f"Sem histórico retornado para {ticker}.")

    serie = resultados[0].get("data", {}).get("historicalDataPrice", [])
    if not serie:
        raise BrapiError(f"Histórico vazio para {ticker}.")

    serie_ordenada = sorted(serie, key=lambda d: d["date"])
    return [ponto["close"] for ponto in serie_ordenada if ponto.get("close") is not None]


def com_retry(func, *args, max_tentativas: int = 2, **kwargs):
    """Wrapper simples: se vier 429, espera o Retry-After e tenta de novo
    uma vez. Para 401/403/404 não insiste — esses não se resolvem sozinhos
    com retry."""
    ultima_excecao: Optional[BrapiError] = None
    for tentativa in range(max_tentativas):
        try:
            return func(*args, **kwargs)
        except BrapiError as exc:
            ultima_excecao = exc
            if exc.status_code == 429 and tentativa < max_tentativas - 1:
                time.sleep(exc.retry_after or 60)
                continue
            raise
    if ultima_excecao:
        raise ultima_excecao
