# KS-5 SSH hardening — Tailscale-only

Status: **LIVE since 2026-05-30** on ks5-cp-1/2/3.

The 3 KS-5-A are internet-exposed OVH dedicated servers. Their sshd is now bound
**only to the Tailscale IP + loopback**, so the public OVH IP no longer answers
SSH (verified: `Connection timed out` on the public IPs; `ss` shows only
`127.0.0.1:22` + `100.x:22`).

## Why ListenAddress, not a firewall

These are **etcd control-plane** nodes. A `ufw` default-deny could silently break
k3s / flannel (VXLAN 8472) / etcd (2379-2380) / kubelet (10250) / tailscale
(UDP 41641). So we touch **only sshd** (`ListenAddress`), never the firewall.

## Mechanism (role `ssh_tailscale_only`)

* `net.ipv4.ip_nonlocal_bind=1` (`/etc/sysctl.d/99-ssh-tailscale.conf`) so sshd
  can bind the Tailscale IP even if tailscaled is not yet up at boot → no boot
  lock-out.
* `/etc/ssh/sshd_config.d/10-tailscale-only.conf`:
  `ListenAddress <tailscale_ipv4>` + `ListenAddress 127.0.0.1`.
* Safety in the role: pre-flight assert the Tailscale IP is live; `sshd -t`
  validate with drop-in rollback; async restart + `wait_for_connection`; final
  assert that `0.0.0.0:22` is gone.

## Apply (canary first)

Ansible **must** connect over Tailscale (the public path is what we are closing):

```bash
cd ansible
ansible-playbook -i inventory/ks5-ts.ini playbooks/ssh-tailscale-only.yml -l ks5-cp-1
# verify, then:
ansible-playbook -i inventory/ks5-ts.ini playbooks/ssh-tailscale-only.yml -l ks5-cp-2,ks5-cp-3
```

`inventory/ks5-ts.ini` points `ansible_host` at the Tailscale IPs:
ks5-cp-1=100.107.21.89, ks5-cp-2=100.71.117.127, ks5-cp-3=100.75.189.75
(`ansible_user=ubuntu`, sudo).

## Consequences / dependencies

* **Any** future Ansible run against KS-5 must use `inventory/ks5-ts.ini`
  (the public-IP `inventory/generated/ks5.ini` can no longer reach them).
* The dgx dashboard (`~/dgx-infra/services/dashboard/routes_cluster.py` and
  `routes_cron.py`) had its KS-5 `ssh` targets repointed from the public IPs to
  the Tailscale IPs.
* Tailscale SSH (ACL `tag:k8s`) and `ubuntu@<tailscale-ip>` both keep working.

## Rollback

Remove `/etc/ssh/sshd_config.d/10-tailscale-only.conf` and `systemctl restart
ssh` (sshd falls back to the default `0.0.0.0:22`). Reachable over Tailscale, or
via the OVH KVM/rescue console if Tailscale is down.
