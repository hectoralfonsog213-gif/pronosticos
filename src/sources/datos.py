"""
Fuentes de estadisticas. Todas gratuitas y sin llave:

  MLB      statsapi.mlb.com        oficial de MLB, sin autenticacion
  NFL      site.api.espn.com       marcadores publicos de ESPN
  Futbol   api.clubelo.com         calificaciones Elo de clubes, CSV plano

Ninguna de estas es un producto con contrato de servicio: son endpoints
publicos que pueden cambiar de forma sin aviso. Por eso cada funcion falla
con un mensaje claro en vez de devolver datos a medias, y el orquestador
sigue con los demas deportes cuando una fuente se cae.
"""
from __future__ import annotations

import csv
import io
from datetime import date

import requests

TIMEOUT = 25
# ESPN responde 403 a cualquier User-Agent que no parezca navegador (incluido
# "compatible; pronosticos/1.0"). Con 403, nfl_resultados se tragaba el error y
# el Elo de la NFL quedaba vacio sin avisar.
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _json(url: str, params: dict | None = None) -> dict:
    r = requests.get(url, params=params or {}, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# ------------------------------------------------------------------- MLB
MLB_BASE = "https://statsapi.mlb.com/api/v1"


def mlb_equipos(temporada: int) -> dict[str, dict]:
    """
    Carreras anotadas y permitidas por juego, por equipo.

    Devuelve {nombre_equipo: {"cf": float, "cc": float, "juegos": int}}.
    """
    standings = _json(
        f"{MLB_BASE}/standings",
        # Sin hydrate=team el nombre viene corto ("Red Sox") y no empata con las
        # casas ("Boston Red Sox"); el modelo MLB se quedaba sin un solo juego.
        {"leagueId": "103,104", "season": temporada, "standingsTypes": "regularSeason",
         "hydrate": "team"},
    )
    out: dict[str, dict] = {}
    for registro in standings.get("records", []) or []:
        for eq in registro.get("teamRecords", []) or []:
            nombre = (eq.get("team") or {}).get("name")
            if not nombre:
                continue
            g = int(eq.get("wins", 0)) + int(eq.get("losses", 0))
            cf = float(eq.get("runsScored", 0) or 0)
            cc = float(eq.get("runsAllowed", 0) or 0)
            if g <= 0:
                continue
            out[nombre] = {"cf": cf / g, "cc": cc / g, "juegos": g}
    if not out:
        raise RuntimeError("statsapi.mlb.com no devolvio standings usables.")
    return out


def mlb_juegos(dia: date) -> list[dict]:
    """Juegos del dia con abridores probables y su ERA de la temporada."""
    data = _json(
        f"{MLB_BASE}/schedule",
        {
            "sportId": 1,
            "date": dia.isoformat(),
            "hydrate": "probablePitcher(stats(type=season)),team",
        },
    )
    juegos = []
    for fecha in data.get("dates", []) or []:
        for j in fecha.get("games", []) or []:
            eq = j.get("teams", {})
            local, visita = eq.get("home", {}), eq.get("away", {})

            def abridor(lado: dict) -> dict:
                p = lado.get("probablePitcher") or {}
                era = None
                for grupo in p.get("stats", []) or []:
                    splits = grupo.get("splits") or []
                    if splits:
                        v = (splits[0].get("stat") or {}).get("era")
                        if v not in (None, "-", ".---"):
                            try:
                                era = float(v)
                            except ValueError:
                                pass
                return {"nombre": p.get("fullName", "por anunciar"), "era": era}

            juegos.append({
                "id": j.get("gamePk"),
                "inicio": j.get("gameDate", ""),
                "local": (local.get("team") or {}).get("name", ""),
                "visita": (visita.get("team") or {}).get("name", ""),
                "abridor_local": abridor(local),
                "abridor_visita": abridor(visita),
            })
    return juegos


# ------------------------------------------------------------------- NFL
ESPN_NFL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"


def nfl_resultados(temporada: int, semanas: range | None = None) -> list[dict]:
    """
    Partidos terminados de una temporada, para alimentar el Elo.
    seasontype=2 es temporada regular; 3 es postemporada.
    """
    salida = []
    for semana in (semanas or range(1, 19)):
        try:
            data = _json(f"{ESPN_NFL}/scoreboard",
                         {"dates": temporada, "seasontype": 2, "week": semana})
        except requests.RequestException:
            continue
        for ev in data.get("events", []) or []:
            comp = (ev.get("competitions") or [{}])[0]
            estado = ((comp.get("status") or {}).get("type") or {}).get("completed")
            if not estado:
                continue
            equipos = comp.get("competitors") or []
            local = next((c for c in equipos if c.get("homeAway") == "home"), None)
            visita = next((c for c in equipos if c.get("homeAway") == "away"), None)
            if not local or not visita:
                continue
            try:
                salida.append({
                    "semana": semana,
                    "fecha": ev.get("date", ""),
                    "local": (local.get("team") or {}).get("displayName", ""),
                    "visita": (visita.get("team") or {}).get("displayName", ""),
                    "pts_local": int(local.get("score", 0)),
                    "pts_visita": int(visita.get("score", 0)),
                })
            except (TypeError, ValueError):
                continue
    return salida


def nfl_proximos() -> list[dict]:
    # ESPN ya no acepta rangos de fechas ("Failed to get events endpoint");
    # sin parametros devuelve la semana en curso.
    data = _json(f"{ESPN_NFL}/scoreboard")
    juegos = []
    for ev in data.get("events", []) or []:
        comp = (ev.get("competitions") or [{}])[0]
        equipos = comp.get("competitors") or []
        local = next((c for c in equipos if c.get("homeAway") == "home"), None)
        visita = next((c for c in equipos if c.get("homeAway") == "away"), None)
        if local and visita:
            juegos.append({
                "inicio": ev.get("date", ""),
                "local": (local.get("team") or {}).get("displayName", ""),
                "visita": (visita.get("team") or {}).get("displayName", ""),
            })
    return juegos


# ---------------------------------------------------------------- FUTBOL
CLUBELO = "http://api.clubelo.com"


def futbol_elo(dia: date | None = None) -> dict[str, float]:
    """
    Elo de todos los clubes del mundo en una fecha. CSV plano, sin llave.
    Columnas: Rank,Club,Country,Level,Elo,From,To
    """
    dia = dia or date.today()
    r = requests.get(f"{CLUBELO}/{dia.isoformat()}", headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    elos: dict[str, float] = {}
    for fila in csv.DictReader(io.StringIO(r.text)):
        club, valor = fila.get("Club"), fila.get("Elo")
        if club and valor:
            try:
                elos[club] = float(valor)
            except ValueError:
                continue
    if not elos:
        raise RuntimeError("api.clubelo.com no devolvio calificaciones.")
    return elos


# --------------------------------------------------- emparejar nombres
def emparejar(nombre: str, catalogo: dict[str, float] | dict[str, dict]) -> str | None:
    """
    Los nombres de equipo nunca coinciden entre dos fuentes. La casa dice
    "Man City", ClubElo dice "Man City" pero tambien existe "Manchester City".
    Esto empareja por similitud y devuelve None cuando no esta seguro, que es
    mejor que emparejar mal y apostarle al equipo equivocado.
    """
    from difflib import SequenceMatcher

    def limpia(s: str) -> str:
        s = s.lower()
        for basura in (" fc", " cf", " afc", "fc ", "cf ", " sc", " ac", "."):
            s = s.replace(basura, " ")
        return " ".join(s.split())

    objetivo = limpia(nombre)
    mejor, puntaje = None, 0.0
    for clave in catalogo:
        r = SequenceMatcher(None, objetivo, limpia(clave)).ratio()
        if r > puntaje:
            mejor, puntaje = clave, r
    return mejor if puntaje >= 0.82 else None
