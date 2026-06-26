#!/usr/bin/env bash
# Symlink a project's Claude Code memory directory into the project as a folder
# Obsidian (or any editor) can browse. Idempotent and non-clobbering.
set -euo pipefail

LINK_NAME="claude memory"
TARGET=""
DIR="$PWD"
GITIGNORE=true

while [ $# -gt 0 ]; do
  case "$1" in
    --name)         LINK_NAME="$2"; shift 2;;
    --target)       TARGET="$2";    shift 2;;
    --dir)          DIR="$2";       shift 2;;
    --no-gitignore) GITIGNORE=false; shift;;
    -h|--help)
      echo "Usage: setup-link.sh [--dir PROJECT_DIR] [--target MEMORY_DIR] [--name LINK_NAME] [--no-gitignore]"
      echo "  --dir            Project directory to link into (default: current dir)"
      echo "  --target         Memory dir to point at (default: computed from --dir)"
      echo "  --name           Name of the folder created in the project (default: 'claude memory')"
      echo "  --no-gitignore   Do not add the linked folder to .gitignore when the project is a git repo"
      exit 0;;
    *) echo "Unknown arg: $1" >&2; exit 2;;
  esac
done

if [ ! -d "$DIR" ]; then echo "Project dir does not exist: $DIR" >&2; exit 1; fi
DIR="$(cd "$DIR" && pwd)"   # normalize to absolute

# Claude Code stores per-project memory at ~/.claude/projects/<key>/memory,
# where <key> is the absolute project path with non-word characters ('/', spaces,
# '~', '.' and similar) turned to '-'. For an unusual path, pass --target instead.
if [ -z "$TARGET" ]; then
  KEY="$(printf '%s' "$DIR" | sed 's#[/ .~]#-#g')"
  TARGET="$HOME/.claude/projects/$KEY/memory"
fi

CREATED_TARGET=false
if [ ! -d "$TARGET" ]; then
  mkdir -p "$TARGET"          # no memories yet: leave it blank
  CREATED_TARGET=true
fi

LINK="$DIR/$LINK_NAME"

if [ -L "$LINK" ]; then
  EXISTING="$(readlink "$LINK")"
  if [ "$EXISTING" = "$TARGET" ]; then
    echo "Already linked: $LINK -> $TARGET"
  else
    echo "A different symlink already exists: $LINK -> $EXISTING" >&2
    echo "Remove it, or pass --name to use a different folder name." >&2
    exit 1
  fi
elif [ -e "$LINK" ]; then
  echo "A real file or directory already exists at: $LINK (left untouched)." >&2
  echo "Pass --name to use a different folder name." >&2
  exit 1
else
  ln -s "$TARGET" "$LINK"
  echo "Linked: $LINK -> $TARGET"
fi

# If the project is a git repo, ignore the linked folder so git does not track
# the symlink and search tools that honor .gitignore skip it. No trailing slash:
# git sees a symlink-to-dir as a file, so the dir-only form would not match it.
if [ "$GITIGNORE" = true ] && git -C "$DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  GI="$DIR/.gitignore"
  ENTRY="/$LINK_NAME"
  if [ -f "$GI" ] && grep -qxF "$ENTRY" "$GI"; then
    echo "gitignore:    already ignores $ENTRY"
  else
    [ -f "$GI" ] && [ -n "$(tail -c1 "$GI" 2>/dev/null)" ] && printf '\n' >> "$GI"
    printf '%s\n' "$ENTRY" >> "$GI"
    echo "gitignore:    added $ENTRY to $GI"
  fi
fi

COUNT="$(find "$TARGET" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')"
echo "Project dir:  $DIR"
echo "Memory dir:   $TARGET$( [ "$CREATED_TARGET" = true ] && echo '  (created, empty)' )"
echo "Memory files: $COUNT markdown file(s)"
