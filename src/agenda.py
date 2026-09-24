"""
Agenda: decide que ligas consultar en esta corrida, sin quemar la cuota.

El problema: una linea colgada se corrige en minutos, asi que conviene revisar
seguido. Pero cada consulta de momios cuesta creditos. Revisar 5 ligas cada 15
minutos serian mas de 14,000 creditos al mes, cuando el plan gratis da 500.

Dos mecanismos lo resuelven:

1. El calendario de eventos es GRATIS en la API. Primero se pregunta que hay y
   a que hora; solo se piden momios de las ligas con partidos cerca. Una liga
   sin juegos hoy no cuesta nada. Y se revisa mas seguido conforme se acerca el
   partido, que es cuando se mueven las lineas.

2. Presupuesto mensual con racionamiento. El sistema lleva la cuenta de lo que
   gasta, calcula cuanto le toca por dia del mes, y si va pasado atiende solo
   los partidos mas proximos. Asi nunca se queda sin creditos a media quincena,
   que es la forma tipica en que estos sistemas se mueren.

Con esto el mismo codigo sirve en plan gratis (500 creditos) y en plan de paga
(100,000): cambias un numero en el config y el sistema se reacomoda solo.
"""
from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass
class Ventana:
    """Cada cuanto revisar, segun que tan cerca esta el partido mas proximo."""

    horas_antes: float
    minutos_entre_consultas: int


# De cerca a lejos. La ultima hora antes del partido es la mas rentable: ahi
# entran las alineaciones y ahi es donde las casas blandas se quedan atras.
ESCALA_DEFECTO = [
    Ventana(1.5, 15),
    Ventana(6.0, 60),
    Ventana(24.0, 240),
    Ventana(72.0, 720),
]


def _parse(iso) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError, TypeError):
        return None


def proximidad(eventos: list[dict], ahora: datetime) -> float | None:
    """Horas que faltan para el partido mas proximo que todavia no empieza."""
    faltas = []
    for e in eventos:
        inicio = _parse(e.get("commence_time", ""))
        if inicio and inicio > ahora:
            faltas.append((inicio - ahora).total_seconds() / 3600)
    return min(faltas) if faltas else None


def intervalo(horas: float | None, escala: list[Ventana] | None = None) -> int | None:
    """Minutos que deben pasar entre consultas. None = no consultar."""
    if horas is None:
        return None
    for v in (escala or ESCALA_DEFECTO):
        if horas <= v.horas_antes:
            return v.minutos_entre_consultas
    return None


# ------------------------------------------------------------- presupuesto
class Presupuesto:
    """Lleva la cuenta del gasto del mes y raciona lo que queda."""

    def __init__(self, ruta: Path, mensual: int = 500):
        self.ruta = Path(ruta)
        self.mensual = int(mensual)
        self.estado = self._cargar()

    def _cargar(self) -> dict:
        try:
            d = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        mes = datetime.now(timezone.utc).strftime("%Y-%m")
        if d.get("mes") != mes:
            d = {"mes": mes, "gastado": 0, "ultimas": {}, "por_dia": {}}
        d.setdefault("ultimas", {})
        d.setdefault("por_dia", {})
        d.setdefault("gastado", 0)
        return d

    def guardar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ruta.write_text(json.dumps(self.estado, indent=2, ensure_ascii=False),
                             encoding="utf-8")

    @property
    def gastado(self) -> int:
        return int(self.estado.get("gastado", 0))

    @property
    def restante(self) -> int:
        return max(0, self.mensual - self.gastado)

    def permitido_hoy(self, ahora: datetime) -> int:
        """Lo que queda repartido entre los dias que faltan, con 30% de holgura."""
        dias_mes = calendar.monthrange(ahora.year, ahora.month)[1]
        faltan = max(1, dias_mes - ahora.day + 1)
        return max(1, int(self.restante / faltan * 1.3))

    def gastado_hoy(self, ahora: datetime) -> int:
        return int(self.estado["por_dia"].get(ahora.strftime("%Y-%m-%d"), 0))

    def cobrar(self, creditos: int, ahora: datetime) -> None:
        self.estado["gastado"] = self.gastado + creditos
        hoy = ahora.strftime("%Y-%m-%d")
        self.estado["por_dia"][hoy] = self.gastado_hoy(ahora) + creditos

    def marcar(self, ligas: list[str], ahora: datetime) -> None:
        for liga in ligas:
            self.estado["ultimas"][liga] = ahora.isoformat(timespec="seconds")

    def ultima(self, liga: str) -> datetime | None:
        return _parse(self.estado["ultimas"].get(liga, ""))

    def sincronizar(self, restantes_reales: int | None) -> None:
        """
        La API informa cuantos creditos quedan de verdad. Cuando lo dice, se
        confia en ella por encima del conteo interno: es la unica fuente que no
        se desincroniza si una corrida falla a medias.
        """
        if restantes_reales is not None:
            self.estado["gastado"] = max(0, self.mensual - int(restantes_reales))


