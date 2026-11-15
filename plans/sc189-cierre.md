# Plan SC-189 — cierre (verificar, desplegar lo que falte, QA, veredicto pm)

Estado Jira (leído 15-09): epic en QA; SC-191/193/195 Done. Cierre por cita 08-09:
PR A = #3 x86-host-runtime-pocharlies (merge 365c95f, main); PR B = #258 dgx-infra
(merge a9f2bfc5, master); PR C = #99 k8s-infra-pocharlies (merge 46f7b2b, main).
Despliegue post-merge reportado como hecho 05-09 (restart del responder, digests
re-pineados, IngressRoute vivo, 302 al SSO). Auditoría 14-09: falta QA con evidencia,
Sign-off de pm e informe de cierre (GOB/6750210).

Partes:
1. DEVOPS (verificación + despliegue residual, una sola agente):
   - Merge real de los 3 PR contra el tronco que lee ArgoCD (gh pr view + merge-base
     --is-ancestor; kubectl get application targetRevision si duda).
   - A en el host: sha256 del ~/.local/libexec/x86-host-runtime/claude-rc-status.py
     instalado vs origin/main; /company-view 200 con token; si falta: install.sh +
     systemctl --user restart claude-rc-status (x86 = esta máquina).
   - B: tag ci-<sha> desplegado del dashboard backend/ui desciende de a9f2bfc5; si no,
     workflow_dispatch build-dashboard-backend/ui (gh), comprobar ArgoCD una vez.
   - C: ingressroute edge-company-viewer-public vivo — sso-chain en todas las routes,
     sin ClientIP/priority; curl -I https://company.e-dani.com/ → 302 auth-next.
2. QA (tras devops, criteria de SC-191/193/195 + epic, evidencia pegada):
   lista blanca exacta, no-fuga con origen nombrado (primeros 200 chars del primer
   mensaje usuario de un transcript vivo), /sessions sin cambio de forma, POST 405,
   sin token 401, 302 sin sesión incluso desde LAN/tailnet, página tras SSO (si el
   navegador no está disponible, decirlo tal cual).
3. PM: veredicto funcional criterio a criterio + informe de cierre en GOB/6750210
   (SC-189-nnn) y enlace; flechas Sign-off/Done son suyas.

Done = merges verificados, despliegue verificado/ejecutado, QA pasa con evidencia,
pm da el veredicto y publica el informe.
