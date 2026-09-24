# ROUTE-ROLES — matriz ruta×rol del AgentGateway (INFRA-219 C3)

Qué rol de realm de `edani` exige cada ruta del AgentGateway, medido contra el
config **vivo** (ConfigMap `agentgateway/agentgateway-config`, clave
`config.yaml`), no contra el repo `k8s-agentgateway-pocharlies`. Este fichero
no cambia ningún `require:`: documenta el que hay y falla cuando se mueve.

- **Fuente de verdad del verificador: el bloque `json` del final**, leído con
  `kc_rbac.load_json_block`. La tabla es un resumen para leer; si discrepa, manda
  el bloque.
- Un **gate** es un par (ruta, rol). `require` = el rol se exige a nivel de ruta
  (regla `require:` o regla de autorización sin tool); `tools` = el rol se exige
  en reglas `mcpAuthorization` que nombran tools, con la lista exacta de tools.
  Hoy: **42 rutas, 68 gates**.
- `unrouted` = roles gateway vivos que ninguna ruta exige, con para qué existen.
  Ninguno se retira desde aquí.

## Comprobarlo

```bash
KUBECONFIG=~/.kube/config python3 platform/keycloak-next/scripts/verify-route-roles.py
# OK: <N> gates coherentes, 0 roles referenciados inexistentes, 0 roles sin ruta documentada  -> exit 0
# DRIFT: <hallazgo>, uno por línea                                                          -> exit 1
# ERROR: <kubectl/auth/red/parse/matriz>                                                    -> exit 2
```

Solo lectura: el ConfigMap con `kubectl get`, los roles del realm con
`kc_rbac.Client.from_env` (flujo netrc de la skill keycloak-admin; el secret
nunca va por argv). `--matrix <ruta>` verifica otra copia de este fichero y
`--config-file <config.yaml>` otra copia del config. Comprueba:

1. cada ruta del config está en la matriz con el mismo path, los mismos roles de
   ruta y, por rol, el mismo conjunto de tools; y ninguna ruta de la matriz falta
   en el config;
2. todo rol referenciado en el config existe en el realm;
3. todo rol gateway vivo (`agentgateway-*` del realm, o cualquiera que el config
   referencie) está en una ruta o en `unrouted`; ningún rol de `unrouted` lo
   exige el config ni falta del realm.

Cuando una ruta cambie de gate en el gateway, esta matriz cambia en una PR de
este repo; el verificador dice qué fila.

## Decisión del CTO: `agentgateway-write:dgx-control` (INFRA-249)

`/dgx-control` y `/chat-dgx-control` gatean `compute_mode_set`,
`refusal_lambda_set` y `opencode_restart` en `agentgateway-write:dgx-control`,
un rol que el 24-09-2026 **no existía en el realm** (verificador: `DRIFT:
agentgateway-write:dgx-control referenciado en config y ausente del realm`).
Decisión del CTO (INFRA-219, no se reabre): se **añade** el rol al reconciliador
`scripts/agentgateway-domain-roles.sh` **sin concederlo a nadie** (sin entrada en
`ALLOWED_SERVICE_ACCOUNTS`, `grantees: []` en `ROLES.yaml`). Es inerte: las tres
tools siguen denegadas para todo token, y el hook falla si alguien lo tiene.
Concederlo exige revisar un client dedicado y su entrada en la allowlist, como
los pares de `chat-agentgateway`. No se toca el `require:` de ninguna ruta.

## Roles sin ruta

