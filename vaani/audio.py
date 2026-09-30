"""Audio loading helpers. Everything is converted to 16 kHz mono float32."""

from __future__ import annotations

import shutil
import subprocess
from math import gcd
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000


def to_float32(audio: np.ndarray) -> np.ndarray:
    """Convert integer PCM or float audio to float32 in [-1, 1], collapsing channels."""
    audio = np.asarray(audio)
    if np.issubdtype(audio.dtype, np.integer):
        audio = audio.astype(np.float32) / float(np.iinfo(audio.dtype).max)
    if audio.ndim == 2:
        # Gradio gives (samples, channels); some decoders give (channels, samples).
        axis = 1 if audio.shape[0] > audio.shape[1] else 0
        audio = audio.mean(axis=axis)
    return audio.astype(np.float32)


def resample(audio: np.ndarray, sr: int, target_sr: int = SAMPLE_RATE) -> np.ndarray:
    if sr == target_sr:
        return audio
    from scipy.signal import resample_poly

    g = gcd(sr, target_sr)
    return resample_poly(audio, target_sr // g, sr // g).astype(np.float32)


def _load_with_ffmpeg(path: Path) -> np.ndarray:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError(
            f"Cannot decode '{path.suffix}' without ffmpeg. Install it with "
            "'winget install ffmpeg' or convert the file to .wav."
        )
    raw = subprocess.run(
        [ffmpeg, "-nostdin", "-i", str(path), "-f", "f32le", "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-loglevel", "error", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def load_audio(source: str | Path | tuple[int, np.ndarray]) -> np.ndarray:
    """Load a file path or a (sample_rate, samples) tuple into 16 kHz mono float32."""
    if isinstance(source, tuple):
        sr, data = source
        return resample(to_float32(data), int(sr))

    path = Path(source)
    if path.suffix.lower() == ".wav":
        from scipy.io import wavfile

        try:
            sr, data = wavfile.read(path)
            return resample(to_float32(data), int(sr))
        except ValueError:
            pass  # unusual WAV encoding: let ffmpeg handle it
    return _load_with_ffmpeg(path)


def load_wav_bytes(data: bytes) -> np.ndarray:
    """Decode an in-memory WAV file (what the web UI uploads) to 16 kHz mono float32."""
    import io

    from scipy.io import wavfile

    sr, samples = wavfile.read(io.BytesIO(data))
    return resample(to_float32(samples), int(sr))


def duration_s(audio: np.ndarray) -> float:
    return len(audio) / SAMPLE_RATE
