# Contributing

This page covers the development loop: setting up an environment, running the
test suite and linter locally, what CI enforces on a pull request, and the smoke
harness used to keep coordinator refactors behaviour-preserving.

For how the code is organised, read [docs/architecture.md](architecture.md)
first — it's the map. This page is about working *on* the code.

## Local setup

The integration's only runtime dependency is `aiofiles` (see `manifest.json`).
The test environment adds Home Assistant itself, via
[pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)
(PHACC), which pins the exact Home Assistant version it was built against.

The quickest loop uses [`uv`](https://github.com/astral-sh/uv):

```bash
uv venv --python 3.13 .venv-test
uv pip install --python .venv-test/bin/python -r requirements_test.txt
.venv-test/bin/python -m pytest
```

`requirements_test.txt` leaves PHACC unpinned, so a local install pulls the
latest (newest Home Assistant) for a fast dev loop. CI pins specific versions —
see the matrix below — so a change that passes locally against the latest HA can
still be exercised against the declared minimum in CI.

> Note: `uv venv` does not bootstrap `pip` into the venv. The commands above
> don't need it (they install via `uv pip` from outside), but if you want a
> `pip` inside the venv, run `.venv-test/bin/python -m ensurepip` first.

## Running the tests

```bash
.venv-test/bin/python -m pytest                       # everything
.venv-test/bin/python -m pytest tests/test_api.py     # one file
.venv-test/bin/python -m pytest -k rarity             # by keyword
```

The suite is around 75 tests across the modules in `tests/`, organised roughly
one file per source module (`test_api.py`, `test_image_cache.py`,
`test_device_trigger.py`, and so on), with the coordinator split across several
files by concern (`test_coordinator_pure.py`, `_rarity`, `_backfill`, `_events`,
`_statistics`, `_update`).

### How the tests stand up a coordinator

The coordinator's `__init__` wires an aiohttp session, six `Store` objects, the
image/audio caches and the `DataUpdateCoordinator` base. Most unit tests don't
want all that. Two patterns keep them light:

- **`tests/coordinator_helpers.py`** — `make_coordinator(hass, ...)` builds a
  `HaikuboxCoordinator` via `__new__` (bypassing `__init__`) and sets only the
  attributes the method under test touches, with deterministic fakes
  (`FakeStore`, `FakeImages`) and the box timezone pre-resolved to UTC. Tests
  that drive a real poll still stub `c._fetch_*` / `c._async_box_tz` per
  instance.
- **`tests/conftest.py`** — an autouse `enable_custom_integrations` fixture (so
  HA will load the custom component) and a `bypass_frontend_setup` fixture that
  stubs `frontend` setup. The integration declares `frontend` to register its
  card JS; real frontend setup needs the heavyweight `home-assistant-frontend`
  wheel that PHACC doesn't ship, and these tests don't exercise the UI.

The HTTP layer is tested directly against `HaikuboxApiClient` in
`tests/test_api.py` with a tiny fake session, rather than mocking aiohttp deep
in the coordinator — one of the reasons the network code now lives in its own
module (see [docs/architecture.md](architecture.md)).

## Linting

Linting is `ruff`, pinned to the same version in `requirements_test.txt` and in
CI so local and CI never disagree:

```bash
.venv-test/bin/python -m ruff check .
```

The rule set is deliberately lean and self-owned (`pyproject.toml`): pyflakes,
pycodestyle, isort, bugbear, comprehensions, and pyupgrade. We do **not** track
Home Assistant core's ruff config — nothing enforces it on a custom component
and chasing it is pure churn. Line length (`E501`) is ignored; there's no
formatter in play, so line breaks are a judgement call.

## What CI enforces

`.github/workflows/test.yml` runs on every push to `main` and every pull
request, in two jobs:

- **ruff** — `ruff check .` on Python 3.13 with the pinned ruff.
- **pytest** — a matrix that pins PHACC (and therefore Home Assistant) to two
  points: the declared minimum and the latest. Each PHACC release pins one exact
  HA version, so pinning PHACC pins HA:

  | Job | PHACC | Home Assistant |
  |---|---|---|
  | minimum | `0.13.236` | 2025.4.4 |
  | latest | `0.13.316` | 2026.2.3 |

  The minimum tracks `hacs.json`'s floor (2025.4 — the recorder statistics API
  the long-term Statistics backfill needs; see the "Minimum HA version" note in
  [docs/architecture.md](architecture.md)). When you raise that floor, update the
  matrix to match.

