---
name: jira-workflow
description: Ticket-first engineering workflow for teams using Jira. Use whenever the user starts or continues a feature, fix, chore, refactor, analysis or spike in a repo; mentions a Jira ticket or key (e.g. ENG-123); commits, pushes or opens a PR; or asks to create, update or move a Jira issue. First asks whether a ticket exists or should be created, fills ticket metadata from the repo's .jira-workflow.json, then keeps the ticket current with milestone comments so leadership can read status in Jira without asking.
---

# Jira workflow (ticket first)

Goal: every piece of real work in a repo is tied to a Jira ticket, and that ticket always shows
where things stand, so leads can check status in Jira instead of asking people. Updates come from
two places:

- **Automation** (already in the repo, no agent needed): commit keys, PR events, reviews, merges,
  a Jira status line on each PR, and a **daily status comment** per active ticket. These cover
  *what* happened.
- **You**: asking about the ticket up front, creating it with the right metadata, and short
  **milestone comments** that explain *why*: the plan, decisions, blockers, scope changes and
  hand-offs. Automation can't write those.

## 0. Orient (once per session, silently)

Pick the tool, in this order:
1. **Atlassian MCP** tools, if connected (names contain `atlassian`/`jira`). Use them for reads
   and writes. They act as the user.
2. **CLI**: `python3 .github/jira/jira.py` (committed in onboarded repos), otherwise
   `python3 ~/.local/share/jira-workflow/jira.py`. Below, `J` means whichever one exists.
3. **Neither works** (no credentials, no network): still do the ticket-first conversation, draft
   the ticket and comments as text for the user to paste, and suggest `J setup`.

Run `J status` (offline). It shows the project, the active ticket, the repo config, which
metadata to ask for (`ask for:`) and which automation is on. If a
`[jira-workflow]` context line came from a hook, it says the same thing.

If `repo config: none`, offer once: *"This repo has no Jira config. Set one up now? It takes a
minute and saves questions later."* If yes, ask for the project key, then run
`J init --project KEY --write`. This drafts `.jira-workflow.json` from the real Jira project
(components, issue types, board, epic field). Show the user the choices (default components,
epic, labels, team field) and edit the file with their answers. See `reference/config.md`.

## 1. Ticket first: ask before starting work

**When:** the user asks for a feature, fix, chore, refactor, docs change, analysis or spike, in a
repo. **Not** for pure questions, explanations or reviews that change nothing.

**If there is already an active ticket** (key in the branch, or one set with `J current --set`):
say it in one line ("Tracking this under **ENG-123**: Retry 429s, *In Progress*.") and carry on.
Ask only if the new request clearly doesn't belong to that ticket.

**Otherwise, ask one question before writing code.** Prepare the answer options first:
- `J mine` gives the user's open tickets in this project.
- `J find "<2–4 words from the request>"` gives open tickets that might already cover it.
- Decide whether the work is ticket-worthy (see below) and which option you recommend.

Then ask, using the client's choice UI when it has one:

> Is there a Jira ticket for this?
> - **ENG-481**: Client retries on 429 (To Do): *looks like this work*
> - **ENG-455**: API client hardening (In Progress, yours)
> - Create a new ticket *(recommended: new user-visible behaviour, ~1–2 days)*
> - No ticket, it's trivial
> - *(Other: type a key)*

**Ticket-worthy** (recommend creating): more than ~2 hours of work or more than one session;
behaviour users or other teams will notice; changes to an API, schema, config or infra; a bug
that reached users; analysis whose answer someone will ask about; anything needing review, QA or
release notes. **Trivial** (recommend no ticket): typos, formatting, a one-line fix, a throwaway
experiment. If the team's `updates.requireKey` is true, PRs need a key, so never recommend
"no ticket" for work that will become a PR.

After the answer:
- **Existing ticket:** `J current --set KEY`. Read it with `J get KEY`. If it's not assigned or
  not started, offer to assign it to the user and move it to In Progress. Suggest a branch with
  `J branch-name KEY --kind <kind>`.
- **Create:** go to step 2.
- **No ticket:** go ahead, and don't ask again about the same work this session. If it grows past
  trivial, ask once more.

## 2. Create with the repo's metadata

`.jira-workflow.json` sets the defaults: project, how kinds of work map to issue types (feature →
Story, fix → Bug, chore → Task, analysis → Spike...), components, default epic, labels, sprint,
team/custom fields, and the list of fields to ask about (`askFor`).

