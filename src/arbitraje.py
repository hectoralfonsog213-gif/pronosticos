"""
Arbitraje y middles: ganancia que no depende de pronosticar nada.

Un arbitraje existe cuando las mejores cotizaciones de cada resultado, tomadas
en casas distintas, suman menos de 100% de probabilidad implicita. Entonces se
cubre todo el mercado y se gana pase lo que pase.

Un middle es distinto: se toman los dos lados con lineas separadas, de modo que
existe un rango de resultados donde ganan las dos apuestas. No es dinero seguro,
pero el costo de fallar es pequeño y el pago de acertar es grande. En la NFL los
middles alrededor del 3 y el 7 son los que valen, porque ahi es donde de verdad
caen los margenes.

Ninguno de los dos necesita modelo. Es aritmetica sobre precios que ya tienes.
"""
from __future__ import annotations

from dataclasses import dataclass

from .motor import clave_seleccion
from .sources.odds import Evento


@dataclass
class Arbitraje:
    evento: str
    liga: str
    inicio: str
    mercado: str
    patas: list[tuple[str, str, float, float]]  # (seleccion, casa, decimal, % del total)
    margen: float                                # ganancia garantizada

    def dict(self) -> dict:
        return {
            "evento": self.evento, "liga": self.liga, "inicio": self.inicio,
            "mercado": self.mercado, "margen": round(self.margen, 4),
            "patas": [{"seleccion": s, "casa": c, "momio_dec": round(d, 3),
                       "reparto": round(r, 4)} for s, c, d, r in self.patas],
        }


@dataclass
class Middle:
    evento: str
    liga: str
    inicio: str
    mercado: str
    pata_a: tuple[str, str, float]   # (seleccion, casa, decimal)
    pata_b: tuple[str, str, float]
    ventana: str                     # rango de resultados donde ganan las dos
    ancho: float
    ganancia: float                  # por unidad total arriesgada, si pega
    perdida: float                   # por unidad total arriesgada, si falla
    prob_necesaria: float            # probabilidad de la ventana para salir tablas

    def dict(self) -> dict:
        return {
            "evento": self.evento, "liga": self.liga, "inicio": self.inicio,
            "mercado": self.mercado, "ventana": self.ventana, "ancho": self.ancho,
            "pata_a": {"seleccion": self.pata_a[0], "casa": self.pata_a[1],
                       "momio_dec": round(self.pata_a[2], 3)},
            "pata_b": {"seleccion": self.pata_b[0], "casa": self.pata_b[1],
                       "momio_dec": round(self.pata_b[2], 3)},
            "ganancia": round(self.ganancia, 4), "perdida": round(self.perdida, 4),
            "prob_necesaria": round(self.prob_necesaria, 4),
        }


# ------------------------------------------------------------- arbitrajes
def buscar_arbitrajes(eventos: list[Evento], margen_minimo: float = 0.005,
                      excluir_casas: set[str] | None = None) -> list[Arbitraje]:
    excluir = excluir_casas or set()
    salida: list[Arbitraje] = []

    for ev in eventos:
        for mercado, por_casa in ev.libros.items():
            # Agrupar por linea: -3.5 y -2.5 son mercados distintos
            grupos: dict[str, dict[str, list]] = {}
            for casa, salidas in por_casa.items():
                if casa in excluir:
                    continue
                punto = salidas[0][2] if salidas else None
                grupos.setdefault("" if punto is None else f"{punto:g}", {})[casa] = salidas

            for etiqueta, casas in grupos.items():
                mejor: dict[str, tuple[str, float]] = {}
                for casa, salidas in casas.items():
                    for nombre, dec, punto in salidas:
                        sel = clave_seleccion(nombre, punto)
                        if sel not in mejor or dec > mejor[sel][1]:
                            mejor[sel] = (casa, dec)

                if len(mejor) < 2:
                    continue
                suma = sum(1 / d for _c, d in mejor.values())
                if suma >= 1 - margen_minimo:
                    continue
                # Se requieren al menos dos casas distintas: una sola casa que se
                # contradice a si misma casi siempre es un error que cancelan.
                if len({c for c, _d in mejor.values()}) < 2:
                    continue

                margen = 1 / suma - 1
                patas = [(sel, casa, dec, (1 / dec) / suma) for sel, (casa, dec) in mejor.items()]
                salida.append(Arbitraje(ev.nombre, ev.liga, ev.inicio, mercado, patas, margen))

    salida.sort(key=lambda a: a.margen, reverse=True)
    return salida


