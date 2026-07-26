# nulltap

Read [Nulltap](https://nulltap.sh) from a terminal. Browse recent cybersecurity and AI articles, search the feed, filter by topic, and read the full article without opening a browser.

## Install

Python 3.10 or newer is required. [pipx](https://pipx.pypa.io/) keeps the command in its own environment:

```sh
pipx install nulltap
```

To upgrade an existing installation:

```sh
pipx upgrade nulltap
```

A regular pip installation also works: `python -m pip install nulltap`.

## Start here

```sh
nulltap                         # browse recent articles
nulltap latest --days 7         # articles published in the last seven days
nulltap topics                  # list every topic and its article count
nulltap topic identity          # browse one topic
nulltap search "token theft"    # search titles, summaries, and topic tags
nulltap read 2                  # read the second result in the terminal
```

Interactive lists show five articles at a time. Enter a result number to read it, `n` or `p` to change pages, and `q` to leave. Use `--page-size N` if you want a different page size.

Articles open in the terminal pager with headings, lists, quotations, code blocks, image descriptions, links, and primary sources formatted for the console. Press `q` to return to the article list.

## Topics

Nulltap currently publishes under these topics:

```text
endpoint
cloud
network
identity
appsec
AI
threats
```

`nulltap topics` reads the catalog from nulltap.sh and shows every topic, including topics that do not have a published article yet. Topic IDs are case-insensitive.

## Search and recent filters

Search runs locally over the feed already downloaded from nulltap.sh. Search words are not sent to Nulltap or another service.

Every search word must match the title, summary, or a topic tag. Title matches rank first, followed by topic and summary matches. Publication date breaks ties.

Use `--days N` with browsing, topics, or search to limit the downloaded feed by publication time:

```sh
nulltap search ransomware --days 30
nulltap topic cloud --days 14
nulltap topics --days 90
```

## Automation

Use `--json` for structured output or `--plain` for stable text without menus, color, or a pager:

```sh
nulltap latest --days 7 --json
nulltap search ransomware --json
nulltap topics --plain
```

Redirected output automatically uses non-interactive mode. Article IDs and slugs remain accepted by `read` for scripts, but ordinary browsing does not require them.

## Network and privacy

Listing and search commands make one read-only request to the public feed. Reading an article makes one additional request for its text. The client has no analytics, account, background process, or local database. Feed and article text are stripped of terminal control sequences before display.

Contributor setup, local feed overrides, and release checks are documented in [CONTRIBUTING.md](https://github.com/JustinHowe/nulltap/blob/main/CONTRIBUTING.md).

Licensed under the MIT License.
