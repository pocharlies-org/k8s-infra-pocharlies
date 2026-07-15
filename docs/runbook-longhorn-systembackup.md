# Longhorn SystemBackup — gates de activación y restaurabilidad

## Estado de diseño

`NO-GO`: el `CronJob/longhorn-system-backup` permanece `suspend: true` hasta
que todos los gates siguientes estén probados. Fusionar el manifiesto no debe
crear un `SystemBackup`.

Longhorn 1.11.2 guarda siempre el bundle de `SystemBackup` en
`BackupTarget/default`. El target debe ser externo al clúster y al domicilio;
un NFS en `ubuntu`, un endpoint `*.svc.cluster.local` o MinIO dentro del mismo
clúster no constituyen recuperación ante desastre.

## Gates antes de activar o derivar un one-shot

1. `BackupTarget/default` está `Available`, usa almacenamiento externo e
   independiente y lleva la etiqueta
   `backup.e-dani.com/failure-domain=external` después de verificar el endpoint
   real de sus credenciales.
2. Cada `BackupTarget` referenciado por un volumen cumple el mismo gate externo
   y `Available`.
3. No existe ningún `SystemBackup` en estado vacío o no terminal y no existe
   ningún `SystemRestore`, ni siquiera uno histórico sin clasificar.
4. No hay ningún `Backup` Longhorn ni Velero en estado vacío, desconocido o no
   terminal.
5. Hay cero volúmenes Longhorn `degraded` y todo volumen no-standby/no-linked
   tiene `status.lastBackup`.
6. El primer `if-not-present` se ejecuta en una ventana observada, sin builds,
   rebalanceos, snapshots, Velero ni migraciones de storage concurrentes.
7. El nuevo `SystemBackup` llega a `Ready`; su objeto vuelve a sincronizar desde
   el target remoto tras una resincronización y el bundle puede descargarse.
8. Se realiza un restore drill aislado antes de cambiar `suspend` a `false`.

La política recurrente es semanal, domingo 12:00 UTC, `Forbid`, sin retry
automático y con retención de cuatro backups `Ready` administrados por el
runner. Solo se purga después de crear otro backup `Ready`; backups manuales o
en `Error` no se borran.

## Separación entre backup y restore

No existe ningún manifiesto `SystemRestore` y la cuenta del CronJob no tiene
verbos de escritura sobre `systemrestores.longhorn.io`. Un restore es una
operación manual, destructiva y con ventana exclusiva.

Según Longhorn 1.11.2, el restore requiere un clúster Longhorn funcionando,
nodos y tags de disco preparados, todos los volúmenes existentes desconectados
y un camino de versión soportado. Longhorn no soporta restore cruzando
major/minor salvo el caso específico de fallo de upgrade. El drill debe usar el
mismo minor de Longhorn que produjo el backup.

## Qué cubre y qué no cubre

El bundle contiene recursos operados por Longhorn, incluidos CRDs, settings,
StorageClasses, PV/PVC y Volumes. SystemBackup no sustituye:

- backups de datos de volumen verificables y actuales;
- checkpoint y restore de etcd/K3s;
- Velero para workloads y recursos ajenos a Longhorn;
- copia externa de credenciales y procedimiento de recuperación del target;
- backup de objetos `Node`, ajustes configurables excluidos o backing images
  del data engine V2;
- una prueba real de restore, checksums, RTO y RPO.

Durante un restore en un clúster con datos, Longhorn no sobrescribe los
volúmenes/PV/PVC ya existentes y restaura volúmenes ausentes desde su último
backup. Por eso un `SystemBackup Ready` por sí solo no demuestra
restaurabilidad.

## Evidencia mínima del primer drill

- versión, imagen y git commit guardados en el `SystemBackup`;
- nombre, timestamp, target y estado `Ready` resincronizado;
- inventario antes/después de CRDs, StorageClasses, PV, PVC, Volumes,
  RecurringJobs y Settings;
- restore de volúmenes seleccionados desde el backup remoto;
- montaje de PVCs y checksums/`quick_check` de datos representativos;
- pruebas de workloads y tiempos medidos RTO/RPO;
- destrucción documentada del entorno aislado, sin tocar producción.

## Fuentes oficiales para Longhorn 1.11.2

- https://longhorn.io/docs/1.11.2/advanced-resources/system-backup-restore/backup-longhorn-system/
- https://longhorn.io/docs/1.11.2/advanced-resources/system-backup-restore/restore-longhorn-system/
