# DGX-626 evidence (pre-sync, 2026-10-06)

## 1. ClusterPolicy parses: kubectl apply --dry-run=server (nothing stored) -- PASS
Command: kubectl --kubeconfig /home/dibanez/.kube/config apply --dry-run=server -f policy.yaml
```
clusterpolicy.kyverno.io/externalsecret-alibaba-plan-only-litellm created (server dry run)
```

## 2. Offline, Kyverno CLI v1.18.1 (same as the cluster): tests/kyverno/alibaba-plan/run-offline.sh -- PASS
```
PASS  deny-connect-form-key-2  (pass: 2, fail: 1, warn: 0, error: 0, skip: 0 )
PASS  deny-connect-form-key  (pass: 2, fail: 1, warn: 0, error: 0, skip: 0 )
PASS  deny-dataFrom-extract  (pass: 2, fail: 1, warn: 0, error: 0, skip: 0 )
PASS  deny-dataFrom-find-catchall  (pass: 2, fail: 1, warn: 0, error: 0, skip: 0 )
PASS  deny-dataFrom-find-literal  (pass: 2, fail: 1, warn: 0, error: 0, skip: 0 )
PASS  deny-dataFrom-find-matches-2  (pass: 2, fail: 1, warn: 0, error: 0, skip: 0 )
PASS  deny-mixed-case-key  (pass: 2, fail: 1, warn: 0, error: 0, skip: 0 )
PASS  deny-old-form-key-2  (pass: 2, fail: 1, warn: 0, error: 0, skip: 0 )
PASS  deny-old-form-key  (pass: 2, fail: 1, warn: 0, error: 0, skip: 0 )
PASS  deny-second-entry  (pass: 2, fail: 1, warn: 0, error: 0, skip: 0 )
PASS  allow-find-unrelated  (pass: 3, fail: 0, warn: 0, error: 0, skip: 0 )
PASS  allow-litellm-connect  (pass: 0, fail: 0, warn: 0, error: 0, skip: 0 )
PASS  allow-litellm-extract  (pass: 0, fail: 0, warn: 0, error: 0, skip: 0 )
PASS  allow-litellm-old-form  (pass: 0, fail: 0, warn: 0, error: 0, skip: 0 )
PASS  allow-litellm-second-account  (pass: 0, fail: 0, warn: 0, error: 0, skip: 0 )
PASS  allow-other-item  (pass: 3, fail: 0, warn: 0, error: 0, skip: 0 )
PASS  allow-plan-gateway-item  (pass: 3, fail: 0, warn: 0, error: 0, skip: 0 )
PASS  allow-ram-reader  (pass: 3, fail: 0, warn: 0, error: 0, skip: 0 )
failures: 0
```

## 3. Control run, server dry-run BEFORE the policy is deployed: tests/kyverno/alibaba-plan/run-server-dry-run.sh
Expected: FAIL on every deny-* (policy not synced yet), PASS on every allow-*: the test discriminates. qa re-runs it after the sync and expects "failures: 0".
```
NOTE: the ClusterPolicy is not in the cluster yet; every deny case will show as FAIL (control run).
FAIL  deny-connect-form-key-2  expected DENIED, got rc=0: externalsecret.external-secrets.io/t-connect-2 created (server dry run)
FAIL  deny-connect-form-key  expected DENIED, got rc=0: externalsecret.external-secrets.io/t-connect created (server dry run)
FAIL  deny-dataFrom-extract  expected DENIED, got rc=0: externalsecret.external-secrets.io/t-extract created (server dry run)
FAIL  deny-dataFrom-find-catchall  expected DENIED, got rc=0: externalsecret.external-secrets.io/t-find-all created (server dry run)
FAIL  deny-dataFrom-find-literal  expected DENIED, got rc=0: externalsecret.external-secrets.io/t-find-literal created (server dry run)
FAIL  deny-dataFrom-find-matches-2  expected DENIED, got rc=0: externalsecret.external-secrets.io/t-find-2 created (server dry run)
FAIL  deny-mixed-case-key  expected DENIED, got rc=0: externalsecret.external-secrets.io/t-case created (server dry run)
FAIL  deny-old-form-key-2  expected DENIED, got rc=0: externalsecret.external-secrets.io/t-old-form-2 created (server dry run)
FAIL  deny-old-form-key  expected DENIED, got rc=0: externalsecret.external-secrets.io/t-old-form created (server dry run)
FAIL  deny-second-entry  expected DENIED, got rc=0: externalsecret.external-secrets.io/t-second created (server dry run)
PASS  allow-find-unrelated  admitted: externalsecret.external-secrets.io/t-find-ok created (server dry run)
PASS  allow-litellm-connect  admitted: externalsecret.external-secrets.io/t-connect created (server dry run)
PASS  allow-litellm-extract  admitted: externalsecret.external-secrets.io/t-extract created (server dry run)
PASS  allow-litellm-old-form  admitted: externalsecret.external-secrets.io/t-old-form created (server dry run)
PASS  allow-litellm-second-account  admitted: externalsecret.external-secrets.io/t-connect-2 created (server dry run)
PASS  allow-other-item  admitted: externalsecret.external-secrets.io/t-other created (server dry run)
PASS  allow-plan-gateway-item  admitted: externalsecret.external-secrets.io/t-pg created (server dry run)
PASS  allow-ram-reader  admitted: externalsecret.external-secrets.io/t-ram created (server dry run)
failures: 10
```
