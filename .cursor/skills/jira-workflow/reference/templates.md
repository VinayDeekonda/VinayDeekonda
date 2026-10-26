# Templates

Write in Markdown-lite (`**bold**`, `` `code` ``, `- bullets`, `1. lists`, `## headings`,
`[text](url)`, fenced code). `jira.py` converts it to Jira markup; the Atlassian MCP tools accept
Markdown directly. Drop any section you cannot fill with real information.

If the project has no "Spike" issue type, create a **Task** with label `spike`.

---

## Story — user-facing feature

```markdown
## Why
<who needs this and the problem it solves, 1–2 sentences>

## What
- <behaviour 1>
- <behaviour 2>

## Acceptance criteria
- [ ] <observable, testable outcome>
- [ ] <observable, testable outcome>

## Notes
- Out of scope: <...>
- Risks / dependencies: <...>
```

## Task — engineering work, refactor, chore

```markdown
## Goal
<what will be different when this is done>

## Plan
- <step>
- <step>

## Done when
- <check>
```

## Bug

```markdown
## What happens
<actual behaviour, where, since when>

## Expected
<expected behaviour>

## Steps to reproduce
1. <...>
2. <...>

## Impact
<who is affected, how often, workaround if any>

## Suspected cause
<optional — only if you have evidence>
```

## Spike — analysis / investigation

```markdown
## Question
<the one question this spike answers>

## Why now
<decision it unblocks>

## Time-box
<e.g. 1 day>

## Approach
- <what will be looked at / measured>

## Output
<doc, recommendation, prototype, numbers>
```

Conclusion comment for a spike (post when the analysis is done):

```markdown
**Spike result: <one-line answer>**
- Evidence: <key numbers or observations>
- Options considered: <A> vs <B> — chose <A> because <reason>
- Recommendation: <what to do next>
- Follow-ups: <keys or "create tickets for X and Y?">
```

---

## Progress comments

Written for a lead who reads the ticket, not the code: outcome first, plain words, and any
risk to the date. The daily status comment already lists commits and PR state, so these explain
*why* and *what's next*.

Plan formed:
```markdown
**Started: <short approach name>**
- Approach: <1–2 bullets>
- Touches: <modules / services / endpoints>
- Risk: <biggest unknown>
Next: <first concrete step>
```

Finding or decision:
```markdown
**Update: <headline>**
- Found: <what>
- Decided: <what> because <why>
Next: <step>
```

Blocked:
```markdown
**Blocked: <what>**
- Waiting on: <person/team/system>
- Tried: <what was tried>
- Unblocks when: <condition>
```

Scope change:
```markdown
**Scope change**
- Was: <original>
- Now: <new> — because <reason>
- Impact: <estimate / dates / other tickets>
```

Hand-off / end of session:
```markdown
**Status: <in progress | ready for review | paused>**
- Done: <bullets>
- Remaining: <bullets>
Next: <step>
```

---

## Commit message

```
ENG-123: <imperative summary, ≤ 72 chars>

<why this change, what it affects; wrap at ~72 chars>
```

## Pull request

Title: `ENG-123: <imperative summary>`

```markdown
## What
- <change 1>
- <change 2>

## Why
<link to ENG-123 and one-line reason>

## How it was tested
- <tests added/run, manual checks>

## Risk / rollout
<flags, migrations, backwards compatibility — or "low">

Jira: ENG-123
```

PR-opened comment on the ticket (only when the GitHub Action is not installed):
```markdown
**PR opened: [#42 Retry 429s with backoff](https://github.com/org/repo/pull/42)**
- <what it does, 1–2 bullets>
- Tested: <how>
```
