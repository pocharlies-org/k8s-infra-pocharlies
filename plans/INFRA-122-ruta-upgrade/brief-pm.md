# Brief pm — crear la historia (despachar con Agent(subagent_type: company-pm, run_in_background: false))

Pegar como prompt, sustituyendo nada (está autocontenido):

---

Eres pm en la compañía. Tarea única: crear una historia en Jira (servidor MCP local `atlassian`,
herramientas `jira_*`; cárgalas con ToolSearch si aparecen diferidas — NO uses el conector
claude.ai Atlassian Rovo). No toques nada más: ni código, ni cluster, ni transiciones, ni
comentarios (`jira_add_comment` prohibido).

Qué crear: historia (issue type "Story") en el proyecto **INFRA**, vinculada como hija de la
épica **INFRA-122** (campo Epic Link; p. ej. `jira_link_to_epic`).

Título exacto: Ruta de upgrade Longhorn 1.11.2 a la primera version publicada con el fix

Asignación: "Daniel Ibanez Fernandez", account_id `5b756d727cefaf05bcc36fbe` (igual que las
hermanas INFRA-165/166/168/169).

Campos/etiquetas: si el proyecto INFRA tiene campos custom "Sesión CTO" y "Agente", rellénalos
con `a3f4f554-1272-44bb-83a4-fe1092df119e` y `agent-a8ea037d915feae5f`; si no existen, añade las
etiquetas `session-a3f4f554-1272-44bb-83a4-fe1092df119e` y `agent-a8ea037d915feae5f`.

Descripción: el contenido de
`/home/dibanez/k8s/k8s-infra-pocharlies/plans/INFRA-122-ruta-upgrade/00-spec.md`
(Léelo con la herramienta Read; úsalo tal cual como descripción de la historia, sin ángulos <>).

Restricciones: NO transiciones la historia (queda en Backlog/To Do); NO adjuntes ficheros; NO
escribas comentarios; NO toques las hermanas.

Informe: clave INFRA-xxx creada y URL; confirmación de épica vinculada, asignatario y
etiquetas/campos usados; estado inicial; errores tal cual (p. ej. si el campo Epic Link se llama
otro en este proyecto — prueba el que exista y dilo).
