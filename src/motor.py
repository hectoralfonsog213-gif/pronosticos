"""
Motor de analisis: convierte eventos con momios en jugadas con valor.

Dos detectores corren en paralelo:

  Mercado  Compara el precio de cada casa contra el consenso de las demas.
           No necesita que sepas nada de deportes. Es el detector que de
           verdad funciona de forma repetible.

  Modelo   Compara el precio del mercado contra tu propio pronostico. Es el
           proyecto de investigacion: puede encontrar cosas que el mercado
           no ve, y puede estar simplemente equivocado. Por eso sale marcado
           aparte y con umbral mas alto.

Nota sobre el orden: las jugadas se ordenan por valor esperado, nunca por
probabilidad. Ordenar por probabilidad da una lista de puros favoritisimos a
-1200, que es la forma mas rapida conocida de perder una banca.
"""
from __future__ import annotations

from dataclasses import dataclass

from .mercado import CotizacionCasa, Jugada, consenso, kelly, valor_esperado
from .sources.odds import Evento

NOMBRES_MERCADO = {
    "h2h": "Ganador",
    "spreads": "Hándicap",
    "totals": "Total",
}


@dataclass
class Umbrales:
    ev_minimo_mercado: float = 0.02      # 2% de ventaja contra el consenso
    ev_minimo_modelo: float = 0.04       # al modelo propio se le exige mas
    casas_minimas: int = 4               # con menos de 4 casas el consenso es ruido
    vig_maximo: float = 0.09             # ignorar casas que cobran comisiones absurdas
    fraccion_kelly: float = 0.25
    tope_stake: float = 0.02             # nunca mas del 2% de la banca en una jugada
    momio_minimo: float = 1.30           # -333
    momio_maximo: float = 6.00           # +500
    metodo_devig: str = "power"


def clave_seleccion(nombre: str, punto: float | None) -> str:
    return f"{nombre} {punto:+g}" if punto is not None else nombre


def analizar_evento(ev: Evento, u: Umbrales,
                    pesos_casa: dict[str, float] | None = None,
                    probs_modelo: dict[str, float] | None = None) -> list[Jugada]:
    """
    `probs_modelo` es opcional: {clave_seleccion: probabilidad} segun tu modelo.
    Si viene, se genera ademas la comparacion modelo contra mercado.
    """
    pesos_casa = pesos_casa or {}
    jugadas: list[Jugada] = []

    for mercado, por_casa in ev.libros.items():
        # Agrupar por linea: un hándicap de -3.5 y uno de -2.5 son mercados distintos
        grupos: dict[tuple, dict[str, list]] = {}
        for casa, salidas in por_casa.items():
            punto = salidas[0][2] if salidas else None
            clave = (round(punto, 2) if punto is not None else None,)
            grupos.setdefault(clave, {})[casa] = salidas

        for clave, casas in grupos.items():
            cotizaciones: list[CotizacionCasa] = []
            orden_nombres: list[str] | None = None

            for casa, salidas in casas.items():
                salidas = sorted(salidas, key=lambda s: s[0])
                nombres = [s[0] for s in salidas]
                if orden_nombres is None:
                    orden_nombres = nombres
                elif nombres != orden_nombres:
                    continue  # la casa lista resultados distintos: no comparable

                c = CotizacionCasa(casa, [s[1] for s in salidas], pesos_casa.get(casa, 1.0))
                c.calcular(u.metodo_devig)
                if c.vig <= u.vig_maximo:
                    cotizaciones.append(c)

            if not orden_nombres or len(cotizaciones) < u.casas_minimas:
                continue

            punto = clave[0]
            for c in cotizaciones:
                justas = consenso(cotizaciones, excluir=c.casa)
                if not justas:
                    continue

                for i, nombre in enumerate(orden_nombres):
                    d = c.decimales[i]
                    if not u.momio_minimo <= d <= u.momio_maximo:
                        continue

                    p_justa = justas[i]
                    ev_mercado = valor_esperado(p_justa, d)
                    sel = clave_seleccion(nombre, punto)
                    p_mod = (probs_modelo or {}).get(sel)
                    ev_mod = valor_esperado(p_mod, d) if p_mod is not None else None

                    usar_mercado = ev_mercado >= u.ev_minimo_mercado
                    usar_modelo = ev_mod is not None and ev_mod >= u.ev_minimo_modelo

                    if not (usar_mercado or usar_modelo):
                        continue

                    # Si ambos detectores coinciden, se apuesta a la probabilidad
                    # mas conservadora de las dos. Nunca a la mas optimista.
                    if usar_mercado and p_mod is not None:
                        p_apuesta = min(p_justa, p_mod)
                        fuente = "ambos"
                    elif usar_mercado:
                        p_apuesta, fuente = p_justa, "mercado"
                    else:
                        p_apuesta, fuente = p_mod, "modelo"

                    stake = kelly(p_apuesta, d, u.fraccion_kelly, u.tope_stake)
                    if stake <= 0:
                        continue

                    jugadas.append(Jugada(
                        deporte=ev.deporte, liga=ev.liga, evento=ev.nombre,
                        inicio=ev.inicio,
                        mercado=NOMBRES_MERCADO.get(mercado, mercado),
                        seleccion=sel, casa=c.casa, momio_dec=d,
                        p_justa=p_justa, p_modelo=p_mod,
                        ev=ev_mercado, ev_modelo=ev_mod,
                        stake=stake, n_casas=len(cotizaciones), fuente=fuente,
                        ev_minimo=(u.ev_minimo_modelo if fuente == "modelo"
                                   else u.ev_minimo_mercado),
                    ))

    return jugadas


