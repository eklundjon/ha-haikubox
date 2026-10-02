# Contributing

This page covers setting up a development environment, running the tests and linter, what CI checks on a pull request, the smoke test used for refactors, and how releases are cut.

If you haven't read [architecture.md](architecture.md) yet, start there. It explains how the code fits together.

## Setup

The integration's only runtime dependency is `aiofiles` (see `manifest.json`). The tests also need Home Assistant, which comes from [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component) (PHACC). Each PHACC release is tied to one Home Assistant version.

With [`uv`](https://github.com/astral-sh/uv):

```bash
uv venv --python 3.14 .venv-test
uv pip install --python .venv-test/bin/python -r requirements_test.txt
.venv-test/bin/python -m pytest
```

`requirements_test.txt` doesn't pin PHACC, so a local install gets the newest Home Assistant, which needs Python 3.14 (Home Assistant 2026.5 and later do). CI also tests against the oldest supported version, so something that passes locally can still fail there. To run that version yourself, build a second venv the way CI does:

```bash
uv venv --python 3.13 .venv-min
uv pip install --python .venv-min/bin/python \
  "pytest-homeassistant-custom-component==0.13.236" -r requirements_test.txt
.venv-min/bin/python -m pytest
```

It's worth doing for anything that touches a Home Assistant API. Several of the APIs used here are newer than the 2025.4 minimum and have a fallback for older versions (see "Minimum HA version" in [architecture.md](architecture.md)), and the fallback only runs on the old version.

> `uv venv` doesn't put `pip` in the venv. You don't need it for the commands above, but if you want it, run `.venv-test/bin/python -m ensurepip`.

## Tests

```bash
.venv-test/bin/python -m pytest                       # everything
.venv-test/bin/python -m pytest tests/test_api.py     # one file
.venv-test/bin/python -m pytest -k rarity             # by keyword
```

There are about 115 tests in `tests/`, mostly one file per module (`test_api.py`, `test_image_cache.py`, `test_device_trigger.py`, `test_bats.py`, and so on). The coordinator's tests are split across several files by topic: `test_coordinator_pure.py`, `_rarity`, `_backfill`, `_events`, `_statistics`, `_update` and `_bats`.

### Building a coordinator in tests

The real coordinator `__init__` sets up an aiohttp session, seven `Store` objects, the photo and audio caches, and the `DataUpdateCoordinator` base. Most tests don't need any of that:

- **`tests/coordinator_helpers.py`**: `make_coordinator(hass, ...)` creates a `HaikuboxCoordinator` with `__new__`, skipping `__init__`, and sets only what the test needs. It uses simple fakes (`FakeStore`, `FakeImages`) and sets the box's time zone to UTC. Tests that run a whole poll stub `c._fetch_*` and `c._async_box_tz` on the instance.
- **`tests/conftest.py`**: turns on `enable_custom_integrations` for every test so HA will load the integration, and has a `bypass_frontend_setup` fixture that stubs out `frontend`. The real frontend needs the large `home-assistant-frontend` package, which PHACC doesn't include, and the tests don't touch the UI anyway.

`tests/test_api.py` tests `HaikuboxApiClient` directly with a small fake session, rather than mocking aiohttp inside the coordinator. That's one of the reasons the network code has its own module.

### Card JavaScript tests

`tests/js/` tests the card loader and the card modules' guards against being loaded twice. They use Node's built-in test runner (Node 22 or newer) and have no dependencies, so there's nothing to install:

```bash
node --test "tests/js/*.test.mjs"
```

## Linting

The linter is `ruff`, and its version is pinned in `requirements_test.txt`. CI reads the version from that file, so the pin only lives in one place:

```bash
.venv-test/bin/python -m ruff check .
```

The rules are set in `pyproject.toml`: pyflakes, pycodestyle, isort, bugbear, comprehensions and pyupgrade. I don't follow Home Assistant core's ruff config, since nothing requires it for a custom integration. Line length (`E501`) isn't checked, and there's no formatter.

## What CI checks

`.github/workflows/test.yml` runs on every push to `main` and every pull request. It has three jobs:

- **ruff**: `ruff check .` on Python 3.13 with the pinned ruff.
- **card JS**: the tests in `tests/js/` on Node 24.
- **pytest**: runs the tests against two Home Assistant versions, the minimum and the latest, by pinning PHACC:

  | Job | Python | PHACC pinned in | Home Assistant |
  |---|---|---|---|
  | minimum | 3.13 | `test.yml` (`0.13.236`) | 2025.4.4 |
  | latest | 3.14 | `requirements_ha_latest.txt` | whatever that pin is (2026.9.4 as of this writing) |

  The minimum matches `hacs.json` (2025.4, see "Minimum HA version" in [architecture.md](architecture.md)). If you raise the minimum, update this job too. It's pinned in `test.yml` so Dependabot can't move it.

  The latest pin is in its own file so Dependabot keeps it current: each week it opens a PR bumping PHACC, in its own `home-assistant` group, and that PR's CI run is where a new Home Assistant release first meets this code. PHACC's own Python floor moves with Home Assistant's. When it rises, raise the latest job's `python` in `test.yml` and the repo's `.python-version` (which Dependabot resolves with) in the same PR.

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

1. **Change the version** in `manifest.json` in its own PR, and merge it. Write the release notes in that commit (see below).
2. **CI creates a draft release** (`.github/workflows/release.yaml`) pointing at the merge commit. There's no tag yet. A version that isn't a plain `X.Y.Z`, such as `1.0.0-rc1`, is drafted as a pre-release, so HACS only offers it to people who've turned on beta versions.
3. **Check the draft and publish.** Publishing creates the tag. It's the only step that can't be undone, so a person does it.

The draft's title and notes come from the version-bump commit:

- A subject of the form `Release 1.0.0-rc1: Bats and polish` titles the draft `v1.0.0-rc1 Bats and polish`. Any other subject gets the bare `v1.0.0-rc1`.
- The body, minus trailers like `Co-Authored-By`, goes above GitHub's generated list of merged PRs.
- Write the message in a file and commit with `git commit -F <file>`. Git's editor mode deletes lines starting with `#`, which would take markdown headings with them.

Write the notes for where people read them, which is mostly not GitHub. Home Assistant's update dialog (**Settings → Updates**) shows them under the version numbers, and when someone skips versions it stacks every release in between, newest first, each under a big heading HACS adds itself. So:

- Lead with what a user has to know or do: anything that breaks, needs a restart or needs reconfiguring. Then the headline changes. Details and the PR list come last.
- Use `###` headings or bold inside the notes. HACS already puts a `#` heading on each release.
- Use full URLs. The dialog doesn't rewrite relative links.

HACS shows this repository's `README.md` as its page, before and after install, and it fetches the README as of the latest release (or the installed one), not `main`. A README change reaches HACS users only with the next release.

If you change your mind before step 3, delete the draft and change the version again. Nothing has been tagged, so there's nothing to clean up.

It's done this way because HACS gets an integration's version from the tag of the latest release, and installs the code at that tag. The code at the tag has to have the matching version in `manifest.json`, and making the tag from the manifest guarantees it. The old workflow went the other way: publish a release, then update `manifest.json` and move the tag to the new commit. For a while the published tag pointed at the old version, and releases could change after they were published.

Two details in the workflow matter, so please don't "simplify" them:

- The draft is created with `--target "$GITHUB_SHA"`, not `main`. A draft's target is only resolved when it's published, so targeting a branch would let anything merged in the meantime end up in the release.
- The check for an existing release uses `gh release list`, not `gh release view "$TAG"`. A draft has no tag until it's published, and GitHub only documents the get-release-by-tag API for published releases, but the list includes drafts. That's what makes the job safe to run more than once. It also runs on manifest edits that don't change the version, and GitHub allows several drafts with the same tag name.
