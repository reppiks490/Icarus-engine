"""Read-only process birth identity for durable worker ownership on Windows."""
import os


def identity(pid):
    """Return a birth token, False for confirmed exited, or None if unknown.

    Never infer death from permission failure and never signal/terminate a PID.
    Reused PIDs have a different birth token.
    """
    if type(pid) is not int or pid <= 0:
        return None
    if os.name != "nt":
        from pathlib import Path
        try:
            # /proc stat's process name may contain spaces/parentheses.
            tail = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            return tail[19]  # field 22: starttime, after pid/comm
        except FileNotFoundError:
            return False
        except (OSError, IndexError):
            return None
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)  # query limited + synchronize
    if not handle:
        return False if ctypes.get_last_error() == 87 else None
    try:
        if kernel.WaitForSingleObject(handle, 0) == 0:
            return False
        values = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in values)):
            return None
        return str((values[0].dwHighDateTime << 32) | values[0].dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)
