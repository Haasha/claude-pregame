#!/bin/sh
# claude-pregame installer for macOS and Linux.
#   curl -fsSL https://raw.githubusercontent.com/Haasha/claude-pregame/main/install.sh | sh
set -eu

RAW="${PREGAME_RAW:-https://raw.githubusercontent.com/Haasha/claude-pregame/main}"
DIR="${XDG_DATA_HOME:-$HOME/.local/share}/claude-pregame"

say() { printf '%s\n' "$*"; }
die() { printf 'pregame: %s\n' "$*" >&2; exit 1; }

# Python 3.8+ (macOS ships it with the Command Line Tools; most Linux distros include it).
PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1 &&
     "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1; then
    PY="$("$cand" -c 'import sys; print(sys.executable)')"
    break
  fi
done
if [ -z "$PY" ]; then
  case "$(uname -s)" in
    Darwin) die "Python 3 not found. Run: xcode-select --install   (then re-run this installer)" ;;
    *)      die "Python 3.8+ not found. Install python3 with your package manager, then re-run." ;;
  esac
fi

command -v claude >/dev/null 2>&1 || [ -x "$HOME/.local/bin/claude" ] ||
  die "Claude Code not found. Install it first: https://claude.com/claude-code"

mkdir -p "$DIR"
# Use the local copy when run from a clone (./install.sh), otherwise download.
SRC_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)"
if [ -n "$SRC_DIR" ] && [ -f "$SRC_DIR/pregame.py" ] && [ "$SRC_DIR" != "$DIR" ]; then
  cp "$SRC_DIR/pregame.py" "$DIR/pregame.py"
else
  curl -fsSL "$RAW/pregame.py" -o "$DIR/pregame.py" || die "download failed: $RAW/pregame.py"
fi
chmod +x "$DIR/pregame.py"

say "Installing claude-pregame..."
"$PY" "$DIR/pregame.py" install

case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) say ""; say "Note: add ~/.local/bin to your PATH to use the 'pregame' command." ;;
esac
say ""
say "Done. Commands: pregame status | pregame logs | pregame uninstall"
