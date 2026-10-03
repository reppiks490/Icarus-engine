"""Verify background Git launches at the production process boundary."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import check_mcp_event_contract as contract
from tools import export_peer_intelligence as exporter
from tools import restored_five_durability_watchdog as watchdog

NO_WINDOW = 0x08000000


class BackgroundGitTests(unittest.TestCase):
    def test_export_git_windows_flags_preserve_source_results(self):
        def execute(command, **kwargs):
            self.assertEqual(kwargs.get("creationflags"), NO_WINDOW)
            self.assertTrue(kwargs["capture_output"])
            value = "a" * 40 + "\n" if "rev-parse" in command else b"committed bytes"
            return subprocess.CompletedProcess(command, 0, value, "")
        with patch.object(sys, "platform", "win32"), patch.object(subprocess, "CREATE_NO_WINDOW", NO_WINDOW, create=True), patch.object(subprocess, "run", execute):
            self.assertEqual(exporter._git_head(Path(".")), "a" * 40)
            self.assertEqual(exporter._git_show_bytes(Path("."), "a" * 40, "receipt.json"), b"committed bytes")

    def test_watchdog_and_contract_git_windows_flags_preserve_history(self):
        def execute(command, **kwargs):
            self.assertEqual(kwargs.get("creationflags"), NO_WINDOW)
            if "show" in command:
                self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
                return json.dumps({"RUN_ID": "fixture"})
            return "a" * 40 + "\n"
        with patch.object(sys, "platform", "win32"), patch.object(subprocess, "CREATE_NO_WINDOW", NO_WINDOW, create=True), patch.object(subprocess, "check_output", execute):
            self.assertEqual(watchdog.git(Path("."), "rev-parse", "HEAD"), "a" * 40)
            self.assertEqual(watchdog.git_json_history(Path("."), "receipt.json"), [{"RUN_ID": "fixture"}])
            self.assertEqual(contract.sh("git", "rev-parse", "HEAD"), "a" * 40)

    def test_real_git_results_and_direct_script_invocation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for args in (("init", "-q"), ("config", "user.name", "fixture"), ("config", "user.email", "fixture@example.invalid"), ("config", "core.autocrlf", "false")):
                subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
            (root / "receipt.json").write_bytes(b'{"RUN_ID":"fixture"}\n')
            for args in (("add", "."), ("commit", "-qm", "fixture")):
                subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
            commit = exporter._git_head(root)
            self.assertEqual(watchdog.git(root, "rev-parse", "HEAD"), commit)
            self.assertEqual(watchdog.git_json_history(root, "receipt.json"), [{"RUN_ID": "fixture"}])
            self.assertEqual(exporter._git_show_bytes(root, commit, "receipt.json"), b'{"RUN_ID":"fixture"}\n')
            subprocess.run(["git", "-C", str(root), "update-ref", "refs/remotes/origin/fixture-base", commit], check=True)
            script = Path(contract.__file__).resolve()
            env = dict(os.environ, GITHUB_BASE_REF="fixture-base")
            result = subprocess.run([sys.executable, str(script)], cwd=root, capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("no critical ICARUS code changes", result.stdout)
            result = subprocess.run([sys.executable, str(Path(watchdog.__file__).resolve()), "--help"], cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(sys.platform == "win32", "requires Windows console API")
    def test_real_background_child_has_no_console(self):
        from tools.background_process import background_kwargs
        result = subprocess.run([sys.executable, "-c", "import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())"],
                                capture_output=True, text=True, check=True, timeout=10, **background_kwargs())
        self.assertEqual(result.stdout.strip(), "0")


if __name__ == "__main__":
    unittest.main()
