Rol: tech-lead · Fecha: 2026-10-01 · Sesión: 7a35dec9-a361-4146-bb68-1e54b4683cb0 · Estado: LISTO

# INFRA-399 (P3) — E2E del diseñador con Opus 5.5

Precondición: PR #555 (P1) y #556 (P2) de pocharlies-org/x86-host-runtime-pocharlies mergeados y desplegados en el x86 (`~/.local/libexec/x86-host-runtime/design-request.py` y `~/.local/share/x86-host-runtime/designer-plugin/` presentes). Comprobar antes; si no, informar, no probar contra un worktree.

## Criterios (comando fijo, qa los ejecuta y NO se fía de lo que el handoff diga: lee el JSON de resultado y el transcript)
- [ ] `design-request.py --dry-run "x"` → `modelo: claude-opus-5-5` y `skills` = las de `designer-plugin/LOCK.json` instalado.
- [ ] `design-request.py --detach --name hero-e-dani "rediseña el hero de e-dani.com"` → `--status <job>` acaba en `ok:true` (tope razonable; es un trabajo largo: lanzar detached y esperar el fichero del job, sin sondear).
- [ ] El resultado JSON lleva `modelo` medido = `claude-opus-5-5` y `skills` presentes; el `handoff.md` contiene `## Evidencia` con modelo y skills; `--status` los muestra.
- [ ] `design-request.py --validate <canvas>` → `ok:true`.
- [ ] El `.dc.html` contiene tokens (colores, tipografía, espaciados), componentes y al menos 2 variantes del hero (grep fijo sobre el fichero; reporta el recuento).
- [ ] Prueba negativa: `DESIGN_MODEL=<modelo local>` sin override explícito no pasa en silencio (el script lo señala/evidencia el modelo real). Si el diseño no lo contempla, repórtalo.
- Adjunta el canvas y el handoff a INFRA-399 (nota-qa o adjuntos) como evidencia. `70-qa.md` con el veredicto.
