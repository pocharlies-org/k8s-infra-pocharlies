# Corte del backup-target default de Longhorn a MinIO (sauvage)

Historia: INFRA-1100 (épica INFRA-1022, P2). Sustituye el destino default de copias
de Longhorn — hoy el NFS `/srv/longhorn-backups` del nodo `ubuntu` — por
`s3://longhorn-backups@us-east-1/` en la MinIO de `sauvage`, con credencial S3
acotada en vez de export NFS abierto (INFRA-980: el punto 1 — export restringido —
ya está Done; el punto 2 se hereda como postura: los backups de volúmenes sin
cifrar siguen sin cifrar, lo que cambia es el acceso; el punto 3 — evidencia — se
cierra con la fase (e) de este runbook).

Plantilla: `docs/openclaw-sauvage-backup-target.md` (retirado con INFRA-993; el
fichero vive en el historial de git, commit `15bd25475^`).

## Estado de las fases (actualizado 2026-11-05, fase (d) de esta PR)

| fase | estado | evidencia |
|---|---|---|
| (a) | Hecha — PR #441 fusionada 2026-11-02 | `ExternalSecret/longhorn-default-backup` `Ready=True` (medido 2026-11-05, last sync 2d13h); veredicto security INFRA-1121 (Done) |
| (b) | Hecha — 2026-11-04 (INFRA-1158, operador IT) | md5 original y restaurado coincidentes: `58bc7d03e9e1b871f0741feec8d549f9`; backup conservado en MinIO como evidencia: `backup-c8b57ec0b72a483e` (`state=Completed`, target `minio-default-test`) |
| (c) | Hecha — PR #442 fusionada 2026-11-04 | `values.yaml` `defaultSettings` a MinIO; veredicto security INFRA-1170 (Done). Estado live medido 2026-11-05: el CR `default` aún `nfs://100.83.56.98:/srv/longhorn-backups` — la aplicación del corte sigue en curso (diagnóstico aparte); se cierra cuando `kubectl -n longhorn-system get backuptarget default -o jsonpath='{.spec.backupTargetURL}'` devuelva la URL de MinIO |
| (d) | En esta PR | Retira `BackupTarget/minio-default-test` del fichero; la entrada de la kustomization se conserva (el fichero sigue proyectando el ExternalSecret). ArgoCD poda el CR vivo al sync |
| (e) | Pendiente del operador | `exportfs -u` del `/srv/longhorn-backups` en el nodo `ubuntu`; la salida vacía de `exportfs -v` es la evidencia del punto 3 de INFRA-980 |

## Límite de lo que esto es

MinIO en sauvage es un solo StatefulSet sobre `/srv/minio/data`: quita a `ubuntu`
del camino de las copias, pero no da independencia de sitio ni de proveedor. No
configurar reglas de lifecycle sobre el bucket: Longhorn es el dueño del ciclo de
vida de sus objetos, y la retención de 14 días del chart no se toca.

## Precondiciones (parar si alguna falla)

