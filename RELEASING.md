# Releasing nulltap to PyPI

PyPI releases use GitHub Actions Trusted Publishing. There is no long-lived PyPI password or API token in GitHub.

## One-time setup

1. Create a PyPI account, enable two-factor authentication, and add recovery codes to a secure password manager.
2. In the `JustinHowe/nulltap` GitHub repository, create an environment named `pypi`. Add Justin as a required reviewer and prevent administrators from bypassing the rule.
3. At `https://pypi.org/manage/account/publishing/`, add a pending GitHub publisher with:
   - PyPI project name: `nulltap`
   - Owner: `JustinHowe`
   - Repository: `nulltap`
   - Workflow: `publish-to-pypi.yml`
   - Environment: `pypi`

The pending publisher creates the PyPI project on the first successful release.

## Release

1. Update the version in `pyproject.toml` and `src/nulltap/__init__.py`. Both must match.
2. Merge the tested change to `main`.
3. Create a GitHub release whose tag is exactly `v<version>`, for example `v0.1.0`.
4. Review the waiting `pypi` environment deployment in GitHub Actions and approve it.
5. Confirm the release at `https://pypi.org/project/nulltap/` and install it in a clean environment with `pipx install nulltap`.

PyPI versions cannot be replaced. If a release is wrong, increment the version and publish a new one.
