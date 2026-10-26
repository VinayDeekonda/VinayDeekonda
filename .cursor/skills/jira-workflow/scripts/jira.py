#!/usr/bin/env python3
"""jira.py - dependency-free Jira CLI for the jira-workflow skill (Python 3.8+, stdlib only).

Works with Jira Cloud (email + API token) and Jira Server / Data Center (personal access token).

Team setup lives in the repo (committed, no secrets):
  .jira-workflow.json        project, issue-type mapping, components, epic, sprint, labels,
                             custom fields, transitions, which automatic updates are on
  .github/jira/jira.py       this file (used by developers, agents, git hooks and GitHub Actions)

Credentials live outside the repo, as environment variables or KEY=VALUE lines in
  <repo>/.jira/env                (per repo, gitignored)
  ~/.config/jira-workflow/env     (per user; `jira.py setup` writes it)
Real environment variables win, then the repo file, then the user file.

  JIRA_BASE_URL      https://yourcompany.atlassian.net   (required)
  JIRA_API_TOKEN     API token (Cloud) or personal access token (Data Center)   (required)
  JIRA_EMAIL         Atlassian login email (Cloud only; leave unset for a DC PAT)
  JIRA_PROJECT       fallback project key when the repo has no .jira-workflow.json
  JIRA_KEY_PREFIXES  only treat these project keys as tickets, e.g. ENG,OPS (optional)
  JIRA_DRY_RUN=1     print write requests instead of sending them
  JIRA_HTTP_TIMEOUT  seconds per request (default 20)

Run `jira.py -h` or `jira.py <command> -h` for usage.
"""
import argparse
import base64
import getpass
import json
import os
import re
import stat
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = "2.0.0"
KEY_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9_]{1,9}-\d+)(?![A-Za-z0-9])")
# Look like keys but aren't (UTF-8, SHA-256, ISO-8601, CVE-2024 ...).
NOT_KEYS = {"UTF", "SHA", "ISO", "RFC", "HTTP", "TLS", "SSL", "CVE", "MD", "AES", "RSA", "UUID",
            "PEP", "BASE", "WCAG", "IPV", "GPT", "ES", "ECMA", "COVID", "H", "X", "IE"}
ZERO_SHA = "0" * 40
CONFIG_FILE = ".jira-workflow.json"
REPO_CLI = ".github/jira/jira.py"
BLOCK_BEGIN, BLOCK_END = "<!-- jira-workflow:begin -->", "<!-- jira-workflow:end -->"
DEFAULT_TYPES = {"feature": "Story", "fix": "Bug", "bug": "Bug", "chore": "Task", "refactor": "Task",
                 "analysis": "Spike", "spike": "Spike", "docs": "Task", "test": "Task"}
BRANCH_PREFIX = {"feature": "feature", "fix": "fix", "bug": "fix", "chore": "chore", "refactor": "refactor",
                 "analysis": "spike", "spike": "spike", "docs": "docs", "test": "test"}


# --------------------------------------------------------------------------- helpers

def die(msg, code=1):
    print(f"jira: {msg}", file=sys.stderr)
    sys.exit(code)


def warn(msg):
    print(f"jira: warning: {msg}", file=sys.stderr)


def git(*args):
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=30)
    except Exception:
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def repo_top():
    return git("rev-parse", "--show-toplevel")


def git_dir():
    d = git("rev-parse", "--git-common-dir")
    return Path(d).resolve() if d else None


def load_env_files():
    files = []
    top = repo_top()
    if top:
        files.append(Path(top) / ".jira" / "env")
    files.append(Path.home() / ".config" / "jira-workflow" / "env")
    for p in files:  # repo file first, so it wins over the user file (setdefault)
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k.startswith("export "):
                k = k[len("export "):].strip()
            os.environ.setdefault(k, v.strip().strip('"').strip("'"))


_CFG = None


def repo_config():
    global _CFG
    if _CFG is None:
        _CFG = {}
        p = Path(repo_top() or ".") / CONFIG_FILE
        if p.is_file():
            try:
                _CFG = json.loads(p.read_text(encoding="utf-8"))
            except ValueError as e:
                warn(f"{CONFIG_FILE} is not valid JSON ({e}); ignoring it")
    return _CFG


def updates_cfg(name, default):
    v = (repo_config().get("updates") or {}).get(name)
    return default if v is None else v


def project_key(arg=None):
    return arg or repo_config().get("project") or os.environ.get("JIRA_PROJECT") or ""


def find_keys(*texts):
    allowed = {x.strip().upper() for x in os.environ.get("JIRA_KEY_PREFIXES", "").split(",") if x.strip()}
    seen = []
    for t in texts:
        for k in KEY_RE.findall(t or ""):
            prefix = k.split("-")[0]
            ok = (prefix in allowed) if allowed else (prefix not in NOT_KEYS)
            if ok and k not in seen:
                seen.append(k)
    return seen


def current_branch():
    return git("symbolic-ref", "--quiet", "--short", "HEAD")


def current_key_file():
    d = git_dir()
    return d / "jira-current" if d else None


def stored_key():
    f = current_key_file()
    if f and f.is_file():
        return f.read_text().strip()
    return ""


def current_key():
    """Active ticket: key in the branch name wins, else the `current --set` value."""
    ks = find_keys(current_branch())
    return ks[0] if ks else stored_key()


def read_text_arg(value, file_value):
    if file_value:
        return sys.stdin.read() if file_value == "-" else Path(file_value).read_text(encoding="utf-8")
    return value or ""


def slugify(text, n=40):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:n].rstrip("-")


_INLINE = [
    (re.compile(r"\*\*(.+?)\*\*"), r"*\1*"),                          # **bold** -> *bold*
    (re.compile(r"`([^`]+)`"), r"{{\1}}"),                             # `code`   -> {{code}}
    (re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)"), r"[\1|\2]"),   # [t](u)   -> [t|u]
]


