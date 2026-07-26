# nulltap

Nulltap in your terminal. This client reads the public [nulltap.sh](https://nulltap.sh) JSON feed and prints cybersecurity and AI coverage without requiring an account.

## Install

Python 3.10 or newer is required. After the first PyPI release, install it with [pipx](https://pipx.pypa.io/):

```sh
pipx install nulltap
```

Until then, install the current version from GitHub with `pipx install git+https://github.com/JustinHowe/nulltap.git`.

Run `nulltap --help` after installation.

## Commands

```sh
nulltap                         # paginated recent articles; type a number to read
nulltap browse                  # explicit form of the default command
nulltap latest -n 20            # browse the newest 20 articles
nulltap latest --topic identity
nulltap topics                  # choose a topic, then choose an article
nulltap topic ai                # paginated articles tagged AI
nulltap topic                   # choose a topic interactively
nulltap search                  # enter search words interactively
nulltap search "token theft"
nulltap search gateway --topic appsec
nulltap read 1                  # directly read the newest article
nulltap read                    # browse first when no number is supplied
nulltap --plain                 # print once; no prompts or pager
```

Interactive lists show five articles per page so a page fits a normal terminal window. Enter the displayed number to read an article, `n` for the next page, `p` for the previous page, or `q` to leave. Use `--page-size N` to change the page size.

Articles open in the terminal pager. Headings, lists, quotations, code blocks, images, inline links, and primary sources are formatted for terminal reading. Press `q` to leave the pager and return to the article list. No browser is required.

When output is redirected, nulltap automatically disables menus and the pager. `--plain` does the same thing explicitly. Article IDs, slugs, and URLs remain accepted as direct targets for scripts, but ordinary readers should not need them.

## Search

Search belongs in the CLI because it is useful when the browser is not. It runs locally over article titles, summaries, and topic tags. Search terms are never sent to nulltap or another service.

Every word in the query must match. Title matches rank above tag and summary matches, with publication date breaking ties.

## Scripts

Add `--json` to `browse`, `latest`, `topics`, `topic`, `search`, `read`, or `show`:

```sh
nulltap search ransomware --json
nulltap topics --json
```

Use a different compatible feed during development:

```sh
nulltap --feed http://127.0.0.1:4321/feed.json
# or
NULLTAP_FEED_URL=http://127.0.0.1:4321/feed.json nulltap
```

Listing and search commands make one read-only feed request. Reading an article makes a second request for that article's text. The client has no analytics, login, local database, or background process. Feed and article text are stripped of terminal control sequences before display.

## Development

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

Licensed under the MIT License.
