"""
Orquestador. Esta pensado para correr cada 15 minutos, no una vez al dia.

Ciclo completo:

  agenda -> momios -> historial -> modelos -> detectores -> reporte -> registro

Cuatro detectores corren sobre los mismos datos:

  Mercado      precio de una casa contra el consenso de las demas
  Modelo       mercado contra tu propio pronostico
  Movimiento   linea que ya se movio y alguna casa no siguio
  Arbitraje    y middles, que no dependen de pronosticar nada

Todo va en try/except por deporte: si una fuente cambia de formato, las demas
siguen. Un pipeline que se muere entero por un campo no sirve para correr solo.

    python -m src.main                 corrida normal
    python -m src.main --sin-modelos   solo detectores de mercado
    python -m src.main --verificar     prueba las fuentes, no gasta cuota
    python -m src.main --seco          simula la agenda sin pedir momios
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import agenda, arbitraje, cartelera, historial
from .mercado import Jugada
from .motor import (Umbrales, analizar_evento, depurar, mejor_jugada,
                    mejor_por_deporte, resumen)
from .puente import Pronostico, modelo_futbol, modelo_mlb, modelo_nfl
from .reporte import escribir_html, escribir_json, registrar
from .sources import datos
from .sources.odds import ClienteOdds, Evento

RAIZ = Path(__file__).resolve().parent.parent
MODELOS = {"mlb": modelo_mlb, "nfl": modelo_nfl, "futbol": modelo_futbol}


def cargar_config(ruta: Path | None = None) -> dict:
    with open(ruta or RAIZ / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _valuar_middles(middles, pronosticos: dict[str, Pronostico],
                    eventos: list[Evento], ev_minimo: float = 0.03) -> list[dict]:
    """Le pone probabilidad real a cada middle usando la distribucion del modelo."""
    por_nombre = {ev.nombre: ev.id for ev in eventos}
    salida = []
    for m in middles:
        d = m.dict()
        pron = pronosticos.get(por_nombre.get(m.evento, ""))
        if pron:
            if m.mercado == "totals":
                lo, hi = sorted([float(m.pata_a[0].split()[-1]), float(m.pata_b[0].split()[-1])])
                p = pron.p_ventana("total", lo, hi)
            else:
                lo = -float(m.pata_a[0].split()[-1])
                hi = float(m.pata_b[0].split()[-1])
                p = pron.p_ventana("margen", lo, hi)
            if p is not None:
                d["p_modelo"] = round(p, 4)
                d["ev"] = round(p * m.ganancia + (1 - p) * m.perdida, 4)
        salida.append(d)

    # Primero los que el modelo valida; los demas se conservan al final
    salida.sort(key=lambda x: (x.get("ev") is not None, x.get("ev", 0)), reverse=True)
    return [d for d in salida if d.get("ev") is None or d["ev"] >= ev_minimo]


def correr(cfg: dict, sin_modelos: bool = False, seco: bool = False,
           forzar: bool = False) -> dict:
    ahora = datetime.now(timezone.utc)
    cliente = ClienteOdds()
    presupuesto = agenda.Presupuesto(RAIZ / "datos" / "presupuesto.json",
                                     cfg.get("presupuesto_mensual", 500))
    u = Umbrales(**cfg.get("umbrales", {}))
    pesos = cfg.get("pesos_casa", {})
    avisos: list[str] = []

    plan, avisos_agenda = agenda.decidir(cliente, cfg, presupuesto, ahora, forzar)
    avisos += avisos_agenda
    costo = agenda.costo_estimado(plan, cfg)
    # Con revision diaria solo interesan los partidos de ese dia: los de manana
    # se revisan manana, con momios mas frescos.
    horizonte = cfg.get("horizonte_horas")
    hasta = ahora + timedelta(hours=horizonte) if horizonte else None

    if seco:
        return {"plan": plan, "costo": costo, "avisos": avisos, "jugadas": [],
                "movimientos": [], "arbitrajes": [], "middles": [], "ahora": ahora}

    todos_eventos: list[Evento] = []
    jugadas: list[Jugada] = []
    pronosticos: dict[str, Pronostico] = {}

    for deporte, ligas in plan.items():
        conf = cfg["deportes"][deporte]
        eventos: list[Evento] = []
        for liga in ligas:
            try:
                eventos += cliente.momios(liga, conf.get("mercados", ["h2h"]),
                                          cfg.get("regiones", ["us"]), hasta=hasta)
            except Exception as e:
                avisos.append(f"momios {liga}: {e}")
        if not eventos:
            continue
        todos_eventos += eventos

        if not sin_modelos and conf.get("usar_modelo", True):
            try:
                fn = MODELOS[deporte]
                pronosticos.update(
                    fn(eventos, cfg.get("parametros_liga", {})) if deporte == "futbol"
                    else fn(eventos))
            except Exception as e:
                avisos.append(f"modelo {deporte}: {e} (sigue el detector de mercado)")

        for ev in eventos:
            try:
                pron = pronosticos.get(ev.id)
                jugadas += analizar_evento(ev, u, pesos, pron.probs if pron else None)
            except Exception as e:
                avisos.append(f"análisis {ev.nombre}: {e}")

    hist_dir = RAIZ / "datos" / "lineas"
    movimientos = []
    if todos_eventos:
        try:
            movimientos = historial.detectar(
                todos_eventos, hist_dir, ahora, pesos,
                ventana_min=cfg.get("movimiento", {}).get("ventana_min", 120),
                umbral_mov=cfg.get("movimiento", {}).get("umbral", 0.025),
                ev_minimo=u.ev_minimo_mercado, metodo=u.metodo_devig)
            historial.guardar(todos_eventos, ahora, hist_dir)
            historial.purgar(hist_dir, cfg.get("movimiento", {}).get("retencion_dias", 21))
        except Exception as e:
            avisos.append(f"historial: {e}")

    arbs = middles = []
    try:
        arbs = arbitraje.buscar_arbitrajes(
            todos_eventos, cfg.get("arbitraje", {}).get("margen_minimo", 0.005))
        middles = _valuar_middles(
            arbitraje.buscar_middles(
                todos_eventos,
                cfg.get("arbitraje", {}).get("ancho_minimo", 1.0),
                cfg.get("arbitraje", {}).get("perdida_maxima", 0.06)),
            pronosticos, todos_eventos,
            cfg.get("arbitraje", {}).get("ev_minimo_middle", 0.03))
    except Exception as e:
        avisos.append(f"arbitrajes: {e}")

    if costo:
        presupuesto.cobrar(costo, ahora)
        presupuesto.marcar([l for ls in plan.values() for l in ls], ahora)
    presupuesto.sincronizar(cliente.restantes)
    presupuesto.guardar()
    avisos.append(f"créditos: {presupuesto.gastado}/{presupuesto.mensual} del mes "
                  f"(esta corrida gastó {costo})")

    # La cartelera mantiene vivas las jugadas de ligas que esta corrida no
    # revisó. Sin esto, correr cada 30 min con intervalos de 60 borraba de la
    # página jugadas perfectamente válidas cuyo partido aún no empezaba.
    ruta_activas = RAIZ / "datos" / "activas.json"
    guardadas = cartelera.cargar(ruta_activas, ahora)
    ligas_revisadas = {ev.liga for ev in todos_eventos}
    jugadas = cartelera.fusionar(guardadas, jugadas, ligas_revisadas, ahora)

    finales = depurar(
        jugadas, cfg.get("max_por_evento", 2), cfg.get("tope_jugadas", 25),
        cfg.get("exposicion", {}).get("tope_evento", 0.03),
        cfg.get("exposicion", {}).get("tope_equipo", 0.04),
        cfg.get("exposicion", {}).get("tope_total", 0.15))

    modo = cfg.get("modo", "todas")
    exigir = cfg.get("exigir_respaldo_mercado", True)
    if modo == "una_jugada":
        unica = mejor_jugada(finales, exigir)
        finales = [unica] if unica else []
    elif modo == "una_por_deporte":
        finales = mejor_por_deporte(finales, exigir)

    tope_ev = cfg.get("exposicion", {}).get("tope_evento", 0.03)
    for j in finales:
        j.stake = min(j.stake, tope_ev)

    cartelera.guardar(ruta_activas, finales, guardadas, ahora)
    edades = {cartelera.clave(j): cartelera.edad_min(j, guardadas, ahora) for j in finales}

    return {"plan": plan, "costo": costo, "avisos": avisos, "jugadas": finales,
            "movimientos": movimientos, "arbitrajes": arbs, "middles": middles,
            "ahora": ahora, "eventos": len(todos_eventos), "edades": edades,
            "consulto": bool(plan), "forzado": forzar,
            "ligas_revisadas": sorted(ligas_revisadas)}


# ------------------------------------------------------------ notificacion
def _nuevas(jugadas: list[Jugada], ruta: Path) -> list[Jugada]:
    """Solo lo que no se ha avisado antes. Corriendo cada 15 min, sin esto el
    telefono suena con las mismas jugadas ochenta veces al dia."""
    try:
        vistas = set(json.loads(ruta.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        vistas = set()
    hoy = date.today().isoformat()
    vistas = {v for v in vistas if v.startswith(hoy)}

    nuevas, claves = [], set(vistas)
    for j in jugadas:
        k = f"{hoy}|{j.evento}|{j.seleccion}|{j.casa}"
        if k not in claves:
            nuevas.append(j)
            claves.add(k)

    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(sorted(claves), ensure_ascii=False), encoding="utf-8")
    return nuevas


# --------------------------------------------------------------- verificar
def verificar() -> int:
    pruebas = [
        ("MLB  equipos", lambda: len(datos.mlb_equipos(date.today().year))),
        ("MLB  juegos de hoy", lambda: len(datos.mlb_juegos(date.today()))),
        ("NFL  próximos", lambda: len(datos.nfl_proximos())),
        ("NFL  resultados (Elo)", lambda: len(datos.nfl_resultados(
            date.today().year - 1, range(1, 2)))),
        ("Fútbol  Elo de clubes", lambda: len(datos.futbol_elo())),
    ]
    fallos = 0
    for nombre, fn in pruebas:
        try:
            n = fn()
            print(f"  [{'ok' if n else 'vacío':5s}] {nombre}: {n} registros")
            fallos += 0 if n else 1
        except Exception as e:
            print(f"  [falla] {nombre}: {type(e).__name__}: {e}")
            fallos += 1
    try:
        c = ClienteOdds()
        ligas = c.deportes()
        print(f"  [ok   ] API de momios: {len(ligas)} ligas activas (consulta gratuita)")
        claves = sorted(d["key"] for d in ligas
                        if d.get("key", "").startswith(("soccer", "baseball", "american")))
        print(f"\n  Claves disponibles ahora mismo:\n    " + "\n    ".join(claves[:40]))
    except Exception as e:
        print(f"  [falla] API de momios: {e}")
        fallos += 1
    return fallos


def main() -> int:
    ap = argparse.ArgumentParser(description="Detector de valor en apuestas")
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--sin-modelos", action="store_true")
    ap.add_argument("--verificar", action="store_true")
    ap.add_argument("--seco", action="store_true", help="simula sin gastar créditos")
    ap.add_argument("--forzar", action="store_true",
                    help="revisa ya, sin esperar los intervalos de la agenda")
    ap.add_argument("--salida", type=Path, default=RAIZ / "docs")
    args = ap.parse_args()

    if args.verificar:
        print("Verificando fuentes de datos\n")
        fallos = verificar()
        print(f"\n{'Todo en orden.' if not fallos else f'{fallos} fuente(s) con problema.'}")
        return 1 if fallos else 0

    cfg = cargar_config(args.config)
    try:
        r = correr(cfg, args.sin_modelos, args.seco, args.forzar)
    except Exception:
        traceback.print_exc()
        return 2

    if args.seco:
        print(f"Plan: {r['plan'] or 'nada que consultar'} → {r['costo']} créditos")
        for a in r["avisos"]:
            print(f"  {a}")
        return 0

    args.salida.mkdir(parents=True, exist_ok=True)
    escribir_json(r, args.salida / "jugadas.json")
    escribir_html(r, args.salida / "index.html", RAIZ / "datos" / "registro.csv")
    registrar(r["jugadas"], r["ahora"], RAIZ / "datos" / "registro.csv")

    res = resumen(r["jugadas"])
    print(f"{r.get('eventos', 0)} eventos | {res['n']} jugadas "
          f"| {len(r['movimientos'])} movimientos "
          f"| {len(r['arbitrajes'])} arbitrajes | {len(r['middles'])} middles")
    for a in r["avisos"]:
        print(f"  {a}")

    if cfg.get("telegram", {}).get("activo"):
        nuevas = _nuevas(r["jugadas"], RAIZ / "datos" / "notificadas.json")
        if nuevas or r["movimientos"] or r["arbitrajes"]:
            try:
                from notify.telegram import enviar
                enviar(nuevas, resumen(nuevas), r["movimientos"], r["arbitrajes"])
            except Exception as e:
                print(f"  aviso: telegram: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
