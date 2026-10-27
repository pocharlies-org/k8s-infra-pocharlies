# Principals of realm `edani` (INFRA-219 C4)

Every user and service account of the realm `edani`, each with a named owner
(a person or a role of the company), the source that owner is based on, its
purpose, the realm roles it holds and its status. The contract is the single
json block at the end of this file; `scripts/verify-principals.py` reads it
with `kc_rbac.load_json_block` and compares it with the live realm. The table
below is a reading aid generated from that block — when they disagree, the
block wins.

Measured against the live realm on 2026-09-24: 9 users + 10 service accounts
= **19 principals** (the 16 of 2026-09-23 plus the three OWU-27 clients
`claude-sessions-norol`, `-other`, `-test`, created by admin API outside this
repo). INFRA-250 adds the 20th, `service-account-keycloak-rbac-auditor`,
created by its own PostSync (`keycloak-rbac-auditor-client.yaml`) in the same
sync that ships this entry. INFRA-477 adds the 21st,
`service-account-jarvis-echo`, the client the INFRA-411 session had created
by hand on 2026-10-03 (the process error that made `keycloak-role-drift`
fail): adopted, not recreated, by its own PostSync
(`jarvis-echo-client.yaml`), so its service-account sub keeps matching the
AgentGateway identity bindings approved in k8s-agentgateway-pocharlies#170.

SC-2005 closed the drift of 2026-10-06: measured against the live realm
that day, 12 users + 18 service accounts = **30 principals** — the 21 above
plus the five service accounts of the Hermes secretaria profiles
(`service-account-hermes-secretaria*`, INFRA-494), the Atlassian probe
`service-account-atlassian-mcp-probe` (SC-1834) and the users
`staticduo@gmail.com` (INFRA-383 M1B), `correo@e-dani.com` (SC-1958)
and `qa-sso-test` (INFRA-561), all created outside this repo and
adopted here without being recreated.

INFRA-676 (P4b of INFRA-480) adds the 31st, `service-account-hermes-enviar`,
the client of the Hermes `enviar` plugin — the only identity that sends or
deletes Gmail drafts through AgentGateway. Unlike the entries above it is NOT
adopted: its PostSync (`hermes-enviar-client.yaml`) creates it in the same sync
that ships this entry, so until the PostSync hooks of that sync finish the
catalog names a principal (and two roles) the realm does not have yet, and the
`keycloak-role-drift` runs that fall in that window report it. It clears on the
first run after the hooks, with no action.

SC-2522 adopts the 33rd, `dom.greco@alphalinkcrossfit.com`: a human user the
realm gained on 2026-10-16 at 12:36 UTC through the admin API (self-registration
is off), with no attributes, no realm roles beyond `default-roles-edani` and no
reference in any repo of the platform. No session of the company claims it, so
it enters as `origen-desconocido` under Dani (operador), the way
`daniel.ibanez@cloudblue.com` did. If it turns out to be a stray fixture, its
retirement goes through the CTO as always.

DGX-1218 (PR-2 of epic DGX-1209) adds the 34th and 35th,
`service-account-correo-agente-lectura` and `service-account-correo-ejecutor`,
the read identity and the executor of the Postia case agent. Like
`hermes-enviar` they are NOT adopted: their PostSync
(`correo-agente-clients.yaml`) creates them in the same sync that ships these
entries, and `keycloak-role-drift` reports them until the hooks finish.

## Rules

- **One entry per live principal, and no entry without one.** A new user or
  client lands here (and in the `grantees` of `ROLES.yaml`, at least
  `default-roles-edani`) in the same PR that creates it.
- **`owner` is never empty.** A person (`Dani (operador)`, `Leila`) or a role
  of the company (`DevOps`, `QA`). `source` names the epic, ticket or document
  the owner is based on. With no such source the owner is `Dani (operador)`
  and `flags` carries `origen-desconocido`.
- **`realm_roles` is exactly what `ROLES.yaml` grants the principal**
  (`grantees`, direct grants only). The live grants are checked by
  `verify-role-catalog.py`; this file only mirrors the catalog.
- **`status`** is `activo` or `retirada-propuesta`. A proposed retirement
  carries `retirement_reason`. It is only a proposal: nobody deletes a user or
  a client from the realm without the CTO's decision (INFRA-219 plan). When a
  principal is actually removed, its entry leaves this file and its grantees
  leave `ROLES.yaml` in the same PR.
- `type` is `sa` (then `client` is the Keycloak clientId and the username is
  `service-account-<client>`) or `humano` (`client: null`).

## The two pending principals of SC-100 / SC-320

SC-320 (alias SC-100, cto-office-mcp) left two of the three principals of
criterion 6 of SC-44 without their `cto-office-send` grant: *el usuario main*
and *la SA propia del agente de operaciones*. Both are identified and hold it
today (measured 2026-09-24, `ROLES.yaml`): `me@e-dani.com` and
`service-account-synapse-sre-orchestrator`. Both stay `activo` with an owner.

## Proposed retirements (CTO decision; nothing is deleted)

