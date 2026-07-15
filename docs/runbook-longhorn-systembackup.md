# Longhorn SystemBackup — ventana GitOps manual y restaurabilidad

## Estado de diseño

`NO-GO`: el `CronJob/longhorn-system-backup` es únicamente una plantilla manual
y permanece `suspend: true` de forma permanente. Su campo `schedule` es un
requisito sintáctico de Kubernetes, no una promesa de recurrencia. Nunca se debe
cambiar `suspend` a `false`.

El `ConfigMap/longhorn-system-backup-window` está cerrado por defecto
(`authorized: "false"`). Fusionar o sincronizar el manifiesto base no crea un
`SystemBackup`.

La cuenta del runner solo puede leer los `Schedule` y `Backup` de Velero. No
puede impedir atómicamente que otro principal autorizado cree un Backup justo
después de una lectura. Por eso no se promete exclusión bidireccional ni
recurrencia automática: cada ejecución necesita una ventana exclusiva GitOps,
la pausa verificada de todos los schedules y un freeze de escrituras manuales.

Longhorn 1.11.2 guarda siempre el bundle de `SystemBackup` en
`BackupTarget/default`. El target debe ser externo al clúster y al domicilio;
un NFS en `ubuntu`, un endpoint `*.svc.cluster.local` o MinIO dentro del mismo
clúster no constituyen recuperación ante desastre.

## Gates de datos y salud

Antes de abrir una ventana deben cumplirse todos estos gates:

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
5. Un volumen Longhorn solo es seguro si está `attached/healthy`,
   `detached/healthy` o `detached/unknown`. `faulted`, `degraded`, estados
   vacíos y cualquier otra combinación bloquean la ejecución.
6. Todo volumen no-standby/no-linked tiene `status.lastBackup`.
7. El primer `if-not-present` se hace sin builds, rebalanceos, snapshots,
   migraciones de storage ni otro writer concurrente.

## Apertura de una ventana exclusiva

La apertura es un cambio coordinado en los dos repos GitOps propietarios. No se
debe lanzar el Job hasta que ambos cambios estén sincronizados y verificados:

1. En `k8s-infra-pocharlies`, pausar `daily-aiops`, `daily-critical` y
   `weekly-all`. En `dgx-infra`, pausar `daily-x86-critical`.
2. En este ConfigMap cambiar, dentro del mismo cambio revisado:
   - `authorized: "true"`;
   - `runId`: identificador DNS único de 1 a 31 caracteres, nunca reutilizado;
   - `expiresAt`: entre 25 h 10 min y 30 h desde el arranque previsto;
   - `changeRef`: PR/cambio aprobado que identifica la ventana;
   - `k8sInfraRollbackRevision` y `dgxInfraRollbackRevision`: commits completos
     de 40 caracteres a los que se restaurará la configuración;
   - `expectedVeleroSchedules`: exactamente
     `daily-aiops,daily-critical,daily-x86-critical,weekly-all`.
3. Sincronizar las aplicaciones Argo CD propietarias y verificar en el runtime
   que el inventario de schedules es exactamente ese y que todos tienen
   `spec.paused=true`. Un schedule nuevo, ausente o no pausado cierra el gate.
4. Verificar que no hay Backup de Velero activo ni Backup Longhorn no terminal.
5. Declarar un freeze exclusivo: nadie crea Backups Velero manuales, reanuda un
   schedule, inicia otro SystemBackup ni cambia storage hasta cerrar la ventana.

Comprobaciones mínimas, siempre read-only:

```sh
kubectl -n velero get schedules.velero.io \
  -o custom-columns=NAME:.metadata.name,PAUSED:.spec.paused
kubectl -n velero get backups.velero.io \
  -o custom-columns=NAME:.metadata.name,PHASE:.status.phase
kubectl -n longhorn-system get configmap longhorn-system-backup-window -o yaml
kubectl -n longhorn-system get systembackups.longhorn.io,systemrestores.longhorn.io
```

## Ejecución manual y protección contra replay

Solo después de los gates anteriores se deriva exactamente un Job de la
plantilla suspendida:

