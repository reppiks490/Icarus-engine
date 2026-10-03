"""Platform options for noninteractive peer-tool children."""
import subprocess
import sys


def background_kwargs() -> dict[str, int]:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
