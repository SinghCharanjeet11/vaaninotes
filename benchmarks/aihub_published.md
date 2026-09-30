# Qualcomm AI Hub published performance (models used by VaaniNotes)

Source: Qualcomm AI Hub Models v0.63.0, `qai-hub-models perf <model>`
(measured by Qualcomm on hosted reference devices, all on the Hexagon **NPU**).
Reproduce with `.venv\Scripts\qai-hub-models perf whisper_small`.

## Speech: Whisper-Small (`whisper_small`, float, 241M params, 99 languages)

| Device | Runtime | Encoder (per 30 s audio) | Decoder (per token) |
|---|---|---|---|
| Snapdragon X Elite CRD | Precompiled QAIRT ONNX *(used by VaaniNotes)* | 117.1 ms | 10.47 ms |
| Snapdragon X Elite CRD | QAIRT Context Binary | 118.3 ms | 11.11 ms |
| Snapdragon X2 Elite CRD | Precompiled QAIRT ONNX *(used by VaaniNotes)* | 52.9 ms | 6.28 ms |

Estimated transcription cost for 30 s of speech (~80 tokens) on X Elite:
117 ms + 80 × 10.5 ms ≈ **1.0 s**, so roughly **30× faster than real time**,
a 1-hour lecture in about 2 minutes.

## Notes LLM: Qwen3-4B-Instruct-2507 (`qwen3_4b_instruct_2507`)

| Device | Runtime | Precision | Context | Decode | Prefill | Time to first token |
|---|---|---|---|---|---|---|
| Snapdragon X Elite CRD | GenieX (QAIRT) *(default)* | w4a16 | 4096 | 22.6 tok/s | 1297 tok/s | 0.10–3.2 s |
| Snapdragon X Elite CRD | GenieX (llama.cpp) | q4_0 | 4096 | 6.1 tok/s | 367 tok/s | — |

## Alternative LLM: Llama-v3.2-3B-Instruct (`llama_v3_2_3b_instruct`; officially supports Hindi)

| Device | Runtime | Precision | Decode | Prefill |
|---|---|---|---|---|
| Snapdragon X Elite CRD | GenieX (QAIRT) | w4a16 | 19.8 tok/s | 989 tok/s |
| Snapdragon X2 Elite CRD | GenieX (QAIRT) | w4a16 | 42.8 tok/s | 2069 tok/s |

Llama 3.2 must be exported by the user (`qai-hub-models export llama_v3_2_3b_instruct`)
because of its license; Qwen3-4B-Instruct is available directly through GenieX.