def md_to_wiki(text):
    """Convert the small Markdown subset agents write into Jira wiki markup."""
    out, in_code = [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            lang = line.strip()[3:].strip()
            out.append(f"{{code:{lang}}}" if lang and not in_code else "{code}")
            in_code = not in_code
            continue
        if in_code:
            out.append(line)
            continue
        prefix, rest = "", line
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            prefix, rest = f"h{min(len(m.group(1)) + 1, 6)}. ", m.group(2)
        else:
            m = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
            if m:
                prefix, rest = "*" * (len(m.group(1).expandtabs(2)) // 2 + 1) + " ", m.group(2)
            else:
                m = re.match(r"^(\s*)\d+[.)]\s+(.*)$", line)
                if m:
                    prefix, rest = "#" * (len(m.group(1).expandtabs(2)) // 2 + 1) + " ", m.group(2)
        if prefix.startswith(("*", "#")):  # task-list checkboxes
            rest = re.sub(r"^\[ \]\s*", "☐ ", rest)
            rest = re.sub(r"^\[[xX]\]\s*", "(/) ", rest)
        for pat, rep in _INLINE:
            rest = pat.sub(rep, rest)
        out.append(prefix + rest)
    if in_code:
        out.append("{code}")
    return "\n".join(out)


def web_base(remote_url):
    """git@github.com:org/repo.git -> https://github.com/org/repo (GitHub/GitLab/Bitbucket)."""
    u = (remote_url or "").strip()
    m = re.match(r"^git@([^:]+):(.+?)(\.git)?$", u) or \
        re.match(r"^ssh://git@([^/:]+)(?::\d+)?/(.+?)(\.git)?$", u)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    m = re.match(r"^https?://(?:[^@/]+@)?([^/]+)/(.+?)(\.git)?/?$", u)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    return ""


def commit_url(base, sha):
    if not base:
        return ""
    if "bitbucket" in base:
        return f"{base}/commits/{sha}"
    if "gitlab" in base:
        return f"{base}/-/commit/{sha}"
    return f"{base}/commit/{sha}"


def repo_name():
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    base = web_base(git("remote", "get-url", "origin"))
    if base:
        return base.split("/", 3)[-1]
    return Path(repo_top() or ".").resolve().name


def parse_value(v):
    try:
        return json.loads(v)
    except ValueError:
        return v


# --------------------------------------------------------------------------- Jira client

class Jira:
    def __init__(self):
        self.base = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
        self.email = os.environ.get("JIRA_EMAIL", "")
        self.token = os.environ.get("JIRA_API_TOKEN", "")
        self.dry = os.environ.get("JIRA_DRY_RUN") == "1"
        self.timeout = float(os.environ.get("JIRA_HTTP_TIMEOUT", "20"))
        if not self.base or (not self.token and not self.dry):
            die("Jira is not configured. Run `jira.py setup`, or set JIRA_BASE_URL and JIRA_API_TOKEN "
                "(plus JIRA_EMAIL for Jira Cloud).", code=3)
        self._me = None

    def browse(self, key):
        return f"{self.base}/browse/{key}"

    def _auth(self):
        if self.email:
            return "Basic " + base64.b64encode(f"{self.email}:{self.token}".encode()).decode()
        return "Bearer " + self.token

    def req(self, method, path, body=None, params=None, allow=()):
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        if self.dry and method != "GET":
            print(f"[dry-run] {method} {url}", file=sys.stderr)
            if body is not None:
                print(json.dumps(body, indent=2, ensure_ascii=False), file=sys.stderr)
            return {"key": "DRY-1", "id": "0"}
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": self._auth(),
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(r, timeout=self.timeout) as resp:
                txt = resp.read().decode("utf-8")
                return json.loads(txt) if txt.strip() else {}
        except urllib.error.HTTPError as e:
            if e.code in allow:
                return None
            detail = e.read().decode("utf-8", errors="replace")[:800]
            hint = " (check JIRA_EMAIL / JIRA_API_TOKEN)" if e.code in (401, 403) else ""
            die(f"{method} {path} -> HTTP {e.code}{hint}\n{detail}", code=4)
        except urllib.error.URLError as e:
            die(f"could not reach {self.base}: {e.reason}", code=5)

    def me(self):
        if self._me is None:
            self._me = self.req("GET", "/rest/api/2/myself")
        return self._me

    def me_ref(self):
        if self.dry:
            return {"accountId": "<me>"}
        me = self.me()
        return {"accountId": me["accountId"]} if me.get("accountId") else {"name": me.get("name")}

    def issue(self, key, fields="summary,status,issuetype,assignee,parent"):
        return self.req("GET", f"/rest/api/2/issue/{key}", params={"fields": fields}, allow=(404,))

    def search(self, jql, limit=10, fields="summary,status,assignee,issuetype,updated"):
        # Jira Cloud: enhanced search endpoint. Server/DC: classic v2 search.
        res = self.req("GET", "/rest/api/3/search/jql",
                       params={"jql": jql, "maxResults": limit, "fields": fields}, allow=(404, 405, 410))
        if res is None:
            res = self.req("GET", "/rest/api/2/search",
                           params={"jql": jql, "maxResults": limit, "fields": fields})
        return res.get("issues", [])

    def transitions(self, key):
        return self.req("GET", f"/rest/api/2/issue/{key}/transitions").get("transitions", [])

    def transition(self, key, name, strict=True):
        if self.dry:
            print(f"[dry-run] would move {key} to '{name}'", file=sys.stderr)
            return True
        issue = self.issue(key, "status")
        if not issue:
            (die if strict else warn)(f"{key} not found")
            return False
        status = issue["fields"]["status"]["name"]
        if status.lower() == name.lower():
            print(f"{key} is already in '{status}'")
            return True
        ts = self.transitions(key)
        want = name.lower()
        match = next((t for t in ts if t["name"].lower() == want), None) or \
            next((t for t in ts if t.get("to", {}).get("name", "").lower() == want), None)
        if not match:
            avail = ", ".join(f"'{t['name']}' -> {t.get('to', {}).get('name', '?')}" for t in ts) or "none"
            msg = f"no transition '{name}' from '{status}' on {key}. Available: {avail}"
            if strict:
                die(msg, code=2)
            warn(msg)
            return False
        self.req("POST", f"/rest/api/2/issue/{key}/transitions", body={"transition": {"id": match["id"]}})
        print(f"{key}: {status} -> {match.get('to', {}).get('name', match['name'])}")
        return True

    def comment(self, key, body, raw=False):
        text = body if raw else md_to_wiki(body)
        res = self.req("POST", f"/rest/api/2/issue/{key}/comment", body={"body": text})
        cid = res.get("id", "")
        focus = f"?focusedCommentId={cid}" if cid and cid != "0" else ""
        print(f"Commented on {key}: {self.browse(key)}{focus}")

    def recent_comments(self, key, n=10):
        path = f"/rest/api/2/issue/{key}/comment"
        head = self.req("GET", path, params={"maxResults": 0}, allow=(400, 404)) or {}
        total = head.get("total", 0)
        res = self.req("GET", path, params={"startAt": max(0, total - n), "maxResults": n}, allow=(400, 404))
        return (res or {}).get("comments", [])

    def link(self, key, url, title):
        self.req("POST", f"/rest/api/2/issue/{key}/remotelink", allow=(400, 403, 404),
                 body={"globalId": url, "object": {"url": url, "title": title}})

    def board_for(self, project):
        res = self.req("GET", "/rest/agile/1.0/board", params={"projectKeyOrId": project},
                       allow=(400, 403, 404)) or {}
        boards = res.get("values", [])
        scrum = [b for b in boards if b.get("type") == "scrum"]
        return (scrum or boards or [{}])[0].get("id")

    def add_to_sprint(self, key, sprint, project):
        if self.dry:
            print(f"[dry-run] would add {key} to sprint '{sprint}'", file=sys.stderr)
            return
        if str(sprint).isdigit():
            sid = int(sprint)
        else:
            board = repo_config().get("board") or self.board_for(project)
            if not board:
                warn(f"no Jira board found for {project}; {key} not added to a sprint")
                return
            res = self.req("GET", f"/rest/agile/1.0/board/{board}/sprint", params={"state": "active"},
                           allow=(400, 403, 404)) or {}
            active = res.get("values", [])
            if not active:
                warn(f"board {board} has no active sprint; {key} stays in the backlog")
                return
            sid = active[0]["id"]
        ok = self.req("POST", f"/rest/agile/1.0/sprint/{sid}/issue", body={"issues": [key]},
                      allow=(400, 403, 404))
        if ok is None:
            warn(f"could not add {key} to sprint {sid}")
        else:
            print(f"{key} added to sprint {sid}")


def fmt_issue(i):
    f = i.get("fields", {})
    who = (f.get("assignee") or {}).get("displayName", "unassigned")
    return (f"{i['key']:<12} [{(f.get('status') or {}).get('name', '?')}] "
            f"{(f.get('issuetype') or {}).get('name', '')}: {f.get('summary', '')}  ({who})")


# --------------------------------------------------------------------------- GitHub client

def gh(method, path, body=None, params=None, allow=()):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return None
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    url = api + path + ("?" + urllib.parse.urlencode(params) if params else "")
    if os.environ.get("JIRA_DRY_RUN") == "1" and method != "GET":
        print(f"[dry-run] GitHub {method} {url}", file=sys.stderr)
        return {}
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "jira-workflow",
    })
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            txt = resp.read().decode("utf-8")
            return json.loads(txt) if txt.strip() else {}
    except urllib.error.HTTPError as e:
        if e.code in allow:
            return None
        warn(f"GitHub {method} {path} -> HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
        return None
    except urllib.error.URLError as e:
        warn(f"could not reach GitHub: {e.reason}")
        return None


def pr_review_summary(repo, number):
    reviews = gh("GET", f"/repos/{repo}/pulls/{number}/reviews", params={"per_page": 100}) or []
    latest = {}
    for r in reviews:
        if r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[(r.get("user") or {}).get("login", "?")] = r["state"]
    approvals = sum(1 for s in latest.values() if s == "APPROVED")
    changes = [u for u, s in latest.items() if s == "CHANGES_REQUESTED"]
    return approvals, changes


def pr_state_text(pr, repo):
    if pr.get("merged_at"):
        return f"merged into {{{{{pr['base']['ref']}}}}}"
    if pr.get("state") == "closed":
        return "closed without merging"
    if pr.get("draft"):
        return "draft"
    approvals, changes = pr_review_summary(repo, pr["number"])
    parts = [f"open, {approvals} approval{'s' if approvals != 1 else ''}" if approvals else "open, awaiting review"]
    if changes:
        parts.append("changes requested by " + ", ".join(changes))
    return "; ".join(parts)


# --------------------------------------------------------------------------- git hooks (embedded)

HOOK_COMMIT_MSG = r'''#!/bin/sh
# jira-workflow: prefix commit messages with the active Jira key (branch name, or
# `jira.py current --set KEY`). Never blocks a commit. Disable once: JIRA_COMMIT_PREFIX=0
HOOK_DIR=$(dirname "$0")
if [ -x "$HOOK_DIR/commit-msg.pre-jira" ]; then
  "$HOOK_DIR/commit-msg.pre-jira" "$@" || exit $?
fi
command -v python3 >/dev/null 2>&1 || exit 0
TOP=$(git rev-parse --show-toplevel 2>/dev/null)
for J in "$TOP/.github/jira/jira.py" "$HOME/.local/share/jira-workflow/jira.py"; do
  if [ -f "$J" ]; then python3 "$J" commit-msg "$1" 2>/dev/null || true; break; fi
done
exit 0
'''

HOOK_PRE_PUSH = r'''#!/bin/sh
# jira-workflow: optional per-push comment on the Jira ticket (only when the repo's
# .jira-workflow.json has "pushComments": true, or JIRA_PUSH_COMMENTS=1). Runs in the
# background; log in .git/jira-hook.log. Never blocks a push. Skip once: JIRA_SKIP_PUSH_HOOK=1
HOOK_DIR=$(dirname "$0")
REFS=$(cat)
if [ -x "$HOOK_DIR/pre-push.pre-jira" ]; then
  printf '%s\n' "$REFS" | "$HOOK_DIR/pre-push.pre-jira" "$@" || exit $?
fi
[ "${JIRA_SKIP_PUSH_HOOK:-0}" = "1" ] && exit 0
command -v python3 >/dev/null 2>&1 || exit 0
[ -n "$REFS" ] || exit 0
TOP=$(git rev-parse --show-toplevel 2>/dev/null)
J=""
for C in "$TOP/.github/jira/jira.py" "$HOME/.local/share/jira-workflow/jira.py"; do
  if [ -f "$C" ]; then J="$C"; break; fi
done
[ -n "$J" ] || exit 0
LOG="$(git rev-parse --git-common-dir)/jira-hook.log"
export JIRA_HTTP_TIMEOUT="${JIRA_HTTP_TIMEOUT:-10}"
if [ "${JIRA_PUSH_SYNC:-0}" = "1" ]; then
  printf '%s\n' "$REFS" | python3 "$J" push-note "$1" "$2" || true
else
  ( sleep 3; printf '%s\n' "$REFS" | python3 "$J" push-note "$1" "$2" ) >>"$LOG" 2>&1 &
fi
exit 0
'''


def hooks_path():
    top = repo_top()
    if not top:
        return None
    p = Path(git("rev-parse", "--git-path", "hooks") or ".git/hooks")
    return p if p.is_absolute() else Path(top) / p


# --------------------------------------------------------------------------- commands: setup

def cmd_setup(a):
    """Interactive: write ~/.config/jira-workflow/env, install git hooks, test the login."""
    conf = Path.home() / ".config" / "jira-workflow" / "env"
    print("jira-workflow setup - credentials are stored in", conf)
    cur = {k: os.environ.get(k, "") for k in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_PROJECT")}
    base = input(f"Jira URL [{cur['JIRA_BASE_URL'] or 'https://yourcompany.atlassian.net'}]: ").strip() \
        or cur["JIRA_BASE_URL"]
    if not base:
        die("a Jira URL is required", code=2)
    cloud = "atlassian.net" in base
    email = input(f"Atlassian email{' (leave empty for Data Center PAT)' if not cloud else ''} "
                  f"[{cur['JIRA_EMAIL']}]: ").strip() or cur["JIRA_EMAIL"]
    print("API token: https://id.atlassian.com/manage-profile/security/api-tokens" if cloud
          else "Personal access token: Jira > Profile > Personal Access Tokens")
    token = getpass.getpass("Token (input hidden): ").strip()
    if not token:
        die("a token is required", code=2)
    project = input(f"Fallback project key [{cur['JIRA_PROJECT']}]: ").strip() or cur["JIRA_PROJECT"]
    conf.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"JIRA_BASE_URL={base.rstrip('/')}", f"JIRA_API_TOKEN={token}"]
    if email:
        lines.append(f"JIRA_EMAIL={email}")
    if project:
        lines.append(f"JIRA_PROJECT={project}")
    conf.write_text("# jira-workflow credentials - keep private\n" + "\n".join(lines) + "\n")
    conf.chmod(stat.S_IRUSR | stat.S_IWUSR)
    os.environ.update({"JIRA_BASE_URL": base.rstrip("/"), "JIRA_API_TOKEN": token, "JIRA_EMAIL": email})
    if repo_top() and not a.no_hooks:
        cmd_install_hooks(a)
    cmd_whoami(a)


def cmd_install_hooks(a):
    hooks = hooks_path()
    if not hooks:
        die("not inside a git repository", code=2)
    hooks.mkdir(parents=True, exist_ok=True)
    for name, body in (("commit-msg", HOOK_COMMIT_MSG), ("pre-push", HOOK_PRE_PUSH)):
        dst = hooks / name
        if dst.is_file() and "jira-workflow" not in dst.read_text(errors="ignore"):
            dst.rename(hooks / f"{name}.pre-jira")
            print(f"Kept your existing {name} hook as {name}.pre-jira (it still runs first)")
        dst.write_text(body)
        dst.chmod(0o755)
    print(f"Installed git hooks in {hooks}: commit-msg, pre-push")
    if git("config", "--get", "core.hooksPath"):
        warn("core.hooksPath is set (husky/lefthook?). If that folder is managed by a tool, call "
             f"`python3 {REPO_CLI} commit-msg \"$1\"` from its commit-msg step instead.")


def cmd_init(a):
    """Draft .jira-workflow.json from the Jira project's real components, types, board and fields."""
    j = Jira()
    project = project_key(a.project)
    if not project:
        die("pass --project KEY", code=2)
    p = j.req("GET", f"/rest/api/2/project/{project}", allow=(404,))
    if not p:
        die(f"project {project} not found or not visible to you", code=2)
    types = [t["name"] for t in p.get("issueTypes", []) if not t.get("subtask")]
    comps = sorted(c["name"] for c in p.get("components", []))
    versions = [v["name"] for v in p.get("versions", []) if not v.get("released") and not v.get("archived")]
    fields = j.req("GET", "/rest/api/2/field", allow=(403, 404)) or []
    epic_link = next((f["id"] for f in fields if f.get("name") == "Epic Link"), None)
    team_field = next((f for f in fields if f.get("name") in ("Team", "Squad") and f.get("custom")), None)
    board = j.board_for(project)

    def pick(*names):
        low = {t.lower(): t for t in types}
        return next((low[n.lower()] for n in names if n.lower() in low), types[0] if types else "Task")

    cfg = {
        "project": project,
        "issueTypes": {
            "feature": pick("Story", "Feature", "Task"), "fix": pick("Bug", "Defect", "Task"),
            "chore": pick("Task", "Chore"), "refactor": pick("Task", "Tech Debt"),
            "analysis": pick("Spike", "Research", "Task"), "docs": pick("Task"),
        },
        "components": comps,
        "defaultComponents": [],
        "labels": [],
        "suggestLabels": ["tech-debt", "security", "performance", "customer-reported"],
        "epic": None,
        "epicField": epic_link or "parent",
        "sprint": "active" if board else None,
        "board": board,
        "fixVersions": versions[:10],
        "priorities": ["Highest", "High", "Medium", "Low"],
        "fields": {},
        "askFor": ["component", "epic", "priority"] + (["sprint"] if board else []),
        "branchPattern": "{prefix}/{key}-{slug}",
        "transitions": {"start": "In Progress", "prOpen": "In Review", "merged": "Done"},
        "updates": {"prEvents": True, "prStatusBlock": True, "dailyDigest": True,
                    "pushComments": False, "requireKey": False},
    }
    if team_field:
        cfg["fields"][team_field["id"]] = None
        cfg["_note"] = (f"Set fields.{team_field['id']} ({team_field['name']}) to your team, "
                        "e.g. {\"value\": \"Payments\"}, or remove it.")
    out = json.dumps(cfg, indent=2)
    if a.write:
        top = repo_top()
        if not top:
            die("not inside a git repository", code=2)
        dst = Path(top) / CONFIG_FILE
        if dst.exists() and not a.force:
            die(f"{dst} exists; pass --force to overwrite", code=2)
        dst.write_text(out + "\n")
        print(f"Wrote {dst}")
    print(out)


def cmd_meta(a):
    """Show fields for creating an issue: required ones, components, versions, allowed values."""
    j = Jira()
    project = project_key(a.project)
    if not project:
        die("pass --project KEY", code=2)
    res = j.req("GET", f"/rest/api/2/issue/createmeta/{project}/issuetypes", allow=(404,))
    types = (res or {}).get("values") or (res or {}).get("issueTypes") or []
    if not types:
        die(f"no create metadata for {project} (check the key and your permissions)", code=2)
    print(f"Project {project} issue types: " + ", ".join(t["name"] for t in types))
    want = (a.type or "").lower()
    t = next((t for t in types if t["name"].lower() == want), None) if want else None
    if not t:
        if want:
            die(f"issue type '{a.type}' not in {project}", code=2)
        return
    fm = j.req("GET", f"/rest/api/2/issue/createmeta/{project}/issuetypes/{t['id']}", params={"maxResults": 200})
    flds = (fm or {}).get("values") or (fm or {}).get("fields") or []
    if isinstance(flds, dict):
        flds = [dict(v, fieldId=k) for k, v in flds.items()]
    interesting = {"components", "priority", "fixVersions", "labels", "parent", "assignee"}
    print(f"\nFields for {t['name']} (* = required, no default):")
    for f in flds:
        fid = f.get("fieldId") or f.get("key")
        req = f.get("required") and not f.get("hasDefaultValue")
        if not (a.all or req or fid in interesting or f.get("name") in ("Sprint", "Team", "Epic Link", "Story Points")):
            continue
        allowed = [x.get("name") or x.get("value") or x.get("key") for x in f.get("allowedValues", []) or []]
        more = f" (+{len(allowed) - 15} more)" if len(allowed) > 15 else ""
        vals = f"  [{', '.join(str(x) for x in allowed[:15])}{more}]" if allowed else ""
        print(f"  {'*' if req else ' '} {fid:<20} {f.get('name', '')}{vals}")


# --------------------------------------------------------------------------- commands: everyday

def cmd_status(a):
    """Offline summary the agent reads at the start of work."""
    top = repo_top()
    cfg = repo_config()
    hooks = hooks_path()

    def has_hook(name):
        f = hooks / name if hooks else None
        return bool(f and f.is_file() and "jira-workflow" in f.read_text(errors="ignore"))

    wf = Path(top or ".") / ".github" / "workflows"
    rows = [
        ("jira", os.environ.get("JIRA_BASE_URL") or "NOT CONFIGURED - run `jira.py setup`"),
        ("auth", "configured" if os.environ.get("JIRA_API_TOKEN") else "missing token"),
        ("repo", top or "(not a git repo)"),
        ("repo config", CONFIG_FILE if cfg else f"none - offer `jira.py init --project KEY --write`"),
        ("project", project_key() or "(unknown - ask the user)"),
        ("mode", os.environ.get("JIRA_WORKFLOW_MODE", "ask")),
        ("branch", current_branch() or "-"),
        ("ticket", current_key() or "(none - ask the user before starting work)"),
        ("commit hook", "yes" if has_hook("commit-msg") else "no"),
        ("push comments", "yes" if has_hook("pre-push") and push_comments_enabled() else "no"),
        ("PR sync", "yes" if (wf / "jira-pr-sync.yml").is_file() else "no"),
        ("daily digest", "yes" if (wf / "jira-daily-digest.yml").is_file() and updates_cfg("dailyDigest", True) else "no"),
    ]
    if cfg.get("askFor"):
        rows.append(("ask for", ", ".join(cfg["askFor"])))
    for k, v in rows:
        print(f"{k + ':':<15}{v}")


def cmd_whoami(a):
    j = Jira()
    me = j.me()
    print(f"{me.get('displayName')}  <{me.get('emailAddress', '')}>  on {j.base}")


def cmd_get(a):
    j = Jira()
    fields = "summary,status,assignee,issuetype,priority,parent,labels,components,description,comment"
    i = j.req("GET", f"/rest/api/2/issue/{a.key}", params={"fields": fields})
    if a.json:
        print(json.dumps(i, indent=2))
        return
    f = i["fields"]
    print(fmt_issue(i))
    print(j.browse(a.key))
    if f.get("parent"):
        print(f"Parent: {f['parent']['key']} {f['parent'].get('fields', {}).get('summary', '')}")
    if f.get("components"):
        print("Components: " + ", ".join(c.get("name", "") for c in f["components"]))
    if f.get("labels"):
        print("Labels: " + ", ".join(f["labels"]))
    desc = f.get("description") or ""
    desc = desc.strip() if isinstance(desc, str) else "(rich content)"
    if desc:
        print("\nDescription:\n" + desc[:1500] + ("..." if len(desc) > 1500 else ""))
    comments = (f.get("comment") or {}).get("comments", [])
    for c in (comments[-a.comments:] if a.comments else []):
        body = c.get("body", "")
        body = body if isinstance(body, str) else "(rich content)"
        who = c.get("author", {}).get("displayName", "?")
        print(f"\n--- {who} @ {c.get('created', '')[:16]}\n{body[:800]}")


def cmd_search(a):
    issues = Jira().search(a.jql, a.limit)
    if not issues:
        print("No matching issues.")
    for i in issues:
        print(fmt_issue(i))


def cmd_find(a):
    words = re.sub(r'[\\"]', " ", a.text).strip()
    clauses = [f'text ~ "{words}"'] if words else []
    project = project_key(a.project)
    if project:
        clauses.append(f"project = {project}")
    if a.mine:
        clauses.append("assignee = currentUser()")
    if not a.all:
        clauses.append("statusCategory != Done")
    a.jql = " AND ".join(clauses) + " ORDER BY updated DESC"
    cmd_search(a)


def cmd_mine(a):
    project = project_key(a.project)
    jql = "assignee = currentUser() AND statusCategory != Done"
    if project:
        jql += f" AND project = {project}"
    a.jql = jql + " ORDER BY updated DESC"
    cmd_search(a)


def cmd_epics(a):
    project = project_key(a.project)
    if not project:
        die("pass --project KEY", code=2)
    a.jql = f"project = {project} AND issuetype = Epic AND statusCategory != Done ORDER BY updated DESC"
    cmd_search(a)


def cmd_create(a):
    cfg = repo_config()
    j = Jira()
    project = project_key(a.project)
    if not project:
        die("no project: pass --project, add .jira-workflow.json, or set JIRA_PROJECT", code=2)
    kind = (a.kind or "").lower()
    itype = a.type or (cfg.get("issueTypes") or {}).get(kind) or DEFAULT_TYPES.get(kind, "Task")
    fields = {"project": {"key": project}, "issuetype": {"name": itype}, "summary": a.summary.strip()[:250]}
    desc = read_text_arg(a.description, a.description_file)
    if desc:
        fields["description"] = md_to_wiki(desc)
    labels = list(cfg.get("labels") or [])
    labels += [x.strip().replace(" ", "-") for x in (a.labels or "").split(",") if x.strip()]
    if kind in ("analysis", "spike") and itype.lower() != "spike":
        labels.append("spike")
    if labels:
        fields["labels"] = sorted(set(labels), key=labels.index)
    comps = a.component if a.component else (cfg.get("defaultComponents") or [])
    if comps:
        fields["components"] = [{"name": c} for c in comps]
    epic = a.epic if a.epic is not None else cfg.get("epic")
    if a.parent:
        fields["parent"] = {"key": a.parent}
    elif epic and str(epic).lower() != "none":
        ef = cfg.get("epicField") or "parent"
        fields[ef] = {"key": epic} if ef == "parent" else epic
    if a.fix_version:
        fields["fixVersions"] = [{"name": v} for v in a.fix_version]
    if a.priority:
        fields["priority"] = {"name": a.priority}
    if a.assign_me:
        fields["assignee"] = j.me_ref()
    extra = {k: v for k, v in (cfg.get("fields") or {}).items() if v is not None}
    for f in a.field or []:
        if "=" not in f:
            die(f"--field expects id=value, got '{f}'", code=2)
        k, v = f.split("=", 1)
        extra[k.strip()] = parse_value(v)
    fields.update(extra)
    res = j.req("POST", "/rest/api/2/issue", body={"fields": fields})
    key = res["key"]
    print(f"Created {key}: {j.browse(key)}")
    sprint = a.sprint if a.sprint is not None else cfg.get("sprint")
    if sprint and str(sprint).lower() != "none":
        j.add_to_sprint(key, sprint, project)
    target = a.transition or (((cfg.get("transitions") or {}).get("start") or "In Progress") if a.start else None)
    if target:
        j.transition(key, target, strict=False)
    if a.set_current:
        f = current_key_file()
        if f:
            f.write_text(key + "\n")
            print(f"Active ticket for this repo: {key}")
    if kind or a.summary:
        prefix = BRANCH_PREFIX.get(kind, "feature")
        pattern = cfg.get("branchPattern") or "{prefix}/{key}-{slug}"
        print("Suggested branch: " + pattern.format(prefix=prefix, key=key, slug=slugify(a.summary)))


def cmd_branch_name(a):
    cfg = repo_config()
    pattern = cfg.get("branchPattern") or "{prefix}/{key}-{slug}"
    summary = a.summary
    if not summary:
        i = Jira().issue(a.key, "summary")
        summary = (i or {}).get("fields", {}).get("summary", "")
    print(pattern.format(prefix=BRANCH_PREFIX.get((a.kind or "").lower(), "feature"),
                         key=a.key, slug=slugify(summary)))


def cmd_comment(a):
    body = read_text_arg(a.body, a.body_file).strip()
    if not body:
        die("empty comment body", code=2)
    Jira().comment(a.key, body, raw=a.raw)


def cmd_transitions(a):
    for t in Jira().transitions(a.key):
        print(f"{t['name']}  ->  {t.get('to', {}).get('name', '?')}")


def cmd_transition(a):
    Jira().transition(a.key, a.name, strict=True)


def cmd_assign(a):
    j = Jira()
    j.req("PUT", f"/rest/api/2/issue/{a.key}/assignee", body=j.me_ref())
    print(f"Assigned {a.key} to you")


def cmd_link(a):
    Jira().link(a.key, a.url, a.title or a.url)
    print(f"Linked {a.url} on {a.key}")


def cmd_keys(a):
    text = " ".join(a.text) if a.text else ("" if sys.stdin.isatty() else sys.stdin.read())
    for k in find_keys(text):
        print(k)


def cmd_current(a):
    f = current_key_file()
    if a.set or a.clear:
        if not f:
            die("not inside a git repository", code=2)
        if a.clear:
            if f.exists():
                f.unlink()
            print("Cleared active ticket")
        else:
            key = a.set.strip()
            if not find_keys(key):
                die(f"'{key}' does not look like a Jira key (e.g. ENG-123)", code=2)
            f.write_text(key + "\n")
            print(f"Active ticket: {key}")
        return
    k = current_key()
    if k:
        print(k)
    else:
        print("No active ticket (no key in branch name, none set).", file=sys.stderr)
        sys.exit(1)


def cmd_hook_context(a):
    """Claude Code SessionStart / UserPromptSubmit hook: tell the agent the Jira state of this repo."""
    if not repo_top():
        return
    key, branch = current_key(), current_branch() or "detached"
    state = current_key_file()
    if a.prompt and state:  # per prompt: only speak when something changed or there is no ticket
        seen = state.with_name("jira-announced")
        now = f"{branch}|{key}"
        if key and seen.is_file() and seen.read_text().strip() == now:
            return
        try:
            seen.write_text(now + "\n")
        except OSError:
            pass
    if key:
        msg = (f"[jira-workflow] Active Jira ticket: {key} (branch {branch}). Use {key} in commit messages "
               f"and PR titles; post milestone updates on it per the jira-workflow skill.")
    else:
        msg = (f"[jira-workflow] No Jira ticket is linked to this work yet (branch {branch}). If this request "
               f"starts or continues a feature, fix, chore or analysis, FIRST ask the user whether a Jira "
               f"ticket exists or should be created (jira-workflow skill). Skip for pure questions.")
    if not repo_config():
        msg += f" This repo has no {CONFIG_FILE}; offer to create it with `jira.py init`."
    print(msg)


# --------------------------------------------------------------------------- commands: automation

def cmd_commit_msg(a):
    """git commit-msg hook: prefix the message with the active ticket key if it has none."""
    if os.environ.get("JIRA_COMMIT_PREFIX", "1") == "0":
        return
    p = Path(a.file)
    msg = p.read_text(encoding="utf-8")
    lines = msg.splitlines(keepends=True)
    idx = next((i for i, ln in enumerate(lines) if ln.strip() and not ln.startswith("#")), None)
    if idx is None:
        return
    first = lines[idx]
    if find_keys(first) or re.match(r"^(Merge|Revert|fixup!|squash!|amend!)", first):
        return
    key = current_key()
    if not key:
        return
    lines[idx] = f"{key}: {first.lstrip()}"
    p.write_text("".join(lines), encoding="utf-8")


def push_comments_enabled():
    if os.environ.get("JIRA_PUSH_COMMENTS") in ("0", "1"):
        return os.environ["JIRA_PUSH_COMMENTS"] == "1"
    if not repo_config():  # no team config: per-push comments are the only automatic update
        return True
    return bool(updates_cfg("pushComments", False))


def cmd_push_note(a):
    """git pre-push hook: one short comment per ticket listing the commits being pushed."""
    if os.environ.get("JIRA_SKIP_PUSH_HOOK") == "1" or not push_comments_enabled():
        return
    remote = a.remote or "origin"
    base = web_base(git("remote", "get-url", remote)) or web_base(a.url)
    notes = {}
    stored = stored_key()
    for line in sys.stdin.read().splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        local_ref, local_sha, _remote_ref, remote_sha = parts
        if local_sha == ZERO_SHA or not local_ref.startswith("refs/heads/"):
            continue  # branch deletion or tag push
        branch = local_ref[len("refs/heads/"):]
        new_branch = remote_sha == ZERO_SHA
        if new_branch or not git("cat-file", "-t", remote_sha):
            rng = [local_sha, "--not", f"--remotes={remote}"]
        else:
            rng = [f"{remote_sha}..{local_sha}"]
        log = git("log", "--no-merges", "--format=%H%x09%s", "-n", "30", *rng)
        commits = [c.split("\t", 1) for c in log.splitlines() if "\t" in c]
        if not commits:
            continue
        branch_keys = find_keys(branch)
        keys = find_keys(branch, *[s for _, s in commits]) or ([stored] if stored else [])
        for key in keys:
            mine = [(h, s) for h, s in commits
                    if key in find_keys(s) or (not find_keys(s) and (key in branch_keys or not branch_keys))]
            if not mine:
                continue
            head = f"Pushed {len(mine)} commit{'s' if len(mine) != 1 else ''} to {{{{{branch}}}}}"
            head += " (new branch)" if new_branch else ""
            rows = []
            for h, s in mine:
                s = re.sub(rf"^{re.escape(key)}[:\s-]*", "", s).strip()
                url = commit_url(base, h)
                rows.append(f"* [{h[:8]}|{url}] {s}" if url else f"* {h[:8]} {s}")
            notes.setdefault(key, []).append(head + ":\n" + "\n".join(rows))
    if not notes:
        return
    j = Jira()
    for key, blocks in notes.items():
        j.comment(key, "\n\n".join(blocks), raw=True)


def jira_block(j, keys):
    rows = []
    for k in keys:
        i = j.issue(k)
        if not i:
            continue
        f = i["fields"]
        parts = [f"[{k}]({j.browse(k)})", (f.get("issuetype") or {}).get("name", ""),
                 f"**{(f.get('status') or {}).get('name', '?')}**", (f.get("summary") or "")[:80]]
        if f.get("assignee"):
            parts.append(f"assignee: {f['assignee'].get('displayName', '')}")
        if f.get("parent"):
            parts.append(f"parent: {f['parent']['key']}")
        rows.append("> **Jira:** " + " · ".join(p for p in parts if p))
    if not rows:
        return ""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"{BLOCK_BEGIN}\n" + "\n>\n".join(rows) + f"\n> <sub>synced {stamp} by jira-workflow</sub>\n{BLOCK_END}"


def update_pr_block(j, repo, pr, keys):
    block = jira_block(j, keys)
    if not block or not repo:
        return
    body = pr.get("body") or ""
    pat = re.compile(re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END), re.S)
    new = pat.sub(lambda m: block, body) if pat.search(body) else (block + "\n\n" + body).rstrip() + "\n"
    if new != body:
        if gh("PATCH", f"/repos/{repo}/pulls/{pr['number']}", body={"body": new}) is not None:
            print(f"Updated Jira status block on PR #{pr['number']}")


def cmd_github_pr(a):
    """GitHub Actions: sync pull_request / pull_request_review events to Jira, and Jira status to the PR."""
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not Path(path).is_file():
        die("GITHUB_EVENT_PATH not set - run this inside a GitHub Actions workflow", code=2)
    ev = json.loads(Path(path).read_text(encoding="utf-8"))
    event = os.environ.get("GITHUB_EVENT_NAME", "pull_request")
    pr, action = ev.get("pull_request") or {}, ev.get("action", "")
    repo = os.environ.get("GITHUB_REPOSITORY") or (ev.get("repository") or {}).get("full_name", "")
    if not pr:
        print("Not a pull request event; nothing to do.")
        return
    keys = find_keys(pr["head"]["ref"], pr.get("title", "")) or find_keys(pr.get("body") or "")
    require = os.environ.get("JIRA_REQUIRE_KEY", "").lower() in ("1", "true") or updates_cfg("requireKey", False)
    if not keys:
        msg = "No Jira key found in the PR branch name, title or description (e.g. ENG-123)."
        if require and pr.get("state") == "open":
            print(f"::error title=Jira key missing::{msg} Add it to the PR title.")
            sys.exit(1)
        print(msg + " Nothing to do.")
        return
    j = Jira()
    tr = repo_config().get("transitions") or {}
    link = f"[#{pr['number']} {pr.get('title', '').strip()}|{pr['html_url']}]"
    stats = (f"{pr.get('commits', '?')} commits, +{pr.get('additions', '?')} / -{pr.get('deletions', '?')} "
             f"across {pr.get('changed_files', '?')} files")
    body, target = None, None
    if event == "pull_request_review":
        review = ev.get("review") or {}
        who = (review.get("user") or {}).get("login", "someone")
        state = (review.get("state") or "").lower()
        if state == "approved":
            body = f"*PR approved* by {who}: {link}"
        elif state == "changes_requested":
            body = f"*Changes requested* by {who} on {link}"
    elif action == "closed" and pr.get("merged"):
        who = (pr.get("merged_by") or {}).get("login", "someone")
        sha = (pr.get("merge_commit_sha") or "")[:8]
        body = f"*PR merged* {link}\n* Merged by {who} into {{{{{pr['base']['ref']}}}}}"
        body += (f" ({sha})" if sha else "") + f"\n* {stats}"
        target = os.environ.get("JIRA_TRANSITION_ON_MERGE") or tr.get("merged")
    elif action == "closed":
        body = f"*PR closed without merging* {link}"
    elif action in ("opened", "reopened", "ready_for_review"):
        label = {"ready_for_review": "PR ready for review", "reopened": "PR reopened"}.get(action, "PR opened")
        if pr.get("draft"):
            label = "Draft PR opened"
        body = (f"*{label}* {link}\n* {{{{{pr['head']['ref']}}}}} -> {{{{{pr['base']['ref']}}}}} "
                f"by {pr['user']['login']}\n* {stats}")
        desc = re.sub(re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END), "", pr.get("body") or "", flags=re.S)
        desc = re.sub(r"<!--.*?-->", "", desc, flags=re.S).strip()
        if desc:
            body += "\n\n" + md_to_wiki(desc[:1200] + ("..." if len(desc) > 1200 else ""))
        if not pr.get("draft"):
            target = os.environ.get("JIRA_TRANSITION_ON_PR_OPEN") or tr.get("prOpen")
    for key in keys:
        if not j.issue(key, "status"):
            warn(f"{key} not found in Jira; skipping")
            continue
        if body and updates_cfg("prEvents", True):
            j.comment(key, body, raw=True)
        if action in ("opened", "reopened", "ready_for_review"):
            j.link(key, pr["html_url"], f"PR #{pr['number']}: {pr.get('title', '')}")
        if target:
            j.transition(key, target, strict=False)
    if updates_cfg("prStatusBlock", True):
        update_pr_block(j, repo, pr, keys)


