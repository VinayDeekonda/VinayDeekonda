# Setup

## What goes where

| Piece | Where | Who sets it up |
|---|---|---|
| Skill + agent rules | `.claude/skills/`, `.agents/skills/`, `.cursor/rules/`, `AGENTS.md` | once per repo (committed) |
| Repo metadata | `.jira-workflow.json` | once per repo (committed) |
| CLI | `.github/jira/jira.py` | once per repo (committed) |
| PR sync + daily status | `.github/workflows/jira-pr-sync.yml`, `jira-daily-digest.yml` | once per repo (committed) + org secrets |
| Claude Code context hook | `.claude/settings.json` | once per repo (committed) |
| Credentials | `~/.config/jira-workflow/env` | each developer |
| Git commit hook (adds the key) | `.git/hooks/` | each developer |

## 1. Onboard a repo (once, by a lead or platform engineer)

```bash
cd your-repo
bash /path/to/jira-workflow/scripts/install.sh --team --project ENG
```

- Review `.jira-workflow.json`. If Jira credentials were available it was drafted from the real
  project; otherwise run `python3 .github/jira/jira.py init --project ENG --write` after step 3.
  Set `defaultComponents`, `epic`, `labels`, the team field and `askFor` (see `config.md`).
- Add GitHub secrets `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`. Set them at the
  **organization** level so every onboarded repo gets them. Use a service account (a "Jira bot")
  so automated comments are clearly automated and don't depend on one person's token.
- Commit everything on a branch and open a PR. Re-running the installer later updates the files
  in place.

Optional, but it adds to this: install Atlassian's **GitHub for Jira** app for the org. Tickets
then also show branches, commits, PRs and builds in their Development panel, and Jira dashboards
can filter on them. The workflow here feeds it by putting keys everywhere.

## 2. Each developer (once per machine)

```bash
python3 .github/jira/jira.py setup
```

It asks for the Jira URL, email and API token (Cloud:
https://id.atlassian.com/manage-profile/security/api-tokens; Data Center: a personal access
token, with no email), saves them to `~/.config/jira-workflow/env` (chmod 600), installs the git
hooks for this repo and checks the login. In other onboarded repos, just run
`python3 .github/jira/jira.py install-hooks`.

Recommended for agents: connect **Atlassian's MCP server**, so the agent reads and writes Jira as
the user with OAuth:
- Claude Code: `claude mcp add --transport http atlassian https://mcp.atlassian.com/v2/mcp`,
  then `/mcp` to sign in
- Cursor: "Atlassian" in the Cursor Marketplace, or in `~/.cursor/mcp.json`:
  `{"mcpServers":{"atlassian":{"url":"https://mcp.atlassian.com/v2/mcp"}}}`
- VS Code / Copilot: Extensions → `@mcp Atlassian` → Install
- Claude desktop / web: add the Atlassian connector

Without MCP, agents use the CLI and the credentials above.

## 3. How each client picks it up

| Client | What makes it ticket-first |
|---|---|
| Claude Code | skill in `.claude/skills/jira-workflow/` + `.claude/settings.json` hooks that print the repo's Jira state at session start and whenever there's no active ticket |
| Cursor | `.cursor/rules/jira-workflow.mdc` (always applied) |
| Codex, Copilot, Windsurf, Gemini CLI, others | `AGENTS.md` section + `.agents/skills/jira-workflow/` for clients that load skills |
| Claude web / desktop | upload `jira-workflow.zip` in the Skills section of Settings and add the Atlassian connector; the sandbox can't run repo hooks, so it works through the connector |
| No AI at all | commit hook, PR sync and daily status still keep Jira current |

## What leadership sees

On each ticket:
- The agent's milestone comments: plan, decisions, blockers, scope changes, hand-offs
- **PR events** as they happen: opened, ready for review, approved, changes requested, merged,
  closed. The PR is linked on the ticket and the status moves (In Review, Done) per
  `transitions`.
- A **Daily status** comment on weekdays when there was activity: commits on any branch and the
  state of each PR. Quiet tickets get nothing, so a missing daily status on an In Progress
  ticket is itself a signal.

On each PR: a line at the top, `Jira: ENG-123 · Story · In Review · summary · assignee ·
parent`, refreshed on every PR event.

Useful JQL for a leadership dashboard:
- stalled work: `project = ENG AND statusCategory = "In Progress" AND updated <= -3d`
- shipped this week: `project = ENG AND status changed to Done during (-1w, now())`
- in review: `project = ENG AND status = "In Review" ORDER BY updated DESC`

## Hooks and knobs

| Want | Do |
|---|---|
| No key prefix on one commit | `JIRA_COMMIT_PREFIX=0 git commit ...` |
| Per-push comments too | `"updates": {"pushComments": true}` (or `JIRA_PUSH_COMMENTS=1` for yourself) |
| Block PRs without a key | `"updates": {"requireKey": true}` and make "Jira PR sync" a required check |
| Different digest time | edit the cron line in `jira-daily-digest.yml` (UTC) |
| Run the digest now | Actions → Jira daily status → Run workflow (optional look-back hours) |
| See what would be sent | `JIRA_DRY_RUN=1 python3 .github/jira/jira.py ...` |
| Husky / lefthook | call `python3 .github/jira/jira.py commit-msg "$1"` from your commit-msg step |
| Only treat some prefixes as keys | `JIRA_KEY_PREFIXES=ENG,OPS` |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Jira is not configured` | `python3 .github/jira/jira.py setup` |
| HTTP 401 / 403 | wrong email/token pair; Cloud needs `JIRA_EMAIL`, a DC PAT must not have it |
| HTTP 400 on create | a required field is missing or a value isn't allowed: `jira.py meta --type Story`, then add it to `fields` in the config |
| not added to sprint | no scrum board or no active sprint; set `board` in the config, or `"sprint": null` |
| `no transition 'X'` | the error lists what's available; update `transitions` in the config |
| no daily status | the workflow needs `fetch-depth: 0`; keys must be in branch names or commit messages; check the Actions log |
| PR status line not updating | the workflow needs `pull-requests: write`; forks are skipped |
| commit not prefixed | no key in the branch and no `jira.py current --set KEY`, or a hook manager overrides `.git/hooks` |
