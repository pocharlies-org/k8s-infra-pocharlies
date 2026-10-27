Rol: pm · Fecha: 2026-10-02T04:05:00Z · Sesión: 904c74fa-943a-429b-925e-e266cae52f6a · Estado: LISTO

## Objetivo

Estudiar si una app iOS tipo PLAUD (grabar → transcribir con hablantes → acta con plantilla) es viable sobre nuestra infraestructura propia, y demostrarlo con un prototipo de script que haga el pipeline completo sobre un audio real. No es construir la app: es entregar el documento de viabilidad con costes medidos y un veredicto HACER / NO HACER / MVP acotado; la app, si sale, será otra épica.

Relación con otras épicas (no duplicar): la transcripción ya existe en producción — `stt-turbo` (whisper + pyannote) en el ns `llm`, expuesto por LiteLLM como `whisper-1` y por Control Nexus (`/api/stt/diarize`); INFRA-368 (dentro de INFRA-364) está consumiendo ese STT para notas de voz de WhatsApp desde 30-09. Esta épica NO construye STT ni diarización: las usa, mide su coste real y estudia qué falta (app iOS, plantillas, búsqueda). DGX-174/DGX-178 (migración de la voz) ya no bloquean: `stt-turbo` corre hoy en `gx10-ec3d` (arm64), verificado 02-10.

Repo: k8s-infra-pocharlies

## Criterios de aceptación

- [ ] Existe el documento de viabilidad en el repo con las secciones obligatorias (Pipeline, Costes medidos, Comparativa con Plaud, Privacidad, Riesgos, Veredicto).
  ```
  f=~/k8s/k8s-infra-pocharlies/docs/estudios/INFRA-380-viabilidad-app-notas.md
  test -f "$f" && for s in Pipeline 'Costes medidos' 'Comparativa con Plaud' Privacidad Riesgos Veredicto; do grep -qi "$s" "$f" || echo "FALTA: $s"; done
  ```
  Salida esperada: ninguna línea `FALTA:` (exit 0).

- [ ] Prototipo: un script en el repo que toma un audio (wav/ogg/mp3), llama a lo que ya existe en el clúster — `POST /v1/audio/transcriptions` y `POST /v1/audio/diarizations` de `stt-turbo` (ns `llm`) y el LLM residente vía LiteLLM (modelo actual: grep `model_name:` en `~/k8s/k8s-litellm-pocharlies/k8s/manifest.yaml`) — y escribe un acta con plantilla (título, asistentes/hablantes con marcas `SPEAKER_NN`, resumen, puntos de acción).
  ```
  bash ~/k8s/k8s-infra-pocharlies/scripts/infra380/proto_nota.sh /tmp/muestra.wav /tmp/acta.md
  test -s /tmp/acta.md && grep -qi 'acta' /tmp/acta.md && grep -qE 'SPEAKER_[0-9]+' /tmp/acta.md && grep -qiE 'resumen|puntos de acción' /tmp/acta.md && echo OK
  ```
  Salida esperada: `OK`. El audio de prueba se puede generar con el TTS del clúster (`tts-mcp`, ns `tts-mcp`) o uno real de Telegram; dos altavoces mínimo para que la diarización sea visible.

- [ ] Costes MEDIDOS, no estimados: GPU-minutos y tiempo de pared por hora de audio, con la medición cruda guardada junto al documento (log o CSV con timestamps).
  ```
  grep -A8 'Costes medidos' ~/k8s/k8s-infra-pocharlies/docs/estudios/INFRA-380-viabilidad-app-notas.md | grep -E '[0-9]+([.,][0-9]+)?'
  ls ~/k8s/k8s-infra-pocharlies/docs/estudios/infra380-*medicion*
  ```
  Salida esperada: al menos una línea con una cifra (min/RTF) y un fichero de medición existente.

- [ ] Comparativa funcional con Plaud: tabla qué tiene Plaud / qué replicamos localmente / qué NO es replicable (hardware con 4 micros y beamforming, captura de llamadas por altavoz, librería de 10.000 plantillas, sincronización dispositivo-app).
  ```
  grep -A15 -i 'comparativa con plaud' ~/k8s/k8s-infra-pocharlies/docs/estudios/INFRA-380-viabilidad-app-notas.md | grep -c '^|'
  ```
  Salida esperada: ≥ 6 filas de tabla.

