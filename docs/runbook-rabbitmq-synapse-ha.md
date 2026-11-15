# Runbook — HA de las colas críticas de /synapse (INFRA-879)

## El problema

`post-upgrade-reboot.timer` (rol Ansible `post_upgrade_reboot` de este repo) reinicia cada
ks5-cp en su ventana escalonada (04:00 / 05:00 / 06:00 UTC) cuando apt deja
`/var/run/reboot-required` (upgrades de kernel). El drain no puede salvar las colas:
`shared-rabbitmq` pone un pod por nodo (anti-affinity `required` + `pause_minority`) y las
571 colas de `/synapse` eran classic sin réplica → mientras su nodo está caído, un tercio
de Synapse da `NOT_FOUND … process is stopped by supervisor` (SKIRM-161/162, medido
2026-10-16: 10–35 min por nodo).

## La decisión (2026-10-16, IT)

Convertir a quorum es lo canónico, pero `x-queue-type` es inmutable: hay que re-declarar
las colas, y eso es código de Synapse (historia aparte). Lo que IT puede aplicar sin tocar
código es **mirroring de las queues de la lista crítica** (patrón de la política
`sf-quorum-exclude`), política viva sobre las colas existentes:

- Política `sf-critical-mirror` en el vhost `/synapse`, prioridad **35**. Las políticas de
  RabbitMQ **no se fusionan**: gana la de mayor prioridad y las definiciones de las demás
  se ignoran. Con prioridad 25 quedaba tapada por `sf-quorum-exclude` (30) y no creaba
  réplicas (medido 2026-10-17); por eso va por encima y **repitiendo la clave `overflow`**
  que `sf-quorum-exclude` ponía en vigor, para no perderla.
- `{"ha-mode":"all","ha-promote-on-shutdown":"always","overflow":"reject-publish-dlx"}` —
  copia en los 3 nodos; con `always` el mirror se promueve aunque pueda perder los últimos
  mensajes async (mejor eso que 30 min sin servicio; los webhooks críticos son
  re-consultables por origen).
- Classic mirroring está deprecado y **no permitido por defecto** en esta imagen
  (3.13.7-dme): requiere
  `deprecated_features.permit.classic_queue_mirroring = true` en el ConfigMap
  `shared-rabbitmq-tuning` (hecho aquí) y un rolling restart de los 3 pods para que
  cargue el conf.

Provisional hasta que Synapse re-declare esas colas como quorum; entonces: borrar la
política y quitar la línea del ConfigMap.

## Comandos

```sh
# política (idempotente; el patrón es la lista crítica de sf-quorum-exclude).
# Prioridad 35 > sf-quorum-exclude (30): las políticas NO se fusionan, gana la de más
# prioridad, así que hay que repetir aquí la clave overflow que aquella fijaba.
kubectl -n databases exec shared-rabbitmq-0 -- rabbitmqctl set_policy -p /synapse \
  --apply-to queues --priority 35 sf-critical-mirror \
  '^(engine\.workflow_triggers|engine\.step_results|adapter\.gmail\.webhooks|adapter\.shopify\.webhooks|collections-tree\.shopify-events\.skirmshop|adapter\.banking\.movements\.import_stripe_webhook|adapter\.banking\.movements\.import_paypal_webhook|adapter\.banking\.movements\.import_psd2|adapter\.banking\.psd2\.complete_requisition|adapter\.messaging\.send|adapter\.accounting\.entry\.post|adapter\.accounting\.entry\.reverse|adapter\.accounting\.year_end_close|adapter\.accounting\.period\.close|adapter\.invoicing\.issued\.create|adapter\.invoicing\.posting\.post|adapter\.tax\.modelo\.submit|adapter\.sii\.push_recibida|adapter\.sii_emitted\.invoice\.poll)$' \
  '{"ha-mode":"all","ha-promote-on-shutdown":"always","overflow":"reject-publish-dlx"}'

# aplicar el conf requiere rolling restart (de uno en uno, esperar Ready en medio)
kubectl -n databases delete pod shared-rabbitmq-2   # el que menos colas maestras críticas tenga
kubectl -n databases wait --for=condition=Ready pod/shared-rabbitmq-2 --timeout=15m
# ... repetir con -1 y -0

# verificar: cada cola crítica con 2 slaves y sus consumidores
kubectl -n databases exec shared-rabbitmq-0 -- rabbitmqctl list_queues name slave_pids consumers \
  --vhost /synapse --silent | grep -E "gmail\.webhooks|shopify\.webhooks|workflow_triggers"
```

Tras aplicar la política, los consumidores de las colas reiniciadas pueden no reconectar
(consumidores sin watchdog, historia aparte): si una cola crítica queda a 0 consumidores,
rollout restart del deployment consumidor (`synapse-engine`, `synapse-dispatcher`,
`synapse-adapter-gmail|shopify|messaging-send`, `skirmbooks-*` en ns skirmshop).

## Rollback

```sh
kubectl -n databases exec shared-rabbitmq-0 -- rabbitmqctl clear_policy -p /synapse sf-critical-mirror
```
y quitar la línea del ConfigMap (el mirror se retira solo; sin el conf, la política no
crea réplicas).
