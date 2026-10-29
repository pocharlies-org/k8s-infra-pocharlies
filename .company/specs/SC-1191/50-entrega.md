Rol: devops · Fecha: 2026-09-19 · Sesión: 0198H5UaQXU6rw7thqvVNebV · Estado: LISTO

# Entrega SC-1191 — saneado de cabeceras de identidad (H1 de SC-702)

## Que se ha hecho

- Middleware nuevo `dgx-strip-identity-headers` (tipo headers, `customRequestHeaders` a cadena vacia) con las 7 cabeceras obligatorias: X-Auth-Request-User, X-Auth-Request-Email, X-Auth-Request-Groups, X-Auth-Request-Preferred-Username, X-Forwarded-User, X-Forwarded-Email, X-Forwarded-Groups. Definido una copia por instancia Traefik (ns `traefik-lan` y ns `traefik-edge`, patron del precedente `sauvage-bot-strip-auth-headers`, duplicado en ambos namespaces).
- Enganchado a TODAS las routes de los 4 IngressRoute (lan-dgx-dashboard-public-host, lan-dgx-s3-media-public-host, edge-dgx-dashboard-public, edge-dgx-s3-media-public), incluida la /openchamber prio-300 de edge, y ANTES de sso-chain en toda route que lo lleva.
- En la misma PR va SC-1192 (H2, routes prio 400/350 con sso-chain sobre el set de control); ver 50-entrega.md de SC-1192.

## PR

https://github.com/pocharlies-org/k8s-infra-pocharlies/pull/149 — rama `fix/sc-702-bypass-sso`, contra `main` (tronco que lee ArgoCD app `k8s-infra`, verificado con kubectl). Ficheros: `networking/traefik-lan/dgx-public-host-lan.yaml`, `networking/traefik-edge/dgx-dashboard-public.yaml`, `networking/traefik-edge/s3-media-public.yaml` (el bloque edge-s3 vive en este ultimo, no en dgx-dashboard-public.yaml).

## Como verificarlo (estructural, pre-merge — medido, no hipotesis)

Script de comparacion contra los 4 objetos vivos (`kubectl get -o yaml` volcados antes del cambio):

- Criterio 1 (middleware con las 7 claves a ""): CUMPLE en el manifiesto; verificable en vivo post-sync con el comando jq de la historia.
- Criterio 2 (strip en todas las routes, antes de sso-chain): CUMPLE — comprobado route a route en los 4 objetos del manifiesto del PR; las routes vivas preexistentes se conservan intactas en match/priority/services (unica diferencia: el middleware anadido).
- Criterios 3-8 (sondas en vivo LAN/borde/s3, forja, no-regresion): post-deploy, corresponden a qa (70-qa.md).
- Criterio 9 (GitOps cerrado): post-merge; `kubectl get application -n argocd k8s-infra -o jsonpath='{.status.sync.status}'` = Synced y vivo==repo.

## Checklist

- [x] Criterio 1: Middleware con las 7 claves vacias (en el manifiesto del PR)
- [x] Criterio 2: enganchado en todas las routes, antes de sso-chain (manifiesto vs vivos)
- [ ] Criterios 3-8: sondas en vivo post-deploy (qa)
- [ ] Criterio 9: merge + Synced + vivo==repo (post-merge)

## Desviaciones / notas

- La transicion a In Progress la bloquea el guard: la historia no tiene `00-spec.md` adjunto (fichero propio del tech-lead; los criterios estan en la descripcion). El trabajo se hizo contra esos criterios, que el CTO declaro especificacion.
- Agente: agent-a28312dc08474a3ca (devops).
