Rol: pm · Fecha: 2026-10-03T07:29:00Z · Sesión: d95cacdc-ae26-49d4-810e-c215f2076dac · Estado: LISTO

# INFRA-220 — Blog diario: cada entrada empaqueta como producto algo ya construido, validado como vendible por finanzas y marketing

## Objetivo
Cada entrada diaria del blog empaqueta como producto, para público externo, algo YA construido (verificable en repos) y solo sale con el doble OK de `finance-agent` y `marketing-agent` vía `veredicto.js`; sin doble OK ese día no hay entrada (resultado correcto). Base ya entregada: SC-1536 (agentes finanzas+marketing, Done: roles en ~/src/company-roles y `bin/veredicto.js`) e INFRA-190/INFRA-193 (pipeline de las 05:00 y bandeja de aprobación, Done); las 5 historias ya existen (INFRA-221..225, en To Do).

Repo: k8s-blog-pocharlies

Fuera: cocina interna, conveniencia, autopublicación. Cierre de la épica: 3 entradas seguidas con doble OK y cero rechazos.

## Criterios de aceptación
- [ ] C1 (INFRA-221) La política de contenido vive en el repo del blog y define "producto vendible a público externo" y la lista de lo excluido (cocina interna, conveniencia).
  Comando: `cd ~/k8s/k8s-blog-pocharlies && git fetch origin -q && git grep -il "cocina interna" origin/main -- ':!src/site/content'`
  Esperado: imprime al menos `origin/main:<ruta del fichero de política>` (ruta fijada por INFRA-221) y el fichero contiene las secciones "Qué sí" y "Qué no".
- [ ] C2 (INFRA-222) El turno propone un candidato de algo ya construido y pide veredicto a ambos agentes antes de escribir borrador.
  Comando: `grep -ci "veredicto" ~/.local/libexec/x86-host-runtime/blog-daily.py && node ~/src/company-roles/bin/veredicto.js --validar`
  Esperado: primer número mayor que 0 (hoy 0) y `ok: N verdict(s) valid` con N >= 8 tras la primera entrada (hoy 6).
- [ ] C3 (INFRA-224) Registro vivo de candidatos: cada candidato queda con estado (propuesto, doble OK, rechazado, publicado) y los veredictos de finanzas y marketing.
  Comando: `jq -r '.[]? // . | [.id,.estado,.finance,.marketing]|@tsv' <fichero de registro fijado por INFRA-224>`
  Esperado: una línea por candidato; los de estado `doble-ok` o `publicado` tienen finance=ok y marketing=ok; ninguno `publicado` sin ambos.
- [ ] C4 (INFRA-223) Verificación de afirmaciones: toda afirmación del borrador sobre lo construido (repo, PR, cifra) se comprueba contra el repo; si una falla, el borrador no se deja en `drafts`.
  Comando: `journalctl --user -u blog-daily.service --since "-2d" | grep -i "afirmaci"`
  Esperado: línea con `afirmaciones verificadas: N/N` en un día con borrador; con una afirmación falsa (prueba controlada) el turno sale sin borrador y registra el motivo.
- [ ] C5 Sin doble OK no hay entrada: un día con candidato rechazado por cualquiera de los dos agentes no crea borrador.
  Comando: `cd ~/k8s/k8s-blog-pocharlies && git log origin/drafts --since "-1d" --format '%h %ad %s' --date=short; jq -r .status ~/.local/share/blog-daily/state.json`
  Esperado: en un día con rechazo, `git log` no muestra commit nuevo de ese día en `drafts` y `status` indica sin-entrada/rechazado con el motivo.
- [ ] C6 (INFRA-225) Primera entrada publicada: producto empaquetado de algo construido, con doble OK registrado, aprobada por Dani en la bandeja existente.
  Comando: `cd ~/k8s/k8s-blog-pocharlies && git fetch origin -q && git log origin/main --since "-14d" --format '%h %ad %s' --date=short -- src/site/content | head -3`
  Esperado: al menos un commit de entrada nueva y su registro (C3) en estado `publicado`.
