"""
Cartelera: mantiene vivas las jugadas entre corridas.

Esto arregla un problema que no se ve hasta que el sistema corre seguido. La
agenda no consulta todas las ligas en cada corrida: si revisa la Liga MX cada
60 minutos y el sistema corre cada 30, la mitad de las corridas no la tocan.
Sin cartelera, esas corridas reescribian la pagina con cero jugadas y la jugada
encontrada a las 14:00 desaparecia a las 14:30, aunque el partido fuera a las
18:00 y la apuesta siguiera siendo buena.

La regla de vigencia es la parte importante:

  - Si la liga SI se revisó en esta corrida y la jugada ya no aparece, se cae.
    El mercado la corrigio y ya no hay valor: mostrarla seria mentir.
  - Si la liga NO se revisó, la jugada se conserva tal como estaba, con su edad
    a la vista para que sepas que tan fresco es ese precio.
  - Cuando el partido empieza, se cae siempre.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .mercado import Jugada

# Margen antes del inicio en el que una jugada deja de ofrecerse. Apostar con el
# partido a punto de empezar es como se toman las peores decisiones.
MARGEN_CIERRE_MIN = 5


def _parse(iso) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError, TypeError):
        return None


def clave(j: Jugada) -> str:
    return f"{j.evento}|{j.mercado}|{j.seleccion}|{j.casa}"


def _a_dict(j: Jugada, visto: datetime) -> dict:
    return {
        "visto": visto.isoformat(timespec="seconds"),
        "deporte": j.deporte, "liga": j.liga, "evento": j.evento, "inicio": j.inicio,
        "mercado": j.mercado, "seleccion": j.seleccion, "casa": j.casa,
        "momio_dec": j.momio_dec, "p_justa": j.p_justa, "p_modelo": j.p_modelo,
        "ev": j.ev, "ev_modelo": j.ev_modelo, "stake": j.stake,
        "n_casas": j.n_casas, "fuente": j.fuente, "ev_minimo": j.ev_minimo,
    }


def _a_jugada(d: dict) -> Jugada:
    return Jugada(
        deporte=d["deporte"], liga=d["liga"], evento=d["evento"], inicio=d["inicio"],
        mercado=d["mercado"], seleccion=d["seleccion"], casa=d["casa"],
        momio_dec=d["momio_dec"], p_justa=d["p_justa"], p_modelo=d.get("p_modelo"),
        ev=d["ev"], ev_modelo=d.get("ev_modelo"), stake=d["stake"],
        n_casas=d["n_casas"], fuente=d["fuente"], ev_minimo=d.get("ev_minimo", 0.02),
    )


def cargar(ruta: Path, ahora: datetime) -> dict[str, dict]:
    """Lee las jugadas guardadas y descarta las de partidos que ya empezaron."""
    try:
        guardadas = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(guardadas, dict):
        return {}

    limite = ahora + timedelta(minutes=MARGEN_CIERRE_MIN)
    vivas = {}
    for k, d in guardadas.items():
        inicio = _parse(d.get("inicio"))
        if inicio is None or inicio > limite:
            vivas[k] = d
    return vivas


def fusionar(guardadas: dict[str, dict], nuevas: list[Jugada],
             ligas_revisadas: set[str], ahora: datetime) -> list[Jugada]:
    """
    Junta lo guardado con lo recien encontrado, aplicando la regla de vigencia.

    `ligas_revisadas` son las ligas que esta corrida SI consultó. Una jugada de
    una liga revisada que no volvió a aparecer se considera corregida por el
    mercado y se cae.
    """
    claves_nuevas = {clave(j) for j in nuevas}

    sobrevivientes: list[Jugada] = []
    for k, d in guardadas.items():
        if k in claves_nuevas:
            continue  # viene actualizada en `nuevas`
        if d.get("liga") in ligas_revisadas:
            continue  # se revisó y ya no está: el mercado la corrigió
        sobrevivientes.append(_a_jugada(d))

    return list(nuevas) + sobrevivientes


def guardar(ruta: Path, jugadas: list[Jugada], guardadas: dict[str, dict],
            ahora: datetime) -> None:
    """Escribe el estado, conservando la hora en que cada jugada se vio primero."""
    estado = {}
    for j in jugadas:
        k = clave(j)
        visto = _parse((guardadas.get(k) or {}).get("visto")) or ahora
        estado[k] = _a_dict(j, visto)

    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


def edad_min(j: Jugada, guardadas: dict[str, dict], ahora: datetime) -> int:
    """Minutos desde que este precio se vio por primera vez."""
    visto = _parse((guardadas.get(clave(j)) or {}).get("visto"))
    if visto is None:
        return 0
    return max(0, int((ahora - visto).total_seconds() // 60))
