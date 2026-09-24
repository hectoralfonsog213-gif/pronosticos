"""
Modo demostracion: genera la pagina real del sistema con datos de ejemplo.

Sirve para dos cosas. Ver como se vera el tablero antes de tener llave de API,
y probar que el renderizado funciona despues de tocar el codigo sin gastar
creditos ni esperar a que haya partidos.

Los datos son inventados a proposito y la pagina lo dice con un aviso arriba,
para que nadie confunda una vista previa con jugadas reales.

    python -m src.demo
"""
from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .arbitraje import Arbitraje
from .historial import Movimiento
from .mercado import Jugada, am_a_dec
from .reporte import escribir_html, escribir_json

RAIZ = Path(__file__).resolve().parent.parent


def construir(ahora: datetime | None = None) -> dict:
    ahora = ahora or datetime.now(timezone.utc)

    jugadas = [
        Jugada(
            deporte="nfl", liga="NFL", evento="Buffalo Bills vs Detroit Lions",
            inicio=(ahora + timedelta(hours=3)).isoformat(),
            mercado="Hándicap", seleccion="Detroit Lions +6.5", casa="BetRivers",
            momio_dec=am_a_dec(-102), p_justa=0.5385, p_modelo=0.5512,
            ev=0.0562, ev_modelo=0.0812, stake=0.0138, n_casas=7,
            fuente="ambos", ev_minimo=0.02,
        ),
        Jugada(
            deporte="mlb", liga="MLB", evento="Seattle Mariners vs Texas Rangers",
            inicio=(ahora + timedelta(hours=5)).isoformat(),
            mercado="Ganador", seleccion="Seattle Mariners", casa="Bovada",
            momio_dec=am_a_dec(138), p_justa=0.4498, p_modelo=0.4402,
            ev=0.0465, ev_modelo=0.0237, stake=0.0121, n_casas=6,
            fuente="mercado", ev_minimo=0.02,
        ),
        Jugada(
            deporte="futbol", liga="Liga MX", evento="Chivas vs América",
            inicio=(ahora + timedelta(hours=8)).isoformat(),
            mercado="Total", seleccion="Under +2.5", casa="Caliente",
            momio_dec=am_a_dec(-105), p_justa=0.5340, p_modelo=0.5611,
            ev=0.0413, ev_modelo=0.0942, stake=0.0102, n_casas=5,
            fuente="ambos", ev_minimo=0.02,
        ),
    ]

    movimientos = [
        Movimiento(
            evento="New York Yankees vs Boston Red Sox", mercado="h2h",
            seleccion="Boston Red Sox", p_antes=0.4120, p_ahora=0.4495,
            casa_rezagada="Bovada", momio_rezagado=am_a_dec(155),
            ev=0.0462, minutos=120,
        ),
        Movimiento(
            evento="Chivas vs América", mercado="totals",
            seleccion="Under +2.5", p_antes=0.5240, p_ahora=0.5605,
            casa_rezagada="Caliente", momio_rezagado=am_a_dec(-108),
            ev=0.0783, minutos=120,
        ),
    ]

    arbitrajes = [
        Arbitraje(
            evento="Seattle Mariners vs Texas Rangers", liga="MLB",
            inicio=(ahora + timedelta(hours=5)).isoformat(), mercado="h2h",
            patas=[("Seattle Mariners", "DraftKings", am_a_dec(138), 0.4262),
                   ("Texas Rangers", "BetMGM", am_a_dec(-118), 0.5738)],
            margen=0.0184,
        ),
    ]

    middles = [
        {"evento": "Buffalo Bills vs Detroit Lions", "liga": "NFL",
         "inicio": (ahora + timedelta(hours=3)).isoformat(), "mercado": "spreads",
         "ventana": "margen del local entre 3.5 y 7.5", "ancho": 4.0,
         "pata_a": {"seleccion": "Buffalo Bills -3.5", "casa": "FanDuel", "momio_dec": 1.909},
         "pata_b": {"seleccion": "Detroit Lions +7.5", "casa": "Caesars", "momio_dec": 1.952},
         "ganancia": 0.9305, "perdida": -0.0240, "prob_necesaria": 0.0251,
         "p_modelo": 0.1483, "ev": 0.1175},
        {"evento": "Los Angeles Dodgers vs San Diego Padres", "liga": "MLB",
         "inicio": (ahora + timedelta(hours=6)).isoformat(), "mercado": "totals",
         "ventana": "total entre 7.5 y 9.5", "ancho": 2.0,
         "pata_a": {"seleccion": "Over +7.5", "casa": "BetMGM", "momio_dec": 1.869},
         "pata_b": {"seleccion": "Under +9.5", "casa": "DraftKings", "momio_dec": 1.909},
         "ganancia": 0.8890, "perdida": -0.0455, "prob_necesaria": 0.0487,
         "p_modelo": 0.2231, "ev": 0.1630},
    ]

    return {
        "ahora": ahora, "jugadas": jugadas, "movimientos": movimientos,
        "arbitrajes": arbitrajes, "middles": middles, "plan": {}, "costo": 4,
        "eventos": 38, "demo": True, "consulto": True,
        "edades": {"Chivas vs América|Total|Under +2.5|Caliente": 34},
        "avisos": [
            "créditos: 213/500 del mes (esta corrida gastó 4)",
            "2 liga(s) pospuestas por presupuesto (287 créditos para el resto del mes)",
            "modelo futbol: 3 equipos sin emparejar con ClubElo",
        ],
    }


