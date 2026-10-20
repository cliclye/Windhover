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
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        ctype = resp.headers.get("Content-Type", "")
        raw = resp.read(max_bytes)
        charset = resp.headers.get_content_charset() or "utf-8"
        try:
            text = raw.decode(charset, errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")
        return getattr(resp, "status", 200), ctype, resp.geturl(), text


_SSL_CTX: list = []


def _ssl_context():
    """TLS context that can verify sites even inside the frozen app.

    A PyInstaller build has no system OpenSSL cert directory, so the default
    context rejects every HTTPS site ("unable to get local issuer certificate")
    and web search wrongly looks offline. Prefer certifi's bundle, then the
    OS bundle, then Python's default.
    """
    if _SSL_CTX:
        return _SSL_CTX[0]
    import ssl

    ctx = None
    candidates: list[str] = []
    try:
        import certifi  # type: ignore

        candidates.append(certifi.where())
    except Exception:
        pass
    candidates += ["/etc/ssl/cert.pem", "/private/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"]
    for cafile in candidates:
        try:
            if os.path.isfile(cafile):
                ctx = ssl.create_default_context(cafile=cafile)
                break
        except Exception:
            continue
    if ctx is None:
        ctx = ssl.create_default_context()
    _SSL_CTX.append(ctx)
    return ctx


def is_online(timeout: float = 4.0, *, max_age: float = 20.0) -> bool:
    """True when the open internet is reachable (cached for ``max_age`` seconds)."""
    now = time.time()
    if now - _ONLINE["t"] < max_age:
        return bool(_ONLINE["ok"])
    ok = False
    err = ""
    for url in ("https://duckduckgo.com/", "https://www.bing.com/", "https://1.1.1.1/"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
            urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()).close()
            ok = True
        except urllib.error.HTTPError:
            ok = True  # the server answered — we are online
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            continue
        break
    _ONLINE.update(t=now, ok=ok, err="" if ok else err)
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


# ── News ─────────────────────────────────────────────────────────────────────

_NEWS_WORDS = re.compile(
    r"\b(news|happen(?:ed|ing|s)?|happend|breaking|latest|today|yesterday|tonight|tomorrow|"
    r"this (?:week|morning|month|weekend)|last (?:night|week|month)|\d+ (?:minutes?|hours?|days?|weeks?) ago|"
    r"recent(?:ly)?|just (?:now|announced|released)|riots?|protests?|attacks?|election|shooting|"
    r"earthquake|announce(?:d|ment)|scores?|update|outcome|aftermath|what(?:'s| is) going on)\b",
    re.I,
)
# Signals that the question is about an event, not a lookup — news only, no generic web noise.
_NEWS_STRONG = re.compile(
    r"\b(news|happen(?:ed|ing)?|happend|breaking|yesterday|tonight|last night|\d+ (?:hours?|days?|weeks?) ago|"
    r"riots?|aftermath)\b",
    re.I,
)


def news_intent(query: str) -> bool:
    return bool(_NEWS_WORDS.search(query or ""))


def _rss_items(xml: str) -> list[dict]:
    out = []
    for it in re.findall(r"<item>(.*?)</item>", xml or "", re.S):
        def tag(name: str) -> str:
            m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", it, re.S)
            if not m:
                return ""
            v = m.group(1).strip()
            v = re.sub(r"^<!\[CDATA\[(.*?)\]\]>$", r"\1", v, flags=re.S)
            return unescape(v)

        out.append({
            "title": _strip_tags(tag("title")),
            "link": tag("link"),
            "pub": tag("pubDate"),
            "desc": _strip_tags(tag("description")),
            "source": _strip_tags(tag("News:Source") or tag("source")),
        })
    return out


def _short_date(pub: str) -> str:
    m = re.match(r"\w{3}, (\d{1,2} \w{3} \d{4})", pub or "")
    return m.group(1) if m else ""


def _resolve_google_news(link: str, timeout: float = 6.0) -> str:
    """news.google.com/rss/articles/<id> → the publisher's real URL ("" if it can't)."""
    try:
        gid = link.split("/articles/")[1].split("?")[0]
        _, _, _, html = _http_get(
            f"https://news.google.com/articles/{gid}?hl=en-US&gl=US&ceid=US:en", timeout=timeout
        )
        ts = re.search(r'data-n-a-ts="([^"]+)"', html)
        sg = re.search(r'data-n-a-sg="([^"]+)"', html)
        if not (ts and sg):
            return ""
        inner = json.dumps([
            "garturlreq",
            [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
             "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
            gid, int(ts.group(1)), sg.group(1),
        ])
        req = urllib.request.Request(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            data=urlencode({"f.req": json.dumps([[["Fbv4je", inner, None, "generic"]]])}).encode(),
            headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
            m = re.search(r'garturlres\\",\\"(https?:[^"\\]+)', r.read().decode("utf-8", "replace"))
        return m.group(1) if m else ""
    except Exception:
        return ""


_RECENT = re.compile(r"\b(yesterday|today|tonight|last night|this (?:morning|week)|\d+ (?:minutes?|hours?|days?) ago|just now)\b", re.I)


def news_query(query: str) -> tuple[str, str]:
    """(topic words for a news feed, recency operator): the feed wants "Vitality headquarters
    France riot", not the whole sentence, and "2 days ago" means "when:7d"."""
    recent = "when:7d" if _RECENT.search(query) else ""
    q = re.sub(r"\b(what|how|why)\s+(?:has|had|have|is|are|was|were)?\s*(?:happen(?:ed|ing|s)?|going on)\s*(?:to|with|at|in|after)?\b", " ", query, flags=re.I)
    q = _RECENT.sub(" ", q)
    q = re.sub(r"\b(?:the|a|an|after|since|about|of|latest|recent|recently|news)\b", " ", q, flags=re.I)
    q = re.sub(r"\s+", " ", q).strip(" ?!.,")
    return (q if len(q.split()) >= 2 else re.sub(r"\s+", " ", query).strip()), recent


def news_search(query: str, max_results: int = 8, timeout: float = 8.0) -> list[dict]:
    """Recent headlines from Google News (+ Bing News) as [{title, url, snippet}]."""
    topic, recent = news_query(query)

    def fetch(name: str, recency: str) -> list[dict]:
        q = quote_plus(f"{topic} {recency}".strip())
        url = {
            "google": f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en",
            "bing": f"https://www.bing.com/news/search?q={q}&format=rss&setlang=en",
        }[name]
        try:
            return _rss_items(_http_get(url, timeout=timeout)[3])
        except Exception:
            return []

    items: dict[str, list[dict]] = {n: fetch(n, recent) for n in ("google", "bing")}
    if recent and len(items["google"]) + len(items["bing"]) < 3:
        items = {n: fetch(n, "") for n in ("google", "bing")}

    rows: list[dict] = []
    # Google News links are opaque redirects; resolve the top ones to real article URLs.
    g = items["google"][: max_results]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        resolved = list(pool.map(lambda it: _resolve_google_news(it["link"]), g[:4]))
    for i, it in enumerate(g):
        url = (resolved[i] if i < len(resolved) else "") or it["link"]
        title = re.sub(r"\s+-\s+" + re.escape(it["source"] or "\0") + r"$", "", it["title"]) if it["source"] else it["title"]
        meta = " · ".join(x for x in (_short_date(it["pub"]), it["source"]) if x)
        rows.append({"title": title, "url": url, "snippet": f"{meta}. {it['desc']}" if meta else it["desc"]})
    for it in items["bing"][: max_results]:
        m = parse_qs(urlparse(unescape(it["link"])).query).get("url")
        url = m[0] if m else it["link"]
        meta = " · ".join(x for x in (_short_date(it["pub"]), it["source"]) if x)
        rows.append({"title": it["title"], "url": url, "snippet": f"{meta}. {it['desc']}" if meta else it["desc"]})

    # Interleave Google / Bing, newest-relevant first, no duplicates.
    seen, uniq = set(), []
    for r in rows:
        key = r["url"].split("?")[0].rstrip("/") if "news.google.com" not in r["url"] else r["url"]
        if r["url"].startswith("http") and key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq[:max_results]


def search(query: str, max_results: int = 8, timeout: float = 8.0) -> list[dict]:
    """Web results [{title, url, snippet}] for ``query``. Raises WebSearchError."""
    query = re.sub(r"\s+", " ", query or "").strip()[:300]
    if not query:
        return []
    errors = []
    news: list[dict] = []
    if news_intent(query):
        try:
            news = news_search(query, max_results, timeout)
        except Exception as e:
            errors.append(f"news: {type(e).__name__}: {e}")
        if len(news) >= 4 and _NEWS_STRONG.search(query):
            return news[:max_results]
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
            for r in news + rows:
                key = r["url"].rstrip("/")
                if key not in seen:
                    seen.add(key)
                    uniq.append(r)
            return uniq[:max_results]
        errors.append(f"{name}: no results")
    if news:
        return news[:max_results]
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


_LEAD = re.compile(
    r"^(?:(?:hey|hi|yo|ok|okay|so|bruh|well)\b[\s,!.]*|"
    r"(?:can|could|would|will|did)\s+(?:you|u|ya)\b[\s,]*(?:please|pls|just|kindly|go|actually)?\b[\s,]*|"
    r"(?:please|pls|just|kindly|go)\b[\s,]*|"
    r"(?:i\s+(?:want|wanna|need|would like)\s+(?:you\s+)?to\s+(?:know|find out)|let me know|tell me(?:\s+about)?)\b[\s,]*|"
    r"(?:look\s*up|look\s+into|search(?:\s+(?:the\s+)?(?:web|internet|online|google|news))?(?:\s+for)?|"
    r"google|find(?:\s+out)?|research|check)\b[\s,]*(?:for|up|about|on)?\b[\s,]*)",
    re.I,
)
_TRAIL = re.compile(
    r"[\s,]*(?:for me|please|pls|thanks|thank you|on (?:the )?(?:web|internet|news|google)|"
    r"(?:using|with|on) (?:google|the web|the internet)(?: news)?)[\s?!.]*$",
    re.I,
)


def clean_query(text: str) -> str:
    """Chat filler off a request so the search engine sees the topic:
    "can u just look up what happened to X?" → "what happened to X"."""
    q = re.sub(r"\s+", " ", text or "").strip()
    for _ in range(6):
        n = _LEAD.sub("", q, count=1).strip()
        n = _TRAIL.sub("", n).strip()
        if n == q:
            break
        q = n
    q = re.sub(r"\bhappend\b", "happened", q, flags=re.I)
    q = q.strip(" ,")
    return q or re.sub(r"\s+", " ", text or "").strip()


def search_query(messages: list) -> str:
    """The search query for this turn: the last user message (minus chat filler), plus the
    previous one when the new message is a short follow-up ("and in 2025?")."""
    users = [_content_text(m.get("content")).strip() for m in messages if m.get("role") == "user"]
    users = [u for u in users if u]
    if not users:
        return ""
    q = clean_query(users[-1])
    if len(users) > 1 and len(q.split()) <= 5:
        q = f"{clean_query(users[-2])} {q}"
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
