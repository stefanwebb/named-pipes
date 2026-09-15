"""© 2025–2026, Stefan Webb. Some Rights Reserved.

Except where otherwise noted, this work is licensed under a
Creative Commons Attribution-ShareAlike 4.0 International License
https://creativecommons.org/licenses/by-sa/4.0/deed.en
"""

from named_pipes.interfaces.interface import ArgSpec, CommandSpec, EventSpec, Interface

_TENSOR = "tensor"  # {"b64": <base64 float32>, "shape": [...], "dtype": "float32"}

ARDY = Interface(
    name="ardy",
    description=(
        "Autoregressive motion diffusion — stateless tokenizer and denoiser inference. "
        "The server holds the weights and evaluates forward passes; the CLIENT owns all "
        "session state (history tokens, global translation, heading) and drives the "
        "denoising loop. Tensor arguments and fields are objects of the form "
        '{"b64": <base64 of little-endian float32>, "shape": [...], "dtype": "float32"}.'
    ),
    commands=[
        CommandSpec(
            name="model_info",
            description=(
                "Request the loaded model's dimensions. A client that owns session state "
                "needs these to size its own tensors."
            ),
        ),
        CommandSpec(
            name="tokenize",
            description="Encode explicit motion frames into hybrid (root + latent body) tokens.",
            args=[
                ArgSpec(name="motion", description="Explicit motion frames [B, T, D].", type=_TENSOR),
                ArgSpec(
                    name="req_id",
                    description="Correlation id echoed back on the response event.",
                    type="int",
                    required=False,
                ),
            ],
        ),
        CommandSpec(
            name="detokenize",
            description="Decode hybrid tokens back into explicit motion frames.",
            args=[
                ArgSpec(name="tokens", description="Hybrid tokens [B, N, D_token].", type=_TENSOR),
                ArgSpec(
                    name="req_id",
                    description="Correlation id echoed back on the response event.",
                    type="int",
                    required=False,
                ),
            ],
        ),
        CommandSpec(
            name="requantize",
            description=(
                "Re-quantize the latent body channels of a token sequence. Needed after the "
                "client recenters its history, when the autoencoder quantizes."
            ),
            args=[
                ArgSpec(name="latent", description="Latent body motion [B, N, D_latent].", type=_TENSOR),
                ArgSpec(
                    name="req_id",
                    description="Correlation id echoed back on the response event.",
                    type="int",
                    required=False,
                ),
            ],
        ),
        CommandSpec(
            name="denoise",
            description=(
                "Run one denoising step: predict the clean tokens and apply the sampler, "
                "returning x_{t-1}. Only tokens selected by the generation mask are written; "
                "history tokens pass through untouched. Call once per timestep, descending."
            ),
            args=[
                ArgSpec(name="x", description="Current noisy token sequence [B, N, D_token].", type=_TENSOR),
                ArgSpec(name="t", description="Diffusion timestep index for this step.", type="int"),
                ArgSpec(
                    name="num_denoising_steps",
                    description="Total steps in the schedule, so the server can space timesteps.",
                    type="int",
                ),
                ArgSpec(name="text_feat", description="Text conditioning features [B, L, D_llm].", type=_TENSOR),
                ArgSpec(name="text_pad_mask", description="Text padding mask [B, L].", type=_TENSOR),
                ArgSpec(
                    name="masks",
                    description=(
                        "Object with the frame and token masks for this window: "
                        "history_mask, generation_mask, future_mask, history_token_mask, "
                        "generation_token_mask, future_token_mask, plus the integer lengths "
                        "history_len, generation_len, future_len."
                    ),
                    type="object",
                ),
                ArgSpec(
                    name="first_heading_angle",
                    description="Heading angle of the window's first frame [B].",
                    type=_TENSOR,
                ),
                ArgSpec(
                    name="motion_mask",
                    description="Kinematic constraint mask [B, T, D], or null when unconstrained.",
                    type=_TENSOR,
                    required=False,
                ),
                ArgSpec(
                    name="observed_motion",
                    description="Constraint target values [B, T, D], or null when unconstrained.",
                    type=_TENSOR,
                    required=False,
                ),
                ArgSpec(
                    name="cfg_weight",
                    description="Guidance weight, or [text_weight, constraint_weight].",
                    type="float",
                    required=False,
                    default="2.0",
                ),
                ArgSpec(
                    name="cfg_type",
                    description="Classifier-free-guidance variant; server default when omitted.",
                    type="str",
                    required=False,
                ),
                ArgSpec(
                    name="req_id",
                    description="Correlation id echoed back on the response event.",
                    type="int",
                    required=False,
                ),
            ],
        ),
    ],
    events=[
        EventSpec(
            name="model_info",
            description="Response to model_info.",
            fields=[
                ArgSpec(name="req_id", description="Correlation id of the request.", type="int"),
                ArgSpec(name="model_name", description="Loaded checkpoint name.", type="str"),
                ArgSpec(name="skeleton", description="Skeleton name, e.g. cskel27.", type="str"),
                ArgSpec(name="fps", description="Motion frame rate of the model.", type="float"),
                ArgSpec(name="gen_horizon_len", description="Frames generated per step.", type="int"),
                ArgSpec(name="num_frames_per_token", description="Frames collapsed into one token.", type="int"),
                ArgSpec(name="nframe_root_dim", description="Explicit root dims per token.", type="int"),
                ArgSpec(name="latent_embedding_dim", description="Latent body dims per token.", type="int"),
                ArgSpec(name="motion_rep_dim", description="Explicit motion feature width.", type="int"),
                ArgSpec(name="num_base_steps", description="Diffusion steps the model was trained with.", type="int"),
                ArgSpec(
                    name="encode_with_quantization",
                    description="Whether the autoencoder quantizes, i.e. whether requantize is required.",
                    type="bool",
                ),
            ],
        ),
        EventSpec(
            name="tokenized",
            description="Response to tokenize.",
            fields=[
                ArgSpec(name="req_id", description="Correlation id of the request.", type="int"),
                ArgSpec(name="tokens", description="Hybrid tokens [B, N, D_token].", type=_TENSOR),
            ],
        ),
        EventSpec(
            name="detokenized",
            description="Response to detokenize.",
            fields=[
                ArgSpec(name="req_id", description="Correlation id of the request.", type="int"),
                ArgSpec(name="motion", description="Explicit motion frames [B, T, D].", type=_TENSOR),
            ],
        ),
        EventSpec(
            name="requantized",
            description="Response to requantize.",
            fields=[
                ArgSpec(name="req_id", description="Correlation id of the request.", type="int"),
                ArgSpec(name="latent", description="Re-quantized latent body motion [B, N, D_latent].", type=_TENSOR),
            ],
        ),
        EventSpec(
            name="denoised",
            description="Response to denoise.",
            fields=[
                ArgSpec(name="req_id", description="Correlation id of the request.", type="int"),
                ArgSpec(name="x", description="Token sequence after one sampler step [B, N, D_token].", type=_TENSOR),
                ArgSpec(name="t", description="Timestep this result corresponds to.", type="int"),
            ],
        ),
        EventSpec(
            name="error",
            description="A command failed. Carries the req_id of the request that failed, when known.",
            fields=[
                ArgSpec(name="req_id", description="Correlation id of the failed request.", type="int", required=False),
                ArgSpec(name="cmd", description="Command that failed.", type="str", required=False),
                ArgSpec(name="message", description="Human-readable failure description.", type="str"),
            ],
        ),
    ],
)
