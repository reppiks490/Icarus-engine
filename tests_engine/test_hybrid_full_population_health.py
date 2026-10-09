from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools import hybrid_loop_bridge as bridge
from tools.test_hybrid_loop_bridge import registry


class HybridFullPopulationHealthTests(unittest.TestCase):
    def populate_requests(self, root: Path, count: int) -> list[str]:
        lane = "robustness_guardian"
        directory = root / bridge.request_dir_for(lane)
        directory.mkdir(parents=True)
        identifiers = []
        start = datetime(2026, 10, 4, 20, tzinfo=timezone.utc)
        for index in range(count):
            slot = start + timedelta(hours=index)
            request_id = f"{lane}-{bridge.compact_stamp(slot)}"
            identifiers.append(request_id)
            (directory / f"{request_id}.json").write_text(json.dumps({
                "request_id": request_id,
                "due_slot_utc": bridge.z(slot),
                "requested_at_utc": bridge.z(slot + timedelta(minutes=5)),
            }))
        return identifiers

    def write_result(self, root: Path, request_id: str, **overrides) -> None:
        result = {
            "schema_version": bridge.RESULT_SCHEMA,
            "fabric_id": bridge.FABRIC_ID,
            "request_id": request_id,
            "lane": "robustness_guardian",
            "automation_id": "a",
            "started_at_utc": "2026-10-06T18:05:00Z",
            "completed_at_utc": "2026-10-06T18:10:00Z",
            "outcome": "NO_MATERIAL_DELTA",
            "substantive_work_performed": True,
            "summary": "checked",
            "evidence": [],
            "research_receipt_paths": [],
            "event_paths": [],
            "blockers": [],
            "backfilled_request_ids": [],
            "execution_authorized": False,
        }
        result.update(overrides)
        path = root / bridge.result_path_for("robustness_guardian", request_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result))

    def test_health_finds_invalid_old_result_outside_resolved_hot_window(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_ids = self.populate_requests(root, 31)
            for request_id in request_ids:
                self.write_result(root, request_id)
            self.write_result(root, request_ids[0], substantive_work_performed="legacy string")
            directory = root / bridge.request_dir_for("robustness_guardian")
            (directory / "latest.json").write_bytes((directory / f"{request_ids[-1]}.json").read_bytes())
            health = bridge.build_health(root, "robustness_guardian", registry()["lanes"]["robustness_guardian"],
                                         datetime(2026, 10, 7, tzinfo=timezone.utc))
            self.assertEqual(health["health"], "PENDING")
            self.assertEqual(health["oldest_unresolved_request_id"], request_ids[0])
            self.assertEqual(health["request_count_total"], 31)
            self.assertEqual(health["unresolved_count_total"], 1)
            self.assertEqual(health["unresolved_count_hot_window"], 0)
            self.assertEqual(health["invalid_request_count"], 0)
            self.assertFalse(health["execution_authorized"])

    def test_enqueue_keeps_complete_prior_backlog_beyond_hot_window(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_ids = self.populate_requests(root, 30)
            originals = {path: path.read_bytes() for path in bridge.request_files(root, "robustness_guardian")}
            new_request = bridge.enqueue(root, registry(), "robustness_guardian", "workflow_dispatch", "101", "1",
                                         datetime(2026, 10, 7, tzinfo=timezone.utc))
            self.assertEqual(new_request["prior_unresolved_request_ids"], request_ids)
            for path, content in originals.items():
                self.assertEqual(path.read_bytes(), content)
            health = bridge.build_health(root, "robustness_guardian", registry()["lanes"]["robustness_guardian"],
                                         datetime(2026, 10, 7, tzinfo=timezone.utc))
            self.assertEqual(health["unresolved_count_total"], 31)
            self.assertEqual(health["unresolved_count_hot_window"], 24)
            self.assertEqual(health["oldest_unresolved_request_id"], request_ids[0])
            self.assertEqual(health["health"], "BACKLOG")

    def test_health_cannot_resolve_malformed_immutable_requests(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_ids = self.populate_requests(root, 30)
            for request_id in request_ids:
                self.write_result(root, request_id)
            directory = root / bridge.request_dir_for("robustness_guardian")
            bad_payloads = {
                "broken.json": b"{",
                "not-object.json": b"[]",
                "missing-id.json": b"{}",
                "mismatch.json": b'{"request_id":"../outside"}',
                "bad-unicode.json": b"\xff",
            }
            for name, content in bad_payloads.items():
                (directory / name).write_bytes(content)
            health = bridge.build_health(root, "robustness_guardian", registry()["lanes"]["robustness_guardian"],
                                         datetime(2026, 10, 7, tzinfo=timezone.utc))
            self.assertEqual(health["health"], "UNVERIFIED")
            self.assertEqual(health["request_count_total"], 35)
            self.assertEqual(health["unresolved_count_total"], 0)
            self.assertEqual(health["invalid_request_count"], 5)
            self.assertEqual({Path(p).name for p in health["invalid_request_paths"]}, set(bad_payloads))

    def test_unhashable_result_outcomes_are_unresolved_without_aborting_scan(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_ids = self.populate_requests(root, 30)
            for request_id in request_ids:
                self.write_result(root, request_id)
            for outcome in ([], {}):
                with self.subTest(outcome=outcome):
                    self.write_result(root, request_ids[0], outcome=outcome)
                    health = bridge.build_health(root, "robustness_guardian", registry()["lanes"]["robustness_guardian"],
                                                 datetime(2026, 10, 7, tzinfo=timezone.utc))
                    self.assertEqual(health["unresolved_count_total"], 1)
                    self.assertEqual(health["oldest_unresolved_request_id"], request_ids[0])
                    self.assertEqual(health["health"], "PENDING")

    def test_oldest_uses_due_time_and_explicit_legacy_request_time(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            directory = root / bridge.request_dir_for("robustness_guardian")
            directory.mkdir(parents=True)
            payloads = {
                "a-later": {"due_slot_utc": "2026-10-06T20:00:00Z", "requested_at_utc": "2026-10-04T20:00:00Z"},
                "z-older": {"due_slot_utc": "2026-10-04T20:00:00Z", "requested_at_utc": "2026-10-06T20:00:00Z"},
                "m-legacy": {"requested_at_utc": "2026-10-04T20:30:00+01:00"},
            }
            for request_id, payload in payloads.items():
                payload["request_id"] = request_id
                (directory / f"{request_id}.json").write_text(json.dumps(payload))
            health = bridge.build_health(root, "robustness_guardian", registry()["lanes"]["robustness_guardian"],
                                         datetime(2026, 10, 7, tzinfo=timezone.utc))
            self.assertEqual(health["oldest_unresolved_request_id"], "m-legacy")
            self.assertEqual(bridge.unresolved_requests(root, "robustness_guardian", "a", limit=0),
                             ["m-legacy", "z-older", "a-later"])
            self.assertEqual(health["invalid_request_count"], 0)

    def test_invalid_present_due_slot_never_falls_back_to_request_clock(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            directory = root / bridge.request_dir_for("robustness_guardian")
            directory.mkdir(parents=True)
            path = directory / "bad-clock.json"
            for clock in (None, True, [], "not-a-clock", "2026-10-04T20:00:00",
                          "9999-12-31T23:59:59-23:59", "0001-01-01T00:00:00+23:59"):
                with self.subTest(clock=clock):
                    path.write_text(json.dumps({"request_id": "bad-clock", "due_slot_utc": clock,
                                                "requested_at_utc": "2026-10-04T20:00:00Z"}))
                    health = bridge.build_health(root, "robustness_guardian", registry()["lanes"]["robustness_guardian"],
                                                 datetime(2026, 10, 7, tzinfo=timezone.utc))
                    self.assertEqual(health["health"], "UNVERIFIED")
                    self.assertEqual(health["invalid_request_count"], 1)
                    self.assertEqual(health["unresolved_count_total"], 1)
                    self.assertFalse(health["execution_authorized"])

    def test_request_and_optional_creation_clocks_are_required_to_verify_health(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_id = self.populate_requests(root, 1)[0]
            self.write_result(root, request_id)
            path = root / bridge.request_dir_for("robustness_guardian") / f"{request_id}.json"
            original = json.loads(path.read_text())
            for field in ("requested_at_utc", "request_created_at_utc"):
                for clock in (None, True, "not-a-clock", "2026-10-04T20:00:00"):
                    with self.subTest(field=field, clock=clock):
                        payload = dict(original)
                        payload[field] = clock
                        path.write_text(json.dumps(payload))
                        health = bridge.build_health(root, "robustness_guardian", registry()["lanes"]["robustness_guardian"],
                                                     datetime(2026, 10, 7, tzinfo=timezone.utc))
                        self.assertEqual(health["health"], "UNVERIFIED")
                        self.assertEqual(health["invalid_request_count"], 1)
                        self.assertEqual(health["unresolved_count_total"], 0)
            payload = dict(original)
            del payload["requested_at_utc"]
            path.write_text(json.dumps(payload))
            self.assertEqual(bridge.build_health(root, "robustness_guardian", registry()["lanes"]["robustness_guardian"],
                                                datetime(2026, 10, 7, tzinfo=timezone.utc))["health"], "UNVERIFIED")

