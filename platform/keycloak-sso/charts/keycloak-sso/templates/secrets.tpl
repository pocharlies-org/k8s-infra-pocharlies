{{- /* SC-2822: secretos de cada realm desde 1Password (Connect; veredicto de
security: nada de generarlos en el clúster, un Secret perdido cambiaría el valor y
dejaría de casar con Keycloak). Un ítem por web, `keycloak-next-oauth2-proxy-<realm>`,
con `client_secret` (el del client oauth2-proxy de ese realm) y `cookie_secret`
(32 bytes en base64url: oauth2-proxy no acepta base64 estándar). Los lee el proxy y el Job que
declara el realm, así que el client secret de Keycloak y el del proxy son el
mismo valor por construcción. */ -}}
{{- range $r := .Values.realms }}
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: oauth2-proxy-{{ $r.name }}-secrets
  namespace: keycloak
  labels:
    app.kubernetes.io/name: oauth2-proxy-{{ $r.name }}
    app.kubernetes.io/component: client-credentials
    e-dani.com/keycloak-realm: {{ $r.name }}
  annotations:
    argocd.argoproj.io/sync-wave: "-2"
spec:
  refreshInterval: 24h
  refreshPolicy: OnChange
  secretStoreRef:
    name: {{ $.Values.secretStore }}
    kind: ClusterSecretStore
  target:
    name: oauth2-proxy-{{ $r.name }}-secrets
    creationPolicy: Owner
    deletionPolicy: Retain
  data:
    - secretKey: OAUTH2_PROXY_CLIENT_SECRET
      remoteRef:
        key: keycloak-next-oauth2-proxy-{{ $r.name }}
        property: client_secret
    - secretKey: OAUTH2_PROXY_COOKIE_SECRET
      remoteRef:
        key: keycloak-next-oauth2-proxy-{{ $r.name }}
        property: cookie_secret
{{- end }}
{{- $google := false }}
{{- range .Values.realms }}{{- if .google }}{{- $google = true }}{{- end }}{{- end }}
{{- if $google }}
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: keycloak-sso-google
  namespace: keycloak
  labels:
    app.kubernetes.io/name: keycloak
    app.kubernetes.io/component: keycloak-sso-config
  annotations:
    argocd.argoproj.io/sync-wave: "-2"
spec:
  refreshInterval: 24h
  refreshPolicy: OnChange
  secretStoreRef:
    name: {{ .Values.secretStore }}
    kind: ClusterSecretStore
  target:
    name: keycloak-sso-google
    creationPolicy: Owner
    deletionPolicy: Retain
  data:
    - secretKey: GOOGLE_CLIENT_ID
      remoteRef:
        key: {{ required "google.item: un realm usa Google" .Values.google.item | quote }}
        property: client_id
    - secretKey: GOOGLE_CLIENT_SECRET
      remoteRef:
        key: {{ .Values.google.item | quote }}
        property: client_secret
{{- end }}
