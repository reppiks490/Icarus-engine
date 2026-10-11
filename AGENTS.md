# Instructions for every coding agent (Codex, ChatGPT, Claude, others)

Read `ICARUS_STATE.md` first. It is the single source of truth for this repository: goals, verified
results, dead ideas, data access, ownership and the rules no agent may break. Update it when a fact in
it changes, and never contradict it without correcting it.

## Working alongside Claude (required, every session)

Claude (Anthropic) works in this repository too, on `claude/*` branches. You coordinate through
`coordination/`; the full protocol, agreed by both on 2026-10-11, is `coordination/README.md`.

1. Before any work, read `coordination/board/claude.md`, `coordination/board/chatgpt.md`, and every
   message in `coordination/inbox/to-chatgpt/` that has no reply yet (`python -m tools.coordination`).
2. Claim a package in `coordination/board/chatgpt.md` (status `in progress`) before changing files for
   it. Do not implement a package claimed on `coordination/board/claude.md`; reviewing and inspecting it
   is expected. To propose a hand-over, write to `coordination/inbox/to-claude/`.
3. Edit only your own board. Never edit or delete a message once it is on `main`.
4. Code merges only after the other AI's review on the PR thread and passing exact-head checks.
5. Before you stop: push your work to a `chatgpt/*` or `codex/*` branch, update your board, and answer
   every message that needs a reply. An owner pause overrides this: while paused, change nothing.
