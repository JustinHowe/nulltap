# Releasing nulltap to PyPI

PyPI releases use GitHub Actions Trusted Publishing. There is no long-lived PyPI password or API token in GitHub.

## Publisher configuration

The `nulltap` PyPI project trusts releases from this repository through the `pypi` GitHub environment:

- Owner: `JustinHowe`
- Repository: `nulltap`
- Workflow: `publish-to-pypi.yml`
- Environment: `pypi`

The environment requires Justin's approval before a package can be uploaded. Keep two-factor authentication enabled on PyPI and store its recovery codes securely.

If the workflow, repository, or environment name changes, update the trusted publisher at `https://pypi.org/manage/project/nulltap/settings/publishing/`.

## Release

1. Update the version in `pyproject.toml` and `src/nulltap/__init__.py`. Both must match.
2. Run the unit tests, build both distributions, and run `twine check`.
3. Merge the tested change to `main`.
4. Create a GitHub release whose tag is exactly `v<version>`, for example `v0.1.1`.
5. Review the waiting `pypi` environment deployment in GitHub Actions and approve it.
6. Confirm the release at `https://pypi.org/project/nulltap/` and install it in a clean environment with `pipx install nulltap`.

PyPI versions cannot be replaced. If a release is wrong, increment the version and publish a new one.
