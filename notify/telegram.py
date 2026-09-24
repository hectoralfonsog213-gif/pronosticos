"""Envio de alertas por Telegram."""
from __future__ import annotations

import os

import requests


def enviar(jugadas, resumen, movimientos=None, arbitrajes=None) -> None:
    token = os.environ.get("TELEGRAM_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise RuntimeError("Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID.")

    bloques = []

    for a in (arbitrajes or [])[:5]:
        patas = "\n".join(f"       {s} en {c} a {d:.2f} ({r * 100:.0f}% del dinero)"
                          for s, c, d, r in a.patas)
        bloques.append(f"ARBITRAJE `{a.margen * 100:+.2f}%` garantizado\n"
                       f"    {a.evento}\n{patas}")

    for m in (movimientos or [])[:6]:
        bloques.append(
            f"LINEA REZAGADA `{m.ev * 100:+.2f}%`\n"
            f"    *{m.seleccion}* a {m.momio_rezagado:.2f} en {m.casa_rezagada}\n"
            f"    {m.evento} — el mercado se movió {m.desplazamiento * 100:+.1f} pts "
            f"en {m.minutos} min")

    for j in (jugadas or [])[:12]:
        d = j.dict()
        marca = "  (solo modelo)" if j.fuente == "modelo" else ""
        bloques.append(f"`{d['ev'] * 100:+5.2f}%` *{d['seleccion']}* {d['momio_am']} "
                       f"en {d['casa']}\n    {d['evento']} — riesgo {d['stake_pct']:.2f}%{marca}")

    if not bloques:
        return

    encabezado = (f"*{len(jugadas or [])} jugada(s) nueva(s)*"
                  if jugadas else "*Alertas de mercado*")
    texto = encabezado + "\n\n" + "\n\n".join(bloques)

    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": texto[:4000], "parse_mode": "Markdown",
              "disable_web_page_preview": True},
        timeout=20,
    )
    r.raise_for_status()
