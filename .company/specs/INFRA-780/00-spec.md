Rol: pm · Fecha: 2026-10-08T22:15:00+00:00 · Sesión: enc-analista-INFRA-780-cf4e9f69 · Estado: FALTA INFO

## Objetivo
A quién sirve: a Jordi (y de rebote a Dani, que imprime). Que las 3 NVIDIA Ascent GX10 de Jordi viajen y funcionen en un rack 3x impreso en la X1C con ventilación silenciosa capaz de evacuar los ~720 W pico sin throttling, siguiendo el precedente del rack doble ya impreso. Si no se hace, las GX10 se quedan apiladas sin flujo de aire controlado (throttling térmico, ver gotcha de dgx2 con GPU a 611 MHz por calor) y el favor a Jordi queda a medias.

Repo: bambulab-openclaw

## Pregunta para Dani
Falta UNA decisión: la configuración de ventiladores, que fija la geometría del STL. Está sin cerrar en el topic «Rack GX10» (Jordi pidió confirmación hace una hora; el cálculo completo está en INFRA-781, rondas 1 y 2). Las otras dos tareas hijas (alimentación INFRA-782 y control térmico INFRA-783) NO necesitan a Dani: su criterio técnico queda cerrado abajo en «Diseño».

1. 4x Noctua NF-A12x25 G2 en rack de 250 mm de ancho (2 delante aspirando + 2 abajo empujando, PWM a ~1200 rpm): 1081 W de capacidad, margen 1,5x, ~25 dBA reales (recomendada)
2. 3x NF-A12x25 G2 en rack del ancho de la unidad (150 mm): 1 delante + 1 abajo + 1 detrás, flujo en línea recta: 810 W, margen 1,13x, ~28 dBA
3. 6x NF-A8 (80 mm) en rack de ≥160 mm: 838 W, margen 1,16x, más cableado y unidades

Con la respuesta se cierran INFRA-781/782/783 y el spec pasa a LISTO sin más análisis.

## Diseño
Diseñador: no — es un objeto físico (STL), no una interfaz; el «mockup» es el propio modelo paramétrico y el precedente visual es el rack doble ya impreso.

Criterio técnico cerrado para las tareas hijas (se confirma al cerrarlas, no requiere a Dani):
- Alimentación (INFRA-782): cada GX10 se alimenta de su propio fuente (unidad de sobremesa, 240 W pico por GB10). El rack NO reparte 230 V: solo alimenta los ventiladores con una fuente externa de 12 V (≤10 W) y un hub PWM; ningún cable de red eléctrica dentro de la pieza impresa.
- Control térmico (INFRA-783): 2 sondas NTC (entrada y salida del rack) + controlador PWM con umbral: 50 % duty desde 45 °C, 100 % desde 60 °C. Opcional deseable: sonda de entrada en Home Assistant (la casa va a HA, INFRA-490) para alerta; no bloquea la épica.
- Geometría: GX10 mide 150×150×51 mm; en 150 mm de ancho solo cabe 1x120 mm por cara (por eso la opción 1 exige rack de 250 mm). Altura interior por nivel ≥55 mm. Ojo cama X1C: 256×256×256 — el rack de 250 mm entra justo en X.

## Criterios de aceptación
(activos en cuanto se responda la pregunta; cada uno con su comprobación)
- [ ] El diseño paramétrico del rack 3x y su STL generado viven en el repo de la impresora.
  Comando: `git -C ~/k8s/bambulab-openclaw ls-files | grep -i rack-gx10`
  Salida: al menos un fichero de diseño (`.scad`/`.py`) y un `.stl` bajo `design/` (nombres concretos los fija la historia de diseño).
- [ ] El STL laminado pasa el preflight de la pipeline sin avisos de tamaño.
  Comando: `python3 -m bambu_openclaw.cli preflight <ruta>/rack-gx10-3x.3mf`
  Salida: `OK` / exit 0 (rechaza <1 KB o sin `Metadata/plate_*.gcode`).
