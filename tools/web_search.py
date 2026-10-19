"""Web search for Windhover Chat: find fresh sources and hand them to the local model.

Stdlib only (urllib + html.parser) so it ships inside the PyInstaller sidecar.
Searches DuckDuckGo's HTML endpoint and falls back to Bing; set
WINDHOVER_SEARCH_URL to a SearXNG instance (``https://searx.example``) to use
that instead. Nothing here runs unless the user allowed web access in the app.

Two modes:
  search    one query (the user's message), read the top few pages
  research  the local model plans several queries, more pages are read
"""
from __future__ import annotations

import base64
import concurrent.futures
import ipaddress
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from datetime import date
from html import unescape
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import parse_qs, quote_plus, urlencode, urlparse

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)

MODES = ("search", "research")
# Character budgets for page text handed to the model (engine CTX is 8192 tokens).
BUDGET = {"search": 4500, "research": 9000}
MAX_PAGES = {"search": 3, "research": 6}
MAX_SOURCES = {"search": 5, "research": 8}
PER_SOURCE_CHARS = 1500

_ONLINE: dict = {"t": 0.0, "ok": False}

Progress = Callable[[str, str], None]


class WebSearchError(RuntimeError):
    pass


# ── HTTP ─────────────────────────────────────────────────────────────────────