| rol | disposición | para qué existe |
|---|---|---|
| `agentgateway-read:dgx-control` | reservado | /dgx-control y /chat-dgx-control no exigen rol lector: compute_mode_get y refusal_lambda_get se permiten a cualquier JWT valido del issuer y la audiencia. agentgateway-read-grants.sh lo concede a agentgateway-mcp (matriz R2, INFRA-44) para que la ruta pueda adoptar un require sin cortar a su cliente. |
| `agentgateway-read:image` | reservado | Ruta /image retirada 24-09 (imagen = solo studio_generate_image en /studio y /chat-studio); el rol sigue vivo, no se borra. Concedido a agentgateway-mcp por agentgateway-read-grants.sh (INFRA-44). |
| `agentgateway-read:offers` | reservado | /offers no exige rol lector: offers_search y offers_test_connection se permiten a cualquier JWT valido. Concedido a agentgateway-mcp y openclaw-readonly-agentgateway por agentgateway-read-grants.sh (INFRA-44) para cuando la ruta adopte un require. |
| `agentgateway-read:tts` | reservado | /tts y /chat-tts no exigen rol lector: tts_list_voices, tts_health y tts_voice_design_spec se permiten a cualquier JWT valido. Concedido a agentgateway-mcp por agentgateway-read-grants.sh (INFRA-44) para cuando la ruta adopte un require. |
| `claude-sessions` | aplicacion | Rol de aplicacion del servicio chat-session-trigger (OWU-27): el propio backend decide quien crea y sigue sesiones de Claude CLI desde el chat. El gateway no lo lee; /claude-sessions se gatea con agentgateway-read:claude-sessions y agentgateway-write:claude-sessions. |

`analytics`, `skirmshop-plugins`, `stt` y `weight` figuraban sin ruta en el
spec de INFRA-249: el config vivo del 24-09-2026 ya los exige (`/analytics`,
`/skirmshop-plugins`, `/stt`, `/weight`), así que están en la matriz de rutas.
Los tres roles de OWU-27: `agentgateway-read:claude-sessions` y
`agentgateway-write:claude-sessions` gatean `/claude-sessions` (rutas
`claude-sessions-read` y `claude-sessions-write`); `claude-sessions` está arriba.

Fuera de alcance (no son roles gateway ni los lee el config):
`default-roles-edani`, `offline_access`, `uma_authorization`. El catálogo de
todos los roles del realm es `ROLES.yaml`.

## Resumen por ruta

Rutas `chat-*` sin rol de ruta: su entrada la autentica `mcpAuthentication`
(usuario del chat); los roles que aparecen son los de sus tools de escritura.

