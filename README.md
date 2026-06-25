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

## Install with a coding agent

If you use Claude Code or another agent, tell it to install a skill and it can do the whole thing without the checklist:

```sh
curl -fsSL https://raw.githubusercontent.com/buildbrett/skills/main/install.sh | bash -s -- --skill show-memory
```

Claude Code watches `~/.claude/skills/` and picks up a newly installed skill in the same session, so the agent can install it and then run it for you, no restart needed. The one exception: if `~/.claude/skills/` did not exist when the session started, that new directory needs a restart before it is watched. A good agent flow is: run the install command above, then offer to run the skill in the current project.

## Reference

### Utilities

- **[show-memory](./skills/show-memory/SKILL.md)** — shows a project's Claude Code memory in Obsidian or any file browser by linking it into the project as a `claude memory` folder. Makes the agent's memory explicit and easy to revisit, so you can update or purge stale entries that have turned into bad habits. Creates the memory dir empty if the project has none yet. User-invoked.