- [ ] La impresión se completa en la X1C desde la pipeline (no a mano desde la SD):
  Comando: `python3 -m bambu_openclaw.cli jobs get <job_id>`
  Salida: `"status": "completed"` (tras renovar el token de Bambu Cloud si estuviera caducado — ver Restricciones).
- [ ] Montaje verificado: las 3 GX10 entran a presión correcta, los ventiladores elegidos van fijados al rack y giran. Evidencia: 2 fotos en el ticket (frontal y con las unidades puestas), veredicto humano del pm en 80-validacion-pm.md.
- [ ] Prueba térmica: con las 3 unidades en carga sostenida ≥30 min, ΔT entrada→salida ≤ 15 °C y sin throttling. Evidencia: lectura de las 2 sondas NTC pegada en el ticket (o `nvidia-smi -q -d TEMPERATURE,PERFORMANCE` en una GX10 conectada a la red de casa mostrando clocks completos).

## Restricciones
- Jordi paga el gasto (filamento PETG + 4 ventiladores NF-A12x25 G2 si se elige la opción 1); no se compra nada sin su confirmación en el topic.
- Gotcha conocido: el token de Bambu Cloud caduca. La X1C rechaza el envío por LAN directa (err 84033543, firmware) → el 3MF sube por el S3 de Bambu Cloud. Flujo de renovación probado el 04-10: contraseña en el vault `llavero` + código de verificación al buzón pocharlies@gmail.com.
- El .stl del rack doble NO está en el x86 (buscado: solo hay STLs de calibración de BambuStudio y jobs viejos en ~/bambulab-openclaw/var/jobs). Localizarlo (Bambu Studio del Mac o Bambu Cloud) ANTES de diseñar; si no aparece, se rediseña desde las cotas de la GX10 (150×150×51).
- GitOps: nada de push directo al tronco; PR y merge automático con CI verde (regla de la casa).
- La cama de la X1C es 256×256×256: cualquier opción que pase de 256 mm en alguna orientación exige partir la pieza en piezas atornilladas (añade historia de uniones).

## Trabajo reciente (24 h)
- 08-10 21:52-21:53 UTC — Dani crea INFRA-780 y las tareas hijas INFRA-781/782/783 (Tasks, en To Do) tras el encargo de Jordi en el topic «Rack GX10» (thread 3445). No duplicar: este spec las referencia, no recrea.
- 08-10 22:08 UTC — Sesión viva (perfil agentic-link, telegram): dos rondas de cálculo de ventilación anotadas en INFRA-781 (720 W pico; NF-A12x25 G2 vs NF-A8; tabla de configuraciones). Jordi sigue decidiendo tamaño/posición («2 delante y 2 abajo? todos de 8 no?»). Esa conversación es la que desbloquea esta épica; no desdoblar la pregunta en otro canal.
- 05-10 — INFRA-584 entregada: bambulab-openclaw en producción con ruta de publicación LAN y pipeline de jobs funcionando (imagen 20261005-4). La impresión por pipeline está viva; el precedente de renovación de token es del 04-10 (adaptador Dyson impreso con éxito).
- Sin sesiones VIVAS (claude-tmux list) trabajando en el rack.

## Historias previstas
- H1 · Cerrar especificación: cerrar INFRA-781/782/783 con la respuesta de Jordi y fijar el STL objetivo (dueño: pm).
- H2 · Diseño paramétrico del rack 3x a partir del rack doble (o desde cotas GX10 si el .stl no aparece), con sujeción de los ventiladores elegidos (dueño: developer).
- H3 · Laminado y envío a la X1C por bambulab-openclaw, con renovación de token si toca (dueño: developer).
- H4 · Impresión, montaje y prueba térmica con evidencia en el ticket (dueño: qa, con la mano física de Dani al montar).

## Tamaño
S — 4 historias, un repo, menos de una semana real (el cuello es el secado/post-proceso de la impresión y la respuesta de Jordi, no el análisis).

## Dificultad
Dificultad: media — es ampliar un precedente que ya existe (rack doble impreso) usando una pipeline de impresión que ya funciona; no hay producto ni software nuevo desde cero, y el coste de un mal arranque es filamento, no datos.
