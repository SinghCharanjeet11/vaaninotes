"""Language-model backends.

``LocalServerLLM`` talks to an OpenAI-compatible server on localhost. On a
Snapdragon PC that is Qualcomm GenieX (``geniex serve``), which runs AI Hub
LLMs such as Qwen3-4B-Instruct on the Hexagon NPU. Ollama / LM Studio work too.

``ExtractiveLLM`` needs no model at all: it ranks sentences by term frequency.
It keeps the app useful on any machine and is the automatic fallback.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter

import requests

from .config import LOCAL_LLM_SERVERS, Config

_THINK = re.compile(r"<think>.*?</think>", re.S)


class LocalServerLLM:
    def __init__(self, base_url: str, model: str, timeout: float, label: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.name = f"{model} via {label}"
        self.last_stats: dict[str, float] = {}

    def generate(self, system: str, user: str, max_tokens: int = 512) -> str:
        t0 = time.perf_counter()
        r = requests.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": self.model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "max_tokens": max_tokens,
                "temperature": 0.2,
                "stream": False,
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        body = r.json()
        text = _THINK.sub("", body["choices"][0]["message"]["content"]).strip()
        elapsed = time.perf_counter() - t0
        tokens = (body.get("usage") or {}).get("completion_tokens") or max(1, len(text) // 4)
        self.last_stats = {"seconds": elapsed, "completion_tokens": tokens,
                           "tokens_per_second": tokens / max(elapsed, 1e-6)}
        return text


class ExtractiveLLM:
    """Model-free fallback: frequency-based sentence ranking (works for any script)."""

    name = "Built-in extractive engine (no LLM)"
    last_stats: dict[str, float] = {}

    @staticmethod
    def sentences(text: str) -> list[str]:
        parts = re.split(r"(?<=[.!?।])\s+", text.strip())
        return [p.strip() for p in parts if len(p.split()) >= 4]

    @staticmethod
    def _words(text: str) -> list[str]:
        return [w for w in re.findall(r"\w+", text.lower()) if len(w) > 3]

    def rank(self, text: str, k: int) -> list[str]:
        sents = self.sentences(text)
        if not sents:
            return [text.strip()] if text.strip() else []
        freq = Counter(self._words(text))
        top = max(freq.values(), default=1)

        def score(s: str) -> float:
            ws = self._words(s)
            return sum(freq[w] / top for w in ws) / math.sqrt(len(ws) or 1)

        best = sorted(range(len(sents)), key=lambda i: score(sents[i]), reverse=True)[:k]
        return [sents[i] for i in sorted(best)]

    STOP = {
        "this", "that", "with", "have", "from", "they", "will", "what", "there", "their",
        "which", "about", "would", "these", "into", "were", "been", "then", "than", "when",
        "your", "also", "just", "like", "because", "called", "going", "today", "please",
        "some", "many", "most", "more", "very", "here", "where", "each", "only", "other",
        "such", "them", "does", "done", "make", "made", "take", "place", "thank", "everyone",
        "morning", "next", "week", "class", "learn", "know", "think", "really", "okay",
        "right", "well", "should", "could", "must", "need", "happens", "main", "simple",
    }

    def keywords(self, text: str, k: int = 8) -> list[str]:
        freq = Counter(w for w in self._words(text) if w not in self.STOP and not w.isdigit())
        return [w for w, _ in freq.most_common(k)]

    def flashcards(self, text: str, n: int = 5) -> list[tuple[str, str]]:
        """Cloze cards: one per key sentence, blanking its most central keyword."""
        central = self.keywords(text, 40)
        rank = {w: i for i, w in enumerate(central)}
        cards, used = [], set()
        for sent in self.rank(text, n * 3):
            words = {w for w in self._words(sent) if w in rank and w not in used}
            if not words:
                continue
            answer = min(words, key=rank.get)
            used.add(answer)
            m = re.search(rf"\b{re.escape(answer)}\b", sent, re.I)
            cards.append((sent[:m.start()] + "_____" + sent[m.end():], m.group(0)))
            if len(cards) == n:
                break
        return cards


def _probe(base_url: str) -> list[str] | None:
    try:
        r = requests.get(f"{base_url.rstrip('/')}/models", timeout=1.5)
        r.raise_for_status()
        return [m.get("id", "") for m in r.json().get("data", [])]
    except (requests.RequestException, ValueError):
        return None


def load_llm(cfg: Config):
    choice = cfg.llm_backend.lower()
    if choice in ("extractive", "none", "off"):
        return ExtractiveLLM()

    if cfg.llm_base_url:
        servers = {"custom server": cfg.llm_base_url}
    elif choice in LOCAL_LLM_SERVERS:
        servers = {choice: LOCAL_LLM_SERVERS[choice]}
    else:
        servers = LOCAL_LLM_SERVERS

    for label, url in servers.items():
        models = _probe(url)
        if models is None:
            continue
        model = cfg.llm_model
        if models and model not in models:
            model = models[0]  # use whatever the local server has loaded
        return LocalServerLLM(url, model, cfg.llm_timeout_s,
                              "GenieX · Hexagon NPU" if label == "geniex" else label)

    if choice != "auto":
        raise RuntimeError(f"No local LLM server reachable for backend '{choice}'.")
    print("[vaani] No local LLM server found; using the extractive engine.")
    return ExtractiveLLM()
