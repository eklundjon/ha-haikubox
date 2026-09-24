# Contributing

This page covers setting up a development environment, running the tests and linter, what CI checks on a pull request, the smoke test used for refactors, and how releases are cut.

If you haven't read [architecture.md](architecture.md) yet, start there. It explains how the code fits together.

## Setup

The integration's only runtime dependency is `aiofiles` (see `manifest.json`). The tests also need Home Assistant, which comes from [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component) (PHACC). Each PHACC release is tied to one Home Assistant version.

With [`uv`](https://github.com/astral-sh/uv):

```bash
uv venv --python 3.13 .venv-test
uv pip install --python .venv-test/bin/python -r requirements_test.txt
.venv-test/bin/python -m pytest
```

`requirements_test.txt` doesn't pin PHACC, so a local install gets the newest Home Assistant. CI also tests against the oldest supported version (see below), so something that passes locally can still fail there.

> `uv venv` doesn't put `pip` in the venv. You don't need it for the commands above, but if you want it, run `.venv-test/bin/python -m ensurepip`.

## Tests

```bash
.venv-test/bin/python -m pytest                       # everything
.venv-test/bin/python -m pytest tests/test_api.py     # one file
.venv-test/bin/python -m pytest -k rarity             # by keyword
```

There are about 80 tests in `tests/`, mostly one file per module (`test_api.py`, `test_image_cache.py`, `test_device_trigger.py`, and so on). The coordinator's tests are split across several files by topic: `test_coordinator_pure.py`, `_rarity`, `_backfill`, `_events`, `_statistics` and `_update`.

### Building a coordinator in tests

The real coordinator `__init__` sets up an aiohttp session, six `Store` objects, the photo and audio caches, and the `DataUpdateCoordinator` base. Most tests don't need any of that:

- **`tests/coordinator_helpers.py`**: `make_coordinator(hass, ...)` creates a `HaikuboxCoordinator` with `__new__`, skipping `__init__`, and sets only what the test needs. It uses simple fakes (`FakeStore`, `FakeImages`) and sets the box's time zone to UTC. Tests that run a whole poll stub `c._fetch_*` and `c._async_box_tz` on the instance.
- **`tests/conftest.py`**: turns on `enable_custom_integrations` for every test so HA will load the integration, and has a `bypass_frontend_setup` fixture that stubs out `frontend`. The real frontend needs the large `home-assistant-frontend` package, which PHACC doesn't include, and the tests don't touch the UI anyway.

`tests/test_api.py` tests `HaikuboxApiClient` directly with a small fake session, rather than mocking aiohttp inside the coordinator. That's one of the reasons the network code has its own module.

## Linting

The linter is `ruff`, and its version is pinned in `requirements_test.txt`. CI reads the version from that file, so the pin only lives in one place:

```bash
.venv-test/bin/python -m ruff check .
```

The rules are set in `pyproject.toml`: pyflakes, pycodestyle, isort, bugbear, comprehensions and pyupgrade. I don't follow Home Assistant core's ruff config, since nothing requires it for a custom integration. Line length (`E501`) isn't checked, and there's no formatter.

## What CI checks

`.github/workflows/test.yml` runs on every push to `main` and every pull request. It has two jobs:

- **ruff**: `ruff check .` on Python 3.13 with the pinned ruff.
- **pytest**: runs the tests against two Home Assistant versions, the minimum and the latest, by pinning PHACC:

  | Job | PHACC | Home Assistant |
  |---|---|---|
  | minimum | `0.13.236` | 2025.4.4 |
  | latest | `0.13.316` | 2026.2.3 |

  The minimum matches `hacs.json` (2025.4, see "Minimum HA version" in [architecture.md](architecture.md)). If you raise the minimum, update this job too.

A pull request needs both test jobs, plus `hassfest` and HACS validation, to pass before it can merge. Documentation-only changes run everything too.

### Coverage

The pytest job fails if coverage drops below a minimum:

```bash
.venv-test/bin/python -m pytest \
  --cov=custom_components.haikubox --cov-report=term-missing --cov-fail-under=84
```

The minimum is a couple of points under the current coverage (about 86%), so a small change doesn't trip it. Raise it over time instead of letting coverage slide down to meet it.

## The refactor smoke test

`scripts/coordinator_smoke.py` runs the real `HaikuboxCoordinator._async_update_data` on fixed, made-up data (no network, no Home Assistant) and prints a summary of the result:

```bash
.venv-test/bin/python scripts/coordinator_smoke.py
```

Use it to check that a refactor doesn't change behavior: save the output, make your change, run it again, and diff the two. The split into `api.py`, `normalize.py` and `statistics.py` was checked this way, and the output stayed identical at every step. Detection times are generated relative to now so the 1-hour and 24-hour windows always contain the same birds, the times themselves are left out of the summary, and notability is set to pure rarity so the output doesn't depend on the clock.

It doesn't replace the tests. The tests check specific behavior. The smoke test catches any unexpected change to the output during a restructuring.

## Pull requests

- Branch off `main` and keep each PR to one change.
- Run `ruff check .` and the tests before pushing. CI runs the same things, so it's faster to catch problems locally.
- Don't change the `version` in `manifest.json` in a feature PR. Changing it starts a release (see [Cutting a release](#cutting-a-release)).
- Keep commit messages and PR descriptions to plain text, with no emoji.

## Cutting a release

The version lives in one place: `custom_components/haikubox/manifest.json`. The release tag is made from it, never the other way around.

1. **Change the version** in `manifest.json` in its own PR, and merge it.
2. **CI creates a draft release** (`.github/workflows/release.yaml`) called `v<version>`, pointing at the merge commit. There's no tag yet.
3. **Write the release notes and publish.** Publishing creates the tag. It's the only step that can't be undone, so a person does it.

If you change your mind before step 3, delete the draft and change the version again. Nothing has been tagged, so there's nothing to clean up.

It's done this way because HACS gets an integration's version from the tag of the latest release, and installs the code at that tag. The code at the tag has to have the matching version in `manifest.json`, and making the tag from the manifest guarantees it. The old workflow went the other way: publish a release, then update `manifest.json` and move the tag to the new commit. For a while the published tag pointed at the old version, and releases could change after they were published.

Two details in the workflow matter, so please don't "simplify" them:

- The draft is created with `--target "$GITHUB_SHA"`, not `main`. A draft's target is only resolved when it's published, so targeting a branch would let anything merged in the meantime end up in the release.
- The check for an existing release uses `gh release list`, not `gh release view "$TAG"`. A draft has no tag until it's published, and GitHub only documents the get-release-by-tag API for published releases, but the list includes drafts. That's what makes the job safe to run more than once. It also runs on manifest edits that don't change the version, and GitHub allows several drafts with the same tag name.
