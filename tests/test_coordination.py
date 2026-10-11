from datetime import datetime, timezone

from tools import coordination as co

NOW = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)


def _msg(root, to, name, **h):
    path = root / "coordination/inbox" / f"to-{to}" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    head = "\n".join(f"{k}: {v}" for k, v in h.items())
    path.write_text(head + "\n\nBody text: with a colon that is not a header.\n", encoding="utf-8")


def _board(root, ai, rows):
    path = root / "coordination/board" / f"{ai}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    table = ["| Id | Task | Status | Branch / PR | Updated |", "|---|---|---|---|---|"]
    table += [f"| {i} | {t} | {s} | - | {u} |" for i, t, s, u in rows]
    path.write_text("# Board\n\n" + "\n".join(table) + "\n\n## Notes\n\nfree text\n", encoding="utf-8")


def test_a_reply_closes_the_message_it_names(tmp_path):
    _msg(tmp_path, "chatgpt", "20261011T0500Z-claude-hello.md", From="Claude", To="ChatGPT",
         Date="2026-10-11T05:00Z", Subject="Hello", **{"Reply-needed": "yes"})
    _msg(tmp_path, "chatgpt", "20261011T0510Z-claude-fyi.md", From="Claude", To="ChatGPT",
         Date="2026-10-11T05:10Z", Subject="FYI", **{"Reply-needed": "no"})
    s = co.summary(tmp_path, NOW)
    assert s["awaiting_reply"] == {"claude": [], "chatgpt": ["20261011T0500Z-claude-hello.md"]}

    _msg(tmp_path, "claude", "20261011T0900Z-chatgpt-re-hello.md", From="ChatGPT", To="Claude",
         Date="2026-10-11T09:00Z", Subject="Re: Hello", Re="20261011T0500Z-claude-hello.md",
         **{"Reply-needed": "no"})
    s = co.summary(tmp_path, NOW)
    assert s["awaiting_reply"] == {"claude": [], "chatgpt": []}
    assert s["messages"] == 3 and s["malformed"] == []


def test_reply_may_name_the_file_without_extension(tmp_path):
    _msg(tmp_path, "claude", "20261011T0500Z-chatgpt-ask.md", From="ChatGPT", To="Claude",
         Date="2026-10-11", Subject="Ask", **{"Reply-needed": "yes"})
    _msg(tmp_path, "chatgpt", "20261011T0600Z-claude-answer.md", From="Claude", To="ChatGPT",
         Date="2026-10-11", Subject="Answer", Re="20261011T0500Z-chatgpt-ask", **{"Reply-needed": "no"})
    assert co.summary(tmp_path, NOW)["awaiting_reply"]["claude"] == []


def test_malformed_messages_are_reported_not_fatal(tmp_path):
    _msg(tmp_path, "claude", "note.md", From="ChatGPT", Subject="no date")
    s = co.summary(tmp_path, NOW)
    assert len(s["malformed"]) == 1
    assert "to" in s["malformed"][0] and "file name" in s["malformed"][0]


def test_board_counts_and_stale_in_progress(tmp_path):
    _board(tmp_path, "claude", [("C2", "Frontier", "in progress", "2026-10-10"),
                                ("C4", "Regime", "in progress", "2026-09-01"),
                                ("S1", "Sentinel", "done", "2026-10-11"),
                                ("X", "Odd", "someday", "2026-10-11")])
    b = co.summary(tmp_path, NOW)["boards"]
    assert b["claude"]["counts"] == {"in progress": 2, "done": 1, "other": 1}
    assert b["claude"]["stale"] == ["C4"]
    assert b["chatgpt"]["present"] is False


def test_markdown_lists_both_ais(tmp_path):
    _board(tmp_path, "chatgpt", [("P1", "MAX Pine", "planned", "2026-10-08")])
    text = co.markdown(co.summary(tmp_path, NOW))
    assert "claude: no board" in text and "chatgpt: planned 1" in text
