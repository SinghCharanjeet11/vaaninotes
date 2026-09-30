"""Detect the host hardware so the UI can show where each model is running."""

from __future__ import annotations

import os
import platform
import subprocess
from functools import lru_cache


@lru_cache(maxsize=1)
def cpu_name() -> str:
    if platform.system() == "Windows":
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_Processor).Name"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            if out:
                return out
        except (OSError, subprocess.SubprocessError):
            pass
    return platform.processor() or platform.machine()


def is_arm64() -> bool:
    arch = (os.environ.get("PROCESSOR_ARCHITECTURE") or platform.machine()).upper()
    return arch in ("ARM64", "AARCH64")


def is_snapdragon() -> bool:
    name = cpu_name().lower()
    return "snapdragon" in name or "qualcomm" in name or "oryon" in name


@lru_cache(maxsize=1)
def qnn_available() -> bool:
    """True when ONNX Runtime can reach the QNN execution provider (Hexagon NPU)."""
    from . import qnn

    try:
        return qnn.available() and (is_arm64() or is_snapdragon())
    except Exception:
        return False


def summary() -> dict[str, str]:
    return {
        "CPU": cpu_name(),
        "Architecture": "ARM64" if is_arm64() else platform.machine(),
        "Snapdragon": "yes" if is_snapdragon() else "no",
        "Hexagon NPU (QNN EP)": "available" if qnn_available() else "not available",
    }
