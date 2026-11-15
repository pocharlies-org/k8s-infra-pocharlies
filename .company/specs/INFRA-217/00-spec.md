Rol: pm · Fecha: 2026-09-22T05:28:39Z · Sesión: 3bc6219a-8f5f-4ffc-905d-7d9801f8d320 · Estado: LISTO

## Objetivo

Que quien tría un incidente en Keep (keep.e-dani.com) vea y abra el análisis de Aurora en un clic, y que la ficha de Aurora enlace de vuelta al incidente de Keep. Y que la degradación silenciosa de Aurora (el mes de 403 con `aurorasvc-llm`, 174 incidentes sin RCA) sea imposible de repetir: una alerta de cobertura visible desde el propio tablero.

No la duplica ninguna épica abierta. Nota de alcance: la épica habla de "campo enriquecido" sin decidir el mecanismo — ése es el trabajo de la historia H1 (architect), no una pregunta para Dani.

Repo: k8s-observability-pocharlies

(Tronco `main`, verificado 22-09: las Applications `keep` y `aurora` leen sus values de este repo vía `$values` — chart keep 0.1.96 y chart aurora-oss 1.2.16. El código de Aurora, si hay que tocarlo, vive en el fork `pocharlies-org` de las imágenes `ghcr.io/pocharlies-org/aurora-{server,frontend}:sha-e35121ae...`, repo que no está en ~/k8s: el CTO abre el checkout si H1 lo dictamina.)

## Criterios de aceptación

- [ ] **C1 — Keep → Aurora en un clic.** Un incidente crítico de Keep despachado a Aurora muestra en su vista de Keep un enlace que abre la ficha de Aurora de ese análisis. Verificación (qa/sre, navegador autenticado — ambas UIs están tras SSO oauth2-proxy `/edani-admins`+`/edani-operators`, un curl anónimo devuelve 302 y eso NO es evidencia): abrir `https://keep.e-dani.com/incidents/<keep_id>` de un incidente crítico real, screenshot con el enlace, y comprobar que el uuid del enlace existe en Aurora:
  ```
  kubectl -n databases exec postgres-shared-rw -- psql -U aurora -d aurora -c \
    "SELECT id, aurora_status FROM incidents WHERE id = '<uuid-del-enlace>'"
  ```
  Salida esperada: 1 fila, `aurora_status = complete`. El enlace tiene la forma `https://aurora.e-dani.com/incidents/<uuid>` (formato ya usado por el workflow `aurora-report-back`, keep/values.yaml:781).

- [ ] **C2 — Aurora → Keep de vuelta.** La ficha `https://aurora.e-dani.com/incidents/<uuid>` muestra enlace a `https://keep.e-dani.com/incidents/<keep_id>` (formato ya usado en el payload de dispatch, keep/values.yaml:892). Verificación: screenshot de la ficha de Aurora con el enlace, y que el `keep_id` del enlace es el incidente Keep cuyo fingerprint coincide con el de Aurora:
  ```
  kubectl -n databases exec postgres-shared-rw -- psql -U aurora -d aurora -c \
    "SELECT keep_incident_id FROM keep_bridge.aurora_dispatches \
      WHERE fingerprint = (SELECT alert_metadata->>'fingerprint' FROM incidents WHERE id = '<uuid>')"
  ```
  Salida esperada: 1 fila con el uuid que aparece en el enlace de la UI. (Si H1 elige otro almacén para el backlink, el comando se actualiza en el contrato de C4 y esta fila cita el contrato — el veredicto se da contra lo documentado, no contra esta línea.)

- [ ] **C3 — Alerta de cobertura (regresión del 403 silenciosa imposible).** Existe una comprobación periódica que dispara (incidente en el tablero de Keep + Telegram, tema 1248) si incidentes despachados a Aurora no tienen análisis completo en la ventana acordada (N = 4 h para la lane crítica, decisión PM; H1 puede ajustarla con razón escrita). Dos evidencias obligatorias:
  1. **Detecta el mes muerto**: la misma consulta que usa la alerta, corrida sobre la ventana del incidente, devuelve los RCA fallidos:
     ```
     kubectl -n databases exec postgres-shared-rw -- psql -U aurora -d aurora -c \
       "SELECT count(*) FROM incidents WHERE <col-fecha-creacion> BETWEEN '2026-08-26' AND '2026-09-21' \
         AND aurora_status IS DISTINCT FROM 'complete'"
     ```
     Salida esperada: `>= 100` (la auditoría del 21-09 contó 174). Nota: el nombre exacto de la columna de creación se lee con `\d incidents` antes de correrla — la auditoría no lo fijó.
  2. **Verde hoy y dispara en sintético**: sobre `now() - interval '24 hours'` la misma consulta devuelve `0`, y tras insertar un dispatch sintético sin análisis más antiguo que la ventana (prueba qa/sre con limpieza posterior), la alerta aparece en el tablero y se resuelve al limpiar. Evidencia: dos screenshots + el SQL de insert/cleanup pegado en `70-qa.md`.

- [ ] **C4 — Contrato documentado en el repo GitOps.** En el tronco de k8s-observability-pocharlies existe `docs/keep-aurora-contract.md` que fija: `fingerprint` como clave de correlación (Aurora lo guarda en `incidents.alert_metadata->>'fingerprint'`), las dos tablas puente `keep_bridge.reported` y `keep_bridge.aurora_dispatches` (fingerprint PK, keep_incident_id uuid) con su DDL bootstrap manual, los dos formatos de deep-link, la lane crítica-only del dispatch, y el mecanismo elegido de enlace (C1/C2) con el almacén del backlink. Verificación:
  ```
  cd ~/k8s/k8s-observability-pocharlies && git fetch -q origin main && \
  git show origin/main:docs/keep-aurora-contract.md | grep -cE 'aurora_dispatches|keep_bridge.reported|fingerprint|/incidents/'
  ```
  Salida esperada: `>= 4`.

