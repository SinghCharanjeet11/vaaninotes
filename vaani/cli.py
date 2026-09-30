"""Command-line interface: python -m vaani.cli lecture.wav --lang hi --notes-lang English"""

from __future__ import annotations

import argparse
from pathlib import Path

from .asr import load_asr
from .audio import load_audio
from .config import LANGUAGES, Config
from .llm import load_llm
from .pipeline import NotesEngine


def main() -> None:
    p = argparse.ArgumentParser(description="VaaniNotes: offline lecture/meeting notes")
    p.add_argument("audio", help="Audio file (.wav; other formats need ffmpeg)")
    p.add_argument("--lang", default="auto", choices=list(LANGUAGES), help="Spoken language")
    p.add_argument("--translate", action="store_true", help="Translate speech to English")
    p.add_argument("--notes-lang", default="English", help="Language of the generated notes")
    p.add_argument("--ask", help="Ask a question about the recording")
    p.add_argument("-o", "--out", help="Output markdown path")
    args = p.parse_args()

    cfg = Config()
    asr, llm = load_asr(cfg), load_llm(cfg)
    print(f"Speech: {asr.name}\nNotes:  {llm.name}\n")

    transcript = asr.transcribe(load_audio(args.audio), args.lang,
                                "translate" if args.translate else "transcribe")
    engine = NotesEngine(llm, cfg.llm_chunk_chars)
    notes = engine.build(transcript, args.notes_lang)
    md = notes.to_markdown()

    out = Path(args.out) if args.out else cfg.output_dir / (Path(args.audio).stem + "_notes.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(md)
    if args.ask:
        print("\n## Answer\n" + engine.ask(transcript, args.ask, args.notes_lang))
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
