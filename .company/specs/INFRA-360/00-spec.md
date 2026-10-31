Rol: pm · Fecha: 2026-10-01T17:03:11Z · Sesión: epica-infra-360 · Estado: CERRADA

## Objetivo
Cazar al escritor que reescribía los config.yaml de los perfiles de Hermes (show_reasoning volvía a true solo) y arreglar la raíz para que los ajustes manuales de Dani sobrevivan a cualquier resincronización.
Repo: k8s-openclaw-qwen36-pocharlies

## Cierre
- Caso: ENTREGADA — los tres criterios se cumplen ya en producción, ejecutados por la propia compañía (tech-lead b2f4d310 con sre/developer/devops/qa) entre el 30-09 21:42 y el 01-10.
- Motivo: la épica quedó lista para validación funcional del pm el 30-09 23:13 (comentarios de progreso) y el tablero cuadrado; no hay trabajo pendiente que planificar.
- Evidencia: 80-validacion-pm.md (adjunto, una fila por criterio con comando y salida medidos el 01-10); PR #460 mergeada (c819456) y desplegada (ArgoCD hermes Synced/Healthy); nota-sre-escritor.md en INFRA-361; 70-qa.md PASA en INFRA-363.

## Trabajo reciente (24 h)
- 01-10 15:35 UTC: pod hermes-gateway reiniciado (deploy nuevo, PRs #471/#472 mergeadas después de #460); tras el arranque, los 13 config.yaml de perfil y el global siguen con show_reasoning: false (medido: true=0 false=13). El arreglo aguanta un ciclo real de arranque+seed.
- 30-09 20:03 UTC: PR #460 (k8s-openclaw-qwen36-pocharlies, deploy/prod) mergeada — el seed trata display como USER_OWNED: solo siembra la clave si falta, nunca pisa el valor vivo.

## Historias previstas
Ninguna — cerradas y entregadas: INFRA-361 (sre, escritor), INFRA-362 (developer, seed idempotente, PR #460), INFRA-363 (qa, prueba de supervivencia en vivo).
