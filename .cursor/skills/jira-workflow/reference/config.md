# `.jira-workflow.json`

One file per repo, committed, with no secrets. It tells the agent and the automation which Jira
project the repo belongs to and which metadata new tickets get. `jira.py init --project KEY
--write` drafts it from the real Jira project. Then edit the team-specific parts.

```json
{
  "project": "ENG",
  "issueTypes": {
    "feature": "Story", "fix": "Bug", "chore": "Task",
    "refactor": "Task", "analysis": "Spike", "docs": "Task"
  },
  "components": ["api", "billing", "web"],
  "defaultComponents": ["api"],
  "labels": ["team-payments"],
  "suggestLabels": ["tech-debt", "security", "performance", "customer-reported"],
  "epic": "ENG-400",
  "epicField": "parent",
  "sprint": "active",
  "board": 12,
  "fixVersions": ["2026.10"],
  "priorities": ["Highest", "High", "Medium", "Low"],
  "fields": { "customfield_10001": { "value": "Payments" } },
  "askFor": ["component", "epic", "priority", "sprint"],
  "branchPattern": "{prefix}/{key}-{slug}",
  "transitions": { "start": "In Progress", "prOpen": "In Review", "merged": "Done" },
  "updates": {
    "prEvents": true,
    "prStatusBlock": true,
    "dailyDigest": true,
    "pushComments": false,
    "requireKey": false
  }
}
```

| Setting | Meaning |
|---|---|
| `project` | Jira project key for tickets from this repo. |
| `issueTypes` | Kind of work → issue type. If the project has no Spike type, `analysis` maps to Task and the `spike` label is added. |
| `components` | The components that make sense for this repo; the agent picks from these, guided by the paths being changed. |
| `defaultComponents` | Applied when nobody chooses. |
| `labels` | Always added (team label, repo label...). |
| `suggestLabels` | Offered when relevant; never added silently. |
| `epic` | Default epic for new tickets (current quarter's initiative, say). `null` = ask or none. |
| `epicField` | `parent` (Jira Cloud and newer DC) or the Epic Link custom field id (older DC). `init` detects it. |
| `sprint` | `"active"` puts new tickets in the board's current sprint; `null` leaves them in the backlog. |
| `board` | Board id used to find the active sprint (`init` finds it). |
| `fixVersions`, `priorities` | Values to offer when those fields are in `askFor`. |
| `fields` | Extra fields sent on every create, e.g. a Team or Squad custom field. `null` values are skipped. Find ids with `jira.py meta --type Story --all`. |
| `askFor` | What the agent asks about when creating: any of `component`, `epic`, `priority`, `sprint`, `fixVersion`, `labels`. Everything else uses the defaults. |
| `branchPattern` | `{prefix}` (feature/fix/chore/refactor/spike/docs), `{key}`, `{slug}`. |
| `transitions.start` | Status when work starts (the agent's `--start`). |
| `transitions.prOpen` | Status when a non-draft PR opens (Action). Remove to disable. |
| `transitions.merged` | Status when the PR merges (Action). Remove to disable, e.g. if QA moves tickets. |
| `updates.prEvents` | Action comments on the ticket for PR opened, ready, approved, changes requested, merged and closed. |
| `updates.prStatusBlock` | Action keeps a "**Jira:** ENG-123 · Story · **In Review** · ..." line at the top of the PR description. |
| `updates.dailyDigest` | Weekday "Daily status" comment per ticket with activity (commits + PR state). |
| `updates.pushComments` | A comment on every push from the git hook. Off by default because the daily status covers it. |
| `updates.requireKey` | The PR check fails when an open PR has no Jira key in its branch or title. |

Local, uncommitted overrides (credentials, a different `JIRA_PROJECT` for experiments) go in
`<repo>/.jira/env`, which is gitignored.
