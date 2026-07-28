from __future__ import annotations

import argparse
import json
import os
import pydoc
import re
import shutil
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, TextIO

from . import __version__


DEFAULT_FEED_URL = "https://nulltap.sh/feed.json"
MAX_FEED_BYTES = 5 * 1024 * 1024
MAX_ARTICLE_BYTES = 2 * 1024 * 1024
ANSI_ESCAPE = re.compile(r"\x1b(?:[@-Z\-_]|\[[0-?]*[ -/]*[@-~])")
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
BIDI_CONTROLS = re.compile(r"[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")
MARKDOWN_IMAGE = re.compile(r"!\[([^]]*)]\([^)]+\)")
MARKDOWN_LINK = re.compile(r"(?<!!)\[([^]]+)]\((https?://[^\s)]+)\)")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
BULLET = re.compile(r"^\s*[-*+]\s+(.+)$")
NUMBERED = re.compile(r"^\s*(\d+)[.)]\s+(.+)$")
RULE = re.compile(r"^\s*(?:[-*_]\s*){3,}$")


class FeedError(RuntimeError):
    pass


def safe_text(value: Any) -> str:
    text = ANSI_ESCAPE.sub("", str(value or ""))
    text = CONTROL_CHARS.sub("", text)
    text = BIDI_CONTROLS.sub("", text)
    return " ".join(text.split())


