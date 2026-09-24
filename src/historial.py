"""
Historial de lineas y deteccion de movimientos.

Guardar cada linea que se observa convierte un detector estatico en uno
dinamico. Con historial se puede ver algo que una sola foto no muestra: que las
casas afiladas ya movieron una linea y las blandas todavia no. Esa ventana dura
minutos y es donde esta el dinero mas limpio que un aficionado puede tomar.

Formato: CSV plano por dia, appendable, sin base de datos. A razon de unas
40 mil lineas al dia pesa cerca de 3 MB por dia, asi que se purga solo.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .mercado import CotizacionCasa, consenso
from .motor import clave_seleccion
from .sources.odds import Evento

CAMPOS = ["ts", "evento_id", "evento", "mercado", "punto", "casa", "seleccion", "decimal"]


def guardar(eventos: list[Evento], ahora: datetime, directorio: Path) -> int:
    """Escribe una foto de todas las lineas observadas."""
    directorio.mkdir(parents=True, exist_ok=True)
    ruta = directorio / f"lineas_{ahora.strftime('%Y-%m-%d')}.csv"
    nuevo = not ruta.exists()
    ts = ahora.isoformat(timespec="seconds")
    n = 0

    with open(ruta, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(CAMPOS)
        for ev in eventos:
            for mercado, por_casa in ev.libros.items():
                for casa, salidas in por_casa.items():
                    for nombre, dec, punto in salidas:
                        w.writerow([ts, ev.id, ev.nombre, mercado,
                                    "" if punto is None else punto,
                                    casa, clave_seleccion(nombre, punto), f"{dec:.4f}"])
                        n += 1
    return n


def cargar(directorio: Path, desde: datetime) -> list[dict]:
    """Lee las lineas observadas desde un momento dado."""
    if not directorio.exists():
        return []
    filas = []
    for dia in range(3):
        fecha = (desde + timedelta(days=dia)).strftime("%Y-%m-%d")
        ruta = directorio / f"lineas_{fecha}.csv"
        if not ruta.exists():
            continue
        with open(ruta, encoding="utf-8") as f:
            for fila in csv.DictReader(f):
                try:
                    if datetime.fromisoformat(fila["ts"]) >= desde:
                        filas.append(fila)
                except (ValueError, KeyError):
                    continue
    return filas


def purgar(directorio: Path, dias: int = 21) -> int:
    """Borra historial viejo. Sin esto el repositorio crece sin freno."""
    if not directorio.exists():
        return 0
    limite = datetime.now(timezone.utc) - timedelta(days=dias)
    n = 0
    for ruta in directorio.glob("lineas_*.csv"):
        try:
            fecha = datetime.strptime(ruta.stem.replace("lineas_", ""), "%Y-%m-%d")
        except ValueError:
            continue
        if fecha.replace(tzinfo=timezone.utc) < limite:
            ruta.unlink()
            n += 1
    return n


# ------------------------------------------------------------ movimientos
@dataclass
class Movimiento:
    evento: str
    mercado: str
    seleccion: str
    p_antes: float
    p_ahora: float
    casa_rezagada: str
    momio_rezagado: float
    ev: float
    minutos: int

    @property
    def desplazamiento(self) -> float:
        return self.p_ahora - self.p_antes

    def dict(self) -> dict:
        return {
            "evento": self.evento, "mercado": self.mercado, "seleccion": self.seleccion,
            "p_antes": round(self.p_antes, 4), "p_ahora": round(self.p_ahora, 4),
            "desplazamiento": round(self.desplazamiento, 4),
            "casa": self.casa_rezagada, "momio_dec": round(self.momio_rezagado, 3),
            "ev": round(self.ev, 4), "minutos": self.minutos,
        }


def _consenso_de(filas: list[dict], pesos: dict[str, float],
                 metodo: str = "power") -> dict[tuple, dict[str, float]]:
    """Consenso por (evento_id, mercado, punto) a partir de filas del historial."""
    agrupado: dict[tuple, dict[str, list[tuple[str, float]]]] = {}
    for f in filas:
        clave = (f["evento_id"], f["mercado"], f["punto"])
        agrupado.setdefault(clave, {}).setdefault(f["casa"], []).append(
            (f["seleccion"], float(f["decimal"])))

    salida: dict[tuple, dict[str, float]] = {}
    for clave, por_casa in agrupado.items():
        cots, nombres = [], None
        for casa, sal in por_casa.items():
            sal = sorted(sal)
            ns = [s[0] for s in sal]
            if nombres is None:
                nombres = ns
            elif ns != nombres:
                continue
            c = CotizacionCasa(casa, [s[1] for s in sal], pesos.get(casa, 1.0))
            c.calcular(metodo)
            cots.append(c)
        if not nombres or len(cots) < 3:
            continue
        justas = consenso(cots)
        if justas:
            salida[clave] = dict(zip(nombres, justas))
    return salida


def detectar(eventos: list[Evento], directorio: Path, ahora: datetime,
             pesos: dict[str, float], ventana_min: int = 120,
             umbral_mov: float = 0.025, ev_minimo: float = 0.02,
             metodo: str = "power") -> list[Movimiento]:
    """
    Busca lineas que el mercado ya movio y alguna casa todavia no siguio.

    Logica: se compara el consenso de hace `ventana_min` minutos contra el de
    ahora. Si se movio mas del umbral y ademas hay una casa cuyo precio implica
    todavia la probabilidad vieja, esa casa esta rezagada y su precio vale mas
    de lo que paga.
    """
    filas = cargar(directorio, ahora - timedelta(minutes=ventana_min * 2))
    if not filas:
        return []

    corte = ahora - timedelta(minutes=ventana_min)
    antes = [f for f in filas if datetime.fromisoformat(f["ts"]) <= corte]
    if not antes:
        return []

    # De las filas viejas, quedarse con la foto mas reciente de cada casa
    ultima: dict[tuple, dict] = {}
    for f in antes:
        k = (f["evento_id"], f["mercado"], f["punto"], f["casa"], f["seleccion"])
        if k not in ultima or f["ts"] > ultima[k]["ts"]:
            ultima[k] = f
    cons_antes = _consenso_de(list(ultima.values()), pesos, metodo)

    ahora_filas = []
    ts = ahora.isoformat(timespec="seconds")
    for ev in eventos:
        for mercado, por_casa in ev.libros.items():
            for casa, salidas in por_casa.items():
                for nombre, dec, punto in salidas:
                    ahora_filas.append({
                        "ts": ts, "evento_id": ev.id, "evento": ev.nombre,
                        "mercado": mercado, "punto": "" if punto is None else str(punto),
                        "casa": casa, "seleccion": clave_seleccion(nombre, punto),
                        "decimal": f"{dec:.4f}",
                    })
    cons_ahora = _consenso_de(ahora_filas, pesos, metodo)

    nombres_ev = {ev.id: ev.nombre for ev in eventos}
    movimientos: list[Movimiento] = []

    for clave, ahora_probs in cons_ahora.items():
        antes_probs = cons_antes.get(clave)
        if not antes_probs:
            continue
        ev_id, mercado, punto = clave

        for seleccion, p_ahora in ahora_probs.items():
            p_antes = antes_probs.get(seleccion)
            if p_antes is None or abs(p_ahora - p_antes) < umbral_mov:
                continue

            # Solo interesa el lado hacia el que se movio el mercado
            if p_ahora < p_antes:
                continue

            for f in ahora_filas:
                if (f["evento_id"], f["mercado"], f["punto"], f["seleccion"]) != \
                   (ev_id, mercado, punto, seleccion):
                    continue
                dec = float(f["decimal"])
                ev_valor = p_ahora * dec - 1
                if ev_valor < ev_minimo:
                    continue
                movimientos.append(Movimiento(
                    evento=nombres_ev.get(ev_id, ev_id), mercado=mercado,
                    seleccion=seleccion, p_antes=p_antes, p_ahora=p_ahora,
                    casa_rezagada=f["casa"], momio_rezagado=dec,
                    ev=ev_valor, minutos=ventana_min,
                ))

    movimientos.sort(key=lambda m: m.ev, reverse=True)
    return movimientos
