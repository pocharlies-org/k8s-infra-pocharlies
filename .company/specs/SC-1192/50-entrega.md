Rol: devops · Fecha: 2026-09-19 · Sesión: 0198H5UaQXU6rw7thqvVNebV · Estado: LISTO

# Entrega SC-1192 — sso-chain sobre el set de control (H2 de SC-702)

## Que se ha hecho

En los 4 IngressRoute del backend dashboard (dgx y hermana s3, lan y edge), dos routes nuevas de mayor priority que la bypass (400 y 350 > 300/200), con las mismas franjas ClientIP de la bypass que protegen y middlewares `[dgx-strip-identity-headers, sso-chain@keycloak]`:

- prio 400, set completo (todos los metodos): PathPrefix de /api/company, /api/litellm/keys, /api/litellm/config, /api/messages, /api/autoreply + /api/claude-sessions y /api/email/state (AMPLIACION del ruling del CTO, censo cerrado 19-09: sin consumidores no interactivos).
- prio 350, split por metodo `Method(POST)` (GET queda abierto en la bypass): PathPrefix /api/cluster/apply; PathRegexp `^/api/cluster/k8s/[^/]+/[^/]+/[^/]+/(scale|restart)$`; PathRegexp `^/api/cluster/argocd/[^/]+/(sync|rollback)$` (refresh deliberadamente fuera, no esta en el set); Path exacto /api/compute/mode.

Sin tocar: lecturas de telemetria (GET /api/cluster/state, GET /api/compute/mode, /api/services), UI estatica, /healthz (siguen en la bypass); route /openchamber prio-300 de edge intacta (la nueva cobertura queda por encima en priority, paths disjuntos); escrituras fuera del set (docker/{action}, argocd refresh, llm/resident-profile, compute rtx-resident, PUT compute/batch) NO cubiertas, segun la historia; sso-chain, oauth2-proxy, Keycloak y el backend dgx-infra, sin tocar.

El H1 (saneado de cabeceras, SC-1191) va en la misma PR y aterriza en el mismo sync; la cadena es strip-then-sso-chain en toda route protegida.

## PR

https://github.com/pocharlies-org/k8s-infra-pocharlies/pull/149 — rama `fix/sc-702-bypass-sso`, contra `main`.

## Como verificarlo (estructural, pre-merge — medido, no hipotesis)

Comparando el manifiesto del PR contra los 4 objetos vivos (volcados kubectl previos):

- Las routes vivas preexistentes se conservan verbatim (match/priority/services); unica diferencia, los middlewares anadidos y las routes 400/350 nuevas.
- Las routes prio 400 contienen los 7 PathPrefix del set (incluida la ampliacion); las prio 350 contienen exactamente las escrituras del set con Method(POST) y ninguna de las excluidas (refresh, docker, resident-profile, batch).
- Criterios 1-7 (baterias de sondas sin sesion, con cookie SSO, split GET/POST, no-regresion) en vivo post-deploy: qa, 70-qa.md.
- Criterio 8: post-merge, Synced y vivo==repo.

## Checklist

- [x] Mecanica: routes 400/350 con sso-chain sobre las bypass, split por Method (manifiesto vs vivos)
- [ ] Criterios 1-7: sondas en vivo post-deploy (qa)
- [ ] Criterio 8: merge + Synced + vivo==repo (post-merge)

## Desviaciones / notas

- AMPLIACION: al escribir el manifiesto, la descripcion de SC-1192 seguia listando /api/claude-sessions y /api/email/state como "fuera de alcance"; el ruling del CTO con censo cerrado (19-09) los mete en el set y el coordinador lo confirmo, asi que ENTRAN en la cobertura. Si pm no llega a actualizar la descripcion, qa lo juzgara por el ruling, no por el texto viejo.
- La transicion a In Progress la bloquea el guard: falta `00-spec.md` en la historia (fichero del tech-lead).
- Agente: agent-a28312dc08474a3ca (devops).
