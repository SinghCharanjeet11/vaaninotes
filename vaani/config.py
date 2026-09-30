"""Runtime configuration. Every value can be overridden with an environment variable."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Config:
    # --- Speech recognition -------------------------------------------------
    # "auto" -> NPU if the QNN runtime + AI Hub Whisper assets are present, else CPU.
    asr_backend: str = field(default_factory=lambda: _env("VAANI_ASR", "auto"))
    # Hugging Face id of the Whisper variant. Must match the AI Hub asset (whisper_small).
    whisper_hf_id: str = field(
        default_factory=lambda: _env("VAANI_WHISPER_HF_ID", "openai/whisper-small")
    )
    # Folder containing the AI Hub precompiled encoder/decoder (.onnx / .zip / .bin).
    whisper_npu_dir: Path = field(
        default_factory=lambda: Path(
            _env("VAANI_WHISPER_NPU_DIR", str(ROOT / "models" / "whisper_small"))
        )
    )

    # --- Language model -----------------------------------------------------
    # "auto" probes the local OpenAI-compatible servers below, then falls back to
    # the built-in extractive engine so the app always works offline.
    llm_backend: str = field(default_factory=lambda: _env("VAANI_LLM", "auto"))
    llm_base_url: str = field(default_factory=lambda: _env("VAANI_LLM_URL", ""))
    llm_model: str = field(
        default_factory=lambda: _env(
            "VAANI_LLM_MODEL", "ai-hub-models/Qwen3-4B-Instruct-2507"
        )
    )
    llm_timeout_s: float = field(
        default_factory=lambda: float(_env("VAANI_LLM_TIMEOUT", "600"))
    )
    # Characters of transcript per LLM call. Keeps prompts inside a 4K context.
    llm_chunk_chars: int = field(
        default_factory=lambda: int(_env("VAANI_LLM_CHUNK_CHARS", "6000"))
    )

    output_dir: Path = field(
        default_factory=lambda: Path(_env("VAANI_OUTPUT_DIR", str(ROOT / "outputs")))
    )


# Local, on-device OpenAI-compatible servers probed in order when llm_backend == "auto".
# Only loopback addresses are used: VaaniNotes never sends data off the machine.
LOCAL_LLM_SERVERS = {
    "geniex": "http://127.0.0.1:18181/v1",  # Qualcomm GenieX (Hexagon NPU)
    "ollama": "http://127.0.0.1:11434/v1",  # Ollama (CPU/GPU fallback)
    "lmstudio": "http://127.0.0.1:1234/v1",  # LM Studio
}

# Whisper language codes offered in the UI (Whisper supports ~100; these cover India + English).
LANGUAGES = {
    "auto": "Auto-detect",
    "en": "English",
    "hi": "Hindi",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "mr": "Marathi",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "ur": "Urdu",
}

OUTPUT_LANGUAGES = ["English", "Hindi", "Bengali", "Tamil", "Telugu", "Marathi",
                    "Gujarati", "Kannada", "Malayalam", "Punjabi", "Urdu"]