def safe_http_url(value: Any) -> str:
    url = str(value or "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if parsed.username or parsed.password:
        return ""
    return url


def safe_article_text(value: Any) -> str:
    text = ANSI_ESCAPE.sub("", str(value or ""))
    text = CONTROL_CHARS.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = BIDI_CONTROLS.sub("", text)
    text = MARKDOWN_IMAGE.sub(
        lambda match: f"[Image: {safe_text(match.group(1))}]" if match.group(1) else "[Image]",
        text,
    )
    return re.sub(r"\n{4,}", "\n\n\n", text).strip()


def same_origin(first: str, second: str) -> bool:
    left = urllib.parse.urlparse(first)
    right = urllib.parse.urlparse(second)
    return (left.scheme.lower(), left.hostname, left.port) == (
        right.scheme.lower(),
        right.hostname,
        right.port,
    )


def normalize_item(
    raw: Any,
    feed_url: str = DEFAULT_FEED_URL,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    title = safe_text(raw.get("title"))
    url = safe_http_url(raw.get("url"))
    trusted_origin = safe_http_url(feed_url)
    if not title or not url or not trusted_origin or not same_origin(url, trusted_origin):
        return None

    raw_tags = raw.get("tags", [])
    if not isinstance(raw_tags, list):
        raw_tags = []
    tags = list(dict.fromkeys(safe_text(tag).lower() for tag in raw_tags if safe_text(tag)))

    try:
        read_time = max(0, int(raw.get("read_time_minutes", 0)))
    except (TypeError, ValueError):
        read_time = 0
    try:
        short_read_time = max(0, int(raw.get("short_read_time_minutes", 0)))
    except (TypeError, ValueError):
        short_read_time = 0

    content_url = safe_http_url(raw.get("content_url"))
    if content_url and not same_origin(url, content_url):
        content_url = ""

    return {
        "id": safe_text(raw.get("id")) or url,
        "url": url,
        "content_url": content_url,
        "title": title,
        "summary": safe_text(raw.get("summary")),
        "date_published": safe_text(raw.get("date_published")),
        "tags": tags,
        "read_time_minutes": read_time,
        "short_read_available": bool(raw.get("short_read_available", False)),
        "short_read_time_minutes": short_read_time,
        "author": safe_text(raw.get("author")),
        "image": safe_http_url(raw.get("image")),
    }


def normalize_topic(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None

    topic_id = safe_text(raw.get("id") or raw.get("topic")).lower()
    if not topic_id:
        return None
    return {
        "topic": topic_id,
        "label": safe_text(raw.get("label")) or topic_id,
        "description": safe_text(raw.get("description")),
    }


def normalize_feed_payload(
    payload: Any,
    feed_url: str = DEFAULT_FEED_URL,
) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise FeedError("feed does not contain an items array")

    items = [
        item
        for raw in payload["items"]
        if (item := normalize_item(raw, feed_url=feed_url))
    ]
    raw_topics = payload.get("topics", [])
    if not isinstance(raw_topics, list):
        raw_topics = []
    topics = [topic for raw in raw_topics if (topic := normalize_topic(raw))]
    return {
        "items": sorted(items, key=lambda item: item["date_published"], reverse=True),
        "topics": list({topic["topic"]: topic for topic in topics}.values()),
    }


def _fetch_json(
    url: str,
    *,
    timeout: float,
    maximum_bytes: int,
    label: str,
    accept: str,
    opener: Callable[..., Any],
) -> Any:
    if not safe_http_url(url):
        raise FeedError(f"{label} URL must be an http or https URL without embedded credentials")

    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": f"nulltap/{__version__} (+https://nulltap.sh)",
        },
    )

    try:
        with opener(request, timeout=timeout) as response:
            final_url = safe_http_url(
                response.geturl() if hasattr(response, "geturl") else request.full_url
            )
            if not final_url or not same_origin(request.full_url, final_url):
                raise FeedError(f"{label} redirected to a different origin")
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > maximum_bytes:
                raise FeedError(f"{label} is larger than {maximum_bytes // (1024 * 1024)} MiB")
            body = response.read(maximum_bytes + 1)
    except FeedError:
        raise
    except (OSError, ValueError, urllib.error.URLError) as exc:
        reason = getattr(exc, "reason", exc)
        raise FeedError(f"could not fetch {label}: {safe_text(reason)}") from exc

    if len(body) > maximum_bytes:
        raise FeedError(f"{label} is larger than {maximum_bytes // (1024 * 1024)} MiB")

    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FeedError(f"{label} returned invalid JSON") from exc


def fetch_feed_document(
    url: str = DEFAULT_FEED_URL,
    timeout: float = 10.0,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, list[dict[str, Any]]]:
    payload = _fetch_json(
        url,
        timeout=timeout,
        maximum_bytes=MAX_FEED_BYTES,
        label="feed",
        accept="application/feed+json, application/json",
        opener=opener,
    )
    return normalize_feed_payload(payload, feed_url=url)


def fetch_feed(
    url: str = DEFAULT_FEED_URL,
    timeout: float = 10.0,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> list[dict[str, Any]]:
    """Return feed items for callers using the 0.1.0 list-based API."""
    return fetch_feed_document(url, timeout, opener)["items"]


def fetch_article(
    item: dict[str, Any],
    timeout: float = 10.0,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    content_url = item.get("content_url", "")
    if not content_url:
        raise FeedError("this article is not available for terminal reading")

    payload = _fetch_json(
        content_url,
        timeout=timeout,
        maximum_bytes=MAX_ARTICLE_BYTES,
        label="article",
        accept="application/json",
        opener=opener,
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("content_text"), str):
        raise FeedError("article does not contain terminal-readable text")
    short_content = payload.get("short_content_text", "")
    if short_content and not isinstance(short_content, str):
        raise FeedError("article contains invalid 1-minute text")
    try:
        short_read_time = max(0, int(payload.get("short_read_time_minutes", 0) or 0))
    except (TypeError, ValueError):
        short_read_time = 0

    raw_sources = payload.get("sources", [])
    if not isinstance(raw_sources, list):
        raw_sources = []
    sources = []
    for raw_source in raw_sources:
        if not isinstance(raw_source, dict):
            continue
        label = safe_text(raw_source.get("label"))
        url = safe_http_url(raw_source.get("url"))
        if label and url:
            sources.append({"label": label, "url": url})

    return {
        **item,
        "content_text": safe_article_text(payload["content_text"]),
        "short_content_text": safe_article_text(short_content),
        "short_read_time_minutes": short_read_time,
        "sources": sources,
    }


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1 or parsed > 500:
        raise argparse.ArgumentTypeError("must be between 1 and 500")
    return parsed


def positive_days(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1 or parsed > 36500:
        raise argparse.ArgumentTypeError("must be between 1 and 36500")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    common.add_argument(
        "--feed",
        metavar="URL",
        help="JSON feed URL (default: NULLTAP_FEED_URL or nulltap.sh/feed.json)",
    )
    common.add_argument("--timeout", type=float, metavar="SECONDS", help="network timeout (default: 10)")
    common.add_argument("--json", action="store_true", help="emit JSON for scripts")
    common.add_argument("--plain", action="store_true", help="print once without menus or a pager")
    common.add_argument("--page-size", type=positive_int, metavar="N", help="articles per page (default: 5)")
    common.add_argument("--days", type=positive_days, metavar="N", help="limit the feed to the last N days")
    common.add_argument("--no-color", action="store_true", help="disable terminal color")
    reading_mode = common.add_mutually_exclusive_group()
    reading_mode.add_argument(
        "--short",
        action="store_true",
        help="read 1-minute versions (or set NULLTAP_READING_MODE=short)",
    )
    reading_mode.add_argument("--full", action="store_true", help="force full articles")

    parser = argparse.ArgumentParser(
        prog="nulltap",
        parents=[common],
        description="Read Nulltap articles without leaving the terminal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            examples:
              nulltap                         browse recent articles
              nulltap latest --days 7         show the last seven days
              nulltap topics                  list the current topic catalog
              nulltap topic identity          browse one topic
              nulltap search "token theft"    search titles, summaries, and tags
              nulltap read 2                  read the second result in the terminal
              nulltap read 2 --short          read its 1-minute version

            Run 'nulltap COMMAND --help' for command-specific options.
            """
        ),
    )
    parser.add_argument("--version", action="version", version=f"nulltap {__version__}")
    subparsers = parser.add_subparsers(dest="command", title="commands", metavar="COMMAND")

    browse = subparsers.add_parser(
        "browse",
        parents=[common],
        help="browse the feed (default)",
        description="Browse recent Nulltap articles, newest first.",
    )
    browse.add_argument("-n", "--limit", type=positive_int, default=50, help="maximum articles shown (default: 50)")
    browse.add_argument("-t", "--topic", help="limit results to one topic")

    latest = subparsers.add_parser(
        "latest",
        parents=[common],
        help="browse the newest articles",
        description="Browse the newest Nulltap articles.",
    )
    latest.add_argument("-n", "--limit", type=positive_int, default=50, help="maximum articles shown (default: 50)")
    latest.add_argument("-t", "--topic", help="limit results to one topic")

    subparsers.add_parser(
        "topics",
        parents=[common],
        help="list topics or choose one interactively",
        description="List every Nulltap topic and its article count.",
    )

    topic = subparsers.add_parser(
        "topic",
        parents=[common],
        help="browse articles for one topic",
        description="Browse articles filed under one topic.",
    )
    topic.add_argument("name", nargs="?", help="topic ID; run 'nulltap topics' to list them")
    topic.add_argument("-n", "--limit", type=positive_int, default=100, help="maximum articles shown (default: 100)")

    search = subparsers.add_parser(
        "search",
        parents=[common],
        help="search titles, summaries, and topic tags",
        description="Search article titles, summaries, and topic tags.",
    )
    search.add_argument("query", nargs="*", help="words to search for")
    search.add_argument("-t", "--topic", help="limit results to one topic")
    search.add_argument("-n", "--limit", type=positive_int, default=100, help="maximum matches shown (default: 100)")

    read = subparsers.add_parser("read", parents=[common], help="read in the terminal or browse when omitted")
    read.add_argument("target", nargs="?", help="result number, article ID, slug, or URL")

    show = subparsers.add_parser("show", parents=[common], help="alias for read")
    show.add_argument("target", nargs="?", help="result number, article ID, slug, or URL")

    open_command = subparsers.add_parser("open", parents=[common], help="optional handoff to a web browser")
    open_command.add_argument("target", help="result number, article ID, slug, or URL")

    return parser


def filter_topic(items: Iterable[dict[str, Any]], topic: str | None) -> list[dict[str, Any]]:
    if not topic:
        return list(items)
    wanted = safe_text(topic).lower()
    return [item for item in items if wanted in item["tags"]]


def filter_days(
    items: Iterable[dict[str, Any]],
    days: int | None,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    if not days:
        return list(items)

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = current.astimezone(timezone.utc) - timedelta(days=days)
    selected = []
    for item in items:
        raw_date = item.get("date_published", "")
        try:
            published = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError):
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        if published.astimezone(timezone.utc) >= cutoff:
            selected.append(item)
    return selected


def search_items(items: Iterable[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    phrase = safe_text(query).lower()
    tokens = [token for token in phrase.split() if token]
    if not tokens:
        return []

    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for item in items:
        title = item["title"].lower()
        summary = item["summary"].lower()
        tags = " ".join(item["tags"]).lower()
        haystack = f"{title} {summary} {tags}"
        if not all(token in haystack for token in tokens):
            continue

        score = 100 if phrase in title else 0
        score += sum(12 for token in tokens if token in title)
        score += sum(7 for token in tokens if token in tags)
        score += sum(3 for token in tokens if token in summary)
        ranked.append((score, item["date_published"], item))

    ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    return [item for _, _, item in ranked]


def resolve_item(items: Sequence[dict[str, Any]], target: str) -> dict[str, Any] | None:
    clean_target = safe_text(target)
    if clean_target.isdigit():
        index = int(clean_target) - 1
        return items[index] if 0 <= index < len(items) else None

    lowered = clean_target.lower().rstrip("/")
    for item in items:
        url = item["url"].lower().rstrip("/")
        slug = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]
        if lowered in {item["id"].lower(), url, slug}:
            return item
    return None


def color_enabled(stream: TextIO, disabled: bool) -> bool:
    return not disabled and "NO_COLOR" not in os.environ and bool(getattr(stream, "isatty", lambda: False)())


def interactive_enabled(stdin: TextIO, stdout: TextIO, plain: bool, json_output: bool) -> bool:
    return (
        not plain
        and not json_output
        and bool(getattr(stdin, "isatty", lambda: False)())
        and bool(getattr(stdout, "isatty", lambda: False)())
    )


def paint(text: str, code: str, enabled: bool) -> str:
    return f"\033[{code}m{text}\033[0m" if enabled else text


def display_date(value: str) -> str:
    return value[:10] if len(value) >= 10 else value or "unknown date"


def terminal_width() -> int:
    return max(60, min(110, shutil.get_terminal_size((92, 24)).columns))


def _clean_inline(text: str, links: list[str]) -> str:
    def replace_link(match: re.Match[str]) -> str:
        url = safe_http_url(match.group(2))
        if not url:
            return safe_text(match.group(1))
        if url not in links:
            links.append(url)
        return f"{safe_text(match.group(1))} [{links.index(url) + 1}]"

    text = MARKDOWN_LINK.sub(replace_link, text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"(?<!_)_([^_]+)_", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return safe_text(text)


def render_markdown(markdown: str, width: int, use_color: bool) -> tuple[str, list[str]]:
    output: list[str] = []
    links: list[str] = []
    paragraph: list[str] = []
    in_code = False

    def blank() -> None:
        if output and output[-1] != "":
            output.append("")

    def flush_paragraph() -> None:
        if not paragraph:
            return
        text = _clean_inline(" ".join(paragraph), links)
        output.extend(textwrap.wrap(text, width=width) or [""])
        paragraph.clear()

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if line.lstrip().startswith("```"):
            flush_paragraph()
            in_code = not in_code
            blank()
            continue
        if in_code:
            output.append(paint(f"    {line}", "2", use_color))
            continue
        if not line.strip():
            flush_paragraph()
            blank()
            continue

        heading = HEADING.match(line)
        bullet = BULLET.match(line)
        numbered = NUMBERED.match(line)
        if heading:
            flush_paragraph()
            blank()
            title = _clean_inline(heading.group(2), links)
            output.extend(paint(part, "1;38;5;214", use_color) for part in textwrap.wrap(title, width=width))
            continue
        if RULE.match(line):
            flush_paragraph()
            blank()
            output.append(paint("─" * min(width, 72), "2", use_color))
            continue
        if bullet:
            flush_paragraph()
            text = _clean_inline(bullet.group(1), links)
            output.append(textwrap.fill(text, width=width, initial_indent="• ", subsequent_indent="  "))
            continue
        if numbered:
            flush_paragraph()
            prefix = f"{numbered.group(1)}. "
            text = _clean_inline(numbered.group(2), links)
            output.append(
                textwrap.fill(text, width=width, initial_indent=prefix, subsequent_indent=" " * len(prefix))
            )
            continue
        if line.lstrip().startswith(">"):
            flush_paragraph()
            text = _clean_inline(line.lstrip()[1:].lstrip(), links)
            output.append(textwrap.fill(text, width=width, initial_indent="│ ", subsequent_indent="│ "))
            continue
        if line.startswith("|") and line.endswith("|"):
            flush_paragraph()
            if all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in line.strip("|").split("|")):
                continue
            output.append(_clean_inline(line, links))
            continue
        paragraph.append(line.strip())

    flush_paragraph()
    while output and output[-1] == "":
        output.pop()
    return "\n".join(output), links


def select_reading_mode(article: dict[str, Any], short_mode: bool) -> dict[str, Any]:
    if not short_mode:
        return {**article, "reading_mode": "full"}
    short_content = article.get("short_content_text", "")
    if not short_content:
        raise FeedError("this article does not include a 1-minute read")
    return {
        **article,
        "content_text": short_content,
        "read_time_minutes": article.get("short_read_time_minutes", 1) or 1,
        "reading_mode": "short",
    }


def render_article(item: dict[str, Any], use_color: bool, width: int | None = None) -> str:
    width = width or terminal_width()
    lines: list[str] = []
    title_lines = textwrap.wrap(item["title"], width=width) or [item["title"]]
    lines.extend(paint(line, "1", use_color) for line in title_lines)

    metadata = [display_date(item["date_published"]), *item["tags"]]
    if item.get("reading_mode") == "short":
        metadata.append("1-minute read")
    if item["read_time_minutes"]:
        metadata.append(f"{item['read_time_minutes']} min")
    if item["author"]:
        metadata.append(item["author"])
    lines.append(paint(" · ".join(metadata), "2", use_color))

    if item["summary"]:
        lines.append("")
        lines.append(textwrap.fill(item["summary"], width=width))

    body, links = render_markdown(item.get("content_text", ""), width, use_color)
    if body:
        lines.extend(["", body])

    if links:
        lines.extend(["", paint("Links", "1;38;5;214", use_color)])
        for index, url in enumerate(links, 1):
            lines.append(textwrap.fill(f"[{index}] {url}", width=width, subsequent_indent="    "))

    sources = item.get("sources", [])
    if sources:
        lines.extend(["", paint("Primary sources", "1;38;5;214", use_color)])
        for source in sources:
            entry = f"• {source['label']}: {source['url']}"
            lines.append(textwrap.fill(entry, width=width, subsequent_indent="  "))

    return "\n".join(lines).rstrip() + "\n"


def print_items(
    items: Sequence[dict[str, Any]],
    stream: TextIO,
    use_color: bool,
    *,
    start_index: int = 1,
    width: int | None = None,
) -> None:
    if not items:
        print("No published articles matched.", file=stream)
        return

    width = width or terminal_width()
    number_width = len(str(start_index + len(items) - 1)) + 2
    for offset, item in enumerate(items):
        index = start_index + offset
        number = paint(f"[{index}]", "2", use_color)
        title = paint(item["title"], "1", use_color)
        print(f"{number:<{number_width}} {title}", file=stream)
        metadata = [display_date(item["date_published"]), *item["tags"]]
        if item["read_time_minutes"]:
            metadata.append(f"{item['read_time_minutes']} min")
        print(f"{' ' * (number_width + 1)}{' · '.join(metadata)}", file=stream)
        if item["summary"]:
            print(
                textwrap.fill(
                    item["summary"],
                    width=width,
                    initial_indent=" " * (number_width + 1),
                    subsequent_indent=" " * (number_width + 1),
                ),
                file=stream,
            )
        if offset != len(items) - 1:
            print(file=stream)


def read_prompt(prompt: str, stdin: TextIO, stdout: TextIO) -> str:
    print(prompt, end="", file=stdout, flush=True)
    value = stdin.readline()
    if value == "":
        return "q"
    return safe_text(value)


def show_article(
    item: dict[str, Any],
    *,
    article_loader: Callable[[dict[str, Any], float], dict[str, Any]],
    timeout: float,
    stdout: TextIO,
    use_color: bool,
    use_pager: bool,
    pager: Callable[[str], None],
    short_mode: bool,
) -> None:
    article = select_reading_mode(article_loader(item, timeout), short_mode)
    rendered = render_article(article, use_color)
    if use_pager:
        pager(rendered)
    else:
        print(rendered, end="", file=stdout)


def browse_items(
    items: Sequence[dict[str, Any]],
    *,
    heading: str,
    page_size: int,
    stdin: TextIO,
    stdout: TextIO,
    use_color: bool,
    article_loader: Callable[[dict[str, Any], float], dict[str, Any]],
    timeout: float,
    pager: Callable[[str], None],
    short_mode: bool,
) -> int:
    if not items:
        print("No published articles matched.", file=stdout)
        return 0

    page = 0
    page_count = (len(items) + page_size - 1) // page_size
    while True:
        start = page * page_size
        end = min(start + page_size, len(items))
        print(file=stdout)
        print(paint(heading, "1;38;5;214", use_color), file=stdout)
        print(paint(f"Articles {start + 1}–{end} of {len(items)} · page {page + 1}/{page_count}", "2", use_color), file=stdout)
        print(file=stdout)
        print_items(items[start:end], stdout, use_color, start_index=start + 1)
        print(file=stdout)

        commands = [f"{start + 1}-{end} read"]
        if page < page_count - 1:
            commands.append("n next")
        if page > 0:
            commands.append("p previous")
        commands.append("q quit")
        choice = read_prompt("  ".join(commands) + "\n> ", stdin, stdout).lower()

        if choice in {"q", "quit", "exit"}:
            return 0
        if choice in {"n", "next", ""}:
            if page < page_count - 1:
                page += 1
            else:
                print("Already on the last page.", file=stdout)
            continue
        if choice in {"p", "prev", "previous"}:
            if page > 0:
                page -= 1
            else:
                print("Already on the first page.", file=stdout)
            continue
        if choice.isdigit():
            index = int(choice) - 1
            if start <= index < end:
                show_article(
                    items[index],
                    article_loader=article_loader,
                    timeout=timeout,
                    stdout=stdout,
                    use_color=use_color,
                    use_pager=True,
                    pager=pager,
                    short_mode=short_mode,
                )
                continue
        print(f"Choose an article from {start + 1} to {end}, or use n, p, or q.", file=stdout)


def json_dump(value: Any, stream: TextIO) -> None:
    json.dump(value, stream, ensure_ascii=False, indent=2)
    print(file=stream)


def topic_counts(
    items: Iterable[dict[str, Any]],
    catalog: Iterable[dict[str, str]] = (),
) -> list[dict[str, Any]]:
    counts = Counter(tag for item in items for tag in item["tags"])
    rows = []
    seen = set()
    for entry in catalog:
        topic = entry["topic"]
        if topic in seen:
            continue
        seen.add(topic)
        rows.append({**entry, "articles": counts.get(topic, 0)})
    for topic, count in sorted(counts.items(), key=lambda row: (-row[1], row[0])):
        if topic not in seen:
            rows.append({"topic": topic, "label": topic, "description": "", "articles": count})
    return rows


def choose_topic(
    items: Sequence[dict[str, Any]],
    catalog: Sequence[dict[str, str]],
    stdin: TextIO,
    stdout: TextIO,
    use_color: bool,
) -> str | None:
    topics = topic_counts(items, catalog)
    if not topics:
        print("No published topics yet.", file=stdout)
        return None
    print(file=stdout)
    print(paint("Topics", "1;38;5;214", use_color), file=stdout)
    for index, row in enumerate(topics, 1):
        noun = "article" if row["articles"] == 1 else "articles"
        print(f"[{index}] {row['label']:<12} {row['articles']} {noun}", file=stdout)
    choice = read_prompt("\nChoose a topic number, or q to quit\n> ", stdin, stdout).lower()
    if choice in {"q", "quit", "exit"}:
        return None
    if choice.isdigit() and 1 <= int(choice) <= len(topics):
        return topics[int(choice) - 1]["topic"]
    print("That topic number is not available.", file=stdout)
    return None


def run(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    feed_loader: Callable[[str, float], Any] = fetch_feed_document,
    article_loader: Callable[[dict[str, Any], float], dict[str, Any]] = fetch_article,
    browser_opener: Callable[..., bool] = webbrowser.open,
    pager: Callable[[str], None] = pydoc.pager,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "browse"
    feed_url = getattr(args, "feed", os.environ.get("NULLTAP_FEED_URL", DEFAULT_FEED_URL))
    timeout = getattr(args, "timeout", 10.0)
    json_output = getattr(args, "json", False)
    plain = getattr(args, "plain", False)
    no_color = getattr(args, "no_color", False)
    configured_mode = safe_text(os.environ.get("NULLTAP_READING_MODE", "full")).lower()
    short_mode = getattr(args, "short", False) or (
        configured_mode == "short" and not getattr(args, "full", False)
    )
    page_size = min(getattr(args, "page_size", 5), 50)

    if timeout <= 0 or timeout > 120:
        parser.error("--timeout must be greater than 0 and no more than 120 seconds")

    loaded_feed = feed_loader(feed_url, timeout)
    if isinstance(loaded_feed, dict):
        feed = normalize_feed_payload(loaded_feed)
    else:
        feed = normalize_feed_payload({"items": list(loaded_feed), "topics": []})
    items = filter_days(feed["items"], getattr(args, "days", None))
    topic_catalog = feed["topics"]
    use_color = color_enabled(stdout, no_color)
    interactive = interactive_enabled(stdin, stdout, plain, json_output)

    if command == "topics":
        topics = topic_counts(items, topic_catalog)
        if json_output:
            json_dump(topics, stdout)
            return 0
        if interactive:
            chosen = choose_topic(items, topic_catalog, stdin, stdout, use_color)
            if chosen:
                chosen_label = next(
                    (row["label"] for row in topics if row["topic"] == chosen),
                    chosen,
                )
                return browse_items(
                    filter_topic(items, chosen),
                    heading=f"Topic: {chosen_label}",
                    page_size=page_size,
                    stdin=stdin,
                    stdout=stdout,
                    use_color=use_color,
                    article_loader=article_loader,
                    timeout=timeout,
                    pager=pager,
                    short_mode=short_mode,
                )
            return 0
        if topics:
            width = max(len(row["label"]) for row in topics)
            for row in topics:
                print(f"{row['label']:<{width}}  {row['articles']}", file=stdout)
        else:
            print("No published topics yet.", file=stdout)
        return 0

    if command == "topic":
        topic_name = args.name
        if not topic_name and interactive:
            topic_name = choose_topic(items, topic_catalog, stdin, stdout, use_color)
            if not topic_name:
                return 0
        if not topic_name:
            print("nulltap: provide a topic name or run this command in a terminal", file=stderr)
            return 1
        selected = filter_topic(items, topic_name)
        available_rows = topic_counts(items, topic_catalog)
        wanted_topic = safe_text(topic_name).lower()
        if wanted_topic not in {row["topic"] for row in available_rows}:
            available = ", ".join(row["topic"] for row in available_rows)
            print(f"nulltap: no topic named '{safe_text(topic_name)}'", file=stderr)
            if available:
                print(f"available topics: {available}", file=stderr)
            return 1
        selected = selected[: args.limit]
        label = next((row["label"] for row in available_rows if row["topic"] == wanted_topic), wanted_topic)
        heading = f"Topic: {label}"
    elif command == "search":
        query = " ".join(args.query)
        if not query and interactive:
            query = read_prompt("Search nulltap\n> ", stdin, stdout)
        if not query:
            print("nulltap: provide search words", file=stderr)
            return 1
        selected = filter_topic(items, getattr(args, "topic", None))
        selected = search_items(selected, query)[: args.limit]
        heading = f"Search: {safe_text(query)}"
    elif command in {"browse", "latest"}:
        limit = getattr(args, "limit", 50)
        selected = filter_topic(items, getattr(args, "topic", None))[:limit]
        heading = "Recent articles"
    elif command in {"read", "show", "open"}:
        target = getattr(args, "target", None)
        if command in {"read", "show"} and not target:
            selected = items[:50]
            heading = "Recent articles"
        else:
            item = resolve_item(items, target or "")
            if not item:
                print(f"nulltap: article not found: {safe_text(target)}", file=stderr)
                return 1
            if command in {"read", "show"}:
                article = select_reading_mode(article_loader(item, timeout), short_mode)
                if json_output:
                    json_dump(article, stdout)
                else:
                    rendered = render_article(article, use_color)
                    if interactive:
                        pager(rendered)
                    else:
                        print(rendered, end="", file=stdout)
                return 0

            opened = browser_opener(item["url"], new=2)
            if json_output:
                json_dump({"url": item["url"], "opened": bool(opened)}, stdout)
            else:
                print(item["url"], file=stdout)
            return 0 if opened else 1
    else:
        parser.error(f"unknown command: {command}")

    if json_output:
        json_dump(selected, stdout)
    elif interactive:
        return browse_items(
            selected,
            heading=heading,
            page_size=page_size,
            stdin=stdin,
            stdout=stdout,
            use_color=use_color,
            article_loader=article_loader,
            timeout=timeout,
            pager=pager,
            short_mode=short_mode,
        )
    else:
        print_items(selected, stdout, use_color)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(argv)
    except FeedError as exc:
        print(f"nulltap: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nnulltap: interrupted", file=sys.stderr)
        return 130
