# Actions Runner Controller

ARC provides Kubernetes-hosted GitHub Actions runners for the cluster CI/CD
standard.

## Namespaces

- `arc-systems`: controller (`arc-gha-rs-controller`)
- `arc-runners`: the shared runner scale set

## Runner

All repositories live under the `pocharlies-org` organization and share a
single org-scope runner. Workflows target it with `runner: arc-k8s` (the input
to the reusable workflows in `pocharlies-org/k8s-gitops-pocharlies`):

| Scale set | runs-on | Scope |
|---|---|---|
| `arc-k8s` | `arc-k8s` | `github.com/pocharlies-org` (whole org) |

Org-scope runners are only available to repositories inside `pocharlies-org`.

## Apply

The `arc-github-app` secret must exist in `arc-runners`. It is materialized
from Vault by External Secrets and is referenced by `githubConfigSecret`.

```bash
platform/arc/install-scale-sets.sh
```

`arc-k8s` uses `containerMode.type: dind` so Docker build and push jobs work
from Kubernetes runners. DinD is privileged; keep these runners isolated in
`arc-runners` and off the `role=edge` node `sauvage`.
