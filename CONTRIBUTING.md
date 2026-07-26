# Contributing

Bug reports and focused pull requests are welcome.

## Local setup

```sh
git clone https://github.com/JustinHowe/nulltap.git
cd nulltap
python -m venv .venv
```

Activate the environment, then install the package:

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
python -m compileall -q src
```

On Windows, activate the environment with `.venv\Scripts\activate`. On macOS or Linux, use `source .venv/bin/activate`.

## Test a local feed

Use `--feed` when developing against a local copy of nulltap.sh:

```sh
nulltap --feed http://127.0.0.1:4321/feed.json
```

The `NULLTAP_FEED_URL` environment variable provides the same override. The public feed contains a topic catalog and an article list. Older feeds that contain only article items remain supported.

## Check a package

```sh
python -m pip install build twine
python -m build
python -m twine check dist/*
```

Keep user-facing installation and command examples in `README.md`. Development-only instructions belong here. Release maintainers should also read [RELEASING.md](RELEASING.md).
