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
repo).

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
| `daniel.ibanez@alphalinkcrossfit.com` | humano | Dani (operador) | activo | Cuenta Google de Dani (Alphalink). SSO del realm y usuario de las sesiones de Claude nacidas del chat (OWU-27). |
| `daniel.ibanez@cloudblue.com` | humano | Dani (operador) (origen-desconocido) | activo | Cuenta Google de trabajo de Dani (CloudBlue); SSO del realm, sin roles propios. |
| `info@e-dani.com` | humano | Dani (operador) | activo | Buzón del negocio (Skirmshop Spain); SSO del realm, grupos edani-operators y skirmbooks-users. |
| `lays84.mv@gmail.com` | humano | Leila | activo | Cuenta Google de Leila; SSO del realm (grupo edani-users) y su buzón en /workspace. |
| `me@e-dani.com` | humano | Dani (operador) | activo | Usuario principal del operador; admin del realm por grupos y cto-office-send para /cto-office. |
| `pocharlies@gmail.com` | humano | Dani (operador) | activo | Cuenta Google de administración de la plataforma (Plataforma Admin); grupos edani-admins y company-operator. |
| `qa-con-rol@e-dani.com` | humano | QA | activo | Usuario de prueba autenticado CON el grupo company-operator; fixture de la prueba de drift de C5 (INFRA-219). |
| `qa-sin-rol@e-dani.com` | humano | QA | retirada-propuesta | Usuario de prueba autenticado SIN company-operator, para el 403 del backend de company.e-dani.com. |
| `uriel` | humano | Dani (operador) | activo | Cuenta del cliente externo Uriel Productions (info@urielproductions.com) para la propuesta viva uriel.e-dani.com. |
| `service-account-agentgateway-mcp` | sa | DevOps | activo | Plano MCP de AgentGateway: las 21 lecturas agentgateway-read:* y agentgateway-write. |
| `service-account-chat-agentgateway` | sa | DevOps | activo | Identidad del chat (/studio) ante AgentGateway: los seis agentgateway-write:<dominio> de su superficie. |
| `service-account-claude-sessions-norol` | sa | QA | retirada-propuesta | Client de prueba SIN el rol claude-sessions: el 403 de /claude-sessions. |
| `service-account-claude-sessions-other` | sa | QA | retirada-propuesta | Segundo sub con claude-sessions: el 403 de propiedad entre sesiones de otro usuario. |
| `service-account-claude-sessions-test` | sa | QA | retirada-propuesta | Client de prueba con claude-sessions y agentgateway-read/write:claude-sessions: el camino feliz de /claude-sessions. |
| `service-account-cloudblue` | sa | Dani (operador) (origen-desconocido) | activo | client_credentials con el que CloudBlue llama a litellm.e-dani.com (team_id=cloudblue, aud=litellm). |
| `service-account-company-metrics-agentgateway` | sa | DevOps | activo | Consumidor MCP de las métricas de la compañía; porta company-metrics-read. |
| `service-account-openclaw-readonly-agentgateway` | sa | DevOps | activo | Identidad de solo lectura de OpenClaw ante AgentGateway, más cto-office-send. |
| `service-account-synapse-draft-orchestrator` | sa | DevOps | activo | M2M de los borradores de Synapse; porta synapse-draft-m2m. |
| `service-account-synapse-sre-orchestrator` | sa | DevOps | activo | M2M del orquestador SRE de Synapse; porta synapse-sre-m2m y cto-office-send. |

## Contract block

```json
{
  "realm": "edani",
  "measured": "2026-09-24",
  "principals": [
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
      "source": "SC-320 (alias SC-100), criterio 6 de SC-44: el usuario main; identity-bindings.yaml (usuario humano de Daniel)",
      "purpose": "Usuario principal del operador; admin del realm por grupos y cto-office-send para /cto-office.",
      "realm_roles": [
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
      "username": "service-account-agentgateway-mcp",
      "type": "sa",
      "client": "agentgateway-mcp",
      "owner": "DevOps",
      "source": "platform/keycloak-next: agentgateway-read-grants.sh (INFRA-44), agentgateway-write-role.sh (SC-44), agentgateway-mcp-token-ttl.sh (INFRA-187)",
      "purpose": "Plano MCP de AgentGateway: las 21 lecturas agentgateway-read:* y agentgateway-write.",
      "realm_roles": [
        "agentgateway-read:analytics",
        "agentgateway-read:atlassian",
        "agentgateway-read:brain",
        "agentgateway-read:dgx-control",
        "agentgateway-read:gsc",
        "agentgateway-read:image",
        "agentgateway-read:merchant",
        "agentgateway-read:offers",
        "agentgateway-read:picqer",
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
      "username": "service-account-chat-agentgateway",
      "type": "sa",
      "client": "chat-agentgateway",
      "owner": "DevOps",
      "source": "platform/keycloak-next/chat-agentgateway-client.yaml (SC-490; contrato v2 de dominios, PR #142)",
      "purpose": "Identidad del chat (/studio) ante AgentGateway: los seis agentgateway-write:<dominio> de su superficie.",
      "realm_roles": [
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
      "username": "service-account-openclaw-readonly-agentgateway",
      "type": "sa",
      "client": "openclaw-readonly-agentgateway",
      "owner": "DevOps",
      "source": "platform/keycloak-next/openclaw-readonly-clients.yaml (618ddea, 10-07); cto-office-send por SC-320 / SC-44",
      "purpose": "Identidad de solo lectura de OpenClaw ante AgentGateway, más cto-office-send.",
      "realm_roles": [
        "agentgateway-read:gsc",
        "agentgateway-read:offers",
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