| ruta | path | rol de ruta | roles por tool (nº tools) |
|---|---|---|---|
| `sauvage-admin` | `/sauvage-admin` | `agentgateway-write:sauvage` | `agentgateway-write:sauvage` (7) |
| `synapse-sre-m2m` | `/synapse-sre-m2m` | `synapse-sre-m2m` | `synapse-sre-m2m` (3) |
| `synapse-sre` | `/synapse-sre` | `agentgateway-read:synapse-sre` | — |
| `synapse-agent-m2m` | `/synapse-agent-m2m` | `synapse-draft-m2m` | `synapse-draft-m2m` (2) |
| `synapse-tools` | `/synapse-tools` | `agentgateway-read:synapse-tools` | `agentgateway-write` (5), `agentgateway-write:synapse` (5) |
| `chat-synapse` | `/chat-synapse` | — | `agentgateway-write` (3), `agentgateway-write:synapse` (3) |
| `synapse` | `/synapse` | `agentgateway-read:synapse` | `agentgateway-write` (3), `agentgateway-write:synapse` (3) |
| `chat-stt` | `/chat-stt` | — | — |
| `stt` | `/stt` | `agentgateway-read:stt` | — |
| `picqer` | `/picqer` | `agentgateway-read:picqer` | `agentgateway-write` (36), `agentgateway-write:picqer` (36) |
| `skirmshop-plugins-admin` | `/skirmshop-plugins-admin` | `agentgateway-write`, `agentgateway-write:skirmshop-plugins` | `agentgateway-write` (35), `agentgateway-write:skirmshop-plugins` (35) |
| `skirmshop-plugins` | `/skirmshop-plugins` | `agentgateway-read:skirmshop-plugins` | — |
| `shopify-admin` | `/shopify-admin` | `agentgateway-read:shopify-admin` | `agentgateway-write` (18), `agentgateway-write:shopify` (18) |
| `shopify` | `/shopify` | `agentgateway-read:shopify` | `agentgateway-write` (5), `agentgateway-write:shopify` (5) |
| `chat-analytics` | `/chat-analytics` | — | — |
| `analytics` | `/analytics` | `agentgateway-read:analytics` | — |
| `chat-brain` | `/chat-brain` | — | — |
| `brain` | `/brain` | `agentgateway-read:brain` | — |
| `social` | `/social` | `agentgateway-read:social` | `agentgateway-write` (13), `agentgateway-write:social` (13) |
| `chat-tts` | `/chat-tts` | — | `agentgateway-write` (2), `agentgateway-write:media` (2) |
| `hermes` | `/hermes` | — | `agentgateway-write` (2), `agentgateway-write:hermes` (2) |
| `browser` | `/browser` | — | `agentgateway-write` (38) |
| `tts` | `/tts` | — | `agentgateway-write` (2), `agentgateway-write:media` (2) |
| `weight` | `/weight` | `agentgateway-read:weight` | — |
| `chat-dgx-control` | `/chat-dgx-control` | — | `agentgateway-write:dgx-control` (3) |
| `dgx-control` | `/dgx-control` | — | `agentgateway-write:dgx-control` (3) |
| `chat-studio` | `/chat-studio` | — | `agentgateway-write` (5), `agentgateway-write:media` (5) |
| `studio` | `/studio` | `agentgateway-read:studio` | `agentgateway-write` (5), `agentgateway-write:media` (5) |
| `grok` | `/grok` | — | `agentgateway-write` (2), `agentgateway-write:media` (2) |
| `workspace` | `/workspace` | `agentgateway-read:workspace` | `agentgateway-write` (17), `agentgateway-write:workspace` (17) |
| `chat-workspace` | `/chat-workspace` | — | `agentgateway-write` (17), `agentgateway-write:workspace` (17) |
| `chat-gsc` | `/chat-gsc` | — | `agentgateway-write` (1), `agentgateway-write:gsc` (1) |
| `gsc` | `/gsc` | `agentgateway-read:gsc` | `agentgateway-write` (1), `agentgateway-write:gsc` (1) |
| `merchant` | `/merchant` | `agentgateway-read:merchant` | — |
| `offers` | `/offers` | — | `agentgateway-write` (3), `agentgateway-write:offers` (3) |
| `cto-office` | `/cto-office` | `cto-office-send` | `cto-office-send` (2) |
| `company-metrics` | `/company-metrics` | `company-metrics-read` | `company-metrics-read` (5) |
| `chat-atlassian` | `/chat-atlassian` | — | `agentgateway-write` (40) |
| `atlassian` | `/atlassian` | `agentgateway-read:atlassian` | `agentgateway-write` (40) |
| `1password` | `/1password` | — | `agentgateway-write` (8) |
| `claude-sessions-read` | `/claude-sessions` | `agentgateway-read:claude-sessions` | — |
| `claude-sessions-write` | `/claude-sessions` | `agentgateway-write:claude-sessions` | — |

## Matriz (fuente del verificador)

