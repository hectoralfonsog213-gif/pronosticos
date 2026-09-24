"""
Salida del sistema: JSON para consumir desde otro lado, pagina HTML para leer
en el telefono, y registro historico en CSV.

El registro es la pieza que casi todos los sistemas caseros omiten y es la mas
importante: sin el no hay forma de saber si el sistema funciona. Guarda el momio
que se tomo y, al dia siguiente, el momio de cierre. La diferencia entre los dos
es la unica señal temprana de ventaja que existe.
"""
from __future__ import annotations

import csv
import html
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .mercado import Jugada, fmt_am
from .motor import resumen

CAMPOS = [
    "fecha_registro", "inicio", "deporte", "liga", "evento", "mercado", "seleccion",
    "casa", "momio_dec", "momio_am", "p_justa", "p_modelo", "ev", "stake_pct",
    "n_casas", "fuente", "momio_cierre", "clv", "resultado",
]


def escribir_json(r: dict, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({
        "generado": r["ahora"].isoformat(),
        "resumen": resumen(r["jugadas"]),
        "avisos": r["avisos"],
        "eventos": r.get("eventos", 0),
        "jugadas": [j.dict() for j in r["jugadas"]],
        "movimientos": [m.dict() for m in r.get("movimientos", [])],
        "arbitrajes": [a.dict() for a in r.get("arbitrajes", [])],
        "middles": r.get("middles", []),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def registrar(jugadas: list[Jugada], ahora: datetime, ruta: Path) -> None:
    """Añade las jugadas del dia al registro, sin duplicar."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    existentes = set()
    if ruta.exists():
        with open(ruta, encoding="utf-8") as f:
            for fila in csv.DictReader(f):
                existentes.add((fila.get("evento"), fila.get("seleccion"), fila.get("casa")))

    nuevo = not ruta.exists()
    with open(ruta, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        if nuevo:
            w.writeheader()
        for j in jugadas:
            if (j.evento, j.seleccion, j.casa) in existentes:
                continue
            d = j.dict()
            w.writerow({
                "fecha_registro": ahora.isoformat(timespec="seconds"),
                "inicio": d["inicio"], "deporte": d["deporte"], "liga": d["liga"],
                "evento": d["evento"], "mercado": d["mercado"], "seleccion": d["seleccion"],
                "casa": d["casa"], "momio_dec": d["momio_dec"], "momio_am": d["momio_am"],
                "p_justa": d["p_justa"], "p_modelo": d["p_modelo"], "ev": d["ev"],
                "stake_pct": d["stake_pct"], "n_casas": d["n_casas"], "fuente": d["fuente"],
                "momio_cierre": "", "clv": "", "resultado": "",
            })


def estadisticas_registro(ruta: Path) -> dict:
    """Rendimiento acumulado, con el CLV al frente."""
    if not ruta.exists():
        return {}
    filas = list(csv.DictReader(open(ruta, encoding="utf-8")))
    if not filas:
        return {}

    clvs = []
    for f in filas:
        try:
            if f.get("clv"):
                clvs.append(float(f["clv"]))
        except ValueError:
            pass

    resueltas = [f for f in filas if f.get("resultado") in ("ganada", "perdida")]
    ganadas = sum(1 for f in resueltas if f["resultado"] == "ganada")
    unidades = 0.0
    for f in resueltas:
        try:
            s = float(f.get("stake_pct", 0))
            d = float(f.get("momio_dec", 0))
            unidades += s * (d - 1) if f["resultado"] == "ganada" else -s
        except ValueError:
            pass

    return {
        "total": len(filas),
        "resueltas": len(resueltas),
        "aciertos": ganadas / len(resueltas) if resueltas else None,
        "unidades": unidades,
        "clv_promedio": sum(clvs) / len(clvs) if clvs else None,
        "clv_positivo": sum(1 for c in clvs if c > 0),
        "clv_medidas": len(clvs),
    }


# ------------------------------------------------------------------- HTML
_CSS = """
:root{--bg:#0A0E13;--panel:#111821;--panel2:#16202B;--ink:#E8EEF4;--slate:#8898AA;
--rule:#1E2935;--soft:#18222D;--brass:#2BD98A;--brass-bg:rgba(43,217,138,.12);
--brick:#FF5F6D;--amber:#F7B84B;--blue:#4DA8FF;
--mlb:#FF6B57;--nfl:#4DA8FF;--futbol:#2BD98A}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.55 "Space Grotesk",system-ui,sans-serif;
background-image:radial-gradient(1000px 500px at 85% -10%,rgba(43,217,138,.10),transparent 60%),
radial-gradient(800px 400px at -10% 0%,rgba(77,168,255,.08),transparent 60%);
background-repeat:no-repeat}
.w{max-width:980px;margin:0 auto;padding:28px 16px 80px}
.mono,.n,.ev,.det b{font-family:"JetBrains Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}
/* encabezado */
.hero{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;margin-bottom:20px}
.kicker{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--brass);font-weight:600}
h1{font-size:clamp(30px,6vw,44px);font-weight:700;letter-spacing:-.03em;margin:4px 0 2px;line-height:1.05}
.sub{color:var(--slate);font-size:14.5px;margin:0}
.live{display:inline-flex;align-items:center;gap:8px;font-size:13px;color:var(--slate);
border:1px solid var(--rule);background:var(--panel);padding:7px 12px;border-radius:999px}
.live i{width:8px;height:8px;border-radius:50%;background:var(--brass);box-shadow:0 0 0 4px var(--brass-bg)}
.prueba{border:1px solid rgba(247,184,75,.35);background:rgba(247,184,75,.08);color:var(--amber);
border-radius:12px;padding:11px 14px;font-size:13.5px;margin:0 0 20px;line-height:1.5}
.prueba b{color:var(--ink)}
/* tarjetas resumen */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:22px}
.stats>div{background:var(--panel);border:1px solid var(--rule);border-radius:14px;padding:14px 16px}
.n{font-weight:600;font-size:26px;line-height:1.1;display:block;letter-spacing:-.02em}
.l{font-size:12.5px;color:var(--slate);margin-top:4px;display:block}
.pos{color:var(--brass)}.neg{color:var(--brick)}
/* filtros */
.chips{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 16px}
.chip{appearance:none;border:1px solid var(--rule);background:var(--panel);color:var(--ink);
font:inherit;font-size:14px;padding:8px 14px;border-radius:999px;cursor:pointer}
.chip span{color:var(--slate);margin-left:4px}
.chip.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.chip.on span{color:var(--bg);opacity:.6}
/* jugada */
.card{position:relative;background:linear-gradient(180deg,var(--panel2),var(--panel));
border:1px solid var(--rule);border-radius:18px;padding:18px;margin-bottom:14px;overflow:hidden}
.card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--c,var(--brass))}
.card[data-dep=mlb]{--c:var(--mlb)}.card[data-dep=nfl]{--c:var(--nfl)}.card[data-dep=futbol]{--c:var(--futbol)}
.cab{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;font-size:13px;color:var(--slate)}
.dep{display:inline-flex;gap:7px;align-items:center;color:var(--ink);font-weight:600}
.dep em{font-style:normal;color:var(--c);font-weight:600}
.hora{font-family:"JetBrains Mono",monospace}
.partido{font-size:14.5px;color:var(--slate);margin:10px 0 2px}
.pick{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;flex-wrap:wrap}
.apuesta{font-size:clamp(21px,4.6vw,26px);font-weight:700;letter-spacing:-.02em;line-height:1.2}
.aclara{font-size:13.5px;color:var(--slate);margin-top:3px}
.precio{text-align:right}
.momio{font:700 30px/1 "JetBrains Mono",monospace;letter-spacing:-.03em}
.casa{font-size:13px;color:var(--slate);margin-top:5px}
.casa b{color:var(--ink)}
.tag{display:inline-block;font-size:11.5px;font-weight:600;padding:3px 8px;border-radius:999px;
background:var(--brass-bg);color:var(--brass);margin-left:8px;vertical-align:3px;letter-spacing:.02em}
.tag.alt{background:rgba(247,184,75,.12);color:var(--amber)}
/* barra de probabilidad */
.barra{margin:16px 0 6px}
.barra .t{display:flex;justify-content:space-between;font-size:12.5px;color:var(--slate);margin-bottom:6px}
.barra .t b{color:var(--brass);font-family:"JetBrains Mono",monospace}
.pista{position:relative;height:12px;border-radius:999px;background:var(--soft);overflow:visible}
.lleno{height:100%;border-radius:999px;background:linear-gradient(90deg,rgba(43,217,138,.45),var(--brass))}
.marca{position:absolute;top:-5px;bottom:-5px;width:2px;background:var(--amber);border-radius:2px}
.marca::after{content:attr(data-l);position:absolute;top:20px;transform:translateX(-50%);
white-space:nowrap;font-size:11.5px;color:var(--amber);font-family:"JetBrains Mono",monospace}
.leyenda{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--slate);margin-top:24px}
.leyenda i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
/* datos */
.det{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin-top:14px}
.det>div{background:var(--bg);border:1px solid var(--rule);border-radius:12px;padding:10px 12px}
.det b{display:block;font-size:18px;font-weight:600;color:var(--ink)}
.det small{font-size:12px;color:var(--slate)}
.det .ok b{color:var(--brass)}
/* explicacion */
details.por{margin-top:12px;border-top:1px solid var(--rule);padding-top:10px}
details.por summary{cursor:pointer;list-style:none;font-weight:600;font-size:14.5px;color:var(--brass);
display:flex;align-items:center;gap:8px}
details.por summary::-webkit-details-marker{display:none}
details.por summary::before{content:"+";display:inline-grid;place-items:center;width:20px;height:20px;
border-radius:6px;background:var(--brass-bg);font-family:"JetBrains Mono",monospace}
details.por[open] summary::before{content:"–"}
.por p{margin:10px 0 0;font-size:14.5px;line-height:1.65;color:#C9D4DF}
.por p b{color:var(--ink)}
.minimo{margin-top:12px;padding:10px 12px;border-radius:12px;background:var(--brass-bg);
font-size:13.5px;color:var(--ink)}
.minimo b{font-family:"JetBrains Mono",monospace;color:var(--brass)}
.edad{color:var(--amber)}
/* secciones secundarias (lineas, arbitrajes, middles) */
h2{font-size:22px;font-weight:700;margin:38px 0 4px;letter-spacing:-.02em}
.sub2{color:var(--slate);font-size:14px;margin:0 0 14px;max-width:70ch}
.j{background:var(--panel);border:1px solid var(--rule);border-left:4px solid var(--brass);
border-radius:14px;padding:15px 17px;margin-bottom:11px}
.j.mov{border-left-color:var(--blue)}.j.arb{border-left-color:var(--brass)}.j.mid{border-left-color:#A77BFF}
.j .top{display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap;align-items:baseline}
.j .sel{font-weight:600;font-size:17px}
.j .meta{color:var(--slate);font-size:13.5px;margin-top:3px}
.ev{font-weight:600;font-size:20px;color:var(--brass);white-space:nowrap}
.ev.gris{color:var(--slate);font-size:14px;font-weight:400}
.j .det{display:flex;gap:18px;flex-wrap:wrap;margin-top:10px;padding-top:10px;border-top:1px solid var(--rule);
font-size:13.5px;color:var(--slate)}
.j .det b{display:inline;font-size:inherit}
.tag.mv{background:rgba(77,168,255,.14);color:var(--blue)}
.vacio{background:var(--panel);border:1px dashed var(--rule);border-radius:18px;padding:28px;
color:var(--slate);line-height:1.65;text-align:center}
.vacio b{color:var(--ink);display:block;font-size:18px;margin-bottom:6px}
.vacio .big{font-size:40px;display:block;margin-bottom:6px}
table{border-collapse:collapse;width:100%;font-size:13.5px;margin-top:8px}
th,td{padding:8px 9px;text-align:left;border-bottom:1px solid var(--rule)}
th{font-size:12px;color:var(--slate);font-weight:500}
td.m,th.m{text-align:right;font-family:"JetBrains Mono",monospace;font-variant-numeric:tabular-nums}
.guia{margin-top:34px;background:var(--panel);border:1px solid var(--rule);border-radius:18px;padding:6px 18px}
.guia summary{cursor:pointer;font-weight:700;font-size:17px;padding:12px 0}
.guia dl{margin:0 0 14px;font-size:14px;line-height:1.6}
.guia dt{font-weight:600;margin-top:12px}
.guia dd{margin:2px 0 0;color:var(--slate)}
.nota{margin-top:22px;font-size:13px;color:var(--slate);line-height:1.6;max-width:75ch}
.avisos{margin-top:22px;font-size:12px;color:var(--slate);border-top:1px solid var(--rule);padding-top:12px}
.avisos div{margin-bottom:3px;font-family:"JetBrains Mono",monospace}
.demo{background:rgba(247,184,75,.1);border:1px solid var(--amber);color:var(--amber);
border-radius:12px;padding:12px 15px;font-size:13.5px;margin-bottom:22px;line-height:1.5}
@media(max-width:560px){.precio{text-align:left}.card{padding:16px 14px}}
"""

def _estado_vacio(r: dict) -> str:
    """
    Tres situaciones distintas que antes se veian igual, y no son lo mismo.

    Que no haya jugadas porque nada pasó el filtro es informacion. Que no haya
    porque esta corrida no consultó ninguna liga es otra cosa, y confundirlas
    hace pensar que el sistema no encuentra nada cuando en realidad no miró.
    """
    if not r.get("consulto", True):
        return ('<div class="vacio"><span class="big">😴</span><b>Hoy no hay partidos que revisar.</b>'
                'Ninguna liga tenía juegos en las próximas horas, así que no se gastaron '
                'créditos. Mañana a las 8 am se vuelve a revisar.</div>')

    n = r.get("eventos", 0)
    return (f'<div class="vacio"><span class="big">🧐</span><b>Revisamos {n} '
            f'{"partido" if n == 1 else "partidos"} y ninguno pasó el filtro.</b>'
            'Ninguna apuesta de hoy tiene 50% o más de probabilidad y además paga más de lo '
            'justo. Es normal: el sistema prefiere no darte nada antes que inventarte una apuesta.</div>')


# Mexico centro no tiene horario de verano desde 2022: UTC-6 fijo. Se evita
# zoneinfo porque en Windows sin tzdata no existe America/Mexico_City.
MX = timezone(timedelta(hours=-6))
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
DEPORTES = {"mlb": ("⚾", "MLB"), "nfl": ("🏈", "NFL"), "futbol": ("⚽", "Fútbol")}
UNIDAD = {"mlb": "carreras", "nfl": "puntos", "futbol": "goles"}
MODELO = {
    "mlb": "nuestro modelo de béisbol (carreras anotadas y permitidas, más el abridor)",
    "nfl": "nuestro modelo de NFL (Elo con los resultados de la temporada)",
    "futbol": "nuestro modelo de fútbol (Elo de clubes con Poisson)",
}


def _hora_mx(iso: str, ahora: datetime) -> str:
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(MX)
    except ValueError:
        return ""
    hoy = ahora.astimezone(MX).date()
    dia = ("Hoy" if d.date() == hoy else "Mañana" if d.date() == hoy + timedelta(days=1)
           else f"{DIAS[d.weekday()].capitalize()} {d.day}")
    return f"{dia} · {d.strftime('%H:%M')}"


def _fecha_larga(ahora: datetime) -> str:
    d = ahora.astimezone(MX)
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}, {d.strftime('%H:%M')}"


def _pct(p: float) -> str:
    return f"{p * 100:.1f}%"


def _describir(j: Jugada) -> tuple[str, str]:
    """(la apuesta en español llano, una aclaración de qué tiene que pasar)."""
    sel, u = j.seleccion, UNIDAD.get(j.deporte, "puntos")
    partes = sel.rsplit(" ", 1)
    try:
        punto = float(partes[1]) if len(partes) == 2 else None
    except ValueError:
        punto = None
    nombre = partes[0] if punto is not None else sel

    if nombre in ("Over", "Under"):
        linea = f"{abs(punto):g}"
        if nombre == "Over":
            return f"Más de {linea} {u}", f"Entre los dos equipos deben sumar más de {linea} {u}."
        return f"Menos de {linea} {u}", f"Entre los dos equipos deben sumar menos de {linea} {u}."
    if nombre == "Draw":
        return "Empate", "El partido tiene que terminar empatado."
    if punto is not None:
        if punto < 0:
            if punto == int(punto):
                acl = f"Tiene que ganar por más de {abs(punto):g}. Si gana por exactamente {abs(punto):g}, te devuelven tu dinero."
            elif abs(punto * 2) != int(abs(punto * 2)):
                acl = "Hándicap asiático con cuarto de punto: la mitad de la apuesta va a cada línea vecina."
            else:
                acl = f"Tiene que ganar por {int(abs(punto)) + 1} o más."
        else:
            if punto == int(punto):
                acl = f"Gana si {nombre} gana, o si pierde por menos de {punto:g}. Si pierde por exactamente {punto:g}, te devuelven tu dinero."
            elif abs(punto * 2) != int(abs(punto * 2)):
                acl = "Hándicap asiático con cuarto de punto: la mitad de la apuesta va a cada línea vecina."
            else:
                acl = (f"Gana si {nombre} gana o empata." if j.deporte == "futbol" and punto < 1
                       else f"Gana si {nombre} gana, o si pierde por {int(punto)} o menos.")
        return f"{nombre} {punto:+g}", acl
    fin = " (en fútbol, si empatan pierdes)" if j.deporte == "futbol" else ""
    return f"Gana {nombre}", f"Solo tiene que ganar el partido{fin}."


def _explicar(j: Jugada, apuesta: str) -> str:
    """El porqué de la jugada, en palabras."""
    p, imp, dec = j.p_apuesta, 1 / j.momio_dec, j.momio_dec
    ev = p * dec - 1
    otras = max(1, j.n_casas - 1)
    txt = []
    if j.fuente != "modelo":
        txt.append(
            f"Juntamos los momios de las otras <b>{otras} casas</b>, les quitamos su comisión "
            f"y el consenso le da a <b>{html.escape(apuesta)}</b> una probabilidad real de "
            f"<b>{_pct(j.p_justa)}</b>. <b>{html.escape(j.casa)}</b> la paga a "
            f"<b>{fmt_am(j.momio_am)}</b>, que es el precio de algo con solo <b>{_pct(imp)}</b> "
            f"de probabilidad. O sea, la está pagando como si fuera menos probable de lo que es: "
            f"esa diferencia de <b>{(j.p_justa - imp) * 100:.1f} puntos</b> es la ventaja.")
    if j.p_modelo is not None:
        nombre = MODELO.get(j.deporte, "nuestro modelo")
        if j.fuente == "modelo":
            txt.append(
                f"Esta jugada la ve <b>solo {nombre}</b>, que le da <b>{_pct(j.p_modelo)}</b> "
                f"contra el <b>{_pct(imp)}</b> que paga {html.escape(j.casa)}. El resto del "
                f"mercado no la ve así, y por eso es la categoría con más riesgo de estar equivocada.")
        elif j.p_modelo >= j.p_justa:
            txt.append(f"Además, {nombre} está de acuerdo: le da <b>{_pct(j.p_modelo)}</b>. "
                       f"Dos métodos distintos llegan a la misma conclusión.")
        else:
            txt.append(f"Por su lado, {nombre} le da <b>{_pct(j.p_modelo)}</b>, un poco menos. "
                       f"Para ir a lo seguro, todos los números de esta tarjeta usan esa cifra más baja.")
    txt.append(
        f"En números: gana más o menos <b>{round(p * 100)} de cada 100</b> veces. Cuando gana, "
        f"cobras <b>${(dec - 1) * 100:,.0f}</b> de ganancia por cada $100. Repitiendo "
        f"esta misma apuesta muchas veces, lo esperado es ganar <b>${ev * 100:,.2f} por cada "
        f"$100</b> apostados. No es una garantía para hoy: es lo que pasa en promedio.")
    return "".join(f"<p>{t}</p>" for t in txt)


def _tarjetas_jugadas(jugadas, edades: dict | None = None, ahora: datetime | None = None) -> str:
    e = html.escape
    edades = edades or {}
    ahora = ahora or datetime.now(timezone.utc)
    out = []
    for j in jugadas:
        d = j.dict()
        emoji, nombre_dep = DEPORTES.get(j.deporte, ("🎯", j.deporte))
        apuesta, aclara = _describir(j)
        p, imp = j.p_apuesta, 1 / j.momio_dec
        ev = p * j.momio_dec - 1
        edad = edades.get(f"{j.evento}|{j.mercado}|{j.seleccion}|{j.casa}", 0)
        sello = f' · <span class="edad">precio visto hace {edad} min</span>' if edad >= 20 else ""
        etiqueta = {"mercado": "", "modelo": '<span class="tag alt">solo modelo</span>',
                    "ambos": '<span class="tag">mercado + modelo</span>'}[j.fuente]
        banca = j.stake * 1000
        out.append(f"""<article class="card" data-dep="{e(j.deporte)}">
<div class="cab"><span class="dep">{emoji} <em>{e(nombre_dep)}</em> · {e(d["liga"])}</span>
<span class="hora">{e(_hora_mx(j.inicio, ahora))}{sello}</span></div>
<div class="partido">{e(d["evento"])} · {e(d["mercado"])}</div>
<div class="pick"><div><div class="apuesta">{e(apuesta)}{etiqueta}</div>
<div class="aclara">{e(aclara)}</div></div>
<div class="precio"><div class="momio">{e(d["momio_am"])}</div>
<div class="casa">en <b>{e(d["casa"])}</b> · {j.momio_dec:.2f}</div></div></div>
<div class="barra"><div class="t"><span>Probabilidad real de ganar</span><b>{_pct(p)}</b></div>
<div class="pista"><div class="lleno" style="width:{p * 100:.1f}%"></div>
<div class="marca" style="left:{imp * 100:.1f}%" data-l="la casa paga como {_pct(imp)}"></div></div></div>
<div class="leyenda"><span><i style="background:var(--brass)"></i>lo que creemos</span>
<span><i style="background:var(--amber)"></i>lo que la casa cree</span></div>
<div class="det">
<div class="ok"><b>+{ev * 100:.1f}%</b><small>ganancia esperada</small></div>
<div><b>{round(p * 100)} de 100</b><small>veces que gana</small></div>
<div><b>${(j.momio_dec - 1) * 100:,.0f}</b><small>cobras por cada $100</small></div>
<div><b>{d["stake_pct"]:.1f}%</b><small>de tu banca (${banca:,.0f} por cada $1,000)</small></div>
</div>
<details class="por"><summary>¿Por qué esta apuesta?</summary>{_explicar(j, apuesta)}
<p style="font-size:13px;color:var(--slate)">Comparado contra {d["n_casas"]} casas.</p></details>
<div class="minimo">¿La vas a poner en otra casa? Hazlo solo si paga <b>{e(d["momio_minimo_am"])}</b> o mejor.
Si paga peor que <b>{e(d["momio_empate_am"])}</b>, a la larga pierdes dinero.</div>
</article>""")
    return "\n".join(out)


def _seccion_movimientos(movs) -> str:
    if not movs:
        return ""
    e = html.escape
    filas = "".join(
        f"""<div class="j mov"><div class="top"><div>
<div class="sel">{e(m.seleccion)}<span class="tag mv">la línea se movió</span></div>
<div class="meta">{e(m.evento)} · el mercado pasó de {m.p_antes * 100:.1f}% a
{m.p_ahora * 100:.1f}% en {m.minutos} min</div></div>
<div class="ev">+{m.ev * 100:.2f}%</div></div>
<div class="det"><span>rezagada <b>{e(m.casa_rezagada)}</b></span>
<span>momio <b>{m.momio_rezagado:.2f}</b></span>
<span>desplazamiento <b>{m.desplazamiento * 100:+.1f} pts</b></span></div></div>"""
        for m in movs[:10])
    return f'<h2>Líneas rezagadas</h2><p class="sub2">Las casas afiladas ya movieron y estas no. Suele durar minutos.</p>{filas}'


def _seccion_arbitrajes(arbs) -> str:
    if not arbs:
        return ""
    e = html.escape
    filas = ""
    for a in arbs[:8]:
        patas = "".join(
            f'<span>{e(s)} en <b>{e(c)}</b> a <b>{d:.2f}</b> → {r * 100:.0f}%</span>'
            for s, c, d, r in a.patas)
        filas += f"""<div class="j arb"><div class="top"><div>
<div class="sel">{e(a.evento)}<span class="tag">ganancia garantizada</span></div>
<div class="meta">{e(a.mercado)} · {e(a.liga)}</div></div>
<div class="ev">+{a.margen * 100:.2f}%</div></div>
<div class="det">{patas}</div></div>"""
    return f'<h2>Arbitrajes</h2><p class="sub2">Cubres todos los resultados y ganas pase lo que pase. Reparte el dinero en los porcentajes indicados.</p>{filas}'


def _seccion_middles(middles) -> str:
    if not middles:
        return ""
    e = html.escape
    filas = ""
    for m in middles[:8]:
        ev = f'<div class="ev">{m["ev"] * 100:+.1f}%</div>' if m.get("ev") is not None else \
             '<div class="ev gris">sin valuar</div>'
        modelo = (f'<span>el modelo da <b>{m["p_modelo"] * 100:.1f}%</b></span>'
                  if m.get("p_modelo") is not None else "")
        filas += f"""<div class="j mid"><div class="top"><div>
<div class="sel">{e(m["ventana"])}<span class="tag">middle</span></div>
<div class="meta">{e(m["evento"])} · {e(m["mercado"])}</div></div>{ev}</div>
<div class="det">
<span>{e(m["pata_a"]["seleccion"])} en <b>{e(m["pata_a"]["casa"])}</b></span>
<span>{e(m["pata_b"]["seleccion"])} en <b>{e(m["pata_b"]["casa"])}</b></span>
<span>necesitas <b>{m["prob_necesaria"] * 100:.1f}%</b></span>{modelo}
<span>si falla <b>{m["perdida"] * 100:.1f}%</b></span></div></div>"""
    return f'<h2>Middles</h2><p class="sub2">Tomas los dos lados con líneas separadas. Si el resultado cae en medio, ganan las dos.</p>{filas}'


def _seccion_calibracion(ruta_registro: Path) -> str:
    try:
        from .calibracion import analizar
        inf = analizar(ruta_registro)
    except Exception:
        return ""
    if not inf.n_total:
        return ""

    clv = (f'<div><span class="n {"pos" if inf.clv_promedio > 0 else "neg"}">'
           f'{inf.clv_promedio * 100:+.2f}%</span><span class="l">CLV promedio</span></div>'
           if inf.clv_promedio is not None else "")
    rend = (f'<div><span class="n {"pos" if inf.rendimiento > 0 else "neg"}">'
            f'{inf.rendimiento * 100:+.2f}%</span><span class="l">rendimiento</span></div>'
            if inf.rendimiento is not None else "")
    brier = (f'<div><span class="n">{inf.brier_mercado:.3f}</span>'
             f'<span class="l">Brier del mercado</span></div>'
             if inf.brier_mercado is not None else "")
    brier_m = (f'<div><span class="n">{inf.brier_modelo:.3f}</span>'
               f'<span class="l">Brier del modelo</span></div>'
               if inf.brier_modelo is not None else "")

    tabla = ""
    if inf.tramos:
        filas = "".join(
            f'<tr><td>{t.desde:.0%}–{t.hasta:.0%}</td><td class="m">{t.n}</td>'
            f'<td class="m">{t.prevista:.1%}</td><td class="m">{t.observada:.1%}</td>'
            f'<td class="m {"neg" if abs(t.desvio) > 0.1 and t.n >= 20 else ""}">'
            f'{t.desvio:+.1%}</td></tr>' for t in inf.tramos)
        tabla = (f'<table><thead><tr><th>tramo</th><th class="m">n</th>'
                 f'<th class="m">prevista</th><th class="m">observada</th>'
                 f'<th class="m">desvío</th></tr></thead><tbody>{filas}</tbody></table>')

    return (f'<h2>¿Está funcionando?</h2><div class="stats">'
            f'<div><span class="n">{inf.n_total}</span><span class="l">apuestas registradas</span></div>'
            f'{clv}{rend}{brier}{brier_m}</div>{tabla}'
            f'<p class="nota">{html.escape(inf.veredicto)}</p>')


_GUIA = """<details class="guia"><summary>📖 Cómo leer esta página</summary><dl>
<dt>Probabilidad real</dt><dd>Qué tan seguido creemos que pasa. Sale del consenso de
varias casas sin su comisión, y cuando hay modelo propio se usa la cifra más baja de las dos.</dd>
<dt>Lo que la casa cree</dt><dd>La probabilidad que corresponde al momio que paga. Si es
menor que la real, la casa está pagando de más: ahí está el valor.</dd>
<dt>Ganancia esperada</dt><dd>Lo que ganarías en promedio por cada $100 si hicieras esta
misma apuesta muchas veces. Una sola apuesta se gana o se pierde completa.</dd>
<dt>% de tu banca</dt><dd>Cuánto apostar según tu dinero total para apuestas. Es un
cuarto de Kelly con techo de 2%: pequeño a propósito, para aguantar las rachas malas.</dd>
<dt>Momio mínimo</dt><dd>Si tu casa paga menos que eso, ya no es la misma apuesta y no
conviene.</dd>
<dt>Por qué no salen las más seguras primero</dt><dd>Se ordenan por ganancia esperada.
Un favorito a -1200 gana casi siempre, pero paga tan poco que una sola derrota se lleva
lo de doce victorias.</dd></dl></details>"""

_FILTRO_JS = """<script>
document.querySelectorAll('.chip').forEach(function(b){b.addEventListener('click',function(){
document.querySelectorAll('.chip').forEach(function(x){x.classList.toggle('on',x===b)});
var d=b.dataset.dep;document.querySelectorAll('.card').forEach(function(c){
c.style.display=(d==='todos'||c.dataset.dep===d)?'':'none'})})});
</script>"""


def _chips(jugadas) -> str:
    if len({j.deporte for j in jugadas}) < 2:
        return ""
    cuenta: dict[str, int] = {}
    for j in jugadas:
        cuenta[j.deporte] = cuenta.get(j.deporte, 0) + 1
    botones = [f'<button class="chip on" data-dep="todos">Todas<span>{len(jugadas)}</span></button>']
    for dep, (emoji, nombre) in DEPORTES.items():
        if dep in cuenta:
            botones.append(f'<button class="chip" data-dep="{dep}">{emoji} {nombre}'
                           f'<span>{cuenta[dep]}</span></button>')
    return f'<div class="chips">{"".join(botones)}</div>'


def escribir_html(r: dict, ruta: Path, ruta_registro: Path | None = None) -> None:
    jugadas = r["jugadas"]
    e = html.escape

    cuerpo = (_chips(jugadas) + _tarjetas_jugadas(jugadas, r.get("edades", {}), r["ahora"])
              if jugadas else _estado_vacio(r))

    extras = (_seccion_movimientos(r.get("movimientos", []))
              + _seccion_arbitrajes(r.get("arbitrajes", []))
              + _seccion_middles(r.get("middles", [])))
    calib = _seccion_calibracion(ruta_registro) if ruta_registro else ""

    banner = ('<div class="demo">Vista previa con datos de ejemplo. Ninguna de estas '
              'jugadas es real.</div>') if r.get("demo") else ""

    if jugadas:
        probs = [j.p_apuesta for j in jugadas]
        evs = [j.p_apuesta * j.momio_dec - 1 for j in jugadas]
        stats = f"""<div class="stats">
<div><span class="n">{len(jugadas)}</span><span class="l">jugadas de hoy</span></div>
<div><span class="n">{_pct(sum(probs) / len(probs))}</span><span class="l">probabilidad promedio</span></div>
<div><span class="n pos">+{sum(evs) / len(evs) * 100:.1f}%</span><span class="l">ganancia esperada promedio</span></div>
<div><span class="n">{sum(j.stake for j in jugadas) * 100:.1f}%</span><span class="l">de tu banca en total</span></div>
</div>"""
    else:
        stats = ""

    avisos = ""
    if r.get("avisos"):
        avisos = '<div class="avisos">' + "".join(
            f"<div>{e(a)}</div>" for a in r["avisos"]) + "</div>"

    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0A0E13">
<title>Jugadas del día</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🎯</text></svg>">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">
<style>{_CSS}</style></head><body><div class="w">
{banner}
<header class="hero"><div><div class="kicker">Detector de valor</div>
<h1>Jugadas del día</h1>
<p class="sub">Revisado el {e(_fecha_larga(r["ahora"]))} (hora del centro de México)</p></div>
<div class="live"><i></i>MLB · NFL · Fútbol</div></header>
<div class="prueba"><b>Periodo de prueba.</b> Estamos registrando jugadas sin apostar para
medir si el sistema de verdad le gana al mercado. Nada aquí es garantía.</div>
{stats}
{cuerpo}
{extras}
{calib}
{_GUIA}
{avisos}
<p class="nota">Solo se muestran jugadas con al menos 50% de probabilidad y que pagan más
de lo justo, ordenadas por ganancia esperada. El consenso excluye siempre a la casa evaluada.</p>
</div>{_FILTRO_JS}</body></html>""", encoding="utf-8")
