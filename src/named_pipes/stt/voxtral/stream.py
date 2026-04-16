import argparse
import collections
import enum
import threading
import time
from typing import Callable, Optional

import mlx.core as mx
import numpy as np
import sounddevice as sd
import torch
from mistral_common.tokens.tokenizers.base import SpecialTokenPolicy

from . import _build_prompt_tokens, load_model
from .audio import SAMPLES_PER_TOKEN, log_mel_spectrogram_step
from .cache import RotatingKVCache

N_LEFT_PAD_TOKENS = 32
N_RIGHT_PAD_TOKENS = 17
VAD_CHUNK_SIZE = 512  # samples per Silero VAD inference call (32 ms at 16 kHz)
VAD_THRESHOLD = 0.5  # speech probability cutoff
PRE_ROLL_BLOCKS = (
    4  # sounddevice blocks to prepend on speech onset (4 × 80 ms = ~320 ms)
)


class VADState(enum.Enum):
    WAITING = "waiting"
    SPEAKING = "speaking"


def load_vad():
    """Load Silero VAD model from torch.hub (cached after first download)."""
    vad_model, _ = torch.hub.load(
        "snakers4/silero-vad", "silero_vad", verbose=False, trust_repo=True
    )
    vad_model.eval()
    return vad_model


def _run_vad_chunks(
    vad_buf: np.ndarray,
    new_audio: np.ndarray,
    vad_model,
) -> tuple[np.ndarray, list[float]]:
    """Consume new_audio into vad_buf; run VAD on every complete VAD_CHUNK_SIZE slice.

    Returns (remaining_vad_buf, list_of_speech_probabilities).
    No-op if combined length < VAD_CHUNK_SIZE.
    """
    buf = np.append(vad_buf, new_audio)
    probs: list[float] = []
    while len(buf) >= VAD_CHUNK_SIZE:
        chunk = buf[:VAD_CHUNK_SIZE]
        buf = buf[VAD_CHUNK_SIZE:]
        with torch.no_grad():
            prob = vad_model(torch.from_numpy(chunk), 16000).item()
        probs.append(prob)
    return buf, probs


