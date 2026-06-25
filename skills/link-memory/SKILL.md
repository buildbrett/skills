---
name: link-memory
description: Symlink the current project's Claude Code memory directory into the project as a "Claude memory" folder, so the memories show up in Obsidian or any file browser. Creates the memory dir empty if the project has none yet. Use when Brett wants to view, expose, or browse a project's Claude memory in Obsidian. Run from the project directory whose memory you want to surface.
---

# link-memory

Claude Code keeps per-project memory as markdown files (YAML frontmatter, one fact per file, plus a `MEMORY.md` index) under `~/.claude/projects/<key>/memory/`. The files are already Obsidian-native. This skill drops a symlink named `Claude memory` into the project directory pointing at that memory folder, so the notes render in Obsidian on desktop and in any editor.

## When to run

From the project directory whose memory you want to see. Running it in `/Users/brett/Documents/consulting` links the consulting memory; running it in a client subdir links that client's memory. The key is the directory you are in.

## Steps

1. Run the helper script. By default it acts on the current directory:
   ```
   bash ~/.claude/skills/link-memory/setup-link.sh
   ```
   To link a different project, name, or target:
   ```
   bash ~/.claude/skills/link-memory/setup-link.sh --dir /path/to/project --name "Claude memory"
   ```
2. The script:
   - Computes the project's memory dir from the directory path (the same `/`, space and `~` to `-` encoding Claude Code uses), or use `--target` to point at an explicit memory dir.
   - Creates that memory dir empty if it does not exist yet, so the folder is present but blank.
   - Creates the `Claude memory` symlink. It is idempotent (re-running is a no-op) and will not overwrite a real file or a symlink pointing somewhere else.
3. Report what was linked and how many memory files are present.

If the script reports a conflicting name, either remove the old item or re-run with `--name` to pick a different folder name.

### Getting the target right

The script computes the memory dir from the directory path, which is correct in normal use. If you are unsure the encoding matched (paths with unusual characters), confirm the target exists, or pass `--target` with the memory path from this session's Memory configuration (the path ending in `/memory/` shown in the system prompt).

## Caveats

- Desktop only by default. iCloud and Obsidian Sync do not sync symlinks, so a linked folder inside an iCloud vault will not appear on mobile. For mobile, a one-way mirror that copies the files into the synced vault is needed instead. This skill does not set that up.
- Editing a memory note through the link writes to the real memory file. It is live, not a copy.
- One link per project. The folder shows that project's memories only. Run the skill separately in each project you want surfaced.
