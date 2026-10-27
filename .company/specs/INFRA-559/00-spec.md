Rol: pm · Fecha: 2026-10-05T22:20:39Z · Sesión: 22e2f096-209d-4185-9fe9-9b78b32aff96 · Estado: LISTO

# INFRA-559 — Orden y documentación de la casa

Hija C de INFRA-490. Repo: home-assistant (pocharlies-org/home-assistant, trunk main).
Depende de: INFRA-557 (instancia GitOps + backup y restauración probados) e INFRA-558 (inventario).
INFRA-558 bloquea esta épica (enlace Blocks): no arranca hasta que el inventario termine.

## Valor

Dani y Leila abren el móvil o preguntan a Jarvis y encuentran cada luz, cada panel y cada nombre
donde esperan, en su zona de la casa, y cualquier persona que toque la config después entiende qué
hay y dónde está sin rebuscar. Si esto no se hace, la casa seguirá con nombres sueltos («Comedor
fuera», «Por ordenar», «Apple TV (2)»), un solo panel vacío y cero documentación: cada automatisation
o compra nueva se decidirá a ciegas y los errores se heredarán.

## Objetivo

Ordenar la casa dentro de Home Assistant —áreas por estancia con nombres coherentes, etiquetas, un
panel por zona exportado al repo— y documentarlo todo en `docs/` del repo home-assistant, con una
lista priorizada de lo que falta. Es configuración, textos y documentación: sin código, sin hardware,
todo reversible con revert.

## Estado de partida (medido 2026-10-05, `kubectl -n homeassistant exec deploy/homeassistant`, python3 sobre `/config/.storage/`)

- `core.area_registry`: 21 áreas con nombres inconsistentes: 'Apple TV (2)', 'Comedor fuera', 'Despacho',
  'Dormitorio papas', 'Escaleras', 'Galería', 'Interruptor recibidor', 'Interruptores cocina', 'Jardin',
  'Jardin delante', 'Lateral cocina', 'Luz de noche', 'Mesa', 'Parca', 'Piscina', 'Por ordenar', 'Recibidor',
  'Salón', 'Baño', 'Casa', 'Cocina'.
- `core.device_registry`: 159 dispositivos, 117 con area_id.
- `core.entity_registry`: 807 entidades operativas; 245 sin área propia ni de su dispositivo. La mayoría
  son ENTIDADES DE SERVICIO sin ubicación física (sun.*, backup.*, weather.*, person.*, todo.*, tts.*):
  quedan EXENTAS — el criterio cuenta solo entidades vinculadas a un dispositivo físico.
- `core.tag_registry` NO existe: no hay ni una etiqueta.
- `lovelace_dashboards`: UN solo dashboard en modo storage, 'map', con 0 views. Los paneles por zona
  están por hacer del todo.
- Repo home-assistant: NO existe `docs/` ni `config/dashboards/` (solo `config/{automations,scenes,scripts,configuration}.yaml`
  y `custom_components`). `ARCHITECTURE.md` existe (commit 193660f).
- jarvis (`/home/dibanez/k8s/jarvis`): `backend/tools/homeassistant_client.py` es genérico (entity_id por
  parámetro, sin entity_ids hardcodeados). Aun así hay que grepear entity_ids literales antes de renombrar.

## Criterios de aceptación

- [ ] **1. Toda entidad operativa vinculada a un dispositivo físico tiene área y sigue la convención de
      `docs/convenciones.md`; las etiquetas existen.**
      Comando (área por dispositivo físico):
      `kubectl -n homeassistant exec deploy/homeassistant -- python3 -c "`
      `import json`
      `E=json.load(open('/config/.storage/core.entity_registry'))['data']['entities']`
      `D={d['id']:d for d in json.load(open('/config/.storage/core.device_registry'))['data']['devices']}`
      `print(sum(1 for e in E if e.get('device_id') and e['device_id'] in D and not D[e['device_id']].get('disabled_by') and not e.get('area_id') and not D[e['device_id']].get('area_id')))"`
      Esperado: `0` (hoy: 245 entidades sin área en total; las de servicio sin dispositivo — sun, weather,
      person, todo, tts, stt, calendar, backup, conversation y similares — quedan exentas y no cuentan).
      Comando (etiquetas):
      `kubectl -n homeassistant exec deploy/homeassistant -- python3 -c "import json,os;p='/config/.storage/core.tag_registry';print(len(json.load(open(p))['data']['tags']) if os.path.exists(p) else 'NO EXISTE')"`
      Esperado: un número ≥ 1 (hoy: `NO EXISTE`).

