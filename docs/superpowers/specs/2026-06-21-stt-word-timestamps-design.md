# STT per-word timestamps via forced alignment — design

**Date:** 2026-06-21
**Status:** approved (pending written-spec review)
**Scope:** Voxtral STT backend only (`named_pipes/stt/server.py`, `named_pipes/stt/voxtral/stream.py`)

## Goal

Emit **per-word absolute timestamps** ("the wall-clock time the user said each word")
in the STT server's `speech` messages, by running a forced aligner over the audio of
the current utterance as it is transcribed by Voxtral.

## Background / constraints

- The Voxtral backend (`stt/voxtral/stream.py`) captures the mic at **16 kHz mono
  float32** and streams sub-word **tokens** to the server via `on_token(text)`, with
  VAD lifecycle callbacks `on_speaking_started()` / `on_speaking_finished()`. The
  server (`stt/server.py`) accumulates a running transcript and broadcasts `speech`,
  `speech_start`, `speech_end`, `token`, and `state_changed` events.
- The forced aligner is **Qwen3-ForcedAligner-0.6B**, accessed through the already-present
  **`mlx-audio`** library (MLX, Apple-Silicon native — avoids the PyTorch `qwen-asr`
  path and its `transformers==4.57.6` pin conflict):
  ```python
  from mlx_audio.stt.utils import load_model
  model = load_model("mlx-community/Qwen3-ForcedAligner-0.6B-4bit")
  result = model.generate(audio_np_16k_f32, text="hello world", language="English")
  for item in result:        # ForcedAlignItem(text, start_time, end_time)
      item.text, item.start_time, item.end_time   # seconds, RELATIVE to passed audio
  ```
  - Accepts a numpy array directly (no file I/O); 16 kHz mono float32 matches the
    Voxtral capture exactly.
  - **Non-autoregressive**: aligns a whole `(audio, text)` pair in a single forward
    pass. It cannot time an isolated word in isolation — "the new word's timing" is
    obtained by re-aligning the utterance-so-far and reading the latest word(s).
  - **Intrinsic resolution is 80 ms** (`timestamp_segment_time = 80.0`; timestamps are
    multiples of 80 ms, returned as `round(ms/1000, 3)` seconds). Benchmarked ~43 ms
    avg error. This is a hard limit of *this* model.

## Decisions (confirmed with user)

1. **Trigger:** re-align the utterance-so-far on **each word boundary**, in a dedicated
   background thread, **coalesced** (≤1 alignment in flight; boundaries arriving during
   a run collapse into a single follow-up), **plus a final authoritative align at
   `speech_end`**.
2. **Opt-in:** new `STTConfig.align: bool = False`. When false, behaviour is unchanged.
3. **Timestamps:** absolute **Unix epoch seconds**, `float`, rounded to **3 decimals
   (millisecond representation)**. The absolute anchor is **sample-accurate**
   (sub-millisecond) so the pipeline adds no avoidable error on top of the model's
   80 ms intrinsic granularity.
4. **MLX concurrency risk** (Voxtral decode thread + aligner thread both submit Metal
   work): primary design is a dedicated alignment thread; if it proves unstable in
   testing, the documented fallback is to isolate the aligner in a subprocess. Validated
   empirically, not assumed.

## Architecture

### New module: `named_pipes/stt/aligner.py`

A self-contained, dependency-injectable wrapper. No threading, no absolute-time logic —
pure and unit-testable.

```python
class ForcedAligner:
    def __init__(self, model_id="mlx-community/Qwen3-ForcedAligner-0.6B-4bit",
                 language="English"): ...
    def load(self) -> None:               # lazy; raises if model/lib unavailable
        ...
    @property
    def available(self) -> bool: ...
    def align(self, audio_16k_f32: np.ndarray, text: str) -> list[WordTiming]:
        """Return RELATIVE-second word timings (start/end rounded to ms)."""
```

`WordTiming` is a small dataclass `{word: str, start: float, end: float}` (relative
seconds). The server converts to absolute.

### `named_pipes/stt/voxtral/stream.py` (minimal additions)

