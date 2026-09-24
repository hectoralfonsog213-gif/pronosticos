"""
Modelo MLB: calidad de equipo + abridor -> probabilidad de ganar.

El beisbol es el deporte mas accesible para un modelo propio: 2,430 juegos por
temporada, favoritos que rara vez pasan de -250, y un mercado bastante menos
vigilado que el de la NFL. El abridor mueve la linea mas que cualquier otro
factor, asi que el modelo lo trata aparte del resto del equipo.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

EXPONENTE_PITAGORICO = 1.83
VENTAJA_LOCAL = 0.535     # porcentaje historico de victorias del local
REGRESION_MEDIA = 0.30    # cuanto se jala hacia .500 (clave a inicio de temporada)


def pitagorica(carreras_a_favor: float, carreras_en_contra: float) -> float:
    """Porcentaje de victorias esperado de un equipo, dado lo que anota y permite."""
    if carreras_a_favor <= 0 or carreras_en_contra <= 0:
        return 0.5
    cf = carreras_a_favor ** EXPONENTE_PITAGORICO
    cc = carreras_en_contra ** EXPONENTE_PITAGORICO
    return cf / (cf + cc)


def regresar(p: float, juegos: int, peso_previo: int = 60) -> float:
    """
    Jala la estimacion hacia .500 segun cuantos juegos lleva la temporada.

    Sin esto, un equipo 12-4 en abril se ve como un .750 y el modelo apuesta a
    ruido. Con 60 juegos de peso previo, en abril el dato del año casi no manda y
    para agosto ya domina.
    """
    if juegos <= 0:
        return 0.5
    return (p * juegos + 0.5 * peso_previo) / (juegos + peso_previo)


def log5(p_a: float, p_b: float) -> float:
    """Probabilidad de que A le gane a B, dados sus porcentajes contra la liga."""
    num = p_a - p_a * p_b
    den = p_a + p_b - 2 * p_a * p_b
    return num / den if den > 0 else 0.5


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sig(x: float) -> float:
    return 1 / (1 + math.exp(-x))


@dataclass
class Equipo:
    nombre: str
    carreras_favor: float      # por juego
    carreras_contra: float     # por juego
    juegos: int = 0

    @property
    def calidad(self) -> float:
        return regresar(pitagorica(self.carreras_favor, self.carreras_contra), self.juegos)


@dataclass
class Abridor:
    """
    El ajuste se expresa en carreras permitidas por 9 entradas respecto al
    promedio de la liga. Un as esta 1.2 carreras por debajo; un quinto abridor,
    0.8 por encima. FIP o xERA sirven mejor que ERA porque tienen menos ruido.
    """

    nombre: str = "desconocido"
    fip: float | None = None
    fip_liga: float = 4.10

    @property
    def delta(self) -> float:
        if self.fip is None:
            return 0.0
        # Un abridor cubre ~5.5 de 9 entradas: su efecto sobre el juego se diluye.
        return (self.fip_liga - self.fip) * (5.5 / 9.0)


def probabilidad_local(local: Equipo, visita: Equipo,
                       abridor_local: Abridor | None = None,
                       abridor_visita: Abridor | None = None,
                       ventaja_local: float = VENTAJA_LOCAL,
                       bullpen_local: float = 0.0,
                       bullpen_visita: float = 0.0) -> dict:
    """
    Probabilidad de que gane el local.

    `bullpen_*` es un ajuste manual en carreras, para cuando un bullpen viene
    fundido de una serie de entradas extra. Eso casi nunca esta en la linea de
    la mañana y es de las pocas cosas que el mercado tarda en incorporar.
    """
    base = log5(local.calidad, visita.calidad)

    ajuste = _logit(ventaja_local) - _logit(0.5)
    delta_carreras = (
        (abridor_local.delta if abridor_local else 0.0)
        - (abridor_visita.delta if abridor_visita else 0.0)
        + bullpen_visita - bullpen_local
    )
    # Cerca de 0.09 de logit por carrera de diferencia en un juego de beisbol.
    ajuste += delta_carreras * 0.09

    p = _sig(_logit(base) + ajuste)
    return {
        "p_local": p,
        "p_visita": 1 - p,
        "calidad_local": local.calidad,
        "calidad_visita": visita.calidad,
        "log5_neutral": base,
        "delta_abridores": delta_carreras,
    }


def total_carreras(local: Equipo, visita: Equipo,
                   abridor_local: Abridor | None = None,
                   abridor_visita: Abridor | None = None,
                   linea: float = 8.5, factor_parque: float = 1.0) -> dict:
    """
    Probabilidad de mas/menos carreras. Usa binomial negativa, que ajusta la cola
    larga del beisbol mucho mejor que Poisson: los juegos de 15 carreras existen y
    Poisson casi los prohibe.
    """
    esperado_local = (local.carreras_favor + visita.carreras_contra) / 2
    esperado_visita = (visita.carreras_favor + local.carreras_contra) / 2
    if abridor_visita:
        esperado_local -= abridor_visita.delta
    if abridor_local:
        esperado_visita -= abridor_local.delta

    mu = max(1.0, (esperado_local + esperado_visita) * factor_parque)
    varianza = mu * 1.45          # dispersion observada en MLB
    r = mu * mu / max(varianza - mu, 0.1)
    p_nb = r / (r + mu)

    def pmf(k: int) -> float:
        return math.exp(
            math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
            + r * math.log(p_nb) + k * math.log(1 - p_nb)
        )

    mas = sum(pmf(k) for k in range(0, 41) if k > linea)
    empate = sum(pmf(k) for k in range(0, 41) if abs(k - linea) < 1e-9)
    total = sum(pmf(k) for k in range(0, 41))
    mas, empate = mas / total, empate / total

    return {
        "total_esperado": mu,
        "p_mas": mas / (1 - empate) if empate < 1 else 0.5,
        "p_menos": 1 - (mas / (1 - empate) if empate < 1 else 0.5),
    }


def distribucion_carreras(local: Equipo, visita: Equipo,
                          abridor_local: Abridor | None = None,
                          abridor_visita: Abridor | None = None,
                          factor_parque: float = 1.0) -> dict[int, float]:
    """
    Distribucion completa de carreras totales del juego.

    Se necesita aparte de total_carreras() para valuar middles: un middle entre
    8.5 y 10.5 gana si el juego cae en 9 o 10, y eso solo se sabe con la
    distribucion, no con la probabilidad de un mas/menos suelto.
    """
    esperado_local = (local.carreras_favor + visita.carreras_contra) / 2
    esperado_visita = (visita.carreras_favor + local.carreras_contra) / 2
    if abridor_visita:
        esperado_local -= abridor_visita.delta
    if abridor_local:
        esperado_visita -= abridor_local.delta

    mu = max(1.0, (esperado_local + esperado_visita) * factor_parque)
    varianza = mu * 1.45
    r = mu * mu / max(varianza - mu, 0.1)
    p_nb = r / (r + mu)

    dist = {}
    for k in range(0, 41):
        dist[k] = math.exp(
            math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
            + r * math.log(p_nb) + k * math.log(1 - p_nb)
        )
    total = sum(dist.values())
    return {k: v / total for k, v in dist.items()}