def cmd_digest(a):
    """Daily status: one comment per ticket with activity - commits (all branches) and PR/review state."""
    if not updates_cfg("dailyDigest", True) and not a.force:
        print("Daily digest is off in .jira-workflow.json (updates.dailyDigest).")
        return
    now = datetime.now(timezone.utc)
    hours = a.hours or (72 if now.weekday() == 0 else 24)  # Monday covers the weekend
    since = now - timedelta(hours=hours)
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    repo = repo_name()
    base = web_base(git("remote", "get-url", "origin")) or (f"https://github.com/{repo}" if "/" in repo else "")
    tickets = {}

    def t(key):
        return tickets.setdefault(key, {"commits": {}, "authors": set(), "branches": set(), "prs": {}})

    refs = [r for r in git("for-each-ref", "--format=%(refname)", "refs/remotes", "refs/heads").splitlines()
            if not r.endswith("/HEAD")]
    default = (git("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD").split("/", 1)[-1]
               or next((b for b in ("main", "master", "develop", "trunk")
                        if f"refs/remotes/origin/{b}" in refs or f"refs/heads/{b}" in refs), ""))
    default_refs = [r for r in (f"refs/remotes/origin/{default}", f"refs/heads/{default}") if default and r in refs]
    for ref in refs:
        short = ref.split("/", 3)[-1] if ref.startswith("refs/remotes/") else ref[len("refs/heads/"):]
        is_default = ref in default_refs
        # Branch-name keys only apply to the branch's own commits, not history shared with the default branch.
        exclude = [] if is_default or not default_refs else ["--not", *default_refs]
        log = git("log", ref, *exclude, "--no-merges", f"--since={since_iso}",
                  "--format=%H%x09%ct%x09%an%x09%s", "-n", "300")
        for seq, line in enumerate(log.splitlines()):
            parts = line.split("\t", 3)
            if len(parts) != 4:
                continue
            h, ct, author, subject = parts
            for key in (find_keys(subject) or ([] if is_default else find_keys(short))):
                d = t(key)
                d["commits"][h] = ((int(ct), -seq), subject)
                d["authors"].add(author)
                d["branches"].add(short)

    gh_repo = os.environ.get("GITHUB_REPOSITORY")
    if os.environ.get("GITHUB_TOKEN") and gh_repo:
        for page in range(1, 4):
            prs = gh("GET", f"/repos/{gh_repo}/pulls",
                     params={"state": "all", "sort": "updated", "direction": "desc", "per_page": 50, "page": page})
            if not prs:
                break
            done = False
            for pr in prs:
                if pr.get("updated_at", "") < since_iso:
                    done = True
                    break
                for key in find_keys(pr["head"]["ref"], pr.get("title", "")):
                    t(key)["prs"][pr["number"]] = (pr, None)
            if done:
                break
        for d in tickets.values():
            for n, (pr, _) in list(d["prs"].items()):
                d["prs"][n] = (pr, pr_state_text(pr, gh_repo))

    if not tickets:
        print(f"No ticket activity in {repo} since {since_iso}.")
        return
    j = Jira()
    date = now.strftime("%Y-%m-%d")
    marker = f"Daily status · {date} · {repo}"
    posted = 0
    for key in sorted(tickets):
        d = tickets[key]
        if not j.issue(key, "status"):
            continue  # not a real ticket (or no access)
        if not a.force and any(marker in (c.get("body") if isinstance(c.get("body"), str) else "")
                               for c in j.recent_comments(key)):
            print(f"{key}: already has today's status; skipped")
            continue
        lines = [f"*{marker}*"]
        commits = sorted(d["commits"].items(), key=lambda kv: kv[1][0])
        if commits:
            n = len(commits)
            branches = ", ".join(f"{{{{{b}}}}}" for b in sorted(d["branches"])[:3])
            lines.append(f"*Code:* {n} commit{'s' if n != 1 else ''} by {', '.join(sorted(d['authors']))} on {branches}")
            for h, (_, s) in commits[-a.max_commits:]:
                s = re.sub(rf"^{re.escape(key)}[:\s-]*", "", s).strip()
                url = commit_url(base, h)
                lines.append(f"* {s} ([{h[:7]}|{url}])" if url else f"* {s} ({h[:7]})")
            if n > a.max_commits:
                lines.append(f"* _...and {n - a.max_commits} earlier_")
        if d["prs"]:
            lines.append("*Pull requests:*")
            for n, (pr, state) in sorted(d["prs"].items()):
                lines.append(f"* [#{n} {pr.get('title', '').strip()}|{pr['html_url']}] - {state or pr.get('state')}")
        j.comment(key, "\n".join(lines), raw=True)
        posted += 1
    print(f"Posted {posted} daily status comment(s) for {repo}.")


