# Restaurar alphalinkcrossfit.com desde restic

Instalado en `/usr/local/share/doc/alphalink-backup/RESTORE.md` del droplet
alphalink. INFRA-1086 (03-11-2026): el WordPress vive en **k3s** (namespace
`alphalink`), no en el docker del host.

Credenciales: 1Password, bóveda k8s-pocharlies, ítem `alphalink-backup-s3`
(AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, RESTIC_PASSWORD, RESTIC_REPOSITORY).
En el droplet ya están en /root/.config/restic/env.

    source /root/.config/restic/env
    restic snapshots                                  # lista
    restic restore latest --target /tmp/restore       # todo
    restic restore latest --target /tmp/restore --include /var/backups/alphalink/db

## Base de datos

El volcado está en `/var/backups/alphalink/db/wordpress.sql` del snapshot. Se
restaura sobre el MySQL de k3s (ns `alphalink`, pod `wordpress-mysql-0`). Desde
el hub (KUBECONFIG=~/.kube/config):

    kubectl -n alphalink exec -i wordpress-mysql-0 -- sh -c \
      'exec mysql -uwpuser -p"$MYSQL_PASSWORD" wordpress' \
      < /tmp/restore/var/backups/alphalink/db/wordpress.sql

En el propio droplet, sin kubeconfig (como root):

    CID=$(crictl ps -q --namespace alphalink --name '^mysql$' | head -1)
    crictl exec -i "$CID" sh -c \
      'exec mysql -uwpuser -p"$MYSQL_PASSWORD" wordpress' \
      < /tmp/restore/var/backups/alphalink/db/wordpress.sql

## Ficheros del sitio (código, uploads)

El contenido vivo está en los PVC de k3s (`wordpress-html`,
`data-wordpress-mysql-0`, ns `alphalink`) y lo respalda **velero** (schedule
`daily-alphalink`): restituir con `velero restore create --from-backup <backup>`.

La ruta `/root/wordpress-alphalinkcrossfit` que aparece en los snapshots es
**LEGACY**: el viejo stack docker-compose, fuera de uso desde octubre 2026
(INFRA-1086). Se sigue respaldando como última copia histórica; NO restaurar
encima del sitio vivo.

Desde otra máquina (droplet perdido): instalar restic, exportar las 4 variables
del ítem y los mismos comandos. El prefijo de tablas de WP es `2r43VdG_`.
