"""Guards on the repository's structural claims.

These fail locally, before CI, if the engine core ever picks up a dependency or
the CLI loses a command.
"""

import ast
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE = ROOT / "icarus"


def _imported_roots(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_engine_core_imports_only_the_standard_library():
    """The claim that makes one code path valid in research and in production."""
    allowed = set(sys.stdlib_module_names) | {"icarus"}
    offenders = {
        str(path.relative_to(ROOT)): sorted(_imported_roots(path) - allowed)
        for path in sorted(CORE.rglob("*.py"))
        if _imported_roots(path) - allowed
    }
    assert offenders == {}, f"third-party imports in the engine core: {offenders}"


def test_project_declares_no_runtime_dependencies():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "dependencies = []" in text


@pytest.mark.parametrize("command", ["demo", "backtest", "compare", "walk", "live", "export-features"])
def test_cli_command_parses(command):
    """Argument parsing is not covered by any other test, so a typo ships silently."""
    result = subprocess.run(
        [sys.executable, "-m", "icarus", command, "--help"],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "--asset" in result.stdout


def test_cli_rejects_an_unknown_command():
    result = subprocess.run(
        [sys.executable, "-m", "icarus", "teleport"],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode != 0
