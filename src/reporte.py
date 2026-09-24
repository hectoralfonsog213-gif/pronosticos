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
from datetime import datetime
from pathlib import Path

from .mercado import Jugada
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
:root{--bg:#E9ECF0;--panel:#F5F7F9;--ink:#16202B;--slate:#5A6D80;--rule:#C2CCD6;
--soft:#D8E0E7;--brass:#7E5F12;--brass-bg:#EFE6CE;--brick:#93383C}
@media(prefers-color-scheme:dark){:root{--bg:#111820;--panel:#18212B;--ink:#DCE4EC;
--slate:#8B9CAD;--rule:#2B3946;--soft:#222E3A;--brass:#D2A945;--brass-bg:#2A2617;--brick:#D98287}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 Archivo,system-ui,sans-serif}
.w{max-width:940px;margin:0 auto;padding:32px 18px 70px}
h1{font-size:30px;font-weight:700;letter-spacing:-.02em;margin:0 0 6px}
.sub{color:var(--slate);font-size:14.5px;margin:0 0 26px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:14px;
background:var(--panel);border:1px solid var(--rule);border-radius:5px;padding:18px;margin-bottom:24px}
.n{font:600 25px/1.1 "IBM Plex Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums;
display:block;letter-spacing:-.02em}
.l{font-size:12.5px;color:var(--slate);margin-top:4px}
.pos{color:var(--brass)}.neg{color:var(--brick)}
.j{background:var(--panel);border:1px solid var(--rule);border-left:3px solid var(--brass);
border-radius:5px;padding:15px 17px;margin-bottom:11px}
.j.modelo{border-left-color:var(--slate)}
.top{display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap;align-items:baseline}
.sel{font-weight:600;font-size:17px}
.meta{color:var(--slate);font-size:13.5px;margin-top:3px}
.ev{font:600 21px/1 "IBM Plex Mono",ui-monospace,monospace;color:var(--brass);white-space:nowrap}
.det{display:flex;gap:20px;flex-wrap:wrap;margin-top:11px;padding-top:11px;
border-top:1px solid var(--soft);font-size:13.5px;color:var(--slate)}
.det b{font-family:"IBM Plex Mono",ui-monospace,monospace;color:var(--ink);font-weight:600}
.tag{display:inline-block;font-size:11.5px;padding:2px 7px;border-radius:3px;
background:var(--brass-bg);color:var(--brass);margin-left:7px;vertical-align:1px}
.edad{color:var(--slate);font-style:italic}
.vacio b{color:var(--ink);font-weight:600}
.vacio{background:var(--panel);border:1px solid var(--rule);border-radius:5px;
padding:26px;text-align:left;color:var(--slate);line-height:1.6}
.avisos{margin-top:28px;font-size:13px;color:var(--slate);border-top:1px solid var(--rule);padding-top:14px}
.avisos div{margin-bottom:4px;font-family:"IBM Plex Mono",ui-monospace,monospace}
.demo{background:var(--brass-bg);border:1px solid var(--brass);color:var(--brass);
border-radius:5px;padding:12px 15px;font-size:13.5px;margin-bottom:22px;line-height:1.5}
.minimo{margin-top:10px;padding-top:9px;border-top:1px dashed var(--rule);
font-size:13px;color:var(--slate)}
.minimo b{font-family:"IBM Plex Mono",ui-monospace,monospace;color:var(--brass)}
.nota{margin-top:26px;font-size:13.5px;color:var(--slate);line-height:1.6;max-width:70ch}
h2{font-size:20px;font-weight:600;margin:34px 0 4px;letter-spacing:-.015em}
.sub2{color:var(--slate);font-size:13.5px;margin:0 0 14px;max-width:70ch}
.j.mov{border-left-color:#2F6F8F}.j.arb{border-left-color:#2E7D52}.j.mid{border-left-color:#6B4E9B}
.tag.alt{background:transparent;border:1px solid var(--rule);color:var(--slate)}
.tag.mv{background:#DCE8EF;color:#2F6F8F}
.ev.gris{color:var(--slate);font-size:14px;font-weight:400}
table{border-collapse:collapse;width:100%;font-size:13.5px;margin-top:8px}
th,td{padding:7px 9px;text-align:left;border-bottom:1px solid var(--soft)}
th{font-size:12px;color:var(--slate);font-weight:500}
td.m,th.m{text-align:right;font-family:"IBM Plex Mono",ui-monospace,monospace;
font-variant-numeric:tabular-nums}
@media(prefers-color-scheme:dark){.tag.mv{background:#1D3542;color:#7FB3CE}}
"""


def _estado_vacio(r: dict) -> str:
    """
    Tres situaciones distintas que antes se veian igual, y no son lo mismo.

    Que no haya jugadas porque nada pasó el filtro es informacion. Que no haya
    porque esta corrida no consultó ninguna liga es otra cosa, y confundirlas
    hace pensar que el sistema no encuentra nada cuando en realidad no miró.
    """
    if not r.get("consulto", True):
        return ('<div class="vacio"><b>Nada que revisar en este momento.</b><br>'
                'Ninguna liga tenía partidos dentro de la ventana de consulta, o ya '
                'se habían revisado hace poco. El sistema no gastó créditos y volverá '
                'a mirar en la próxima corrida. Si quieres una revisión ahora mismo, '
                'corre el flujo a mano con la opción de forzar.</div>')

    n = r.get("eventos", 0)
    return (f'<div class="vacio"><b>Sin jugadas: revisamos {n} '
            f'{"evento" if n == 1 else "eventos"} y ninguno pasó el filtro.</b><br>'
            'Es lo normal y es buena señal. El sistema prefiere no darte nada antes '
            'que inventarte una apuesta para justificar la corrida.</div>')


def _tarjetas_jugadas(jugadas, edades: dict | None = None) -> str:
    e = html.escape
    edades = edades or {}
    out = []
    for j in jugadas:
        d = j.dict()
        edad = edades.get(f"{j.evento}|{j.mercado}|{j.seleccion}|{j.casa}", 0)
        sello = (f'<span class="edad">precio visto hace {edad} min</span>'
                 if edad >= 20 else "")
        etiqueta = {"mercado": "", "modelo": '<span class="tag alt">solo modelo</span>',
                    "ambos": '<span class="tag">modelo + mercado</span>'}[j.fuente]
        p_mod = f'<span>modelo <b>{d["p_modelo"] * 100:.1f}%</b></span>' if d["p_modelo"] else ""
        out.append(f"""<div class="j{' modelo' if j.fuente == 'modelo' else ''}">
<div class="top"><div>
<div class="sel">{e(d["seleccion"])}{etiqueta}</div>
<div class="meta">{e(d["evento"])} · {e(d["mercado"])} · {e(d["liga"])}</div>
</div><div class="ev">+{d["ev"] * 100:.2f}%</div></div>
<div class="det"><span>casa <b>{e(d["casa"])}</b></span>
<span>momio <b>{e(d["momio_am"])}</b></span>
<span>justa <b>{d["p_justa"] * 100:.1f}%</b></span>{p_mod}
<span>riesgo <b>{d["stake_pct"]:.2f}%</b></span>
<span>{d["n_casas"]} casas</span>{sello}</div>
<div class="minimo">En tu casa, apuesta solo si paga <b>{e(d["momio_minimo_am"])}</b> o mejor.
Debajo de {e(d["momio_empate_am"])} pierdes dinero.</div></div>""")
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


def escribir_html(r: dict, ruta: Path, ruta_registro: Path | None = None) -> None:
    jugadas = r["jugadas"]
    res = resumen(jugadas)
    fecha = r["ahora"].strftime("%d/%m/%Y %H:%M UTC")
    e = html.escape

    cuerpo = (_tarjetas_jugadas(jugadas, r.get("edades", {})) if jugadas
              else _estado_vacio(r))

    extras = (_seccion_movimientos(r.get("movimientos", []))
              + _seccion_arbitrajes(r.get("arbitrajes", []))
              + _seccion_middles(r.get("middles", [])))
    calib = _seccion_calibracion(ruta_registro) if ruta_registro else ""

    banner = ('<div class="demo">Vista previa con datos de ejemplo. Ninguna de estas '
              'jugadas es real: sirven para mostrar cómo se verá el tablero cuando '
              'conectes tu llave de API.</div>') if r.get("demo") else ""
    refresco = "" if r.get("demo") else '<meta http-equiv="refresh" content="300">'

    avisos = ""
    if r.get("avisos"):
        avisos = '<div class="avisos">' + "".join(
            f"<div>{e(a)}</div>" for a in r["avisos"]) + "</div>"

    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{refresco}
<title>Jugadas del día</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;700&family=IBM+Plex+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>{_CSS}</style></head><body><div class="w">
{banner}
<h1>Jugadas del día</h1>
<p class="sub">Actualizado {fecha}. Ordenadas por valor esperado, no por probabilidad.</p>
<div class="stats">
<div><span class="n">{res["n"]}</span><span class="l">jugadas sobre el umbral</span></div>
<div><span class="n pos">+{res["ev_promedio"] * 100:.2f}%</span><span class="l">valor esperado promedio</span></div>
<div><span class="n">{res["exposicion"] * 100:.2f}%</span><span class="l">exposición de banca</span></div>
<div><span class="n">{len(r.get("movimientos", []))}</span><span class="l">líneas rezagadas</span></div>
<div><span class="n">{len(r.get("arbitrajes", []))}</span><span class="l">arbitrajes</span></div>
<div><span class="n">{len(r.get("middles", []))}</span><span class="l">middles</span></div>
</div>
{cuerpo}
{extras}
{calib}
{avisos}
<p class="nota">El valor esperado se calcula contra el consenso de las demás casas,
excluyendo siempre a la casa evaluada. Una jugada marcada "solo modelo" no tiene
respaldo del mercado: es tu pronóstico contra el de todos los demás, y ahí el riesgo
de estar equivocado es mucho más alto. Los arbitrajes son ganancia matemática y no
dependen de ningún pronóstico. Anota el momio que tomaste: el CLV es lo único que te
dice pronto si esto sirve.</p>
</div></body></html>""", encoding="utf-8")
