"""Transcript -> study / meeting notes, entirely on-device."""

from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from .asr import Transcript, _fmt
from .config import LANGUAGES
from .llm import ExtractiveLLM

SYSTEM = (
    "You are VaaniNotes, a private note-taking assistant running fully offline on a "
    "Snapdragon laptop. Use ONLY information from the transcript. Be concise and "
    "concrete. Write your entire answer in {lang}."
)

PROMPTS = {
    "condense": "Rewrite this transcript excerpt as 5-8 short factual bullet points.\n\n"
                "Transcript excerpt:\n{text}",
    "summary": "Write a clear summary (one paragraph, at most 120 words) of this "
               "lecture/meeting.\n\nTranscript:\n{text}",
    "key_points": "List the 5-8 most important key points as '- ' bullets.\n\n"
                  "Transcript:\n{text}",
    "action_items": "List every action item, task, deadline, homework or decision as "
                    "'- ' bullets (include who/when if stated). If there are none, reply "
                    "exactly '- None mentioned'.\n\nTranscript:\n{text}",
    "flashcards": "Create 5 revision flashcards from this content. Format each exactly as:\n"
                  "Q: <question>\nA: <short answer>\n\nTranscript:\n{text}",
    "ask": "Answer the question using only these timestamped transcript excerpts. Cite "
           "timestamps like [mm:ss]. If the answer is not in them, say so.\n\n"
           "Excerpts:\n{text}\n\nQuestion: {question}",
}

SECTIONS = {
    "summary": "Summary",
    "key_points": "Key points",
    "action_items": "Action items & deadlines",
    "flashcards": "Flashcards",
}

_ACTION_CUES = re.compile(
    r"\b(will|should|must|need to|have to|deadline|due|submit|assignment|homework|"
    r"next (week|class|meeting)|by (monday|tuesday|wednesday|thursday|friday|tomorrow))\b"
    r"|करना|करें|होगा|जमा",
    re.I,
)


_QUESTION_WORDS = {"when", "what", "where", "which", "who", "whom", "why", "how", "does",
                   "did", "the", "are", "was", "is", "can", "tell"}


@dataclass
class Notes:
    transcript: Transcript
    output_language: str
    llm_name: str
    sections: dict[str, str] = field(default_factory=dict)
    llm_seconds: float = 0.0

    def to_markdown(self) -> str:
        t = self.transcript
        lang = LANGUAGES.get(t.language, t.language)
        lines = [
            "# VaaniNotes",
            f"_Generated {datetime.now():%d %b %Y, %H:%M} · fully offline_",
            "",
            f"- **Audio:** {_fmt(t.audio_seconds)} · spoken language: {lang}",
            f"- **Speech model:** {t.backend} ({t.elapsed_seconds:.1f} s, "
            f"{1 / max(t.realtime_factor, 1e-6):.1f}x real-time)",
            f"- **Notes model:** {self.llm_name} ({self.llm_seconds:.1f} s)",
            "",
        ]
        for key, title in SECTIONS.items():
            if key in self.sections:
                lines += [f"## {title}", "", self.sections[key].strip(), ""]
        lines += ["## Transcript", "", t.timestamped(), ""]
        return "\n".join(lines)


def split_text(text: str, max_chars: int) -> list[str]:
    """Split on sentence boundaries into pieces of at most ~max_chars."""
    sents = re.split(r"(?<=[.!?।])\s+", text)
    chunks, cur = [], ""
    for s in sents:
        if cur and len(cur) + len(s) + 1 > max_chars:
            chunks.append(cur)
            cur = ""
        while len(s) > max_chars:  # one enormous "sentence" (no punctuation)
            chunks.append(s[:max_chars])
            s = s[max_chars:]
        cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur)
    return chunks


