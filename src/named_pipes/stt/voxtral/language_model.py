import mlx.core as mx
import mlx.nn as nn

from .cache import RotatingKVCache


class DecoderAttention(nn.Module):
    def __init__(
        self,
        dim: int = 3072,
        n_heads: int = 32,
        n_kv_heads: int = 8,
        head_dim: int = 128,
        rope_theta: float = 1e6,
    ):
        super().__init__()
        self.n_heads = n_heads
        self.n_kv_heads = n_kv_heads
        self.head_dim = head_dim
        self.scale = head_dim ** -0.5
        self.q_proj = nn.Linear(dim, n_heads * head_dim, bias=False)
        self.k_proj = nn.Linear(dim, n_kv_heads * head_dim, bias=False)
        self.v_proj = nn.Linear(dim, n_kv_heads * head_dim, bias=False)
        self.o_proj = nn.Linear(n_heads * head_dim, dim, bias=False)

        self.rope_theta = rope_theta

    def __call__(
        self,
        x: mx.array,
        mask=None,
        cache: RotatingKVCache | None = None,
    ) -> mx.array:
        B, L, _ = x.shape
        q = self.q_proj(x).reshape(B, L, self.n_heads, self.head_dim).transpose(0, 2, 1, 3)
        k = self.k_proj(x).reshape(B, L, self.n_kv_heads, self.head_dim).transpose(0, 2, 1, 3)
        v = self.v_proj(x).reshape(B, L, self.n_kv_heads, self.head_dim).transpose(0, 2, 1, 3)

        offset = cache.offset if cache is not None else 0
        q = mx.fast.rope(q, self.head_dim, traditional=True, base=self.rope_theta, scale=1.0, offset=offset)
        k = mx.fast.rope(k, self.head_dim, traditional=True, base=self.rope_theta, scale=1.0, offset=offset)

        if cache is not None:
            k, v = cache.update_and_fetch(k, v)

        out = mx.fast.scaled_dot_product_attention(q, k, v, scale=self.scale, mask=mask)
        out = out.transpose(0, 2, 1, 3).reshape(B, L, -1)
        return self.o_proj(out)


class DecoderSwiGLU(nn.Module):
    def __init__(self, dim: int = 3072, hidden_dim: int = 9216):
        super().__init__()
        self.gate_proj = nn.Linear(dim, hidden_dim, bias=False)
        self.up_proj = nn.Linear(dim, hidden_dim, bias=False)
        self.down_proj = nn.Linear(hidden_dim, dim, bias=False)

    def __call__(self, x: mx.array) -> mx.array:
        return self.down_proj(nn.silu(self.gate_proj(x)) * self.up_proj(x))


class AdaptiveNorm(nn.Module):
    def __init__(self, dim: int = 3072, cond_dim: int = 32):
        super().__init__()
        self.linear_in = nn.Linear(dim, cond_dim, bias=False)
        self.linear_out = nn.Linear(cond_dim, dim, bias=False)

    def __call__(self, t_cond: mx.array) -> mx.array:
        return self.linear_out(nn.gelu(self.linear_in(t_cond)))


class DecoderLayer(nn.Module):
    def __init__(
        self,
        dim: int = 3072,
        n_heads: int = 32,
        n_kv_heads: int = 8,
        head_dim: int = 128,
        hidden_dim: int = 9216,
        rope_theta: float = 1e6,
        cond_dim: int = 32,
    ):
        super().__init__()
        self.attn_norm = nn.RMSNorm(dim, eps=1e-5)
        self.attention = DecoderAttention(dim, n_heads, n_kv_heads, head_dim, rope_theta)
        self.ada_norm = AdaptiveNorm(dim, cond_dim)
        self.ffn_norm = nn.RMSNorm(dim, eps=1e-5)
        self.mlp = DecoderSwiGLU(dim, hidden_dim)

    def __call__(
        self,
        x: mx.array,
        t_cond: mx.array,
        mask=None,
        cache: RotatingKVCache | None = None,
    ) -> mx.array:
        h = self.attention(self.attn_norm(x), mask, cache)
        x = x + h
        ffn_in = self.ffn_norm(x) * (1.0 + self.ada_norm(t_cond))
        x = x + self.mlp(ffn_in)
        return x


class LanguageModel(nn.Module):
    def __init__(
        self,
        dim: int = 3072,
        n_layers: int = 26,
        n_heads: int = 32,
        n_kv_heads: int = 8,
        head_dim: int = 128,
        hidden_dim: int = 9216,
        vocab_size: int = 131072,
        rope_theta: float = 1e6,
        cond_dim: int = 32,
    ):
        super().__init__()
        self.embed_tokens = nn.Embedding(vocab_size, dim)
        self.layers = [
            DecoderLayer(dim, n_heads, n_kv_heads, head_dim, hidden_dim, rope_theta, cond_dim)
            for _ in range(n_layers)
        ]
        self.norm = nn.RMSNorm(dim, eps=1e-5)
        self._dim = dim

    def embed(self, input_ids: mx.array) -> mx.array:
        return self.embed_tokens(input_ids)

    def __call__(
        self,
        x: mx.array,
        t_cond: mx.array,
        mask=None,
        cache: list[RotatingKVCache] | None = None,
    ) -> mx.array:
        t_cond = t_cond.astype(x.dtype)
        for i, layer in enumerate(self.layers):
            layer_cache = cache[i] if cache is not None else None
            x = layer(x, t_cond, mask, layer_cache)
        x = self.norm(x)
        logits = self.embed_tokens.as_linear(x)
        return logits
