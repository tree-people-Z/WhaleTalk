"""Helpers for launching console tools from the windowed GUI build."""

import subprocess
import sys


def hidden_window_kwargs() -> dict:
    """Return subprocess kwargs that prevent console tools from flashing a window.

    In a windowed PyInstaller build there is no console, so every console
    subprocess (ffmpeg, pip, ...) would otherwise pop up a black window.
    """
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
    }
