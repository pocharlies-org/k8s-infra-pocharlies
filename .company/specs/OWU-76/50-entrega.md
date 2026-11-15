Rol: devops · Fecha: 2026-10-08 · Sesión: cd09dd62-949d-4060-8a43-fd8d51d7226b · Estado: LISTO

# OWU-76: firstName y lastName del usuario fixture

## Qué se hizo

El login PKCE de qa-write-sin-vinculo@e-dani.com caía en «Update Account Information». Causa, leída en el hook y confirmada en el repo: el hook creaba el usuario con requiredActions=[] pero nunca fijaba firstName ni lastName. Ningún fichero del repo cambia el perfil de usuario del realm, así que rige el perfil por defecto de Keycloak 26, que exige ambos para el rol user.

Cambio en platform/keycloak-next/scripts/agentgateway-write-fixture-user.sh:
- ensure fija firstName=QA y lastName=Fixture al crear el usuario, y los corrige en cada sync donde difieran, con post-lectura como aserción.
- audit falla si firstName o lastName están vacíos (o llegan como null).
- requiredActions sigue vacío. Rol, grupos y vínculo no cambian. Los nombres son constantes del script, no sustituibles por entorno.

## Pull request

https://github.com/pocharlies-org/k8s-infra-pocharlies/pull/267 (rama OWU-28-g-fixture-profile, commit f634b1b, contra main). No mergeado.

## Cómo verificar

- sh -n platform/keycloak-next/scripts/agentgateway-write-fixture-user.sh: OK.
- REQUIRE_IMAGE_CONTRACT=0 python3 -m unittest tests/test_agentgateway_write_fixture_user_contract.py: 38 tests OK.
- pytest tests -k keycloak: 148 passed. Ese filtro no selecciona el fichero del fixture; lo cubre el unittest.
- Contra el hook de origin/main, los cinco casos nuevos fallan: son la prueba de que cubren el cambio.
- Efecto en vivo: no medido por devops. Se mide tras el sync del PostSync keycloak-agentgateway-write-fixture-user (wave 25).

## Criterios (00-spec.md de OWU-76)

El 00-spec.md adjunto a OWU-76 es el de la historia b (P2, listener 3038 del shim), no este cambio, así que no hay casillas que marcar en él. Los criterios que aplican son los de 70-qa.md de hoy:
- Condición 1 (requiredActions vacío y perfil completo): cumplida en código y tests. En vivo, pendiente de sync y del login de qa.
- C2 reverso y condición 6: pendientes de qa en vivo, tras el sync.

## Reutilizado

- Reutilizado: los helpers de platform/keycloak-next/scripts/kc-admin-common.sh (fail, nonempty_lines, kget) y el user_field, el patrón de lectura exacta por username y la post-lectura ya presentes en el mismo hook.
- Reutilizado: el harness tests/keycloak_hook_testlib.py (fake kcadm, run_hook, SilentWriteContractMixin); solo se amplió el fake del fixture con firstName y lastName.
- Buscado: rg -n "firstName|lastName|UPDATE_PROFILE|user-profile|userProfile|unmanagedAttributePolicy" en el repo. No hay ninguna coincidencia, así que no existe override del perfil que reutilizar.
- Nuevo: profile_names_match, apply_profile_names y assert_profile_names_present. Motivo: el hook no tenía ninguna lectura ni escritura de atributos de perfil, y el patrón existente (escribir con kcadm update, releer y fallar) es el mismo que usa apply_password y el rol.

## Qué queda y riesgos

- Queda el sync de ArgoCD que aplique el ConfigMap nuevo y ejecute el PostSync. El cambio entra por GitOps; no se ha tocado Keycloak a mano.
- Riesgo: si el realm rechazara el valor QA o Fixture por validación de perfil, el post-update falla en voz alta y el job queda en error. No se ha medido porque no se ha ejecutado contra Keycloak.
- Riesgo residual: el fixture ya existente en vivo tiene nombres vacíos; el primer sync lo corrige con una escritura. No hay migración manual.
- Contratos: ningún surface cambia (no hay routing key, ruta ni esquema). No hace falta .company/changes.

## Documento que refleja el cambio

platform/keycloak-next/RUNBOOK.md §17: el login del fixture ya no pasa por una página de perfil.

## Fuera de alcance (una línea)

En Jira no se han tocado transiciones ni asignación; el encargo pedía solo este adjunto. Hay que asignar el subtask y pasarlo a In Progress y a In Review según la tabla de roles si el orquestador no lo hace.
