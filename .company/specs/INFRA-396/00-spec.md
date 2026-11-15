Rol: pm · Fecha: 2026-10-02T19:35:00Z · Sesión: 02912cd6-bc3d-420c-b369-81e887a652fb · Estado: LISTO

## Objetivo

Modernizar la capa visual de www.e-dani.com (web corporativa Astro, ES/EN) aplicando el rediseño del diseñador de la compañía: hero con movimiento, micro-animaciones al scroll, tipografía display, paleta dark/light coherente, variantes móvil e imágenes generadas con krea2. La web actual rinde perfecto (Lighthouse ES 100/100/100 medido 02-10 07:42Z): el trabajo es visual, sin romper SEO, hreflang, CSP ni rendimiento.

Esta épica CONSOLIDA a SC-1408 (duplicado, mismo repo y objetivo, cancelada por Dani el 02-10 02:34Z, como señaló el CTO el 01-10 22:10): sus requisitos extra (imágenes krea2 y criterios heredados de SC-1333) viven solo aquí (C6, C7).

Repo: k8s-web-pocharlies

## Criterios de aceptación

- [ ] C1. Dani aprueba el canvas del diseño ANTES de implementar.
  Comando: `python3 ~/.local/libexec/x86-host-runtime/jira_rest.py attachments --rol pm INFRA-396`
  Esperado: lista un `diseno-*.dc.html` del rediseño final (no solo `diseno-web-edani-home-mockup.dc.html`) y los comentarios de la épica incluyen la aprobación de Dani. Sin ambos, la historia de implementación no entra en In Progress.

