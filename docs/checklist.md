# KS-5 HA Checklist

- [ ] Export all required environment variables.
- [ ] Run `scripts/preflight.sh`.
- [ ] Confirm OVH catalog has **KS-5-A** with **SSD NVMe Soft RAID** and no
  HDD/SATA variant selected.
- [x] Store OVH EU credentials in Vault path `secret/infra/ovh/claude-eu`.
- [x] Sync OVH credentials into cluster Secret `infra-secrets/ovh-claude-eu`.
- [x] Store OVH CA API credentials in Vault path `secret/infra/ovh/ca`.
- [x] Sync OVH CA credentials into cluster Secret `infra-secrets/ovh-ca`.
- [ ] Store OVH credentials in 1Password item `OVH Claude EU`.
- [ ] Store OVH CA web login in 1Password item `OVH CA me@e-dani.com`.
  `op` CLI currently cannot connect to the local 1Password desktop app, so this
  remains a manual/reattempt step. Do not store the one-time OTP value.
- [ ] Wait until OVH EU exposes all 3 KS-5-A service names.
- [ ] Run Terraform/OpenTofu plan.
- [ ] Order exactly 3 KS-5-A with `confirm_ovh_order=order-3-ks5`.
- [ ] Install Ubuntu Server 24.04 LTS with `CONFIRM_OVH_REINSTALL=install-ubuntu-24.04`.
- [ ] Generate Ansible inventory.
- [ ] Bootstrap Tailscale.
- [ ] Bootstrap k3s server/etcd on all three KS-5-A nodes.
- [ ] Verify 3 KS-5-A nodes Ready and etcd quorum healthy.
- [ ] Demote x86 only after quorum is healthy.
- [ ] Apply labels and confirm scheduling preferences.
- [ ] Deploy Traefik HA and health route.
- [ ] Back up Cloudflare DNS in JSON and BIND formats.
- [ ] Rewrite external-dns public targets to the 4 edge IPs.
- [ ] Run `scripts/verify.sh --all`.
- [ ] Record final IPs, service names, and datacenter in the runbook.