def registro_ejemplo(ruta: Path, n: int = 190) -> None:
    """Historial simulado, para que la sección de calibración tenga qué mostrar."""
    random.seed(11)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    campos = ["fecha_registro", "inicio", "deporte", "liga", "evento", "mercado",
              "seleccion", "casa", "momio_dec", "momio_am", "p_justa", "p_modelo",
              "ev", "stake_pct", "n_casas", "fuente", "momio_cierre", "clv", "resultado"]
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(campos)
        for i in range(n):
            p = random.uniform(0.30, 0.68)
            dec = (1 / p) * 1.035
            gano = random.random() < p
            w.writerow([
                f"2026-0{7 + i // 70}-{1 + i % 28:02d}T14:00:00", "", "nfl", "NFL",
                "ejemplo", "Ganador", "ejemplo", "DraftKings", round(dec, 3), "-110",
                round(p, 4), "", 0.035, round(random.uniform(0.6, 1.8), 2), 6,
                "mercado", "", round(random.gauss(0.021, 0.028), 4),
                "ganada" if gano else "perdida",
            ])


def construir_vacio(consulto: bool, ahora: datetime | None = None) -> dict:
    """
    Las dos caras del dia sin jugadas.

    `consulto=True`  -> se revisaron los partidos y ninguno pasó el filtro.
    `consulto=False` -> no había nada dentro de la ventana, no se miró.
    """
    ahora = ahora or datetime.now(timezone.utc)
    avisos = ([f"créditos: 213/500 del mes (esta corrida gastó 4)"] if consulto
              else ["ningún partido en ventana: esta corrida no gastó créditos",
                    "créditos: 209/500 del mes (esta corrida gastó 0)"])
    return {
        "ahora": ahora, "jugadas": [], "movimientos": [], "arbitrajes": [],
        "middles": [], "plan": {}, "costo": 4 if consulto else 0,
        "eventos": 26 if consulto else 0, "demo": True, "consulto": consulto,
        "edades": {}, "avisos": avisos,
    }


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Vista previa del tablero")
    ap.add_argument("--vacio", action="store_true",
                    help="muestra el día sin jugadas (revisó y no encontró)")
    ap.add_argument("--sin-revisar", action="store_true",
                    help="muestra la corrida que no consultó ninguna liga")
    args = ap.parse_args()

    salida = RAIZ / "docs"
    registro = RAIZ / "datos" / "registro_demo.csv"
    registro_ejemplo(registro)

    if args.vacio:
        r = construir_vacio(consulto=True)
    elif args.sin_revisar:
        r = construir_vacio(consulto=False)
    else:
        r = construir()

    escribir_json(r, salida / "jugadas.json")
    escribir_html(r, salida / "index.html", registro)

    print(f"Vista previa generada en {salida / 'index.html'}")
    print("Los datos son de ejemplo. La página lo indica arriba.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
