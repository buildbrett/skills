#!/usr/bin/env bash
# Installer for buildbrett/skills.
# Shows a checklist of the skills in this repo, installs the ones you pick into
# ~/.claude/skills (global). No npx, no node, just bash.
#
#   curl -fsSL https://raw.githubusercontent.com/buildbrett/skills/main/install.sh | bash
#
# Flags (pass with: curl ... | bash -s -- --all):
#   --all            install every skill, no prompt
#   --skill NAME     install just this skill, no prompt (repeatable). Good for agents.
#   --list           print the skill names and exit
#   -h, --help       show this help
# Env overrides:
#   SKILLS_SRC=DIR   install from a local checkout instead of downloading
#   SKILLS_DEST=DIR  install target (default ~/.claude/skills)
#   SKILLS_REPO=u/r  source repo (default buildbrett/skills)
#   SKILLS_BRANCH=b  branch (default main)
set -euo pipefail

REPO="${SKILLS_REPO:-buildbrett/skills}"
BRANCH="${SKILLS_BRANCH:-main}"
DEST="${SKILLS_DEST:-$HOME/.claude/skills}"
MODE="interactive"
WANT=()

while [ $# -gt 0 ]; do
  case "$1" in
    --all)     MODE="all" ;;
    --list)    MODE="list" ;;
    --skill)   MODE="skills"; WANT+=("$2"); shift ;;
    --skill=*) MODE="skills"; WANT+=("${1#*=}") ;;
    -h|--help) MODE="help" ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

c_reset=$'\033[0m'; c_dim=$'\033[2m'; c_bold=$'\033[1m'; c_rev=$'\033[7m'; c_grn=$'\033[32m'

if [ "$MODE" = "help" ]; then
  awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "${BASH_SOURCE[0]:-/dev/null}" 2>/dev/null \
    || echo "See https://github.com/$REPO"
  exit 0
fi

# --- Get the source tree -----------------------------------------------------
TMP=""; HID_CURSOR=0
cleanup() { [ "$HID_CURSOR" = "1" ] && printf '\033[?25h'; [ -n "$TMP" ] && [ -d "$TMP" ] && rm -rf "$TMP"; return 0; }
trap cleanup EXIT

if [ -n "${SKILLS_SRC:-}" ]; then
  SRC="$SKILLS_SRC"
else
  TMP="$(mktemp -d)"
  echo "Downloading $REPO@$BRANCH ..."
  if command -v git >/dev/null 2>&1; then
    git clone --depth 1 --branch "$BRANCH" "https://github.com/$REPO.git" "$TMP/repo" >/dev/null 2>&1 \
      || { echo "git clone failed for $REPO@$BRANCH" >&2; exit 1; }
    SRC="$TMP/repo"
  elif command -v curl >/dev/null 2>&1; then
    curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" | tar xz -C "$TMP" \
      || { echo "download failed for $REPO@$BRANCH" >&2; exit 1; }
    SRC="$(find "$TMP" -maxdepth 1 -mindepth 1 -type d | head -1)"
  else
    echo "Need git or curl to download. Neither found." >&2; exit 1
  fi
fi

SKILLS_DIR="$SRC/skills"
[ -d "$SKILLS_DIR" ] || { echo "No skills/ directory found in $SRC" >&2; exit 1; }

# --- Enumerate skills (any SKILL.md under skills/) ---------------------------
names=(); paths=(); descs=()
while IFS= read -r skfile; do
  d="$(dirname "$skfile")"
  nm="$(basename "$d")"
  fm_name="$(sed -n 's/^name:[[:space:]]*//p' "$skfile" | head -1)"
  [ -n "$fm_name" ] && nm="$fm_name"
  ds="$(sed -n 's/^description:[[:space:]]*//p' "$skfile" | head -1)"
  names+=("$nm"); paths+=("$d"); descs+=("$ds")
done < <(find "$SKILLS_DIR" -name SKILL.md | sort)