- **Sample-accurate wall-clock anchor.** In the existing `callback(indata, frames,
  time_info, status)`, on the first callback map global sample 0 to wall-clock using
  PortAudio's `time_info` (`wall0 = time.time() - (time_info.currentTime -
  time_info.inputBufferAdcTime)`), and maintain a running captured-sample counter. The
  wall-clock time of global sample `k` is `wall0 + k / 16000`. Fallback if ADC times are
  unavailable: `time.time()` at onset minus the pre-roll duration.
- **`on_speaking_started(abs_start: float)`** — pass the absolute wall-clock time of the
  utterance's first sample (the first **pre-roll** sample, since pre-roll is prepended
  to the utterance audio).
- **`on_audio(chunk: np.ndarray)`** — deliver the utterance's speech samples (pre-roll
  included in the onset call) to the server as they are routed to `pending_audio`, so the
  server owns the per-utterance audio buffer.
- All new callbacks are optional (default no-op) to preserve existing call sites.

### `named_pipes/stt/server.py` (orchestration)

- New `STTConfig` fields: `align: bool = False`, `align_language: str = "English"`,
  `align_model: str = "mlx-community/Qwen3-ForcedAligner-0.6B-4bit"`.
- Constructor accepts an optional injected aligner (`aligner: ForcedAligner | None`) for
  testing; otherwise constructs one when `align` is true.
- Per-utterance state: `_utt_audio: np.ndarray`, `_utt_abs_start: float`, transcript text.
- **Word-boundary detection:** in `_on_token`, append token text to the transcript; a
  boundary occurs when an incoming token's decoded text starts with a space (SentencePiece
  word-initial marker) and the buffer is non-empty (plus the very first token). The whole
  current transcript is passed to the aligner regardless — the aligner does its own word
  tokenisation; boundary detection is only the *trigger/throttle*.
- **Coalesced alignment worker:** a single worker thread with a one-slot "pending job"
  (latest `(audio_snapshot, text, abs_start)` wins). On each boundary, set pending; the
  worker runs `aligner.align(...)`, converts each `WordTiming` to absolute
  (`start' = round(abs_start + start, 3)`, same for end), and emits an updated `speech`
  event with a `words` array. `speech_end` enqueues a final job over the full utterance.
- **Buffer lifecycle:** `on_speaking_started` clears `_utt_audio`/sets `_utt_abs_start`;
  `on_audio` appends; final align at `speech_end`; buffer released afterward.

### Data flow

```
mic → stream.py (Voxtral decode + VAD, worker thread)
  ├─ on_speaking_started(abs_start) → server: set anchor, clear utt buffer
  ├─ on_audio(chunk)                → server: append to utt buffer
  ├─ on_token(text)                 → server: append transcript; on word
  │                                    boundary → set coalesced align job
  └─ on_speaking_finished()         → server: emit speech_end; enqueue final align

alignment thread (coalesced, ≤1 in flight):
  job(audio_snapshot, text, abs_start)
    → ForcedAligner.align(audio, text)  # relative seconds
    → words = [{word, start: round(abs_start+s,3), end: round(abs_start+e,3)}]
    → emit speech {text, words}
```

## Message / interface change

The `speech` event gains an optional `words` field:

```json
{"event": "speech",
 "text": "testing one two",
 "words": [{"word": "testing", "start": 1750540000.080, "end": 1750540000.480},
           {"word": "one",     "start": 1750540000.560, "end": 1750540000.800},
           {"word": "two",     "start": 1750540000.880, "end": 1750540001.200}]}
```

- `start`/`end` are absolute Unix epoch seconds (float, ms precision).
- Add the `words` field to the `speech` `EventSpec` in `named_pipes/interfaces/stt.py`
  (a list field; document the element shape in its description).
- `examples/stt_client.py` prints word timings when present.
- When `align` is false or the aligner is unavailable, `speech` is emitted **without**
  `words` (unchanged behaviour).

## Error handling / graceful degradation

- Aligner load failure (model not downloaded, `mlx-audio` import error, etc.): log once,
  continue transcription normally, emit `speech` without `words`. Never crash STT.
- Per-alignment exception: caught and logged; that `speech` omits `words`.
- Skip alignment for empty transcript or audio shorter than a small threshold.
- Mismatch between aligner word count and our transcript: trust the aligner's items (it
  tokenises the text itself).

## Dependencies

- No new pip dependencies: `mlx-audio` is already a dependency (darwin). The aligner is
  an optional *runtime model*, not a package.
- Document the model id `mlx-community/Qwen3-ForcedAligner-0.6B-4bit` with an
  `hf download <id>` hint, and add a cache-presence check that produces a clear message
  when `align=True` but the model is missing (degrade gracefully, do not crash).

## Testing

- **Pure unit tests (no model):**
  - word-boundary detection over token sequences (leading-space heuristic, first token,
    punctuation).
  - relative→absolute conversion + ms rounding.
  - coalescing logic: with a stub aligner, multiple rapid boundaries produce ≤1 in-flight
    align and a final align at `speech_end`.
- **Aligner integration test:** gated on model availability (skip if not downloaded) —
  feed a short known clip + text, assert monotonically increasing relative times and
  reasonable values.
- **Server integration test:** inject a fake aligner, drive `on_speaking_started` /
  `on_audio` / `on_token` / `on_speaking_finished`, assert `speech` messages carry the
  expected absolute `words` and that the final align fires at `speech_end`.

## Risks & open items

- **MLX/Metal cross-thread stability** (decode thread + align thread). Mitigation:
  coalescing; subprocess isolation as documented fallback if unstable. Validate during
  implementation.
- **80 ms model resolution** is a hard limit of Qwen3-ForcedAligner. Future option for
  finer (~20 ms) timing: a CTC-based aligner (`mlx-audio` ships `wav2vec`/`mms`/
  `lasr_ctc`). Out of scope here.
- **Latency/contention** of per-word re-alignment on longer utterances (each pass is a
  full-utterance forward). Coalescing bounds it; acceptable for the expected
  short-utterance use case.

## Out of scope

- Word timestamps for the Moonshine backend (it exposes native `WordTiming` via
  `line.words`; a separate, simpler follow-up).
- Finer-than-80 ms alignment / alternative aligner models.
