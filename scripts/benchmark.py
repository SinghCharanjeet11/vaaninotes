"""Benchmark speech recognition on the Hexagon NPU vs. the CPU on this machine.

    python scripts/benchmark.py samples/lecture_demo.wav [--runs 3]

Writes benchmarks/local_results.json and benchmarks/local_results.md.
Run it on the Snapdragon laptop to produce the NPU-vs-CPU numbers for the README.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vaani import device  # noqa: E402
from vaani.asr import CpuWhisperASR, NpuWhisperASR, npu_ready  # noqa: E402
from vaani.audio import duration_s, load_audio  # noqa: E402
from vaani.config import Config  # noqa: E402


def bench(asr, audio, runs: int) -> dict:
    asr.transcribe(audio[: 16000 * 5])  # warm-up (graph finalisation, caches)
    times, text = [], ""
    for _ in range(runs):
        t = asr.transcribe(audio)
        times.append(t.elapsed_seconds)
        text = t.text
    best = min(times)
    return {
        "backend": asr.name,
        "runs_s": [round(x, 3) for x in times],
        "median_s": round(statistics.median(times), 3),
        "speed_x_realtime": round(duration_s(audio) / best, 2),
        "transcript_preview": text[:160],
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("audio", nargs="?", default=str(ROOT / "samples" / "lecture_demo.wav"))
    p.add_argument("--runs", type=int, default=3)
    args = p.parse_args()

    cfg = Config()
    audio = load_audio(args.audio)
    results = {"date": datetime.now().isoformat(timespec="seconds"),
               "device": device.summary(), "audio_seconds": round(duration_s(audio), 1),
               "results": []}

    ok, why = npu_ready(cfg)
    if ok:
        print("Benchmarking NPU ...")
        results["results"].append(bench(NpuWhisperASR(cfg), audio, args.runs))
    else:
        print(f"Skipping NPU: {why}")
    try:
        print("Benchmarking CPU ...")
        results["results"].append(bench(CpuWhisperASR(cfg), audio, args.runs))
    except ImportError as e:
        print(f"Skipping CPU baseline: {e}")

    out = ROOT / "benchmarks"
    out.mkdir(exist_ok=True)
    (out / "local_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    lines = [f"# Local benchmark ({results['date']})", "",
             *(f"- **{k}:** {v}" for k, v in results["device"].items()),
             f"- **Audio:** {results['audio_seconds']} s", "",
             "| Backend | Median time (s) | Speed vs real-time |", "|---|---|---|"]
    lines += [f"| {r['backend']} | {r['median_s']} | {r['speed_x_realtime']}x |"
              for r in results["results"]]
    if len(results["results"]) == 2:
        npu, cpu = results["results"]
        lines += ["", f"**NPU speed-up over CPU: {cpu['median_s'] / npu['median_s']:.1f}x**"]
    (out / "local_results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
