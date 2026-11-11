# Runbook — registries.yaml de Harbor en los nodos OVH (INFRA-1099)

Qué es y por qué. Los nodos de OVH (ks5-cp-1/2/3, sauvage, atlantic) bajaban
las imágenes de Harbor por la casa: el espejo apuntaba a
`https://harbor.lan.e-dani.com` (192.168.50.240, el Traefik LAN). Con el x86
apagado ningún pod de OVH que se recreaba arrancaba (`ImagePullBackOff`).
Ahora los dos nombres de registro (`harbor.e-dani.com` y
`harbor.lan.e-dani.com`, el que referencian las 28 apps) espejan al edge
público, que ya sirve `harbor-core`
(`networking/traefik-edge/harbor-ingressroute.yaml`). Ningún prefijo de imagen
se renombra: el espejo separa el nombre de la ruta.

Fichero versionado (fuente de verdad):
- Plantilla: `ansible/roles/k3s_worker/templates/registries.yaml.j2` (espejo
  idéntico en `ansible/roles/k3s_control_plane/templates/`).
- Tarea + handler: `ansible/roles/*/tasks/registries.yml` y
  `ansible/roles/*/handlers/main.yml`. El handler reinicia k3s/k3s-agent
  porque el agente solo lee `registries.yaml` al arrancar.
- Playbook: `ansible/playbooks/apply-registries.yml`.
- Grupo: `ovh_nodes` (children `ks5_control_plane` + `ovh_workers`) en el
  inventario `ansible/inventory/ks5-tailscale.ini`. Los nodos de casa (ubuntu,
  sparks) no reciben el fichero: `harbor_registries_enabled` solo está en
  `ansible/group_vars/ovh_nodes.yml`.

## Aplicar

El paso es operativo, no de ArgoCD: ArgoCD reconcilia el clúster, no `/etc`
de un nodo. Se ejecuta desde el host de control (x86), con el inventario de
day-2 (el SSH público :22 está cerrado por el hardening tailscale-only):

```bash
cd ~/k8s/k8s-infra-pocharlies
ansible-playbook -i ansible/inventory/ks5-tailscale.ini \
  ansible/playbooks/apply-registries.yml
```

`serial: 1`: el handler reinicia k3s/k3s-agent nodo a nodo. El fichero se
escribe `0600 root:root`.

### Contraseña (nunca en git)

La contraseña del robot de pull se lee del vault `k8s-pocharlies` de 1Password
en el host de control con un lookup `op read` (`op-secret`, copia in-cluster
vía Connect, sin cupo diario). El ítem es
`infra-harbor-k8s-runtime-pull` (campo `dockerconfigjson`); la tarea extrae
usuario y contraseña de la entrada `harbor.e-dani.com` (variable
`harbor_registries_auth_host` en `ansible/group_vars/ovh_nodes.yml`).
La tarea va con `no_log: true`: el valor no se imprime ni va a git.

### sauvage (nodo sin sudo sin contraseña)

`ubuntu@sauvage` no tiene sudo sin contraseña (la clave no está en 1Password;
INFRA-937), pero sí `NOPASSWD` para `docker` y `systemctl`. La tarea
`registries_write_via_docker` (activada en `[sauvage:vars]`) renderiza el
fichero en el host de control (`0600`, borrado al terminar) y lo escribe con
un contenedor `alpine` en `docker` root con bind-mount de `/etc/rancher/k3s`,
comparando dentro del contenedor para no tocar el fichero si no cambia. El
reinicio del agente usa `sudo -n systemctl restart k3s-agent` (NOPASSWD). No
se añade ningún privilegio nuevo.

## Pin de `/etc/hosts` al borde público (INFRA-1099 ronda 2 · INFRA-1276)

El espejo del `registries.yaml` separa nombre de destino, pero el destino se
resuelve por DNS, y el DNS del tailnet (MagicDNS → AdGuard de casa) responde
`192.168.50.240` (el Traefik LAN de la casa) también por `harbor.e-dani.com`:
con la casa inaccesible, el pull de una imagen no cacheada caía en
`dial tcp 192.168.50.240:443` (salida literal en INFRA-1276). El mismo
playbook fija además el nombre del destino del espejo al borde público en
`/etc/hosts` de los nodos del grupo, en un bloque marcado
`# BEGIN/END INFRA-1099 harbor-publico`: idempotente por las dos vías
(`blockinfile` con become; contenedor docker con escritura in-place en
sauvage). `containerd` resuelve en cada pull: cambiar el pin **no** requiere
reiniciar k3s/k3s-agent.

Las IPs viven en `harbor_public_edge_ips`
(`ansible/group_vars/ovh_nodes.yml`): son las del proxy de
Cloudflare que sirve `e-dani.com`. Cloudflare puede rotar sus IPs de proxy —
si un pull falla con timeout o `no such host` resolviendo `harbor.e-dani.com`
sin estar la casa cortada, re-verificar contra un resolutor público y
actualizar la lista:

```bash
dig +short harbor.e-dani.com @1.1.1.1   # debe coincidir con harbor_public_edge_ips
```

Tras cambiar la lista, volver a ejecutar el playbook (repite la prueba
destructiva de abajo). En cada nodo OVH el pin se comprueba con
`getent hosts harbor.e-dani.com` → una IP de `harbor_public_edge_ips`, nunca
`192.168.50.240`.

## Verificación (criterio C1)

En cada nodo OVH, un `crictl pull` de una imagen referenciada como
`harbor.lan.e-dani.com/...` con digest no cacheado debe terminar sin ningún
`dial tcp` a `192.168.50.240`. En atlantic se prueba además con la ruta LAN
cortada (y vuelta por temporizador):

```bash
# atlantic: cortar la ruta LAN con temporizador de vuelta y de seguridad
ssh atlantic '
  sudo ip route del 192.168.50.0/24 table 52
  systemd-run --on-active=90s  --unit=infra1099-restore-1 \
    sudo ip route add 192.168.50.0/24 dev tailscale0 table 52
  systemd-run --on-active=180s --unit=infra1099-restore-2 \
    sudo ip route add 192.168.50.0/24 dev tailscale0 table 52'
# pull de prueba (imagen NO cacheada, referenciada por harbor.lan)
ssh atlantic 'sudo crictl pull harbor.lan.e-dani.com/homelab/<img>:<tag>'
# comprobar restauración
ssh atlantic 'ip route show table 52 | grep 192.168.50'
```

El pull no debe mostrar `dial tcp ... 192.168.50.240`. La ruta queda
restaurada por el temporizador (comprobar `ip route show table 52`).

Desde la ronda 2 esta prueba se ejecuta **sin tocar `/etc/hosts` a mano**:
el pin del borde público lo aporta el playbook (sección anterior). En
sauvage la prueba de rutas necesita root completo (INFRA-937: allí solo hay
`sudo -n` para `docker`/`systemctl`), así que en ese nodo la verificación es
`getent hosts harbor.e-dani.com` → IP del borde.

## Rotación

Tras rotar el robot de pull (runbook
`docs/runbooks/runtime-credential-rotation.md`, ítem
`infra-harbor-k8s-runtime-pull`), volver a ejecutar el playbook: el lookup
`op read` recoge la credencial nueva y el handler reinicia el agente. No hay
que tocar el fichero a mano en ningún nodo.
