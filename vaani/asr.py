"""Speech recognition backends.

* ``NpuWhisperASR`` runs Qualcomm AI Hub's Whisper-Small encoder/decoder on the
  Hexagon NPU through ONNX Runtime's QNN execution provider, with the same
  decoding contract as ``qai_hub_models``' HfWhisperApp (the model Qualcomm
  profiled on Snapdragon X Elite).
* ``CpuWhisperASR`` runs the same Whisper-Small weights with PyTorch on the CPU.
  It is the fallback for non-Snapdragon machines and the baseline in benchmarks.

Both split audio into 30 s windows (Whisper's native context), so every
segment carries a timestamp for the notes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .audio import SAMPLE_RATE, duration_s
from .config import Config

CHUNK_SECONDS = 30


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    text: str
    segments: list[Segment]
    language: str
    backend: str
    audio_seconds: float
    elapsed_seconds: float
    per_chunk_ms: list[float] = field(default_factory=list)

    @property
    def realtime_factor(self) -> float:
        """Seconds of compute per second of audio (lower is better)."""
        return self.elapsed_seconds / max(self.audio_seconds, 1e-6)

    def timestamped(self) -> str:
        return "\n".join(f"[{_fmt(s.start)}] {s.text}" for s in self.segments if s.text)


def _fmt(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def chunk_audio(audio: np.ndarray, seconds: int = CHUNK_SECONDS) -> list[tuple[float, np.ndarray]]:
    step = seconds * SAMPLE_RATE
    chunks = [(i / SAMPLE_RATE, audio[i:i + step]) for i in range(0, len(audio), step)]
    # Drop a trailing sliver (< 0.5 s) that would only produce hallucinations.
    if len(chunks) > 1 and len(chunks[-1][1]) < SAMPLE_RATE // 2:
        chunks.pop()
    return chunks or [(0.0, audio)]


def _language_tokens(tokenizer) -> dict[int, str]:
    """Map Whisper language-token ids (<|hi|>, <|en|>, ...) to language codes."""
    from transformers.models.whisper.tokenization_whisper import LANGUAGES as WHISPER_LANGS

    out = {}
    for code in WHISPER_LANGS:
        tid = tokenizer.convert_tokens_to_ids(f"<|{code}|>")
        if tid is not None and tid != tokenizer.unk_token_id:
            out[tid] = code
    return out


def _prompt_ids(tokenizer, language: str, task: str) -> list[int]:
    """Whisper decoder prompt: <|startoftranscript|> [<|lang|>] <|task|> <|notimestamps|>.

    With language == "auto" only the start token is forced and Whisper predicts the
    language itself (and then defaults to transcription).
    """
    ids = [tokenizer.convert_tokens_to_ids("<|startoftranscript|>")]
    if language == "auto":
        return ids
    ids.append(tokenizer.convert_tokens_to_ids(f"<|{language}|>"))
    ids.append(tokenizer.convert_tokens_to_ids(f"<|{task}|>"))
    ids.append(tokenizer.convert_tokens_to_ids("<|notimestamps|>"))
    return ids


class BaseASR:
    name = "base"

    def _transcribe_chunk(self, audio: np.ndarray, language: str, task: str) -> tuple[str, str | None]:
        raise NotImplementedError

    def transcribe(self, audio: np.ndarray, language: str = "auto", task: str = "transcribe",
                   progress=None, on_segment=None) -> Transcript:
        segments, per_chunk, langs = [], [], []
        chunks = chunk_audio(audio)
        t0 = time.perf_counter()
        for i, (start, chunk) in enumerate(chunks):
            if progress:
                progress(i / len(chunks), f"Transcribing {i + 1}/{len(chunks)} on {self.name}")
            c0 = time.perf_counter()
            text, lang = self._transcribe_chunk(chunk, language, task)
            per_chunk.append((time.perf_counter() - c0) * 1000)
            segments.append(Segment(start, start + duration_s(chunk), text.strip()))
            if on_segment:
                on_segment(segments[-1])
            if lang:
                langs.append(lang)
        elapsed = time.perf_counter() - t0
        detected = language if language != "auto" else (max(set(langs), key=langs.count) if langs else "unknown")
        return Transcript(
            text=" ".join(s.text for s in segments if s.text),
            segments=segments,
            language=detected,
            backend=self.name,
            audio_seconds=duration_s(audio),
            elapsed_seconds=elapsed,
            per_chunk_ms=per_chunk,
        )


_ORT_DTYPES = {
    "tensor(float)": np.float32,
    "tensor(float16)": np.float16,
    "tensor(int32)": np.int32,
    "tensor(int64)": np.int64,
}
MASK_NEG = -100.0  # value used by AI Hub's Whisper export for masked positions


class QnnSession:
    """Thin ONNX Runtime wrapper: {input name: array} -> {output name: array}.

    Inputs are cast to the dtype the compiled graph declares (AI Hub's float
    Whisper export uses float16 I/O), so callers can stay in float32.
    """

    def __init__(self, model_path: Path, provider: str = "QNNExecutionProvider"):
        if provider == "QNNExecutionProvider":
            from . import qnn

            self.session = qnn.session(str(model_path))
        else:
            import onnxruntime as ort

            self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.inputs = {i.name: i for i in self.session.get_inputs()}
        self.output_names = [o.name for o in self.session.get_outputs()]

    def dtype(self, name: str):
        return _ORT_DTYPES.get(self.inputs[name].type, np.float32)

    def __call__(self, feed: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        feed = {k: np.asarray(v).astype(self.dtype(k), copy=False) for k, v in feed.items()}
        return dict(zip(self.output_names, self.session.run(None, feed)))


class NpuWhisperASR(BaseASR):
    """Whisper-Small exported by Qualcomm AI Hub (``whisper_small``, precision float,
    runtime ``precompiled_qnn_onnx``) running on the Hexagon NPU.

    I/O contract of the AI Hub export (checked against the v0.63.0 assets):
      encoder: input_features[1,80,3000] -> k/v_cache_cross_{i}
      decoder: input_ids[1,1], position_ids[1], attention_mask[1,1,1,200],
               k/v_cache_self_{i}_in, k/v_cache_cross_{i}
               -> k/v_cache_self_{i}_out, logits[1,vocab,1,1]
    Tensors are fed by name. The greedy loop follows ``HfWhisperApp`` in
    qai_hub_models (BSD-3-Clause, Qualcomm Technologies), re-implemented in numpy so
    the NPU path needs only onnxruntime-qnn + the tokenizer (no PyTorch), and extended
    with a forced prompt to pin the language and choose transcribe / translate.
    """

    name = "Whisper-Small on Hexagon NPU (QNN)"

    def __init__(self, cfg: Config, provider: str = "QNNExecutionProvider"):
        from transformers import WhisperConfig, WhisperFeatureExtractor, WhisperTokenizer

        encoder_path, decoder_path = find_npu_assets(cfg.whisper_npu_dir)
        self.encoder = QnnSession(encoder_path, provider)
        self.decoder = QnnSession(decoder_path, provider)
        self.eos_token_id = WhisperConfig.from_pretrained(cfg.whisper_hf_id).eos_token_id
        self.feature_extractor = WhisperFeatureExtractor.from_pretrained(cfg.whisper_hf_id)
        self.tokenizer = WhisperTokenizer.from_pretrained(cfg.whisper_hf_id)
        self.lang_ids = _language_tokens(self.tokenizer)

    def _transcribe_chunk(self, audio, language, task):
        feats = self.feature_extractor(audio, sampling_rate=SAMPLE_RATE,
                                       return_tensors="np")["input_features"]
        tokens = greedy_decode(self.encoder, self.decoder, feats,
                               _prompt_ids(self.tokenizer, language, task), self.eos_token_id)
        lang = next((self.lang_ids[t] for t in tokens if t in self.lang_ids), None)
        return self.tokenizer.decode(tokens, skip_special_tokens=True), lang


def greedy_decode(encoder, decoder, features: np.ndarray, prompt: list[int], eos: int) -> list[int]:
    """Greedy Whisper decoding against the AI Hub encoder/decoder contract.

    ``encoder`` / ``decoder`` are callables taking and returning {name: array};
    ``decoder.inputs`` maps input names to objects with ``.shape`` (see QnnSession).
    """
    specs = decoder.inputs
    cross = {k: v for k, v in encoder({"input_features": features}).items() if k in specs}
    self_cache = {name: np.zeros(spec.shape, dtype=decoder.dtype(name))
                  for name, spec in specs.items() if name.endswith("_in")}
    n_ctx = specs["attention_mask"].shape[-1]  # max decode length (200)
    mask = np.full((1, 1, 1, n_ctx), MASK_NEG, dtype=np.float32)

    tokens = list(prompt)
    for n in range(n_ctx - 1):
        mask[..., n_ctx - n - 1] = 0.0  # positions are unmasked from the right
        out = decoder({
            "input_ids": np.array([[tokens[n]]], dtype=np.int32),
            "position_ids": np.array([n], dtype=np.int32),
            "attention_mask": mask,
            **self_cache,
            **cross,
        })
        self_cache = {name[:-4] + "_in": value for name, value in out.items()
                      if name.endswith("_out")}
        if n >= len(prompt) - 1:
            next_id = int(np.argmax(out["logits"].reshape(-1)))
            tokens.append(next_id)
            if next_id == eos:
                break
    return tokens


class CpuWhisperASR(BaseASR):
    name = "Whisper-Small on CPU (PyTorch)"

    def __init__(self, cfg: Config):
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor

        self._torch = torch
        self.processor = WhisperProcessor.from_pretrained(cfg.whisper_hf_id)
        self.model = WhisperForConditionalGeneration.from_pretrained(cfg.whisper_hf_id).eval()
        self.lang_ids = _language_tokens(self.processor.tokenizer)
        size = cfg.whisper_hf_id.rsplit("-", 1)[-1].capitalize()
        self.name = f"Whisper-{size} on CPU (PyTorch)"

    def _transcribe_chunk(self, audio, language, task):
        feats = self.processor(audio, sampling_rate=SAMPLE_RATE, return_tensors="pt").input_features
        with self._torch.inference_mode():
            if language == "auto":
                # generate() strips the prompt from its output, so detect explicitly.
                lang_id = int(self.model.detect_language(feats).flatten()[0])
                language = self.lang_ids.get(lang_id, "en")
            ids = self.model.generate(feats, task=task, language=language,
                                      max_new_tokens=440)[0].tolist()
        return self.processor.tokenizer.decode(ids, skip_special_tokens=True), language


def find_npu_assets(folder: Path) -> tuple[Path, Path]:
    """Locate the AI Hub encoder/decoder ONNX files under ``folder``.

    AI Hub downloads are zip bundles (model.onnx + QNN context .bin); they are
    extracted in place the first time.
    """
    import zipfile

    folder = Path(folder)
    if not folder.exists():
        raise FileNotFoundError(f"{folder} does not exist. Run scripts/fetch_models.ps1 first.")
    for z in folder.rglob("*.zip"):
        target = z.with_suffix("")
        if not target.exists():
            with zipfile.ZipFile(z) as zf:
                zf.extractall(target)
    onnx_files = [p for p in folder.rglob("*.onnx") if "__MACOSX" not in p.parts]
    found: dict[str, Path] = {}
    for part in ("encoder", "decoder"):
        matches = sorted(p for p in onnx_files if part in str(p.relative_to(folder)).lower())
        if not matches:
            raise FileNotFoundError(f"No Whisper {part} .onnx found under {folder}.")
        found[part] = matches[0]
    return found["encoder"], found["decoder"]


def npu_ready(cfg: Config) -> tuple[bool, str]:
    from .device import qnn_available

    if not qnn_available():
        return False, "onnxruntime-qnn (QNNExecutionProvider) is not installed"
    try:
        find_npu_assets(cfg.whisper_npu_dir)
    except FileNotFoundError as e:
        return False, str(e)
    return True, "ok"


def load_asr(cfg: Config) -> BaseASR:
    choice = cfg.asr_backend.lower()
    if choice in ("auto", "npu"):
        ok, reason = npu_ready(cfg)
        if ok:
            return NpuWhisperASR(cfg)
        if choice == "npu":
            raise RuntimeError(f"NPU backend requested but unavailable: {reason}")
        print(f"[vaani] NPU ASR unavailable ({reason}); using CPU.")
    return CpuWhisperASR(cfg)
