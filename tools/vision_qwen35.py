"""Qwen3.5 / Qwen3-VL vision encoder in numpy (no torch).

Turns an image into the embeddings the language model expects at its
<|image_pad|> positions. Mirrors transformers' Qwen3_5VisionModel:

  smart-resize (multiples of patch*merge) -> 16x16x2 patches (block-major order)
  -> patch_embed (Conv3d == linear) + bilinear-interpolated learned pos-embed
  -> 24 x [LayerNorm, MHA with 2D rotary, LayerNorm, GELU-tanh MLP]
  -> merger (LayerNorm, 2x2 concat, Linear, GELU, Linear) -> [tokens, text_hidden]

Weights are read straight from the original HF safetensors (bf16/f16/f32).
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import struct
import threading
from pathlib import Path
from typing import Any

import numpy as np

# Default pixel budget per image: ~0.5 MP -> <= ~490 LLM tokens. Big enough to
# read a screenshot, small enough to encode in a few seconds on a laptop CPU.
DEFAULT_MAX_PIXELS = int(os.environ.get("WINDHOVER_VISION_MAX_PIXELS") or 512 * 1024)
DEFAULT_MIN_PIXELS = 64 * 1024

IMAGE_PAD = "<|image_pad|>"
VISION_START = "<|vision_start|>"
VISION_END = "<|vision_end|>"


# ---------------------------------------------------------------- safetensors
_DT = {"BF16": np.uint16, "F16": np.float16, "F32": np.float32}


class _ST:
    """Minimal lazy safetensors reader (multi-shard) that returns float32 arrays."""

    def __init__(self, snap: Path):
        self.files: dict[str, tuple[Path, dict]] = {}
        idx = snap / "model.safetensors.index.json"
        shards = []
        if idx.is_file():
            wm = json.loads(idx.read_text())["weight_map"]
            shards = sorted({snap / v for v in wm.values()})
        else:
            shards = sorted(snap.glob("*.safetensors"))
        for sh in shards:
            with open(sh, "rb") as f:
                n = struct.unpack("<Q", f.read(8))[0]
                hdr = json.loads(f.read(n))
            base = 8 + n
            for k, v in hdr.items():
                if k == "__metadata__":
                    continue
                self.files[k] = (sh, dict(v, base=base))
        self._mm: dict[Path, np.memmap] = {}

    def has(self, name: str) -> bool:
        return name in self.files

    def get(self, name: str) -> np.ndarray:
        path, info = self.files[name]
        mm = self._mm.get(path)
        if mm is None:
            mm = self._mm[path] = np.memmap(path, dtype=np.uint8, mode="r")
        a, b = info["data_offsets"]
        raw = mm[info["base"] + a: info["base"] + b]
        dt = info["dtype"]
        if dt == "BF16":
            u = np.frombuffer(raw, dtype=np.uint16).astype(np.uint32) << 16
            arr = u.view(np.float32)
        elif dt in _DT:
            arr = np.frombuffer(raw, dtype=_DT[dt]).astype(np.float32)
        else:
            raise ValueError(f"unsupported dtype {dt} for {name}")
        return arr.reshape(info["shape"])


# ---------------------------------------------------------------- math helpers
def _layernorm(x: np.ndarray, w: np.ndarray, b: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    mu = x.mean(-1, keepdims=True)
    var = ((x - mu) ** 2).mean(-1, keepdims=True)
    return (x - mu) / np.sqrt(var + eps) * w + b


def _gelu_tanh(x: np.ndarray) -> np.ndarray:
    return 0.5 * x * (1.0 + np.tanh(0.7978845608028654 * (x + 0.044715 * x * x * x)))


def _erf(x: np.ndarray) -> np.ndarray:
    # Abramowitz & Stegun 7.1.26 (|err| < 1.5e-7) — numpy has no erf.
    s = np.sign(x)
    a = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * a)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t
               + 0.254829592) * t * np.exp(-a * a)
    return s * y


def _gelu(x: np.ndarray) -> np.ndarray:
    return 0.5 * x * (1.0 + _erf(x * 0.7071067811865476))


def _softmax_rows(s: np.ndarray) -> np.ndarray:
    s = s - s.max(-1, keepdims=True)
    np.exp(s, out=s)
    s /= s.sum(-1, keepdims=True)
    return s


# ---------------------------------------------------------------- preprocessing
def smart_resize(h: int, w: int, factor: int = 32, min_pixels: int = DEFAULT_MIN_PIXELS,
                 max_pixels: int = DEFAULT_MAX_PIXELS) -> tuple[int, int]:
    """Qwen2-VL smart_resize: both sides multiples of `factor`, area within bounds."""
    if max(h, w) / max(1, min(h, w)) > 200:
        raise ValueError("image aspect ratio is too extreme")
    hb = max(factor, round(h / factor) * factor)
    wb = max(factor, round(w / factor) * factor)
    if hb * wb > max_pixels:
        beta = math.sqrt((h * w) / max_pixels)
        hb = max(factor, math.floor(h / beta / factor) * factor)
        wb = max(factor, math.floor(w / beta / factor) * factor)
    elif hb * wb < min_pixels:
        beta = math.sqrt(min_pixels / (h * w))
        hb = math.ceil(h * beta / factor) * factor
        wb = math.ceil(w * beta / factor) * factor
    return hb, wb


def load_image(data: bytes) -> np.ndarray:
    """Decode PNG/JPEG/WebP/GIF bytes to RGB uint8 [H, W, 3]."""
    from PIL import Image  # bundled with the app (Pillow)

    im = Image.open(io.BytesIO(data))
    im.load()
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg
    return np.asarray(im.convert("RGB"), dtype=np.uint8)


def resize_rgb(rgb: np.ndarray, h: int, w: int) -> np.ndarray:
    from PIL import Image

    if rgb.shape[0] == h and rgb.shape[1] == w:
        return rgb
    return np.asarray(Image.fromarray(rgb).resize((w, h), Image.BICUBIC), dtype=np.uint8)


def to_patches(rgb: np.ndarray, patch: int = 16, temporal: int = 2, merge: int = 2,
               mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5)) -> tuple[np.ndarray, tuple[int, int, int]]:
    """RGB uint8 [H, W, 3] (already smart-resized) -> flattened patches + (t, gh, gw)."""
    x = rgb.astype(np.float32) / 255.0
    x = (x - np.asarray(mean, np.float32)) / np.asarray(std, np.float32)
    x = x.transpose(2, 0, 1)  # C, H, W
    C, H, W = x.shape
    gh, gw = H // patch, W // patch
    frames = np.repeat(x[None], temporal, axis=0)  # T, C, H, W (an image is one repeated frame)
    p = frames.reshape(1, temporal, C, gh // merge, merge, patch, gw // merge, merge, patch)
    p = p.transpose(0, 3, 6, 4, 7, 2, 1, 5, 8)
    return np.ascontiguousarray(p.reshape(gh * gw, C * temporal * patch * patch)), (1, gh, gw)


# ---------------------------------------------------------------- encoder
class VisionEncoder:
    def __init__(self, snap: Path):
        cfg = json.loads((snap / "config.json").read_text())
        vc = cfg.get("vision_config") or {}
        if not vc:
            raise ValueError("model has no vision encoder")
        self.depth = int(vc["depth"])
        self.dim = int(vc["hidden_size"])
        self.heads = int(vc["num_heads"])
        self.hd = self.dim // self.heads
        self.patch = int(vc.get("patch_size", 16))
        self.temporal = int(vc.get("temporal_patch_size", 2))
        self.merge = int(vc.get("spatial_merge_size", 2))
        self.side = int(round(int(vc.get("num_position_embeddings", 2304)) ** 0.5))
        self.out_dim = int(vc.get("out_hidden_size") or cfg.get("text_config", {}).get("hidden_size"))
        if vc.get("deepstack_visual_indexes"):
            raise ValueError("deepstack vision models are not supported")
        pp = snap / "preprocessor_config.json"
        pre = json.loads(pp.read_text()) if pp.is_file() else {}
        self.mean = pre.get("image_mean", [0.5, 0.5, 0.5])
        self.std = pre.get("image_std", [0.5, 0.5, 0.5])
        st = _ST(snap)
        pfx = next((p for p in ("model.visual.", "visual.", "model.vision_tower.") if st.has(p + "pos_embed.weight")),
                   None)
        if pfx is None:
            raise ValueError("vision weights not found in this model folder")
        g = lambda n: st.get(pfx + n)  # noqa: E731
        pw = g("patch_embed.proj.weight")
        self.patch_w = np.ascontiguousarray(pw.reshape(pw.shape[0], -1).T)  # [1536, D]
        self.patch_b = g("patch_embed.proj.bias")
        self.pos = g("pos_embed.weight")
        self.blocks = []
        for i in range(self.depth):
            b = f"blocks.{i}."
            self.blocks.append({
                "n1w": g(b + "norm1.weight"), "n1b": g(b + "norm1.bias"),
                "n2w": g(b + "norm2.weight"), "n2b": g(b + "norm2.bias"),
                "qkvT": np.ascontiguousarray(g(b + "attn.qkv.weight").T), "qkvb": g(b + "attn.qkv.bias"),
                "projT": np.ascontiguousarray(g(b + "attn.proj.weight").T), "projb": g(b + "attn.proj.bias"),
                "fc1T": np.ascontiguousarray(g(b + "mlp.linear_fc1.weight").T), "fc1b": g(b + "mlp.linear_fc1.bias"),
                "fc2T": np.ascontiguousarray(g(b + "mlp.linear_fc2.weight").T), "fc2b": g(b + "mlp.linear_fc2.bias"),
            })
        self.m_nw, self.m_nb = g("merger.norm.weight"), g("merger.norm.bias")
        self.m_fc1T = np.ascontiguousarray(g("merger.linear_fc1.weight").T)
        self.m_fc1b = g("merger.linear_fc1.bias")
        self.m_fc2T = np.ascontiguousarray(g("merger.linear_fc2.weight").T)
        self.m_fc2b = g("merger.linear_fc2.bias")
        rd = self.hd // 2
        self.inv_freq = 1.0 / (10000.0 ** (np.arange(0, rd, 2, dtype=np.float32) / rd))

    # -- positional helpers (block-major order, as in transformers.vision_utils)
    def _block_order(self, gh: int, gw: int) -> np.ndarray:
        m = self.merge
        idx = np.arange(gh * gw).reshape(gh // m, m, gw // m, m).transpose(0, 2, 1, 3)
        return idx.reshape(-1)

    def _pos_embed(self, gh: int, gw: int) -> np.ndarray:
        s = self.side
        hg = np.linspace(0, s - 1, gh, dtype=np.float32)
        wg = np.linspace(0, s - 1, gw, dtype=np.float32)
        hf, wf = hg.astype(np.int64), wg.astype(np.int64)
        hc, wc = np.minimum(hf + 1, s - 1), np.minimum(wf + 1, s - 1)
        dh, dw = hg - hf, wg - wf
        idx = [(hf[:, None] * s + wf[None, :]), (hf[:, None] * s + wc[None, :]),
               (hc[:, None] * s + wf[None, :]), (hc[:, None] * s + wc[None, :])]
        wts = [((1 - dh)[:, None] * (1 - dw)[None, :]), ((1 - dh)[:, None] * dw[None, :]),
               (dh[:, None] * (1 - dw)[None, :]), (dh[:, None] * dw[None, :])]
        order = self._block_order(gh, gw)
        out = np.zeros((gh * gw, self.dim), np.float32)
        for i, w in zip(idx, wts):
            out += self.pos[i.reshape(-1)[order]] * w.reshape(-1)[order][:, None]
        return out

    def _rotary(self, gh: int, gw: int) -> tuple[np.ndarray, np.ndarray]:
        hp, wp = np.meshgrid(np.arange(gh), np.arange(gw), indexing="ij")
        order = self._block_order(gh, gw)
        hp, wp = hp.reshape(-1)[order], wp.reshape(-1)[order]
        f = np.concatenate([hp[:, None] * self.inv_freq[None], wp[:, None] * self.inv_freq[None]], 1)
        emb = np.concatenate([f, f], 1).astype(np.float32)  # [N, hd]
        return np.cos(emb), np.sin(emb)

    @staticmethod
    def _rope(x: np.ndarray, cos: np.ndarray, sin: np.ndarray) -> np.ndarray:
        # x [N, H, hd]; rotate_half convention
        h = x.shape[-1] // 2
        rot = np.concatenate([-x[..., h:], x[..., :h]], -1)
        return x * cos[:, None, :] + rot * sin[:, None, :]

    def encode_patches(self, patches: np.ndarray, grid: tuple[int, int, int]) -> np.ndarray:
        _, gh, gw = grid
        N = patches.shape[0]
        x = patches.astype(np.float32) @ self.patch_w + self.patch_b
        x += self._pos_embed(gh, gw)
        cos, sin = self._rotary(gh, gw)
        H, hd = self.heads, self.hd
        scale = hd ** -0.5
        for b in self.blocks:
            h = _layernorm(x, b["n1w"], b["n1b"])
            qkv = (h @ b["qkvT"] + b["qkvb"]).reshape(N, 3, H, hd)
            q = self._rope(qkv[:, 0], cos, sin)
            k = self._rope(qkv[:, 1], cos, sin)
            v = qkv[:, 2]
            ctx = np.empty((N, H, hd), np.float32)
            for hh in range(H):
                s = (q[:, hh] @ k[:, hh].T) * scale
                ctx[:, hh] = _softmax_rows(s) @ v[:, hh]
            x = x + ctx.reshape(N, H * hd) @ b["projT"] + b["projb"]
            h = _layernorm(x, b["n2w"], b["n2b"])
            x = x + _gelu_tanh(h @ b["fc1T"] + b["fc1b"]) @ b["fc2T"] + b["fc2b"]
        x = _layernorm(x, self.m_nw, self.m_nb).reshape(-1, self.dim * self.merge * self.merge)
        x = _gelu(x @ self.m_fc1T + self.m_fc1b) @ self.m_fc2T + self.m_fc2b
        return np.ascontiguousarray(x.astype(np.float32))

    def encode(self, data: bytes, max_pixels: int = DEFAULT_MAX_PIXELS) -> dict[str, Any]:
        rgb = load_image(data)
        f = self.patch * self.merge
        h, w = smart_resize(rgb.shape[0], rgb.shape[1], f, DEFAULT_MIN_PIXELS, max_pixels)
        rgb = resize_rgb(rgb, h, w)
        patches, grid = to_patches(rgb, self.patch, self.temporal, self.merge, self.mean, self.std)
        emb = self.encode_patches(patches, grid)
        _, gh, gw = grid
        return {"embeddings": emb, "grid": (1, gh // self.merge, gw // self.merge),
                "tokens": emb.shape[0], "size": (w, h)}


# ---------------------------------------------------------------- cache / API
_ENC: dict[str, VisionEncoder] = {}
_EMB: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def supports_images(snap: Path | None) -> bool:
    if not snap:
        return False
    try:
        cfg = json.loads((Path(snap) / "config.json").read_text())
    except Exception:
        return False
    vc = cfg.get("vision_config") or {}
    mt = str(cfg.get("model_type") or "")
    if not vc or vc.get("deepstack_visual_indexes") or not mt.startswith("qwen3_5"):
        return False
    snap = Path(snap)
    return any(p.name.startswith("model") and p.suffix == ".safetensors" for p in snap.glob("*.safetensors"))


def encode_image(snap: Path, data: bytes) -> dict[str, Any]:
    """Cached by (model, image bytes): follow-up turns reuse the embeddings."""
    key = hashlib.sha256(str(snap).encode() + b"\0" + data).hexdigest()
    with _LOCK:
        hit = _EMB.get(key)
        if hit:
            return hit
        enc = _ENC.get(str(snap))
        if enc is None:
            enc = _ENC[str(snap)] = VisionEncoder(Path(snap))
        out = enc.encode(data)
        out["hash"] = int(key[:15], 16)
        if len(_EMB) > 32:
            _EMB.pop(next(iter(_EMB)))
        _EMB[key] = out
        return out


def placeholder(n_tokens: int) -> str:
    return VISION_START + IMAGE_PAD * n_tokens + VISION_END
