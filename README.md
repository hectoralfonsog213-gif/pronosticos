# Detector diario de valor

Sistema automatizado que cada media hora extrae momios y estadísticas, corre modelos
para fútbol, NFL y MLB, y busca valor con cuatro detectores distintos. Publica todo
en una página web y te avisa por Telegram.

Corre solo en GitHub Actions. No necesitas dejar una computadora prendida ni pagar
hosting.

---

## Lo primero: qué hace y qué no

Este sistema tiene **cuatro detectores**, y conviene entender la diferencia porque no
valen lo mismo.

**Detector de mercado.** Compara el precio de cada casa contra el consenso de todas
las demás, después de quitarle la comisión a cada una. Cuando una casa se queda
atrás moviendo una línea, aparece. Este detector funciona de forma repetible, no
necesita que sepas nada de deportes, y es de donde va a salir la mayoría de tus
jugadas. Es también lo que venden servicios de pago como OddsJam.

**Detector de líneas rezagadas.** Guarda cada línea que observa. Cuando las casas
afiladas mueven una línea y alguna blanda no sigue, lo detecta. Esa ventana dura
minutos y es el dinero más limpio que puedes tomar. Por esto el sistema corre cada
media hora y no una vez al día.

**Arbitrajes y middles.** No dependen de pronosticar nada, son aritmética sobre
precios. El arbitraje cubre todos los resultados y gana pase lo que pase. El middle
toma los dos lados con líneas separadas: si el resultado cae en medio, ganan las dos.
Los middles de NFL alrededor del 3 y el 7 son los que valen, y el sistema los valúa
con la distribución real de márgenes.

**Detector de modelo.** Compara el mercado contra tu propio pronóstico: Poisson con
corrección Dixon-Coles para fútbol, Elo con distribución de márgenes calibrada para
NFL, pitagórica con log5 y ajuste por abridor para béisbol. Puede encontrar cosas que
el mercado no ve. También puede estar simplemente equivocado. Por eso sale marcado
aparte, con el doble de umbral, y cuando coincide con el detector de mercado el
sistema apuesta a la probabilidad **más conservadora** de las dos.

**Lo que este sistema no hace:** no te da "las jugadas con más probabilidad de que
pasen". Esa lista sería puros favoritos a -1200 y es la forma más rápida conocida de
perder una banca. Ordena por **valor esperado**: qué tan bien te están pagando
respecto a lo que realmente vale. Un +240 con 32% de probabilidad real vale mucho más
que un -500 con 85%.

---

## Sobre los datos que pediste cruzar

Pediste cruzar estadísticas, planteles, contexto, enfrentamientos directos y rachas.
Vale la pena separar lo que carga señal de lo que no, porque el trabajo de
integración es caro y la mayor parte no se paga sola:

| Dato | ¿Sirve? |
|---|---|
| Fuerza de equipo (goles, carreras, eficiencia) | **Sí**, es la base de todo modelo |
| Abridor confirmado en MLB | **Sí**, es el factor más grande del deporte |
| Lesiones y alineaciones, *antes* de que muevan la línea | **Sí**, aquí está la ventaja real |
| Descanso, viaje, partido en tres días | **Sí**, moderado pero real |
| Clima en parques abiertos y estadios sin techo | **Sí**, en totales sobre todo |
| Enfrentamientos directos (historial) | **Casi no.** Muestra chica, planteles distintos. Ya está dentro de la fuerza de equipo |
| Rachas y "momentum" | **No.** Es de los resultados mejor documentados en estadística deportiva: la racha no predice el siguiente partido más allá de lo que ya dice la calidad del equipo |
| Motivación, "necesita ganar" | **No medible** sin caer en narrativa |

Los modelos incluidos usan lo de la primera columna. Los dos últimos renglones los
dejé fuera a propósito: meterlos hace que el modelo se sienta más inteligente y
prediga peor.

---

## Instalación

Toma unos 20 minutos. No necesitas saber programar, pero sí seguir los pasos.

### 1. Llave de la API de momios

