# skills

Agent skills I find useful as a product manager and for software engineering, shared in case they're useful to you. Each skill lives in its own folder under `skills/` with a `SKILL.md`.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/buildbrett/skills/main/install.sh | bash
```

A checklist appears in your terminal. Move with up/down, toggle a skill with space, press Enter to install the checked ones into `~/.claude/skills` (global). Restart Claude Code to load them. No npx, no node, just bash.

Other ways to run it:

```sh
# install everything, no prompt
curl -fsSL https://raw.githubusercontent.com/buildbrett/skills/main/install.sh | bash -s -- --all

# just list the skills
curl -fsSL https://raw.githubusercontent.com/buildbrett/skills/main/install.sh | bash -s -- --list

# install from a local checkout
SKILLS_SRC=. bash install.sh
```

## Reference

### Utilities

- **[link-memory](./skills/link-memory/SKILL.md)** — symlinks a project's Claude Code memory directory into the project as a `Claude memory` folder, so you can read it in Obsidian or any file browser. Makes the agent's memory explicit and easy to revisit, so you can update or purge stale entries that have turned into bad habits. Creates the memory dir empty if the project has none yet. User-invoked.
