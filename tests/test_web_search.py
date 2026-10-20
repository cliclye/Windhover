"""Unit tests for tools/web_search (parsing, passage picking, prompt wrapping — no network)."""
from __future__ import annotations

import base64
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import web_search as ws  # noqa: E402

DDG = """
<div class="result results_links results_links_deep result--ad">
  <h2 class="result__title"><a rel="nofollow" class="result__a" href="//duckduckgo.com/y.js?ad_domain=x">Ad</a></h2>
</div>
<div class="result results_links results_links_deep web-result ">
  <div class="links_main links_deep result__body">
    <h2 class="result__title">
      <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fnews%3Fa%3D1&amp;rut=abc">Example <b>News</b></a>
    </h2>
    <a class="result__snippet" href="//duckduckgo.com/l/?uddg=x">The <b>latest</b> release shipped in 2026.</a>
  </div>
</div>
<div class="result results_links results_links_deep web-result ">
  <h2 class="result__title"><a rel="nofollow" class="result__a" href="https://other.org/page">Other &amp; Co</a></h2>
</div>
"""


def _bing_href(url: str) -> str:
    enc = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    return f"https://www.bing.com/ck/a?!&amp;&amp;p=abc&amp;u=a1{enc}&amp;ntb=1"


BING = f"""
<ol id="b_results">
<li class="b_algo" data-id=""><h2><a href="{_bing_href('https://site.com/a?b=1')}" h="ID=SERP">Site <strong>A</strong></a></h2>
<div class="b_caption"><p class="b_lineclamp2">Snippet for A.</p></div></li>
<li class="b_algo"><h2><a href="https://plain.net/" h="ID=SERP">Plain</a></h2><p>Plain snippet</p></li>
</ol>
"""


class ParseTests(unittest.TestCase):
    def test_ddg(self):
        rows = ws.parse_ddg_html(DDG)
        self.assertEqual([r["url"] for r in rows], ["https://example.com/news?a=1", "https://other.org/page"])
        self.assertEqual(rows[0]["title"], "Example News")
        self.assertEqual(rows[0]["snippet"], "The latest release shipped in 2026.")
        self.assertEqual(rows[1]["title"], "Other & Co")

    def test_bing(self):
        rows = ws.parse_bing_html(BING)
        self.assertEqual([r["url"] for r in rows], ["https://site.com/a?b=1", "https://plain.net/"])
        self.assertEqual(rows[0]["title"], "Site A")
        self.assertEqual(rows[0]["snippet"], "Snippet for A.")

    def test_html_to_text_skips_chrome(self):
        title, text = ws.html_to_text(
            "<html><head><title>T &amp; X</title><style>p{}</style></head><body>"
            "<nav>Home About</nav><h1>Heading</h1><p>First   para.</p><script>var x=1</script>"
            "<p>Second<br>line</p><footer>(c)</footer></body></html>"
        )
        self.assertEqual(title, "T & X")
        self.assertEqual(text, "Heading\nFirst para.\nSecond\nline")


class PassageTests(unittest.TestCase):
    def test_picks_relevant_within_budget(self):
        filler = "\n".join(f"Unrelated paragraph number {i} about gardening and soil." for i in range(30))
        text = filler + "\nThe Windhover 0.7 release adds web search to local chat in October 2026.\n" + filler
        out = ws.best_passages(text, "windhover web search release", budget=300)
        self.assertIn("web search", out)
        self.assertLessEqual(len(out), 320)

    def test_empty(self):
        self.assertEqual(ws.best_passages("", "q"), "")


class QueryTests(unittest.TestCase):
    def test_follow_up_joins_previous(self):
        msgs = [
            {"role": "user", "content": "Who won the 2026 F1 championship?"},
            {"role": "assistant", "content": "…"},
            {"role": "user", "content": "and constructors?"},
        ]
        self.assertEqual(ws.search_query(msgs), "Who won the 2026 F1 championship? and constructors?")

    def test_long_message_alone(self):
        msgs = [{"role": "user", "content": "old"}, {"role": "user", "content": "what is the price of an M5 MacBook Air"}]
        self.assertEqual(ws.search_query(msgs), "what is the price of an M5 MacBook Air")

    def test_parse_queries(self):
        text = "<think>hmm</think>\n1. rust 2026 edition release\n- \"rust edition changes\"\nHere are queries:\nrust"
        self.assertEqual(ws.parse_queries(text, "q"), ["rust 2026 edition release", "rust edition changes"])

    def test_parse_queries_fallback(self):
        self.assertEqual(ws.parse_queries("", "best laptop")[0], "best laptop")


class GatherTests(unittest.TestCase):
    def test_interleaves_dedupes_and_reads(self):
        def searcher(q):
            if q == "a":
                return [{"title": "A1", "url": "https://a.com/1", "snippet": "s"},
                        {"title": "Shared", "url": "https://s.com/", "snippet": "s"}]
            return [{"title": "Shared", "url": "https://s.com", "snippet": "s"},
                    {"title": "B2", "url": "https://www.b.com/2", "snippet": "s"}]

        def fetcher(url):
            if "a.com" in url:
                raise ws.WebSearchError("paywall")
            return "", f"Long enough paragraph describing {url} in some detail for the test."

        stages = []
        out = ws.gather(["a", "b"], mode="search", on_progress=lambda s, m: stages.append(s),
                        searcher=searcher, fetcher=fetcher)
        self.assertEqual([s["url"] for s in out], ["https://a.com/1", "https://s.com", "https://www.b.com/2"])
        self.assertEqual([s["n"] for s in out], [1, 2, 3])
        self.assertEqual(out[0]["content"], "")  # fetch failed → snippet only
        self.assertIn("describing", out[1]["content"])
        self.assertEqual(out[2]["domain"], "b.com")
        self.assertEqual(stages, ["search", "search", "read", "done"])

    def test_all_searches_fail(self):
        def searcher(q):
            raise ws.WebSearchError("blocked")

        with self.assertRaises(ws.WebSearchError):
            ws.gather(["x"], searcher=searcher, fetcher=lambda u: ("", ""))


class PromptTests(unittest.TestCase):
    def test_augment_wraps_last_user_only(self):
        msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"},
                {"role": "user", "content": "latest news?", "images": ["data:x"]}]
        src = ws.sanitize_sources([{"title": "T", "url": "https://n.com/x", "content": "Body text"},
                                   {"url": "javascript:alert(1)"}])
        out = ws.augment_messages(msgs, src, today=date(2026, 10, 19))
        self.assertEqual(out[0], msgs[0])
        self.assertEqual(out[2]["images"], ["data:x"])
        c = out[2]["content"]
        self.assertIn("[1] T — n.com\nBody text", c)
        self.assertIn("Today is 2026-10-19", c)
        self.assertTrue(c.endswith("Question: latest news?"))
        self.assertEqual(len(src), 1)
        self.assertEqual(msgs[2]["content"], "latest news?")  # caller's list untouched

    def test_no_sources_is_noop(self):
        msgs = [{"role": "user", "content": "q"}]
        self.assertIs(ws.augment_messages(msgs, []), msgs)

    def test_public_url_guard(self):
        self.assertFalse(ws.public_http_url("http://127.0.0.1:8000/api/stats"))
        self.assertFalse(ws.public_http_url("http://192.168.1.1/"))
        self.assertFalse(ws.public_http_url("file:///etc/passwd"))


if __name__ == "__main__":
    unittest.main()