- [ ] **2. Un panel por zona en modo storage, exportado al repo en `config/dashboards/`.**
      Comando (en HA):
      `kubectl -n homeassistant exec deploy/homeassistant -- python3 -c "import json;print([(i.get('url_path'),len(i.get('views',[]))) for i in json.load(open('/config/.storage/lovelace_dashboards'))['data']['items']])"`
      Esperado: un dashboard `url_path` por zona final, cada uno con sus vistas y entidades
      (hoy: `[('map', 0)]` — solo 'map' con 0 views).
      Comando (en el repo): `git -C /home/dibanez/k8s/home-assistant ls-files config/dashboards/`
      Esperado: los JSON de los paneles versionados (hoy: vacío, el directorio no existe).

- [ ] **3. `docs/` del repo con `docs/estancias.md` (una sección `## ` por área final), `docs/convenciones.md`
      (nombres, áreas, etiquetas) y `docs/recuperacion.md` (enlaza el backup y la restauración probada de INFRA-557).**
      Comando: `ls /home/dibanez/k8s/home-assistant/docs/ && grep -c '^## ' /home/dibanez/k8s/home-assistant/docs/estancias.md`
      Esperado: los 3 ficheros listados; el recuento = nº de áreas finales (coherente con el área_registry).

- [ ] **4. `docs/pendiente.md`: lista numerada priorizada de lo que falta, cada item con su motivo de orden.**
      Comando: `grep -c '^[0-9]\+\. ' /home/dibanez/k8s/home-assistant/docs/pendiente.md`
      Esperado: ≥ 1.

- [ ] **5. Lo que sea compra sale como Acción en el proyecto ACC asignada a secretaria-casa, con referencia
      a INFRA-490/INFRA-559 — o «ninguna compra» explícito en `docs/pendiente.md`.** Aquí no se compra nada:
      la secretaria prepara y Dani confirma. Verificación: los enlaces ACC citados en pendiente.md existen,
      o el literal «ninguna compra» está (`grep -in 'ninguna compra' docs/pendiente.md`).

- [ ] **6. No se rompe nada: `check_config` da Successful config test y tras cada renombramiento el grep de
      entity_ids literales en jarvis sale actualizado (los consumidores siguen respondiendo).**
      Comando: `kubectl -n homeassistant exec deploy/homeassistant -- python -m homeassistant --script check_config -c /config`
      Esperado: `Successful config test`.
      Comando (consumidores): `git -C /home/dibanez/k8s/jarvis grep -nE "(light|switch|sensor|binary_sensor|climate|cover|media_player|scene|script)\.[a-z0-9_]+" -- backend/ | grep -v homeassistant_client`
      Esperado: ningún entity_id renombrado quede obsoleto (hoy el cliente es genérico: se comprueba, no se asume).

## Restricciones

- Renombrar entidades puede romper a Jarvis y a los agentes: se grepa en pocharlies/jarvis y se cambia junto,
  en la misma historia.
- Solo config, textos y docs: nada de código ni hardware; todo reversible con revert.
- Sin compras: la secretaria prepara, Dani confirma (criterio 5).
- El token `ha-dashboard` de 1Password/Vault no se imprime nunca.
- Se trabaja sobre la instancia GitOps (INFRA-557) y con el inventario (INFRA-558), sin repetir su trabajo.

## Historias previstas (orden y por qué)

1. **Áreas, nombres y etiquetas** (dueño: developer) — base de todo lo demás: los paneles, docs y grep
   de consumidores cuelgan de las áreas finales. Criterios 1 y 6.
2. **Paneles por zona exportados a `config/dashboards/`** (dueño: developer) — necesita las áreas de la 1.
   Criterio 2.
3. **`docs/` estancias + convenciones + recuperación** (dueño: writer) — documenta lo entregado por 1 y 2;
   recuperación enlaza INFRA-557. Criterio 3.
4. **`docs/pendiente.md` y Acciones ACC de compra** (dueño: pm) — al final, con la foto completa de lo que
   falta. Criterios 4 y 5.
5. **Verificación contra HA viva** (dueño: qa) — los 6 criterios con sus comandos sobre la instancia real.

## Diseño

Diseñador: no — se usan los paneles y vistas nativos de Home Assistant, sin interfaz nueva.

## Dificultad

Dificultad: baja — configuración, textos y documentación, todo reversible con revert.

## Tamaño

S.

## Trabajo reciente (24 h)

- 2026-10-05 00:09Z sesión e2d0f788 (reparto de INFRA-490): esta hija C creada con spec borrador; enlaces
  557→558→559 (Blocks).
- 2026-10-05: mediciones de arriba (premisas vivas, nada entregado aún). INFRA-557 e INFRA-558 en To Do
  con spec LISTO, sin ejecutar — esta épica no arranca hasta que 558 termine.