Crea cuenta gratis en [the-odds-api.com](https://the-odds-api.com). El plan gratis da
500 créditos al mes. Copia tu llave.

**No tienes que calcular la cuota.** El sistema la administra solo: consulta el
calendario (que es gratis), solo pide momios de ligas con partidos cerca, revisa más
seguido conforme se acerca el juego, y raciona el gasto para que los créditos duren
todo el mes. Si cambias de plan, ajusta `presupuesto_mensual` en el config y el
sistema se reacomoda.

Probado en simulación de un mes completo corriendo cada 15 minutos: gasta 494 de 500
créditos en plan gratis, sin quedarse sin nada a medio mes.

### 2. Subir el proyecto a GitHub

Crea una cuenta en GitHub si no tienes. Crea un repositorio **privado** nuevo, y sube
esta carpeta completa (botón *Add file* → *Upload files*, puedes arrastrar todo).

### 3. Guardar la llave como secreto

En tu repositorio: **Settings → Secrets and variables → Actions → New repository
secret**.

- Nombre: `ODDS_API_KEY`, valor: tu llave.
- Opcional, para Telegram: `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID`.

Nunca escribas la llave dentro de un archivo del repositorio.

### 4. Encender la página

**Settings → Pages → Source: GitHub Actions.** Ahí va a quedar publicada tu página
de jugadas diarias.

### 5. Ver cómo se verá antes de conectar nada

```bash
pip install -r requirements.txt
python -m src.demo
```

Genera `docs/index.html` con datos de ejemplo y un aviso arriba diciéndolo. Ábrelo en
el navegador. Es la misma página que va a producir el sistema en vivo, así que también
sirve para probar que el renderizado quedó bien después de tocar el código.

### 6. Probar

En la pestaña **Actions**, elige *Pronósticos diarios* y dale a *Run workflow*. La
primera corrida tarda un par de minutos. Si sale verde, ya quedó: de ahí en adelante
corre sola todos los días a las 7:00 AM del centro de México.

Para probar las fuentes de datos sin gastar cuota:

```bash
pip install -r requirements.txt
python -m src.main --verificar
```

### 7. Telegram (opcional)

Escríbele a [@BotFather](https://t.me/botfather) en Telegram, manda `/newbot`, copia
el token. Luego escríbele a tu bot, abre
`https://api.telegram.org/bot<TU_TOKEN>/getUpdates` y copia el `chat.id`. Ponlos como
secretos y cambia `telegram.activo: true` en `config.yaml`.

---

## Modo de una sola jugada

Por defecto el sistema publica **una apuesta, la mejor del momento, o ninguna**.
Se configura con `modo: una_jugada`.

Para elegirla no usa el valor esperado más alto a secas. Un EV enorme en un mercado
grande casi siempre significa error de captura, línea que ya se movió, o modelo
descuadrado. El criterio es: primero las que tienen respaldo del mercado *y* del
modelo, luego las que tienen muchas casas en el consenso, y entre esas la de mayor
valor. Las que solo sostiene el modelo quedan fuera, porque si vas a hacer una sola
apuesta no conviene gastarla en la categoría con más riesgo de estar equivocada.
Cambia `exigir_respaldo_mercado` si quieres permitirlas.

### El momio mínimo

Cada jugada trae dos precios además del que se encontró:

- **Momio mínimo**: el peor precio al que la apuesta todavía vale la pena.
- **Punto de empate**: el precio donde el valor esperado llega a cero.

Sirven para lo que de verdad pasa: el sistema encuentra la jugada en una casa y tú
la vas a poner en la tuya, a otro precio. Si tu casa paga igual o mejor que el momio
mínimo, adelante. Si paga menos, no la hagas. No es la misma apuesta aunque sea el
mismo equipo: entre +210 y +190 puede estar toda la diferencia entre ganar y perder
a la larga.

## Cómo se corre

**No hay que estar prendiendo nada.** Una vez instalado corre solo: cada 30 minutos
dentro del horario donde hay deporte.

**El botón, para cuando lo quieras ahora mismo:** en tu repositorio, pestaña
**Actions** → *Detector de valor* → botón **Run workflow**. Déjale la casilla
"forzar" activada y revisa en ese momento sin esperar los intervalos. Tarda 1 o 2
minutos y la página queda actualizada.

## Los días sin jugadas

Sí te lo dice, y distingue tres situaciones, porque no son lo mismo:

| Lo que ves | Qué pasó |
|---|---|
| Las jugadas | Hay valor ahora mismo |
| "Revisamos N eventos y ninguno pasó el filtro" | Miró y no encontró nada. Normal |
| "Nada que revisar en este momento" | No había partidos en ventana. No gastó créditos |

La diferencia importa: confundir "no encontré nada" con "no miré" hace pensar que el
sistema no sirve cuando en realidad no había nada que revisar.

Las jugadas **no desaparecen** entre corridas. Si a las 2 encuentra algo para un
partido de las 6, sigue ahí a las 3 aunque esa corrida no haya consultado esa liga,
y trae un sello de cuántos minutos tiene el precio. Se cae sola si el mercado la
corrige o si el partido empieza.

## Cómo leer las jugadas

Cada jugada trae:

- **EV** — cuánto vale por peso arriesgado. +3.5% significa que a la larga esperas
  3.5 centavos de ganancia por peso, si la estimación es correcta.
- **Justa** — la probabilidad real según el consenso, sin comisión.
- **Riesgo** — porcentaje de banca sugerido: un cuarto de Kelly, con techo de 2%.
- **Casas** — cuántas casas entraron al consenso. Menos de 4 y el sistema ni la
  considera.
- **Etiqueta "solo modelo"** — no tiene respaldo del mercado. Es tu pronóstico contra
  el de todos los demás. Trátala con más cuidado y con menos dinero.

Un día sin jugadas es normal y es buena señal. Significa que el filtro está
funcionando en lugar de inventarte apuestas para justificar su existencia.

---

## Lo único que te va a decir si funciona

El sistema guarda cada jugada en `datos/registro.csv` con el momio que tomaste, y una
segunda corrida diaria anota el momio de cierre. La diferencia es el **CLV**.

- CLV promedio **positivo** y vas perdiendo → mala suerte. El sistema sirve, aguanta.
- CLV promedio **negativo** y vas ganando → buena suerte. El sistema no sirve, y la
  ganancia se va a revertir.

El CLV se estabiliza en 50 o 100 apuestas. La ganancia tarda miles: con una ventaja
real del 2%, después de mil apuestas todavía vas perdiendo en uno de cada cuatro
universos posibles. Por eso no puedes juzgar esto por un mes bueno ni por un mes malo.

**Corre el sistema tres meses sin apostar un peso**, sólo registrando. Si el CLV
promedio es positivo, entonces tiene sentido empezar con dinero.

---

## Límites que conviene saber desde ahora

**El plan gratis no incluye casas afiladas.** Pinnacle y Betfair son las referencias
que mueven primero; sin ellas el consenso es más ruidoso y el detector pierde filo.
Si esto te empieza a funcionar, un plan con acceso a Pinnacle es la primera inversión
que vale la pena, muy por encima de mejorar los modelos.

**Los nombres de equipo no coinciden entre fuentes.** El módulo empareja por
similitud y devuelve nada cuando no está seguro, que es preferible a emparejar mal.
Vas a ver partidos sin pronóstico de modelo por esto. Se arregla agregando alias a
mano conforme aparecen.

**Las fuentes gratuitas son endpoints públicos, no productos con contrato.** ESPN,
statsapi.mlb.com y ClubElo pueden cambiar de formato sin avisar. Por eso cada deporte
va aislado: si una se cae, las demás siguen.

**Si ganas de forma sostenida, te van a limitar.** Es el final normal de un ganador en
una casa comercial. Cuéntalo dentro del plan desde el principio y abre varias cuentas.

**Y lo más importante:** que el sistema encuentre valor no significa que vaya a ganar.
Significa que, *si* las probabilidades están bien estimadas, la apuesta paga de más.
Las dos cosas que pueden fallar son la estimación y tu paciencia. Arriesga solo dinero
que puedas perder sin que te cambie la semana.

---

## Estructura

```
config.yaml              ligas, mercados, umbrales, pesos por casa
src/
  main.py                orquestador: corre todo el ciclo
  mercado.py             momios, de-vig, consenso, EV, Kelly
  motor.py               detección de valor y depuración de jugadas
  puente.py              conecta los modelos con las líneas del mercado
  reporte.py             JSON, página HTML, registro histórico
  cierre.py              captura de línea de cierre y CLV
  agenda.py              qué consultar y cuándo, sin quemar la cuota
  historial.py           registro de líneas y detección de rezagos
  arbitraje.py           arbitrajes y middles
  calibracion.py         Brier, fiabilidad y veredicto sobre el sistema
  demo.py                vista previa de la página con datos de ejemplo
  models/futbol.py       Poisson + Dixon-Coles desde Elo
  models/nfl.py          Elo + distribución de márgenes con números clave
  models/mlb.py          pitagórica + log5 + ajuste por abridor
  sources/odds.py        The Odds API
  sources/datos.py       statsapi.mlb.com, ESPN, ClubElo
notify/telegram.py       envío diario
docs/                    página publicada
datos/registro.csv       historial con CLV
```

## Ajustes que quizá quieras hacer

**Menos jugadas, mejores.** Sube `ev_minimo_mercado` a `0.03` y `casas_minimas` a `6`.

**Revisar cada 15 minutos.** Edita el cron en el workflow. Pero saca la cuenta antes:
un repositorio privado trae 2,000 minutos gratis de Actions al mes y cada corrida
gasta ~1.5. La configuración actual usa ~1,800. Para ir a 15 minutos necesitas hacer
el repositorio público (minutos ilimitados) o pagar minutos extra.

**Ver si el modelo sirve.** `python -m src.calibracion` compara el Brier de tu modelo
contra el del mercado sobre las mismas apuestas. Si el tuyo es peor, el modelo no está
aportando nada y conviene poner `usar_modelo: false`. Mejor apagarlo que creerle.

**Otras ligas.** Corre `python -m src.main --verificar` para ver las claves
disponibles y agrégalas en `config.yaml`. Las ligas chicas suelen tener líneas más
flojas que las grandes.

**Calibrar el fútbol a tu liga.** Los parámetros por defecto son de ligas europeas.
Con una temporada de resultados, `src.models.futbol.calibrar()` ajusta goles
promedio, ventaja de local y la correción Dixon-Coles a la liga que sea.

**Cambiar el horario.** Edita el `cron` en `.github/workflows/diario.yml`. Está en
UTC: el centro de México es UTC-6.
