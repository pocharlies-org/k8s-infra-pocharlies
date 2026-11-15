Rol: devops · Fecha: 2026-09-17 · Sesión: a5b648df-3f6e-444f-aac4-e582baafc2a8 · Estado: LISTO

# 00-spec — Forense deriva 17-09 (los 69 ES vault-backend)

Spec = despacho del CTO a devops en la sesión a5b648df-3f6e-444f-aac4-e582baafc2a8 (re-auditoría de la épica SC-490, Vault→1Password). Redactada por devops por ser tarea de investigación forense de solo lectura encomendada directamente; no hay código que escribir.

## Contexto (hechos del CTO, 17-09)

- vault-backend subió 47→69 y onepassword bajó 169→138 (el dump del 12-09 da 49→69 / 167→138).
- ES de ns ya migrados apuntan otra vez a vault-backend CON creationTimestamp viejos (skirmshop/catalog-api-client creation 2026-07-10; harbor-runtime-pull en comfyui/libreplay/litellm/shopify-admin-mcp).
- El CPS ya fue borrado por el operador; el ns openclaw está vacío.

## Hipótesis a confirmar/refutar (del tech-lead)

El paquete `_ops/vault-to-1password/huerfanos/` tiene dos árboles: `migrados/` (58 manifiestos store onepassword) y `vivo/` (78 volcados FIELES pre-migración, store vault-backend, para rollback). Un apply sobre objeto existente conserva el creationTimestamp: si alguien reaplicó `vivo/` (o los dumps crudos) en vez de `migrados/`, los ES vuelven a vault-backend con creation viejos. Alternativas a descartar: revert en troncos, syncs a revisiones viejas.

## Trabajo

1. Volco vivo `kubectl get externalsecret -A -o yaml`: los 69 con store vault-backend (ns, nombre, creationTimestamp, annotations).
2. Para cada uno, origen del spec vault-backend actual contra 4 fuentes: (a) tronco git (¿migrado o revertido?), (b) app Argo (sync revision vs HEAD), (c) paquete huerfanos (¿coincide con vivo/ o con migrados/?), (d) nuevos post-12-09 con manifiesto en ~/k8s.
3. Clasificar los 69: (1) revert en tronco, (2) app a revisión vieja, (3) reaplicación as-is (coincide con vivo/), (4) huérfano pendiente del guion, (5) nuevo post-migración con manifiesto viejo, (6) otro.
4. Estado del paquete: ¿migrados/ íntegro (58, onepassword)? ¿vivo/ intacto? ¿alguno de los 69 coincide con los 25 huérfanos del 12-09?
5. Evidencia en `fase6-evidencia/forense-2026-09-17.md` (tabla ns/ES→clase + veredicto por cubo).

## Criterios de aceptación

- [ ] Los 69 clasificados con evidencia de una línea cada uno.
- [ ] Hipótesis del tech-lead confirmada o refutada con evidencia (byte-comparison con vivo/ y migrados/, anotación last-applied, git log de troncos, revisión sincronizada de las apps).
- [ ] Integridad del paquete huerfanos verificada.
- [ ] forense-2026-09-17.md escrito en fase6-evidencia/.