```sh
RUN_ID='<mismo-runId-aprobado-en-GitOps>'
kubectl -n longhorn-system create job \
  --from=cronjob/longhorn-system-backup \
  "longhorn-system-backup-job-${RUN_ID}"
```

El runner crea el nombre determinista
`SystemBackup/longhorn-system-backup-${RUN_ID}`. Mientras existe, ese objeto es
el cerrojo y el registro de consumo de la ventana:

- dos Jobs concurrentes compiten por el mismo nombre; solo un `POST` puede
  ganar y el otro falla cerrado;
- si el Job muere después del `POST`, el controlador Longhorn continúa y un
  retry no puede duplicar el backup;
- si ese nombre ya existe, la ventana está consumida aunque el estado sea
  `Ready` o `Error`; nunca se reutiliza el `runId`.

La retención elimina objetos `Ready` administrados cuando superan cuatro, por
lo que el CR no es un ledger anti-replay eterno. La revisión de apertura debe
comprobar en el historial Git de `longhorn-system-backup-window` que el `runId`
no apareció antes. Ese historial y `changeRef` son el registro durable; no se
debe afirmar que el runner puede demostrar por sí solo la unicidad histórica.

El runner fija el UID y `metadata.generation` inicial de cada schedule, además
del conjunto inicial de UID de Backup Velero. Vuelve a leer la autorización, el
snapshot completo de ventana y ese estado de Velero antes del `POST`, en cada
poll y antes de la retención. Falla aunque un schedule se haya despausado y
vuelto a pausar o un Backup nuevo ya haya terminado. Una violación no borra el
SystemBackup ni intenta cancelar controladores de manera incierta.

El runner sigue siendo read-only sobre Velero: no puede detectar un objeto que
otro principal cree y borre por completo entre dos polls, ni impedir el write
atómicamente. El freeze manual/admission de la ventana sigue siendo obligatorio.

Monitorización:

```sh
kubectl -n longhorn-system logs -f \
  "job/longhorn-system-backup-job-${RUN_ID}"
kubectl -n longhorn-system get \
  "systembackup.longhorn.io/longhorn-system-backup-${RUN_ID}" -w
```

Solo un estado `Ready`, resincronizado desde el target remoto y cuyo bundle se
puede descargar, cuenta como éxito. La retención conserva cuatro backups
`Ready` administrados por el runner y solo se ejecuta después de ese éxito;
backups manuales o en `Error` no se borran.

Los Jobs creados con `kubectl create job --from=cronjob` no están gobernados por
`concurrencyPolicy` ni por los límites de historial del CronJob. La exclusión
real es el nombre determinista del SystemBackup. Cada Job lleva
`ttlSecondsAfterFinished: 604800`; hay que exportar logs y evidencia antes de
que se elimine automáticamente una semana después de terminar.

## Cierre, rollback y recuperación de fallo

El cierre también es GitOps explícito:

1. Preparar y fusionar los cambios que restauran las configuraciones de ambos
   repos desde `k8sInfraRollbackRevision` y `dgxInfraRollbackRevision`.
2. Restaurar el ConfigMap base: `authorized: "false"`, `runId: closed`, fecha
   expirada, `changeRef: closed` y revisiones `unset`.
3. Sincronizar ambos propietarios en Argo CD y verificar que el ConfigMap está
   cerrado y que cada schedule ha recuperado exactamente su política anterior.
4. Registrar Job, SystemBackup, resultado, target y los commits de apertura y
   cierre. No dejar el freeze levantado solo porque el Job terminó.

Si falla antes del `POST`, se puede cerrar la ventana. Si falla después del
`POST`, expira la ventana o no se conoce el punto exacto, se mantiene el freeze,
se inspecciona el SystemBackup determinista y se espera a un estado terminal.
No se reanuda Velero mientras haya un SystemBackup o Backup Longhorn activo. No
hay replay, purge ni segundo Job hasta clasificar el objeto; una nueva ejecución
requiere otro `runId` y otra ventana revisada.

## Separación entre backup y restore

No existe ningún manifiesto `SystemRestore` y la cuenta del Job no tiene verbos
de escritura sobre `systemrestores.longhorn.io`. Un restore es una operación
manual, destructiva y con ventana exclusiva.

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
restaurabilidad. SystemBackup no sustituye el restore drill.

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