```json
{
  "schema": "agentgateway-route-roles/v1",
  "measured": "2026-09-24, ConfigMap agentgateway/agentgateway-config resourceVersion 234195236",
  "routes": [
    {
      "route": "sauvage-admin",
      "path": "/sauvage-admin",
      "require": ["agentgateway-write:sauvage"],
      "tools": {
        "agentgateway-write:sauvage": ["sauvage_contest_begin_finalize", "sauvage_contest_confirm_finalize", "sauvage_contest_create_draft", "sauvage_contest_get", "sauvage_contest_leaderboard", "sauvage_contest_list", "sauvage_contest_publish"]
      }
    },
    {
      "route": "synapse-sre-m2m",
      "path": "/synapse-sre-m2m",
      "require": ["synapse-sre-m2m"],
      "tools": {
        "synapse-sre-m2m": ["synapse_sre_action_request", "synapse_sre_approval_record", "synapse_sre_run_complete"]
      }
    },
    {
      "route": "synapse-sre",
      "path": "/synapse-sre",
      "require": ["agentgateway-read:synapse-sre"],
      "tools": {}
    },
    {
      "route": "synapse-agent-m2m",
      "path": "/synapse-agent-m2m",
      "require": ["synapse-draft-m2m"],
      "tools": {
        "synapse-draft-m2m": ["synapse_agent_run_claim", "synapse_agent_run_complete"]
      }
    },
    {
      "route": "synapse-tools",
      "path": "/synapse-tools",
      "require": ["agentgateway-read:synapse-tools"],
      "tools": {
        "agentgateway-write": ["synapse_archive_expense_pdf_to_drive", "synapse_give_up", "synapse_record_expense", "synapse_shopify_backorder_enable", "synapse_shopify_sku_repoint"],
        "agentgateway-write:synapse": ["synapse_archive_expense_pdf_to_drive", "synapse_give_up", "synapse_record_expense", "synapse_shopify_backorder_enable", "synapse_shopify_sku_repoint"]
      }
    },
    {
      "route": "chat-synapse",
      "path": "/chat-synapse",
      "require": [],
      "tools": {
        "agentgateway-write": ["product_creator_create_request", "refresh_api_docs", "skirmbooks_invoice_search_request"],
        "agentgateway-write:synapse": ["product_creator_create_request", "refresh_api_docs", "skirmbooks_invoice_search_request"]
      }
    },
    {
      "route": "synapse",
      "path": "/synapse",
      "require": ["agentgateway-read:synapse"],
      "tools": {
        "agentgateway-write": ["product_creator_create_request", "refresh_api_docs", "skirmbooks_invoice_search_request"],
        "agentgateway-write:synapse": ["product_creator_create_request", "refresh_api_docs", "skirmbooks_invoice_search_request"]
      }
    },
    {
      "route": "chat-stt",
      "path": "/chat-stt",
      "require": [],
      "tools": {}
    },
    {
      "route": "stt",
      "path": "/stt",
      "require": ["agentgateway-read:stt"],
      "tools": {}
    },
    {
      "route": "picqer",
      "path": "/picqer",
      "require": ["agentgateway-read:picqer"],
      "tools": {
        "agentgateway-write": ["picqer_api", "picqer_backorders", "picqer_comments", "picqer_customer_addresses", "picqer_customers", "picqer_fulfilment", "picqer_location_types", "picqer_locations", "picqer_order_actions", "picqer_order_fields", "picqer_order_products", "picqer_orders", "picqer_packagings", "picqer_picking_containers", "picqer_picklist_batches", "picqer_picklist_comments", "picqer_picklist_products", "picqer_picklist_shipments", "picqer_picklists", "picqer_product_comments", "picqer_product_images", "picqer_product_locations", "picqer_product_parts", "picqer_product_stock", "picqer_products", "picqer_purchase_order_products", "picqer_purchase_orders", "picqer_receipts", "picqer_resource_tags", "picqer_return_comments", "picqer_return_products", "picqer_returns", "picqer_suppliers", "picqer_tags", "picqer_tasks", "picqer_webhooks"],
        "agentgateway-write:picqer": ["picqer_api", "picqer_backorders", "picqer_comments", "picqer_customer_addresses", "picqer_customers", "picqer_fulfilment", "picqer_location_types", "picqer_locations", "picqer_order_actions", "picqer_order_fields", "picqer_order_products", "picqer_orders", "picqer_packagings", "picqer_picking_containers", "picqer_picklist_batches", "picqer_picklist_comments", "picqer_picklist_products", "picqer_picklist_shipments", "picqer_picklists", "picqer_product_comments", "picqer_product_images", "picqer_product_locations", "picqer_product_parts", "picqer_product_stock", "picqer_products", "picqer_purchase_order_products", "picqer_purchase_orders", "picqer_receipts", "picqer_resource_tags", "picqer_return_comments", "picqer_return_products", "picqer_returns", "picqer_suppliers", "picqer_tags", "picqer_tasks", "picqer_webhooks"]
      }
    },
    {
      "route": "skirmshop-plugins-admin",
      "path": "/skirmshop-plugins-admin",
      "require": ["agentgateway-write", "agentgateway-write:skirmshop-plugins"],
      "tools": {
        "agentgateway-write": ["affiliate_api", "back_in_stock_api", "bundles_api", "catalog_rag_api", "catalog_rag_competitor_coverage", "catalog_rag_competitor_price_comparison", "catalog_rag_competitor_products", "catalog_rag_competitor_rescue_candidates", "catalog_rag_competitor_source", "catalog_rag_competitor_sources", "chatbot_api", "collections_tree_api", "labels_api", "labels_carrier_service_rates", "labels_correos_fuel_surcharge", "labels_create_label", "labels_latest_order_status", "labels_pickup_create", "labels_rate_quote", "labels_shipment_status", "picker_api", "serial_numbers_api", "shopify_sync_api", "sii_api", "skirmbooks_reconcile_invoices", "skirmbooks_reconcile_movements", "skirmbooks_reconcile_summary", "skirmbooks_reconcile_upload_invoice", "skirmshop_plugins_call", "skirmshop_plugins_describe", "skirmshop_plugins_get", "skirmshop_plugins_list", "skirmshop_plugins_request", "skirmshop_plugins_tools_list", "translations_api"],
        "agentgateway-write:skirmshop-plugins": ["affiliate_api", "back_in_stock_api", "bundles_api", "catalog_rag_api", "catalog_rag_competitor_coverage", "catalog_rag_competitor_price_comparison", "catalog_rag_competitor_products", "catalog_rag_competitor_rescue_candidates", "catalog_rag_competitor_source", "catalog_rag_competitor_sources", "chatbot_api", "collections_tree_api", "labels_api", "labels_carrier_service_rates", "labels_correos_fuel_surcharge", "labels_create_label", "labels_latest_order_status", "labels_pickup_create", "labels_rate_quote", "labels_shipment_status", "picker_api", "serial_numbers_api", "shopify_sync_api", "sii_api", "skirmbooks_reconcile_invoices", "skirmbooks_reconcile_movements", "skirmbooks_reconcile_summary", "skirmbooks_reconcile_upload_invoice", "skirmshop_plugins_call", "skirmshop_plugins_describe", "skirmshop_plugins_get", "skirmshop_plugins_list", "skirmshop_plugins_request", "skirmshop_plugins_tools_list", "translations_api"]
      }
    },
    {
      "route": "skirmshop-plugins",
      "path": "/skirmshop-plugins",
      "require": ["agentgateway-read:skirmshop-plugins"],
      "tools": {}
    },
    {
      "route": "shopify-admin",
      "path": "/shopify-admin",
      "require": ["agentgateway-read:shopify-admin"],
      "tools": {
        "agentgateway-write": ["collection_create", "collection_delete", "customer_create", "customer_update", "draft_order_create", "graphql_execute", "metafields_set", "order_returnable_lines_get", "order_shipping_line_replace", "product_archive_or_delete", "product_collection_connect", "product_collection_disconnect", "product_create", "product_publish_toggle", "product_update", "return_create", "translations_register", "variant_update"],
        "agentgateway-write:shopify": ["collection_create", "collection_delete", "customer_create", "customer_update", "draft_order_create", "graphql_execute", "metafields_set", "order_returnable_lines_get", "order_shipping_line_replace", "product_archive_or_delete", "product_collection_connect", "product_collection_disconnect", "product_create", "product_publish_toggle", "product_update", "return_create", "translations_register", "variant_update"]
      }
    },
    {
      "route": "shopify",
      "path": "/shopify",
      "require": ["agentgateway-read:shopify"],
      "tools": {
        "agentgateway-write": ["complete-draft-order", "create-discount", "create-draft-order", "manage-webhook", "tag-customer"],
        "agentgateway-write:shopify": ["complete-draft-order", "create-discount", "create-draft-order", "manage-webhook", "tag-customer"]
      }
    },
    {
      "route": "chat-analytics",
      "path": "/chat-analytics",
      "require": [],
      "tools": {}
    },
    {
      "route": "analytics",
      "path": "/analytics",
      "require": ["agentgateway-read:analytics"],
      "tools": {}
    },
    {
      "route": "chat-brain",
      "path": "/chat-brain",
      "require": [],
      "tools": {}
    },
    {
      "route": "brain",
      "path": "/brain",
      "require": ["agentgateway-read:brain"],
      "tools": {}
    },
    {
      "route": "social",
      "path": "/social",
      "require": ["agentgateway-read:social"],
      "tools": {
        "agentgateway-write": ["social_approve_draft", "social_click_interaction", "social_create_draft", "social_delete_message", "social_forward_message", "social_manage_chat", "social_manage_comment", "social_manage_forum", "social_manage_session", "social_mark_read", "social_publish_content", "social_send_draft", "social_send_message"],
        "agentgateway-write:social": ["social_approve_draft", "social_click_interaction", "social_create_draft", "social_delete_message", "social_forward_message", "social_manage_chat", "social_manage_comment", "social_manage_forum", "social_manage_session", "social_mark_read", "social_publish_content", "social_send_draft", "social_send_message"]
      }
    },
    {
      "route": "chat-tts",
      "path": "/chat-tts",
      "require": [],
      "tools": {
        "agentgateway-write": ["tts_design", "tts_speak"],
        "agentgateway-write:media": ["tts_design", "tts_speak"]
      }
    },
    {
      "route": "hermes",
      "path": "/hermes",
      "require": [],
      "tools": {
        "agentgateway-write": ["messages_send", "permissions_respond"],
        "agentgateway-write:hermes": ["messages_send", "permissions_respond"]
      }
    },
    {
      "route": "browser",
      "path": "/browser",
      "require": [],
      "tools": {
        "agentgateway-write": ["browser_click", "browser_close_tab", "browser_drag", "browser_drop", "browser_evaluate", "browser_fill_form", "browser_fill_secret", "browser_find", "browser_get_attribute", "browser_get_console_logs", "browser_get_html", "browser_get_text", "browser_go_back", "browser_go_forward", "browser_highlight", "browser_hover", "browser_iframe_click", "browser_iframe_eval", "browser_is_visible", "browser_list_connections", "browser_list_tabs", "browser_navigate", "browser_network_request", "browser_network_requests", "browser_new_tab", "browser_pdf", "browser_press_key", "browser_reload", "browser_resize_viewport", "browser_screenshot", "browser_select_option", "browser_snapshot", "browser_state", "browser_switch_tab", "browser_type", "browser_upload_file", "browser_wait", "browser_wait_for_element"]
      }
    },
    {
      "route": "tts",
      "path": "/tts",
      "require": [],
      "tools": {
        "agentgateway-write": ["tts_design", "tts_speak"],
        "agentgateway-write:media": ["tts_design", "tts_speak"]
      }
    },
    {
      "route": "weight",
      "path": "/weight",
      "require": ["agentgateway-read:weight"],
      "tools": {}
    },
    {
      "route": "chat-dgx-control",
      "path": "/chat-dgx-control",
      "require": [],
      "tools": {
        "agentgateway-write:dgx-control": ["compute_mode_set", "opencode_restart", "refusal_lambda_set"]
      }
    },
    {
      "route": "dgx-control",
      "path": "/dgx-control",
      "require": [],
      "tools": {
        "agentgateway-write:dgx-control": ["compute_mode_set", "opencode_restart", "refusal_lambda_set"]
      }
    },
    {
      "route": "chat-studio",
      "path": "/chat-studio",
      "require": [],
      "tools": {
        "agentgateway-write": ["studio_cancel_job", "studio_generate_image", "studio_generate_video", "studio_voice_clone", "studio_voice_clone_publish"],
        "agentgateway-write:media": ["studio_cancel_job", "studio_generate_image", "studio_generate_video", "studio_voice_clone", "studio_voice_clone_publish"]
      }
    },
    {
      "route": "studio",
      "path": "/studio",
      "require": ["agentgateway-read:studio"],
      "tools": {
        "agentgateway-write": ["studio_cancel_job", "studio_generate_image", "studio_generate_video", "studio_voice_clone", "studio_voice_clone_publish"],
        "agentgateway-write:media": ["studio_cancel_job", "studio_generate_image", "studio_generate_video", "studio_voice_clone", "studio_voice_clone_publish"]
      }
    },
    {
      "route": "grok",
      "path": "/grok",
      "require": [],
      "tools": {
        "agentgateway-write": ["grok_generate_image", "grok_generate_video"],
        "agentgateway-write:media": ["grok_generate_image", "grok_generate_video"]
      }
    },
    {
      "route": "workspace",
      "path": "/workspace",
      "require": ["agentgateway-read:workspace"],
      "tools": {
        "agentgateway-write": ["calendar_create_event", "drive_create_file", "gmail_apply_labels", "gmail_archive", "gmail_batch_modify", "gmail_bulk_label_matching", "gmail_create_draft", "gmail_create_label", "gmail_delete_draft", "gmail_forward", "gmail_mark_read", "gmail_mark_unread", "gmail_send", "gmail_send_draft", "gmail_trash", "gmail_untrash", "gmail_update_draft"],
        "agentgateway-write:workspace": ["calendar_create_event", "drive_create_file", "gmail_apply_labels", "gmail_archive", "gmail_batch_modify", "gmail_bulk_label_matching", "gmail_create_draft", "gmail_create_label", "gmail_delete_draft", "gmail_forward", "gmail_mark_read", "gmail_mark_unread", "gmail_send", "gmail_send_draft", "gmail_trash", "gmail_untrash", "gmail_update_draft"]
      }
    },
    {
      "route": "chat-workspace",
      "path": "/chat-workspace",
      "require": [],
      "tools": {
        "agentgateway-write": ["calendar_create_event", "drive_create_file", "gmail_apply_labels", "gmail_archive", "gmail_batch_modify", "gmail_bulk_label_matching", "gmail_create_draft", "gmail_create_label", "gmail_delete_draft", "gmail_forward", "gmail_mark_read", "gmail_mark_unread", "gmail_send", "gmail_send_draft", "gmail_trash", "gmail_untrash", "gmail_update_draft"],
        "agentgateway-write:workspace": ["calendar_create_event", "drive_create_file", "gmail_apply_labels", "gmail_archive", "gmail_batch_modify", "gmail_bulk_label_matching", "gmail_create_draft", "gmail_create_label", "gmail_delete_draft", "gmail_forward", "gmail_mark_read", "gmail_mark_unread", "gmail_send", "gmail_send_draft", "gmail_trash", "gmail_untrash", "gmail_update_draft"]
      }
    },
    {
      "route": "chat-gsc",
      "path": "/chat-gsc",
      "require": [],
      "tools": {
        "agentgateway-write": ["submit_sitemap"],
        "agentgateway-write:gsc": ["submit_sitemap"]
      }
    },
    {
      "route": "gsc",
      "path": "/gsc",
      "require": ["agentgateway-read:gsc"],
      "tools": {
        "agentgateway-write": ["submit_sitemap"],
        "agentgateway-write:gsc": ["submit_sitemap"]
      }
    },
    {
      "route": "merchant",
      "path": "/merchant",
      "require": ["agentgateway-read:merchant"],
      "tools": {}
    },
    {
      "route": "offers",
      "path": "/offers",
      "require": [],
      "tools": {
        "agentgateway-write": ["offers_dismiss", "offers_import", "offers_link"],
        "agentgateway-write:offers": ["offers_dismiss", "offers_import", "offers_link"]
      }
    },
    {
      "route": "cto-office",
      "path": "/cto-office",
      "require": ["cto-office-send"],
      "tools": {
        "cto-office-send": ["cto_office_fetch", "cto_office_send"]
      }
    },
    {
      "route": "company-metrics",
      "path": "/company-metrics",
      "require": ["company-metrics-read"],
      "tools": {
        "company-metrics-read": ["company_activity", "company_config", "company_session_aggregates", "company_session_index", "company_status"]
      }
    },
    {
      "route": "chat-atlassian",
      "path": "/chat-atlassian",
      "require": [],
      "tools": {
        "agentgateway-write": ["confluence_add_comment", "confluence_add_inline_comment", "confluence_add_label", "confluence_copy_page", "confluence_create_page", "confluence_create_page_from_template", "confluence_delete_attachment", "confluence_delete_page", "confluence_move_page", "confluence_reply_to_comment", "confluence_set_page_restrictions", "confluence_update_page", "confluence_update_page_section", "confluence_upload_attachment", "confluence_upload_attachments", "jira_add_comment", "jira_add_issues_to_sprint", "jira_add_watcher", "jira_add_worklog", "jira_assign_issue", "jira_batch_create_issues", "jira_batch_create_versions", "jira_create_customer_request", "jira_create_issue", "jira_create_issue_link", "jira_create_remote_issue_link", "jira_create_sprint", "jira_create_version", "jira_delete_issue", "jira_edit_comment", "jira_link_to_epic", "jira_move_issue", "jira_move_issues_to_backlog", "jira_remove_issue_link", "jira_remove_watcher", "jira_transition_issue", "jira_update_issue", "jira_update_proforma_form_answers", "jira_update_sprint", "jira_update_version"]
      }
    },
    {
      "route": "atlassian",
      "path": "/atlassian",
      "require": ["agentgateway-read:atlassian"],
      "tools": {
        "agentgateway-write": ["confluence_add_comment", "confluence_add_inline_comment", "confluence_add_label", "confluence_copy_page", "confluence_create_page", "confluence_create_page_from_template", "confluence_delete_attachment", "confluence_delete_page", "confluence_move_page", "confluence_reply_to_comment", "confluence_set_page_restrictions", "confluence_update_page", "confluence_update_page_section", "confluence_upload_attachment", "confluence_upload_attachments", "jira_add_comment", "jira_add_issues_to_sprint", "jira_add_watcher", "jira_add_worklog", "jira_assign_issue", "jira_batch_create_issues", "jira_batch_create_versions", "jira_create_customer_request", "jira_create_issue", "jira_create_issue_link", "jira_create_remote_issue_link", "jira_create_sprint", "jira_create_version", "jira_delete_issue", "jira_edit_comment", "jira_link_to_epic", "jira_move_issue", "jira_move_issues_to_backlog", "jira_remove_issue_link", "jira_remove_watcher", "jira_transition_issue", "jira_update_issue", "jira_update_proforma_form_answers", "jira_update_sprint", "jira_update_version"]
      }
    },
    {
      "route": "1password",
      "path": "/1password",
      "require": [],
      "tools": {
        "agentgateway-write": ["item_archive", "item_delete", "item_edit", "note_create", "password_create", "password_generate", "password_generate_memorable", "password_update"]
      }
    },
    {
      "route": "claude-sessions-read",
      "path": "/claude-sessions",
      "require": ["agentgateway-read:claude-sessions"],
      "tools": {}
    },
    {
      "route": "claude-sessions-write",
      "path": "/claude-sessions",
      "require": ["agentgateway-write:claude-sessions"],
      "tools": {}
    }
  ],
  "unrouted": [
    {"role": "agentgateway-read:dgx-control", "disposition": "reservado", "purpose": "/dgx-control y /chat-dgx-control no exigen rol lector: compute_mode_get y refusal_lambda_get se permiten a cualquier JWT valido del issuer y la audiencia. agentgateway-read-grants.sh lo concede a agentgateway-mcp (matriz R2, INFRA-44) para que la ruta pueda adoptar un require sin cortar a su cliente."},
    {"role": "agentgateway-read:image", "disposition": "reservado", "purpose": "Ruta /image retirada 24-09 (imagen = solo studio_generate_image en /studio y /chat-studio); el rol sigue vivo, no se borra. Concedido a agentgateway-mcp por agentgateway-read-grants.sh (INFRA-44)."},
    {"role": "agentgateway-read:offers", "disposition": "reservado", "purpose": "/offers no exige rol lector: offers_search y offers_test_connection se permiten a cualquier JWT valido. Concedido a agentgateway-mcp y openclaw-readonly-agentgateway por agentgateway-read-grants.sh (INFRA-44) para cuando la ruta adopte un require."},
    {"role": "agentgateway-read:tts", "disposition": "reservado", "purpose": "/tts y /chat-tts no exigen rol lector: tts_list_voices, tts_health y tts_voice_design_spec se permiten a cualquier JWT valido. Concedido a agentgateway-mcp por agentgateway-read-grants.sh (INFRA-44) para cuando la ruta adopte un require."},
    {"role": "claude-sessions", "disposition": "aplicacion", "purpose": "Rol de aplicacion del servicio chat-session-trigger (OWU-27): el propio backend decide quien crea y sigue sesiones de Claude CLI desde el chat. El gateway no lo lee; /claude-sessions se gatea con agentgateway-read:claude-sessions y agentgateway-write:claude-sessions."}
  ]
}
```
