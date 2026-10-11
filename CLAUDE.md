# Icarus-engine — instructions for Claude sessions

Read `ICARUS_STATE.md` before doing anything. It holds the goal in numbers, what is proven, what is dead,
the rules no AI may break, which keys exist, and who owns what.

Then read both task lists in `coordination/board/` and every unanswered message in
`coordination/inbox/to-claude/` (`python -m tools.coordination`). ChatGPT/Codex works in this repo too;
the protocol, agreed by both on 2026-10-11, is `coordination/README.md`. Claim a package on
`coordination/board/claude.md` before changing files for it; never implement a package on ChatGPT's
board (reviewing it is expected); merge code only after ChatGPT's review and passing exact-head checks;
push and answer messages before stopping, unless the owner has paused work.

- Tests: `python -m pytest tests tests_engine --import-mode=importlib -q` and
  `python -m pytest tests_cl -q -p no:cacheprovider` (needs numpy, pandas, scipy).
- Research claims go in `docs/RESEARCH_LOG.md`, with numbers on both the tuning and held-out spans.
- New tests of an idea are pre-registered in a `docs/*PREREG*.md` file before their data is seen.
- Work on a `claude/*` branch. Merge to `main` only when every test passes.
- `automation_intelligence/` is mostly written by bots. Do not hand-edit another lane's files.
- Never write `close`, `fix` or `resolve` followed by `#<number>` in a PR description or commit message
  unless that PR is meant to close it.
