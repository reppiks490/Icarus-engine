# Instructions for every coding agent (Codex, ChatGPT, Claude, others)

Read `ICARUS_STATE.md` first. It is the single source of truth for this repository: goals, verified
results, dead ideas, data access, ownership and the rules no agent may break. Update it when a fact in
it changes, and never contradict it without correcting it.

## Working alongside Claude (required, every session)

Claude (Anthropic) works in this repository too, on `claude/*` branches. You coordinate through
`coordination/`; the full protocol is `coordination/README.md`.

1. Before any work, read `coordination/board/claude.md`, `coordination/board/chatgpt.md`, and every
   message in `coordination/inbox/to-chatgpt/` that has no reply yet (`python -m tools.coordination`).
2. Claim a task in `coordination/board/chatgpt.md` (status `in progress`) before you start it. Do not
   work on any task listed in `coordination/board/claude.md` unless it is `done`; to propose a change,
   write to `coordination/inbox/to-claude/`.
3. Edit only your own board. Never edit or delete a message once it is on `main`.
4. Before you stop: push your work to a `chatgpt/*` or `codex/*` branch, update your board, and answer
   every message that needs a reply. Messages and board updates must reach `main` to be seen.
