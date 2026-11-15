Rol: tech-lead · Fecha: 2026-10-01 · Sesión: 7a35dec9-a361-4146-bb68-1e54b4683cb0 · Estado: LISTO

# INFRA-397 (P1) — designer-plugin versionado

Repo: /home/dibanez/src/x86-host-runtime-pocharlies (leer ARCHITECTURE.md, CLAUDE.md, README). Rama propia, un PR contra el tronco. Plan: 10-plan.md v3 y nota-architect-plan.md de INFRA-395 (mandan).

## Qué
Árbol nuevo `designer-plugin/` en la raíz (NO `skills/`: install.sh lo copia al `~/.claude/skills` global) con formato de plugin de Claude Code (`.claude-plugin/plugin.json` + `skills/<nombre>/SKILL.md`) y `LOCK.json` (por skill: repo origen, commit fijado, licencia, sha256). Vendorizado. `install.sh` lo instala en `~/.local/share/x86-host-runtime/designer-plugin/` (solo el diseñador lo carga, vía `--plugin-dir`, en P2).

## Contenido
- `web-design-guidelines` de `vercel-labs/agent-skills` (comprobar ANTES que no descarga reglas por URL al ejecutarse; si lo hace, vendorizar las reglas y documentarlo).
- `latent-spaces/brag`: EXCLUIDA (decisión del CTO: es un generador de vídeos de lanzamiento, extra opcional que se trata en INFRA-396). No se vendoriza ni figura en LOCK.json.
- Busca en el ecosistema (vercel-labs/agent-skills, skills.sh y similares) guías de paleta, tipografía, espaciados, micro-animaciones y componentes con licencia que permita vendorizar. NO inventes: lo que no exista, regístralo en `50-entrega.md` como hueco con lo buscado.

## Criterios
- [ ] `python3 -m unittest ci.test_design_skills` verde (árbol instalado == LOCK por sha256; cada skill tiene SKILL.md con frontmatter válido; licencia registrada).
- [ ] Ninguna skill del diseñador añadida a `~/.claude/skills` ni a `skills/` del repo (el test lo comprueba).
- [ ] El test está añadido al paso de CI de design-request del repo.
- [ ] `./install.sh` (o su modo dry-run documentado) deja el árbol en `~/.local/share/x86-host-runtime/designer-plugin/`.
- [ ] Documentación: README/ARCHITECTURE.md del repo mencionan `designer-plugin/`, o 1 línea diciendo que no hace falta.

## Entrega
Rama + PR contra el tronco que lea CI (compruébalo), `50-entrega.md` con la lista de skills de LOCK y los huecos. No despliegues, no mergees. Termina con rama, PR y run id.
