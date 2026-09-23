# Agent Guide

This repo is worked on by two humans and several AI agents (Claude, ChatGPT/Codex, local models).
Agents do not share memory. **GitHub is the only shared state**: issues hold tasks and their current state,
pull requests hold the work. Follow this file exactly; if something here is wrong or missing, say so in
your PR instead of silently working around it.

## Golden rules

1. **Never push to `main`.** All changes go through a pull request. `main` is protected.
2. **One task = one issue = one branch = one PR.** No work without an issue.
3. **Claim before you start**, and never work on an issue someone else has claimed.
4. **Leave a state comment before you stop**, even if the work is unfinished.
5. **Stay in scope.** Unrelated fixes you notice become new issues, not extra commits.
6. **No secrets in the repo.** No API keys, tokens, `.env` files or personal paths. The repo is public.
7. **Humans merge.** Agents may open, update and review PRs, but never merge them.

## Labels

| Label | Meaning |
|---|---|
| `status:ready` | Specified and free to pick up |
| `status:in-progress` | Claimed; someone is working on it |
| `status:blocked` | Waiting on a decision or another issue (say which in a comment) |
| `status:review` | PR is open and ready for review |
| `agent:claude` / `agent:codex` / `agent:local` | Which agent currently holds the task |

An issue has exactly one `status:*` label and at most one `agent:*` label. Closed issues are done.

## Workflow

### 1. Pick a task

```sh
gh issue list --label status:ready
```

Pick one whose dependencies are closed. If nothing is ready, stop and report that; do not invent work.

### 2. Claim it

First re-check the issue. If it already has `status:in-progress`, or a claim comment by someone else, pick another one.

```sh
gh issue edit <N> --remove-label status:ready --add-label status:in-progress --add-label agent:<you>
gh issue comment <N> --body "Claimed by <agent> (<human operator>). Branch: <branch>"
```

### 3. Branch

Name: `<agent>/<issue-number>-<short-slug>`, e.g. `claude/12-login-form`.

```sh
git switch main && git pull
git switch -c claude/12-login-form
```

When several agents run on the same machine, give each its own worktree
(`git worktree add ../Endless-12 -b claude/12-login-form`).

### 4. Work

- Open a **draft PR early** so the work is visible: `gh pr create --draft --fill`.
- The PR body must contain `Closes #<N>`.
- Small, focused commits. Commit messages: imperative mood, first line under 72 chars.
- Add a trailer naming the agent, e.g. `Co-Authored-By: Claude <noreply@anthropic.com>`.
- Keep your branch current with `git pull --rebase origin main`; resolve conflicts yourself.

### 5. Hand off: state comment (required)

Whenever you stop (task done, session ending, blocked, or out of context), post on the **issue**:

```markdown
### State – <agent>, <YYYY-MM-DD>
**Done:** what is finished and pushed
**Next:** the concrete next step
**Blockers / open questions:** or "none"
**Branch / PR:** <branch>, #<PR>
```

This comment is the handoff. The next agent reads the latest one and continues from there.
Everything you learned that matters must be in it or in the PR; your chat history is gone.

If you are blocked, also switch the label to `status:blocked`.
If you abandon the task, set it back to `status:ready`, remove your `agent:*` label, and say why.

### 6. Ready for review

```sh
gh pr ready <PR>
gh issue edit <N> --remove-label status:in-progress --add-label status:review
```

Fill in the PR template completely, including how you verified the change.

### 7. Review

Reviews by a **different** agent or a human are encouraged. Reviewers comment; they don't push to someone
else's branch unless asked. A human merges; merging with `Closes #N` closes the issue.

## Decisions

Lasting decisions (architecture, libraries, conventions) go in `docs/decisions/NNNN-title.md`
(context, decision, consequences; a few lines is fine). Read existing decisions before proposing changes
that contradict them. Never reverse a recorded decision without a new decision file.

## Project specifics

<!-- Fill in once the stack is chosen: build, test, lint and format commands, folder layout, code style. -->
- Stack: not decided yet.
- Build / test / lint commands: none yet.
