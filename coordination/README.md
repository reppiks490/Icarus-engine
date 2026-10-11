# Claude ↔ ChatGPT coordination

Two AIs work in this repository:

- **Claude** (Anthropic), on `claude/*` branches;
- **ChatGPT / Codex** (OpenAI), on `chatgpt/*` and `codex/*` branches.

They cannot talk to each other directly, so this folder is how they talk. The owner set it up on
2026-10-11 after the two collided twice on the same work (the SEC user agent and the Databento depth
cache). The older lane notes in this folder (`CL_LANE_*.md`, `PR2_*.md`, `PEER_*.md`) stay as they are.

## Every session, both AIs

1. Read `ICARUS_STATE.md`.
2. Read both task lists: `board/claude.md` and `board/chatgpt.md`.
3. Read every message in your inbox that still needs a reply. `python -m tools.coordination` lists them.
4. **Claim before you start.** Add the task to your own board as `in progress` before working on it.
   Never start a task that is on the other AI's board unless its status is `done`. If you think a task
   should change hands, send a message and wait for the answer.
5. **Before you stop:** push your work, update your board, and answer every message that needs a reply.
   Work that is not pushed is invisible to the other AI.

## Task lists

- `board/claude.md` is edited only by Claude; `board/chatgpt.md` only by ChatGPT. Never edit the other's.
- Each has an **Owns** list (the paths that AI writes) and one task table:

  | Id | Task | Status | Branch / PR | Updated |
  |---|---|---|---|---|

  Status is one of `planned`, `in progress`, `blocked`, `waiting`, `done`. `Updated` is `YYYY-MM-DD`.
  An `in progress` row not updated for 7 days is reported as stale.
- Files outside both Owns lists, and the shared files (`ICARUS_STATE.md`, `AGENTS.md`, `CLAUDE.md`,
  this README, `docs/RESEARCH_LOG.md`), may be edited by either AI in a PR that says why.

## Messages

- To send, create a new file in `inbox/to-<recipient>/` (`to-claude` or `to-chatgpt`) named
  `YYYYMMDDTHHMMZ-<sender>-<short-slug>.md`, in UTC. Example: `20261011T0437Z-claude-hello.md`.
- The file starts with these header lines, then a blank line, then the body:

  ```
  From: Claude
  To: ChatGPT
  Date: 2026-10-11T04:37Z
  Subject: One line
  Reply-needed: yes
  Re: -
  ```

- To reply, create a new file in the sender's inbox whose `Re:` line names the file you are answering.
  That closes it.
- Never edit or delete a message once it is on `main`. To correct one, send another.
- Keep messages short and concrete: what you need, the file paths, the PR links. Evidence, not claims
  (rule 2 in `ICARUS_STATE.md`).

## Getting it onto `main`

The other AI reads `main`, so messages and board updates count only once they are there. They hold no
code, so they may be committed straight to `main`, or merged in a PR without waiting for review. Code
goes through PRs as usual. To ask for a review of a PR, send a message with its link.

## Automation

- **Claude coordinator** (Claude routine, 06:25 and 18:25 America/Chicago): reads Claude's inbox and
  answers it, reviews ChatGPT PRs opened or updated since its last run, and updates Claude's board.
- **Data-health sentinel** (`tools/data_sentinel.py`, every 3 h and on every push here): puts the
  mailbox and board counts into `automation_intelligence/sentinel/DATA_HEALTH.md`.
- **Daily briefing** (Claude routine, 06:55 America/Chicago): reports both to the owner's phone.
