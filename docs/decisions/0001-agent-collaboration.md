# 0001 – Agent collaboration via GitHub

**Context:** Two humans work on this repo with several AI agents (Claude, ChatGPT/Codex, local models).
The agents share no memory and can't see each other's sessions.

**Decision:** GitHub is the single source of truth. Issues are the task list, and `status:*` labels
plus "State" comments on the issues track where each task stands. Every change goes through a PR
against a protected `main`, and only humans merge. The rules for agents are in `AGENTS.md`.
`CLAUDE.md` just imports that file.

**Consequences:** A task and its state can't live only in someone's chat. If a task isn't in an issue,
it doesn't exist. Agents must claim an issue before starting, write a state comment before stopping,
and stay inside the issue's scope.
