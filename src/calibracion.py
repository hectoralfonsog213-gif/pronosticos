"""
Calibracion: mide si las probabilidades que produce el sistema son honestas.

Un modelo puede acertar mucho y aun asi estar mal calibrado. Si dice 70% en
cien apuestas y ganan 55, no es mala suerte: es que el modelo miente y Kelly va
a mandar apuestas mas grandes de lo que deberia, que es como se revienta una
banca incluso teniendo ventaja.

Tres medidas, en orden de que tan pronto sirven:

  CLV        Sirve en 50 apuestas. Es la señal temprana de ventaja.
  Brier      Sirve en 200. Mide la calidad de las probabilidades.
  Ganancia   Sirve en miles. Es la que todos miran y la que menos informa.

El puntaje de Brier es el error cuadratico medio de las probabilidades. Mas bajo
es mejor. Por si solo dice poco, asi que se compara contra el Brier del mercado
sobre las mismas apuestas: si tu modelo no le gana al mercado en Brier, no tiene
nada que aportar y conviene apagar el detector de modelo.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Tramo:
    desde: float
    hasta: float
    n: int = 0
    suma_prob: float = 0.0
    aciertos: int = 0

    @property
    def prevista(self) -> float:
        return self.suma_prob / self.n if self.n else 0.0

    @property
    def observada(self) -> float:
        return self.aciertos / self.n if self.n else 0.0

    @property
    def desvio(self) -> float:
        return self.observada - self.prevista


@dataclass
class Informe:
    n_total: int = 0
    n_resueltas: int = 0
    brier_modelo: float | None = None
    brier_mercado: float | None = None
    tramos: list[Tramo] = field(default_factory=list)
    clv_promedio: float | None = None
    clv_positivo: int = 0
    clv_medidas: int = 0
    unidades: float = 0.0
    arriesgado: float = 0.0
    aciertos: float | None = None
    serie_clv: list[tuple[str, float]] = field(default_factory=list)

    @property
    def rendimiento(self) -> float | None:
        return self.unidades / self.arriesgado if self.arriesgado else None

    @property
    def veredicto(self) -> str:
        if self.clv_medidas < 30:
            return (f"Todavía no hay suficiente para juzgar: {self.clv_medidas} apuestas "
                    "con cierre medido. El CLV empieza a significar algo alrededor de 50.")
        if self.clv_promedio is None:
            return "Faltan líneas de cierre. Revisa que la corrida de cierre esté funcionando."
        if self.clv_promedio > 0.005:
            base = (f"CLV promedio {self.clv_promedio * 100:+.2f}%: le estás ganando a la "
                    "línea de cierre. Esa es la señal que importa, aunque la ganancia "
                    "todavía no se vea.")
        elif self.clv_promedio < -0.005:
            base = (f"CLV promedio {self.clv_promedio * 100:+.2f}%: estás comprando caro. "
                    "Si vas ganando dinero es suerte y se va a revertir. Revisa umbrales "
                    "y qué casas entran al consenso antes de seguir apostando.")
        else:
            base = (f"CLV promedio {self.clv_promedio * 100:+.2f}%: estás empatando con el "
                    "mercado. Sin ventaja, la comisión te gana a la larga.")

        if self.brier_modelo is not None and self.brier_mercado is not None:
            if self.brier_modelo > self.brier_mercado:
                base += (" Además tu modelo tiene peor Brier que el mercado: no está "
                         "aportando nada. Considera poner usar_modelo en false.")
            else:
                base += " Tu modelo tiene mejor Brier que el mercado sobre estas apuestas."
        return base


def _f(v, por_defecto=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return por_defecto


def analizar(ruta: Path, n_tramos: int = 10) -> Informe:
    inf = Informe()
    if not Path(ruta).exists():
        return inf

    with open(ruta, encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    inf.n_total = len(filas)
    if not filas:
        return inf

    ancho = 1.0 / n_tramos
    inf.tramos = [Tramo(i * ancho, (i + 1) * ancho) for i in range(n_tramos)]

    err_modelo, err_mercado = [], []
    clvs: list[tuple[str, float]] = []

    for fila in filas:
        clv = _f(fila.get("clv"))
        if clv is not None:
            clvs.append((fila.get("fecha_registro", "")[:10], clv))

        resultado = (fila.get("resultado") or "").strip().lower()
        if resultado not in ("ganada", "perdida"):
            continue
        inf.n_resueltas += 1
        gano = 1.0 if resultado == "ganada" else 0.0

        stake = _f(fila.get("stake_pct"), 0.0) or 0.0
        dec = _f(fila.get("momio_dec"), 0.0) or 0.0
        inf.arriesgado += stake
        inf.unidades += stake * (dec - 1) if gano else -stake

        p_mer = _f(fila.get("p_justa"))
        if p_mer is not None:
            err_mercado.append((p_mer - gano) ** 2)
            idx = min(int(p_mer / ancho), n_tramos - 1)
            t = inf.tramos[idx]
            t.n += 1
            t.suma_prob += p_mer
            t.aciertos += int(gano)

        p_mod = _f(fila.get("p_modelo"))
        if p_mod is not None:
            err_modelo.append((p_mod - gano) ** 2)

    if err_mercado:
        inf.brier_mercado = sum(err_mercado) / len(err_mercado)
    if len(err_modelo) >= 20:
        inf.brier_modelo = sum(err_modelo) / len(err_modelo)

    resueltas = [f for f in filas if (f.get("resultado") or "").strip().lower()
                 in ("ganada", "perdida")]
    if resueltas:
        ganadas = sum(1 for f in resueltas
                      if (f.get("resultado") or "").strip().lower() == "ganada")
        inf.aciertos = ganadas / len(resueltas)

    if clvs:
        inf.clv_medidas = len(clvs)
        inf.clv_positivo = sum(1 for _d, c in clvs if c > 0)
        inf.clv_promedio = sum(c for _d, c in clvs) / len(clvs)
        acumulado, serie = 0.0, []
        for i, (dia, c) in enumerate(sorted(clvs), 1):
            acumulado += c
            serie.append((dia, acumulado / i))
        inf.serie_clv = serie

    inf.tramos = [t for t in inf.tramos if t.n > 0]
    return inf


def imprimir(inf: Informe) -> None:
    print(f"Apuestas registradas: {inf.n_total} | resueltas: {inf.n_resueltas}")
    if inf.clv_promedio is not None:
        print(f"CLV promedio: {inf.clv_promedio * 100:+.2f}% "
              f"({inf.clv_positivo}/{inf.clv_medidas} le ganaron al cierre)")
    if inf.rendimiento is not None:
        print(f"Rendimiento: {inf.rendimiento * 100:+.2f}% sobre lo arriesgado "
              f"({inf.unidades:+.2f} unidades)")
    if inf.aciertos is not None:
        print(f"Aciertos: {inf.aciertos * 100:.1f}%")
    if inf.brier_mercado is not None:
        linea = f"Brier mercado: {inf.brier_mercado:.4f}"
        if inf.brier_modelo is not None:
            linea += f" | Brier modelo: {inf.brier_modelo:.4f}"
        print(linea)

    if inf.tramos:
        print("\nCalibración (qué tan bien pegan las probabilidades):")
        print(f"  {'tramo':>12}  {'n':>5}  {'prevista':>9}  {'observada':>10}  desvío")
        for t in inf.tramos:
            marca = "  <-- descuadrado" if t.n >= 20 and abs(t.desvio) > 0.10 else ""
            print(f"  {t.desde:.0%}-{t.hasta:.0%}".rjust(14) +
                  f"  {t.n:5d}  {t.prevista:8.1%}  {t.observada:9.1%}  "
                  f"{t.desvio:+6.1%}{marca}")

    print(f"\n{inf.veredicto}")


if __name__ == "__main__":
    import sys
    raiz = Path(__file__).resolve().parent.parent
    imprimir(analizar(raiz / "datos" / "registro.csv"))
    sys.exit(0)
