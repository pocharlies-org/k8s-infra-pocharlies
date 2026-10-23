Rol: tech-lead · Fecha: 2026-10-01 · Sesión: 7a35dec9-a361-4146-bb68-1e54b4683cb0 · Estado: LISTO

# INFRA-398 (P2) — design-request.py con Opus 5.5, skills y evidencia medida

Repo: /home/dibanez/src/x86-host-runtime-pocharlies, `libexec/design-request.py`. Parte DESPUÉS de P1 (INFRA-397): arranca desde la rama/commit de P1 (mismo fichero, mismo repo; un solo PR acumulado o PR sobre la rama de P1). Plan: 10-plan.md v3 y nota-architect-plan.md de INFRA-395 (mandan; no reinvestigues el router: Opus 5.5 sale a Anthropic y basta `--model`).

## Qué
- `DESIGN_MODEL` (default `claude-opus-5-5`) → `--model` en `lanzar_disenador()`. No se toca claude-router, ANTHROPIC_BASE_URL ni company-roles.
- Carga de `~/.local/share/x86-host-runtime/designer-plugin/` con `--plugin-dir` (+ variable para override en tests).
- Quitar `x-claude-router-force-local` de `ANTHROPIC_CUSTOM_HEADERS` heredadas (cambiaría Opus por el local en silencio, INFRA-243).
- `--output-format stream-json`; medir `message.model`, `message.id` con prefijo `msg_` y `usage.inference_geo`. Si el modelo medido no es el pedido (y es Opus 5.5 por defecto) → salir ≠0 con mensaje claro.
- Evidencia escrita por el SCRIPT (no por el modelo): `modelo` y `skills` (nombre+commit de LOCK.json) en el JSON de resultado, bloque `## Evidencia` añadido al `handoff.md`, y visibles en `--status <job>` y `--dry-run`.
- Actualizar docstring de design-request.py y `ARCHITECTURE.md` del repo (hoy no menciona design-request).

## Criterios (comando fijo)
- [ ] `design-request.py --dry-run "x"` → JSON con `modelo:"claude-opus-5-5"` y `skills` = las de `designer-plugin/LOCK.json`.
- [ ] `python3 -m unittest ci.test_design_skills ci.test_design_request` verde: fixture stream-json con modelo ≠ Opus 5.5 → ≠0; con Opus 5.5 y `msg_` → ok; el bloque Evidencia se añade al handoff; `--status` muestra modelo y skills.
- [ ] Verificación real mínima: una invocación corta `claude -p --model claude-opus-5-5 --output-format stream-json` desde el script contra el router 18791; pega en `50-entrega.md` los campos medidos (`message.model`, prefijo del id, `inference_geo`) y fija un fixture con esa forma real. Si LiteLLM/gate devuelve otra cosa, dilo (hallazgo, no lo maquilles).
- [ ] ARCHITECTURE.md actualizado.

## Entrega
Rama + PR, `50-entrega.md` con la salida de los comandos. No despliegues ni mergees. Termina con rama y PR.