def _http_get(
    url: str,
    *,
    data: dict | None = None,
    timeout: float = 8.0,
    max_bytes: int = 1_500_000,
) -> tuple[int, str, str, str]:
    """GET (or form POST) → (status, content_type, final_url, text)."""
    body = urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.5",
            "Accept-Language": "en-US,en;q=0.8",
        },
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("Content-Type", "")
        raw = resp.read(max_bytes)
        charset = resp.headers.get_content_charset() or "utf-8"
        try:
            text = raw.decode(charset, errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")
        return getattr(resp, "status", 200), ctype, resp.geturl(), text


def is_online(timeout: float = 2.5, *, max_age: float = 20.0) -> bool:
    """True when the open internet is reachable (cached for ``max_age`` seconds)."""
    now = time.time()
    if now - _ONLINE["t"] < max_age:
        return bool(_ONLINE["ok"])
    ok = False
    for url in ("https://duckduckgo.com/", "https://www.bing.com/", "https://1.1.1.1/"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
            urllib.request.urlopen(req, timeout=timeout).close()
            ok = True
        except urllib.error.HTTPError:
            ok = True  # the server answered — we are online
        except Exception:
            continue
        break
    _ONLINE.update(t=now, ok=ok)
    return ok


def public_http_url(url: str) -> bool:
    """Only fetch http(s) pages on public hosts — never localhost or the LAN."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        infos = socket.getaddrinfo(p.hostname, None)
    except (OSError, ValueError, UnicodeError):
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            return False
    return bool(infos)


# ── Result parsing ───────────────────────────────────────────────────────────


def _strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def _ddg_target(href: str) -> str:
    """//duckduckgo.com/l/?uddg=<url> → <url>; drop ad redirects."""
    href = unescape(href or "")
    if href.startswith("//"):
        href = "https:" + href
    p = urlparse(href)
    if p.hostname and p.hostname.endswith("duckduckgo.com"):
        if p.path.startswith("/y.js"):
            return ""
        return (parse_qs(p.query).get("uddg") or [""])[0]
    return href


def _bing_target(href: str) -> str:
    """bing.com/ck/a?...&u=a1<base64url> → real URL."""
    href = unescape(href or "")
    p = urlparse(href)
    if p.hostname and p.hostname.endswith("bing.com") and p.path.startswith("/ck/"):
        u = (parse_qs(p.query).get("u") or [""])[0]
        if u.startswith("a1"):
            u = u[2:]
            try:
                return base64.urlsafe_b64decode(u + "=" * (-len(u) % 4)).decode("utf-8", "replace")
            except (ValueError, UnicodeError):
                return ""
        return ""
    return href


def parse_ddg_html(html: str) -> list[dict]:
    out = []
    blocks = re.split(r'<div[^>]+class="[^"]*\bresult\b', html)[1:]
    for block in blocks:
        head = block[:200]
        if "result--ad" in head:
            continue
        a = re.search(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not a:
            a = re.search(r'<a[^>]+href="([^"]+)"[^>]+class="[^"]*result__a[^"]*"[^>]*>(.*?)</a>', block, re.S)
        if not a:
            continue
        url = _ddg_target(a.group(1))
        snip = re.search(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|div|td)>', block, re.S)
        if url.startswith("http"):
            out.append({
                "title": _strip_tags(a.group(2)),
                "url": url,
                "snippet": _strip_tags(snip.group(1)) if snip else "",
            })
    return out


def parse_bing_html(html: str) -> list[dict]:
    out = []
    for block in re.split(r'<li[^>]+class="[^"]*\bb_algo\b', html)[1:]:
        a = re.search(r"<h2[^>]*>.*?<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>", block, re.S)
        if not a:
            continue
        url = _bing_target(a.group(1))
        snip = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        if url.startswith("http"):
            out.append({
                "title": _strip_tags(a.group(2)),
                "url": url,
                "snippet": _strip_tags(snip.group(1)) if snip else "",
            })
    return out


def _searx(base: str, query: str, timeout: float) -> list[dict]:
    _, _, _, text = _http_get(
        f"{base.rstrip('/')}/search?q={quote_plus(query)}&format=json", timeout=timeout
    )
    rows = json.loads(text).get("results") or []
    return [
        {"title": str(r.get("title") or ""), "url": str(r.get("url") or ""), "snippet": str(r.get("content") or "")}
        for r in rows
        if str(r.get("url") or "").startswith("http")
    ]


def search(query: str, max_results: int = 8, timeout: float = 8.0) -> list[dict]:
    """Web results [{title, url, snippet}] for ``query``. Raises WebSearchError."""
    query = re.sub(r"\s+", " ", query or "").strip()[:300]
    if not query:
        return []
    errors = []
    providers: list[tuple[str, Callable[[], list[dict]]]] = []
    searx = os.environ.get("WINDHOVER_SEARCH_URL", "").strip()
    if searx:
        providers.append(("searxng", lambda: _searx(searx, query, timeout)))
    providers += [
        ("duckduckgo", lambda: parse_ddg_html(
            _http_get("https://html.duckduckgo.com/html/", data={"q": query}, timeout=timeout)[3])),
        ("bing", lambda: parse_bing_html(
            _http_get(f"https://www.bing.com/search?q={quote_plus(query)}&setlang=en", timeout=timeout)[3])),
    ]
    for name, run in providers:
        try:
            rows = run()
        except Exception as e:  # network, HTTP error, captcha page, bad JSON
            errors.append(f"{name}: {type(e).__name__}: {e}")
            continue
        if rows:
            seen, uniq = set(), []
            for r in rows:
                key = r["url"].rstrip("/")
                if key not in seen:
                    seen.add(key)
                    uniq.append(r)
            return uniq[:max_results]
        errors.append(f"{name}: no results")
    raise WebSearchError("web search failed — " + "; ".join(errors))


# ── Page reading ─────────────────────────────────────────────────────────────


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form",
            "aside", "iframe", "button", "select", "template", "canvas"}
    BLOCK = {"p", "div", "li", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
             "section", "article", "blockquote", "pre", "table", "ul", "ol", "dd", "dt"}
    VOID = {"br", "img", "hr", "input", "meta", "link", "source", "wbr", "area", "col"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        lines = (re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in "".join(self.parts).split("\n"))
        return "\n".join(ln for ln in lines if ln)


def html_to_text(html: str) -> tuple[str, str]:
    """HTML → (title, readable text)."""
    p = _TextExtractor()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    return re.sub(r"\s+", " ", p.title).strip(), p.text()


def fetch_text(url: str, timeout: float = 8.0) -> tuple[str, str]:
    """Download a public page and return (title, text). Raises on failure."""
    if not public_http_url(url):
        raise WebSearchError("not a public http(s) URL")
    status, ctype, final, body = _http_get(url, timeout=timeout)
    if final != url and not public_http_url(final):
        raise WebSearchError("redirected to a non-public URL")
    if "html" in ctype or not ctype:
        return html_to_text(body)
    if ctype.startswith("text/"):
        return "", body
    raise WebSearchError(f"unsupported content type {ctype}")


_STOP = set(
    "a an and are as at be by can do does for from has have how i in is it its me my of on or "
    "so that the their there these this to was what when where which who why will with you your "
    "about tell give show find latest recent current new news today now please".split()
)


def keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9\-\.]*", (text or "").lower()) if w not in _STOP and len(w) > 1}


def best_passages(text: str, query: str, budget: int = PER_SOURCE_CHARS) -> str:
    """The parts of ``text`` most relevant to ``query``, in reading order, within ``budget`` chars."""
    chunks: list[str] = []
    cur = ""
    for para in (text or "").split("\n"):
        if len(para) < 25 and not re.search(r"\d", para):
            continue  # menu items, buttons, bylines
        if cur and len(cur) + len(para) > 600:
            chunks.append(cur)
            cur = ""
        cur = f"{cur} {para}".strip()
    if cur:
        chunks.append(cur)
    if not chunks:
        return ""
    kw = keywords(query)

    def score(i: int) -> float:
        words = keywords(chunks[i])
        return len(kw & words) * 2 + (0.5 if re.search(r"\b20\d\d\b", chunks[i]) else 0) - i * 0.01

    picked: list[int] = []
    used = 0
    for i in sorted(range(len(chunks)), key=score, reverse=True):
        c = chunks[i][: budget - used] if not picked else chunks[i]
        if used + len(c) > budget:
            continue
        picked.append(i)
        used += len(c) + 2
        if used >= budget * 0.9:
            break
    return "\n…\n".join(chunks[i][:budget] for i in sorted(picked))


# ── Queries ──────────────────────────────────────────────────────────────────


def _content_text(content) -> str:
    if isinstance(content, list):  # OpenAI-style parts
        return " ".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    return str(content or "")


def search_query(messages: list) -> str:
    """The search query for this turn: the last user message, plus the previous
    one when the new message is a short follow-up ("and in 2025?")."""
    users = [_content_text(m.get("content")).strip() for m in messages if m.get("role") == "user"]
    users = [u for u in users if u]
    if not users:
        return ""
    q = users[-1]
    if len(users) > 1 and len(q.split()) <= 5:
        q = f"{users[-2]} {q}"
    return re.sub(r"\s+", " ", q).strip()[:300]


def plan_messages(question: str, *, today: date | None = None) -> list[dict]:
    """Prompt asking the local model for search queries (research mode)."""
    d = (today or date.today()).isoformat()
    return [{
        "role": "user",
        "content": (
            f"Today is {d}. Write 3 short web search queries that together would find "
            "current, reliable information to answer the question below. "
            "Output only the queries, one per line, with no numbering or explanation.\n\n"
            f"Question: {question}"
        ),
    }]


def parse_queries(text: str, question: str, n: int = 3) -> list[str]:
    """Model output → up to ``n`` clean queries; always includes something usable."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    out: list[str] = []
    for line in text.splitlines():
        q = re.sub(r"^\s*(?:[-*•]|\d+[.)]|query\s*\d*:)\s*", "", line, flags=re.I).strip().strip("\"'`")
        if not q or len(q) > 160 or q.endswith(":") or len(q.split()) < 2:
            continue
        if q.lower() not in (x.lower() for x in out):
            out.append(q)
        if len(out) >= n:
            break
    if not out:
        q = question[:200]
        out = [q, f"{q} {(date.today()).year}"]
    return out


# ── Gathering ────────────────────────────────────────────────────────────────


def _domain(url: str) -> str:
    host = urlparse(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


def gather(
    queries: list[str],
    *,
    mode: str = "search",
    question: str = "",
    on_progress: Progress | None = None,
    searcher: Callable[[str], list[dict]] | None = None,
    fetcher: Callable[[str], tuple[str, str]] | None = None,
) -> list[dict]:
    """Search ``queries``, read the top pages, and return numbered sources:
    [{n, title, url, domain, snippet, content}]."""
    mode = mode if mode in MODES else "search"
    searcher = searcher or search
    fetcher = fetcher or fetch_text
    say = on_progress or (lambda stage, msg: None)
    question = question or (queries[0] if queries else "")

    per_query: list[list[dict]] = []
    errors: list[str] = []
    for q in queries:
        say("search", f"Searching the web for “{q}”")
        try:
            per_query.append(searcher(q))
        except Exception as e:
            errors.append(str(e))
    # Interleave so every query contributes its best hits.
    results: list[dict] = []
    seen: set[str] = set()
    for rank in range(max((len(r) for r in per_query), default=0)):
        for rows in per_query:
            if rank < len(rows):
                key = rows[rank]["url"].rstrip("/")
                if key not in seen:
                    seen.add(key)
                    results.append(rows[rank])
    results = results[: MAX_SOURCES[mode]]
    if not results:
        raise WebSearchError(errors[0] if errors else "no web results found")

    to_read = results[: MAX_PAGES[mode]]
    say("read", "Reading " + ", ".join(_domain(r["url"]) for r in to_read))
    pages: dict[str, tuple[str, str]] = {}
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(to_read))
    futs = {pool.submit(fetcher, r["url"]): r["url"] for r in to_read}
    try:
        for fut in concurrent.futures.as_completed(futs, timeout=25):
            try:
                pages[futs[fut]] = fut.result()
            except Exception:
                pass  # paywall, timeout, PDF … the snippet still counts
    except concurrent.futures.TimeoutError:
        pass  # slow sites don't hold up the answer
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    per_source = min(PER_SOURCE_CHARS, BUDGET[mode] // max(1, len(pages) or 1))
    sources = []
    for i, r in enumerate(results, 1):
        title, text = pages.get(r["url"], ("", ""))
        content = best_passages(text, f"{question} {' '.join(queries)}", per_source) if text else ""
        sources.append({
            "n": i,
            "title": (r.get("title") or title or _domain(r["url"]))[:200],
            "url": r["url"],
            "domain": _domain(r["url"]),
            "snippet": (r.get("snippet") or "")[:400],
            "content": content,
        })
    say("done", f"Found {len(sources)} sources")
    return sources


def sanitize_sources(raw) -> list[dict]:
    """Sources echoed back by the app in a chat request → bounded, well-formed."""
    out = []
    if not isinstance(raw, list):
        return out
    for i, s in enumerate(raw[:10], 1):
        if not isinstance(s, dict):
            continue
        url = str(s.get("url") or "")
        if not url.startswith(("http://", "https://")):
            continue
        out.append({
            "n": i,
            "title": str(s.get("title") or "")[:200],
            "url": url[:600],
            "domain": _domain(url),
            "snippet": str(s.get("snippet") or "")[:400],
            "content": str(s.get("content") or "")[:PER_SOURCE_CHARS + 200],
        })
    return out


def sources_block(sources: list[dict], *, today: date | None = None) -> str:
    d = (today or date.today()).isoformat()
    lines = [f"Web search results (retrieved {d}):", ""]
    for s in sources:
        lines.append(f"[{s['n']}] {s['title']} — {s['domain']}")
        body = s.get("content") or s.get("snippet") or ""
        if body:
            lines.append(body)
        lines.append("")
    return "\n".join(lines).strip()


def augment_messages(messages: list, sources: list[dict], *, today: date | None = None) -> list:
    """Wrap the last user message with the web results so any chat template sees them."""
    if not sources:
        return messages
    idx = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
    if idx < 0:
        return messages
    d = (today or date.today()).isoformat()
    question = _content_text(messages[idx].get("content"))
    content = (
        f"{sources_block(sources, today=today)}\n\n"
        f"Today is {d}. Answer the question below using the web results above where they "
        "are relevant, preferring the most recent information. Cite sources inline by "
        "number, like [1] or [2][3]. If the results don't cover it, say so and answer "
        "from what you know.\n\n"
        f"Question: {question}"
    )
    out = list(messages)
    out[idx] = {**messages[idx], "content": content}
    return out
