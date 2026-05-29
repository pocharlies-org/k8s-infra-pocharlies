# Cloudflare DNS

Cloudflare DNS changes for this rollout are script-driven instead of managed as
new Terraform resources, because the zone already contains live records managed
by `external-dns` and manual history.

Use:

```bash
python3 ../../scripts/cloudflare_backup.py backup-json --output ../../docs/dns-backups/pre-ks5.json
python3 ../../scripts/cloudflare_backup.py backup-bind --output ../../docs/dns-backups/pre-ks5.bind
python3 ../../scripts/update_external_dns_targets.py --targets "KS5_1,KS5_2,KS5_3,SAUVAGE_IP" --write
```

Required environment:

```bash
export CLOUDFLARE_API_TOKEN=...
export CLOUDFLARE_ZONE_ID=...
```
