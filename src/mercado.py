"""
Motor de mercado: conversion de momios, eliminacion de comision (vig),
consenso entre casas y calculo de valor esperado.

Esta es la parte que no depende de ningun deporte, y tambien la parte donde
de verdad hay ventaja repetible: comparar el precio de una casa blanda contra
el consenso de todas las demas.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


# ----------------------------------------------------------------- momios
def am_a_dec(m: float) -> float:
    m = float(m)
    return m / 100.0 + 1.0 if m > 0 else 100.0 / abs(m) + 1.0


def dec_a_am(d: float) -> float:
    if d <= 1:
        return float("nan")
    return (d - 1) * 100.0 if d >= 2 else -100.0 / (d - 1)


def prob_a_am(p: float) -> float:
    if not 0 < p < 1:
        return float("nan")
    return dec_a_am(1.0 / p)


def fmt_am(m: float) -> str:
    if m != m:  # NaN
        return "—"
    return f"+{round(m)}" if m > 0 else f"{round(m)}"


# -------------------------------------------------------- quitar comision
def devig(probs: list[float], metodo: str = "power") -> list[float]:
    """Convierte probabilidades implicitas (que suman mas de 1) en probabilidades justas."""
    s = sum(probs)
    if s <= 1 or any(p <= 0 for p in probs):
        return list(probs)

    if metodo == "mult":
        return [p / s for p in probs]

    if metodo == "power":
        lo, hi = 1e-4, 20.0
        for _ in range(120):
            k = (lo + hi) / 2
            if sum(p ** k for p in probs) > 1:
                lo = k
            else:
                hi = k
        k = (lo + hi) / 2
        return [p ** k for p in probs]

    # Shin: modela la proporcion de dinero informado dentro del mercado
    def shin(z: float) -> list[float]:
        return [(math.sqrt(z * z + 4 * (1 - z) * p * p / s) - z) / (2 * (1 - z)) for p in probs]

    lo, hi = 0.0, 0.6
    for _ in range(120):
        m = (lo + hi) / 2
        if sum(shin(m)) > 1:
            lo = m
        else:
            hi = m
    return shin((lo + hi) / 2)


def comision(probs: list[float]) -> float:
    s = sum(probs)
    return (s - 1) / s if s > 0 else 0.0


# --------------------------------------------------------------- consenso
def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoide(x: float) -> float:
    return 1 / (1 + math.exp(-x))


@dataclass
class CotizacionCasa:
    """Los momios de una casa para todos los resultados de un mismo mercado."""

    casa: str
    decimales: list[float]
    peso: float = 1.0
    justas: list[float] = field(default_factory=list)

    def calcular(self, metodo: str = "power") -> None:
        self.justas = devig([1 / d for d in self.decimales], metodo)

    @property
    def vig(self) -> float:
        return comision([1 / d for d in self.decimales])


def consenso(cotizaciones: list[CotizacionCasa], excluir: str | None = None) -> list[float] | None:
    """
    Promedio ponderado, en espacio logit, de las probabilidades justas de cada casa.

    `excluir` deja fuera a una casa del consenso. Esto importa mas de lo que parece:
    para juzgar si el precio de una casa tiene valor, el consenso no debe incluirla,
    o se estaria comparando contra si misma y el valor real se diluye. Cuantas menos
    casas haya, mas grave es el error.
    """
    usables = [c for c in cotizaciones if c.justas and c.casa != excluir]
    if not usables:
        return None
    n = len(usables[0].justas)
    if any(len(c.justas) != n for c in usables):
        return None
    total = sum(c.peso for c in usables)
    if total <= 0:
        return None

    crudo = [_sigmoide(sum(c.peso * _logit(c.justas[i]) for c in usables) / total) for i in range(n)]
    s = sum(crudo)
    return [p / s for p in crudo]


# ---------------------------------------------------------- valor y riesgo
def valor_esperado(p: float, decimal: float) -> float:
    return p * decimal - 1.0


def kelly(p: float, decimal: float, fraccion: float = 0.25, tope: float = 0.02) -> float:
    """
    Fraccion de banca a arriesgar, con tope duro.

    El tope es lo que salva bancas: Kelly asume que tu probabilidad es exacta y
    nunca lo es. Un cuarto de Kelly con techo del 2% conserva la mayor parte del
    crecimiento y perdona errores de estimacion.
    """
    if decimal <= 1:
        return 0.0
    f = (p * decimal - 1) / (decimal - 1)
    return max(0.0, min(f * fraccion, tope))


@dataclass
class Jugada:
    deporte: str
    liga: str
    evento: str
    inicio: str
    mercado: str
    seleccion: str
    casa: str
    momio_dec: float
    p_justa: float           # probabilidad segun el consenso de las otras casas
    p_modelo: float | None   # probabilidad segun el modelo propio, si lo hay
    ev: float
    ev_modelo: float | None
    stake: float
    n_casas: int
    fuente: str              # "mercado" o "modelo"
    ev_minimo: float = 0.02  # umbral con el que se aprobo esta jugada

    @property
    def momio_am(self) -> float:
        return dec_a_am(self.momio_dec)

    @property
    def p_apuesta(self) -> float:
        """La probabilidad con la que se decidio: siempre la mas conservadora."""
        if self.p_modelo is None:
            return self.p_justa
        return min(self.p_justa, self.p_modelo)

    @property
    def momio_minimo_dec(self) -> float:
        """
        El peor precio al que esta jugada sigue valiendo la pena.

        Sirve para lo que de verdad pasa: yo te digo una jugada a cierto momio
        y tu la vas a poner en TU casa, donde el precio es otro. Si tu casa paga
        igual o mejor que esto, la apuesta sigue teniendo valor. Si paga menos,
        no la hagas: no es la misma apuesta aunque sea el mismo equipo.
        """
        return (1 + self.ev_minimo) / self.p_apuesta

    @property
    def momio_minimo_am(self) -> float:
        return dec_a_am(self.momio_minimo_dec)

    @property
    def momio_empate_dec(self) -> float:
        """Precio donde el valor esperado llega a cero. Abajo de aqui pierdes."""
        return 1 / self.p_apuesta

    def dict(self) -> dict:
        return {
            "deporte": self.deporte,
            "liga": self.liga,
            "evento": self.evento,
            "inicio": self.inicio,
            "mercado": self.mercado,
            "seleccion": self.seleccion,
            "casa": self.casa,
            "momio_dec": round(self.momio_dec, 3),
            "momio_am": fmt_am(self.momio_am),
            "p_justa": round(self.p_justa, 4),
            "p_modelo": round(self.p_modelo, 4) if self.p_modelo is not None else None,
            "ev": round(self.ev, 4),
            "ev_modelo": round(self.ev_modelo, 4) if self.ev_modelo is not None else None,
            "stake_pct": round(self.stake * 100, 3),
            "n_casas": self.n_casas,
            "fuente": self.fuente,
            "momio_minimo_dec": round(self.momio_minimo_dec, 3),
            "momio_minimo_am": fmt_am(self.momio_minimo_am),
            "momio_empate_am": fmt_am(dec_a_am(self.momio_empate_dec)),
        }