def depurar(jugadas: list[Jugada], max_por_evento: int = 2, tope_total: int = 25,
            tope_evento: float = 0.03, tope_equipo: float = 0.04,
            tope_exposicion: float = 0.15) -> list[Jugada]:
    """
    Quita duplicados y limita la exposicion correlacionada.

    Tres problemas distintos que se resuelven aqui:

    Duplicados. Si la misma seleccion aparece en cinco casas, solo interesa la
    que mejor paga.

    Concentracion por partido. Si un solo partido genera ocho jugadas, casi
    siempre es que el modelo esta descuadrado con ese evento, no que haya ocho
    oportunidades. Ademas, apostar el ganador y el handicap del mismo equipo no
    son dos apuestas: es una apuesta al doble, porque ganan y pierden juntas.

    Concentracion por equipo. Tres partidos distintos donde todos dependen de
    que el mismo equipo juegue bien tampoco son tres apuestas independientes.
    Kelly supone independencia y sin estos topes se rompe en silencio.
    """
    mejor: dict[tuple, Jugada] = {}
    for j in jugadas:
        k = (j.evento, j.mercado, j.seleccion)
        if k not in mejor or j.momio_dec > mejor[k].momio_dec:
            mejor[k] = j

    ordenadas = sorted(mejor.values(), key=lambda j: j.ev, reverse=True)

    por_evento: dict[str, int] = {}
    stake_evento: dict[str, float] = {}
    stake_equipo: dict[str, float] = {}
    total = 0.0
    salida: list[Jugada] = []

    for j in ordenadas:
        if por_evento.get(j.evento, 0) >= max_por_evento:
            continue

        equipo = j.seleccion.rsplit(" ", 1)[0] if j.seleccion[-1].isdigit() else j.seleccion

        margen = min(
            j.stake,
            tope_evento - stake_evento.get(j.evento, 0.0),
            tope_equipo - stake_equipo.get(equipo, 0.0),
            tope_exposicion - total,
        )
        if margen <= 0.0005:       # menos de 0.05% de banca no vale la pena
            continue

        j.stake = margen
        por_evento[j.evento] = por_evento.get(j.evento, 0) + 1
        stake_evento[j.evento] = stake_evento.get(j.evento, 0.0) + margen
        stake_equipo[equipo] = stake_equipo.get(equipo, 0.0) + margen
        total += margen

        salida.append(j)
        if len(salida) >= tope_total:
            break

    return salida


def mejor_jugada(jugadas: list[Jugada], exigir_mercado: bool = True) -> Jugada | None:
    """
    Una sola jugada, la mejor, o ninguna.

    Apostar poco y bien le gana a apostar mucho y regular, pero solo si esa
    unica jugada es de verdad la mejor. El criterio no es el valor esperado mas
    alto a secas: un EV enorme casi siempre significa error de captura, linea
    que ya se movio, o un modelo descuadrado. Se prefiere la jugada con mejor
    respaldo, y entre las respaldadas, la de mayor valor.

    Con `exigir_mercado`, las jugadas que solo sostiene el modelo quedan fuera:
    son las de mayor riesgo de estar equivocadas, y cuando vas a hacer una sola
    apuesta no es donde conviene gastarla.
    """
    candidatas = [j for j in jugadas if not (exigir_mercado and j.fuente == "modelo")]
    if not candidatas:
        return None

    def puntaje(j: Jugada) -> tuple:
        respaldo = {"ambos": 2, "mercado": 1, "modelo": 0}[j.fuente]
        # Un EV por arriba de 12% en un mercado grande es sospechoso, no una joya
        ev = j.ev if j.ev <= 0.12 else 0.12 - (j.ev - 0.12)
        return (respaldo, j.n_casas >= 6, ev)

    return max(candidatas, key=puntaje)


def mejor_por_deporte(jugadas: list[Jugada], exigir_mercado: bool = True) -> list[Jugada]:
    """La mejor jugada de cada deporte, con el mismo criterio que mejor_jugada."""
    por_deporte: dict[str, list[Jugada]] = {}
    for j in jugadas:
        por_deporte.setdefault(j.deporte, []).append(j)

    salida = []
    for candidatas in por_deporte.values():
        elegida = mejor_jugada(candidatas, exigir_mercado)
        if elegida:
            salida.append(elegida)
    salida.sort(key=lambda j: j.ev, reverse=True)
    return salida


def resumen(jugadas: list[Jugada]) -> dict:
    if not jugadas:
        return {"n": 0, "ev_promedio": 0.0, "exposicion": 0.0, "por_deporte": {}}
    por_deporte: dict[str, int] = {}
    for j in jugadas:
        por_deporte[j.deporte] = por_deporte.get(j.deporte, 0) + 1
    return {
        "n": len(jugadas),
        "ev_promedio": sum(j.ev for j in jugadas) / len(jugadas),
        "exposicion": sum(j.stake for j in jugadas),
        "por_deporte": por_deporte,
    }
