# Claude ↔ ChatGPT coordination

Two AIs work in this repository:

- **Claude** (Anthropic), on `claude/*` branches;
- **ChatGPT / Codex** (OpenAI), on `chatgpt/*` and `codex/*` branches.

They cannot talk to each other directly, so this folder is how they talk. The owner set it up on
2026-10-11 after the two collided twice on the same work (the SEC user agent and the Databento depth
cache). Both AIs agreed this protocol on 2026-10-11; any change to it needs the other AI's review. The
older lane notes in this folder (`CL_LANE_*.md`, `PR2_*.md`, `PEER_*.md`) stay as they are.

## Where each kind of record lives

| Purpose | Place | Who edits |
|---|---|---|
| Who is doing what now | `board/<ai>.md` in this folder | each AI only its own |
| Questions, hand-overs, package receipts | `inbox/to-<ai>/`, one immutable file per message | the sender |
| Review of one change | that PR's own thread | reviewer comments, author answers |
| The requirement ledger (202 requirements, acceptance, certificates) | `reppiks490/icarus-owner-actions` `mission/register.json` and `mission/continuations/` | Codex; Claude sends receipts through the inbox |
| History | Icarus `coordination/`, older files here | nobody adds agent-to-agent messages there |

Work packages keep the IDs agreed on 2026-10-11 (`C01`, `J01`, `K1`, `R01-C2`, …). Name the repository
whenever a path is ambiguous: `icarus_engine/brain.py` in `reppiks490/Icarus` is not an Engine path.

## Every session, both AIs

1. Read `ICARUS_STATE.md`.
2. Read both task lists: `board/claude.md` and `board/chatgpt.md`.
3. Read every message in your inbox that still needs a reply. `python -m tools.coordination` lists them.
4. **Claim before you implement.** Add the package to your own board as `in progress` before changing
   any file for it. A claim stops the other AI from implementing the same thing. It does not stop
   read-only inspection, specification review or independent PR review, which are expected; track a
   review as its own row if useful, without taking over implementation. To move a package between AIs,
   send a message and wait for the answer.
5. **Before you stop:** push your work, update your board, and answer every message that needs a reply.
   Work that is not pushed is invisible to the other AI.

**An owner pause overrides step 5 and every other rule here that says to push, claim, answer or
schedule work.** While paused, change nothing. Unsafe or incomplete material is never published just
because a session is ending. When the owner pauses work, the AI that receives the instruction may commit
an empty file `coordination/PAUSED` (its commit message says who paused and when); every scheduled agent
does nothing while that file exists on `main`, and it is removed when the owner resumes.

## Task lists

- `board/claude.md` is edited only by Claude; `board/chatgpt.md` only by ChatGPT. Never edit the other's.
- Each has an **Owns** list (the paths that AI writes, with the repository named) and one task table:

  | Id | Task | Status | Branch / PR | Updated |
  |---|---|---|---|---|

  Status is one of `planned`, `in progress`, `blocked`, `waiting`, `done`. `Updated` is `YYYY-MM-DD`.
  An `in progress` row not updated for 7 days is reported as stale.
- **Shared files** (`ICARUS_STATE.md`, `AGENTS.md`, `CLAUDE.md`, this README, `docs/RESEARCH_LOG.md`)
  and files outside both Owns lists have one named editor per change: claim the edit on your board
  first, and never edit one the other AI has claimed. When a change affects the other AI's rules or
  ownership, it needs that AI's review before merging.

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
- **Package receipts.** When a package merges, its author sends a receipt to the other AI: PR, head and
  merge SHAs, CI run, tests actually collected and their counts (passed, failed, skipped), consumer or
  readback proof, limitations, and `execution_authorized=false`. Codex appends Claude's receipts to the
  requirement ledger.

## Delivery and merging

- Everything reaches `main` through a branch and a PR, respecting branch protection, required checks
  and any owner pause.
- Board updates and messages hold no code: their PRs need passing checks but no review.
- **Code:** the author merges only after the other AI's independent review on the PR thread and passing
  exact-head checks. A board status or a mailbox reply never substitutes for either.
- Never write `close`, `fix` or `resolve` followed by `#<number>` in a PR description or commit message
  unless that PR is meant to close it: GitHub closes the target on merge. (Claude closed #84 this way by
  accident on 2026-10-11.)

## Automation

- **Claude coordinator** (Claude routine, 06:25 and 18:25 America/Chicago): reads Claude's inbox and
  answers it, reviews ChatGPT PRs opened or updated since its last run on their PR threads, and keeps
  Claude's board true. It writes only `coordination/**` and PR review comments, and does nothing while
  `coordination/PAUSED` exists.
- **Data-health sentinel** (`tools/data_sentinel.py`, every 3 h and on every push here): puts the
  mailbox and board counts into `automation_intelligence/sentinel/DATA_HEALTH.md`.
- **Daily briefing** (Claude routine, 06:55 America/Chicago, read-only): reports both to the owner's
  phone.
- No rule here changes any ChatGPT automation's ID, prompt, cadence or enabled state.
