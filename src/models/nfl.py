"""
Modelo NFL: calificaciones Elo -> margen esperado -> distribucion de margenes.

Lo importante de este modelo no es el Elo, que es estandar, sino la distribucion
de margenes. Los resultados de futbol americano se amontonan en el 3 y el 7 y casi
nunca caen en 1 o 2, porque asi estan construidas las anotaciones. Una campana
normal reparte parejo y subestima mucho los empates contra la linea, que es justo
donde se pierde dinero sin darse cuenta.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# Pesos calibrados contra la frecuencia historica de margenes en la NFL.
# La masa que se le quita a los margenes muertos se le da a los numeros clave,
# conservando el total dentro de |margen| <= 20. Deja el 3 en ~9.6% de los
# partidos y el 7 en ~7.1%, que es lo que ocurre en la realidad.
PESOS_CLAVE = {
    1: 0.52, 2: 0.68, 3: 1.66, 4: 1.00, 5: 0.74, 6: 1.10, 7: 1.38,
    8: 0.86, 9: 0.86, 10: 1.08, 11: 0.90, 12: 0.92, 13: 0.92, 14: 1.10,
    17: 1.08, 20: 1.06, 21: 1.08,
}

SIGMA_MARGEN = 13.5
SIGMA_TOTAL = 10.5


def _ncdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


@dataclass
class Calificaciones:
    """Elo por equipo. 1500 es el promedio de la liga."""

    elo: dict[str, float] = field(default_factory=dict)
    k: float = 20.0
    ventaja_local_elo: float = 45.0   # unos 1.8 puntos
    elo_por_punto: float = 25.0

    def get(self, equipo: str) -> float:
        return self.elo.get(equipo, 1500.0)

    def margen_esperado(self, local: str, visita: str) -> float:
        return (self.get(local) - self.get(visita) + self.ventaja_local_elo) / self.elo_por_punto

    def actualizar(self, local: str, visita: str, pts_local: int, pts_visita: int) -> None:
        """Ajuste tras un partido, con multiplicador por margen de victoria."""
        dif = self.get(local) - self.get(visita) + self.ventaja_local_elo
        esperado = 1 / (1 + 10 ** (-dif / 400))
        real = 1.0 if pts_local > pts_visita else (0.5 if pts_local == pts_visita else 0.0)
        margen = abs(pts_local - pts_visita)
        mult = math.log(margen + 1) * (2.2 / (0.001 * abs(dif) + 2.2))
        cambio = self.k * mult * (real - esperado)
        self.elo[local] = self.get(local) + cambio
        self.elo[visita] = self.get(visita) - cambio

    def regresion_temporada(self, hacia: float = 1500.0, peso: float = 0.33) -> None:
        """Entre temporadas, acercar todo al promedio. Los equipos no son los mismos."""
        for eq in self.elo:
            self.elo[eq] = self.elo[eq] * (1 - peso) + hacia * peso


def distribucion_margen(mu: float, sd: float = SIGMA_MARGEN, numeros_clave: bool = True) -> dict[int, float]:
    """Probabilidad de cada margen entero (positivo = gana el local)."""
    base = {m: _ncdf((m + 0.5 - mu) / sd) - _ncdf((m - 0.5 - mu) / sd) for m in range(-70, 71)}

    if numeros_clave:
        extra = libre = 0.0
        for m in range(-20, 21):
            w = PESOS_CLAVE.get(abs(m))
            if w:
                extra += base[m] * (w - 1)
            else:
                libre += base[m]
        c = max(0.0, (libre - extra) / libre) if libre > 0 else 1.0
        dist = {}
        for m, pr in base.items():
            a = abs(m)
            w = PESOS_CLAVE.get(a)
            dist[m] = pr * w if (a <= 20 and w) else (pr * c if a <= 20 else pr)
    else:
        dist = base

    s = sum(dist.values())
    return {m: pr / s for m, pr in dist.items()}


def ganador(dist: dict[int, float]) -> tuple[float, float]:
    """(probabilidad de que gane el local, probabilidad de empate)."""
    gana = sum(pr for m, pr in dist.items() if m > 0)
    empate = dist.get(0, 0.0)
    return gana, empate


def cubre_linea(dist: dict[int, float], linea: float) -> tuple[float, float]:
    """
    Probabilidad de que el local cubra una linea dada (negativa = favorito).
    Devuelve (cubre, empate_tecnico).
    """
    cubre = empate = 0.0
    for m, pr in dist.items():
        ajustado = m + linea
        if ajustado > 1e-9:
            cubre += pr
        elif abs(ajustado) < 1e-9:
            empate += pr
    return cubre, empate


def total_puntos(proyectado: float, linea: float, sd: float = SIGMA_TOTAL) -> tuple[float, float]:
    """(probabilidad de mas, probabilidad de empate tecnico)."""
    mas = empate = 0.0
    for t in range(0, 141):
        pr = _ncdf((t + 0.5 - proyectado) / sd) - _ncdf((t - 0.5 - proyectado) / sd)
        if t > linea:
            mas += pr
        elif abs(t - linea) < 1e-9:
            empate += pr
    return mas, empate


def predecir(cal: Calificaciones, local: str, visita: str,
             linea: float | None = None, total_linea: float | None = None,
             total_proyectado: float | None = None) -> dict:
    mu = cal.margen_esperado(local, visita)
    dist = distribucion_margen(mu)
    gana, emp = ganador(dist)

    res = {
        "margen_esperado": mu,
        "p_local": gana / (1 - emp) if emp < 1 else 0.5,
        "p_visita": 1 - gana / (1 - emp) if emp < 1 else 0.5,
        "linea_justa": -mu,
    }
    if linea is not None:
        cubre, emp_l = cubre_linea(dist, linea)
        res["p_cubre_local"] = cubre / (1 - emp_l) if emp_l < 1 else 0.5
        res["p_cubre_visita"] = 1 - res["p_cubre_local"]
        res["p_empate_linea"] = emp_l
    if total_linea is not None and total_proyectado is not None:
        mas, emp_t = total_puntos(total_proyectado, total_linea)
        res["p_mas"] = mas / (1 - emp_t) if emp_t < 1 else 0.5
        res["p_menos"] = 1 - res["p_mas"]
    return res
