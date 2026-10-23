Rol: pm · Fecha: 2026-10-01T23:15:00Z · Sesión: epica-infra-359 · Estado: LISTO

## Objetivo
Dejar /model-routing del dashboard DGX con un único tema oscuro coherente: los 3 textareas de criterios con fondo oscuro, jerarquía de botones (guardar primario con relleno, descartar secundario con borde, volver a git enlace tenue) y filas alternas perceptibles, reutilizando los tokens de colors_and_type.css. Sin solapes: el contraste de botones y etiquetas ya lo cerró de hecho la migración React de INFRA-263 (ver Trabajo reciente) — aquí solo quedan color, clases y zebra.

Repo: dgx-infra

## Criterios de aceptación
- [ ] Los 3 textareas de «criterios de clasificación» se sirven con fondo oscuro y texto claro (hoy heredan el blanco del navegador).
  - Comando (x86): `export KUBECONFIG=/home/dibanez/.kube/config; kubectl -n control-nexus exec deploy/dgx-dashboard-ui -- sh -c 'wget -qO- http://127.0.0.1/static/inferencia/model-routing.css' | grep "textarea"`
  - Esperado: la regla `#dificultad textarea` incluye `background` (gris muy oscuro, p. ej. `var(--bg-1)` o `rgba(8,16,25,.6)` como los inputs) y `color: var(--text...)`. Hoy solo tiene `width/min-height/font/resize/box-sizing` → fondo blanco UA.
- [ ] Ratio de contraste ≥4,5:1 en el texto de «VOLVER A GIT», «DESCARTAR» y las etiquetas de criterio sobre su fondo.
  - Comando (x86): traer las dos CSS servidas (`model-routing.css` y `colors_and_type.css`, mismo wget del criterio 1) y calcular en python el ratio WCAG del color resuelto de `.danger` y del `label` de `#dificultad .criterios` contra `--bg-0` (`#081019`).
  - Esperado: ≥4,5. YA es verdad hoy (`--danger #ff7d9f` = 7,9:1; `--muted-2 #7b93aa` = 6,0:1): tras la jerarquía del criterio 3 debe seguir siéndolo, incluidas las variantes `:disabled` y hover.
- [ ] Jerarquía de botones en la tarjeta de dificultad (y same en las otras tarjetas de la página): `guardar` primario con relleno, `descartar` secundario con borde visible, `volver a git` enlace tenue (sin borde, color muted).
  - Comando (x86): `... wget -qO- http://127.0.0.1/static/inferencia/model-routing.css | grep -E "btn-primary|dif-save|#dif-git"`
  - Esperado: al menos una regla de relleno para el guardar (`background:` distinto de `transparent`) y reglas distinguibles para descartar (borde) y volver a git (tenue). Hoy los tres botones comparten el mismo estilo ghost (`.danger` solo cambia el color).
- [ ] Zebra perceptible: ratio de luminancia ≥1,15:1 entre la fila resaltada y la normal de las tablas de la página.
  - Comando (x86): leer del CSS servido el `background` de `tr.base td`, mezclarlo sobre `--bg-0` y calcular el ratio (mismo script del criterio 2).
  - Esperado: ≥1,15. Hoy `rgba(70,213,255,.035)` → 1,05:1 (casi imperceptible); con alfa ≈0,08–0,10 o un fondo alterno explícito se cumple.
- [ ] Sin cambios funcionales: la página y su API se comportan igual.
  - Comando (x86): `kubectl -n control-nexus exec deploy/dgx-dashboard-ui -- sh -c 'wget -qO- http://127.0.0.1/model-routing' | grep -c "data-app-entry"` → `1`; y CI en verde con `services/dashboard/tests/test_model_routing_routes.py` y `test_ui_production_build.py`.
- [ ] Capturas antes/después pegadas en la historia QA (página completa, con los 3 textareas y las acciones visibles), sobre el despliegue servido.

## Restricciones
- Cambiar solo `services/dashboard/static/inferencia/model-routing.css` y, si hace falta para las clases de botón, `src/pages/CompanySettingsCards.jsx` (clases nada más, sin tocar lógica ni markup estructural).
- Reutilizar tokens de `static/colors_and_type.css` (`--bg-0/1`, `--text`, `--muted-2`, `--line`, `--danger`, `--accent`): no inventar una paleta paralela.
- Tras tocar CSS, `npm run build` en `services/dashboard/static/inferencia` (write-shell.mjs reescribe el shell con el bundle con hash) y commitear el shell regenerado — `test_ui_production_build.py` lo comprueba.
- Rama desde `origin/master` (ArgoCD `control-nexus` y `dashboard-ui` trackean master, verificado hoy en `f7d1bf03`); push directo al tronco bloqueado por hook — PR y merge por CI verde.
- Mantener el chip OPERADOR y los acentos verde/azul que ya funcionan.

## Trabajo reciente (24 h)
- 2026-10-01 00:18 (+02) commit `025a0e5b` (INFRA-263): /model-routing migrada a React — el HTML es ahora un shell y los estilos viven en `static/inferencia/model-routing.css`. Deja obsoletas las premisas de la épica: los hex `#f8f9fb`, `#c9506e`, `#9a4a63`, `#0d1422`, `#0a0f1a` ya NO existen en el repo (`git grep` sobre `origin/master` = 0 hits); los botones usan `--danger #ff7d9f` (7,9:1) y las etiquetas `--muted-2` (6,0:1) — el criterio de contraste ya se cumple y solo debe mantenerse.
- Hoy ArgoCD sirve master `f7d1bf03` en `control-nexus` y `dashboard-ui` (pods con ~3 h de vida): producción ya corre la versión React — el zebra «#0d1422/#0a0f1a» de la captura es del HTML viejo; el zebra real hoy es `tr.base` con alfa .035 (1,05:1).
- Radar 23:00Z: ninguna sesión viva trabajando en los estilos de este panel — no se duplica nada.
- INFRA-264 está metiendo cambios React en `static/inferencia` hoy (playground, `fa5d2b0e`): rebasear la rama sobre el master del día antes del PR.

## Diseño
Diseñador: no — la épica ya define la paleta objetivo, el ratio WCAG exigido y la jerarquía de botones; no hay pantallas ni flujos nuevos, solo ajuste de tokens y clases sobre una UI existente.

## Historias previstas
- S1 (developer): textareas oscuros + jerarquía de botones + zebra perceptible en `inferencia/model-routing.css` (clases en CompanySettingsCards.jsx si hace falta), `npm run build` y shell regenerado comiteado.
- S2 (qa): capturas antes/después servidas, ratios de contraste medidos con comando y prueba de no-regresión funcional (rutas + build test).

## Tamaño
S — un fichero CSS (más clases puntuales en un JSX), un repo, un PR reversible.

## Dificultad
Dificultad: baja — estilos en un solo repo (dgx-infra), el qué y el dónde están claros en la épica, sin lógica nueva ni datos, se deshace con un revert; nada de la lista de alta.
