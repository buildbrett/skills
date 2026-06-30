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

The description and the dependencies are listed separately for each skill. The installer itself needs only bash; the dependencies are what a skill needs when you actually run it.

### Utilities

**[show-memory](./skills/show-memory/SKILL.md)** — shows a project's Claude Code memory in Obsidian or any file browser by linking it into the project as a `claude memory` folder. Makes the agent's memory explicit and easy to revisit, so you can update or purge stale entries that have turned into bad habits. Creates the memory dir empty if the project has none yet. User-invoked.

- Dependencies: none beyond a shell. Obsidian is optional, for viewing the notes.

**[push-to-google-docs](./skills/push-to-google-docs/SKILL.md)** — pushes a local markdown file to Google Docs with tables, formatting, embedded images, and mermaid diagrams. Built to be fast: mermaid renders locally with Merman (no headless browser), and the whole document uploads once as a self-contained `.docx` for Google to convert, so a typical push takes a few seconds and only the finished document leaves your machine. Connects through whatever Google access the project already has (gws CLI, a Drive/Docs MCP, or OAuth). User-invoked. Run `/push-to-google-docs --setup` once to install the dependencies.

- Dependencies: pandoc and python3; a Google transport (gws CLI, a Drive/Docs MCP, or OAuth credentials); and, for mermaid diagrams, Merman (`cargo install merman-cli`), which needs Rust/cargo.
