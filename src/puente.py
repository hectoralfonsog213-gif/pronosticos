"""
Puente entre los modelos y el motor de deteccion.

Cada funcion devuelve {id_evento: {clave_seleccion: probabilidad}}, donde la
clave se construye EXACTAMENTE igual que en el motor (motor.clave_seleccion),
porque si no coinciden el detector de modelo queda mudo sin avisar.

Aqui tambien se leen las lineas que ofrece el mercado (handicap y total) para
poder darle al modelo el numero contra el que tiene que opinar. Un modelo que
solo dice "gana el local 62%" no sirve para handicaps ni totales.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from .models import futbol as m_futbol
from .models import mlb as m_mlb
from .models import nfl as m_nfl
from .motor import clave_seleccion
from .sources import datos
from .sources.odds import Evento


@dataclass
class Pronostico:
    """Lo que el modelo sabe de un evento: probabilidades y distribuciones."""

    probs: dict[str, float] = field(default_factory=dict)
    # Distribucion del margen del local (NFL, futbol) y del total (todos).
    margen: dict[int, float] = field(default_factory=dict)
    total: dict[int, float] = field(default_factory=dict)

    def p_ventana(self, tipo: str, lo: float, hi: float) -> float | None:
        """
        Probabilidad de que el resultado caiga estrictamente entre lo y hi.
        Es justo lo que hace ganar un middle.
        """
        d = self.margen if tipo == "margen" else self.total
        if not d:
            return None
        return sum(pr for v, pr in d.items() if lo < v < hi)


def _linea_modal(ev: Evento, mercado: str, nombre: str | None = None) -> float | None:
    """
    La linea mas repetida entre las casas para un mercado.

    Se usa la moda y no el promedio porque un promedio puede dar 3.17, que no
    existe como linea real y no coincidiria con ninguna oferta.
    """
    puntos = []
    for salidas in ev.libros.get(mercado, {}).values():
        for n, _d, punto in salidas:
            if punto is None:
                continue
            if nombre is None or n == nombre:
                puntos.append(round(float(punto), 2))
    if not puntos:
        return None
    return Counter(puntos).most_common(1)[0][0]


# --------------------------------------------------------------------- MLB
def modelo_mlb(eventos: list[Evento]) -> dict[str, Pronostico]:
    temporada = date.today().year
    equipos = datos.mlb_equipos(temporada)
    juegos = {(j["local"], j["visita"]): j for j in datos.mlb_juegos(date.today())}

    salida: dict[str, Pronostico] = {}
    for ev in eventos:
        loc = datos.emparejar(ev.local, equipos)
        vis = datos.emparejar(ev.visita, equipos)
        if not loc or not vis:
            continue

        e_loc = m_mlb.Equipo(loc, equipos[loc]["cf"], equipos[loc]["cc"], equipos[loc]["juegos"])
        e_vis = m_mlb.Equipo(vis, equipos[vis]["cf"], equipos[vis]["cc"], equipos[vis]["juegos"])

        ab_loc = ab_vis = None
        j = juegos.get((loc, vis))
        if j:
            if j["abridor_local"]["era"]:
                ab_loc = m_mlb.Abridor(j["abridor_local"]["nombre"], j["abridor_local"]["era"])
            if j["abridor_visita"]["era"]:
                ab_vis = m_mlb.Abridor(j["abridor_visita"]["nombre"], j["abridor_visita"]["era"])

        r = m_mlb.probabilidad_local(e_loc, e_vis, ab_loc, ab_vis)
        probs = {
            clave_seleccion(ev.local, None): r["p_local"],
            clave_seleccion(ev.visita, None): r["p_visita"],
        }

        pron = Pronostico(probs=probs)

        linea = _linea_modal(ev, "totals")
        if linea is not None:
            t = m_mlb.total_carreras(e_loc, e_vis, ab_loc, ab_vis, linea)
            probs[clave_seleccion("Over", linea)] = t["p_mas"]
            probs[clave_seleccion("Under", linea)] = t["p_menos"]
            pron.total = m_mlb.distribucion_carreras(e_loc, e_vis, ab_loc, ab_vis)

        # La linea de carreras (-1.5) se deja al detector de mercado a proposito:
        # el modelo da probabilidad de ganar, no distribucion de margenes, y
        # convertir una en otra a ojo mete mas error del que quita.
        salida[ev.id] = pron
    return salida


# ------------------------------------------------------------------ FUTBOL
def modelo_futbol(eventos: list[Evento], params: dict) -> dict[str, Pronostico]:
    elos = datos.futbol_elo()
    salida: dict[str, Pronostico] = {}

    for ev in eventos:
        loc = datos.emparejar(ev.local, elos)
        vis = datos.emparejar(ev.visita, elos)
        if not loc or not vis:
            continue

        cfg = params.get(ev.liga)
        p = m_futbol.ParametrosLiga(**cfg) if cfg else m_futbol.ParametrosLiga()
        r = m_futbol.predecir(elos[loc], elos[vis], p)
        mk, matriz = r["mercados"], r["_matriz"]

        probs = {
            clave_seleccion(ev.local, None): mk["1"],
            clave_seleccion("Draw", None): mk["X"],
            clave_seleccion(ev.visita, None): mk["2"],
        }

        linea = _linea_modal(ev, "totals")
        if linea is not None:
            mas = sum(pr for i, fila in enumerate(matriz)
                      for j, pr in enumerate(fila) if i + j > linea)
            probs[clave_seleccion("Over", linea)] = mas
            probs[clave_seleccion("Under", linea)] = 1 - mas

        linea_h = _linea_modal(ev, "spreads", ev.local)
        if linea_h is not None:
            gana, empate = m_futbol.handicap_asiatico(matriz, linea_h)
            if empate < 1:
                probs[clave_seleccion(ev.local, linea_h)] = gana / (1 - empate)
                probs[clave_seleccion(ev.visita, -linea_h)] = 1 - gana / (1 - empate)

        pron = Pronostico(probs=probs)
        for i, fila in enumerate(matriz):
            for j, pr in enumerate(fila):
                pron.total[i + j] = pron.total.get(i + j, 0.0) + pr
                pron.margen[i - j] = pron.margen.get(i - j, 0.0) + pr
        salida[ev.id] = pron
    return salida


# --------------------------------------------------------------------- NFL
def modelo_nfl(eventos: list[Evento]) -> dict[str, Pronostico]:
    hoy = date.today()
    temporada = hoy.year if hoy.month >= 8 else hoy.year - 1

    cal = m_nfl.Calificaciones()
    for p in datos.nfl_resultados(temporada - 1):
        cal.actualizar(p["local"], p["visita"], p["pts_local"], p["pts_visita"])
    cal.regresion_temporada()
    for p in datos.nfl_resultados(temporada):
        cal.actualizar(p["local"], p["visita"], p["pts_local"], p["pts_visita"])

    salida: dict[str, Pronostico] = {}
    for ev in eventos:
        loc = datos.emparejar(ev.local, cal.elo)
        vis = datos.emparejar(ev.visita, cal.elo)
        if not loc or not vis:
            continue

        linea_h = _linea_modal(ev, "spreads", ev.local)
        linea_t = _linea_modal(ev, "totals")

        # El total proyectado sale de la linea del mercado: el modelo de Elo no
        # pronostica puntos totales, solo margenes. Opinar sobre el total sin un
        # modelo de ritmo seria inventar, asi que en totales el modelo se abstiene
        # y solo trabaja el detector de mercado.
        r = m_nfl.predecir(cal, loc, vis, linea=linea_h)

        probs = {
            clave_seleccion(ev.local, None): r["p_local"],
            clave_seleccion(ev.visita, None): r["p_visita"],
        }
        if linea_h is not None and "p_cubre_local" in r:
            probs[clave_seleccion(ev.local, linea_h)] = r["p_cubre_local"]
            probs[clave_seleccion(ev.visita, -linea_h)] = r["p_cubre_visita"]

        pron = Pronostico(probs=probs)
        pron.margen = m_nfl.distribucion_margen(r["margen_esperado"])
        salida[ev.id] = pron
    return salida
