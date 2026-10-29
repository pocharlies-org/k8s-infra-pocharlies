# INFRA-42 criterio 4 — Job de prueba de programación (lo aplica el operador)

Ningún rol de la compañía puede aplicar un recurso suelto contra el clúster vivo: se lo
denegó a `company-qa` (verbatim en INFRA-88), `company-devops` no aplica a mano, `company-sre`
y el CTO son de solo lectura. Este manifiesto es el de la prueba, verificado por qa contra el
spec del story: 25m de CPU, podAffinity requerida al pod openclaw-qwen36 (vivo en ks5-cp-3,
4/4 Running, 1360m libres en el nodo).

Aplicar y medir (creación → Running, objetivo < 60 s):

```sh
export KUBECONFIG=~/.kube/config
kubectl apply -f - <<'EOF'
apiVersion: batch/v1
kind: Job
metadata:
  name: infra42-affinity-test
  namespace: default
spec:
  activeDeadlineSeconds: 300
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      affinity:
        podAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                app.kubernetes.io/component: openclaw
                app.kubernetes.io/instance: openclaw-qwen36
            topologyKey: kubernetes.io/hostname
            namespaces:
            - openclaw-qwen36
      containers:
      - name: test
        image: curlimages/curl:8.16.0
        command: ["sh", "-c", "sleep 120"]
        resources:
          requests:
            cpu: 25m
            memory: 32Mi
EOF
kubectl get pod -n default -l job-name=infra42-affinity-test -o wide -w   # anotar hora de creación y de Running
kubectl get events -n default --field-selector involvedObject.name=infra42-affinity-test
kubectl delete job infra42-affinity-test -n default
```

Notas:
- `curlimages/curl:8.16.0` ya está presente en ks5-cp-3 (qa lo confirmó antes de que se le
  denegara el apply). Si el nodo no la resolviera, sustituir por la imagen de cualquier pod
  ya corriendo en ks5-cp-3 (busybox/pause del harbor local).
- El Job se autolimita (activeDeadlineSeconds 300) pero hay que borrarlo después de medir.
- Evidencia esperada: pod en ks5-cp-3, tiempo creation→Running < 60 s, sin intervención.
