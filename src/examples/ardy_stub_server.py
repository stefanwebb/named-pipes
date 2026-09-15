"""Stub ARDY server: implements the `ardy` interface with trivial arithmetic.

Exists to exercise the client's transport, correlation and codec end to end
over real FIFOs, without loading any model.
"""

import numpy as np
from named_pipes import ToolServer
from named_pipes.ardy import decode_tensor, encode_tensor

INFO = dict(
    model_name="ARDY-Core-RP-20FPS-Horizon40",
    skeleton="cskel27",
    fps=20.0,
    gen_horizon_len=40,
    num_frames_per_token=4,
    nframe_root_dim=20,
    latent_embedding_dim=128,
    motion_rep_dim=272,
    num_base_steps=100,
    encode_with_quantization=True,
)


def main():
    with ToolServer("ardy", description="Stub ARDY inference server") as server:

        @server.handler("model_info")
        def _(msg, pid):
            server.send_event("model_info", pid, req_id=msg.get("req_id"), **INFO)

        @server.handler("tokenize")
        def _(msg, pid):
            motion = decode_tensor(msg["motion"])          # [B, T, D]
            b, t, _ = motion.shape
            n = t // INFO["num_frames_per_token"]
            tokens = np.zeros((b, n, 148), dtype=np.float32)
            tokens[:, :, 0] = 1.0                          # marker we can assert on
            server.send_event("tokenized", pid, req_id=msg.get("req_id"),
                              tokens=encode_tensor(tokens))

        @server.handler("detokenize")
        def _(msg, pid):
            tokens = decode_tensor(msg["tokens"])          # [B, N, 148]
            b, n, _ = tokens.shape
            frames = n * INFO["num_frames_per_token"]
            motion = np.full((b, frames, INFO["motion_rep_dim"]), 0.5, dtype=np.float32)
            server.send_event("detokenized", pid, req_id=msg.get("req_id"),
                              motion=encode_tensor(motion))

        @server.handler("requantize")
        def _(msg, pid):
            latent = decode_tensor(msg["latent"])
            server.send_event("requantized", pid, req_id=msg.get("req_id"),
                              latent=encode_tensor(np.round(latent)))

        @server.handler("denoise")
        def _(msg, pid):
            x = decode_tensor(msg["x"])
            masks = msg["masks"]
            gen = decode_tensor(masks["generation_token_mask"])
            # Stand-in for a sampler step: only generation tokens are written,
            # history passes through untouched. Shrink toward zero each step.
            out = x.copy()
            out[gen] = out[gen] * 0.5
            server.send_event("denoised", pid, req_id=msg.get("req_id"),
                              t=msg["t"], x=encode_tensor(out))

        @server.handler("boom")
        def _(msg, pid):
            server.send_event("error", pid, req_id=msg.get("req_id"),
                              cmd="boom", message="deliberate failure")

        done = server.listen()
        print("stub ardy server listening on /tmp/tool-ardy", flush=True)
        done.wait()


if __name__ == "__main__":
    main()