Both jobs must pass for a PR to merge (the required checks include the two
matrix jobs plus the `hassfest` and `hacs` validation workflows). Docs-only
changes still run the full suite.

### Coverage gate

The pytest job runs under coverage and fails under a floor:

```bash
.venv-test/bin/python -m pytest \
  --cov=custom_components.haikubox --cov-report=term-missing --cov-fail-under=84
```

The floor sits a couple of points below the current coverage (~86%) so a trivial
change doesn't trip it. Ratchet it up over time rather than letting coverage
drift down to meet it.

## The refactor smoke harness

`scripts/coordinator_smoke.py` drives the real
`HaikuboxCoordinator._async_update_data` with canned, deterministic inputs (no
network, no Home Assistant) and prints a stable structural summary of the result
dict:

```bash
.venv-test/bin/python scripts/coordinator_smoke.py
```

It exists to prove a refactor is behaviour-preserving: capture the output before
your change, apply the change, run it again, and diff. The coordinator split
into `api.py` / `normalize.py` / `statistics.py` was verified this way — the
summary stayed byte-identical across each step. Detection timestamps are
generated relative to "now" so the recency/24h windows have stable membership,
but the raw timestamps are excluded from the summary, and notability is forced
to pure-rarity so the output doesn't depend on wall-clock recency.

This is a complement to the unit tests, not a replacement: the tests assert
specific behaviours; the smoke harness catches *any* unintended change to the
overall output shape during a structural refactor.

## Pull request conventions

- Branch off `main`; one focused change per PR.
- Run `ruff check .` and the test suite locally before pushing — CI runs the
  same thing, so catching it locally is faster.
- Leave `manifest.json`'s `version` alone in feature PRs — bumping it is its own
  deliberate step, and it is what starts a release (see
  [Cutting a release](#cutting-a-release)).
- Keep commit messages and PR descriptions plain text (no emoji), matching the
  existing history.

## Cutting a release

`custom_components/haikubox/manifest.json` is the single source of truth for the
version. The tag is derived from it, never the other way round, so the version
string is written in exactly one place.

1. **Bump the version** in `manifest.json` in its own PR, and merge it to `main`.
2. **CI opens a draft release** (`.github/workflows/release.yaml`): it reads the
   version, and drafts a release named `v<version>` pinned to the merge commit.
   No tag exists yet.
3. **Write the notes and publish.** Publishing is what creates the tag — it is
   the one irreversible step, and a human takes it deliberately.

Change your mind before step 3? Delete the draft and bump again. Nothing has
been tagged, so there is nothing to clean up.

Why it's built this way: HACS resolves an integration's version from the *tag
name of the latest published release*, and installs the repository tree at that
tag. So the tree a tag points at must already carry the matching manifest
version. Deriving the tag from the manifest guarantees that by construction. The
previous workflow ran the other direction — publish a release, then rewrite
`manifest.json` and force-move the tag onto the new commit — which left a window
where the published tag pointed at a stale version, and made release snapshots
mutable after the fact.

Two details in the workflow are load-bearing, so don't "simplify" them away:

- The draft is pinned with `--target "$GITHUB_SHA"`, not to `main`. A draft's
  target is resolved when it is published, so a branch target would let anything
  merged in the meantime move the tag to a later commit.
- The `gh release view` guard makes the job idempotent. It also fires on
  manifest edits that don't change the version, and GitHub permits several
  drafts sharing one tag name.
