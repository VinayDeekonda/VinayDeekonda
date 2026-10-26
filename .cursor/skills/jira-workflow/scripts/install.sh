#!/usr/bin/env bash
# jira-workflow installer. Safe to re-run.
#
#   install.sh --team [REPO_DIR]     once per repo, by whoever onboards it; then commit the result
#   install.sh [REPO_DIR]            each developer: CLI in ~/.local/share + git hooks (no repo changes)
#
# --team adds (all committed, no secrets):
#   .github/jira/jira.py                     CLI used by devs, agents, git hooks and Actions
#   .github/workflows/jira-pr-sync.yml       PR/review events -> Jira; Jira status line -> PR
#   .github/workflows/jira-daily-digest.yml  weekday status comment per active ticket
#   .jira-workflow.json                      repo metadata (drafted from Jira if credentials work)
#   .claude/skills/jira-workflow/            the skill, for Claude Code
#   .claude/settings.json                    hooks that tell Claude the repo's Jira state each session
#   .agents/skills/jira-workflow/            the skill, for agents that read .agents/skills
#   .cursor/rules/jira-workflow.mdc          always-on rule for Cursor
#   AGENTS.md                                Jira section for Codex, Copilot, Windsurf, Gemini CLI...
#   .gitignore                               ignores .jira/ (local credential overrides)
# Options: --project KEY (for the config draft), --no-hooks
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHARE_DIR="${JIRA_WORKFLOW_HOME:-$HOME/.local/share/jira-workflow}"
TEAM=0 HOOKS=1 REPO="" PROJECT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --team) TEAM=1 ;;
    --no-hooks) HOOKS=0 ;;
    --project) PROJECT="$2"; shift ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) REPO="$1" ;;
  esac
  shift
done
say() { printf '  %s\n' "$*"; }

mkdir -p "$SHARE_DIR"
cp "$SKILL_DIR/scripts/jira.py" "$SHARE_DIR/jira.py"; chmod +x "$SHARE_DIR/jira.py"
echo "jira-workflow"
say "CLI           -> $SHARE_DIR/jira.py"

[ -n "$REPO" ] || REPO="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$REPO" ]; then
  [ "$TEAM" = 1 ] && { echo "error: --team needs a git repo" >&2; exit 2; }
  say "Not in a repo: CLI only. Next: python3 $SHARE_DIR/jira.py setup"
  exit 0
fi
REPO="$(cd "$REPO" && git rev-parse --show-toplevel)"
cd "$REPO"
say "Repo          -> $REPO"

upsert_block() { # file srcfile : replace/append the marked jira-workflow section
  python3 - "$1" "$2" <<'PY'
import sys, re, pathlib
f, src = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
b, e = "<!-- jira-workflow:begin -->", "<!-- jira-workflow:end -->"
t = f.read_text() if f.exists() else ""
new = f"{b}\n{src.read_text().strip()}\n{e}"
if b in t:
    t = re.sub(re.escape(b) + ".*?" + re.escape(e), lambda m: new, t, flags=re.S)
else:
    t = (t.rstrip() + "\n\n" if t.strip() else "") + new + "\n"
f.write_text(t)
PY
}

copy_skill() { # dest dir
  rm -rf "$1"; mkdir -p "$1"
  cp "$SKILL_DIR/SKILL.md" "$1/"; cp -r "$SKILL_DIR/reference" "$1/"
}

if [ "$TEAM" = 1 ]; then
  mkdir -p .github/jira .github/workflows .cursor/rules .claude
  cp "$SKILL_DIR/scripts/jira.py" .github/jira/jira.py; chmod +x .github/jira/jira.py
  cp "$SKILL_DIR/templates/jira-pr-sync.yml" .github/workflows/
  cp "$SKILL_DIR/templates/jira-daily-digest.yml" .github/workflows/
  say "GitHub        -> .github/jira/jira.py, workflows jira-pr-sync + jira-daily-digest"
  copy_skill .claude/skills/jira-workflow
  copy_skill .agents/skills/jira-workflow
  say "Skill         -> .claude/skills/ and .agents/skills/"
  python3 - <<'PY'
import json, pathlib
p = pathlib.Path(".claude/settings.json")
s = json.loads(p.read_text()) if p.exists() and p.read_text().strip() else {}
cmd = 'python3 "$CLAUDE_PROJECT_DIR/.github/jira/jira.py" hook-context{} 2>/dev/null || true'
hooks = s.setdefault("hooks", {})
for event, extra in (("SessionStart", ""), ("UserPromptSubmit", " --prompt")):
    entries = hooks.setdefault(event, [])
    if not any("jira.py" in h.get("command", "") and "hook-context" in h.get("command", "")
               for e in entries for h in e.get("hooks", [])):
        entries.append({"hooks": [{"type": "command", "command": cmd.format(extra)}]})
p.write_text(json.dumps(s, indent=2) + "\n")
PY
  say "Claude Code   -> .claude/settings.json (SessionStart + UserPromptSubmit context hooks)"
  cp "$SKILL_DIR/templates/cursor-rule.mdc" .cursor/rules/jira-workflow.mdc
  say "Cursor        -> .cursor/rules/jira-workflow.mdc"
  upsert_block AGENTS.md "$SKILL_DIR/templates/agent-rules.md"
  say "Other agents  -> AGENTS.md (Jira section)"
  touch .gitignore; grep -qxF ".jira/" .gitignore || printf '.jira/\n' >> .gitignore
  if [ ! -f .jira-workflow.json ]; then
    if python3 .github/jira/jira.py init ${PROJECT:+--project "$PROJECT"} --write >/dev/null 2>&1; then
      say "Repo config   -> .jira-workflow.json (drafted from Jira - review components, epic, labels)"
    else
      say "Repo config   -> NOT created (no Jira credentials yet). After 'jira.py setup' run:"
      say "                 python3 .github/jira/jira.py init --project KEY --write"
    fi
  else
    say "Repo config   -> .jira-workflow.json (kept existing)"
  fi
fi

if [ "$HOOKS" = 1 ]; then
  python3 "$SHARE_DIR/jira.py" install-hooks | sed 's/^/  /'
fi

echo
if [ "$TEAM" = 1 ]; then
  echo "Next: review .jira-workflow.json, commit, and add org/repo secrets JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN."
  echo "Each developer then runs once: python3 .github/jira/jira.py setup"
else
  echo "Next (once per machine): python3 $SHARE_DIR/jira.py setup"
fi
