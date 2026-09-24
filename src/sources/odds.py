"""
Extraccion de momios. Implementado contra The Odds API v4, que es la mas
documentada y tiene plan gratis (500 creditos al mes).

Cuidado con la cuota: un credito NO es una llamada. The Odds API cobra
mercados x regiones por peticion, asi que pedir 3 mercados en 2 regiones
cuesta 6 creditos. Con 500 al mes eso son unas 80 llamadas. El modulo lleva
la cuenta y avisa antes de que te quedes sin nada a medio mes.

Limitacion importante del plan gratis: no incluye Pinnacle ni Betfair, que son
las referencias afiladas. Sin una casa afilada en la muestra, el consenso es
mas ruidoso y el detector de valor pierde bastante filo.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "https://api.the-odds-api.com/v4"


def _cargar_env() -> None:
    """Lee .env de la raiz para correr local. En GitHub la llave llega como secreto."""
    ruta = Path(__file__).resolve().parents[2] / ".env"
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8-sig").splitlines():
        clave, sep, valor = linea.partition("=")
        if sep and not clave.strip().startswith("#"):
            os.environ.setdefault(clave.strip(), valor.strip().strip('"\''))


_cargar_env()


@dataclass
class Evento:
    id: str
    deporte: str
    liga: str
    inicio: str
    local: str
    visita: str
    # {mercado: {casa: [(nombre_seleccion, decimal, punto_o_None), ...]}}
    libros: dict[str, dict[str, list[tuple[str, float, float | None]]]] = field(default_factory=dict)

    @property
    def nombre(self) -> str:
        return f"{self.local} vs {self.visita}"


class ClienteOdds:
    def __init__(self, api_key: str | None = None, timeout: int = 20):
        self.api_key = api_key or os.environ.get("ODDS_API_KEY", "")
        if not self.api_key:
            raise RuntimeError(
                "Falta ODDS_API_KEY. Ponla como secreto del repositorio en GitHub "
                "(Settings > Secrets and variables > Actions) o exportala en tu terminal."
            )
        self.timeout = timeout
        self.restantes: int | None = None
        self.usados: int | None = None
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "pronosticos/1.0"

    def _get(self, ruta: str, params: dict) -> list | dict:
        params = {**params, "apiKey": self.api_key}
        for intento in range(3):
            try:
                r = self.s.get(f"{BASE}{ruta}", params=params, timeout=self.timeout)
            except requests.RequestException as e:
                if intento == 2:
                    raise
                time.sleep(2 ** intento)
                continue

            if r.status_code == 401:
                raise RuntimeError("La API rechazo la llave. Revisa ODDS_API_KEY.")
            if r.status_code == 429:
                raise RuntimeError("Cuota agotada en The Odds API. Espera al proximo ciclo o sube de plan.")
            if r.status_code >= 500:
                if intento == 2:
                    r.raise_for_status()
                time.sleep(2 ** intento)
                continue
            r.raise_for_status()

            if "x-requests-remaining" in r.headers:
                self.restantes = int(float(r.headers["x-requests-remaining"]))
                self.usados = int(float(r.headers.get("x-requests-used", 0)))
            return r.json()
        raise RuntimeError(f"No se pudo consultar {ruta}")

    def deportes(self) -> list[dict]:
        """Gratis, no consume cuota. Util para ver las claves de liga disponibles."""
        return self._get("/sports/", {})

    def eventos_programados(self, liga: str) -> list[dict]:
        """
        Calendario de una liga SIN momios. Tambien es gratis y no descuenta
        creditos, y es la pieza que permite consultar seguido sin quemar la
        cuota: primero se pregunta que hay, y solo se piden momios de las ligas
        que de verdad tienen partidos cerca.
        """
        try:
            return self._get(f"/sports/{liga}/events/", {}) or []
        except Exception:
            return []

    def momios(self, liga: str, mercados: list[str], regiones: list[str],
               formato: str = "decimal", hasta: datetime | None = None) -> list[Evento]:
        """`hasta` deja fuera los partidos que empiezan despues de esa hora."""
        costo = len(mercados) * len(regiones)
        if self.restantes is not None and self.restantes < costo:
            raise RuntimeError(f"Quedan {self.restantes} creditos y esta llamada cuesta {costo}.")

        params = {
            "regions": ",".join(regiones),
            "markets": ",".join(mercados),
            "oddsFormat": formato,
            "dateFormat": "iso",
        }
        if hasta is not None:
            params["commenceTimeTo"] = hasta.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        crudo = self._get(f"/sports/{liga}/odds/", params)

        # /odds/ tambien devuelve partidos en juego, con momios en vivo. Compararlos
        # contra momios previos da arbitrajes y "valor" falsos (Red Sox a 1.05 vs 34).
        ahora = datetime.now(timezone.utc)
        eventos = []
        for ev in crudo or []:
            try:
                inicio = datetime.fromisoformat(ev.get("commence_time", "").replace("Z", "+00:00"))
            except ValueError:
                continue
            if inicio <= ahora:
                continue
            e = Evento(
                id=ev.get("id", ""),
                deporte=_deporte_de(liga),
                liga=ev.get("sport_title", liga),
                inicio=ev.get("commence_time", ""),
                local=ev.get("home_team", ""),
                visita=ev.get("away_team", ""),
            )
            for casa in ev.get("bookmakers", []) or []:
                titulo = casa.get("title") or casa.get("key", "?")
                for mk in casa.get("markets", []) or []:
                    clave = mk.get("key")
                    salidas = []
                    for o in mk.get("outcomes", []) or []:
                        precio = o.get("price")
                        if not precio or precio <= 1:
                            continue
                        salidas.append((o.get("name", ""), float(precio), o.get("point")))
                    if len(salidas) >= 2:
                        e.libros.setdefault(clave, {})[titulo] = salidas
            if e.libros:
                eventos.append(e)
        return eventos


def _deporte_de(liga: str) -> str:
    if liga.startswith("soccer"):
        return "futbol"
    if liga.startswith("americanfootball"):
        return "nfl"
    if liga.startswith("baseball"):
        return "mlb"
    return "otro"