- [ ] Veredicto explícito y una línea de decisión de iOS: si se puede o no grabar llamadas de terceros (restricción de Apple) y qué alcance alternativo se propone (notas de voz + import de archivos + reuniones en persona).
  ```
  grep -E 'Veredicto: (HACER|NO HACER|MVP)' ~/k8s/k8s-infra-pocharlies/docs/estudios/INFRA-380-viabilidad-app-notas.md
  grep -qi 'llamada' ~/k8s/k8s-infra-pocharlies/docs/estudios/INFRA-380-viabilidad-app-notas.md && echo iOS-cubierto
  ```
  Salida esperada: una línea `Veredicto: …` y `iOS-cubierto`.

## Restricciones

- No comprar hardware ni suscripciones (ni Plaud) sin OK explícito de Dani.
- El resumen lo hace el LLM residente (qwen38-flash-next vía LiteLLM). API externa solo si el estudio demuestra calidad superior MEDIBLE; la demostración va en el documento.
- No crear cargas nuevas de GPU en los Sparks: el perfil vigente es `llm-tp` y en `ready` no cabe nada más allí (leer `kubectl get cm -n comfyui gpu-arbiter-state -o jsonpath='{.data.effective_mode}'` antes de cualquier prueba). El prototipo usa los endpoints ya residentes (`stt-turbo` en gx10-ec3d, omnivoice, LiteLLM); si algo no cabe, se documenta como hallazgo, no se fuerza.
- No tocar el arbiter ni las réplicas del residente (prohibido `kubectl scale`).
- Privacidad: todo el pipeline local; el estudio debe decir dónde queda el audio (borrado tras procesar o PVC, decidir y escribir).
- Nada de app iOS en esta épica (ni SwiftUI, ni TestFlight): solo script + documento.

## Trabajo reciente (24 h)

- Nada en 24 h que afecte a este plan directamente (sin sesiones tocando PLAUD/whisper/diarización; `stt-turbo` lleva ~28 h en `gx10-ec3d` tras reinicio ordinario).
- Contexto cercano que sí afecta (fuera de las 24 h, citado del brain):
  - 30-09 (sesión 8fd2c199, épica INFRA-364): INFRA-368 despacha la transcripción de notas de voz de WhatsApp sobre el STT existente, en dry-run — confirma que el pipeline de transcripción ya tiene consumidor real en la casa; esta épica no lo reconstruye.
  - 13-06-2026 (brain, rollout codex): benchmark autogestionado de STT — ganó `Systran/faster-whisper-large-v3` (CTranslate2 CUDA): WER ~0.56-0.60 con hint, latencia ~0.5-0.6 s/segmento; Qwen3-ASR 1.7B y Voxtral peores en nombres propios. El estudio cita ese benchmark y no lo repite desde cero; solo revalida sobre el servicio actual.
  - Existe la skill `dgx-speaker-diarization` (k8s-openclaw-qwen36-pocharlies): diarización pyannote accesible vía Control Nexus `/api/stt/diarize`, con RTTM y marcas de hablante — la pieza de diarización ya está resuelta.

## Diseño

Diseñador: no — la épica entrega un documento markdown y un script de prototipo; no hay ninguna pantalla ni interfaz. Si el veredicto es HACER/MVP, la épica de la app iOS llevará su diseñador (mockups + revisión UX) y será otro CTO.

## Historias previstas

- H1 Inventario y revalidación del ASR/diarización actuales: calidad (WER subjetivo, nombres propios, dos hablantes) sobre 2-3 audios reales usando `stt-turbo` residente, citando el benchmark de junio — dueño: developer.
- H2 Prototipo `proto_nota.sh`: audio → transcripción + diarización → acta con plantilla propia (reunión) vía LiteLLM residente — dueño: developer.
- H3 Medición de coste y latencia: GPU-min y tiempo de pared por hora de audio, log de medición, y comparación económica con Plaud (~99 €/año + hardware) — dueño: developer.
- H4 Estudio de límites iOS (grabación de llamadas de terceros, import de archivos, privacidad) y redacción del documento completo con comparativa y veredicto — dueño: tech-lead.

## Tamaño

M — cuatro historias, un repo, sin código de producción: el trabajo es medir, montar un script sobre endpoints que ya existen y escribir el veredicto. Menos de una semana.

## Dificultad

Dificultad: media — no hay decisión de arquitectura (reutiliza servicios residentes ya expuestos) ni toca secretos, GPU del árbitro ni datos irreversibles, pero hay que mirar qué existe (stt-turbo, LiteLLM, benchmark de junio, skill de diarización) antes de escribir para no duplicar ni medir sobre un camino muerto; se deshace con un revert.
