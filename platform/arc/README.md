# Actions Runner Controller

ARC provides Kubernetes-hosted GitHub Actions runners for the cluster CI/CD
standard.

## Namespaces

- `arc-systems`: controller (`arc-gha-rs-controller`)
- `arc-runners`: per-repository runner scale sets

`pocharlies` is a personal GitHub account, so runners are registered per repo
instead of at organization scope. Workflows target the scale-set name directly
with `runs-on`.

## Scale sets

| Repository | runs-on |
|---|---|
| `k8s-socialmedia-pocharlies` | `arc-amd64` |
| `k8s-adguard-pocharlies` | `arc-adguard` |
| `k8s-firecrawl-pocharlies` | `arc-firecrawl` |
| `k8s-gitops-pocharlies` | `arc-gitops` |
| `k8s-infra-pocharlies` | `arc-infra` |
| `k8s-libreplay-pocharlies` | `arc-libreplay` |
| `k8s-litellm-pocharlies` | `arc-litellm` |
| `k8s-n8n-pocharlies` | `arc-n8n` |
| `k8s-observability-pocharlies` | `arc-observability` |
| `k8s-shopify-bundles-pocharlies` | `arc-shopify-bundles` |
| `k8s-shopify-label-pocharlies` | `arc-shopify-label` |
| `k8s-shopify-picker-pocharlies` | `arc-shopify-picker` |
| `k8s-shopify-sii-pocharlies` | `arc-shopify-sii` |
| `k8s-teslamate-pocharlies` | `arc-teslamate` |

## Apply

The `arc-github-pat-secret` secret must exist in `arc-runners` and contain
`github_token`.

```bash
platform/arc/install-scale-sets.sh
```

All scale sets use `containerMode.type: dind` so Docker build and push jobs work
from Kubernetes runners. DinD is privileged; keep these runners isolated in
`arc-runners`.