# ----------------------------------------------------------------- decidir
def decidir(cliente, cfg: dict, presupuesto: Presupuesto,
            ahora: datetime | None = None,
            forzar: bool = False) -> tuple[dict[str, list[str]], list[str]]:
    """
    Devuelve ({deporte: [ligas a consultar]}, avisos).

    Con `forzar` se ignoran los intervalos y se revisa todo lo que tenga partido
    en ventana. Es lo que hace el boton de "correr ahora": cuando alguien lo
    aprieta quiere una respuesta de este momento, no un "ya revisé hace rato".
    El presupuesto se respeta igual, porque esa proteccion no se salta nunca.

    Las ligas se ordenan por cercania del partido y se aceptan mientras alcance
    el presupuesto del dia. Si sobra poco, se atiende primero lo que esta por
    empezar, que es donde estan las oportunidades reales.
    """
    ahora = ahora or datetime.now(timezone.utc)
    escala = [Ventana(**v) for v in cfg.get("escala", [])] or ESCALA_DEFECTO
    regiones = len(cfg.get("regiones", ["us"]))
    avisos: list[str] = []

    candidatas: list[tuple[float, str, str, int]] = []
    for deporte, conf in cfg.get("deportes", {}).items():
        if not conf.get("activo", True):
            continue
        costo = len(conf.get("mercados", ["h2h"])) * regiones
        for liga in conf.get("ligas", []):
            horas = proximidad(cliente.eventos_programados(liga), ahora)
            cada = intervalo(horas, escala)
            if cada is None:
                continue
            if not forzar:
                ultima = presupuesto.ultima(liga)
                if ultima and (ahora - ultima) < timedelta(minutes=cada):
                    continue
            candidatas.append((horas, deporte, liga, costo))

    if not candidatas:
        avisos.append("ningún partido en ventana: esta corrida no gastó créditos")
        return {}, avisos

    # "cercania": primero el partido que esta por empezar (revision continua).
    # "config": en el orden en que aparecen en config.yaml, para que con una sola
    # revision al dia el presupuesto se gaste primero en las ligas que importan.
    if cfg.get("prioridad", "cercania") != "config":
        candidatas.sort(key=lambda c: c[0])

    disponible = min(
        presupuesto.permitido_hoy(ahora) - presupuesto.gastado_hoy(ahora),
        presupuesto.restante,
    )

    plan: dict[str, list[str]] = {}
    gasto = pospuestas = 0
    for _horas, deporte, liga, costo in candidatas:
        if gasto + costo > disponible:
            pospuestas += 1
            continue
        plan.setdefault(deporte, []).append(liga)
        gasto += costo

    if pospuestas:
        avisos.append(f"{pospuestas} liga(s) pospuestas por presupuesto "
                      f"({presupuesto.restante} créditos para el resto del mes)")
    if presupuesto.restante < presupuesto.mensual * 0.15:
        avisos.append("quedan menos del 15% de los créditos del mes")

    return plan, avisos


def costo_estimado(plan: dict[str, list[str]], cfg: dict) -> int:
    regiones = len(cfg.get("regiones", ["us"]))
    return sum(
        len(ligas) * len(cfg["deportes"][deporte].get("mercados", ["h2h"])) * regiones
        for deporte, ligas in plan.items()
    )