def stream_transcribe(
    model_path: str = "mlx-community/Voxtral-Mini-4B-Realtime-6bit",
    temperature: float = 0.0,
    vad_onset: int = 2,
    vad_offset: int = 32,
    notify_on_eos: bool = False,
    on_speaking_started=lambda: print("\non_speaking_started", flush=True),
    on_speaking_finished=lambda: print("on_speaking_finished", flush=True),
    on_token: Optional[Callable[[str], None]] = None,
):
    model, sp, config = load_model(model_path)

    prompt_tokens, n_delay_tokens = _build_prompt_tokens(sp)
    prefix_len = len(prompt_tokens)
    eos_token_id = sp.eos_id

    t_cond = model.time_embedding(mx.array([n_delay_tokens], dtype=mx.float32))
    mx.eval(t_cond)

    prompt_ids = mx.array([prompt_tokens])
    text_embeds = model.language_model.embed(prompt_ids)[0]  # [prefix_len, 3072]
    mx.eval(text_embeds)

    n_layers = len(model.language_model.layers)
    sliding_window = 8192

    print("Loading VAD...", flush=True)
    vad_model = load_vad()

    def sample(logits):
        if temperature <= 0:
            return mx.argmax(logits[0, -1:], axis=-1).squeeze()
        return mx.random.categorical(logits[0, -1:] / temperature).squeeze()

    def decode_steps(embeds, n_to_decode):
        """Decode n_to_decode positions from embeds[0..n_to_decode-1].

        Returns (n_consumed, hit_eos). On EOS, cache and y are reset.
        """
        nonlocal cache, y

        for i in range(n_to_decode):
            token_embed = model.language_model.embed(y.reshape(1, 1))[0, 0]
            step_embed = (embeds[i] + token_embed)[None, None, :]
            logits = model.decode(step_embed, t_cond, mask=None, cache=cache)
            next_y = sample(logits)
            mx.async_eval(next_y)

            token_id = y.item()
            if token_id == eos_token_id:
                if on_token is None:
                    print(flush=True)
                cache = None
                y = None
                return i, True

            text = sp.decode([token_id], special_token_policy=SpecialTokenPolicy.IGNORE)
            if on_token is not None:
                on_token(text)
            else:
                print(text, end="", flush=True)

            if i > 0 and i % 256 == 0:
                mx.clear_cache()

            y = next_y

        return n_to_decode, False

    # Audio buffer and lock
    lock = threading.Lock()
    audio_buf = np.zeros(0, dtype=np.float32)

    def callback(indata, frames, time_info, status):
        nonlocal audio_buf
        with lock:
            audio_buf = np.append(audio_buf, indata[:, 0])

    # Decoder state
    cache = None
    y = None

    # Incremental encoder state
    audio_tail = None  # mel STFT overlap (240 samples)
    conv1_tail = None  # conv1 kernel overlap (2 frames)
    conv2_tail = None  # conv2 kernel overlap (1 frame)
    encoder_cache = None  # KV cache for encoder transformer layers
    ds_buf = None  # partial downsample group

    # Bounded buffers and counters
    pending_audio = np.zeros(0, dtype=np.float32)
    audio_embeds = None
    n_audio_samples_fed = 0
    n_total_decoded = 0
    first_cycle = True
    prefilled = False

    # VAD state
    vad_state = VADState.WAITING
    speech_frame_count = 0
    silence_frame_count = 0
    vad_buf = np.zeros(0, dtype=np.float32)
    pre_roll: collections.deque = collections.deque(maxlen=PRE_ROLL_BLOCKS)

    def reset_all_state():
        nonlocal audio_tail, conv1_tail, conv2_tail, encoder_cache, ds_buf
        nonlocal pending_audio, audio_embeds, n_audio_samples_fed
        nonlocal n_total_decoded, first_cycle, prefilled
        audio_tail = None
        conv1_tail = None
        conv2_tail = None
        encoder_cache = None
        ds_buf = None
        pending_audio = np.zeros(0, dtype=np.float32)
        audio_embeds = None
        n_audio_samples_fed = 0
        n_total_decoded = 0
        first_cycle = True
        prefilled = False

    def flush_and_reset():
        """Flush remaining audio through Voxtral, decode, then reset all state."""
        nonlocal cache, y, vad_state, speech_frame_count, silence_frame_count
        nonlocal vad_buf, pending_audio, audio_embeds

        if cache is not None and y is not None:
            right_pad = np.zeros(
                N_RIGHT_PAD_TOKENS * SAMPLES_PER_TOKEN, dtype=np.float32
            )
            flush_chunk = np.concatenate([pending_audio, right_pad])
            mel, _ = log_mel_spectrogram_step(flush_chunk, audio_tail)
            new_embeds, _, _, _, _ = model.encode_step(
                mel, conv1_tail, conv2_tail, encoder_cache, ds_buf
            )
            if new_embeds is not None:
                mx.eval(new_embeds)
                final_embeds = (
                    mx.concatenate([audio_embeds, new_embeds])
                    if audio_embeds is not None
                    else new_embeds
                )
                decode_steps(final_embeds, final_embeds.shape[0])

            if y is not None:
                token_id = y.item()
                if token_id != eos_token_id:
                    text = sp.decode(
                        [token_id], special_token_policy=SpecialTokenPolicy.IGNORE
                    )
                    if on_token is not None:
                        on_token(text)
                    else:
                        print(text, end="", flush=True)
            if on_token is None:
                print(flush=True)
            cache = None
            y = None

        reset_all_state()
        vad_state = VADState.WAITING
        speech_frame_count = 0
        silence_frame_count = 0
        vad_buf = np.zeros(0, dtype=np.float32)
        pre_roll.clear()
        vad_model.reset_states()

    print("Listening... (Ctrl+C to stop)\n", flush=True)

    stream = sd.InputStream(
        samplerate=16000,
        channels=1,
        dtype="float32",
        blocksize=SAMPLES_PER_TOKEN,
        callback=callback,
    )
    stream.start()

    try:
        start_time = time.monotonic()
        warned_no_audio = False
        while True:
            # --- Drain mic ---
            with lock:
                new_audio = audio_buf
                audio_buf = np.zeros(0, dtype=np.float32)

            # --- VAD ---
            if len(new_audio) > 0:
                transition_to_speaking = False
                vad_buf, probs = _run_vad_chunks(vad_buf, new_audio, vad_model)

                for prob in probs:
                    if vad_state == VADState.WAITING:
                        if prob >= VAD_THRESHOLD:
                            speech_frame_count += 1
                            if speech_frame_count >= vad_onset:
                                vad_state = VADState.SPEAKING
                                speech_frame_count = 0
                                silence_frame_count = 0
                                transition_to_speaking = True
                                on_speaking_started()
                        else:
                            speech_frame_count = 0
                    else:  # SPEAKING
                        if prob < VAD_THRESHOLD:
                            silence_frame_count += 1
                            if silence_frame_count >= vad_offset:
                                flush_and_reset()  # resets vad_state to WAITING
                                on_speaking_finished()
                                transition_to_speaking = False
                        else:
                            silence_frame_count = 0

                # Route audio to pre-roll or pending_audio based on VAD state
                if vad_state == VADState.WAITING:
                    pre_roll.append(new_audio)
                else:  # SPEAKING
                    if transition_to_speaking and len(pre_roll) > 0:
                        pre_roll_audio = np.concatenate(list(pre_roll))
                        pending_audio = np.append(
                            pending_audio, np.concatenate([pre_roll_audio, new_audio])
                        )
                        pre_roll.clear()
                    else:
                        pending_audio = np.append(pending_audio, new_audio)
            else:
                # No audio yet — warn if mic silent for > 2 s
                # if not warned_no_audio and (time.monotonic() - start_time) > 2.0:
                #     warned_no_audio = True
                #     print(
                #         "Warning: No audio received. Check that your terminal app "
                #         "has microphone permission in System Settings > Privacy & "
                #         "Security > Microphone.",
                #         flush=True,
                #     )
                pass

            # --- Skip encode/decode if waiting for speech ---
            if vad_state == VADState.WAITING:
                time.sleep(0.02)
                continue

            # --- Encode new audio if we have at least one token's worth ---
            if first_cycle and len(pending_audio) >= SAMPLES_PER_TOKEN:
                left_pad = np.zeros(
                    N_LEFT_PAD_TOKENS * SAMPLES_PER_TOKEN, dtype=np.float32
                )
                n_feed = (len(pending_audio) // SAMPLES_PER_TOKEN) * SAMPLES_PER_TOKEN
                chunk = np.concatenate([left_pad, pending_audio[:n_feed]])
                pending_audio = pending_audio[n_feed:]
                n_audio_samples_fed += n_feed

                mel, audio_tail = log_mel_spectrogram_step(chunk, audio_tail)
                new_embeds, conv1_tail, conv2_tail, encoder_cache, ds_buf = (
                    model.encode_step(
                        mel, conv1_tail, conv2_tail, encoder_cache, ds_buf
                    )
                )
                if new_embeds is not None:
                    mx.eval(new_embeds)
                    audio_embeds = new_embeds
                first_cycle = False

            elif not first_cycle and len(pending_audio) >= SAMPLES_PER_TOKEN:
                n_feed = (len(pending_audio) // SAMPLES_PER_TOKEN) * SAMPLES_PER_TOKEN
                chunk = pending_audio[:n_feed]
                pending_audio = pending_audio[n_feed:]
                n_audio_samples_fed += n_feed

                mel, audio_tail = log_mel_spectrogram_step(chunk, audio_tail)
                new_embeds, conv1_tail, conv2_tail, encoder_cache, ds_buf = (
                    model.encode_step(
                        mel, conv1_tail, conv2_tail, encoder_cache, ds_buf
                    )
                )
                if new_embeds is not None:
                    mx.eval(new_embeds)
                    if audio_embeds is not None:
                        audio_embeds = mx.concatenate([audio_embeds, new_embeds])
                    else:
                        audio_embeds = new_embeds

            if audio_embeds is None:
                time.sleep(0.02)
                continue

            safe_total = N_LEFT_PAD_TOKENS + n_audio_samples_fed // SAMPLES_PER_TOKEN
            n_decodable = min(audio_embeds.shape[0], safe_total - n_total_decoded)

            if n_decodable <= 0:
                time.sleep(0.02)
                continue

            if not prefilled:
                if n_total_decoded + audio_embeds.shape[0] < prefix_len:
                    time.sleep(0.02)
                    continue

                cache = [RotatingKVCache(sliding_window) for _ in range(n_layers)]

                prefix_embeds = text_embeds + audio_embeds[:prefix_len]
                prefix_embeds = prefix_embeds[None, :, :]

                logits = model.decode(prefix_embeds, t_cond, "causal", cache)
                mx.eval(logits, *[x for c in cache for x in (c.keys, c.values)])

                y = sample(logits)
                mx.async_eval(y)

                audio_embeds = audio_embeds[prefix_len:]
                n_total_decoded = prefix_len
                prefilled = True

                n_decodable = min(audio_embeds.shape[0], safe_total - n_total_decoded)

            if n_decodable <= 0:
                time.sleep(0.02)
                continue

            n_consumed, hit_eos = decode_steps(audio_embeds, n_decodable)
            n_total_decoded += n_consumed

            if audio_embeds.shape[0] > n_consumed:
                audio_embeds = audio_embeds[n_consumed:]
            else:
                audio_embeds = None

            if hit_eos:
                flush_and_reset()
                if notify_on_eos:
                    on_speaking_finished()

            time.sleep(0.02)

    except KeyboardInterrupt:
        pass
    finally:
        stream.stop()
        stream.close()
        with lock:
            final_audio = audio_buf
            audio_buf = np.zeros(0, dtype=np.float32)
        pending_audio = np.append(pending_audio, final_audio)
        was_speaking = vad_state == VADState.SPEAKING
        flush_and_reset()
        if was_speaking:
            on_speaking_finished()


def main():
    parser = argparse.ArgumentParser(
        description="Live streaming speech-to-text with Voxtral"
    )
    parser.add_argument(
        "--model",
        default="mlx-community/Voxtral-Mini-4B-Realtime-6bit",
        help="Model path or HF model ID",
    )
    parser.add_argument(
        "--temp",
        type=float,
        default=0.0,
        help="Sampling temperature (0 = greedy)",
    )
    parser.add_argument(
        "--vad-onset",
        type=int,
        default=2,
        help="Consecutive VAD speech frames before starting transcription (default: 2, ~64 ms)",
    )
    parser.add_argument(
        "--vad-offset",
        type=int,
        default=32,
        help="Consecutive VAD silence frames before stopping transcription (default: 32, ~1 s)",
    )
    args = parser.parse_args()

    stream_transcribe(
        model_path=args.model,
        temperature=args.temp,
        vad_onset=args.vad_onset,
        vad_offset=args.vad_offset,
    )
