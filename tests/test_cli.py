import io
import json
import re
import ssl
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

from nulltap import __version__
from nulltap.cli import (
    build_parser,
    fetch_feed,
    fetch_feed_document,
    filter_days,
    normalize_item,
    render_article,
    run,
    search_items,
    select_reading_mode,
    FeedError,
)


ITEMS = [
    {
        "id": "2026-07-26-cloud-token",
        "url": "https://nulltap.sh/p/cloud-token/",
        "content_url": "https://nulltap.sh/api/articles/cloud-token.json",
        "title": "Cloud Tokens Became the Perimeter",
        "summary": "An identity failure exposed a cloud control plane.",
        "date_published": "2026-07-26T12:00:00Z",
        "tags": ["cloud", "identity"],
        "read_time_minutes": 6,
        "short_read_available": True,
        "short_read_time_minutes": 1,
        "author": "nulltap",
        "image": "",
    },
    {
        "id": "2026-07-25-ai-gateway",
        "url": "https://nulltap.sh/p/ai-gateway/",
        "content_url": "https://nulltap.sh/api/articles/ai-gateway.json",
        "title": "The AI Gateway Had Root",
        "summary": "A gateway flaw exposed credentials used by production agents.",
        "date_published": "2026-07-25T12:00:00Z",
        "tags": ["ai", "appsec"],
        "read_time_minutes": 4,
        "short_read_available": True,
        "short_read_time_minutes": 1,
        "author": "nulltap",
        "image": "",
    },
]

TOPICS = [
    {"id": "endpoint", "label": "endpoint", "description": "Endpoint security."},
    {"id": "cloud", "label": "cloud", "description": "Cloud security."},
    {"id": "network", "label": "network", "description": "Network security."},
    {"id": "identity", "label": "identity", "description": "Identity security."},
    {"id": "appsec", "label": "appsec", "description": "Application security."},
    {"id": "ai", "label": "AI", "description": "AI security."},
    {"id": "threats", "label": "threats", "description": "Threat activity."},
]


class FakeResponse:
    def __init__(self, payload, url="https://nulltap.sh/feed.json"):
        self.payload = payload
        self.url = url
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self.payload

    def geturl(self):
        return self.url


class TTYBuffer(io.StringIO):
    def isatty(self):
        return True


