# DNS Backup

Create backups before any Cloudflare or `external-dns` target change:

```bash
python3 scripts/cloudflare_backup.py backup-json --output docs/dns-backups/pre-ks5.json
python3 scripts/cloudflare_backup.py backup-bind --output docs/dns-backups/pre-ks5.bind
```

Restore selected record types from JSON:

```bash
export CONFIRM_CLOUDFLARE_RESTORE=restore-dns-from-backup
python3 scripts/cloudflare_backup.py restore-json \
  --input docs/dns-backups/pre-ks5.json \
  --name-suffix e-dani.com \
  --types A CNAME TXT
```

Backups are ignored by Git.
