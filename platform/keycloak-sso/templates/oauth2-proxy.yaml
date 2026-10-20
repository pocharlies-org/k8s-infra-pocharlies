{{- /* SC-2822: por cada web, su oauth2-proxy contra SU realm, con cookie pegada
al host (sin cookie_domains) y su cadena de Traefik sso-<realm>-chain. Ningún
proxy ni cookie se comparte entre realms: es la norma de docs/sso-por-app.md. */ -}}
{{- range $r := .Values.realms }}
{{- $proxy := printf "oauth2-proxy-%s" $r.name }}
{{- $realmPublic := printf "%s/realms/%s/protocol/openid-connect" $.Values.keycloak.publicUrl $r.name }}
{{- $realmInternal := printf "%s/realms/%s/protocol/openid-connect" $.Values.keycloak.internalUrl $r.name }}
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ $proxy }}-config
  namespace: keycloak
  labels:
    app.kubernetes.io/name: {{ $proxy }}
    app.kubernetes.io/component: forward-auth
    e-dani.com/keycloak-realm: {{ $r.name }}
data:
  oauth2_proxy.cfg: |
    provider = "keycloak-oidc"
    provider_display_name = "Keycloak"
    oidc_issuer_url = "{{ $.Values.keycloak.publicUrl }}/realms/{{ $r.name }}"
    skip_oidc_discovery = true
    {{- if $r.google }}
    # Directo a Google: el realm no tiene contraseñas locales.
    login_url = "{{ $realmPublic }}/auth?kc_idp_hint=google"
    {{- else }}
    login_url = "{{ $realmPublic }}/auth"
    {{- end }}
    redeem_url = "{{ $realmInternal }}/token"
    profile_url = "{{ $realmInternal }}/userinfo"
    validate_url = "{{ $realmInternal }}/userinfo"
    oidc_jwks_url = "{{ $realmInternal }}/certs"
    # Relativo: el callback es el del host por el que se entra (alias .lan incluidos).
    redirect_url = "/oauth2/callback"
    scope = "openid email profile"

    reverse_proxy = true
    http_address = "0.0.0.0:4180"
    upstreams = [ "static://202" ]

    cookie_name = "_{{ $r.name | replace "-" "_" }}_sso"
    cookie_secure = true
    cookie_samesite = "lax"
    cookie_expire = "12h"
    cookie_refresh = "1h"

    whitelist_domains = [ {{- range $i, $h := $r.hosts }}{{ if $i }}, {{ end }}{{ $h | quote }}{{ end -}} ]
    email_domains = [ "*" ]
    {{- with $r.allowedGroups }}
    allowed_groups = [ {{- range $i, $g := . }}{{ if $i }}, {{ end }}{{ printf "/%s" $g | quote }}{{ end -}} ]
    {{- end }}

    pass_user_headers = true
    set_xauthrequest = true
    skip_provider_button = true
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ $proxy }}
  namespace: keycloak
  labels:
    app.kubernetes.io/name: {{ $proxy }}
    app.kubernetes.io/component: forward-auth
    e-dani.com/keycloak-realm: {{ $r.name }}
spec:
  replicas: {{ if $r.critical }}2{{ else }}1{{ end }}
  selector:
    matchLabels:
      app: {{ $proxy }}
  template:
    metadata:
      labels:
        app: {{ $proxy }}
      annotations:
        checksum/config: {{ toJson $r | sha256sum }}
    spec:
      enableServiceLinks: false
      nodeSelector:
        kubernetes.io/arch: amd64
      # Stateless y en `edge`, no en el x86 de desarrollo, que se reinicia sin aviso.
      tolerations:
        - key: role
          operator: Equal
          value: edge
          effect: NoSchedule
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: role
                    operator: In
                    values: [edge]
              - matchExpressions:
                  - key: node-pool
                    operator: In
                    values: [ks5-nvme]
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              preference:
                matchExpressions:
                  - key: role
                    operator: In
                    values: [edge]
      containers:
        - name: oauth2-proxy
          image: {{ $.Values.images.oauth2Proxy }}
          args: ["--config=/etc/oauth2-proxy/oauth2_proxy.cfg"]
          env:
            - { name: OAUTH2_PROXY_CLIENT_ID, value: oauth2-proxy }
          envFrom:
            - secretRef:
                name: {{ $proxy }}-secrets
          ports:
            - { name: http, containerPort: 4180 }
          volumeMounts:
            - name: config
              mountPath: /etc/oauth2-proxy/oauth2_proxy.cfg
              subPath: oauth2_proxy.cfg
              readOnly: true
          readinessProbe:
            httpGet: { path: /ping, port: http }
            initialDelaySeconds: 5
          livenessProbe:
            httpGet: { path: /ping, port: http }
            initialDelaySeconds: 15
          resources:
            requests: { cpu: 25m, memory: 64Mi }
            limits: { cpu: 500m, memory: 256Mi }
      volumes:
        - name: config
          configMap:
            name: {{ $proxy }}-config
---
apiVersion: v1
kind: Service
metadata:
  name: {{ $proxy }}
  namespace: keycloak
  labels:
    app.kubernetes.io/name: {{ $proxy }}
    app.kubernetes.io/component: forward-auth
    e-dani.com/keycloak-realm: {{ $r.name }}
spec:
  selector:
    app: {{ $proxy }}
  ports:
    - { name: http, port: 4180, targetPort: http }
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: sso-{{ $r.name }}-forward-auth
  namespace: keycloak
  labels:
    app.kubernetes.io/name: {{ $proxy }}
    app.kubernetes.io/component: forward-auth
    e-dani.com/keycloak-realm: {{ $r.name }}
spec:
  forwardAuth:
    address: http://{{ $proxy }}.keycloak.svc.cluster.local:4180/oauth2/auth
    trustForwardHeader: true
    maxResponseBodySize: 1048576
    authResponseHeaders:
      - X-Auth-Request-User
      - X-Auth-Request-Email
      - X-Auth-Request-Groups
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: sso-{{ $r.name }}-errors
  namespace: keycloak
  labels:
    app.kubernetes.io/name: {{ $proxy }}
    app.kubernetes.io/component: forward-auth
    e-dani.com/keycloak-realm: {{ $r.name }}
spec:
  errors:
    # SOLO 401: reescribir el 403 a sign_in mete en bucle a quien entra sin grupo.
    status:
      - "401"
    service:
      name: {{ $proxy }}
      port: 4180
    query: /oauth2/sign_in?rd={url}
    statusRewrites:
      "401": 302
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: sso-{{ $r.name }}-chain
  namespace: keycloak
  labels:
    app.kubernetes.io/name: {{ $proxy }}
    app.kubernetes.io/component: forward-auth
    e-dani.com/keycloak-realm: {{ $r.name }}
spec:
  chain:
    middlewares:
      - name: sso-{{ $r.name }}-errors
      - name: sso-{{ $r.name }}-forward-auth
{{- end }}
