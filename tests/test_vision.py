"""Image input: preprocessing, engine image block, model capability check."""
from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import engine_session as ES  # noqa: E402
import vision_qwen35 as V  # noqa: E402


class Preprocess(unittest.TestCase):
    def test_smart_resize_multiples_and_budget(self):
        for h, w in [(400, 640), (1800, 2880), (33, 900), (64, 64)]:
            rh, rw = V.smart_resize(h, w, 32, max_pixels=512 * 1024)
            self.assertEqual(rh % 32, 0)
            self.assertEqual(rw % 32, 0)
            self.assertLessEqual(rh * rw, 512 * 1024)
            self.assertGreaterEqual(rh * rw, V.DEFAULT_MIN_PIXELS)

    def test_patches_layout(self):
        rgb = np.zeros((64, 96, 3), np.uint8)
        rgb[:, :, 0] = 255  # red -> normalized +1 in channel 0, -1 elsewhere
        p, grid = V.to_patches(rgb)
        self.assertEqual(grid, (1, 4, 6))
        self.assertEqual(p.shape, (24, 3 * 2 * 16 * 16))
        per = 2 * 16 * 16
        self.assertTrue(np.allclose(p[:, :per], 1.0))
        self.assertTrue(np.allclose(p[:, per:], -1.0))

    def test_block_order_groups_2x2(self):
        enc = V.VisionEncoder.__new__(V.VisionEncoder)
        enc.merge = 2
        order = enc._block_order(4, 4)
        # first merged token = patches (0,0) (0,1) (1,0) (1,1) of a 4x4 grid
        self.assertEqual(order[:4].tolist(), [0, 1, 4, 5])

    def test_placeholder(self):
        s = V.placeholder(3)
        self.assertEqual(s.count(V.IMAGE_PAD), 3)
        self.assertTrue(s.startswith(V.VISION_START) and s.endswith(V.VISION_END))


class EngineBlock(unittest.TestCase):
    def test_image_block_layout(self):
        emb = np.arange(2 * 4, dtype=np.float32).reshape(2, 4)
        blob = ES.encode_images([{"embeddings": emb, "grid": (1, 1, 2), "hash": 42}], (11, 11, 10), True)
        self.assertEqual(blob[:4], b"WHIM")
        n, s0, s1, s2, inter = struct.unpack("<5I", blob[4:24])
        self.assertEqual((n, s0, s1, s2, inter), (1, 11, 11, 10, 1))
        ntok, gt, gh, gw, dim, h = struct.unpack("<5IQ", blob[24:52])
        self.assertEqual((ntok, gt, gh, gw, dim, h), (2, 1, 1, 2, 4, 42))
        self.assertEqual(np.frombuffer(blob[52:], np.float32).tolist(), emb.reshape(-1).tolist())

    def test_header_flag(self):
        hdr = ES.encode_whgen("hi", ngen=8, temp=0, topk=0, topp=0, spec=0, flags=2).split(b"\n")[0]
        self.assertTrue(hdr.endswith(b" 2"))


class Capability(unittest.TestCase):
    def _snap(self, cfg: dict, weights: bool = True) -> Path:
        d = Path(tempfile.mkdtemp())
        (d / "config.json").write_text(json.dumps(cfg))
        if weights:
            (d / "model.safetensors").write_bytes(b"")
        return d

    def test_text_only_models_cannot_see(self):
        self.assertFalse(V.supports_images(self._snap({"model_type": "qwen3"})))
        self.assertFalse(V.supports_images(None))

    def test_qwen35_with_weights_can_see(self):
        cfg = {"model_type": "qwen3_5", "vision_config": {"depth": 2, "deepstack_visual_indexes": []}}
        self.assertTrue(V.supports_images(self._snap(cfg)))
        self.assertFalse(V.supports_images(self._snap(cfg, weights=False)))

    def test_deepstack_not_supported(self):
        cfg = {"model_type": "qwen3_5", "vision_config": {"deepstack_visual_indexes": [5, 11]}}
        self.assertFalse(V.supports_images(self._snap(cfg)))


if __name__ == "__main__":
    unittest.main()
