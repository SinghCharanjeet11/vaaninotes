import numpy as np

from vaani.asr import Segment, Transcript, _prompt_ids, chunk_audio
from vaani.audio import SAMPLE_RATE, load_audio, to_float32
from vaani.llm import ExtractiveLLM
from vaani.pipeline import NotesEngine, split_text

LECTURE = (
    "Photosynthesis converts light energy into chemical energy in plants. "
    "It happens inside chloroplasts which contain the pigment chlorophyll. "
    "The Calvin cycle uses energy to fix carbon dioxide into glucose. "
    "Your lab report on photosynthesis must be submitted by Friday. "
    "Please read chapter seven before next class for the quiz."
)


def make_transcript(text=LECTURE):
    return Transcript(text=text, segments=[Segment(0, 30, text)], language="en",
                      backend="test", audio_seconds=30, elapsed_seconds=1.5)


def test_chunk_audio_splits_into_30s_windows():
    audio = np.zeros(SAMPLE_RATE * 75, dtype=np.float32)
    chunks = chunk_audio(audio)
    assert [start for start, _ in chunks] == [0.0, 30.0, 60.0]
    assert len(chunks[-1][1]) == SAMPLE_RATE * 15


def test_chunk_audio_drops_tiny_tail():
    audio = np.zeros(SAMPLE_RATE * 30 + 100, dtype=np.float32)
    assert len(chunk_audio(audio)) == 1


def test_to_float32_int16_stereo():
    pcm = np.full((10, 2), 16383, dtype=np.int16)
    out = to_float32(pcm)
    assert out.shape == (10,) and out.dtype == np.float32
    assert abs(out[0] - 0.5) < 0.01


def test_load_audio_resamples_tuple():
    audio = load_audio((48000, np.zeros(48000, dtype=np.int16)))
    assert len(audio) == SAMPLE_RATE


def test_split_text_respects_limit():
    chunks = split_text(LECTURE * 10, 300)
    assert len(chunks) > 1
    assert all(len(c) <= 300 for c in chunks)


def test_extractive_notes_have_all_sections():
    notes = NotesEngine(ExtractiveLLM()).build(make_transcript())
    assert set(notes.sections) == {"summary", "key_points", "action_items", "flashcards"}
    assert "Friday" in notes.sections["action_items"]
    assert "Q:" in notes.sections["flashcards"]
    md = notes.to_markdown()
    assert "## Transcript" in md and "[00:00]" in md


def test_empty_transcript():
    notes = NotesEngine(ExtractiveLLM()).build(make_transcript(""))
    assert "No speech" in notes.sections["summary"]


def test_ask_retrieves_relevant_segment():
    t = make_transcript()
    t.segments = [Segment(0, 30, "Chlorophyll absorbs red and blue light."),
                  Segment(30, 60, "The lab report is due on Friday.")]
    answer = NotesEngine(ExtractiveLLM()).ask(t, "When is the lab report due?", k=1)
    assert "[00:30]" in answer and "Friday" in answer


class FakeTokenizer:
    vocab = {"<|startoftranscript|>": 1, "<|hi|>": 2, "<|translate|>": 3,
             "<|transcribe|>": 4, "<|notimestamps|>": 5}

    def convert_tokens_to_ids(self, tok):
        return self.vocab[tok]


def test_prompt_ids():
    tok = FakeTokenizer()
    assert _prompt_ids(tok, "auto", "transcribe") == [1]
    assert _prompt_ids(tok, "hi", "translate") == [1, 2, 3, 5]


# --- NPU decoder contract (mirrors the AI Hub whisper_small precompiled_qnn_onnx I/O) ---

class _Spec:
    def __init__(self, shape):
        self.shape = shape


class FakeEncoder:
    def __call__(self, feed):
        assert feed["input_features"].shape == (1, 80, 3000)
        return {f"{kv}_cache_cross_{i}": np.full((2, 1, 4, 6) if kv == "k" else (2, 1, 6, 4), i, np.float16)
                for i in range(2) for kv in "kv"}


class FakeDecoder:
    """Emits a scripted token sequence and checks every feed against the contract."""

    N_CTX = 8

    def __init__(self, script):
        self.script, self.step, self.fed_tokens = script, 0, []
        self.inputs = {"input_ids": _Spec([1, 1]), "position_ids": _Spec([1]),
                       "attention_mask": _Spec([1, 1, 1, self.N_CTX])}
        for i in range(2):
            self.inputs[f"k_cache_self_{i}_in"] = _Spec([2, 1, 4, self.N_CTX - 1])
            self.inputs[f"v_cache_self_{i}_in"] = _Spec([2, 1, self.N_CTX - 1, 4])
            self.inputs[f"k_cache_cross_{i}"] = _Spec([2, 1, 4, 6])
            self.inputs[f"v_cache_cross_{i}"] = _Spec([2, 1, 6, 4])

    def dtype(self, name):
        return np.int32 if name.endswith("_ids") else np.float16

    def __call__(self, feed):
        assert set(feed) == set(self.inputs), "every declared input must be fed by name"
        for name, spec in self.inputs.items():
            assert list(feed[name].shape) == spec.shape, name
        n = self.step
        assert int(feed["position_ids"][0]) == n
        mask = feed["attention_mask"].reshape(-1)
        assert (mask[self.N_CTX - n - 1:] == 0).all() and (mask[: self.N_CTX - n - 1] == -100).all()
        # the self cache written at step n-1 must come back at step n
        assert float(feed["k_cache_self_0_in"].flat[0]) == float(n)
        self.fed_tokens.append(int(feed["input_ids"][0, 0]))
        logits = np.zeros((1, 50, 1, 1), np.float16)
        logits[0, self.script[n], 0, 0] = 1
        self.step += 1
        out = {f"{kv}_cache_self_{i}_out": np.full(self.inputs[f"{kv}_cache_self_{i}_in"].shape, n + 1, np.float16)
               for i in range(2) for kv in "kv"}
        out["logits"] = logits  # logits is the LAST output in the real model
        return out


def test_greedy_decode_follows_aihub_contract():
    from vaani.asr import greedy_decode

    eos = 9
    prompt = [1, 2, 4, 5]  # <sot> <lang> <task> <notimestamps>
    # predictions at steps 0-2 are ignored (prompt is forced); then 21, 22, EOS
    decoder = FakeDecoder(script=[7, 7, 7, 21, 22, eos, 7])
    tokens = greedy_decode(FakeEncoder(), decoder, np.zeros((1, 80, 3000), np.float32), prompt, eos)
    assert tokens == [1, 2, 4, 5, 21, 22, eos]
    assert decoder.fed_tokens == [1, 2, 4, 5, 21, 22]


def test_greedy_decode_stops_at_context_limit():
    from vaani.asr import greedy_decode

    decoder = FakeDecoder(script=[3] * 8)
    tokens = greedy_decode(FakeEncoder(), decoder, np.zeros((1, 80, 3000), np.float32), [1], eos=9)
    assert len(tokens) == FakeDecoder.N_CTX  # prompt + 7 generated, never overruns the mask
