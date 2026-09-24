"""
Modelo de futbol: de calificacion Elo a distribucion completa de marcadores.

Cadena: Elo de los dos equipos -> diferencia de goles esperada (supremacia)
-> goles esperados de cada lado -> matriz de Poisson con correccion
Dixon-Coles -> probabilidad de cualquier mercado (1X2, totales, ambos anotan,
handicap asiatico, marcador exacto).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

MAX_GOLES = 12


@lru_cache(maxsize=4096)
def _poisson(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1))


@dataclass
class ParametrosLiga:
    """
    Se calibran por liga. Los valores por defecto son razonables para las cinco
    ligas grandes de Europa; para Liga MX o MLS conviene recalcularlos con una
    temporada de resultados (ver `calibrar` mas abajo).
    """

    goles_promedio: float = 2.70     # goles totales por partido en la liga
    ventaja_local: float = 0.22      # en goles, no en Elo
    elo_a_goles: float = 0.0042      # cuantos goles de supremacia da 1 punto de Elo
    rho: float = -0.11               # correccion Dixon-Coles para marcadores bajos


def goles_esperados(elo_local: float, elo_visita: float, p: ParametrosLiga) -> tuple[float, float]:
    """Convierte la diferencia de Elo en goles esperados para cada lado."""
    supremacia = (elo_local - elo_visita) * p.elo_a_goles + p.ventaja_local
    lam_l = max(0.12, (p.goles_promedio + supremacia) / 2)
    lam_v = max(0.12, (p.goles_promedio - supremacia) / 2)
    return lam_l, lam_v


def matriz(lam_l: float, lam_v: float, rho: float = -0.11) -> list[list[float]]:
    """
    Matriz de probabilidad de cada marcador.

    La correccion Dixon-Coles arregla el defecto conocido de Poisson puro: los
    marcadores 0-0 y 1-1 ocurren mas seguido de lo que la formula predice, y los
    1-0 y 0-1 un poco menos.
    """
    m = [[0.0] * (MAX_GOLES + 1) for _ in range(MAX_GOLES + 1)]
    total = 0.0
    for i in range(MAX_GOLES + 1):
        for j in range(MAX_GOLES + 1):
            pr = _poisson(i, lam_l) * _poisson(j, lam_v)
            if i == 0 and j == 0:
                pr *= 1 - lam_l * lam_v * rho
            elif i == 0 and j == 1:
                pr *= 1 + lam_l * rho
            elif i == 1 and j == 0:
                pr *= 1 + lam_v * rho
            elif i == 1 and j == 1:
                pr *= 1 - rho
            pr = max(pr, 0.0)
            m[i][j] = pr
            total += pr
    if total > 0:
        for i in range(MAX_GOLES + 1):
            for j in range(MAX_GOLES + 1):
                m[i][j] /= total
    return m


def mercados(m: list[list[float]], lineas_totales=(1.5, 2.5, 3.5)) -> dict[str, float]:
    """Todas las probabilidades que se pueden leer de la matriz de marcadores."""
    out = {"1": 0.0, "X": 0.0, "2": 0.0, "ambos_si": 0.0}
    for i, fila in enumerate(m):
        for j, pr in enumerate(fila):
            if i > j:
                out["1"] += pr
            elif i == j:
                out["X"] += pr
            else:
                out["2"] += pr
            if i > 0 and j > 0:
                out["ambos_si"] += pr

    out["1X"] = out["1"] + out["X"]
    out["12"] = out["1"] + out["2"]
    out["X2"] = out["X"] + out["2"]
    out["ambos_no"] = 1 - out["ambos_si"]

    for linea in lineas_totales:
        mas = sum(pr for i, fila in enumerate(m) for j, pr in enumerate(fila) if i + j > linea)
        out[f"mas_{linea}"] = mas
        out[f"menos_{linea}"] = 1 - mas

    return out


def handicap_asiatico(m: list[list[float]], linea: float) -> tuple[float, float]:
    """
    Probabilidad de que el local cubra un handicap asiatico entero o de medio gol.
    Devuelve (gana, empate_tecnico). Las lineas de cuarto no se manejan aqui.
    """
    gana = empate = 0.0
    for i, fila in enumerate(m):
        for j, pr in enumerate(fila):
            margen = (i - j) + linea
            if margen > 1e-9:
                gana += pr
            elif abs(margen) < 1e-9:
                empate += pr
    return gana, empate


def marcadores_probables(m: list[list[float]], n: int = 8) -> list[tuple[int, int, float]]:
    todos = [(i, j, pr) for i, fila in enumerate(m) for j, pr in enumerate(fila) if i <= 6 and j <= 6]
    todos.sort(key=lambda t: t[2], reverse=True)
    return todos[:n]


def predecir(elo_local: float, elo_visita: float, p: ParametrosLiga | None = None) -> dict:
    p = p or ParametrosLiga()
    lam_l, lam_v = goles_esperados(elo_local, elo_visita, p)
    m = matriz(lam_l, lam_v, p.rho)
    return {
        "lambda_local": lam_l,
        "lambda_visita": lam_v,
        "mercados": mercados(m),
        "marcadores": marcadores_probables(m),
        "_matriz": m,
    }


# ------------------------------------------------------------- calibracion
def calibrar(resultados: list[tuple[float, float, int, int]]) -> ParametrosLiga:
    """
    Ajusta los parametros de una liga a partir de resultados historicos.

    Cada resultado es (elo_local, elo_visita, goles_local, goles_visita).
    Busca los parametros que maximizan la verosimilitud de los marcadores vistos.
    Con media temporada ya da algo usable; con dos temporadas, bastante estable.
    """
    if len(resultados) < 50:
        return ParametrosLiga()

    n = len(resultados)
    goles_prom = sum(gl + gv for _, _, gl, gv in resultados) / n
    ventaja = sum(gl - gv for _, _, gl, gv in resultados) / n

    mejor, mejor_ll = None, -1e18
    for coef in [0.0025 + 0.0004 * i for i in range(12)]:
        for rho in [-0.18 + 0.02 * i for i in range(10)]:
            p = ParametrosLiga(goles_prom, ventaja, coef, rho)
            ll = 0.0
            for el, ev, gl, gv in resultados:
                lam_l, lam_v = goles_esperados(el, ev, p)
                m = matriz(lam_l, lam_v, p.rho)
                gl_c, gv_c = min(gl, MAX_GOLES), min(gv, MAX_GOLES)
                ll += math.log(max(m[gl_c][gv_c], 1e-12))
            if ll > mejor_ll:
                mejor_ll, mejor = ll, p
    return mejor or ParametrosLiga()
