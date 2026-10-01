# ARCHITECTURE.md — k8s-infra-pocharlies

> Infraestructura del cluster k3s: networking (Traefik, MetalLB, cert-manager, DNS), plataforma (Harbor, Keycloak,
> Kyverno, CNPG…), Postgres compartido, Ansible/Terraform del plan KS-5 y runbooks. Una de las raíces más
> consumidas del estate. Escrito por `architect` (SC-1426).

## 1. Clientes y versiones

Sin clientes de usuario. Despliega **4 Applications** de ArgoCD (todas desde este repo, tronco **`main`**, sync
automático `prune: false`, `selfHeal: true`):

| Application | fuente | versión | notas |
|---|---|---|---|
| `k8s-infra` | path `.` (kustomize raíz: cert-manager issuers, CoreDNS, metallb ippool, IngressRoutes de `traefik-lan` y `traefik-edge`, networkpolicies…) | `origin/main` = 5d52ca2 | ~49+ recursos listados en `kustomization.yaml` |
| `postgres-shared` | path `databases/postgres-shared` | CNPG | BD compartida (litellm, langfuse, firecrawl, intake…) |
| `traefik-edge` | multi-source: chart `traefik` 40.2.0 (`traefik.github.io/charts`) + values de este repo | 40.2.0 | DaemonSet hostNetwork en sauvage/ks5 |
| `traefik-lan` | ídem, chart `traefik` 40.2.0 | 40.2.0 | LAN `192.168.50.240` |

## 2. Dependencias, en ambos sentidos

- **Depende de** — `k8s-gitops-pocharlies` (registra las Applications y su CI reutilizable `reusable-ci.yml@96ec4d91…`),
  charts upstream, Cloudflare/OVH (DNS y servidores KS-5), Tailscale, Vault/1Password (ExternalSecrets).
- **Dependen de él** — prácticamente todo: cada host público/LAN nuevo necesita su IngressRoute aquí
  (`networking/traefik-edge/*-public.yaml`, `networking/traefik-lan/*-lan.yaml`; el DaemonSet del edge solo observa un
  allowlist de namespaces, por eso rutas como `langfuse-public.yaml` viven aquí); `k8s-adguard-pocharlies` (rewrites DNS
  de cada host nuevo); Postgres compartido; `platform/keycloak-next` (`ROLES.yaml`, registro de roles consumido por
  AgentGateway).
- Contratos: `platform/keycloak-next/ROLES.yaml` y los `tests/test_*_contract.py` (33 ficheros) fijan roles de
  AgentGateway, firewall del edge, external-dns, Velero…

## 3. Stack

| pieza | versión | para qué | no se usa en su lugar |
|---|---|---|---|
| Traefik (chart) | 40.2.0 | edge + LAN | nginx (retirado) |
| MetalLB, cert-manager, external-dns, external-secrets, Kyverno, Velero, Harbor, CNPG, Keycloak (`keycloak-next`) | por `platform/*`, `networking/*` | plataforma | — |
| Ansible + Terraform OVH + `scripts/ovh_install.py` | — | KS-5 (3 control-plane) | scripts a mano |
| Python 3.12 + PyYAML 6.0.2 | CI | tests de contrato | — |

## 4. Componentes compartidos

| concepto | pieza canónica | ruta | quién la usa |
|---|---|---|---|
| Rutas públicas del edge | `networking/traefik-edge/<app>-public.yaml` | ídem | todas las apps públicas |
| Rutas LAN | `networking/traefik-lan/` (`canonical-hosts-lan.yaml`) | ídem | toda la LAN (+ AdGuard) |
| Postgres compartido | `databases/postgres-shared` | ídem | litellm, langfuse, firecrawl, document-intake, auto-reply |
| Catálogo de roles Keycloak | `platform/keycloak-next/ROLES.yaml` | ídem | AgentGateway |
| Runbooks | `docs/runbook*.md`, `docs/disaster-recovery.md` | `docs/` | operación |

## 5. Cómo se construye aquí

Host nuevo = IngressRoute en `networking/traefik-{edge,lan}/` + línea en `kustomization.yaml` + rewrite en AdGuard + (edge)
`wildcard-cert`/TLS store. **Un cambio de naturaleza destructiva** (KS-5, OVH reinstall) exige las confirmaciones
explícitas del README (`CONFIRM_OVH_REINSTALL=…`) y `docs/runbook.md`. `docs/architecture.md` describe el estado
objetivo KS-5; el estado actual lo manda el cluster.

## 6. Tests y validaciones

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v   # 33 ficheros de contrato
python3 -m unittest discover -s tests -p 'test_keycloak_rbac_*.py' -v
kustomize build .                                           # reusable-ci
```
Nº de casos: **pendiente de medir**.

## 7. CI/CD y despliegue

- `ci.yml` (`arc-k8s`): `reusable-ci.yml@96ec4d91…` + jobs de contrato (reconciliador de roles Keycloak con imagen fijada,
  auditor RBAC, registro `ROLES.yaml`, operabilidad Velero, propiedad de external-dns…), `duplicados.yml`,
  `pr-review.yml`, `release.yml`.
- Despliegue: merge a `main` → ArgoCD (`k8s-infra`, `postgres-shared`, `traefik-*`). **Validación en producción**: probar el
  host nuevo extremo a extremo (`curl -I https://<host>` por edge y por LAN) y `kubectl get applications -n argocd`;
  Synced ≠ funcionando. Pendiente de ejecutar.

## 8. Decisiones y trampas

- `README`/`docs/architecture.md` aún dicen k3s v1.32.5 y «ubuntu único control-plane»: el cluster real tiene `ks5-cp-1/2/3`
  (README desfasado).
- El edge no ve namespaces fuera de su allowlist: una ruta pública «en el namespace de la app» no funciona.
- `prune: false` en `k8s-infra`: quitar un fichero de `kustomization.yaml` no borra el recurso en el cluster.
- `docs/runbook-cloudflare-lan-record-budget.md`: límite de registros LAN en Cloudflare; leer antes de añadir hosts.

Última verificación contra el código: 2026-10-01 · 5d52ca2 (origin/main)