n=${#names[@]}
[ "$n" -gt 0 ] || { echo "No skills found under $SKILLS_DIR" >&2; exit 1; }

if [ "$MODE" = "list" ]; then
  for nm in "${names[@]}"; do printf '%s\n' "$nm"; done
  exit 0
fi

# --- Install helper ----------------------------------------------------------
sel=(); for ((i=0;i<n;i++)); do sel[$i]=0; done

install_selected() {
  mkdir -p "$DEST"
  local count=0 i target
  for i in "${!names[@]}"; do
    [ "${sel[$i]}" = "1" ] || continue
    target="$DEST/$(basename "${paths[$i]}")"
    rm -rf "$target"
    cp -R "${paths[$i]}" "$target"
    echo "  ${c_grn}installed${c_reset} ${names[$i]}  ->  $target"
    count=$((count+1))
  done
  if [ "$count" -eq 0 ]; then
    echo "Nothing selected. No changes made."
  else
    echo "$count skill(s) installed to $DEST"
    echo "Claude Code picks up new skills automatically in the current session. If one does not appear, restart Claude Code."
  fi
}

if [ "$MODE" = "all" ]; then
  for ((i=0;i<n;i++)); do sel[$i]=1; done
  install_selected
  exit 0
fi

if [ "$MODE" = "skills" ]; then
  any=0
  for want in "${WANT[@]}"; do
    found=0
    for i in "${!names[@]}"; do
      if [ "${names[$i]}" = "$want" ] || [ "$(basename "${paths[$i]}")" = "$want" ]; then
        sel[$i]=1; found=1; any=1
      fi
    done
    [ "$found" = "1" ] || echo "No skill named '$want' in $REPO" >&2
  done
  [ "$any" = "1" ] || { echo "None of the requested skills matched; nothing installed." >&2; exit 1; }
  install_selected
  exit 0
fi

# --- Interactive checklist (reads /dev/tty so it works under curl | bash) ----
if [ ! -e /dev/tty ] || [ ! -r /dev/tty ]; then
  echo "No interactive terminal. Re-run with: curl ... | bash -s -- --all" >&2
  exit 1
fi

cursor=0
draw() {
  printf '\033[H\033[J'
  printf '%sSkills in %s%s\n' "$c_bold" "$REPO" "$c_reset"
  printf '%s  up/down move   space toggle   a all   n none   enter install   q quit%s\n\n' "$c_dim" "$c_reset"
  local i box
  for i in "${!names[@]}"; do
    if [ "${sel[$i]}" = "1" ]; then box="[${c_grn}x${c_reset}]"; else box="[ ]"; fi
    if [ "$i" = "$cursor" ]; then
      printf '%s > %s %s %s\n' "$c_rev" "$box" "${names[$i]}" "$c_reset"
    else
      printf '   %s %s\n' "$box" "${names[$i]}"
    fi
  done
  printf '\n%s%s%s\n' "$c_dim" "${descs[$cursor]:0:96}" "$c_reset"
}

read_key() {
  local k rest
  IFS= read -rsn1 k </dev/tty || true
  if [ "$k" = $'\033' ]; then
    IFS= read -rsn2 -t 0.05 rest </dev/tty || true
    k+="$rest"
  fi
  printf '%s' "$k"
}

printf '\033[?25l'; HID_CURSOR=1  # hide cursor
while true; do
  draw
  key="$(read_key)"
  case "$key" in
    $'\033[A'|k) cursor=$(( (cursor - 1 + n) % n )) ;;
    $'\033[B'|j) cursor=$(( (cursor + 1) % n )) ;;
    ' ')         sel[$cursor]=$(( 1 - sel[$cursor] )) ;;
    a)           for ((i=0;i<n;i++)); do sel[$i]=1; done ;;
    n)           for ((i=0;i<n;i++)); do sel[$i]=0; done ;;
    q|$'\033')   printf '\033[?25h'; echo; echo "Cancelled."; exit 0 ;;
    '')          break ;;   # Enter
  esac
done
printf '\033[?25h'
echo
install_selected
