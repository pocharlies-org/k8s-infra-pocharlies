# alphalink: backup restic del WordPress

Fuente de verdad del backup diario de alphalinkcrossfit.com (droplet OVH
`ubuntu-s-2vcpu-4gb-ams3-01`, nodo k3s `alphalink`). El sitio corre en k3s
(ns `alphalink`); el dump de BD sale del contenedor mysql vía `crictl exec` y
el resto va a restic (bucket `alphalink-backups` del MinIO skirmshop-drive-s3).

Instalación en el droplet (los ficheros de este directorio, tal cual):

- `alphalink-backup.sh` → `/usr/local/sbin/alphalink-backup.sh` (mode 0755, root)
- `alphalink-backup.service` y `alphalink-backup.timer` → `/etc/systemd/system/`
  (quitar el comentario de cabecera), `systemctl daemon-reload && systemctl enable --now alphalink-backup.timer`
- `RESTORE.md` → `/usr/local/share/doc/alphalink-backup/RESTORE.md`

Credenciales del repo restic: ítem 1Password `alphalink-backup-s3` (bóveda
k8s-pocharlies), en el droplet en `/root/.config/restic/env`.

Comprobar: `ssh alphalink 'sudo systemctl start alphalink-backup.service && journalctl -u alphalink-backup.service -n 20'`
y `restic snapshots --host alphalinkcrossfit | tail -3` (debe haber uno de hoy, UTC).