1. **Draft it yourself first**, from the request and the code:
   - *Kind* → issue type through `issueTypes`.
   - *Summary*: imperative, specific, ≤ 80 chars ("Retry 429 responses with backoff in API
     client").
   - *Description*: the template for that type from `reference/templates.md`, filled with what you
     actually know. Leave out sections you can't fill.
   - *Component*: infer it from the paths you expect to touch, matched against `components`.
   - *Epic*: the config's `epic`, or the most relevant from `J epics`.
2. **Ask only what `askFor` lists**, in one batch (at most 4 questions), each with your
   recommendation first. For example: Component (api ✓ / web / billing), Epic (ENG-400 Reliability
   Q3 ✓ / other / none), Priority (Medium ✓ / High / Low), Sprint (current ✓ / backlog). Don't ask
   about anything the config already fixes.
3. **Show the draft in 3–4 lines, then create it:**
   ```bash
   J create --kind feature --summary "..." --component api --epic ENG-400 --priority Medium \
     --assign-me --start --set-current --description-file - <<'EOF'
   ## Why
   ...
   EOF
   ```
   Repo defaults (labels, custom fields, sprint) are applied automatically; flags override them.
   The command prints the key, the link and a suggested branch name. With MCP, send the same
   fields.
4. Tell the user the key and link in one line, and offer the branch:
   `git switch -c feature/ENG-123-retry-429s`. Creating the branch is their call.

If creating fails because of a required field, run `J meta --type <Type>`. It shows required
fields and allowed values. Ask the user for the missing one and suggest adding it to the config's
`fields` so nobody gets asked again.

## 3. While working: milestone comments (the "why")

Post when one of these **happens**, not on a timer, not per edit:

| Milestone | Headline example |
|---|---|
| Plan formed (after the first real look at the code) | **Started:** approach + main risk |
| Key finding or decision | **Update:** root cause found / chose X over Y |
| Blocked, or waiting on someone | **Blocked:** what, and who or what unblocks it |
| Scope or estimate changed | **Scope change:** was → now, impact on dates |
| Analysis concluded | **Spike result:** the answer first, then evidence |
| Hand-off / end of session with real progress | **Status:** done, remaining, next |

Write for a lead who isn't in the code: outcome first, plain language, 3–8 lines, bold headline,
bullets, `Next:`, and any risk to the date. Name features and services, not files and line
numbers. Batch small steps into one comment. **Never** include secrets, tokens, env values,
customer data or raw stack traces. Before posting, check the last comments (`J get KEY`) and
don't repeat what's there or what automation already posted. After posting, one line to the user
is enough ("Posted a status update on ENG-123.").

If the user wants less noise, respect it: `quiet` mode (they say so, or `JIRA_WORKFLOW_MODE=quiet`)
means you draft comments and post only when told. `auto` mode means create tickets without asking
when the work is clearly ticket-worthy and there is no duplicate (still report what you did).

## 4. Commits, pushes, PRs (mostly automatic)

- **Commits** start with the key: `ENG-123: Add jittered backoff to retry loop`. The commit hook
  adds it when missing, but write it anyway.
- **Pushes:** nothing to do. The daily status comment summarises the commits. (Per-push comments
  exist only if the repo turned on `updates.pushComments`.)
- **PR:** put the key in the title (`ENG-123: Retry 429s with backoff`) and use the PR body
  template in `reference/templates.md`. If `J status` shows `PR sync: yes`, the Action comments on
  the ticket, links the PR, moves the status, records approvals and merges, and keeps a Jira status
  line at the top of the PR. **Don't duplicate any of that.** If PR sync is off: `J link KEY
  <pr-url>`, post a short "PR opened" comment and offer to move the ticket to In Review.
- **Done:** only when the user says so or the PR merged (the Action handles merges).

## 5. Guardrails

- Ask before: creating more than one ticket at once, editing tickets that belong to other people,
  reassigning away from the user, closing or resolving anything. Never delete issues or comments.
- A Jira failure must never block the coding work. Report it in one line (auth, permission,
  missing field, unknown transition) and carry on.
- Keep what the user said: if they picked "no ticket", don't nag. If they gave a key, use it
  everywhere.

## Reference

- `reference/templates.md`: ticket descriptions (Story, Task, Bug, Spike), milestone comments,
  commit and PR templates
- `reference/config.md`: every `.jira-workflow.json` setting
- `reference/setup.md`: team rollout, developer setup, per-client install, troubleshooting
- CLI help: `J -h`, `J <command> -h`
