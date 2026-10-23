Rol: tech-lead · Fecha: 2026-10-01 · Sesión: 7a35dec9-a361-4146-bb68-1e54b4683cb0 · Estado: BORRADOR

# INFRA-395 — Plan v3: diseñador con skills de diseño web + Opus 5.5

## Hallazgos (leídos, no supuestos)
- Repo del trabajo: `x86-host-runtime-pocharlies` (`libexec/design-request.py`; despliegue `./install.sh` en el x86). `k8s-infra-pocharlies` NO se toca.
- `lanzar_disenador()` ejecuta `claude -p --agent company-designer ...` contra el router local `127.0.0.1:18791`, sin `--model`; el modelo sale de `company-designer.md` (`qwen38-flash-next`).
- El router pasa `claude-opus-5-5` a api.anthropic.com (no hay que tocar `claude-router`, `ANTHROPIC_BASE_URL` ni `company-roles`). Basta `--model`.
- Caminos que cambian Opus por el local en silencio (INFRA-243): cabecera heredada `x-claude-router-force-local` (en `ANTHROPIC_CUSTOM_HEADERS`) y `claude_gate` en modo `rewrite`; el interruptor de Claude de la compañía da 403 ruidoso.
- La evidencia del modelo no puede salir del `handoff.md` escrito por el modelo: la mide el script.

## Partes
- **P1 · Skills versionadas** (developer, repo x86-host-runtime-pocharlies): árbol nuevo `designer-plugin/` en la raíz (NO `skills/`, que `install.sh` copia al global `~/.claude/skills`), con `LOCK.json` (repo origen, commit fijado, licencia, sha256 por skill). Vendorizado (ambos repos MIT). `install.sh` lo instala en `~/.local/share/x86-host-runtime/designer-plugin/`. Fuentes reales: `vercel-labs/skills` es solo el instalador; las skills están en `vercel-labs/agent-skills` (solo `web-design-guidelines` es guía de UI); `latent-spaces/brag` = vídeos de lanzamiento. Paleta/tipografía/espaciados/micro-animaciones/componentes: buscar en el ecosistema; lo que no exista se REGISTRA en la historia, no se inventa. Antes de vendorizar, comprobar que `web-design-guidelines` no descarga reglas por URL al ejecutarse. Test: `ci/test_design_skills.py` (`unittest`, el repo no tiene pytest ni `tests/`), añadido al paso de CI de design-request.
- **P2 · Modelo Opus 5.5 + evidencia** (developer, MISMO repo, DESPUÉS de P1: mismo fichero): `DESIGN_MODEL` (default `claude-opus-5-5`) → `--model`; carga de `designer-plugin` con `--plugin-dir`; limpiar `x-claude-router-force-local` de las cabeceras heredadas; `--output-format stream-json` y medición de `message.model`, `message.id` con prefijo `msg_` y `usage.inference_geo`; si el modelo medido no es Opus 5.5 (y no hay override explícito de `DESIGN_MODEL`) el script sale ≠0; `modelo` y `skills` (nombre+commit) en el JSON de resultado, en un bloque `## Evidencia` añadido por el script al `handoff.md`, y en `--status` y `--dry-run`. Tests unittest con fixtures stream-json. Actualiza docstring y `ARCHITECTURE.md` del repo (hoy no menciona design-request). Pendiente de confirmar con petición real (P3): que LiteLLM no devuelva `msg_`/`inference_geo`; se fija en el fixture.
- **P3 · Validación E2E** (qa): encargo real «rediseña el hero de e-dani.com».
- Sin UI de developer: la entrega es el canvas del propio diseñador; no hay revisión UX posterior.

## Criterios (comando fijo)
1. `design-request.py --dry-run "x"` → JSON con `modelo:"claude-opus-5-5"` y `skills` = exactamente las de `designer-plugin/LOCK.json` (nombre+commit).
2. `python3 -m unittest ci.test_design_skills` verde: árbol instalado == LOCK (sha256); ninguna skill del diseñador en `~/.claude/skills`.
3. Fixture stream-json con modelo ≠ Opus 5.5 → script sale ≠0 con mensaje; con Opus 5.5 → ok (unittest).
4. E2E: `design-request.py --detach --name hero-e-dani "rediseña el hero de e-dani.com"` → `--status <job>` final `ok:true`, `modelo` medido = claude-opus-5-5, skills presentes; `--validate <canvas>` ok; el .dc.html contiene tokens, componentes y ≥2 variantes (grep fijo en el spec); `handoff.md` con `## Evidencia`.

## Riesgos / decisiones
- Cuota: Opus por defecto, configurable (`DESIGN_MODEL`). Una invocación vía hermes no lleva `x-claude-class: company`, así que el interruptor/gate de la compañía no la ve; si el CTO quiere atarla, el script estampa esa cabecera (una línea). No bloquea el arranque.
- Opus también en las sesiones del designer dentro de una épica = cambio aparte en `company-roles` (fuera de alcance).
- Licencia/procedencia: verificar y registrar en LOCK.