- [ ] C2. Lighthouse mayor o igual 95 en performance y accesibilidad, en ES y en EN (móvil).
  Comando (repetir con https://www.e-dani.com/en/ y /tmp/lh-en.json):
  `npx --no-install lighthouse https://www.e-dani.com/ --only-categories=performance,accessibility,best-practices,seo --quiet --chrome-flags="--headless=new --no-sandbox" --output=json --output-path=/tmp/lh-es.json && python3 -c "import json;d=json.load(open('/tmp/lh-es.json'));print({k:round(v['score']*100) for k,v in d['categories'].items()})"`
  Esperado: performance y accessibility >= 95 en ambas rutas (y las 4 categorías >= 90, ver C6). Base 02-10 07:42Z: ES 100/100/100 (perf/a11y/seo). Las animaciones respetan `prefers-reduced-motion` (es lo que sostiene la accesibilidad). LCP móvil < 2,5 s (`d['audits']['largest-contentful-paint']['numericValue']` < 2500).

- [ ] C3. SEO y hreflang intactos.
  Comando: `curl -s https://www.e-dani.com/ | grep -o 'hreflang="[a-z-]*"' | sort -u`
  Esperado: exactamente `hreflang="en"`, `hreflang="es"`, `hreflang="x-default"`.
  Comando: `curl -s -o /dev/null -w "%{http_code}\n" https://www.e-dani.com/sitemap-index.xml` → `200` (y `/sitemap-0.xml` → `200`; `curl -s https://www.e-dani.com/robots.txt | grep -i sitemap` lo referencia). OJO: `/sitemap.xml` da 404 hoy y NO es el criterio (corrección del spec anterior). No cambiar ninguna URL de página (las legales las consumen las fichas de App Store — ver ARCHITECTURE.md).

- [ ] C4. Web publicada en producción ES/EN con el nuevo diseño, no solo mergeada.
  Comandos:
  `curl -sI https://www.e-dani.com/ | head -1` → `HTTP/2 200`; `curl -sI https://www.e-dani.com/en/ | head -1` → `HTTP/2 200`
  `kubectl -n argocd get app web -o jsonpath='{.status.sync.status} {.status.health.status}'` → `Synced Healthy`
  `kubectl get deploy web-edani -n web -o jsonpath='{.spec.template.spec.containers[0].image}'` → tag sha DISTINTO de `ea6ee4551085bb3c71579d7f741b96657831c67a` (imagen desplegada hoy, `harbor.e-dani.com/homelab/web-edani`) e igual al `newTag` del segundo commit en `k8s/kustomization.yaml` (el que construyó la CI del merge).

- [ ] C5. El movimiento está realmente en producción (no solo en el repo).
  Comando: `for f in $(curl -s https://www.e-dani.com/ | grep -oE '/_astro/[^"]+\.js'); do curl -s "https://www.e-dani.com$f"; done | grep -c IntersectionObserver`
  Esperado: mayor o igual 1 (baseline hoy: 0). El JS de animaciones va en fichero externo (CSP sin `unsafe-inline`). Con `prefers-reduced-motion: reduce` no hay animación (qa lo comprueba emulándolo). qa confirma con captura del hero antes/durante la animación.

- [ ] C6. Criterios heredados de SC-1333 (siguen vigentes).
  Comandos y esperado:
  - Pie legal en todas las páginas: `for u in / /en/ /soporte/ /apps/privacidad/; do echo -n "$u "; curl -s "https://www.e-dani.com$u" | grep -c 'B13959085'; done` → cada línea >= 1 (texto «MORENOIBAÑEZ S.L. · NIF B13959085»; hoy la home da 1).
  - Públicas: `curl -s -o /dev/null -w "%{http_code}\n" https://www.e-dani.com/soporte/` → `200`; `curl -s -o /dev/null -w "%{http_code}\n" https://www.e-dani.com/apps/privacidad/` → `200`.
  - CSP estricta: `curl -sI https://www.e-dani.com/ | grep -i '^content-security-policy'` debe contener `default-src 'self'`, `base-uri 'self'`, `form-action 'self'`, `frame-ancestors 'none'`, `object-src 'none'`, `img-src 'self' data:`, `upgrade-insecure-requests`; y `curl -sI https://www.e-dani.com/ | grep -i '^content-security-policy' | grep -c unsafe-inline` → `0`.
  - Cero terceros: `curl -s https://www.e-dani.com/ | grep -oE '(src|href)="https?://[^"]+"' | grep -v 'www.e-dani.com' | wc -l` → `0` (repetir en /en/); qa además lista las peticiones de red con el navegador headless y todas son a www.e-dani.com.
  - Sin analítica ni cookies no técnicas: `curl -sI https://www.e-dani.com/ | grep -ci '^set-cookie'` → `0` y el HTML no contiene `gtag`, `googletagmanager`, `analytics` (`grep -ciE 'gtag|googletagmanager|analytics'` → `0`).
  - Lighthouse móvil >= 90 en las 4 categorías (performance, accessibility, best-practices, seo) en ES y EN, con el comando de C2.

- [ ] C7. Imágenes krea2 como assets propios.
  Generadas con el motor krea2 (`studio_generate_image`): mínimo 1 hero + 1 por línea de solución + portadas de los casos del portfolio; coherentes entre sí, SIN texto embebido en la imagen.
  Comandos y esperado:
  - `curl -s https://www.e-dani.com/ | grep -o '<img ' | wc -l` → mayor que 0 (hoy 0); mínimo = 1 hero + nº de líneas de solución + nº de casos del portfolio (el qa fija el número exacto con el canvas aprobado).
  - Servidas desde el propio dominio: `curl -s https://www.e-dani.com/ | grep -oE '<img[^>]+src="[^"]+"' | grep -vcE 'src="(/|https://www.e-dani.com/)'` → `0`.
  - AVIF/WebP con fallback: `curl -s https://www.e-dani.com/ | grep -ocE 'image/(avif|webp)'` >= 1 (elementos `picture/source`) y `curl -sI` de un `.avif` y un `.webp` servidos → `HTTP/2 200` con `content-type: image/avif` / `image/webp`.
  - Dimensiones explícitas y lazy: todo `img` fuera del hero lleva `width`, `height` y `loading="lazy"`; el hero NO lleva lazy (LCP). `curl -s https://www.e-dani.com/ | grep -oE '<img[^>]*>' | grep -vc 'width='` → `0`.
  - Alt descriptivo no vacío en ES y EN: `curl -s https://www.e-dani.com/ | grep -oE '<img[^>]*>' | grep -c 'alt=""'` → `0`; ídem en `/en/`.
  - Cero requests a terceros por imágenes (img-src 'self' data: de la CSP intacta, ver C6); las imágenes son ficheros del repo, nunca hotlink.
  - LCP móvil < 2,5 s (C2).

## Restricciones

- El tronco es **`main`**, no `deploy/prod` (lo dice ARCHITECTURE.md y el targetRevision de la app ArgoCD `web`; la descripción de la épica se equivoca). PR contra `main`, nunca push directo.
- **Trampa de deploy**: la CI (`build.yml`) construye y sube la imagen a Harbor pero NO despliega. Hace falta un segundo commit subiendo `newTag` en `k8s/kustomization.yaml`; sin él la web no cambia y ArgoCD está en verde.
- CSP sin `'unsafe-inline'`: ni etiquetas style ni script en línea; CSS a `/_astro/*.css` y JS a ficheros (vite `assetsInlineLimit: 0`). Ojo: con `assetsInlineLimit: 0` no se incrustan imágenes como data URI; las imágenes van como ficheros.
- No duplicar páginas por idioma: plantillas compartidas en `src/components/pages/` y correspondencia ES/EN en `src/i18n/routes.ts`. No cambiar URLs existentes.
- No tocar contenido ni textos: cerrado en SC-1335/1339; esto es capa visual (los `alt` son nuevos, no cuentan como cambio de contenido).
- Imágenes solo como assets del repo: cero terceros, cero hotlink, sin texto embebido.
- NO relanzar el mockup: `diseno-web-edani-home-mockup.dc.html` (+ `.handoff.md`, adjunto 02-10 09:47+02, job 20261002-074216-web-edani-home) ya existe.
- La historia de diseño no se despacha hasta que INFRA-395 (skills del diseñador + Opus 5.5) esté Done; enlace Blocks INFRA-395 → INFRA-396 ya existe en Jira.
- Vídeo /brag de redes: fuera de alcance (otro ticket).

## Trabajo reciente (24 h)

- 02-10 ~16:20Z (re-plan): re-medición — sin cambios: INFRA-395 en To Do, repo web sin commits, imagen desplegada ea6ee455, 0 <img> en home.
- 02-10 07:48Z (sesión 284b59a2): spec 15256 adjuntado y enlace Blocks creado.
- 02-10 02:34Z: Dani cancela SC-1408; sus requisitos se consolidan aquí (comentario del CTO 01-10 22:10).
- INFRA-395 avanzada: PR 555 (P1, skills versionadas) qa PASA lista para merge, PR 556 (P2, Opus 5.5) en revisión, INFRA-399 (E2E) creada.
- Repo web sin cambios de código en 24 h (último: 01-10 21:56Z, merge PR 17, docs ARCHITECTURE.md SC-1523).
- Medido hoy en producción: ES/EN 200, hreflang es/en/x-default, NIF en el pie, /soporte/ y /apps/privacidad/ 200, CSP estricta sin unsafe-inline, cero terceros, 0 `<img>` en la home, 0 IntersectionObserver. `/sitemap.xml` da 404; lo real es `/sitemap-index.xml` 200. Imagen desplegada `web-edani:ea6ee4551085bb3c71579d7f741b96657831c67a`, app web Synced Healthy.

## Diseño

Diseñador: sí — el encargo es un rediseño visual profesional de la web con imágenes generadas; es el trabajo del diseñador con sus skills (INFRA-395).

- Mockup de baja fidelidad YA existente: `diseno-web-edani-home-mockup.dc.html` (+ `diseno-web-edani-home-mockup.handoff.md`), adjunto 02-10 09:47+02, job 20261002-074216-web-edani-home. No se relanza.
- Home www.e-dani.com: ES escritorio + EN + móvil, dark/light, hero con movimiento, contadores de trayectoria, tipografía display, grid de soluciones, portada de casos.
- La historia 5 (revisión UX, dueño: designer) revisa lo construido contra el canvas aprobado y deja `nota-designer-ux.md` antes de qa.

## Historias previstas (6)

1. Diseño del rediseño: canvas `.dc.html` final de home ES/EN + móvil, dark/light (dueño: designer) — BLOQUEADA por INFRA-395.
2. Gate de aprobación del canvas por Dani (dueño: pm) — criterio C1; sin él no arrancan la 3 ni la 4.
3. Producción de imágenes krea2 coherentes, AVIF/WebP con alt ES/EN, sin texto embebido (dueño: designer) — tras el gate; criterio C7.
4. Implementación Astro + deploy: hero con movimiento, IntersectionObserver, tipografía, dark/light, móvil, `prefers-reduced-motion`, CSP, imágenes del repo, y segundo commit con bump de `newTag` en `k8s/kustomization.yaml` (dueño: developer) — C4, C5, C6, C7. El deploy va dentro de esta historia, no hay historia devops aparte.
5. Revisión UX contra el canvas aprobado (dueño: designer) — `nota-designer-ux.md`; lo que encuentre lo corrige la 4 antes de qa.
6. QA (dueño: qa) — C2, C3, C6, C7 y verificación ArgoCD/producción de C4 y C5.

## Dificultad

Dificultad: media — un solo repo, sin decisión de arquitectura ni secretos, se deshace con un revert; pero hay que mirar qué existe (CSP sin unsafe-inline, i18n/routes.ts, bump newTag, cero terceros) para no romper una web que hoy puntúa 100.

## Tamaño

M — 6 historias en un repo; el riesgo no es el volumen sino no romper una web que hoy puntúa 100 al introducir imágenes (primeras `<img>` de la home) y movimiento.
