"""
Carteira Viva — motor de análise (fase 2 -> fase 3)
=====================================================

Este módulo concentra, em código versionável, os cálculos que hoje ainda
são feitos manualmente (planilha + navegador): preço-justo de Graham,
filtro técnico (MM50 + mínima de 10 pregões) e nota fundamentalista 0-100
por classe de ativo, usando as faixas fixas decididas em 25/11/2026
(ver página Notion "Aprendizado Bolsa" / "Carteira Viva").

Nada neste arquivo executa ordem nenhuma. Ele só lê dados (brapi.dev,
Google Sheets) e escreve de volta na planilha. A decisão de aportar,
reduzir ou vender continua sendo sempre do investidor.

Variáveis de ambiente esperadas (nunca hardcode a chave):
    BRAPI_TOKEN                 -> token da API brapi.dev (Bearer)
    GOOGLE_SHEETS_CREDENTIALS   -> caminho do JSON de credenciais da service
                                    account usada pela Google Sheets API
    CARTEIRA_SPREADSHEET_ID     -> ID da planilha "Carteira Brasil - Ordens"

Este arquivo ainda não está rodando em produção — é o ponto de partida
do motor da Fase 3 (site com login via Vercel + Supabase). Hoje ele roda
localmente para validar a lógica; a leitura/escrita real no Sheets e a
chamada à API exigem as variáveis de ambiente acima configuradas.

AVISO — repositório público: este repositório hospeda hoje o dashboard
público (gdm2026.github.io/carteira-brasil-dashboard). Este arquivo não
contém nenhuma chave, senha ou posição real de carteira — só fórmulas e
faixas de pontuação, por isso pode ficar aqui. Nenhum dado pessoal ou
segredo deve ser commitado nesta pasta ("engine/") nem no restante deste
repositório enquanto ele permanecer público.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# 1. Preço-justo de Graham
# ---------------------------------------------------------------------------

def preco_justo_graham(lpa: float, vpa: float) -> Optional[float]:
    """Preço Justo = sqrt(22,5 x LPA x VPA).

    Retorna None quando o resultado não é confiável: LPA ou VPA negativos
    ou zero. A fórmula também é pouco confiável para empresas de
    crescimento/múltiplo elevado ou com lucro ciclicamente deprimido —
    isso não é detectado aqui (depende de P/L, ver `classificar_graham`),
    tem que ser sinalizado por quem chama esta função.
    """
    if lpa is None or vpa is None:
        return None
    if lpa <= 0 or vpa <= 0:
        return None
    return math.sqrt(22.5 * lpa * vpa)


def classificar_confiabilidade_graham(p_l: Optional[float], classe: str) -> str:
    """Sinaliza quando o Graham não deve ser confiado, mesmo que o cálculo
    tenha rodado sem erro. Critérios já documentados nesta sessão:
    - P/L muito alto (crescimento ou lucro deprimido por ciclo) -> não confiável
    - classe 'commodity' com P/L > 40 -> lucro deprimido por ciclo
    - classe 'crescimento' ou 'saude_crescimento' com P/L > 25 -> múltiplo caro
    """
    if p_l is None:
        return "sem dado de P/L para avaliar confiabilidade"
    if classe == "commodity" and p_l > 40:
        return "NÃO CONFIÁVEL — lucro provavelmente deprimido pelo ciclo"
    if classe in ("crescimento", "saude_crescimento") and p_l > 25:
        return "NÃO CONFIÁVEL — múltiplo de crescimento, Graham subestima"
    return "OK"


def preco_justo_mais_conservador(fontes: dict[str, float]) -> tuple[str, float]:
    """Regra já decidida: quando há mais de uma fonte de preço-justo,
    adotar sempre a mais baixa (mais conservadora).

    `fontes` é um dict {"Graham": 52.98, "Investing.com": 26.83, ...}.
    Retorna (nome_da_fonte_adotada, valor).
    """
    fontes_validas = {k: v for k, v in fontes.items() if v is not None}
    if not fontes_validas:
        raise ValueError("nenhuma fonte de preço-justo disponível")
    fonte_escolhida = min(fontes_validas, key=fontes_validas.get)
    return fonte_escolhida, fontes_validas[fonte_escolhida]


# ---------------------------------------------------------------------------
# 2. Filtro técnico — MM50 + mínima de 10 pregões
# ---------------------------------------------------------------------------

@dataclass
class FiltroTecnicoResultado:
    ultimo_preco: float
    mm50: float
    minima_10_pregoes: float
    abaixo_mm50: bool
    nova_minima_10: bool
    status: str  # "SIM" | "ATENCAO" | "NAO"


def filtro_tecnico(closes_ordenados_por_data: list[float]) -> FiltroTecnicoResultado:
    """`closes_ordenados_por_data` deve vir em ordem crescente de data
    (mais antigo primeiro, mais recente por último) — mesma convenção da
    série `historicalDataPrice` do brapi.dev depois de ordenada.

    Regra (decidida em revisão por voz, 25/11/2026):
    "queda ativa" = SIM somente quando, ao mesmo tempo:
      (a) preço abaixo da média móvel de 50 dias, E
      (b) o preço de hoje é uma nova mínima dos últimos 10 pregões.
    Só uma das duas condições = ATENÇÃO (aviso, não "queda ativa").
    Nenhuma das duas = NÃO.
    """
    if len(closes_ordenados_por_data) < 10:
        raise ValueError("histórico insuficiente para o filtro técnico (mínimo 10 pregões)")

    n = len(closes_ordenados_por_data)
    ultimo = closes_ordenados_por_data[-1]
    janela_mm50 = closes_ordenados_por_data[-50:] if n >= 50 else closes_ordenados_por_data
    mm50 = sum(janela_mm50) / len(janela_mm50)
    janela_10 = closes_ordenados_por_data[-10:]
    minima_10 = min(janela_10)

    abaixo_mm50 = ultimo < mm50
    nova_minima_10 = ultimo <= minima_10

    if abaixo_mm50 and nova_minima_10:
        status = "SIM"
    elif abaixo_mm50 or nova_minima_10:
        status = "ATENCAO"
    else:
        status = "NAO"

    return FiltroTecnicoResultado(
        ultimo_preco=ultimo,
        mm50=mm50,
        minima_10_pregoes=minima_10,
        abaixo_mm50=abaixo_mm50,
        nova_minima_10=nova_minima_10,
        status=status,
    )


# ---------------------------------------------------------------------------
# 3. Concentração vs. teto
# ---------------------------------------------------------------------------

TETO_ACAO_FII_INDIVIDUAL = 0.15
TETO_ETF_DIVERSIFICADO = 0.25
ORCAMENTO_ESPECULATIVO_AGREGADO = 0.10  # % do total da carteira (soma de todas as apostas ativas)


def status_concentracao(pct_carteira: float, classe_ativo: str) -> str:
    """classe_ativo: 'acao', 'fii', 'etf_diversificado' ou 'especulativo'.
    Carteiras Brasil e EUA são tratadas separadamente — o `pct_carteira`
    passado aqui já deve ser calculado sobre a carteira certa, com caixa
    parado fora do denominador (regras já decididas, ver Notion)."""
    teto = TETO_ETF_DIVERSIFICADO if classe_ativo == "etf_diversificado" else TETO_ACAO_FII_INDIVIDUAL
    return "Acima do teto" if pct_carteira > teto else "OK"


# ---------------------------------------------------------------------------
# 4. Nota fundamentalista 0-100 por classe (faixas fixas, decididas 25/11/2026)
# ---------------------------------------------------------------------------

def _pontos_por_faixas(valor: Optional[float], faixas: list[tuple[float, float, float]], default_abaixo: float, default_acima: float) -> Optional[float]:
    """faixas: lista de (min, max, pontos), em qualquer ordem.
    Se o valor não cair em nenhuma faixa, usa default_abaixo (valor menor
    que todas as faixas) ou default_acima (valor maior que todas)."""
    if valor is None:
        return None
    menores = [f for f in faixas if valor < f[0]]
    maiores = [f for f in faixas if valor > f[1]]
    for minimo, maximo, pontos in faixas:
        if minimo <= valor <= maximo:
            return pontos
    if len(menores) == len(faixas):
        return default_abaixo
    if len(maiores) == len(faixas):
        return default_acima
    # caiu num "buraco" entre faixas não contíguas — interpola pelo vizinho mais próximo
    faixas_ordenadas = sorted(faixas, key=lambda f: f[0])
    for i in range(len(faixas_ordenadas) - 1):
        if faixas_ordenadas[i][1] < valor < faixas_ordenadas[i + 1][0]:
            return (faixas_ordenadas[i][2] + faixas_ordenadas[i + 1][2]) / 2
    return default_abaixo


@dataclass
class NotaResultado:
    nota: Optional[float]
    parcial: bool
    motivo_parcial: str = ""


# Pesos e faixas por classe — ver registro em Notion "Faixas fixas da nota
# 0-100 por classe — proposta fechada (25/11/2026)" para a justificativa de
# cada faixa.
FAIXAS_BANCO = {
    "roe": [(20, 999, 100), (15, 20, 80), (10, 15, 60), (5, 10, 40)],
    "p_vp": [(0.8, 1.5, 100), (1.5, 2.5, 70), (0.5, 0.8, 50), (2.5, 3.5, 50)],
    "p_l": [(5, 10, 100), (10, 14, 70), (14, 18, 40)],
    "dy": [(8, 999, 100), (5, 8, 70), (3, 5, 40)],
}
PESOS_BANCO = {"roe": 0.40, "p_vp": 0.30, "p_l": 0.20, "dy": 0.10}

FAIXAS_UTILITY = {
    "dy": [(8, 999, 100), (6, 8, 80), (4, 6, 60), (2, 4, 40)],
    "margem": [(30, 999, 100), (20, 30, 80), (10, 20, 60), (0, 10, 40)],
    "p_vp": [(1, 2, 100), (2, 3, 70), (0.5, 1, 70)],
    "p_l": [(8, 14, 100), (14, 20, 70)],
}
PESOS_UTILITY = {"dy": 0.35, "margem": 0.25, "p_vp": 0.20, "p_l": 0.20}

FAIXAS_CRESCIMENTO = {
    "roe": [(25, 999, 100), (18, 25, 80), (12, 18, 60), (6, 12, 40)],
    "margem": [(20, 999, 100), (12, 20, 75), (6, 12, 50)],
    "p_l": [(15, 30, 100), (30, 45, 70)],
    "p_vp": [(3, 8, 100), (8, 15, 70)],
}
PESOS_CRESCIMENTO = {"roe": 0.30, "margem": 0.25, "p_l": 0.25, "p_vp": 0.20}

FAIXAS_COMMODITY = {
    "roe": [(15, 999, 100), (8, 15, 70), (3, 8, 40)],
    "margem": [(15, 999, 100), (8, 15, 70), (3, 8, 40)],
    "p_vp": [(0.8, 1.5, 100), (1.5, 2.5, 60), (0.5, 0.8, 60)],
    "dy": [(8, 999, 100), (5, 8, 70), (2, 5, 40)],
}
PESOS_COMMODITY = {"roe": 0.35, "margem": 0.35, "p_vp": 0.15, "dy": 0.15}
# P/L fica fora de propósito — distorce em ciclo de commodity (já documentado)

FAIXAS_SEGURADORA = {
    "roe": [(25, 999, 100), (15, 25, 75), (8, 15, 50)],
    "dy": [(10, 999, 100), (6, 10, 70), (3, 6, 40)],
    "p_vp": [(1, 3, 100), (3, 6, 70)],
    "p_l": [(6, 12, 100), (12, 18, 70)],
}
PESOS_SEGURADORA = {"roe": 0.40, "dy": 0.30, "p_vp": 0.20, "p_l": 0.10}

CLASSES_SEM_MATRIZ = {"especulativo"}  # usam só o filtro das 3 perguntas

# Pontuação do "pior caso" (valor abaixo de todas as faixas definidas) por
# classe e critério — documentado em Notion. Onde o texto só dizia "fora
# disso" sem diferenciar abaixo/acima, usamos o mesmo valor para os dois
# lados (sempre o pior caso, nunca estimado).
DEFAULT_ABAIXO_POR_CLASSE = {
    "banco": {"roe": 20, "p_vp": 20, "p_l": 20, "dy": 20},
    "utility": {"dy": 20, "margem": 0, "p_vp": 20, "p_l": 20},
    "crescimento": {"roe": 20, "margem": 25, "p_l": 20, "p_vp": 20},
    "saude_crescimento": {"roe": 20, "margem": 25, "p_l": 20, "p_vp": 20},
    "commodity": {"roe": 15, "margem": 15, "p_vp": 30, "dy": 20},
    "seguradora": {"roe": 25, "dy": 20, "p_vp": 20, "p_l": 20},
}


def calcular_nota(
    classe: str,
    roe: Optional[float] = None,
    p_vp: Optional[float] = None,
    p_l: Optional[float] = None,
    dy: Optional[float] = None,
    margem: Optional[float] = None,
    criterios_ausentes: Optional[list[str]] = None,
) -> NotaResultado:
    """`roe`, `dy`, `margem` em percentual (ex.: 20.83 para 20,83%).
    `criterios_ausentes` é a lista de critérios que a matriz da classe
    pediria mas que a fonte de dado atual não entrega (ex.: inadimplência
    e capital para banco) — isso nunca é estimado, só marca a nota como
    parcial.
    """
    if classe in CLASSES_SEM_MATRIZ:
        return NotaResultado(nota=None, parcial=True, motivo_parcial="fora da matriz — especulativo, usa o filtro das 3 perguntas")

    tabela = {
        "banco": (FAIXAS_BANCO, PESOS_BANCO),
        "utility": (FAIXAS_UTILITY, PESOS_UTILITY),
        "crescimento": (FAIXAS_CRESCIMENTO, PESOS_CRESCIMENTO),
        "saude_crescimento": (FAIXAS_CRESCIMENTO, PESOS_CRESCIMENTO),
        "commodity": (FAIXAS_COMMODITY, PESOS_COMMODITY),
        "seguradora": (FAIXAS_SEGURADORA, PESOS_SEGURADORA),
    }
    if classe not in tabela:
        return NotaResultado(nota=None, parcial=True, motivo_parcial=f"classe '{classe}' sem matriz definida ainda")

    faixas, pesos = tabela[classe]
    valores = {"roe": roe, "p_vp": p_vp, "p_l": p_l, "dy": dy, "margem": margem}
    defaults_classe = DEFAULT_ABAIXO_POR_CLASSE.get(classe, {})

    soma_pontos = 0.0
    soma_pesos_usados = 0.0
    for criterio, peso in pesos.items():
        if criterio not in faixas:
            continue
        default_abaixo = defaults_classe.get(criterio, 20)
        pontos = _pontos_por_faixas(valores.get(criterio), faixas[criterio], default_abaixo=default_abaixo, default_acima=100)
        if pontos is None:
            continue
        soma_pontos += pontos * peso
        soma_pesos_usados += peso

    if soma_pesos_usados == 0:
        return NotaResultado(nota=None, parcial=True, motivo_parcial="nenhum critério disponível para calcular a nota")

    # renormaliza pelos pesos realmente usados, para não penalizar por dado ausente
    nota_final = soma_pontos / soma_pesos_usados

    parcial = bool(criterios_ausentes)
    motivo = f"falta: {', '.join(criterios_ausentes)}" if criterios_ausentes else ""
    return NotaResultado(nota=round(nota_final, 1), parcial=parcial, motivo_parcial=motivo)


# ---------------------------------------------------------------------------
# 5. Auto-teste — valida a lógica contra os números já conferidos manualmente
#    em 25/11/2026 (ver página Notion). Roda sem precisar de nenhuma chave
#    de API nem credencial — serve pra garantir que o código bate com a
#    conta feita na mão antes de ligar isso a dado ao vivo.
# ---------------------------------------------------------------------------

def _autoteste():
    casos = [
        ("ITUB4", "banco", dict(roe=20.83, p_vp=1.9, p_l=9.13, dy=7.97), ["inadimplência", "capital"], 88),
        ("BBDC4", "banco", dict(roe=13.41, p_vp=0.79, p_l=5.86, dy=11.85), ["inadimplência", "capital"], 69),
        ("TAEE11", "utility", dict(margem=40.85, p_vp=1.68, p_l=8.41, dy=7.86), ["risco regulatório"], 93),
        ("SBSP3", "utility", dict(margem=17.47, p_vp=2.13, p_l=13.72, dy=5.19), ["risco regulatório"], 70),
        ("WEGE3", "crescimento", dict(roe=31.41, margem=15.40, p_l=33.02, p_vp=10.37), ["crescimento de receita"], 80.2),
        ("RDOR3", "saude_crescimento", dict(roe=21.67, margem=7.89, p_l=17.89, p_vp=3.88), ["crescimento de receita"], 81.5),
        ("VALE3", "commodity", dict(roe=1.13, margem=1.01, p_vp=1.28, dy=10.17), ["dívida"], 40.5),
        ("BBSE3", "seguradora", dict(roe=68.17, dy=12.52, p_vp=5.3, p_l=7.78), ["sinistralidade"], 94),
    ]
    print(f"{'Ativo':8} {'Nota código':>12} {'Nota manual (25/11)':>20} {'Confere?':>10}")
    for ticker, classe, metrics, ausentes, nota_manual in casos:
        resultado = calcular_nota(classe, criterios_ausentes=ausentes, **metrics)
        confere = "sim" if resultado.nota == nota_manual else f"DIVERGE ({resultado.nota} vs {nota_manual})"
        print(f"{ticker:8} {resultado.nota:>12} {nota_manual:>20} {confere:>10}")

    # filtro técnico — valida com os números já gravados na planilha hoje
    # (WEGE3 deve dar SIM, SBSP3 deve dar NAO, os demais ATENCAO)
    print()
    print("Filtro técnico — reconstrução simplificada a partir dos valores já gravados:")
    exemplos_tecnico = {
        "WEGE3": (49.65, 49.74, 49.65),   # (último, mm50, min10) já calculados hoje
        "SBSP3": (28.48, 28.36, 26.93),
    }
    for ticker, (ultimo, mm50, min10) in exemplos_tecnico.items():
        abaixo = ultimo < mm50
        nova_min = ultimo <= min10
        status = "SIM" if (abaixo and nova_min) else ("ATENCAO" if (abaixo or nova_min) else "NAO")
        print(f"{ticker}: último={ultimo} mm50={mm50} min10={min10} -> {status}")


if __name__ == "__main__":
    _autoteste()