| principal | reason |
|---|---|
| `qa-sin-rol@e-dani.com` | Fixture of SC-479 / SC-665 (Done); no open criterion uses it (the C5 drift test uses `qa-con-rol`). |
| `service-account-claude-sessions-norol` | Fixture of the OWU-27 live verification (Done); no manifest or reconciler references it. |
| `service-account-claude-sessions-other` | Same, OWU-27 ownership-403 fixture. |
| `service-account-claude-sessions-test` | Same, OWU-27 happy-path fixture; retiring it also changes the grantees of `claude-sessions` and `agentgateway-read/write:claude-sessions`. |

## Inventory

| principal | type | owner | status | purpose |
|---|---|---|---|---|
| `correo@e-dani.com` | humano | Dani (operador) | activo | Cuenta de correo de la org Claude Team E-dani («E-dani Correo»); su login a claude.ai pasa por el SSO de este realm. Sin roles propios. |
| `daniel.ibanez@alphalinkcrossfit.com` | humano | Dani (operador) | activo | Cuenta Google de Dani (Alphalink). SSO del realm y usuario de las sesiones de Claude nacidas del chat (OWU-27). |
| `daniel.ibanez@cloudblue.com` | humano | Dani (operador) (origen-desconocido) | activo | Cuenta Google de trabajo de Dani (CloudBlue); SSO del realm, sin roles propios. |
| `dom.greco@alphalinkcrossfit.com` | humano | Dani (operador) (origen-desconocido) | activo | Usuario de origen desconocido (alta por API de admin el 16-10, SC-2522); sin atributos ni roles propios. |
| `info@e-dani.com` | humano | Dani (operador) | activo | Buzón del negocio (Skirmshop Spain); SSO del realm, grupos edani-operators y skirmbooks-users. |
| `lays84.mv@gmail.com` | humano | Leila | activo | Cuenta Google de Leila; SSO del realm (grupo edani-users) y su buzón en /workspace. |
| `me@e-dani.com` | humano | Dani (operador) | activo | Usuario principal del operador; admin del realm por grupos, cto-office-send para /cto-office y el write global agentgateway-write concedido por OWU-80. |
| `pocharlies@gmail.com` | humano | Dani (operador) | activo | Cuenta Google de administración de la plataforma (Plataforma Admin); grupos edani-admins y company-operator. |
| `qa-con-rol@e-dani.com` | humano | QA | activo | Usuario de prueba autenticado CON el grupo company-operator; fixture de la prueba de drift de C5 (INFRA-219). |
| `qa-sin-rol@e-dani.com` | humano | QA | retirada-propuesta | Usuario de prueba autenticado SIN company-operator, para el 403 del backend de company.e-dani.com. |
| `qa-write-sin-vinculo@e-dani.com` | humano | QA | activo | Fixture C2 reverso de OWU-28-g: usuario de prueba CON agentgateway-write, SIN grupos y SIN entrada en atlassian-identity-bindings; login scriptado PKCE por el cliente público agentgateway-chat-mcp. Su alta y contraseña las posee GitOps (agentgateway-write-fixture-user.sh + ítem 1Password); retirada propuesta al cerrar la épica. |
| `qa-sso-test` | humano | QA | activo | Usuario de prueba de QA para cadenas SSO con TOTP; grupo edani-operators, sin roles directos. |
| `staticduo@gmail.com` | humano | Dani (operador) | activo | Jordi Ibáñez Fernández (staticduo), colaborador externo de las épicas Browser Harness (INFRA-383/INFRA-413): su principal para gobernar por Keycloak sus propios browsers en sus hosts. Sin roles en este realm. |
| `uriel` | humano | Dani (operador) | activo | Cuenta del cliente externo Uriel Productions (info@urielproductions.com) para la propuesta viva uriel.e-dani.com. |
| `service-account-agentgateway-mac-cb` | sa | Dani (operador) | activo | client_credentials del Mac CloudBlue para /hindsight-cloudblue (banco CloudBlue, solo lectura; contenido solo Anthropic/local). Client manual, declarado en INFRA-974. |
| `service-account-agentgateway-mcp` | sa | DevOps | activo | Plano MCP de AgentGateway: las 24 lecturas agentgateway-read:* y agentgateway-write. |
| `service-account-atlassian-mcp-probe` | sa | DevOps | activo | Sonda de round-trip MCP del plano Atlassian: llama a la ruta /atlassian-probe (única herramienta jira_get_issue) con agentgateway-read:atlassian. |
| `service-account-chat-agentgateway` | sa | DevOps | activo | Identidad del chat (/studio) ante AgentGateway: los seis agentgateway-write:<dominio> de su superficie mas el rol de ruta agentgateway-read:studio (SC-699). |
| `service-account-claude-sessions-norol` | sa | QA | retirada-propuesta | Client de prueba SIN el rol claude-sessions: el 403 de /claude-sessions. |
| `service-account-claude-sessions-other` | sa | QA | retirada-propuesta | Segundo sub con claude-sessions: el 403 de propiedad entre sesiones de otro usuario. |
| `service-account-claude-sessions-test` | sa | QA | retirada-propuesta | Client de prueba con claude-sessions y agentgateway-read/write:claude-sessions: el camino feliz de /claude-sessions. |
| `service-account-cloudblue` | sa | Dani (operador) (origen-desconocido) | activo | client_credentials con el que CloudBlue llama a litellm.e-dani.com (team_id=cloudblue, aud=litellm). |
| `service-account-company-metrics-agentgateway` | sa | DevOps | activo | Consumidor MCP de las métricas de la compañía; porta company-metrics-read. |
| `service-account-correo-agente-lectura` | sa | DevOps | activo | Identidad de lectura del agente de casos de Postia ante AgentGateway: los agentgateway-read:<ruta> de sus perfiles (brain, picqer, shopify, shopify-admin, skirmshop-plugins, workspace) y ningún agentgateway-write*. (DGX-1218) |
| `service-account-correo-ejecutor` | sa | DevOps | activo | Ejecutor de las acciones aprobadas de los casos de Postia: agentgateway-write:correo-ejecutor (order_shipping_line_replace, order_returnable_lines_get, return_create, labels_pickup_create) y agentgateway-read:shopify-admin para pasar la puerta de la ruta. Nunca el agentgateway-write pelado ni otro dominio. (DGX-1218) |
| `service-account-hermes-enviar` | sa | DevOps | activo | Identidad MCP del plugin enviar de Hermes ante AgentGateway: el único que envía o borra borradores de Gmail (agentgateway-write:workspace-envio) por /workspace, más agentgateway-read:workspace para llegar a la ruta; nunca agentgateway-write ni otro dominio (INFRA-676). |
| `service-account-hermes-secretaria` | sa | DevOps | activo | Identidad MCP del perfil general de las secretarias de Hermes ante AgentGateway: lee brain/social/workspace y escribe en social, workspace y compania, con su propio sub (sustituye al sub compartido operator-machines). |
| `service-account-hermes-secretaria-casa` | sa | DevOps | activo | Identidad MCP del perfil de casa de las secretarias de Hermes ante AgentGateway: lee brain/social/workspace y escribe en social, workspace y compania, con su propio sub (sustituye al sub compartido operator-machines). |
| `service-account-hermes-secretaria-dani` | sa | DevOps | activo | Identidad MCP del perfil de Dani de las secretarias de Hermes ante AgentGateway: lee brain/social/workspace y escribe en social y workspace, con su propio sub (sustituye al sub compartido operator-machines). |
| `service-account-hermes-secretaria-leila` | sa | DevOps | activo | Identidad MCP del perfil de Leila de las secretarias de Hermes ante AgentGateway: lee brain/social/workspace y escribe en social y workspace, con su propio sub (sustituye al sub compartido operator-machines). |
| `service-account-hermes-secretaria-skirmshop` | sa | DevOps | activo | Identidad MCP del perfil secretaria-skirmshop de Hermes ante AgentGateway: lectura de negocio (picqer, shopify, shopify-admin solo product_stock_status por su lista fina de Hermes —DGX-854—, skirmshop-plugins, brain, workspace) y, como única escritura, redactar borradores de Gmail (agentgateway-write:workspace-borrador, INFRA-676); nunca enviar. |
| `service-account-jarvis-echo` | sa | DevOps | activo | Identidad M2M de la skill de Alexa jarvis-alexa: lectura del calendario de la Agenda del Echo Show por AgentGateway /workspace con agentgateway-read:workspace; sin ningún write (INFRA-477). |
| `service-account-keycloak-rbac-auditor` | sa | DevOps | activo | Auditor de solo lectura del realm para el CronJob keycloak-role-drift (view-realm, view-users, query-users, query-groups de realm-management; sin view-clients ni manage-*). |
| `service-account-openclaw-readonly-agentgateway` | sa | DevOps | activo | Identidad de solo lectura de OpenClaw ante AgentGateway, más cto-office-send. |
| `service-account-synapse-draft-orchestrator` | sa | DevOps | activo | M2M de los borradores de Synapse; porta synapse-draft-m2m. |
| `service-account-synapse-sre-orchestrator` | sa | DevOps | activo | M2M del orquestador SRE de Synapse; porta synapse-sre-m2m y cto-office-send. |

