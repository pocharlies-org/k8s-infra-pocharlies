{{- /* SC-2822: keycloak-config-cli concilia los realms de realms.yaml ANTES de
que los proxies cambien (hook Sync, wave -1: después de los secretos y el
ConfigMap de la wave -2, antes de los Deployments de la wave 0). Si falla, el
sync se para y ningún proxy apunta a un realm a medio hacer. Solo toca los
realms que declara este chart: `edani` y `master` no están en IMPORT_FILES. */ -}}
{{- if .Values.realms }}
{{- $google := false }}
{{- range .Values.realms }}{{- if .google }}{{- $google = true }}{{- end }}{{- end }}
apiVersion: batch/v1
kind: Job
metadata:
  name: keycloak-sso-config
  namespace: keycloak
  labels:
    app.kubernetes.io/name: keycloak
    app.kubernetes.io/component: keycloak-sso-config
  annotations:
    argocd.argoproj.io/hook: Sync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
    argocd.argoproj.io/sync-wave: "-1"
spec:
  backoffLimit: 1
  activeDeadlineSeconds: 900
  ttlSecondsAfterFinished: 86400
  template:
    metadata:
      labels:
        app.kubernetes.io/name: keycloak
        app.kubernetes.io/component: keycloak-sso-config
    spec:
      automountServiceAccountToken: false
      restartPolicy: Never
      enableServiceLinks: false
      nodeSelector:
        kubernetes.io/arch: amd64
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        seccompProfile: { type: RuntimeDefault }
      containers:
        - name: keycloak-config-cli
          image: {{ .Values.images.configCli }}
          imagePullPolicy: IfNotPresent
          env:
            - { name: KEYCLOAK_URL, value: {{ .Values.keycloak.internalUrl | quote }} }
            - { name: KEYCLOAK_AVAILABILITYCHECK_ENABLED, value: "true" }
            - { name: KEYCLOAK_AVAILABILITYCHECK_TIMEOUT, value: 120s }
            - name: KEYCLOAK_USER
              valueFrom: { secretKeyRef: { name: {{ .Values.keycloak.adminSecret }}, key: KC_BOOTSTRAP_ADMIN_USERNAME } }
            - name: KEYCLOAK_PASSWORD
              valueFrom: { secretKeyRef: { name: {{ .Values.keycloak.adminSecret }}, key: KC_BOOTSTRAP_ADMIN_PASSWORD } }
            - { name: IMPORT_FILES_LOCATIONS, value: /config/*.yaml }
            - { name: IMPORT_VARSUBSTITUTION_ENABLED, value: "true" }
            {{- range .Values.realms }}
            - name: CLIENT_SECRET_{{ .name | upper | replace "-" "_" }}
              valueFrom: { secretKeyRef: { name: oauth2-proxy-{{ .name }}-secrets, key: OAUTH2_PROXY_CLIENT_SECRET } }
            {{- end }}
            {{- if $google }}
            - name: GOOGLE_CLIENT_ID
              valueFrom: { secretKeyRef: { name: keycloak-sso-google, key: GOOGLE_CLIENT_ID } }
            - name: GOOGLE_CLIENT_SECRET
              valueFrom: { secretKeyRef: { name: keycloak-sso-google, key: GOOGLE_CLIENT_SECRET } }
            {{- end }}
            - { name: JAVA_TOOL_OPTIONS, value: "-XX:MaxRAMPercentage=75" }
          resources:
            requests: { cpu: 100m, memory: 256Mi }
            limits: { cpu: "1", memory: 512Mi }
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: { drop: ["ALL"] }
          volumeMounts:
            - { name: realms, mountPath: /config, readOnly: true }
            - { name: tmp, mountPath: /tmp }
      volumes:
        - name: realms
          configMap:
            name: keycloak-sso-realms
        - name: tmp
          emptyDir: { sizeLimit: 64Mi }
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: keycloak-sso-config-egress
  namespace: keycloak
  labels:
    app.kubernetes.io/name: keycloak
    app.kubernetes.io/component: keycloak-sso-config
  annotations:
    argocd.argoproj.io/sync-wave: "-2"
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/component: keycloak-sso-config
  policyTypes: [Egress]
  egress:
    - to:
        - podSelector:
            matchLabels: { app: keycloak }
      ports:
        - { protocol: TCP, port: 8080 }
    - to:
        - namespaceSelector:
            matchLabels: { kubernetes.io/metadata.name: kube-system }
          podSelector:
            matchLabels: { k8s-app: kube-dns }
      ports:
        - { protocol: UDP, port: 53 }
        - { protocol: TCP, port: 53 }
{{- end }}
