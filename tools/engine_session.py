"""Persistent windhover-engine (SERVE=1) for Chat / Agent.

One process per loaded pack. Tokens stream on stdout. The process is
unloaded on SNAP / RAM-profile change, idle timeout, or crash.

Protocol (KPK + dense paths, binary stdio):

  engine → host:  \\x01\\x01READY\\x01\\x01\\n   after mmap/load
  host  → engine: WHGEN <ngen> <temp> <topk> <topp> <nbytes> <spec>\\n
                  <nbytes bytes of UTF-8 prompt>
  engine → host:  streamed tokens, then
                  \\n@@WH_STATS@@{...}\\n\\x01\\x01END\\x01\\x01\\n
  host  → engine: WHQUIT\\n   or close stdin
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, TextIO

READY = b"\x01\x01READY\x01\x01\n"
END = b"\x01\x01END\x01\x01\n"
STATS_MARK = b"@@WH_STATS@@"
MAX_PROMPT_BYTES = 8 * 1024 * 1024


def serve_enabled() -> bool:
    v = os.environ.get("WINDHOVER_ENGINE_SERVE", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def idle_seconds() -> float:
    raw = os.environ.get("WINDHOVER_ENGINE_IDLE_S")
    if raw is None or str(raw).strip() == "":
        return 600.0
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):
        return 600.0


def encode_whgen(
    prompt: str,
    *,
    ngen: int,
    temp: float,
    topk: int,
    topp: float,
    spec: int,
) -> bytes:
    body = (prompt or "").encode("utf-8")
    if len(body) > MAX_PROMPT_BYTES:
        body = body[:MAX_PROMPT_BYTES]
    header = f"WHGEN {int(ngen)} {float(temp):.4f} {int(topk)} {float(topp):.4f} {len(body)} {int(spec)}\n"
    return header.encode("ascii") + body


def parse_stats_blob(raw: bytes) -> tuple[bytes, dict]:
    """Split trailing @@WH_STATS@@ JSON (and END sentinel) from token bytes."""
    text = raw or b""
    if END in text:
        text = text.split(END, 1)[0]
    if STATS_MARK not in text:
        return text, {}
    head, _, tail = text.partition(STATS_MARK)
    line = tail.splitlines()[0] if tail else b""
    stats: dict = {}
    try:
        stats = json.loads(line.decode("utf-8", errors="replace").strip())
        if not isinstance(stats, dict):
            stats = {}
    except Exception:
        stats = {}
    return head, stats


def _dec(b: bytes) -> str:
    return (b or b"").decode("utf-8", errors="replace")


class EngineSession:
    """Owns at most one windhover-engine SERVE process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._err_buf: list[bytes] = []
        self._err_thread: threading.Thread | None = None
        self._identity: tuple | None = None
        self._last_used = 0.0
        self._idle_stop = threading.Event()
        self._watcher: threading.Thread | None = None

    def is_warm(self) -> bool:
        proc = self._proc
        return bool(proc and proc.poll() is None)

    def identity(self) -> tuple | None:
        return self._identity

    def status(self) -> dict:
        with self._lock:
            warm = self.is_warm()
            ident = self._identity
            return {
                "engine_warm": warm,
                "snap": ident[0] if ident else None,
                "ram_gb": ident[1] if ident else None,
                "mlock": ident[2] if ident else None,
                "sparse": ident[3] if ident else None,
            }

    def unload(self, reason: str = "unload") -> None:
        with self._lock:
            self._kill_locked(reason)

    def generate(
        self,
        *,
        engine_bin: Path,
        cwd: Path,
        env: dict[str, str],
        prompt: str,
        ngen: int,
        timeout_s: float,
        on_delta: Callable[[str], None] | None = None,
        log: TextIO | None = None,
    ) -> tuple[str, dict, str, int]:
        """Run one turn on the warm process (spawn/reload as needed).

        Returns (raw_text, wh_stats, stderr, returncode).
        returncode 0 means the turn finished; the process may still be alive.
        """
        ident = self._ident_from_env(env)
        t0 = time.perf_counter()
        with self._lock:
            try:
                self._ensure_locked(engine_bin, cwd, env, ident, timeout_s, t0, log)
                return self._turn_locked(prompt, ngen, env, timeout_s, t0, on_delta)
            except Exception:
                self._kill_locked("generate-error")
                raise

    def oneshot(
        self,
        *,
        engine_bin: Path,
        cwd: Path,
        env: dict[str, str],
        timeout_s: float,
        on_delta: Callable[[str], None] | None = None,
    ) -> tuple[bytes, str, int]:
        """Legacy spawn-per-turn path (also the SERVE fallback)."""
        t0 = time.perf_counter()
        if on_delta is None:
            try:
                p = subprocess.run(
                    [str(engine_bin), "64", "4", "4"],
                    cwd=str(cwd),
                    env=env,
                    capture_output=True,
                    timeout=timeout_s,
                )
            except subprocess.TimeoutExpired as e:
                raise TimeoutError(
                    f"windhover-engine timed out after {int(timeout_s)}s"
                ) from e
            return p.stdout or b"", _dec(p.stderr), int(p.returncode)
        proc = subprocess.Popen(
            [str(engine_bin), "64", "4", "4"],
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        err_buf: list[bytes] = []

        def _drain() -> None:
            try:
                if proc.stderr is not None:
                    err_buf.append(proc.stderr.read() or b"")
            except Exception:
                pass

        err_thread = threading.Thread(target=_drain, daemon=True)
        err_thread.start()
        chunks: list[bytes] = []
        pending = b""
        timed_out = False
        try:
            while True:
                if time.perf_counter() - t0 > timeout_s:
                    timed_out = True
                    proc.kill()
                    break
                if proc.stdout is None:
                    break
                b = proc.stdout.read(64)
                if not b:
                    break
                chunks.append(b)
                pending += b
                emit, pending = self._split_emit(pending)
                if emit:
                    try:
                        on_delta(_dec(emit))
                    except Exception:
                        proc.kill()
                        raise
        finally:
            self._wait_proc(proc, 5)
            err_thread.join(timeout=2)
        raw = b"".join(chunks)
        err = _dec(b"".join(err_buf))
        rc = proc.returncode if proc.returncode is not None else -1
        if timed_out:
            raise TimeoutError(f"windhover-engine timed out after {int(timeout_s)}s")
        return raw, err, rc

    # ---- internals -------------------------------------------------

    @staticmethod
    def _ident_from_env(env: dict[str, str]) -> tuple:
        snap = env.get("SNAP") or ""
        ram = env.get("RAM_GB") or ""
        mlock = env.get("MLOCK") or "1"
        sparse = env.get("WH_SPARSE") or "25"
        ctx = env.get("CTX") or ""
        return (snap, ram, mlock, sparse, ctx)

    def _ensure_locked(
        self,
        engine_bin: Path,
        cwd: Path,
        env: dict[str, str],
        ident: tuple,
        timeout_s: float,
        t0: float,
        log: TextIO | None,
    ) -> None:
        if self._proc is not None and self._proc.poll() is not None:
            self._kill_locked("died")
        if self._proc is not None and self._identity != ident:
            self._kill_locked("reload")
        if self._proc is not None:
            return
        serve_env = dict(env)
        serve_env["SERVE"] = "1"
        serve_env["WH_JSON_STATS"] = "1"
        serve_env["QUIET"] = serve_env.get("QUIET") or "1"
        serve_env.pop("PROMPT", None)
        serve_env.pop("COLI_PROMPT", None)
        if log:
            log.write(f"[windhover] starting warm engine SNAP={ident[0]}\n")
            log.flush()
        proc = subprocess.Popen(
            [str(engine_bin), "64", "4", "4"],
            cwd=str(cwd),
            env=serve_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._proc = proc
        self._identity = ident
        self._err_buf = []
        self._err_thread = threading.Thread(
            target=self._drain_err, args=(proc,), daemon=True
        )
        self._err_thread.start()
        self._last_used = time.monotonic()
        self._ensure_idle_watcher()
        # Load can be tens of seconds on a 7B pack.
        ready_budget = max(30.0, min(timeout_s, 180.0))
        if not self._wait_ready(proc, ready_budget, t0):
            err = _dec(b"".join(self._err_buf))
            self._kill_locked("no-ready")
            raise RuntimeError(
                "windhover-engine SERVE did not signal READY "
                f"(stderr={err[:500]!r})"
            )

    def _wait_ready(self, proc: subprocess.Popen, budget: float, t0: float) -> bool:
        stdout = proc.stdout
        if stdout is None:
            return False
        buf = b""
        deadline = t0 + budget
        while time.perf_counter() < deadline:
            if proc.poll() is not None:
                return False
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return False
            try:
                chunk = stdout.read(1)
            except Exception:
                return False
            if not chunk:
                time.sleep(0.01)
                continue
            buf += chunk
            if len(buf) > 4096:
                buf = buf[-64:]
            if READY in buf:
                return True
            if STATS_MARK in buf or END in buf:
                return False
            if len(buf) > 256 and READY not in buf:
                return False
        return False

    def _turn_locked(
        self,
        prompt: str,
        ngen: int,
        env: dict[str, str],
        timeout_s: float,
        t0: float,
        on_delta: Callable[[str], None] | None,
    ) -> tuple[str, dict, str, int]:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.stdout is None:
            raise RuntimeError("warm engine missing stdio")
        try:
            temp = float(env.get("TEMP") or 0)
        except (TypeError, ValueError):
            temp = 0.0
        try:
            topk = int(float(env.get("TOPK") or 0))
        except (TypeError, ValueError):
            topk = 0
        try:
            topp = float(env.get("TOPP") or 0)
        except (TypeError, ValueError):
            topp = 0.0
        spec = 1 if (env.get("WH_SPEC") or "0") not in ("0", "false") and temp <= 0 else 0
        blob = encode_whgen(
            prompt, ngen=ngen, temp=temp, topk=topk, topp=topp, spec=spec
        )
        try:
            proc.stdin.write(blob)
            proc.stdin.flush()
        except BrokenPipeError as e:
            self._kill_locked("pipe")
            raise RuntimeError("warm engine stdin closed") from e
        chunks: list[bytes] = []
        pending = b""
        timed_out = False
        while True:
            if time.perf_counter() - t0 > timeout_s:
                timed_out = True
                break
            if proc.poll() is not None:
                rest = proc.stdout.read() or b""
                pending += rest
                chunks.append(rest)
                break
            b = proc.stdout.read(64)
            if not b:
                if proc.poll() is not None:
                    break
                continue
            chunks.append(b)
            pending += b
            emit, pending, done = self._split_serve_emit(pending)
            if emit and on_delta:
                try:
                    on_delta(_dec(emit))
                except Exception:
                    self._kill_locked("delta-abort")
                    raise
            if done:
                break
        raw = b"".join(chunks)
        err = _dec(b"".join(self._err_buf))
        if timed_out:
            self._kill_locked("timeout")
            raise TimeoutError(f"windhover-engine timed out after {int(timeout_s)}s")
        if END not in raw:
            rc = proc.returncode if proc.returncode is not None else -1
            self._kill_locked("no-end")
            text, stats = parse_stats_blob(raw)
            return _dec(text).strip(), stats, err, rc if rc is not None else 1
        text_b, stats = parse_stats_blob(raw)
        self._last_used = time.monotonic()
        self._err_buf = []
        return _dec(text_b), stats, err, 0

    @staticmethod
    def _split_emit(pending: bytes) -> tuple[bytes, bytes]:
        if STATS_MARK in pending:
            emit, _, _ = pending.partition(STATS_MARK)
            return emit, b""
        emit, pending = pending, b""
        for back in range(1, min(4, len(emit)) + 1):
            if emit[-back] & 0xC0 == 0xC0:
                pending = emit[-back:]
                emit = emit[:-back]
                break
        return emit, pending

    @staticmethod
    def _split_serve_emit(pending: bytes) -> tuple[bytes, bytes, bool]:
        done = END in pending
        work = pending.split(END, 1)[0] if done else pending
        if STATS_MARK in work:
            emit, _, tail = work.partition(STATS_MARK)
            # Keep the stats marker in pending until END so parse_stats_blob sees it.
            return emit, STATS_MARK + tail + (END if done else b""), done
        emit = work
        hold = b""
        if not done:
            for back in range(1, min(4, len(emit)) + 1):
                if emit[-back] & 0xC0 == 0xC0:
                    hold = emit[-back:]
                    emit = emit[:-back]
                    break
            # Hold back a partial END sentinel (up to 8 bytes).
            if emit.endswith(END[:1]) or emit.endswith(END[:2]) or emit.endswith(b"\x01"):
                # keep last few bytes in case END is split across reads
                keep = min(len(END) - 1, len(emit))
                hold = emit[-keep:] + hold
                emit = emit[:-keep]
        return emit, hold if not done else b"", done

    def _drain_err(self, proc: subprocess.Popen) -> None:
        try:
            if proc.stderr is None:
                return
            while True:
                b = proc.stderr.read(256)
                if not b:
                    break
                self._err_buf.append(b)
                if sum(len(x) for x in self._err_buf) > 64_000:
                    self._err_buf = self._err_buf[-8:]
        except Exception:
            pass

    def _ensure_idle_watcher(self) -> None:
        if self._watcher and self._watcher.is_alive():
            return
        self._idle_stop.clear()
        self._watcher = threading.Thread(target=self._idle_loop, daemon=True, name="wh-engine-idle")
        self._watcher.start()

    def _idle_loop(self) -> None:
        while True:
            idle = idle_seconds()
            slice_s = min(15.0, max(0.5, idle / 3.0))
            if self._idle_stop.wait(slice_s):
                break
            with self._lock:
                if self._proc is None:
                    continue
                if time.monotonic() - self._last_used >= idle:
                    self._kill_locked("idle")

    def _kill_locked(self, reason: str) -> None:
        proc = self._proc
        self._proc = None
        self._identity = None
        if proc is None:
            return
        try:
            if proc.stdin:
                try:
                    proc.stdin.write(b"WHQUIT\n")
                    proc.stdin.flush()
                except Exception:
                    pass
                try:
                    proc.stdin.close()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            proc.wait(timeout=1.5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream:
                    stream.close()
            except Exception:
                pass
        self._err_buf = []

    @staticmethod
    def _wait_proc(proc: subprocess.Popen, timeout: float) -> None:
        try:
            proc.wait(timeout=timeout)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                pass


SESSION = EngineSession()
