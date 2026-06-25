# AGENTS.md

Notes for coding agents working with or installing from this repo.

## Layout

```
skills/
  <skill-name>/
    SKILL.md      # name + description frontmatter, then instructions
    ...           # any helper scripts the skill runs
install.sh        # checklist installer (also non-interactive modes)
```

One folder per skill under `skills/`. The installer finds every `SKILL.md` under `skills/` and copies its folder into `~/.claude/skills/<skill-name>/`.

## Installing a single skill

The interactive checklist needs a real terminal, so for an agent use the non-interactive flag:

```sh
curl -fsSL https://raw.githubusercontent.com/buildbrett/skills/main/install.sh | bash -s -- --skill <skill-name>
```

Other modes: `--all` installs everything, `--list` prints skill names. `SKILLS_SRC=DIR` installs from a local checkout instead of downloading.

After installing, offer to run the skill in the current project.

## Reloading

Claude Code watches `~/.claude/skills/` and picks up a newly installed skill in the same session, so you can install and then invoke it without a restart. The exception: if `~/.claude/skills/` did not exist when the session started, that directory needs a restart before it is watched. These are plain skills (no plugin features), so `/reload-plugins` is not needed.
