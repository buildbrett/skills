# skills

A small collection of Claude Code skills, with a one-line installer.

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

## Skills

- `link-memory` — symlink a project's Claude Code memory directory into the project as a `Claude memory` folder, so the memories show up in Obsidian or any file browser. Creates the memory dir empty if the project has none yet.

## Layout

```
skills/
  <skill-name>/
    SKILL.md         # the skill (name + description frontmatter, instructions)
    ...              # any helper scripts the skill runs
install.sh           # the checklist installer
```

The installer finds every `SKILL.md` under `skills/` and copies its folder into `~/.claude/skills/`.
