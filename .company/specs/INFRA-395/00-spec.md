Rol: pm · Fecha: 2026-10-02T06:41:20Z · Sesión: 8ea921e3-ddf0-44eb-b23e-e4819b351ac6 · Estado: LISTO

## Objetivo

Que el rol company-designer produzca diseños web profesionales: skills de diseño versionadas en su entorno y pipeline (`design-request.py`) que invoque SIEMPRE Opus 5.5, configurable y con evidencia medida del modelo y skills aplicadas. Es previa e imprescindible de INFRA-396 (rediseño de www.e-dani.com, blocked-by esta).

Repo: x86-host-runtime-pocharlies

**Estado real (medido 2026-10-02):** esta épica YA está a medio ejecutar por una sesión tech-lead de ayer (sesión 7a35dec9): historias creadas (INFRA-397/398/399), P1 mergueada y desplegada, P2 en Review con QA y architect aprobados. El CTO no parte de cero: queda mergear #559, desplegar, el E2E (P3) y cerrar. Ver `## Trabajo reciente (24 h)`.

## Criterios de aceptación

- [x] C1 · Skills de diseño versionadas e instaladas (no manuales en el host): árbol `designer-plugin/` en el repo con `LOCK.json` (repo origen, commit, licencia, sha256 por fichero), instalado en `~/.local/share/x86-host-runtime/designer-plugin/`, y cero skills de diseño en `~/.claude/skills` (global).
  Comando: `cd ~/src/x86-host-runtime-pocharlies && python3 -m unittest ci.test_design_skills` → `Ran 32 tests ... OK` (medido 2026-10-02, OK). Y `ls ~/.claude/skills | grep -iE 'web-design|frontend-design|brag'` → vacío (medido: solo `company-design`, que es el skill del rol, no una guía vendorizada).
  Nota: `/brag` (latent-spaces/brag) quedó FUERA con motivo registrado — genera vídeos de lanzamiento, no guías de diseño (veredicto architect, `nota-architect-plan.md`). Las fuentes reales son `vercel-labs/agent-skills` (`web-design-guidelines`, adaptada para leer `rules.md` local en vez de descargar por URL, y `frontend-design`).
- [ ] C2 · El pipeline invoca Opus 5.5, configurable: `DESIGN_MODEL` (default `claude-opus-5-5`) → `--model`, y el dry-run lo evidencia.
  Comando: `~/.local/libexec/x86-host-runtime/design-request.py --dry-run "x"` → JSON con `"modelo": "claude-opus-5-5"` y `"skills"` = las del LOCK.
  Medido hoy: el JSON NO tiene `modelo` ni `skills` (versión desplegada = P1 sin P2). Depende de mergear #559 y desplegar.
- [ ] C3 · El modelo usado es verificable sin fiarse del modelo: `--status <job>` y el `handoff.md` (bloque `## Evidencia` escrito por el script, medido del stream-json: `message.model`, `message.id` `msg_*`, `inference_geo`) muestran el modelo real; si el medido ≠ Opus 5.5 sin override explícito, el script sale ≠0.
  Comando: `~/.local/libexec/x86-host-runtime/design-request.py --status <job>` → campo `modelo` presente; unittest con fixture de modelo ≠ Opus → exit ≠0 (`python3 -m unittest` del repo, en CI).
- [ ] C4 · E2E: encargo real «rediseña el hero de e-dani.com» → canvas `.dc.html` con tokens, componentes y ≥2 variantes, generado con Opus 5.5 medido.
  Comando: `~/.local/libexec/x86-host-runtime/design-request.py --detach --name hero-e-dani "rediseña el hero de e-dani.com"` → `--status <job>` final `ok:true`, `modelo` medido = `claude-opus-5-5`, `--validate <canvas>` ok; en el `.dc.html`: `grep -q 'var(--' && grep -qi 'componente\|component' y ≥2 variantes (`grep -c 'data-variant\|<!-- v'` ≥2 según fije el spec de INFRA-399); `handoff.md` con `## Evidencia`.

## Restricciones

- Repo del trabajo: `x86-host-runtime-pocharlies` (`libexec/design-request.py`, despliegue por CI/`install.sh` en el x86). `k8s-infra-pocharlies` NO se toca.
- Las skills NO van en `skills/` del repo (install.sh la copia al global `~/.claude/skills`): van en `designer-plugin/` + `--plugin-dir`.
- No tocar `claude-router`, `ANTHROPIC_BASE_URL` ni `company-roles`. Cuidado con los caminos que cambian Opus por el local en silencio (INFRA-243): cabecera heredada `x-claude-router-force-local` y `claude_gate` en modo rewrite.
- La evidencia del modelo la mide el script (stream-json), nunca la escribe el modelo.
- Opus 5.5 en las sesiones interactivas del designer dentro de una épica = cambio aparte en `company-roles`, fuera de alcance.

## Trabajo reciente (24 h)

- 2026-10-01 · sesión tech-lead 7a35dec9: `10-plan.md` v3 + nota architect (APROBADA con 3 correcciones ya incorporadas); creadas INFRA-397 (P1), INFRA-398 (P2), INFRA-399 (P3).
- 2026-10-01 · P1 = PR #555 MERGED (CI verde, `aprobacion/qa` y `aprobacion/architect` SUCCESS) y DESPLEGADA en el x86: `designer-plugin/` con LOCK.json existe, `ci/test_design_skills.py` en el tronco, 32 tests OK medidos hoy. C1 ya se cumple.
- 2026-10-01 · P2 = PR #559 ABIERTA (`infra-398-design-opus-v2`, rebase sobre #555): CI verde y QA + architect aprobados → lista para mergear. El `design-request.py` desplegado aún no tiene `modelo`/`skills` (medido con `--dry-run`).
- 2026-10-01 20:28 UTC · la épica volvió a Backlog mientras sus historias siguen en Review (397 y 398) — incoherencia de tablero, no de terreno. Ninguna sesión VIVA trabajando en esto ahora.
- Qué le hace al plan: C1 sobra ejecutarlo (ya entregado); el trabajo restante es mergear #559 + desplegar, el E2E P3 (INFRA-399, To Do) y cerrar 397/398/399.

## Diseño

Diseñador: no — no hay interfaz que construir: la épica configura el pipeline del propio diseñador; el entregable visual (canvas .dc.html) lo produce el E2E y lo valida qa con `--validate` y grep de tokens/variantes. Sin revisión UX posterior (decisión del tech-lead en 10-plan.md, razonada: no hay UI de developer).

## Historias previstas

Todas EXISTEN ya — el CTO no crea historias nuevas:
- INFRA-397 · P1 skills versionadas (dueño: developer) — entregada, PR #555 mergueada y desplegada; cerrar al validar C1.
- INFRA-398 · P2 Opus 5.5 + evidencia (dueño: developer) — en Review, #559 aprobada por qa y architect; mergear, desplegar y cerrar.
- INFRA-399 · P3 E2E hero e-dani.com (dueño: qa) — To Do; lanzar tras desplegar #559.

## Dificultad

Dificultad: media — funcionalidad nueva con lógica (medición del modelo desde stream-json, guard de modelo, carga de plugin) dentro de un solo repo, sin decisión de arquitectura (ya la dio el architect) y reversible con revert del PR; no toca cluster, secretos ni enrutado del LLM compartido (el router local solo recibe `--model`).

## Tamaño

S — 3 historias en un repo, y 2/3 ya entregadas; lo que queda es un merge, un despliegue y un E2E.
