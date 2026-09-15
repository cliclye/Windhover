"""Persistent SERVE protocol + EngineSession (fake engine, no real pack)."""
from __future__ import annotations

import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import engine_session as es  # noqa: E402

FAKE_ENGINE = r"""#!/usr/bin/env python3
import os, sys
pid_path = os.environ.get("FAKE_ENGINE_PID")
if pid_path:
    open(pid_path, "a", encoding="utf-8").write(str(os.getpid()) + "\n")
sys.stdout.buffer.write(b"\x01\x01READY\x01\x01\n")
sys.stdout.buffer.flush()
turns = 0
while True:
    hdr = sys.stdin.buffer.readline()
    if not hdr or hdr.startswith(b"WHQUIT"):
        break
    parts = hdr.decode("ascii", errors="replace").split()
    if parts[0] != "WHGEN" or len(parts) < 7:
        sys.stdout.buffer.write(b"\n@@WH_STATS@@{\"error\":\"bad_header\"}\n")
        sys.stdout.buffer.write(b"\x01\x01END\x01\x01\n")
        sys.stdout.buffer.flush()
        continue
    nbytes = int(parts[5])
    body = sys.stdin.buffer.read(nbytes) if nbytes else b""
    turns += 1
    sys.stdout.buffer.write(f"pong{turns}:{body.decode('utf-8')}".encode("utf-8"))
    sys.stdout.buffer.write(b"\n@@WH_STATS@@{\"decode_tok_s\":9.8,\"tokens\":2,\"rss_gb\":0.1}\n")
    sys.stdout.buffer.write(b"\x01\x01END\x01\x01\n")
    sys.stdout.buffer.flush()
"""


class ProtocolTests(unittest.TestCase):
    def test_encode_whgen(self):
        blob = es.encode_whgen("hi\nthere", ngen=32, temp=0.35, topk=40, topp=0.9, spec=0)
        header, _, body = blob.partition(b"\n")
        self.assertTrue(header.startswith(b"WHGEN 32 "))
        self.assertEqual(body, b"hi\nthere")
        self.assertTrue(header.endswith(b" 8 0"))

    def test_parse_stats(self):
        raw = b"Hello\n@@WH_STATS@@{\"decode_tok_s\":9.8,\"tokens\":2}\n" + es.END
        text, stats = es.parse_stats_blob(raw)
        self.assertEqual(text, b"Hello\n")
        self.assertEqual(stats["decode_tok_s"], 9.8)
        self.assertEqual(stats["tokens"], 2)


class EngineSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.bin = self.dir / "fake-engine"
        self.bin.write_text(FAKE_ENGINE, encoding="utf-8")
        self.bin.chmod(self.bin.stat().st_mode | stat.S_IEXEC)
        self.pid_file = self.dir / "pids.txt"
        self.sess = es.EngineSession()

    def tearDown(self):
        self.sess.unload("test")
        self.tmp.cleanup()

    def _env(self, ram="8.8"):
        env = os.environ.copy()
        env["SNAP"] = str(self.dir / "pack")
        env["RAM_GB"] = ram
        env["MLOCK"] = "1"
        env["WH_SPARSE"] = "25"
        env["TEMP"] = "0.35"
        env["TOPK"] = "40"
        env["TOPP"] = "0.9"
        env["FAKE_ENGINE_PID"] = str(self.pid_file)
        env["COLI_OMP_TUNED"] = "1"
        return env

    def test_two_turns_one_process(self):
        deltas: list[str] = []
        text, stats, err, rc = self.sess.generate(
            engine_bin=self.bin,
            cwd=self.dir,
            env=self._env(),
            prompt="hello",
            ngen=16,
            timeout_s=10,
            on_delta=deltas.append,
        )
        self.assertEqual(rc, 0, msg=err)
        self.assertIn("pong1:hello", text)
        self.assertEqual(stats.get("decode_tok_s"), 9.8)
        self.assertTrue(self.sess.is_warm())
        self.assertTrue("".join(deltas).startswith("pong1:hello"))
        self.assertNotIn("@@WH_STATS@@", "".join(deltas))

        text2, stats2, err2, rc2 = self.sess.generate(
            engine_bin=self.bin,
            cwd=self.dir,
            env=self._env(),
            prompt="again",
            ngen=16,
            timeout_s=10,
        )
        self.assertEqual(rc2, 0, msg=err2)
        self.assertIn("pong2:again", text2)
        pids = self.pid_file.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(pids), 1, msg=pids)

    def test_reload_on_ram_profile_change(self):
        self.sess.generate(
            engine_bin=self.bin, cwd=self.dir, env=self._env("8.8"),
            prompt="a", ngen=8, timeout_s=10,
        )
        self.sess.generate(
            engine_bin=self.bin, cwd=self.dir, env=self._env("6.4"),
            prompt="b", ngen=8, timeout_s=10,
        )
        pids = self.pid_file.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(set(pids)), 2, msg=pids)

    def test_idle_unload(self):
        os.environ["WINDHOVER_ENGINE_IDLE_S"] = "1"
        try:
            self.sess.generate(
                engine_bin=self.bin, cwd=self.dir, env=self._env(),
                prompt="z", ngen=8, timeout_s=10,
            )
            self.assertTrue(self.sess.is_warm())
            deadline = time.time() + 20
            while self.sess.is_warm() and time.time() < deadline:
                time.sleep(0.25)
            self.assertFalse(self.sess.is_warm())
        finally:
            os.environ.pop("WINDHOVER_ENGINE_IDLE_S", None)


if __name__ == "__main__":
    unittest.main()
