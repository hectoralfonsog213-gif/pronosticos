"""
Captura de linea de cierre y calculo de CLV.

Corre poco antes de que empiecen los partidos. Toma el momio mas reciente de
cada jugada pendiente y lo guarda como cierre. La diferencia entre el momio que
tomaste y el de cierre es el CLV, y es la unica señal que se estabiliza rapido:
en 50 o 100 apuestas ya dice algo, mientras la ganancia tarda miles.

CLV positivo y perdiendo dinero  ->  mala suerte, el sistema sirve.
CLV negativo y ganando dinero    ->  buena suerte, el sistema no sirve.

    python -m src.cierre
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .main import cargar_config
from .sources.odds import ClienteOdds

RAIZ = Path(__file__).resolve().parent.parent


def actualizar(ruta: Path, horas: int = 3) -> int:
    if not ruta.exists():
        print("No hay registro todavia.")
        return 0

    filas = list(csv.DictReader(open(ruta, encoding="utf-8")))
    campos = list(filas[0].keys()) if filas else []
    ahora = datetime.now(timezone.utc)

    pendientes = []
    for f in filas:
        if f.get("momio_cierre"):
            continue
        try:
            inicio = datetime.fromisoformat(f["inicio"].replace("Z", "+00:00"))
        except (ValueError, KeyError):
            continue
        if ahora <= inicio <= ahora + timedelta(hours=horas):
            pendientes.append(f)

    if not pendientes:
        print("Ninguna jugada por cerrar en esta ventana.")
        return 0

    cfg = cargar_config()
    cliente = ClienteOdds()
    precios: dict[tuple[str, str], float] = {}

    for deporte, conf in cfg.get("deportes", {}).items():
        if not conf.get("activo", True):
            continue
        for liga in conf.get("ligas", []):
            try:
                for ev in cliente.momios(liga, conf.get("mercados", ["h2h"]),
                                         cfg.get("regiones", ["us"])):
                    for por_casa in ev.libros.values():
                        for casa, salidas in por_casa.items():
                            for nombre, dec, punto in salidas:
                                sel = f"{nombre} {punto:+g}" if punto is not None else nombre
                                clave = (ev.nombre, sel)
                                # El cierre es el mejor precio disponible en el mercado
                                precios[clave] = max(precios.get(clave, 0), dec)
            except Exception as e:
                print(f"  aviso: {liga}: {e}")

    n = 0
    for f in pendientes:
        cierre = precios.get((f["evento"], f["seleccion"]))
        if not cierre:
            continue
        try:
            tomado = float(f["momio_dec"])
        except (ValueError, KeyError):
            continue
        f["momio_cierre"] = f"{cierre:.3f}"
        f["clv"] = f"{tomado / cierre - 1:.4f}"
        n += 1

    with open(ruta, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        w.writerows(filas)

    print(f"{n} jugada(s) con linea de cierre registrada.")
    return n


if __name__ == "__main__":
    sys.exit(0 if actualizar(RAIZ / "datos" / "registro.csv") >= 0 else 1)
