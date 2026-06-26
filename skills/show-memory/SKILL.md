---
name: show-memory
description: Show this project's Claude Code memory in Obsidian or any file browser. Links the project's memory directory into the project as a "claude memory" folder so you can read, revisit, and prune the agent's stored memories. Creates the memory dir empty if the project has none yet. Use when Brett wants to view, browse, or audit a project's claude memory. Run from the project directory whose memory you want to surface.
---

# show-memory

Claude Code keeps per-project memory as markdown files (YAML frontmatter, one fact per file, plus a `MEMORY.md` index) under `~/.claude/projects/<key>/memory/`. The files are already Obsidian-native, but they sit in a hidden path you rarely look at. This skill drops a symlink named `claude memory` into the project directory pointing at that memory folder, so the notes render in Obsidian on desktop and in any editor. The point is to make the agent's memory visible so you can revisit it and prune stale entries that have turned into bad habits.

## When to run

From the project directory whose memory you want to see. Running it in `/Users/brett/Documents/consulting` shows the consulting memory; running it in a client subdir shows that client's memory. The key is the directory you are in.

## Steps

1. Run the helper script. By default it acts on the current directory:
   ```
   bash ~/.claude/skills/show-memory/setup-link.sh
   ```
   To act on a different project, name, or target:
   ```
   bash ~/.claude/skills/show-memory/setup-link.sh --dir /path/to/project --name "claude memory"
   ```
2. The script:
   - Computes the project's memory dir from the directory path (mapping `/`, spaces, `~`, `.` and similar to `-`, as Claude Code does), or use `--target` to point at an explicit memory dir.
   - Creates that memory dir empty if it does not exist yet, so the folder is present but blank.
   - Creates the `claude memory` symlink. It is idempotent (re-running is a no-op) and will not overwrite a real file or a symlink pointing somewhere else.
   - If the project is a git repo, adds the linked folder to that directory's `.gitignore`, so git does not track the symlink and search tools that honor `.gitignore` (Grep, Glob, the `@` file picker) skip it. Pass `--no-gitignore` to leave `.gitignore` alone. Non-git projects are untouched.
3. Report what was linked and how many memory files are present.

If the script reports a conflicting name, either remove the old item or re-run with `--name` to pick a different folder name.

### Getting the target right

The script computes the memory dir from the directory path, which is correct in normal use. If you are unsure the encoding matched (paths with unusual characters), confirm the target exists, or pass `--target` with the memory path from this session's Memory configuration (the path ending in `/memory/` shown in the system prompt).

## Caveats

- Desktop only by default. iCloud and Obsidian Sync do not sync symlinks, so a linked folder inside an iCloud vault will not appear on mobile. For mobile, a one-way mirror that copies the files into the synced vault is needed instead. This skill does not set that up.
- Editing a memory note through the link writes to the real memory file. It is live, not a copy.
- One link per project. The folder shows that project's memories only. Run the skill separately in each project you want surfaced.