# ----------------------------------------------------------------- middles
def _lado(nombre: str) -> str | None:
    n = nombre.lower()
    if n in ("over", "más", "mas"):
        return "over"
    if n in ("under", "menos"):
        return "under"
    return None


def buscar_middles(eventos: list[Evento], ancho_minimo: float = 1.0,
                   perdida_maxima: float = 0.06) -> list[Middle]:
    """
    `perdida_maxima` es cuanto estas dispuesto a perder por unidad cuando el
    middle falla. Por arriba de 6% deja de valer la pena salvo ventanas muy
    anchas o alrededor de numeros clave.
    """
    salida: list[Middle] = []

    for ev in eventos:
        for mercado in ("totals", "spreads"):
            ofertas: list[tuple[str, str, float, float]] = []  # (lado, casa, punto, dec)
            for casa, salidas in ev.libros.get(mercado, {}).items():
                for nombre, dec, punto in salidas:
                    if punto is None:
                        continue
                    lado = _lado(nombre) if mercado == "totals" else (
                        "local" if nombre == ev.local else "visita")
                    if lado:
                        ofertas.append((lado, casa, float(punto), dec))

            if mercado == "totals":
                bajos = [o for o in ofertas if o[0] == "over"]
                altos = [o for o in ofertas if o[0] == "under"]
            else:
                bajos = [o for o in ofertas if o[0] == "local"]
                altos = [o for o in ofertas if o[0] == "visita"]

            for _l1, casa1, p1, d1 in bajos:
                for _l2, casa2, p2, d2 in altos:
                    if casa1 == casa2:
                        continue

                    if mercado == "totals":
                        # Over p1 y Under p2 ganan juntos si p1 < total < p2
                        ancho = p2 - p1
                        ventana = f"total entre {p1:g} y {p2:g}"
                    else:
                        # Local p1 y Visita p2 ganan juntos si -p1 < margen < p2
                        ancho = p1 + p2
                        ventana = f"margen del local entre {-p1:g} y {p2:g}"

                    if ancho < ancho_minimo:
                        continue

                    # Apuesta pareja en las dos patas, media unidad cada una
                    gana_ambas = 0.5 * (d1 - 1) + 0.5 * (d2 - 1)
                    gana_una = 0.5 * (max(d1, d2) - 1) - 0.5
                    if gana_una > 0:
                        continue  # esto ya es arbitraje, se reporta en la otra lista
                    if -gana_una > perdida_maxima:
                        continue

                    prob_nec = -gana_una / (gana_ambas - gana_una)
                    salida.append(Middle(
                        ev.nombre, ev.liga, ev.inicio, mercado,
                        (f"{'Over' if mercado == 'totals' else ev.local} {p1:+g}", casa1, d1),
                        (f"{'Under' if mercado == 'totals' else ev.visita} {p2:+g}", casa2, d2),
                        ventana, ancho, gana_ambas, gana_una, prob_nec,
                    ))

    salida.sort(key=lambda m: (m.ancho, -m.prob_necesaria), reverse=True)
    return salida


def middles_con_modelo(middles: list[Middle],
                       probs: dict[str, dict[str, float]]) -> list[tuple[Middle, float, float]]:
    """
    Cuando hay un modelo con distribucion de margenes o totales, se puede
    estimar la probabilidad real de la ventana y saber si el middle paga.
    Devuelve (middle, probabilidad_estimada, valor_esperado).
    """
    salida = []
    for m in middles:
        p = (probs.get(m.evento) or {}).get(f"ventana:{m.ventana}")
        if p is None:
            continue
        ev = p * m.ganancia + (1 - p) * m.perdida
        salida.append((m, p, ev))
    salida.sort(key=lambda t: t[2], reverse=True)
    return salida
