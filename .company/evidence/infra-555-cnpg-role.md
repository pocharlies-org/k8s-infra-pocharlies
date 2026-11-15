# INFRA-555 P2-b · evidencia (rol CNPG brain_openwebui_ro)

Dónde: worktree de la rama `infra-555-cnpg-role` (desde origin/main 8eb2881c1), x86, 31-10-2026.
Nada de `kubectl apply`: todo GitOps; las consultas a la base `chat` son de solo lectura (diagnóstico).

## 1. Esquema real de la base `chat`, medido antes de fijar los GRANT · PASS

`kubectl exec -n databases postgres-shared-nvme-1 -- psql -U postgres -d chat` (solo lectura):

```
\dt public.*          → chat, chat_message, "user" existen (entre 40+ tablas de Open WebUI)
chat cols             → id, user_id, title, created_at, updated_at, ..., chat, ... (JSON legado)
chat_message cols     → id, chat_id, user_id, role, parent_id, content, ... (mensajes normalizados)
user cols             → id, name, email, ...
chats                 → 184
chat_message rows     → 1218
chats con JSON        → 183 (el JSON chat.chat sigue poblado; chat_message vive en paralelo)
users con chats       → 6 (me@e-dani.com, lays84.mv@gmail.com, + 4 de prueba/otros)
```

Decisión: los mensajes VIVEN SEPARADOS (`chat_message` con datos) → el GRANT entra también
sobre `chat_message`, como condiciona el plan (INFRA-546, hallazgo 4). Nada más: ni `channel`,
ni `file`, ni `document` — cero escrituras, cero tablas de más.

## 2. Render del manifiesto · PASS

`kustomize build databases/postgres-shared` → limpio. Objetos nuevos:

```
added:   Job databases/postgres-shared-brain-openwebui-grants (PostSync, GRANT idempotente)
         ExternalSecret databases/brain-openwebui-db-credentials (sync-wave -1, formato Connect)
         Cluster spec.managed.roles: brain_openwebui_ro (30 → 31 roles; antes = yaml.safe_load
         de origin/main, después = render de la rama)
removed: (ninguno)
```

`kustomize build .` (lo que construye el CI, `kustomize_paths: "."`) → limpio, 726 objetos.

## 3. Ningún secreto en git · PASS

`git diff origin/main -- databases/postgres-shared | grep -i password` → solo referencias por
nombre (`passwordSecret: name:`, `property: DB_PASSWORD`, `secretKeyRef`); ningún valor. La
contraseña la posee 1Password (item `brain-openwebui-db`), materializada por ESO desde el
ClusterSecretStore `onepassword-connect`.

## 4. Postura de seguridad del rol (veredicto: security en esta PR)

- `login: true`, `connectionLimit: 3` (el CronJob abre 1 conexión por pasada).
- SELECT sobre exactamente `chat`, `"user"`, `chat_message`; USAGE en `public` (imprescindible
  para leer). Sin INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/CREATE.
- El Job PostSync falla a propósito (`ON_ERROR_STOP=1`) si el rol no existe aún: secuencia =
  item sembrado por security → ExternalSecret sano → rol creado por CNPG → GRANT.
- Si tras sembrar el item el rol no cogiera la contraseña, bump del annotation
  `synapse.e-dani.com/agent-role-credentials-generation` (regla del repo: solo tras ESO sano).

## Criterios

- C7 (Credencial, parte del rol): rol de solo lectura declarativo (CNPG `managed.roles` +
  passwordSecret), contraseña por ExternalSecret formato Connect, ningún secreto en git
  (secciones 2 y 3). El ExternalSecret del CronJob (skirmshop-brain-k8s, P2-c) lee el mismo
  item: nombre acordado `brain-openwebui-db` (campos `DB_USER`, `DB_PASSWORD`), secreto k8s de
  CNPG `brain-openwebui-db-credentials` (ns `databases`).