- [ ] **C5 — No se rompe la lane existente.** Los workflows `aurora-investigate` y `aurora-report-back` (y su test de contrato) siguen intactos tras los cambios:
  ```
  cd ~/k8s/k8s-observability-pocharlies && git checkout -q main && git pull -q && \
  python3 -m unittest discover -s tests -v
  ```
  Salida esperada: `OK`, con `test_keep_aurora_dispatch_contract` en verde. Y desplegado: `kubectl get app -n argocd keep aurora` → `Synced` **y** el enlace de C1 funcionando sobre un incidente real (ArgoCD verde no prueba la entrega — la evidencia es C1/C2/C3).

## Restricciones

- No romper `aurora-investigate`/`aurora-report-back`: la cabecera de keep/values.yaml documenta que este workflow tumbó el sistema de alertas entero (06/07–08-2026) por reclamar y leer en el mismo step (PostgresProvider `_query` no hace commit; `_notify` sí). Cualquier SQL nuevo respeta esa separación y pasa C5.
- El esquema `keep_bridge` lo crea una persona a mano (DDL de bootstrap documentado en keep/values.yaml); si el mecanismo añade tablas/columnas, van al contrato de C4 y se aplican a mano contra la BBDD `aurora` de postgres-shared.
- Versiones pineadas: chart keep 0.1.96, Keep 0.52.1, chart aurora-oss 1.2.16, imágenes por sha. El upgrade a 1.3.0 solo si H1 escribe por qué lo necesita; no es premisa.
- Dispatch crítico-only: la alerta de cobertura aplica a la lane despachada; no ensancharla sin cambiar el test de contrato.
- Ambas UIs tras SSO: las evidencias de UI son de navegador autenticado, nunca curl anónimo.
- **Fuera de alcance (decisión PM, no pregunta a Dani):** reprocesar los 174 incidentes históricos (valor pasado, saturaría el LLM); backup de weaviate 50Gi + redis 5Gi en local-path de sauvage (merece épica propia de backups, nombrada aquí, no creada).
- GitOps: PR contra `main` de k8s-observability-pocharlies, nunca push directo; repo activo (INFRA-214 fusionando #39–#41 esta semana) — rebase antes del PR.

## Trabajo reciente (24 h)

- 21-09, sesión `dd17daf2` (cwd ~/k8s/dgx-infra): auditoría de Aurora — la key LiteLLM `aurorasvc-llm` perdió `tooling` del allowlist → 403 en todos los LLM calls desde ~26-08 → 174 incidentes con "Summary generation failed" y 0 RCA findings; allowlist restaurado y verificado 200 en la misma sesión. Es la premisa de esta épica; C3 nace de aquí.
- 22-09, sesión `5183c22f` (misma épica, fase plan): murió sin adjuntar spec tras el reconocimiento. Sus medidas, verificadas y usadas aquí: deep-link `aurora.e-dani.com/incidents/<uuid>`, tablas `keep_bridge.{reported,aurora_dispatches}`, dispatch crítico-only con `keep_url` ya en el payload, apps keep/aurora Synced, UIs 302 por SSO. No hay sesión viva en esto (radar 22-09: 0 vivas).
- Tronco de k8s-observability-pocharlies: #39/#40/#41 (reglas INFRA-214) fusionados en horas — el repo está vivo, rebase obligatorio.

## Historias previstas

- **H1 — Architect**: verificar mecanismo y escribir `docs/keep-aurora-contract.md` (C4): si Keep 0.52.1 soporta campo enriquecido visible en la vista de incidente vs alternativa; si Aurora persiste/muestra el `keep_url` que ya recibe en el dispatch o hay que tocar el fork; deep-links del chart 1.2.16; valorar 1.3.0 solo si hace falta. Dueño: architect. Bloquea H2–H4.
- **H2 — DevOps**: enlace Keep → Aurora desplegado por GitOps y que sobrevive a reinicios (C1). Dueño: devops. Depende de H1.
- **H3 — DevOps**: backlink Aurora → Keep (config, o fork + bump de imagen si H1 lo dictamina) (C2). Dueño: devops. Depende de H1.
- **H4 — DevOps**: alerta de cobertura RCA con la ventana acordada, disparando al tablero + Telegram (C3). Dueño: devops. Depende de H1.
- **H5 — SRE**: validación end-to-end con incidente de prueba real (disparar → enlace → RCA), revisión de calidad de los RCA generados desde el fix de la key, y cierre de la evidencia de cobertura (C1–C5). Dueño: sre. Depende de H2, H3, H4.

Orden: H1 → (H2 ∥ H3 ∥ H4) → H5. Razón: sin el contrato de H1, H2/H3/H4 construirían sobre un mecanismo supuesto — y el histórico de este repo (caída de julio) dice que suponer aquí cuesta caro.

## Tamaño

M. Cinco historias, un repo GitOps (más el checkout del fork de Aurora solo si H1 lo dictamina), tres roles. No es L porque la plomería ya existe y está verificada (dispatch, report-back, tablas puente, deep-links): falta el enlace visible y la alerta, no un sistema.