class NotesEngine:
    def __init__(self, llm, chunk_chars: int = 6000):
        self.llm = llm
        self.chunk_chars = chunk_chars

    @property
    def is_extractive(self) -> bool:
        return isinstance(self.llm, ExtractiveLLM)

    def _ask(self, kind: str, lang: str, max_tokens: int = 512, **kw) -> str:
        return self.llm.generate(SYSTEM.format(lang=lang), PROMPTS[kind].format(**kw),
                                 max_tokens=max_tokens)

    def condense(self, text: str, lang: str, progress=None, depth: int = 0) -> str:
        """Map step: long transcripts are condensed chunk-by-chunk to fit a 4K context."""
        chunks = split_text(text, self.chunk_chars)
        if len(chunks) == 1 or depth >= 3:
            return text[: self.chunk_chars]
        parts = []
        for i, c in enumerate(chunks):
            if progress:
                progress(i / len(chunks), f"Condensing part {i + 1}/{len(chunks)}")
            parts.append(self._ask("condense", lang, max_tokens=300, text=c))
        return self.condense("\n".join(parts), lang, progress, depth + 1)

    def build(self, transcript: Transcript, output_language: str = "English",
              sections: list[str] | None = None, progress=None, on_section=None) -> Notes:
        sections = sections or list(SECTIONS)
        notes = Notes(transcript, output_language, self.llm.name)
        t0 = time.perf_counter()
        if not transcript.text.strip():
            notes.sections = {k: "_No speech detected._" for k in sections}
            return notes

        if self.is_extractive:
            notes.sections = self._extractive(transcript.text, sections)
            if on_section:
                for key, value in notes.sections.items():
                    on_section(key, value)
        else:
            text = self.condense(transcript.text, output_language, progress)
            for i, key in enumerate(sections):
                if progress:
                    progress(i / len(sections), f"Writing {SECTIONS[key].lower()}")
                notes.sections[key] = self._ask(key, output_language, text=text)
                if on_section:
                    on_section(key, notes.sections[key])
        notes.llm_seconds = time.perf_counter() - t0
        return notes

    def _extractive(self, text: str, sections: list[str]) -> dict[str, str]:
        ex: ExtractiveLLM = self.llm
        out = {}
        if "summary" in sections:
            out["summary"] = " ".join(ex.rank(text, 4))
        if "key_points" in sections:
            out["key_points"] = "\n".join(f"- {s}" for s in ex.rank(text, 7))
        if "action_items" in sections:
            acts = [s for s in ex.sentences(text) if _ACTION_CUES.search(s)]
            out["action_items"] = "\n".join(f"- {s}" for s in acts[:10]) or "- None mentioned"
        if "flashcards" in sections:
            cards = [f"Q: {q}\nA: {a}" for q, a in ex.flashcards(text)]
            out["flashcards"] = "\n\n".join(cards) or "_Not enough content for flashcards._"
        return out

    def ask(self, transcript: Transcript, question: str, output_language: str = "English",
            k: int = 4) -> str:
        """Question answering over the transcript with keyword retrieval (RAG-lite)."""
        segs = [s for s in transcript.segments if s.text]
        if not segs:
            return "_No transcript yet._"
        q = {w for w in re.findall(r"\w+", question.lower())
             if len(w) > 2 and w not in ExtractiveLLM.STOP | _QUESTION_WORDS}

        def overlap(text: str) -> int:
            words = Counter(re.findall(r"\w+", text.lower()))
            return sum(1 for w in q if words[w])

        if self.is_extractive:
            # Answer with the best-matching sentences, each with its timestamp.
            sents = [(s.start, x) for s in segs for x in ExtractiveLLM.sentences(s.text)]
            best = sorted(sents, key=lambda p: overlap(p[1]), reverse=True)[:2]
            if not best or overlap(best[0][1]) == 0:
                return "_I couldn't find that in the recording._"
            return "\n".join(f"- [{_fmt(t)}] {x}" for t, x in sorted(best) if overlap(x))

        top = sorted(sorted(segs, key=lambda s: overlap(s.text), reverse=True)[:k],
                     key=lambda s: s.start)
        context = "\n".join(f"[{_fmt(s.start)}] {s.text}" for s in top)
        return self._ask("ask", output_language, max_tokens=400, text=context, question=question)
