# Icarus-engine — instructions for Claude sessions

Read `ICARUS_STATE.md` before doing anything. It holds the goal in numbers, what is proven, what is dead,
the rules no AI may break, which keys exist, and who owns what.

- Tests: `python -m pytest tests tests_engine --import-mode=importlib -q` and
  `python -m pytest tests_cl -q -p no:cacheprovider` (needs numpy, pandas, scipy).
- Research claims go in `docs/RESEARCH_LOG.md`, with numbers on both the tuning and held-out spans.
- New tests of an idea are pre-registered in a `docs/*PREREG*.md` file before their data is seen.
- Work on a `claude/*` branch. Merge to `main` only when every test passes.
- `automation_intelligence/` is mostly written by bots. Do not hand-edit another lane's files.
