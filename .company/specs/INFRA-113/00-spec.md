Rol: pm · Fecha: 2026-09-19T12:40:56Z · Sesión: 0b151797-4fa8-45f3-85e9-58b3789c6d72 · Estado: LISTO

# INFRA-113 — AgentGateway: las rutas READ autentican pero no autorizan

## Objetivo
Que ninguna ruta del AgentGateway conceda `initialize` / `tools/list` a un principal sin el rol de realm de esa ruta: cada ruta READ exige su `agentgateway-read:<ruta>` y el aislamiento cruzado queda verificado en vivo. **Esta épica ya fue planificada y ejecutada en parte** (ciclo CTO `ffdafd89-33ae-45f3-85e9-58b3789c6d72`, historias numeradas como "INFRA-23-H*"): quedan el cierre del ciclo en curso (ruta /studio) y la cola de rutas restantes hasta la auditoría final.

Repo: k8s-agentgateway-pocharlies (trunk `main`, lo lee ArgoCD). Nota: INFRA-187 (TTL de token en Keycloak) vive en k8s-infra/keycloak GitOps y ya está entregada (Sign-off); no abre trabajo nuevo en otro repo.

## Estado de partida (medido 2026-09-19 ~12:35Z, no de memoria)
- **26 historias hijas ya existen** (INFRA-135…159 + INFRA-187). No crear historias nuevas: la cola está hecha y ordenada (orden R7 en el título de cada una).
- **Hecho y verificado en vivo**: 5 de las 6 rutas del hueco original ya tienen `require` de rol en el ConfigMap desplegado de `agentgateway` — synapse, picqer, shopify-admin, social, atlassian (PRs #76, #84, #85, #86, #87 en `main`). Historias Done: INFRA-138/139/140/141.
- **En curso**: /studio — PR #88 abierto hoy 11:17Z, CI en verde (validate + review), **sin fusionar**; INFRA-143 en Sign-off.
- **En Sign-off, pendientes del veredicto funcional del PM**: INFRA-135 (retención de logs), INFRA-136 (roles + grants GitOps), INFRA-137 (apagar fullScopeAllowed), INFRA-142, INFRA-143, INFRA-187.
- **En Backlog**: INFRA-144…158 (enforce de las rutas 7–21: synapse-tools, shopify, brain, workspace, gsc, merchant, offers, analytics, skirmshop-plugins-read, dgx-control, weight, image, stt, tts, y el no-op de /synapse-sre) + INFRA-159 (auditoría de cobertura final de las 29 rutas).
- **Inconsistencia de estado**: la épica está en To Do con 4 hijos Done — el CTO la adopta (In Progress) y trabaja la cola restante.
- **Premisa a diagnosticar primero**: la aplicación ArgoCD `agentgateway-mcp` está **OutOfSync / Degraded** (medido hoy). En el ciclo anterior el CTO ponía el merge solo con la app Synced/Healthy; no fusionar nada hasta diagnosticar y restaurar.
- **Peligro de repo**: el checkout principal de `~/k8s/k8s-agentgateway-pocharlies` está en la rama `o3b-toolsmcp` (199 behind) con cambios **ajenos** sin commitear sobre `k8s/base/agentgateway-config.yaml`. Trabajar desde rama limpia sobre `origin/main`; no tocar ese working tree.

## Criterios de aceptación
- [ ] **C1 — /studio autoriza en vivo** (cierra INFRA-143: merge del PR #88 + deploy + verificación).
  Comando: `kubectl -n agentgateway get cm agentgateway-config -o yaml | grep -c 'agentgateway-read:studio'`
  Esperada: `1` (hoy da `0`).
- [ ] **C2 — las 6 rutas del hueco original autorizan todas en vivo.**
  Comando: `for r in synapse shopify-admin atlassian studio social picqer; do kubectl -n agentgateway get cm agentgateway-config -o yaml | grep -q "agentgateway-read:$r" && echo "$r OK" || echo "$r FALTA"; done`
  Esperada: 6 líneas `OK`, cero `FALTA`.
- [ ] **C3 — el smoke cruzado de aislamiento niega en las 6 rutas.** Con un JWT firmado sin ningún rol de realm (el fixture del script), las seis rutas devuelven 403 en `initialize` y `tools/list` sin marcar el backend.
  Comando: `cd ~/k8s/k8s-agentgateway-pocharlies && git worktree add /tmp/infra113 origin/main && cd /tmp/infra113 && python3 scripts/test-gateway-authz.py`
  Esperada: salida del script con las 6 rutas en 403 (`authorization failed`) — el script ya existe y prueba contra la imagen pinada y los overlays renderizados. (Si el matrix del script no cubre aún las 6 rutas READ, la historia de cierre amplía el matrix; el criterio es la salida, no el script.)
- [ ] **C4 — el gate de despliegue sano tras cada merge.**
  Comando: `kubectl -n argocd get application agentgateway-mcp -o jsonpath='{.status.syncStatus.status} {.status.health.status}'`
  Esperada: `Synced Healthy` (hoy: `OutOfSync Degraded`).
- [ ] **C5 — cola restante completada o aplazada con nombre.** Las historias Backlog INFRA-144…158 terminan en Done, o cada una queda aplazada con el motivo escrito en su 50-entrega/00-spec por decisión del PM (no se cierra la épica "casi": o ejecutadas, o aplazadas explícitamente con criterio de cuándo se retoman).
  Comando: `jira_search` JQL `parent = INFRA-113 AND status != Done` sobre las 144…158.
  Esperada: vacío, o solo aplazamientos nombrados.
- [ ] **C6 — auditoría de cobertura final entregada** (INFRA-159): las 29 rutas del gateway con `require` efectivo o patrón correcto demostrado, con evidencia pegada en la historia.
  Comando: `jira_search` JQL `key = INFRA-159 AND status = Done`, más el informe adjunto de la historia.
  Esperada: Done con `70-qa.md` Estado: PASA.
- [ ] **C7 — cero hijos abiertos al cerrar.**
  Comando: `jira_search` JQL `parent = INFRA-113 AND status != Done`.
  Esperada: vacío (los Sign-off cerrados por el PM con su veredicto, incluido INFRA-187).

## Restricciones
- Cambio BREAKING sobre superficie compartida: el patrón es el ya aprobado y en producción — `policies.authorization.rules` con `require` del rol `agentgateway-read:<ruta>`, copiado de /cto-office y de los PRs #76/#84/#85/#86/#87. Entrada nueva junto a la vieja; nunca editar contratos establecidos (repo con CONTRACTS: trailer `Contract-Change:` si algo roza un id registrado).
- Grants solo vía la matriz GitOps de INFRA-136 (patrón PostSync sobre Keycloak); nunca conceder roles a mano.
- Antes de cada enforce: verificar con los logs (retención de INFRA-135) qué principals reales consumen la ruta y que tienen el rol concedido — el ciclo anterior exigía ventana de tráfico real por ruta (regla R1); no romper consumidores vivos.
- Merge solo con `agentgateway-mcp` Synced/Healthy y CI verde; el merge lo pulsa el CTO.
- No tocar el working tree sucio `o3b-toolsmcp` del checkout principal.
- FUERA DE ALCANCE: el cutover de escritura de /cto-office (CTO_OFFICE_WRITE) — pertenece a SC-100.
- Sin dinero, sin borrar nada irreversible.

## Trabajo reciente (24 h)
- 2026-09-19 11:17Z — PR #88 (/studio, INFRA-143) abierto, CI verde, sin fusionar. Es el siguiente golpe del CTO.
- 2026-09-19 ~12:30Z — sesión CTO rancia `ffdafd89` sigue viva por mensajes: su devops terminó el PR de studio; el tech-lead `agent-a2a7395e2f29da979` es reanudable. **No duplicar su trabajo**: la cola de esta spec es exactamente la suya, reanudable o de un CTO nuevo sobre el tablero.
- 2026-09-19 ~12:35Z — medido: CM en vivo con 5/6 rutas del hueco enforced; app `agentgateway-mcp` OutOfSync/Degraded (bloqueante del merge, diagnosticar primero).
- 2026-09-19 07:05Z — QA revisó el PR #85 (/atlassian) — cerrado ya en main; nada pendiente de ahí.
- 2026-09-17 — el CTO anterior se bloqueó esperando la ventana de 72 h de logs (regla R1) y el supervisor lo reanudó; hoy la retención (INFRA-135) está entregada en Sign-off: la premisa del bloqueo ya no existe.
- Sesiones vivas de k8s-infra (Vault→1Password, Longhorn, hace 21 h): no tocan esta épica salvo INFRA-187, ya en Sign-off.

## Historias previstas
No se crean: existen las 26. Cola que le queda al CTO, en orden:
1. Diagnosticar y restaurar `agentgateway-mcp` a Synced/Healthy (devops, prerrequisito de todo merge).
2. INFRA-143 /studio: merge del PR #88 + verificación en vivo (devops + qa) → cierre PM.
3. Cierre funcional (pm) de los Sign-off: INFRA-135, 136, 137, 142, 187.
4. Cola R7 de enforce de rutas restantes: INFRA-144…158 (devops, una por PR en el orden del título; qa verifica cada una; pm cierra) — o aplazamiento explícito con motivo.
5. INFRA-159 auditoría de cobertura final (qa/pm).
6. Cierre de épica (pm): C1–C7 con evidencia.

## Tamaño
L — pero ya ejecutada en ~40 %: el patrón está probado y en producción 5 veces; lo restante es repetir un mecánico conocido 15 veces más el cierre. Encaja en 1–2 ciclos de CTO (el ciclo actual puede cerrarse con C1–C4 y los Sign-off; la cola R7 y la auditoría en el siguiente).