class NulltapCliTests(unittest.TestCase):
    def test_runtime_and_package_versions_match(self):
        pyproject = Path(__file__).parents[1].joinpath("pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(__version__, match.group(1))

    def invoke(self, args, items=None, opener=None):
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = run(
            args,
            stdout=stdout,
            stderr=stderr,
            feed_loader=lambda _url, _timeout: {
                "items": list(ITEMS if items is None else items),
                "topics": TOPICS,
            },
            article_loader=lambda item, _timeout: {
                **item,
                "content_text": "## Access path\n\nThe token crossed a trust boundary.\n\n[Image: Token path]",
                "short_content_text": "The token crossed a trust boundary. Revoke it and inspect the audit log.",
                "short_read_time_minutes": 1,
                "sources": [{"label": "Primary advisory", "url": "https://example.com/advisory"}],
            },
            browser_opener=opener or (lambda _url, **_kwargs: True),
        )
        return code, stdout.getvalue(), stderr.getvalue()

    def invoke_interactive(self, args, user_input, items=None):
        stdin = TTYBuffer(user_input)
        stdout = TTYBuffer()
        stderr = io.StringIO()
        pages = []
        code = run(
            args,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            feed_loader=lambda _url, _timeout: {
                "items": list(ITEMS if items is None else items),
                "topics": TOPICS,
            },
            article_loader=lambda item, _timeout: {
                **item,
                "content_text": "## Access path\n\nThe token crossed a trust boundary.",
                "short_content_text": "The short read keeps the affected boundary and the immediate check.",
                "short_read_time_minutes": 1,
                "sources": [],
            },
            pager=pages.append,
        )
        return code, stdout.getvalue(), stderr.getvalue(), pages

    def test_default_command_lists_latest_articles(self):
        code, stdout, stderr = self.invoke([])
        self.assertEqual(code, 0)
        self.assertIn("Cloud Tokens Became the Perimeter", stdout)
        self.assertIn("The AI Gateway Had Root", stdout)
        self.assertEqual(stderr, "")

    def test_topic_command_filters_articles(self):
        code, stdout, _ = self.invoke(["topic", "identity"])
        self.assertEqual(code, 0)
        self.assertIn("Cloud Tokens", stdout)
        self.assertNotIn("AI Gateway", stdout)

    def test_topics_reports_counts(self):
        code, stdout, _ = self.invoke(["topics", "--json"])
        self.assertEqual(code, 0)
        topics = json.loads(stdout)
        counts = {row["topic"]: row["articles"] for row in topics}
        self.assertEqual(counts["identity"], 1)
        self.assertEqual(counts["ai"], 1)
        self.assertEqual(counts["endpoint"], 0)

    def test_help_surfaces_examples_and_date_filter(self):
        help_text = build_parser().format_help()
        self.assertIn("nulltap latest --days 7", help_text)
        self.assertIn("nulltap topics", help_text)
        self.assertIn("limit the feed to the last N days", help_text)
        self.assertIn("nulltap read 2 --short", help_text)

    def test_search_uses_title_summary_and_tags(self):
        results = search_items(ITEMS, "production credentials")
        self.assertEqual([item["id"] for item in results], ["2026-07-25-ai-gateway"])

    def test_search_can_be_limited_to_topic(self):
        code, stdout, _ = self.invoke(["search", "control plane", "--topic", "cloud", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)[0]["id"], "2026-07-26-cloud-token")

    def test_read_resolves_slug_and_prints_full_article(self):
        code, stdout, _ = self.invoke(["read", "ai-gateway"])
        self.assertEqual(code, 0)
        self.assertIn("The AI Gateway Had Root", stdout)
        self.assertIn("The token crossed a trust boundary.", stdout)
        self.assertIn("Primary advisory: https://example.com/advisory", stdout)
        self.assertNotIn("https://nulltap.sh/p/ai-gateway/", stdout)

    def test_show_is_an_alias_for_terminal_reading(self):
        code, stdout, _ = self.invoke(["show", "1"])
        self.assertEqual(code, 0)
        self.assertIn("Access path", stdout)
        self.assertNotIn("## Access path", stdout)

    def test_short_mode_reads_the_one_minute_version(self):
        code, stdout, stderr = self.invoke(["read", "1", "--short"])
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("1-minute read", stdout)
        self.assertIn("Revoke it and inspect the audit log.", stdout)
        self.assertNotIn("Access path", stdout)

    def test_full_flag_overrides_short_environment_default(self):
        with patch.dict("os.environ", {"NULLTAP_READING_MODE": "short"}):
            code, stdout, _ = self.invoke(["read", "1", "--full"])
        self.assertEqual(code, 0)
        self.assertIn("Access path", stdout)
        self.assertNotIn("1-minute read", stdout)

    def test_short_mode_fails_clearly_when_article_has_no_short_read(self):
        with self.assertRaisesRegex(FeedError, "does not include a 1-minute read"):
            select_reading_mode({**ITEMS[0], "content_text": "Full article"}, True)

    def test_list_does_not_require_browser_urls(self):
        code, stdout, _ = self.invoke(["latest"])
        self.assertEqual(code, 0)
        self.assertNotIn("https://nulltap.sh/p/", stdout)
        self.assertIn("[1]", stdout)

    def test_interactive_list_reads_selected_article_without_a_slug(self):
        code, stdout, stderr, pages = self.invoke_interactive([], "2\nq\n")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("Articles 1–2 of 2", stdout)
        self.assertEqual(len(pages), 1)
        self.assertIn("The AI Gateway Had Root", pages[0])
        self.assertIn("The token crossed a trust boundary.", pages[0])

    def test_interactive_list_paginates(self):
        many = []
        for index in range(12):
            many.append({**ITEMS[0], "id": f"article-{index + 1}", "title": f"Article {index + 1}"})
        code, stdout, _, pages = self.invoke_interactive(["--page-size", "10"], "n\n12\nq\n", items=many)
        self.assertEqual(code, 0)
        self.assertIn("page 2/2", stdout)
        self.assertEqual(len(pages), 1)
        self.assertIn("Article 12", pages[0])

    def test_search_without_words_prompts_then_opens_result(self):
        code, stdout, _, pages = self.invoke_interactive(["search"], "gateway\n1\nq\n")
        self.assertEqual(code, 0)
        self.assertIn("Search nulltap", stdout)
        self.assertIn("Search: gateway", stdout)
        self.assertEqual(len(pages), 1)
        self.assertIn("The AI Gateway Had Root", pages[0])

    def test_topics_menu_opens_a_topic_and_article(self):
        code, stdout, _, pages = self.invoke_interactive(["topics"], "6\n1\nq\n")
        self.assertEqual(code, 0)
        self.assertIn("Topics", stdout)
        self.assertIn("Topic: AI", stdout)
        self.assertEqual(len(pages), 1)
        self.assertIn("The AI Gateway Had Root", pages[0])

    def test_known_empty_topic_is_not_reported_as_invalid(self):
        code, stdout, stderr = self.invoke(["topic", "endpoint"])
        self.assertEqual(code, 0)
        self.assertIn("No published articles matched.", stdout)
        self.assertEqual(stderr, "")

    def test_days_filter_uses_publication_time(self):
        selected = filter_days(
            ITEMS,
            1,
            now=datetime(2026, 7, 26, 18, 0, tzinfo=timezone.utc),
        )
        self.assertEqual([item["id"] for item in selected], ["2026-07-26-cloud-token"])

    def test_direct_read_uses_pager_in_a_terminal(self):
        code, _, _, pages = self.invoke_interactive(["read", "1"], "")
        self.assertEqual(code, 0)
        self.assertEqual(len(pages), 1)
        self.assertIn("Cloud Tokens Became the Perimeter", pages[0])

    def test_article_renderer_formats_markdown_and_collects_links(self):
        article = {
            **ITEMS[0],
            "content_text": (
                "## Access path\n\nA [vendor advisory](https://example.com/advisory) confirmed **the flaw**.\n\n"
                "- Revoke the token\n- Check the audit log"
            ),
            "sources": [],
        }
        rendered = render_article(article, False, width=72)
        self.assertIn("Access path", rendered)
        self.assertNotIn("## Access path", rendered)
        self.assertIn("vendor advisory [1]", rendered)
        self.assertNotIn("**the flaw**", rendered)
        self.assertIn("• Revoke the token", rendered)
        self.assertIn("[1] https://example.com/advisory", rendered)

    def test_open_passes_only_resolved_url_to_browser(self):
        opened = []
        code, stdout, _ = self.invoke(
            ["open", "1"],
            opener=lambda url, **_kwargs: opened.append(url) or True,
        )
        self.assertEqual(code, 0)
        self.assertEqual(opened, ["https://nulltap.sh/p/cloud-token/"])
        self.assertIn(opened[0], stdout)

    def test_normalization_strips_terminal_escape_sequences(self):
        item = normalize_item(
            {
                "id": "unsafe",
                "url": "https://nulltap.sh/p/unsafe/",
                "content_url": "https://evil.example/article.json",
                "title": "safe\x1b[31m red",
                "summary": "summary\x00text",
                "tags": ["AI"],
            }
        )
        self.assertEqual(item["title"], "safe red")
        self.assertEqual(item["summary"], "summarytext")
        self.assertEqual(item["tags"], ["ai"])
        self.assertEqual(item["content_url"], "")

    def test_normalization_rejects_article_urls_outside_feed_origin(self):
        item = normalize_item(
            {
                "url": "http://127.0.0.1:8000/private",
                "content_url": "http://127.0.0.1:8000/private.json",
                "title": "Local service",
            },
            feed_url="https://feed.example/feed.json",
        )
        self.assertIsNone(item)

    def test_local_feed_can_reference_its_own_origin(self):
        item = normalize_item(
            {
                "url": "http://127.0.0.1:8000/article/",
                "content_url": "http://127.0.0.1:8000/article.json",
                "title": "Local article",
            },
            feed_url="http://127.0.0.1:8000/feed.json",
        )
        self.assertEqual(item["content_url"], "http://127.0.0.1:8000/article.json")

    def test_normalization_strips_bidirectional_controls(self):
        item = normalize_item(
            {
                **ITEMS[0],
                "title": "safe\u202eevil",
                "summary": "plain\u2066text\u2069",
            }
        )
        self.assertEqual(item["title"], "safeevil")
        self.assertEqual(item["summary"], "plaintext")

    def test_fetch_feed_sends_no_search_query(self):
        seen = {}
        payload = json.dumps({"items": [ITEMS[0]]}).encode()

        def opener(request, timeout):
            seen["url"] = request.full_url
            seen["timeout"] = timeout
            return FakeResponse(payload)

        items = fetch_feed("https://nulltap.sh/feed.json", 3, opener=opener)
        self.assertEqual(len(items), 1)
        self.assertEqual(seen, {"url": "https://nulltap.sh/feed.json", "timeout": 3})

    @patch("nulltap.cli.urllib.request.urlopen")
    @patch("nulltap.cli.truststore.SSLContext")
    def test_default_transport_uses_native_system_trust(self, context_type, urlopen):
        payload = json.dumps({"items": [ITEMS[0]], "topics": TOPICS}).encode()
        native_context = context_type.return_value
        urlopen.return_value = FakeResponse(payload)

        document = fetch_feed_document(timeout=3)

        self.assertEqual(len(document["items"]), 1)
        context_type.assert_called_once_with(ssl.PROTOCOL_TLS_CLIENT)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://nulltap.sh/feed.json")
        self.assertEqual(urlopen.call_args.kwargs, {"timeout": 3, "context": native_context})

    def test_fetch_feed_rejects_cross_origin_redirect(self):
        payload = json.dumps({"items": [ITEMS[0]]}).encode()
        with self.assertRaisesRegex(FeedError, "redirected to a different origin"):
            fetch_feed(
                "https://nulltap.sh/feed.json",
                3,
                opener=lambda _request, timeout: FakeResponse(
                    payload,
                    "http://127.0.0.1:8000/feed.json",
                ),
            )

    def test_fetch_feed_document_includes_topic_catalog(self):
        payload = json.dumps({"items": ITEMS, "topics": TOPICS}).encode()
        document = fetch_feed_document(
            "https://nulltap.sh/feed.json",
            3,
            opener=lambda _request, timeout: FakeResponse(payload),
        )
        self.assertEqual(document["topics"][0]["topic"], "endpoint")
        self.assertEqual(document["topics"][5]["label"], "AI")

    def test_unknown_topic_returns_helpful_error(self):
        code, _, stderr = self.invoke(["topic", "nope"])
        self.assertEqual(code, 1)
        self.assertIn("available topics", stderr)


if __name__ == "__main__":
    unittest.main()