## Contract block

```json
{
  "realm": "edani",
  "measured": "2026-10-16",
  "principals": [
    {
      "username": "correo@e-dani.com",
      "type": "humano",
      "client": null,
      "owner": "Dani (operador)",
      "source": "SC-1958/SC-1959 (06-10): alta de la cuenta `correo` «E-dani Correo» en la org Claude Team E-dani; el SSO de claude.ai de la org va por Keycloak (claude-ai-sso), así que su login vive en este realm",
      "purpose": "Cuenta de correo de la org Claude Team E-dani («E-dani Correo»); su login a claude.ai pasa por el SSO de este realm. Sin roles propios.",
      "realm_roles": [
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "daniel.ibanez@alphalinkcrossfit.com",
      "type": "humano",
      "client": null,
      "owner": "Dani (operador)",
      "source": "k8s-agentgateway-pocharlies backends/workspace/identity-bindings.yaml (buzón propio de Daniel, admitido 23-09); claude-sessions por OWU-27",
      "purpose": "Cuenta Google de Dani (Alphalink). SSO del realm y usuario de las sesiones de Claude nacidas del chat (OWU-27).",
      "realm_roles": [
        "claude-sessions",
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "daniel.ibanez@cloudblue.com",
      "type": "humano",
      "client": null,
      "owner": "Dani (operador)",
      "source": "ninguna: solo el propio realm (IdP google, nombre Daniel Ibanez Fernandez)",
      "purpose": "Cuenta Google de trabajo de Dani (CloudBlue); SSO del realm, sin roles propios.",
      "realm_roles": [
        "default-roles-edani"
      ],
      "status": "activo",
      "flags": [
        "origen-desconocido"
      ]
    },
    {
      "username": "dom.greco@alphalinkcrossfit.com",
      "type": "humano",
      "client": null,
      "owner": "Dani (operador)",
      "source": "ninguna: alta en el realm el 2026-10-16 12:36 UTC por la API de admin (auto-registro apagado), sin atributos y sin referencia en ningún repo; adoptada por SC-2522",
      "purpose": "Usuario de origen desconocido; sin roles propios más allá del compuesto del realm.",
      "realm_roles": [
        "default-roles-edani"
      ],
      "status": "activo",
      "flags": [
        "origen-desconocido"
      ]
    },
    {
      "username": "info@e-dani.com",
      "type": "humano",
      "client": null,
      "owner": "Dani (operador)",
      "source": "k8s-agentgateway-pocharlies backends/workspace/identity-bindings.yaml (GWS_DEFAULT_USER, cuenta del operador)",
      "purpose": "Buzón del negocio (Skirmshop Spain); SSO del realm, grupos edani-operators y skirmbooks-users.",
      "realm_roles": [
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "lays84.mv@gmail.com",
      "type": "humano",
      "client": null,
      "owner": "Leila",
      "source": "k8s-agentgateway-pocharlies backends/workspace/identity-bindings.yaml (usuario de Leila, sub medido 21-09)",
      "purpose": "Cuenta Google de Leila; SSO del realm (grupo edani-users) y su buzón en /workspace.",
      "realm_roles": [
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "me@e-dani.com",
      "type": "humano",
      "client": null,
      "owner": "Dani (operador)",
      "source": "SC-320 (alias SC-100), criterio 6 de SC-44: el usuario main; identity-bindings.yaml (usuario humano de Daniel); agentgateway-write por OWU-80 (veredicto de security de OWU-28, condición (b))",
      "purpose": "Usuario principal del operador; admin del realm por grupos, cto-office-send para /cto-office y el write global agentgateway-write concedido por OWU-80.",
      "realm_roles": [
        "agentgateway-write",
        "cto-office-send",
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "pocharlies@gmail.com",
      "type": "humano",
      "client": null,
      "owner": "Dani (operador)",
      "source": "k8s-agentgateway-pocharlies backends/workspace/identity-bindings.yaml (cuenta Google del operador)",
      "purpose": "Cuenta Google de administración de la plataforma (Plataforma Admin); grupos edani-admins y company-operator.",
      "realm_roles": [
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "qa-con-rol@e-dani.com",
      "type": "humano",
      "client": null,
      "owner": "QA",
      "source": "SC-479 / SC-359 (alias SC-665): usuario de prueba con company-operator creado por devops; INFRA-250 (P4 de INFRA-219) lo usa para la prueba de drift",
      "purpose": "Usuario de prueba autenticado CON el grupo company-operator; fixture de la prueba de drift de C5 (INFRA-219).",
      "realm_roles": [
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "qa-sin-rol@e-dani.com",
      "type": "humano",
      "client": null,
      "owner": "QA",
      "source": "SC-479 / SC-359 (alias SC-665): usuario de prueba sin company-operator creado por devops",
      "purpose": "Usuario de prueba autenticado SIN company-operator, para el 403 del backend de company.e-dani.com.",
      "realm_roles": [
        "default-roles-edani"
      ],
      "status": "retirada-propuesta",
      "retirement_reason": "Fixture de SC-479 / SC-665 (Done). Ningún criterio de INFRA-219 ni otra épica abierta lo usa (la prueba de drift de C5 usa qa-con-rol). Decisión del CTO; mientras no se decida sigue activo en el realm."
    },
    {
      "username": "qa-write-sin-vinculo@e-dani.com",
      "type": "humano",
      "client": null,
      "owner": "QA",
      "source": "OWU-28 / historia g (fixture C2 reverso; plan del architect nota-architect-plan.md)",
      "purpose": "Fixture C2 reverso de OWU-28 (write sin vínculo Atlassian): usuario de prueba con agentgateway-write, sin grupos ni entrada en atlassian-identity-bindings; login scriptado PKCE por /chat-atlassian con el cliente público agentgateway-chat-mcp. Alta, contraseña y retirada por GitOps (agentgateway-write-fixture-user.sh).",
      "realm_roles": [
        "agentgateway-write",
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "qa-sso-test",
      "type": "humano",
      "client": null,
      "owner": "QA",
      "source": "INFRA-561 (usuario de prueba del realm edani para QA, con TOTP en 1Password, alta 05-10); su acceso por sso-chain verificado en INFRA-599 (cierre de la exposición INFRA-556)",
      "purpose": "Usuario de prueba de QA para cadenas SSO con TOTP; grupo edani-operators, sin roles directos.",
      "realm_roles": [
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "staticduo@gmail.com",
      "type": "humano",
      "client": null,
      "owner": "Dani (operador)",
      "source": "INFRA-383 M1B (Browser Harness): la propuesta de identidad Keycloak de Jordi Ibáñez (staticduo, relay 2039) aceptada el 03-10 sustituye los tokens compartidos por principals; alta el 05-10",
      "purpose": "Jordi Ibáñez Fernández (staticduo), colaborador externo de las épicas Browser Harness (INFRA-383/INFRA-413): su principal para gobernar por Keycloak sus propios browsers en sus hosts. Sin roles en este realm.",
      "realm_roles": [
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "uriel",
      "type": "humano",
      "client": null,
      "owner": "Dani (operador)",
      "source": "~/k8s/uriel-proposal/README.md (directorio del workspace, sin repo): client uriel-proposal, solo entra info@urielproductions.com",
      "purpose": "Cuenta del cliente externo Uriel Productions (info@urielproductions.com) para la propuesta viva uriel.e-dani.com.",
      "realm_roles": [
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "service-account-agentgateway-mac-cb",
      "type": "sa",
      "client": "agentgateway-mac-cb",
      "owner": "Dani (operador)",
      "source": "ningún ticket ni repo: client creado a mano en el realm (el Mac CloudBlue del paseo SC-2473); declarada por security al cerrar la matriz hindsight (INFRA-974)",
      "purpose": "client_credentials del Mac CloudBlue para la ruta /hindsight-cloudblue de AgentGateway (banco CloudBlue, solo lectura; contenido que solo puede ir a modelos Anthropic/local, nunca a OpenAI/Alibaba).",
      "realm_roles": [
        "agentgateway-read:hindsight-cloudblue",
        "default-roles-edani"
      ],
      "status": "activo",
      "flags": [
        "origen-desconocido"
      ]
    },
    {
      "username": "service-account-agentgateway-mcp",
      "type": "sa",
      "client": "agentgateway-mcp",
      "owner": "DevOps",
      "source": "platform/keycloak-next: agentgateway-read-grants.sh (INFRA-44), agentgateway-write-role.sh (SC-44), agentgateway-mcp-token-ttl.sh (INFRA-187)",
      "purpose": "Plano MCP de AgentGateway: las 24 lecturas agentgateway-read:* y agentgateway-write (la escritura del planificador va con el write pelado; SC-2726).",
      "realm_roles": [
        "agentgateway-read:alphalink",
        "agentgateway-read:analytics",
        "agentgateway-read:atlassian",
        "agentgateway-read:brain",
        "agentgateway-read:dgx-control",
        "agentgateway-read:gsc",
        "agentgateway-read:hindsight-tienda",
        "agentgateway-read:image",
        "agentgateway-read:merchant",
        "agentgateway-read:offers",
        "agentgateway-read:picqer",
        "agentgateway-read:plaud",
        "agentgateway-read:shopify",
        "agentgateway-read:shopify-admin",
        "agentgateway-read:skirmshop-plugins",
        "agentgateway-read:social",
        "agentgateway-read:stt",
        "agentgateway-read:studio",
        "agentgateway-read:synapse",
        "agentgateway-read:synapse-sre",
        "agentgateway-read:synapse-tools",
        "agentgateway-read:tts",
        "agentgateway-read:weight",
        "agentgateway-read:workspace",
        "agentgateway-write",
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "service-account-atlassian-mcp-probe",
      "type": "sa",
      "client": "atlassian-mcp-probe",
      "owner": "DevOps",
      "source": "SC-1834 (H4 de SC-1728): sonda de salud del plano Atlassian (Deployment atlassian-mcp-probe, ns monitoring, k8s-observability-pocharlies); el binding de su sub a la cuenta `sonda` está en k8s-agentgateway-pocharlies backends/atlassian-mcp/atlassian-identity-bindings.yaml y el contrato en su CONTRACTS.yaml",
      "purpose": "Sonda de round-trip MCP del plano Atlassian: llama a la ruta /atlassian-probe (única herramienta jira_get_issue) con agentgateway-read:atlassian.",
      "realm_roles": [
        "agentgateway-read:atlassian",
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "service-account-chat-agentgateway",
      "type": "sa",
      "client": "chat-agentgateway",
      "owner": "DevOps",
      "source": "platform/keycloak-next/chat-agentgateway-client.yaml (SC-490; contrato v2 de dominios, PR #142; SC-699 anade la puerta de ruta read:studio)",
      "purpose": "Identidad del chat (/studio) ante AgentGateway: los seis agentgateway-write:<dominio> de su superficie mas agentgateway-read:studio, el rol de ruta que /studio exige desde INFRA-143.",
      "realm_roles": [
        "agentgateway-read:studio",
        "agentgateway-write:gsc",
        "agentgateway-write:hermes",
        "agentgateway-write:media",
        "agentgateway-write:social",
        "agentgateway-write:synapse",
        "agentgateway-write:workspace",
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "service-account-claude-sessions-norol",
      "type": "sa",
      "client": "claude-sessions-norol",
      "owner": "QA",
      "source": "OWU-27 (fixture sec-norol de la matriz de qa), creado por admin API fuera de este repo",
      "purpose": "Client de prueba SIN el rol claude-sessions: el 403 de /claude-sessions.",
      "realm_roles": [
        "default-roles-edani"
      ],
      "status": "retirada-propuesta",
      "retirement_reason": "Fixture de la verificación en vivo de OWU-27 (Done 24-09). Ningún manifiesto ni reconciliador lo referencia (grep de k8s-agentgateway-pocharlies, dgx-infra y x86-host-runtime-pocharlies: 0 resultados, 24-09); su secreto solo lo usaron los encargos de qa de OWU-27. Retirarlo exige quitarlo también de los grantees de ROLES.yaml en la misma PR. Decisión del CTO."
    },
    {
      "username": "service-account-claude-sessions-other",
      "type": "sa",
      "client": "claude-sessions-other",
      "owner": "QA",
      "source": "OWU-27 (descripción del client: segundo usuario de prueba, 403 de propiedad), creado por admin API fuera de este repo",
      "purpose": "Segundo sub con claude-sessions: el 403 de propiedad entre sesiones de otro usuario.",
      "realm_roles": [
        "claude-sessions",
        "default-roles-edani"
      ],
      "status": "retirada-propuesta",
      "retirement_reason": "Fixture de la verificación en vivo de OWU-27 (Done 24-09). Ningún manifiesto ni reconciliador lo referencia (grep de k8s-agentgateway-pocharlies, dgx-infra y x86-host-runtime-pocharlies: 0 resultados, 24-09); su secreto solo lo usaron los encargos de qa de OWU-27. Retirarlo exige quitarlo también de los grantees de ROLES.yaml en la misma PR. Decisión del CTO."
    },
    {
      "username": "service-account-claude-sessions-test",
      "type": "sa",
      "client": "claude-sessions-test",
      "owner": "QA",
      "source": "OWU-27 (fixture sec-test de la matriz de qa), creado por admin API fuera de este repo",
      "purpose": "Client de prueba con claude-sessions y agentgateway-read/write:claude-sessions: el camino feliz de /claude-sessions.",
      "realm_roles": [
        "agentgateway-read:claude-sessions",
        "agentgateway-write:claude-sessions",
        "claude-sessions",
        "default-roles-edani"
      ],
      "status": "retirada-propuesta",
      "retirement_reason": "Fixture de la verificación en vivo de OWU-27 (Done 24-09). Ningún manifiesto ni reconciliador lo referencia (grep de k8s-agentgateway-pocharlies, dgx-infra y x86-host-runtime-pocharlies: 0 resultados, 24-09); su secreto solo lo usaron los encargos de qa de OWU-27. Retirarlo exige quitarlo también de los grantees de ROLES.yaml en la misma PR. Decisión del CTO."
    },
    {
      "username": "service-account-cloudblue",
      "type": "sa",
      "client": "cloudblue",
      "owner": "Dani (operador)",
      "source": "ningún ticket ni repo: solo la descripción del client en el realm (CloudBlue -> LiteLLM, scope litellm-cloudblue)",
      "purpose": "client_credentials con el que CloudBlue llama a litellm.e-dani.com (team_id=cloudblue, aud=litellm).",
      "realm_roles": [
        "default-roles-edani"
      ],
      "status": "activo",
      "flags": [
        "origen-desconocido"
      ]
    },
    {
      "username": "service-account-company-metrics-agentgateway",
      "type": "sa",
      "client": "company-metrics-agentgateway",
      "owner": "DevOps",
      "source": "SC-255 (épica SC-226): Company metrics MCP consumer, creado por admin API",
      "purpose": "Consumidor MCP de las métricas de la compañía; porta company-metrics-read.",
      "realm_roles": [
        "company-metrics-read",
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "service-account-correo-agente-lectura",
      "type": "sa",
      "client": "correo-agente-lectura",
      "owner": "DevOps",
      "source": "DGX-1218 (PR-2 de la épica DGX-1209, agente de casos de Postia); condición 3 de security de DGX-1209 (comentarios 37045 y 37075); k8s-agentgateway-pocharlies#221 (reglas del gateway); creado por platform/keycloak-next/correo-agente-clients.yaml, nunca a mano; el secreto lo copia devops a 1Password tras el sync (RUNBOOK sección 19); el binding por sub a los buzones del núcleo en k8s-agentgateway-pocharlies backends/workspace/identity-bindings.yaml va en el mismo cambio de GitOps que el buzón",
      "purpose": "Identidad de lectura del agente de casos de Postia ante AgentGateway: los agentgateway-read:<ruta> de sus perfiles (brain, picqer, shopify, shopify-admin, skirmshop-plugins, workspace) y ningún agentgateway-write*.",
      "realm_roles": [
        "agentgateway-read:brain",
        "agentgateway-read:picqer",
        "agentgateway-read:shopify",
        "agentgateway-read:shopify-admin",
        "agentgateway-read:skirmshop-plugins",
        "agentgateway-read:workspace",
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "service-account-correo-ejecutor",
      "type": "sa",
      "client": "correo-ejecutor",
      "owner": "DevOps",
      "source": "DGX-1218 (PR-2 de la épica DGX-1209, agente de casos de Postia); condición 3 de security de DGX-1209 (comentarios 37045 y 37075); k8s-agentgateway-pocharlies#221 (reglas del gateway); creado por platform/keycloak-next/correo-agente-clients.yaml, nunca a mano; el secreto lo copia devops a 1Password tras el sync (RUNBOOK sección 19)",
      "purpose": "Ejecutor de las acciones aprobadas de los casos de Postia: agentgateway-write:correo-ejecutor (order_shipping_line_replace, order_returnable_lines_get, return_create, labels_pickup_create) y agentgateway-read:shopify-admin para pasar la puerta de la ruta. Nunca el agentgateway-write pelado ni otro dominio.",
      "realm_roles": [
        "agentgateway-read:shopify-admin",
        "agentgateway-write:correo-ejecutor",
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "service-account-hermes-enviar",
      "type": "sa",
      "client": "hermes-enviar",
      "owner": "DevOps",
      "source": "INFRA-676 (P4b de INFRA-480, historia hermana de INFRA-642); veredicto de security INFRA-640 (a): client confidencial con solo estos dos roles; k8s-agentgateway-pocharlies#186 (reglas del gateway); creado por platform/keycloak-next/hermes-enviar-client.yaml, nunca a mano; el secreto en 1Password `hermes-kc-enviar` vía ExternalSecret hermes-kc-secretarias (k8s-openclaw-qwen36-pocharlies); el binding por sub en k8s-agentgateway-pocharlies backends/workspace/identity-bindings.yaml es INFRA-677",
      "purpose": "Identidad MCP del plugin enviar de Hermes ante AgentGateway: el único que envía o borra borradores de Gmail por /workspace con agentgateway-write:workspace-envio (gmail_send, gmail_forward, gmail_send_draft, gmail_delete_draft), más agentgateway-read:workspace para llegar a la ruta. Nunca el agentgateway-write pelado ni otro dominio.",
      "realm_roles": [
        "agentgateway-read:workspace",
        "agentgateway-write:workspace-envio",
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "service-account-hermes-secretaria",
      "type": "sa",
      "client": "hermes-secretaria",
      "owner": "DevOps",
      "source": "INFRA-494 (épica INFRA-479): client client_credentials del perfil hermes-secretaria de Hermes, creado por devops el 04-10; el secreto en 1Password `hermes-kc-secretaria` vía ExternalSecret hermes-kc-secretarias (k8s-openclaw-qwen36-pocharlies); bindings por sub en k8s-agentgateway-pocharlies backends/workspace/identity-bindings.yaml",
      "purpose": "Identidad MCP del perfil general de las secretarias de Hermes ante AgentGateway: lee brain/social/workspace y escribe en social, workspace y compania, con su propio sub (sustituye al sub compartido operator-machines).",
      "realm_roles": [
        "agentgateway-read:brain",
        "agentgateway-read:social",
        "agentgateway-read:workspace",
        "agentgateway-write:browser-navegacion",
        "agentgateway-write:compania",
        "agentgateway-write:social",
        "agentgateway-write:workspace",
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "service-account-hermes-secretaria-casa",
      "type": "sa",
      "client": "hermes-secretaria-casa",
      "owner": "DevOps",
      "source": "INFRA-494 (épica INFRA-479): client client_credentials del perfil hermes-secretaria-casa de Hermes, creado por devops el 04-10; el secreto en 1Password `hermes-kc-secretaria-casa` vía ExternalSecret hermes-kc-secretarias (k8s-openclaw-qwen36-pocharlies); bindings por sub en k8s-agentgateway-pocharlies backends/workspace/identity-bindings.yaml",
      "purpose": "Identidad MCP del perfil de casa de las secretarias de Hermes ante AgentGateway: lee brain/social/workspace y escribe en social, workspace y compania, con su propio sub (sustituye al sub compartido operator-machines).",
      "realm_roles": [
        "agentgateway-read:brain",
        "agentgateway-read:social",
        "agentgateway-read:workspace",
        "agentgateway-write:browser-navegacion",
        "agentgateway-write:compania",
        "agentgateway-write:social",
        "agentgateway-write:workspace",
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "service-account-hermes-secretaria-dani",
      "type": "sa",
      "client": "hermes-secretaria-dani",
      "owner": "DevOps",
      "source": "INFRA-494 (épica INFRA-479): client client_credentials del perfil hermes-secretaria-dani de Hermes, creado por devops el 04-10; el secreto en 1Password `hermes-kc-secretaria-dani` vía ExternalSecret hermes-kc-secretarias (k8s-openclaw-qwen36-pocharlies); bindings por sub en k8s-agentgateway-pocharlies backends/workspace/identity-bindings.yaml",
      "purpose": "Identidad MCP del perfil de Dani de las secretarias de Hermes ante AgentGateway: lee brain/social/workspace y escribe en social y workspace, con su propio sub (sustituye al sub compartido operator-machines).",
      "realm_roles": [
        "agentgateway-read:brain",
        "agentgateway-read:social",
        "agentgateway-read:workspace",
        "agentgateway-write:browser-navegacion",
        "agentgateway-write:social",
        "agentgateway-write:workspace",
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "service-account-hermes-secretaria-leila",
      "type": "sa",
      "client": "hermes-secretaria-leila",
      "owner": "DevOps",
      "source": "INFRA-494 (épica INFRA-479): client client_credentials del perfil hermes-secretaria-leila de Hermes, creado por devops el 04-10; el secreto en 1Password `hermes-kc-secretaria-leila` vía ExternalSecret hermes-kc-secretarias (k8s-openclaw-qwen36-pocharlies); bindings por sub en k8s-agentgateway-pocharlies backends/workspace/identity-bindings.yaml",
      "purpose": "Identidad MCP del perfil de Leila de las secretarias de Hermes ante AgentGateway: lee brain/social/workspace y escribe en social y workspace, con su propio sub (sustituye al sub compartido operator-machines).",
      "realm_roles": [
        "agentgateway-read:brain",
        "agentgateway-read:social",
        "agentgateway-read:workspace",
        "agentgateway-write:browser-navegacion",
        "agentgateway-write:social",
        "agentgateway-write:workspace",
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "service-account-hermes-secretaria-skirmshop",
      "type": "sa",
      "client": "hermes-secretaria-skirmshop",
      "owner": "DevOps",
      "source": "INFRA-494 (épica INFRA-479): client client_credentials del perfil hermes-secretaria-skirmshop de Hermes, creado por devops el 04-10; el secreto en 1Password `hermes-kc-secretaria-skirmshop` vía ExternalSecret hermes-kc-secretarias (k8s-openclaw-qwen36-pocharlies); bindings por sub en k8s-agentgateway-pocharlies backends/workspace/identity-bindings.yaml",
      "purpose": "Identidad MCP del perfil secretaria-skirmshop de Hermes ante AgentGateway: lectura de negocio (picqer, shopify, shopify-admin solo product_stock_status por su lista fina de Hermes —DGX-854—, skirmshop-plugins, brain, workspace) y, como única escritura, redactar borradores de Gmail (agentgateway-write:workspace-borrador, INFRA-676); nunca enviar.",
      "realm_roles": [
        "agentgateway-read:brain",
        "agentgateway-read:picqer",
        "agentgateway-read:shopify",
        "agentgateway-read:shopify-admin",
        "agentgateway-read:skirmshop-plugins",
        "agentgateway-read:workspace",
        "agentgateway-write:workspace-borrador",
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "service-account-jarvis-echo",
      "type": "sa",
      "client": "jarvis-echo",
      "owner": "DevOps",
      "source": "INFRA-411 (skill jarvis-alexa; client creado a mano el 03-10 por la API de admin — cauce corregido en INFRA-477); veredicto de security en k8s-agentgateway-pocharlies#170 (identity-bindings del sub 1bcb6c47-0a01-4717-959d-9755e2c9ad36); adoptado por platform/keycloak-next/jarvis-echo-client.yaml",
      "purpose": "Identidad M2M de la skill de Alexa jarvis-alexa (ns jarvis): lee el calendario de la Agenda del Echo Show con calendar_list_events por AgentGateway /workspace. Solo lectura: agentgateway-read:workspace; nunca agentgateway-write.",
      "realm_roles": [
        "agentgateway-read:workspace",
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "service-account-keycloak-rbac-auditor",
      "type": "sa",
      "client": "keycloak-rbac-auditor",
      "owner": "DevOps",
      "source": "INFRA-250 (P4 de INFRA-219): platform/keycloak-next/keycloak-rbac-auditor-client.yaml, identidad del CronJob keycloak-role-drift",
      "purpose": "Auditor de solo lectura del realm para el CronJob keycloak-role-drift (view-realm, view-users, query-users, query-groups de realm-management; sin view-clients ni manage-*).",
      "realm_roles": [
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "service-account-openclaw-readonly-agentgateway",
      "type": "sa",
      "client": "openclaw-readonly-agentgateway",
      "owner": "DevOps",
      "source": "platform/keycloak-next/openclaw-readonly-clients.yaml (618ddea, 10-07); cto-office-send por SC-320 / SC-44",
      "purpose": "Identidad de solo lectura de OpenClaw ante AgentGateway, más cto-office-send.",
      "realm_roles": [
        "agentgateway-read:gsc",
        "agentgateway-read:offers",
        "agentgateway-read:plaud",
        "agentgateway-read:skirmshop-plugins",
        "agentgateway-read:studio",
        "agentgateway-read:synapse",
        "agentgateway-read:synapse-tools",
        "cto-office-send",
        "default-roles-edani"
      ],
      "status": "activo"
    },
    {
      "username": "service-account-synapse-draft-orchestrator",
      "type": "sa",
      "client": "synapse-draft-orchestrator",
      "owner": "DevOps",
      "source": "platform/keycloak-next/synapse-sre-client.yaml (1c3babc, 14-07: identidad M2M de borradores de Synapse)",
      "purpose": "M2M de los borradores de Synapse; porta synapse-draft-m2m.",
      "realm_roles": [
        "default-roles-edani",
        "synapse-draft-m2m"
      ],
      "status": "activo"
    },
    {
      "username": "service-account-synapse-sre-orchestrator",
      "type": "sa",
      "client": "synapse-sre-orchestrator",
      "owner": "DevOps",
      "source": "platform/keycloak-next/synapse-sre-client.yaml (#46/#47, 14-07); SC-320 (alias SC-100), criterio 6 de SC-44: la SA del agente de operaciones",
      "purpose": "M2M del orquestador SRE de Synapse; porta synapse-sre-m2m y cto-office-send.",
      "realm_roles": [
        "cto-office-send",
        "default-roles-edani",
        "synapse-sre-m2m"
      ],
      "status": "activo"
    }
  ]
}
```