# --------------------------------------------------------------------------- main

def build_parser():
    p = argparse.ArgumentParser(prog="jira.py", description="Jira CLI for the jira-workflow skill.")
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        s = sub.add_parser(name, help=help_, description=help_)
        s.set_defaults(fn=fn)
        return s

    s = add("setup", cmd_setup, "interactive: save credentials, install git hooks, test login")
    s.add_argument("--no-hooks", action="store_true")
    add("install-hooks", cmd_install_hooks, "install the commit-msg and pre-push git hooks in this repo")
    s = add("init", cmd_init, f"draft {CONFIG_FILE} from the Jira project (components, types, board)")
    s.add_argument("--project")
    s.add_argument("--write", action="store_true", help=f"write {CONFIG_FILE} at the repo root")
    s.add_argument("--force", action="store_true")
    s = add("meta", cmd_meta, "issue types, required fields and allowed values for creating issues")
    s.add_argument("--project")
    s.add_argument("--type", help="show fields for this issue type")
    s.add_argument("--all", action="store_true", help="show every field, not just the interesting ones")

    add("status", cmd_status, "repo config, active ticket and automation in place (offline)")
    add("whoami", cmd_whoami, "check credentials")
    s = add("hook-context", cmd_hook_context, "(Claude Code hook) print this repo's Jira state for the agent")
    s.add_argument("--prompt", action="store_true", help="per-prompt mode: stay quiet unless something changed")

    s = add("get", cmd_get, "show an issue with its latest comments")
    s.add_argument("key")
    s.add_argument("--comments", type=int, default=3)
    s.add_argument("--json", action="store_true")
    s = add("search", cmd_search, "run a JQL query")
    s.add_argument("jql")
    s.add_argument("--limit", type=int, default=10)
    s = add("find", cmd_find, "find open issues by text in the repo's project (dedupe check)")
    s.add_argument("text")
    s.add_argument("--project")
    s.add_argument("--mine", action="store_true")
    s.add_argument("--all", action="store_true", help="include Done issues")
    s.add_argument("--limit", type=int, default=8)
    s = add("mine", cmd_mine, "my open issues in the repo's project")
    s.add_argument("--project")
    s.add_argument("--limit", type=int, default=10)
    s = add("epics", cmd_epics, "open epics in the repo's project")
    s.add_argument("--project")
    s.add_argument("--limit", type=int, default=15)

    s = add("create", cmd_create, "create an issue using the repo's defaults; prints key and branch name")
    s.add_argument("--summary", required=True)
    s.add_argument("--kind", help="feature, fix, chore, refactor, analysis, docs -> issue type via repo config")
    s.add_argument("--type", help="explicit issue type (overrides --kind)")
    s.add_argument("--project")
    s.add_argument("--description", help="Markdown-lite text")
    s.add_argument("--description-file", help="file path, or - for stdin")
    s.add_argument("--component", action="append", help="repeatable; default: repo defaultComponents")
    s.add_argument("--epic", help="epic key, or 'none'; default: repo epic")
    s.add_argument("--parent", help="parent key (sub-tasks)")
    s.add_argument("--labels", help="comma separated, added to the repo's labels")
    s.add_argument("--priority")
    s.add_argument("--fix-version", action="append")
    s.add_argument("--sprint", help="'active', a sprint id, or 'none'; default: repo sprint")
    s.add_argument("--field", action="append", help="extra field id=value (value may be JSON); repeatable")
    s.add_argument("--assign-me", action="store_true")
    s.add_argument("--start", action="store_true", help="move to the repo's start status (In Progress)")
    s.add_argument("--transition", help="move to this status after creating")
    s.add_argument("--set-current", action="store_true", help="make it this repo's active ticket")
    s = add("branch-name", cmd_branch_name, "suggest a branch name for a ticket")
    s.add_argument("key")
    s.add_argument("--kind")
    s.add_argument("--summary")

    s = add("comment", cmd_comment, "add a comment (Markdown-lite is converted)")
    s.add_argument("key")
    s.add_argument("--body")
    s.add_argument("--body-file", help="file path, or - for stdin")
    s.add_argument("--raw", action="store_true", help="send body as Jira wiki markup unchanged")
    s = add("transitions", cmd_transitions, "list available transitions")
    s.add_argument("key")
    s = add("transition", cmd_transition, "move an issue by transition or status name")
    s.add_argument("key")
    s.add_argument("name")
    s = add("assign-me", cmd_assign, "assign an issue to yourself")
    s.add_argument("key")
    s = add("link", cmd_link, "attach a web link (PR, doc, dashboard) to an issue")
    s.add_argument("key")
    s.add_argument("url")
    s.add_argument("--title")
    s = add("keys", cmd_keys, "print Jira keys found in text or stdin")
    s.add_argument("text", nargs="*")
    s = add("current", cmd_current, "show or set this repo's active ticket")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--set", metavar="KEY")
    g.add_argument("--clear", action="store_true")

    s = add("commit-msg", cmd_commit_msg, "(git hook) prefix commit message with the ticket key")
    s.add_argument("file")
    s = add("push-note", cmd_push_note, "(git hook) comment pushed commits on their tickets")
    s.add_argument("remote", nargs="?")
    s.add_argument("url", nargs="?")
    add("github-pr", cmd_github_pr, "(GitHub Actions) sync a PR or review event to Jira and back")
    s = add("digest", cmd_digest, "(scheduled) post a daily status comment per active ticket")
    s.add_argument("--hours", type=int, help="look-back window (default 24, 72 on Mondays)")
    s.add_argument("--max-commits", type=int, default=6)
    s.add_argument("--force", action="store_true", help="post even if today's status exists / digest is off")
    return p


def main():
    load_env_files()
    a = build_parser().parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
