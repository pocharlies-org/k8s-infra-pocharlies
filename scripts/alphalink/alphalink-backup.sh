#!/bin/bash
# Backup diario incremental (restic) de alphalinkcrossfit.com.
# Destino: bucket alphalink-backups del MinIO skirmshop-drive-s3 (backup-hub del
# cluster k3s), vía https://skirmshop-s3.e-dani.com. Credenciales y RESTIC_PASSWORD
# en 1Password: k8s-pocharlies / alphalink-backup-s3.
# Fuente de verdad de este script y de las unidades systemd: scripts/alphalink/ de
# k8s-infra-pocharlies; se instalan en el droplet alphalink (ubuntu-s-2vcpu-4gb-ams3-01).
# El WordPress corre en k3s (namespace alphalink), NO en docker del host (INFRA-1086).
# Restaurar: ver /usr/local/share/doc/alphalink-backup/RESTORE.md
set -euo pipefail

source /root/.config/restic/env

STAGE=/var/backups/alphalink
mkdir -p "$STAGE/db"
chmod 700 "$STAGE"

# 1) Volcado lógico de MySQL desde el pod de k3s (ns alphalink, wordpress-mysql-0).
#    La contraseña no toca el disco del host: crictl exec la toma del entorno del
#    contenedor. Antes era `docker exec wp_db` (INFRA-1086: ese contenedor ya no
#    existe desde el 31-10; el backup quedó ciego 17 días en silencio).
CID="$(crictl ps -q --namespace alphalink --name '^mysql$' | head -1)"
if [ -z "$CID" ]; then
    echo "no hay contenedor mysql corriendo en el namespace alphalink (k3s)" >&2
    exit 1
fi
crictl exec "$CID" sh -c 'exec mysqldump -uwpuser -p"$MYSQL_PASSWORD" \
    --single-transaction --quick --no-tablespaces --routines --triggers \
    --default-character-set=utf8mb4 wordpress' > "$STAGE/db/wordpress.sql.tmp"
if ! tail -c 200 "$STAGE/db/wordpress.sql.tmp" | grep -q "Dump completed"; then
    echo "mysqldump incompleto" >&2
    exit 1
fi
mv -f "$STAGE/db/wordpress.sql.tmp" "$STAGE/db/wordpress.sql"

# 2) Snapshot incremental: BD + restos LEGACY del stack docker (el stack vivo está
#    en k3s ns alphalink y lo respalda velero, schedule daily-alphalink) +
#    sauvagebot + /etc.
restic backup --tag daily --host alphalinkcrossfit \
    --exclude-file /etc/alphalink-backup/excludes \
    "$STAGE" \
    /root/wordpress-alphalinkcrossfit \
    /root/sauvagebottelegram \
    /etc

# 3) Retención: 14 diarios, 8 semanales, 12 mensuales.
restic forget --host alphalinkcrossfit --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune

# 4) Los domingos, verificar estructura y un 5 % de los datos.
if [ "$(date +%u)" = 7 ]; then
    restic check --read-data-subset=5%
fi

# 5) Fail-closed (INFRA-1086): el snapshot más reciente del repo debe ser de hoy
#    (UTC). Un "éxito" sin snapshot nuevo sale 1 y dispara el aviso OnFailure;
#    así el fallo no vuelve a pasar un mes en silencio.
LAST="$(restic snapshots --host alphalinkcrossfit --json \
    | grep -o '"time": *"[^"]*"' | tail -1 | cut -d'"' -f4)"
if [ "$(date -u +%F)" != "$(date -u -d "$LAST" +%F 2>/dev/null || true)" ]; then
    echo "fail-closed: snapshot más reciente '${LAST:-ninguno}', no es de hoy" >&2
    exit 1
fi