- [ ] C7 El timer vuelve a estar activo solo cuando S2+S4 están desplegadas y el servicio corre sin error.
  Comando: `systemctl --user is-active blog-daily.timer; journalctl --user -u blog-daily.service --since "-1d" | grep -ci "error\|traceback"`
  Esperado: `active` y `0` (hoy: `inactive`, apagado el 03-10 06:55 UTC por el perfil default de Hermes).
- [ ] C8 Cierre: 3 entradas consecutivas con doble OK y cero rechazos.
  Comando: `jq -r '[.[]|select(.estado=="publicado" or .estado=="rechazado")]|.[-3:]|map(.estado)|@tsv' <fichero de registro>`
  Esperado: `publicado	publicado	publicado`.

## Restricciones
- No tocar `blog-approve` ni el gate humano de Dani (INFRA-190/193): ningún borrador pasa a `main` sin su aprobación; no hay autopublicación.
- No anunciar cocina interna (agentes, roles, tooling propio): solo productos para público externo.
- Contratos de veredicto.js y `data/verdicts/*.jsonl` (SC-1536) no se renombran ni cambian de forma: se consumen tal cual.
- El timer `blog-daily` se reactiva solo cuando INFRA-222 e INFRA-224 estén desplegadas; hasta entonces permanece apagado.
- Sin decisión de arquitectura ni secretos nuevos.

## Trabajo reciente (24 h)
- 03-10 06:55 UTC: el perfil default de Hermes dejó `blog-daily.timer` INACTIVE tras dos borradores rechazados; `state.json`: status `rejected`, tema "dos agentes deciden si algo de casa es vendible" (cocina interna).
- `blog-daily.py` (desplegado en ~/.local/libexec/x86-host-runtime/) no menciona veredicto/finance/marketing (grep = 0): la fontanería del criterio nuevo no existe (INFRA-222/224).
- 01-10: SC-1536 Done; `node ~/src/company-roles/bin/veredicto.js --validar` → `ok: 6 verdict(s) valid`.
- INFRA-220 sin enlaces; sus 5 historias (creadas 01-10) no están enlazadas a la épica: trabajo del CTO, enlazarlas con EPIC_LINK.

## Diseño
Diseñador: no — no hay interfaz nueva; la bandeja de aprobación ya existe en INFRA-190

## Historias previstas
Orden: 221 → 222 → 224 → 223 → 225. Todas existen en To Do; el CTO las enlaza a la épica (EPIC_LINK) antes de lanzarlas.
1. INFRA-221 · S1 política de contenido en k8s-blog-pocharlies · dueño: developer · necesita: criterio del ticket (producto de algo construido, público externo, exclusiones); sin dependencias. Cubre C1.
2. INFRA-222 · S2 el turno propone candidato y pide veredicto · dueño: developer · necesita: S1 (política) y veredicto.js de SC-1536. Toca también `x86-host-runtime-pocharlies` (`blog-daily.py`), además del blog. Cubre C2, C5.
3. INFRA-224 · S4 registro vivo de candidatos · dueño: developer · necesita: S2 (formato del candidato y del veredicto). Cubre C3, C8.
4. INFRA-223 · S3 verificación de afirmaciones · dueño: developer · necesita: S2 y S4 (qué es una afirmación y dónde se anota). Cubre C4.
5. INFRA-225 · S5 primera entrada publicada · dueño: writer · necesita: S1–S4 desplegadas y el timer reactivado (C7); la aprobación de Dani va por el gate existente. Cubre C6, C7.

## Tamaño
M

## Dificultad
Dificultad: media — funcionalidad nueva sobre flujos existentes (blog-daily.py y veredicto.js) en repos que ya conocemos, sin decisión de arquitectura ni secretos nuevos; reactivar un timer de usuario no es infraestructura delicada