1. **Request [SEC] INFRA-1112 cerrada**: item 1Password `longhorn-default-backup`
   (vault k8s-pocharlies, campos `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
   `AWS_ENDPOINTS`) y usuario MinIO `longhorn-default-backup` con la política
   versionada `storage/minio/longhorn-default-backup-policy.json` (acotada a
   `longhorn-backups/*`). No reutilizar `backup-user` (su política es
   `velero-backups/*`).
2. **Veredicto de security sobre la PR del corte** (la puerta lo pide: esta PR toca
   credenciales).
3. **Disco de sauvage medido y alerta confirmada** (precedente INFRA-992: la raíz
   llena tumbó minio-0 y con él Harbor). Medir antes de cada corte:

   ```
   ssh ubuntu@100.109.183.9 'df -h /'
   ```

   y confirmar que `NodeDiskFilling` (VMRule `monitoring/node-capacity`, umbral
   >80 %, operativo desde INFRA-993) salta por debajo del 85 %.
   Medición de 2026-11-02 (INFRA-1100): `/dev/md3 3.6T, 1.2T usados (35 %), 2.3T
   libres` — holgado; la alerta está desplegada y `operational`.
4. Ningún mantenimiento de storage/drain/upgrade de nodos en curso.
5. `BackupTarget/default` (el NFS actual) sigue disponible: las fases (a) y (b)
   nunca lo editan.

## Orden del corte (fases a–e)

### (a) ExternalSecret + BackupTarget de prueba temporal

Los trae esta PR (`storage/longhorn/longhorn-default-backup.yaml`, añadida a la
kustomization raíz): `ExternalSecret/longhorn-default-backup` (ns
`longhorn-system`, sync-wave -2, `refreshInterval: 24h` + `refreshPolicy:
OnChange`) y `BackupTarget/minio-default-test` (sync-wave -1, tier transitional,
`backupTargetURL: s3://longhorn-backups@us-east-1/`). Tras el sync:

```
kubectl -n longhorn-system get externalsecret longhorn-default-backup -o wide
```

Debe estar `Ready=True`. La validación de la identidad (listar el bucket, escribir
y borrar un objeto random, y que otro bucket/prefijo esté denegado) la hizo
security al crear el usuario (INFRA-1112); no repetir aquí con credenciales a la
vista. Nunca imprimir el valor del secreto ni en comando, ni en log, ni en
anotación.

### (b) Backup de volumen de prueba → restore a volumen nuevo → lectura md5

Sobre un volumen de prueba (no de producción):

1. Escribir un fichero con `md5sum` conocido (p. ej. `dd if=/dev/urandom
   bs=1M count=64 of=/data/probe.bin; md5sum /data/probe.bin`).
2. `Snapshot` con nombre único → esperar `status.readyToUse=true`.
3. `Backup` con `backupMode: full`, `backupTargetName: minio-default-test` →
   esperar `status.state=Completed` y URL bajo `s3://longhorn-backups@us-east-1/`.
4. `Volume` nuevo con `fromBackup` = esa URL, `backupTargetName:
   minio-default-test`, montado read-only en un pod de auditoría; `md5sum` del
   fichero restaurado debe coincidir con el original.
5. Borrar el volumen de restore, el pod y la PVC temporales. Conservar el backup.

Con (b) en verde queda cubierto el punto 3 de INFRA-980 (backup y restauración
probados); la evidencia va al PR del corte.

### (c) Fijar los values (segunda PR, el corte)

En `storage/longhorn/values.yaml`, `defaultSettings`: descomentar/fijar
`backupTarget: s3://longhorn-backups@us-east-1/` y añadir
`backupTargetCredentialSecret: longhorn-default-backup`. El CR
`BackupTarget/default` pasa a MinIO al aplicar ArgoCD. La retención de 14 días y la
StorageClass por defecto no se tocan. Verificar que los backups nuevos salen a S3 y
que `kubectl -n longhorn-system get backuptarget default -o jsonpath='{.spec.backupTargetURL}'`
devuelve la URL de MinIO.

### (d) Retirar el CR temporal

Quitar `BackupTarget/minio-default-test` del fichero (PR del corte o siguiente;
hecha en esta PR, 2026-11-05). La entrada del fichero en la kustomization raíz se
conserva: sigue proyectando el ExternalSecret, que es la credencial del default.

### (e) `exportfs -u` del NFS del x86 — solo tras (b) verificada

En el nodo `ubuntu` (operativo, con evidencia):

```
sudo exportfs -u '/srv/longhorn-backups:<red permitida>'
exportfs -v   # debe salir vacío respecto de este export
```

La salida vacía de `exportfs -v` es la evidencia del punto 3 de INFRA-980. Los
backups históricos del NFS quedan en el disco del x86 como copia fría; su poda es
una decisión aparte, no parte de este corte.

## Rollback

- Si (a) o (b) fallan: retirar `BackupTarget/minio-default-test` (quitar de la
  kustomization); `default` no se ha tocado, no hay nada que revertir en Longhorn.
- Si (c) falla tras aplicar los values: revertir el commit de `values.yaml` (el CR
  `default` vuelve al NFS al reconciliar) y volver a (b) antes de reintentar.
- (e) es reversible con `exportfs -o ... && exportfs -ra` desde el `/etc/exports`
  del x86, que no se borra hasta cerrar la historia.

## Rotación

Rotar = crear credencial nueva en el item de 1Password, actualizar el usuario MinIO
en sauvage, y `refreshPolicy: OnChange` propaga al Secret (o forzar el sync del
ExternalSecret). Revalidar después: un backup de prueba a `default` completado.
