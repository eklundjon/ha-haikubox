from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .audio_cache import AudioCache
from .const import (
    ACTIVITY_BASELINE_DAYS,
    API_BASE,
    BACKFILL_REQUEST_DELAY,
    BACKFILL_STOP_AFTER_404,
    CONF_ABSENCE_DAYS,
    CONF_AUDIO_CACHE_DAYS,
    CONF_AUDIO_ENABLED,
    CONF_AUDIO_NORM_TARGET,
    CONF_DEVICE_NAME,
    CONF_NEW_SPECIES_WINDOW_DAYS,
    CONF_NOTABLE_RARITY_WEIGHT,
    CONF_RARITY_WINDOW_DAYS,
    CONF_RECENT_WINDOW_HOURS,
    CONF_SCAN_INTERVAL,
    CONF_SERIAL,
    CONF_WATCHED_EXTRA,
    CONF_WATCHED_SPECIES,
    DAILY_WINDOW_HOURS,
    DEFAULT_ABSENCE_DAYS,
    DEFAULT_AUDIO_CACHE_DAYS,
    DEFAULT_AUDIO_ENABLED,
    DEFAULT_AUDIO_NORM_TARGET,
    DEFAULT_NOTABLE_RARITY_WEIGHT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_HAIKUBOX,
    HEADLINE_AUDIO_DAYS,
    HISTORY_BACKFILL_CHUNK,
    IMAGES_BASE,
    LAST_DETECTION_EVENT_LIMIT,
    MAX_AUDIO_CLIPS,
    NEW_SPECIES_HISTORY_LIMIT,
    NEW_SPECIES_WINDOW_DAYS,
    NOTABILITY_WINDOW_HOURS,
    RARITY_BACKFILL_CHUNK,
    RARITY_WINDOW_DAYS,
    RECENT_WINDOW_HOURS,
    TRIGGER_NEW_SPECIES,
    TRIGGER_UNUSUAL_VISITOR,
    TRIGGER_WATCHED_SPECIES,
)
from .image_cache import ImageCache

_LOGGER = logging.getLogger(__name__)

_STORE_VERSION = 1

# Per-box .storage suffixes (each file is `haikubox.<serial>.<suffix>`). The
# current set must mirror the Store(...) constructors in __init__; the legacy
# set is the orphaned stores earlier versions wrote. Both are removed when the
# entry is removed (async_remove_stores); the legacy set is also cleaned up
# once per session at load.
_STORE_SUFFIXES = (
    "seen_species",
    "sp_codes",
    "sci_names",
    "last_seen",
    "daily_counts",
    "recent_events",
)
_LEGACY_STORE_SUFFIXES = ("yearly", "seven_day", "sticky")

# Config entry whose runtime_data is the coordinator (lazily evaluated,
# so the forward reference to the class below is fine).
type HaikuboxConfigEntry = ConfigEntry[HaikuboxCoordinator]


# Bundled common-name → {eBird species_code, scientific name} fallback map.
# Haikubox's sp_code is the eBird species code (the image S3 is keyed by it),
# but we only *learn* a species' code and scientific name from the /detections
# sample, which omits rarely-heard species. This derived map (from the
# eBird/Clements taxonomy) lets daily-count-only species still resolve an image
# and a scientific name. See data/ebird_species_codes.json + NOTICE.
#
# Loaded once, off the event loop (~750 KB of JSON), via
# _async_load_ebird_species; _sp_code_for / _sci_name_for read the cache.
_EBIRD_SPECIES: dict[str, dict[str, str]] | None = None


def _read_ebird_species() -> dict[str, dict[str, str]]:
    """Blocking read+parse of the bundled map. Call only via the executor."""
    path = Path(__file__).parent / "data" / "ebird_species_codes.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("names", {})
    except (OSError, ValueError):
        _LOGGER.warning("Could not load bundled eBird species map")
        return {}


async def _async_load_ebird_species(hass: HomeAssistant) -> None:
    """Populate the module-level eBird species cache once, off the event loop."""
    global _EBIRD_SPECIES
    if _EBIRD_SPECIES is None:
        _EBIRD_SPECIES = await hass.async_add_executor_job(_read_ebird_species)


def _ffmpeg_binary(hass: HomeAssistant) -> str | None:
    """Resolve the ffmpeg binary for audio normalization (None if unavailable).

    Prefer HA's ffmpeg component (bundled in standard installs); fall back to a
    binary on PATH. When neither exists, audio normalization is silently skipped
    and clips are served at their raw (quiet) level.
    """
    try:
        from homeassistant.components.ffmpeg import get_ffmpeg_manager

        return get_ffmpeg_manager(hass).binary
    except (KeyError, HomeAssistantError, ImportError, ValueError):
        # ValueError: get_ffmpeg_manager raises it when the ffmpeg component
        # isn't set up. ffmpeg is only an after-dependency (not forced), so on
        # a minimal install without it this is reached — fall back to PATH and,
        # failing that, None, rather than letting the whole coordinator fail to
        # construct.
        from shutil import which

        return which("ffmpeg")


class HaikuboxCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the Haikubox API and normalises the response for sensors."""

    def __init__(self, hass: HomeAssistant, entry: HaikuboxConfigEntry) -> None:
        serial = entry.data[CONF_SERIAL]
        # Poll interval is user-tunable (minutes); an options change reloads the
        # entry, so a new interval takes effect via this fresh coordinator.
        scan_minutes = entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL // 60
        )
        super().__init__(
            hass,
            _LOGGER,
            # Include the serial so coordinator log lines disambiguate which box
            # they refer to when more than one Haikubox is configured.
            name=f"{DOMAIN} {serial}",
            config_entry=entry,
            update_interval=timedelta(minutes=scan_minutes),
        )
        self.serial = serial
        self.device_name = entry.data.get(CONF_DEVICE_NAME, "Haikubox")
        self._session = async_get_clientsession(hass)
        # The box's own timezone (from the box-info endpoint), resolved lazily
        # on the first poll and cached. /daily-count is keyed to the box's local
        # calendar day, so day-boundary math must use the box's tz — the box may
        # sit in a different timezone than the Home Assistant host.
        self._box_tz: tzinfo | None = None

        # Rarity baseline — a trailing RARITY_WINDOW_DAYS aggregate over the
        # per-day counts, rebuilt every poll (cheap). The `yearly_*` data keys /
        # `yearly_rank` record field that this feeds keep their names for
        # backward compatibility (entity ids, event payload, cards, docs).
        self._baseline_ranks: dict[str, int] = {}   # species → rank (1 = most common)
        self._baseline_species_count: int = 0
        # Whether the first-seen log has been reconciled against _daily_counts
        # at least once this session (the reconciliation otherwise runs only
        # when the per-day history changes).
        self._reconciled_once: bool = False

        # Rolling buffer of the most-recent detection EVENTS (newest-first,
        # capped at LAST_DETECTION_EVENT_LIMIT), persisted. This is what backs
        # last_detection: "the last detection" is the last detection no matter
        # how old, so it must NOT drain when the live /detections feed empties
        # (box offline). The buffer survives restarts and outages; its head is
        # the last_detection state. (Replaces the old sticky single — see #62.)
        # notable_species is deliberately NOT sticky: it's "notable observed in
        # the last 24 h", so it drains to unknown with its window.
        self._event_buffer: list[dict[str, Any]] = []

        # Persistent stores. Kept as SEPARATE files on purpose — do NOT merge
        # them into one combined store. Each is saved independently (gated by its
        # own dirty flag), and they change at very different cadences: last_seen
        # and recent_events on nearly every active poll, but daily_counts (the
        # large, full-box-lifetime history) only ~once a day, and the lookup maps
        # only when a new species appears. Combining them would rewrite the whole
        # blob — including the big daily_counts — on every poll that touches the
        # frequently-changing data, multiplying disk writes (flash/SD wear) for
        # no functional gain. The current split keeps each write proportional to
        # what actually changed. (See _STORE_SUFFIXES for the removal list.)
        self._store            = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.seen_species")
        self._sp_codes_store   = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.sp_codes")
        self._sci_names_store  = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.sci_names")
        self._last_seen_store  = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.last_seen")
        self._daily_store      = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.daily_counts")
        self._events_store     = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.recent_events")

        # In-memory store state
        self._seen_species: dict[str, str] = {}          # species → first_seen ISO
        self._sp_codes: dict[str, str] = {}              # species → sp_code
        self._sci_names: dict[str, str] = {}             # species → scientific_name
        self._last_seen: dict[str, str] = {}             # species → last_seen ISO
        self._baseline_items: list[dict[str, Any]] = []    # trailing-window baseline [{species, count, rank}]
        self._daily_counts: dict[str, dict[str, int]] = {}  # date_str → {species: count}, full lifetime
        self._stats_imported_date: date | None = None    # long-term statistics backfill, once per box-day
        self._backfill_complete: bool = False            # reached the pre-install 404 floor
        self._backfill_cursor: str | None = None         # oldest date the deep backfill has probed
        self._backfill_misses: int = 0                   # consecutive 404s at the leading (oldest) edge

        # Automation-event edge detection. Species present in the recent
        # window on the previous poll — used to fire unusual_visitor only on
        # a species's (re)appearance, not every poll while it lingers. None
        # until the first poll of the session establishes the baseline; that
        # first poll fires no unusual_visitor events (avoids a restart flood).
        self._prev_recent_species: set[str] | None = None

        # Species photo cache (downloads once, served via our static path)
        self._images = ImageCache(hass, self._session)
        # Detection-audio cache (downloads recent clips, served via our static path);
        # ffmpeg (bundled with HA) is used to peak-normalize the quiet clips.
        # The whole pipeline is opt-in (read once here; options changes reload
        # the entry, so this is re-evaluated): when off, nothing is indexed,
        # fetched, normalized or pruned, and no audio_url is exposed.
        self._audio = AudioCache(
            hass,
            self._session,
            self.serial,
            _ffmpeg_binary(hass),
            entry.options.get(CONF_AUDIO_NORM_TARGET, DEFAULT_AUDIO_NORM_TARGET),
        )
        self._audio_enabled = entry.options.get(
            CONF_AUDIO_ENABLED, DEFAULT_AUDIO_ENABLED
        )
        # Per-poll map: species code → its most-recent clip URL (for audio resolve)
        self._latest_wav_by_species: dict[str, str] = {}

    @staticmethod
    async def async_remove_stores(hass: HomeAssistant, serial: str) -> None:
        """Delete this box's persistent .storage files (current + legacy).

        Called from async_remove_entry when the integration entry is removed.
        Store.async_remove() no-ops if a file is already gone. The shared image
        cache under config/haikubox/ is NOT touched here — it's keyed by
        species code, not serial, so it's cleaned up only when the last box
        goes away (see __init__.async_remove_entry)."""
        for suffix in (*_STORE_SUFFIXES, *_LEGACY_STORE_SUFFIXES):
            await Store(
                hass, _STORE_VERSION, f"{DOMAIN}.{serial}.{suffix}"
            ).async_remove()

    # ------------------------------------------------------------------
    # DataUpdateCoordinator interface
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        # Anchor "today" to the box's OWN timezone, NOT UTC. The /daily-count
        # endpoint is keyed to the box's local calendar day, and the per-day
        # store, 7-day window, and once-per-day refresh should all turn over on
        # that same local midnight. A UTC "today" runs ahead of the box's day
        # every evening west of UTC, so the today /daily-count request asked for
        # a not-yet-existent date (HTTP 400) and zeroed "Detections today" until
        # UTC midnight. The box's tz comes from the API (it may differ from the
        # HA host's); until it resolves, dt_util.now() falls back to HA's tz.
        # (Supersedes the earlier UTC anchoring from issue #16.)
        today = dt_util.now(await self._async_box_tz()).date()

        # Keep the per-day counts store fresh (fetch newly-completed days +
        # a throttled chunk of historical backfill), then rebuild the rarity
        # baseline by aggregating the trailing RARITY_WINDOW_DAYS. This slides
        # continuously, so it never resets on Jan 1 the way /yearly-count did.
        daily_changed = False
        try:
            daily_changed = await self._ensure_daily_counts(today)
        except aiohttp.ClientError as err:
            _LOGGER.warning("Could not fetch daily counts: %s", err)
        self._rebuild_baseline(today)

        # If we still have no baseline, every rarity_score would collapse to
        # 1.0 and notable_species / rarest_species would lose their meaning.
        # Fail loudly instead of computing silently-wrong rankings. Only a true
        # fresh install whose first /daily-count fetch failed reaches here; any
        # prior success rehydrates _daily_counts from .storage at load time, and
        # HA retries the first refresh automatically, so this self-heals.
        if not self._baseline_ranks:
            raise UpdateFailed(
                "Rarity baseline not yet available — /daily-count backfill has "
                "no data yet and there is no cached history"
            )

        # Backfill HA long-term statistics straight from the per-day counts store
        # (no API call). Once per box-local calendar day; idempotent, so it also
        # fills days as the deep backfill keeps accumulating them. No recorder →
        # skip cleanly for the day.
        if self._stats_imported_date != today:
            if "recorder" not in (self.hass.config.components if self.hass else ()):
                self._stats_imported_date = today
            elif self._daily_counts:
                try:
                    await self._import_history_statistics()
                    self._stats_imported_date = today
                except (aiohttp.ClientError, HomeAssistantError) as err:
                    _LOGGER.warning("Could not import history statistics: %s", err)

        try:
            daily_raw = await self._fetch_detections(DAILY_WINDOW_HOURS)
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error communicating with Haikubox API: {err}") from err

        # Single API call: the 24h window is a superset of the 1h window we
        # used to fetch separately. Derive the recent subset client-side at
        # the raw level so `count` on recent_detections items reflects
        # detections-in-last-hour, not detections-in-last-24h.
        recent_hours = self.config_entry.options.get(
            CONF_RECENT_WINDOW_HOURS, RECENT_WINDOW_HOURS
        )
        recent_threshold = datetime.now(UTC) - timedelta(hours=recent_hours)
        recent_raw = {"detections": _filter_by_dt(daily_raw, recent_threshold)}

        # Map each species → its most-recent clip URL (a ~1h presigned FLAC).
        # The audio cache/resolve below works off this; empty when audio is
        # unavailable (or in the offline smoke), which short-circuits it.
        self._latest_wav_by_species = _latest_wav_by_species(daily_raw)

        detections = _normalise_detections(recent_raw)
        _apply_rarity_scores(detections, self._baseline_ranks, self._baseline_species_count)

        # "Daily" sensors use a true trailing 24-hour window derived from
        # /detections (not the server-side calendar-day /daily-count),
        # ordered by detection count so daily_top_species ranks by 24h volume.
        # Normalised here (earlier than its downstream uses) so the
        # fresh-install bootstrap below sees the full 24h species list
        # before the recent-window new-species loop populates _seen_species
        # from the 1h subset — the gap that issue #14 surfaced.
        daily_count = sorted(
            _normalise_detections(daily_raw),
            key=lambda x: x.get("count", 0),
            reverse=True,
        )
        _apply_rarity_scores(daily_count, self._baseline_ranks, self._baseline_species_count)

        # Cache images and rewrite image_url to local path
        for d in detections:
            if d.get("sp_code"):
                d["image_url"] = await self._images.async_fetch(d["sp_code"])

        # Snapshot last_seen before the update loop overwrites it, so the
        # unusual_visitor event can measure each species' absence gap against
        # when we *previously* heard it (not this poll's timestamp).
        prior_last_seen = dict(self._last_seen)

        # Update sp_codes, scientific_name, and last_seen lookups. The
        # dirty flags also accumulate adds from the bootstrap below, so
        # one save per dict at the end covers both populations.
        sp_codes_dirty = False
        sci_names_dirty = False
        last_seen_dirty = False
        for d in detections:
            sp = d["species"]
            if d.get("sp_code") and sp not in self._sp_codes:
                self._sp_codes[sp] = d["sp_code"]
                sp_codes_dirty = True
            if d.get("scientific_name") and sp not in self._sci_names:
                self._sci_names[sp] = d["scientific_name"]
                sci_names_dirty = True
            ts = d.get("last_seen")
            if ts and ts > self._last_seen.get(sp, ""):
                self._last_seen[sp] = ts
                last_seen_dirty = True

        seen_dirty = False

        # Reconcile the lifetime first-seen log against the per-day history —
        # only when that history actually changed this poll (new/backfilled
        # days), or once per session as a safety net. Walking all of
        # _daily_counts every poll is wasted work once the store is stable.
        if daily_changed or not self._reconciled_once:
            if self._reconcile_first_seen():
                seen_dirty = True
            self._reconciled_once = True

        # Fresh-install bootstrap for _seen_species. Must run BEFORE the
        # recent-window loop below; otherwise that loop would seed
        # _seen_species from the 1h subset only and species detected 2-24h
        # ago would silently miss their "new" flagging until they next
        # appear in a recent window (issue #14).
        #
        # Also fills _sp_codes / _sci_names / _last_seen for those same
        # 24h-tail species so their records in new_species.detections
        # have full metadata (image_url, scientific_name, last_seen) on
        # poll 1 — without this, the detections loop above would only
        # have populated the lookups for the 1h subset and tail species
        # would render with the placeholder until they next hit the
        # recent window (issue #27).
        #
        # We use each species' *earliest* dt in the 24h window as
        # first_seen — accurate for our observation window (the box's
        # true lifetime first-detection date is fundamentally
        # inaccessible). daily_count carries last_seen (the max dt per
        # species); the actual earliest dt has to come from the raw
        # payload (issue #19 item F).
        # Image fetches populate the cache so _build_new_species_history
        # (which reads via url_for) returns cached URLs for seeded species.
        if not self._seen_species and daily_count:
            first_seen_by_species = _first_seen_per_species(daily_raw)
            for d in daily_count:
                sp = d["species"]
                if not sp:
                    continue
                if d.get("sp_code"):
                    await self._images.async_fetch(d["sp_code"])
                    if sp not in self._sp_codes:
                        self._sp_codes[sp] = d["sp_code"]
                        sp_codes_dirty = True
                if d.get("scientific_name") and sp not in self._sci_names:
                    self._sci_names[sp] = d["scientific_name"]
                    sci_names_dirty = True
                ts = d.get("last_seen")
                if ts and ts > self._last_seen.get(sp, ""):
                    self._last_seen[sp] = ts
                    last_seen_dirty = True
                # Prefer the actual earliest dt; fall back to last_seen
                # then to today if neither parses (the original behaviour).
                self._seen_species[sp] = (
                    first_seen_by_species.get(sp)
                    or d.get("last_seen")
                    or today.isoformat()
                )
                seen_dirty = True

        if sp_codes_dirty:
            await self._sp_codes_store.async_save(self._sp_codes)
        if sci_names_dirty:
            await self._sci_names_store.async_save(self._sci_names)
        if last_seen_dirty:
            await self._last_seen_store.async_save(self._last_seen)

        # Track new (never-before-seen) species from the recent window.
        # On a fresh install this is a no-op (the bootstrap above already
        # covered everything in the 24h superset); on established installs
        # this is the live new-species detector. `newly_seen` drives the
        # new_species automation event — naturally silent on fresh install
        # since the bootstrap pre-seeded _seen_species.
        newly_seen: set[str] = set()
        for d in detections:
            sp = d["species"]
            if sp not in self._seen_species:
                self._seen_species[sp] = d.get("last_seen") or today.isoformat()
                newly_seen.add(sp)
                seen_dirty = True
        if seen_dirty:
            await self._store.async_save(self._seen_species)

        # rarest_species: species heard in the last 7 days, scored by the
        # trailing-window rarity baseline. The 7-day set comes from the
        # persisted daily_counts (completed days) plus today's live 24h list
        # (so today counts before it's a completed day in the store).
        seven_day_rare = self._build_rarest(daily_count, today)

        # Notability: weighted blend of rarity_score (yearly-rank-derived,
        # stable across the day) and recency_score (linear decay over a 24h
        # window). The user controls the blend via a config option; high
        # weight on rarity → stable list dominated by long-tail species; high
        # weight on recency → dynamic list of what just happened. Computed over
        # the 24h list (not the 1h subset) so recency has real dynamic range.
        # notable is deliberately NOT sticky — it drains with its 24h window
        # (#62), so notable_detection in the data dict is the current top, or
        # None when the window is empty (box quiet/offline) → sensor "unknown".
        rarity_weight = self.config_entry.options.get(
            CONF_NOTABLE_RARITY_WEIGHT, DEFAULT_NOTABLE_RARITY_WEIGHT
        ) / 100.0
        _apply_notability_scores(
            daily_count,
            datetime.now(UTC),
            NOTABILITY_WINDOW_HOURS,
            rarity_weight,
        )
        notable = sorted(
            daily_count, key=lambda x: x.get("notability_score", 0), reverse=True
        )

        # last_detection is backed by a persisted rolling buffer of recent
        # EVENTS (per-event, newest-first, capped at LAST_DETECTION_EVENT_LIMIT),
        # NOT the live feed — so "the last detection" persists across restarts
        # and outages (#62). Build this poll's events (they still carry their
        # transient `wav` for the audio fetch below), merge the new ones into the
        # buffer, and persist when it changes.
        poll_events = _build_recent_events(
            daily_raw,
            self._baseline_ranks,
            self._baseline_species_count,
            self._images.url_for,
            LAST_DETECTION_EVENT_LIMIT,
        )
        if self._merge_event_buffer(poll_events):
            await self._events_store.async_save(self._event_buffer)

        # Fire automation events (new_species / unusual_visitor) for this
        # poll's qualifying species, then advance the recent-window baseline.
        self._fire_detection_events(detections, newly_seen, prior_last_seen)

        # Detection audio: download clips while their ~1h presigned URLs are
        # fresh, then prune. ALWAYS cache the headline records (last + notable)
        # — a couple of clips/poll, gentle on Haikubox's API — kept for
        # HEADLINE_AUDIO_DAYS. With audio_cache_days > 0, ALSO cache the full
        # recent feed for that many days (power users; heavier download). The
        # retention floor is the headline window. _with_links resolves the
        # stable /local audio_url; the signed source URL is never stored.
        if self._audio_enabled and self._latest_wav_by_species:
            full_days = self.config_entry.options.get(
                CONF_AUDIO_CACHE_DAYS, DEFAULT_AUDIO_CACHE_DAYS
            )
            if full_days > 0:
                for wav in self._latest_wav_by_species.values():
                    await self._audio.async_fetch(wav)
                for ev in poll_events:
                    if ev.get("wav"):
                        await self._audio.async_fetch(ev["wav"])
            else:
                headline = {
                    (poll_events[0].get("sp_code") if poll_events else None),
                    (notable[0].get("sp_code") if notable else None),
                }
                for code in headline:
                    wav = self._latest_wav_by_species.get(code)
                    if wav:
                        await self._audio.async_fetch(wav)
            await self._audio.async_prune(
                max(HEADLINE_AUDIO_DAYS, full_days), MAX_AUDIO_CLIPS
            )

        # Today's TRUE per-species counts. The /detections feed is only a
        # ≤5-per-species recency sample, so daily *volume* and diversity must
        # come from /daily-count (the same source as the rarity baseline).
        # Today is a partial, still-accumulating calendar day; fetched fresh
        # each poll. (See issue #44 re: daily_count's capped-feed undercount.)
        try:
            today_species = await self._fetch_daily_count(today.isoformat()) or {}
        except aiohttp.ClientError as err:
            _LOGGER.warning("Could not fetch today's daily count: %s", err)
            today_species = {}
        today_total = sum(today_species.values())

        # Activity-vs-typical and new-species-momentum figures (store-only).
        metrics = self._compute_window_metrics(today)
        typical_daily = metrics["typical_daily"]
        latest_day_total = metrics["latest_day_total"]
        latest_day = metrics["latest_day_date"]
        new_species_window = metrics["new_species_window"]
        days_since_new = metrics["days_since_new"]

        # last_detection's list + head come from the persisted event buffer (not
        # the live feed), so they never drain on an outage (#62). _buffer_view()
        # returns copies with fresh /local images + current rarity/links, leaving
        # the stored buffer untouched. notable stays live — its list + head drain
        # to [] / None with the 24h window.
        recent_events_out = _ranked(self._with_links(self._buffer_view()))
        notable_out = _ranked(self._with_links(notable))

        return {
            # key == sensor id; the public list attribute is always
            # `detections`. Singular keys are a single record (or None); plural
            # keys are ranked lists. last_detection's record + list come from the
            # persisted event buffer (per-event; survives restarts/outages);
            # notable_detection is the live current top (None when its 24h window
            # is empty → sensor "unknown"). Other lists are per-species.
            "recent_detections": _ranked(self._with_links(detections)),  # 1h, by recency (drains)
            "last_detection": recent_events_out[0] if recent_events_out else None,  # buffer head — persists
            "recent_events": recent_events_out,              # per-event buffer, newest-first
            "notable_detection": notable_out[0] if notable_out else None,  # live; None → "unknown"
            # Capped (≤5/species) trailing-24h list from /detections. NOT the
            # daily_count *sensor's* value (that's today_total) — hence the
            # distinct key, to avoid conflating the two. Kept for the
            # extended-silence emptiness check and rarest's "seen today"
            # membership, both of which only need presence, not true counts.
            "detections_24h": daily_count,
            "daily_top_species": _ranked(self._with_links(self._build_today_top(today_species))),  # true counts, today
            "notable_detections": notable_out,               # by notability; drains with 24h window
            # Sticky lifetime-history list (N most recently first-seen
            # species, newest first). Derived from _seen_species, not from
            # the current poll's new arrivals — populated on a fresh box
            # as soon as the bootstrap fills _seen_species, and stays
            # populated forever after.
            "new_detections": _ranked(self._with_links(self._build_new_species_history())),
            "new_detection": self._build_last_new_species(), # sticky
            "lifetime_species_count": len(self._seen_species),
            "yearly_top_species": self._with_links(self._build_baseline_top()),  # by trailing-window count (own rank)
            "rarest_species": _ranked(self._with_links(seven_day_rare)),       # by rarity
            "watched_species": _ranked(self._with_links(self._build_watched())),  # user watch-list, by recency
            "today_total": today_total,                       # true daily total (/daily-count)
            "today_species": today_species,                   # true per-species map (diversity)
            "typical_daily_count": typical_daily,             # mean active completed-day total
            "latest_day_total": latest_day_total,             # most recent completed day's total
            "latest_day_date": latest_day,                    # its date (ISO)
            "new_species_window": new_species_window,         # first-seen in last N days
            "days_since_new_species": days_since_new,         # since most recent lifetime-first
            # Backfill coverage (diagnostic): how far back the daily-count
            # history reaches, how many days are stored, and whether the
            # backward backfill has reached the box's install floor.
            "history_earliest": min(self._daily_counts) if self._daily_counts else None,
            "history_days_recorded": len(self._daily_counts),
            "history_complete": self._backfill_complete,
        }

    # ------------------------------------------------------------------
    # Automation events
    # ------------------------------------------------------------------

    def _fire_detection_events(
        self,
        detections: list[dict[str, Any]],
        newly_seen: set[str],
        prior_last_seen: dict[str, str],
    ) -> None:
        """Fire new_species / unusual_visitor bus events for this poll.

        `detections` is the recent (1h) per-species list with rarity and
        image metadata; `newly_seen` are species first recorded this poll
        (the live new-species detector, empty on a fresh-install bootstrap);
        `prior_last_seen` is the last-seen map as it was *before* this poll's
        update — used to measure each species' absence gap.
        """
        by_species = {d["species"]: d for d in detections if d.get("species")}
        current_recent = set(by_species)

        # new_species — genuinely new arrivals. Naturally silent on a fresh
        # install (the bootstrap pre-seeds _seen_species, so newly_seen is
        # empty); on established installs these are real first-ever records.
        for sp in newly_seen:
            self._fire_event(
                TRIGGER_NEW_SPECIES,
                by_species[sp],
                lifetime_species_count=len(self._seen_species),
            )

        # unusual_visitor — a known species reappearing after a long absence.
        # Skipped on the first poll of the session (no baseline yet) so a
        # restart doesn't replay every long-absent bird currently in the
        # window. The "newly present vs. previous window" gate then prevents
        # re-firing while a bird lingers across polls.
        if self._prev_recent_species is not None:
            threshold_days = self.config_entry.options.get(
                CONF_ABSENCE_DAYS, DEFAULT_ABSENCE_DAYS
            )
            now = datetime.now(UTC)
            for sp in current_recent - self._prev_recent_species:
                if sp in newly_seen:
                    continue  # brand-new → already fired as new_species
                prior = _parse_dt(prior_last_seen.get(sp))
                if prior is None:
                    continue
                days_absent = (now - prior).days
                if days_absent >= threshold_days:
                    self._fire_event(
                        TRIGGER_UNUSUAL_VISITOR,
                        by_species[sp],
                        days_absent=days_absent,
                    )

        # watched_species — a user-chosen species entered the recent window.
        # Edge-gated against the previous poll (fires on appearance, not every
        # poll while it lingers) and silent on the first poll, like the others.
        # A newly-seen species that's also watched fires both events — both true.
        watched = self._watched_species()
        if watched and self._prev_recent_species is not None:
            for sp in current_recent - self._prev_recent_species:
                if sp.casefold() in watched:
                    self._fire_event(TRIGGER_WATCHED_SPECIES, by_species[sp])

        self._prev_recent_species = current_recent

    def _watched_species(self) -> set[str]:
        """Case-folded set of common names to watch, from the options flow:
        the pick-list selections plus the free-text list (one name per line)."""
        opts = self.config_entry.options
        names = list(opts.get(CONF_WATCHED_SPECIES) or [])
        names += [ln.strip() for ln in (opts.get(CONF_WATCHED_EXTRA) or "").splitlines()]
        return {n.casefold() for n in names if n.strip()}

    @property
    def known_species(self) -> list[str]:
        """Species this box has been seen to detect (for the watch-list picker
        in the options flow), sorted alphabetically."""
        return sorted(self._seen_species)

    def _links_for(self, species: str, sp_code: str, scientific_name: str) -> dict[str, Any]:
        """Reference-link URLs for a record, surfaced by the integration so the
        cards just render them (no URL construction in the card). Haikubox has
        no upstream URLs, so all are templated: eBird and Macaulay Library from
        the species code, All About Birds from the common name (all share eBird's
        taxonomy), and Wikipedia from the scientific name (binomials resolve
        reliably via Wikipedia redirects)."""
        return {
            "ebird_url": _ebird_url(sp_code),
            "wikipedia_url": _wikipedia_url(scientific_name),
            "allaboutbirds_url": _allaboutbirds_url(species),
            "macaulay_url": _ml_url(sp_code),
        }

    def _with_links(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Stamp eBird / Wikipedia / All About Birds URLs and the cached
        `audio_url` onto each record. Audio resolves to a stable /local path if
        the clip is cached (per-event records carry their own transient `wav`;
        per-species records use that species' most-recent clip); the raw signed
        URL is stripped so it never reaches HA state."""
        for r in records:
            r.update(
                self._links_for(
                    r.get("species", ""), r.get("sp_code", ""), r.get("scientific_name", "")
                )
            )
            wav = r.pop("wav", None) or self._latest_wav_by_species.get(r.get("sp_code", ""))
            r["audio_url"] = (
                self._audio.url_for(wav)
                if (self._audio_enabled and self._audio)
                else None
            )
        return records

    def _fire_event(
        self, trigger_type: str, record: dict[str, Any], **extra: Any
    ) -> None:
        """Assemble and fire one haikubox_event for a species record.

        Beyond the core fields the payload carries the per-record `count`, the
        reference-link URLs (templated — so automations can deep-link), and a
        local `audio_url` for the species' cached call clip when audio is enabled
        and a clip is cached (else None). Callers may add per-trigger `extra`
        (e.g. `days_absent` for unusual_visitor, `lifetime_species_count` for
        new_species).
        """
        device = dr.async_get(self.hass).async_get_device(
            identifiers={(DOMAIN, self.serial)}
        )
        if device is None:
            return  # device not in the registry yet (only on first-ever setup)
        sp_code = record.get("sp_code", "")
        # Resolve the species' most-recent cached clip to a stable /local URL
        # (None when audio is off or the clip isn't cached). Pure in-memory lookup.
        wav = self._latest_wav_by_species.get(sp_code) if self._audio_enabled else None
        self.hass.bus.async_fire(
            EVENT_HAIKUBOX,
            {
                "device_id": device.id,
                "serial": self.serial,
                "device_name": self.device_name,
                "type": trigger_type,
                "species": record.get("species"),
                "scientific_name": record.get("scientific_name"),
                "sp_code": sp_code,
                "image_url": record.get("image_url"),
                "audio_url": self._audio.url_for(wav) if (wav and self._audio) else None,
                "last_seen": record.get("last_seen"),
                "count": record.get("count"),
                "rarity_score": record.get("rarity_score"),
                "yearly_rank": record.get("yearly_rank"),
                **self._links_for(
                    record.get("species", ""), sp_code, record.get("scientific_name", "")
                ),
                **extra,
            },
        )

    # ------------------------------------------------------------------
    # Store helpers
    # ------------------------------------------------------------------

    async def _async_setup(self) -> None:
        """Load persisted stores and warm caches once, before the first poll.

        This is DataUpdateCoordinator's setup hook (HA 2024.8+): it runs a
        single time during async_config_entry_first_refresh, so no "loaded yet?"
        guard or flag is needed in _async_update_data. A failure here surfaces
        as ConfigEntryNotReady and is retried by HA.
        """
        seen      = await self._store.async_load()
        sp_codes  = await self._sp_codes_store.async_load()
        sci_names = await self._sci_names_store.async_load()
        last_seen = await self._last_seen_store.async_load()
        daily     = await self._daily_store.async_load()
        events    = await self._events_store.async_load()

        self._seen_species   = seen      if isinstance(seen, dict)      else {}
        self._sp_codes       = sp_codes  if isinstance(sp_codes, dict)  else {}
        self._sci_names      = sci_names if isinstance(sci_names, dict) else {}
        self._last_seen      = last_seen if isinstance(last_seen, dict) else {}
        if isinstance(daily, dict):
            # Sanitize on load: a corrupt/hand-edited store should rebuild via
            # backfill, not crash _rebuild_baseline on every poll.
            self._daily_counts = _sanitize_daily_counts(daily.get("days"))
            self._backfill_complete = bool(daily.get("backfill_complete"))
            cursor = daily.get("cursor")
            self._backfill_cursor = cursor if isinstance(cursor, str) else None
            misses = daily.get("misses")
            self._backfill_misses = misses if isinstance(misses, int) and misses >= 0 else 0
        else:
            self._daily_counts = {}
            self._backfill_complete = False
            self._backfill_cursor = None
            self._backfill_misses = 0

        # Rehydrate the rolling event buffer so last_detection shows its last
        # value immediately after a restart (and survives an outage) instead of
        # "unknown" until the next live detection. Keep only well-formed records,
        # newest-first, capped — a corrupt/hand-edited store can't crash us.
        if isinstance(events, list):
            self._event_buffer = [e for e in events if isinstance(e, dict) and e.get("last_seen")]
            self._event_buffer.sort(key=lambda e: e.get("last_seen") or "", reverse=True)
            del self._event_buffer[LAST_DETECTION_EVENT_LIMIT:]

        # Rebuild the rarity baseline from the persisted daily counts so
        # rarity is available immediately on restart, before the first poll's
        # daily-count fetch. No-op-safe when the store is empty. Anchor to the
        # box's tz (resolved + cached here so the first poll reuses it — no
        # extra request); the window is 365 days, so the boundary day is moot.
        self._rebuild_baseline(dt_util.now(await self._async_box_tz()).date())

        # One-time cleanup of the legacy stores that earlier versions wrote.
        # The trailing-window baseline supersedes yearly/seven_day, and the
        # rolling event buffer + live notable replace the sticky store (#62);
        # all are orphaned now. async_remove no-ops if a file is already gone.
        # Runs once per session (this whole method is the one-time setup hook).
        for legacy in _LEGACY_STORE_SUFFIXES:
            await Store(
                self.hass, _STORE_VERSION, f"{DOMAIN}.{self.serial}.{legacy}"
            ).async_remove()

        await self._images.async_init()
        if self._audio_enabled:
            await self._audio.async_init()

        # Preload the bundled eBird-code fallback map off the event loop, so
        # the synchronous _sp_code_for() lookups during a poll never touch disk.
        await _async_load_ebird_species(self.hass)

    async def _ensure_daily_counts(self, today: date) -> bool:
        """Keep _daily_counts current and gap-free, then extend history.

        Returns whether `_daily_counts` changed this poll (so callers can skip
        work — e.g. the first-seen reconciliation — when nothing new arrived).

        Two phases per poll share one throttled budget:

          1. **Fill gaps** in `[oldest known … yesterday]`, newest-first. This
             covers newly-completed days *and* repairs holes left by HA /
             internet downtime. A 404 or empty result *in range* is stored as
             `{}` ("checked, no data") so it isn't re-fetched and contributes 0.
          2. **Extend older** than the oldest known day (deep backfill) via a
             persisted cursor, stopping at the pre-install floor. Only 404s
             *here* count toward the floor (`_backfill_misses`, persisted across
             polls); an empty day resets the count and a real-data day records.

        Because the cursor advances regardless of result, a 404-gap larger than
        one poll's budget never stalls the walk; because gaps inside the known
        range are handled in phase 1, they can't be mistaken for the floor.

        Budget is two-tier (fast while the rarity window isn't covered, then
        gentle for the deep tail). A `try/finally` persists partial progress so
        a mid-chunk failure or restart never wastes work; the backfill resumes
        from the stored watermark.
        """
        yesterday = today - timedelta(days=1)
        rarity_days = self.config_entry.options.get(
            CONF_RARITY_WINDOW_DAYS, RARITY_WINDOW_DAYS
        )
        window_floor = (today - timedelta(days=rarity_days)).isoformat()
        window_covered = self._backfill_complete or (
            bool(self._daily_counts) and min(self._daily_counts) <= window_floor
        )
        budget = HISTORY_BACKFILL_CHUNK if window_covered else RARITY_BACKFILL_CHUNK
        changed = False
        try:
            # Phase 1 — fill gaps in [oldest known .. yesterday], newest-first.
            range_start = (
                date.fromisoformat(min(self._daily_counts))
                if self._daily_counts
                else yesterday
            )
            d = yesterday
            while budget > 0 and d >= range_start:
                ds = d.isoformat()
                if ds not in self._daily_counts:
                    res = await self._fetch_daily_count(ds)
                    budget -= 1
                    self._daily_counts[ds] = res if res is not None else {}
                    changed = True
                    await asyncio.sleep(BACKFILL_REQUEST_DELAY)
                d -= timedelta(days=1)

            # Phase 2 — extend older than the oldest known day, via the cursor.
            if not self._backfill_complete and budget > 0:
                if self._backfill_cursor is not None:
                    cur = date.fromisoformat(self._backfill_cursor) - timedelta(days=1)
                elif self._daily_counts:
                    cur = date.fromisoformat(min(self._daily_counts)) - timedelta(days=1)
                else:
                    cur = yesterday  # nothing known yet (phase 1 found no data)
                while budget > 0 and self._backfill_misses < BACKFILL_STOP_AFTER_404:
                    res = await self._fetch_daily_count(cur.isoformat())
                    budget -= 1
                    if res is None:                       # 404 → pre-install (or a 404 gap)
                        self._backfill_misses += 1
                    else:                                  # {} or data → the day exists
                        self._daily_counts[cur.isoformat()] = res
                        self._backfill_misses = 0
                    self._backfill_cursor = cur.isoformat()
                    changed = True
                    await asyncio.sleep(BACKFILL_REQUEST_DELAY)
                    cur -= timedelta(days=1)
                if self._backfill_misses >= BACKFILL_STOP_AFTER_404:
                    self._backfill_complete = True
        except aiohttp.ClientResponseError as err:
            # Unexpected HTTP status (e.g. 429 rate limit, 5xx). Pause the
            # backfill for this poll and keep whatever we fetched; the next
            # poll (~10 min later) resumes — a natural backoff. The floor count
            # is untouched, so a transient limit can't end the backfill early.
            _LOGGER.warning(
                "daily-count returned HTTP %s (%s) — pausing backfill until next poll",
                err.status, err.message,
            )
        finally:
            if changed:
                await self._daily_store.async_save(
                    {
                        "days": self._daily_counts,
                        "backfill_complete": self._backfill_complete,
                        "cursor": self._backfill_cursor,
                        "misses": self._backfill_misses,
                    }
                )
        return changed

    def _reconcile_first_seen(self) -> bool:
        """Reconcile the lifetime first-seen log against the TRUE per-day history.

        On its own `_seen_species` only records when the *integration* first
        observed a species, so a recent (re)install makes everything look new
        (e.g. new-in-30-days == lifetime). `_daily_counts` holds the box's real
        backfilled history, so a species' first_seen should be the earliest day
        it actually appears there. Walking oldest-first, set or lower each
        species' first_seen accordingly. Also stops the live new_species event
        from firing for species already present in that history. Returns whether
        anything changed (so the caller can persist `_seen_species`).
        """
        changed = False
        for day in sorted(self._daily_counts):
            for sp in self._daily_counts[day]:
                prev = self._seen_species.get(sp)
                if prev is None or day < prev[:10]:
                    self._seen_species[sp] = day
                    changed = True
        return changed

    def _rebuild_baseline(self, today: date) -> None:
        """Aggregate the trailing RARITY_WINDOW_DAYS of daily counts into the
        rarity baseline (species → rank). Replaces the calendar-year fetch;
        cheap enough to run every poll."""
        rarity_days = self.config_entry.options.get(
            CONF_RARITY_WINDOW_DAYS, RARITY_WINDOW_DAYS
        )
        cutoff = (today - timedelta(days=rarity_days)).isoformat()
        totals: dict[str, int] = {}
        for date_str, counts in self._daily_counts.items():
            if date_str >= cutoff:  # ISO dates compare lexicographically
                for sp, c in counts.items():
                    totals[sp] = totals.get(sp, 0) + int(c)
        self._baseline_ranks, self._baseline_species_count, self._baseline_items = (
            _ranks_from_counts(totals)
        )

    def _merge_event_buffer(self, poll_events: list[dict[str, Any]]) -> bool:
        """Merge this poll's events into the rolling last-N buffer that backs
        last_detection. De-duped by (sp_code, last_seen), newest-first, capped at
        LAST_DETECTION_EVENT_LIMIT. The transient `wav` is stripped before
        storing (it's a ~1h presigned URL — useless once persisted; audio is
        re-resolved live). Returns whether the buffer changed (→ persist)."""
        existing = {(e.get("sp_code"), e.get("last_seen")) for e in self._event_buffer}
        added = False
        for ev in poll_events:
            key = (ev.get("sp_code"), ev.get("last_seen"))
            if ev.get("last_seen") and key not in existing:
                self._event_buffer.append({k: v for k, v in ev.items() if k != "wav"})
                existing.add(key)
                added = True
        if added:
            self._event_buffer.sort(key=lambda e: e.get("last_seen") or "", reverse=True)
            del self._event_buffer[LAST_DETECTION_EVENT_LIMIT:]
        return added

    def _buffer_view(self) -> list[dict[str, Any]]:
        """Display copies of the event buffer for last_detection: fresh /local
        image_url (a species' photo may have been cached after the event was
        buffered) and current rarity scores, without mutating the stored buffer.
        _with_links (applied by the caller) then stamps reference links + a live
        audio_url (None for aged events whose clip is gone)."""
        view = [dict(e) for e in self._event_buffer]
        for e in view:
            img = self._images.url_for(e.get("sp_code"))
            if img:
                e["image_url"] = img
        _apply_rarity_scores(view, self._baseline_ranks, self._baseline_species_count)
        return view

    def _compute_window_metrics(self, today: date) -> dict[str, Any]:
        """Activity-vs-typical and new-species-momentum figures, derived purely
        from the stored per-day counts and the first-seen log (no API calls).

        Activity compares the most recent *completed* day (not today's partial)
        to the mean of completed days over the trailing ACTIVITY_BASELINE_DAYS,
        excluding zero/offline days — a stable full-day-vs-full-day ratio.
        Momentum counts species first heard in the last NEW_SPECIES_WINDOW_DAYS
        and the gap since the most recent lifetime-first. first_seen values are
        ISO strings (date or datetime); compared on the YYYY-MM-DD prefix
        (lexicographic == chronological for ISO).
        """
        today_str = today.isoformat()
        baseline_cutoff = (today - timedelta(days=ACTIVITY_BASELINE_DAYS)).isoformat()
        completed = {
            d: sum(c.values()) for d, c in self._daily_counts.items() if d < today_str
        }
        window_totals = [t for d, t in completed.items() if d >= baseline_cutoff and t > 0]
        typical_daily = (
            round(sum(window_totals) / len(window_totals), 1) if window_totals else None
        )
        latest_day = max(completed) if completed else None
        latest_day_total = completed[latest_day] if latest_day else None

        new_days = self.config_entry.options.get(
            CONF_NEW_SPECIES_WINDOW_DAYS, NEW_SPECIES_WINDOW_DAYS
        )
        new_cutoff = (today - timedelta(days=new_days)).isoformat()
        first_seen_dates = [fs[:10] for fs in self._seen_species.values() if fs]
        new_species_window = sum(1 for fs in first_seen_dates if fs >= new_cutoff)
        days_since_new: int | None = None
        if first_seen_dates:
            try:
                days_since_new = (today - date.fromisoformat(max(first_seen_dates))).days
            except ValueError:
                days_since_new = None

        return {
            "typical_daily": typical_daily,
            "latest_day_total": latest_day_total,
            "latest_day_date": latest_day,
            "new_species_window": new_species_window,
            "days_since_new": days_since_new,
        }

    def _build_rarest(
        self, daily_count: list[dict[str, Any]], today: date
    ) -> list[dict[str, Any]]:
        """Species heard in the last 7 days, scored by the trailing-window
        rarity baseline, rarest first. The 7-day set is the persisted completed
        days plus today's live 24h list (so today counts before it lands in the
        store as a completed day)."""
        cutoff = (today - timedelta(days=6)).isoformat()  # 7 days incl. today
        counts7: dict[str, int] = {}
        for date_str, counts in self._daily_counts.items():
            if date_str >= cutoff:
                for sp, c in counts.items():
                    counts7[sp] = counts7.get(sp, 0) + int(c)
        for d in daily_count:
            sp = d.get("species")
            if sp:
                counts7[sp] = counts7.get(sp, 0) + int(d.get("count", 0))

        denom = max(self._baseline_species_count, 1)
        out: list[dict[str, Any]] = []
        for sp, c in counts7.items():
            sp_code = self._sp_code_for(sp)
            rank = self._baseline_ranks.get(sp, self._baseline_species_count)
            out.append({
                "species": sp,
                "scientific_name": self._sci_name_for(sp),
                "sp_code": sp_code,
                "image_url": self._images.url_for(sp_code),
                "last_seen": self._last_seen.get(sp),
                "count": c,
                "rarity_score": round(rank / denom, 4),
                "yearly_rank": rank,
            })
        out.sort(key=lambda x: x["rarity_score"], reverse=True)
        return out

    # ------------------------------------------------------------------
    # Dataset builders (store-only, no API calls)
    # ------------------------------------------------------------------

    def _sp_code_for(self, species: str) -> str:
        """Resolve a species' sp_code: prefer what we learned from /detections,
        else fall back to the bundled eBird map. The fallback lets species seen
        only via /daily-count (e.g. rare birds the /detections sample misses)
        still get an image. Empty string when truly unknown."""
        return self._sp_codes.get(species) or (_EBIRD_SPECIES or {}).get(species, {}).get("code", "")

    def _sci_name_for(self, species: str) -> str:
        """Resolve a species' scientific name: prefer what we learned from
        /detections, else fall back to the bundled eBird map (so daily-count-only
        species still show a scientific name). Empty string when unknown."""
        return self._sci_names.get(species) or (_EBIRD_SPECIES or {}).get(species, {}).get("sci", "")

    def _build_baseline_top(self) -> list[dict[str, Any]]:
        """Trailing-window baseline species list enriched with sp_code,
        scientific_name, last_seen, and image. (Surfaced as the
        `yearly_top_species` sensor — the name kept for compatibility.)"""
        result = []
        for item in self._baseline_items:
            sp = item["species"]
            sp_code = self._sp_code_for(sp)
            result.append({
                **item,
                "sp_code": sp_code,
                "scientific_name": self._sci_name_for(sp),
                "last_seen": self._last_seen.get(sp),
                "image_url": self._images.url_for(sp_code),
            })
        return result

    def _build_today_top(self, today_species: dict[str, int]) -> list[dict[str, Any]]:
        """Today's species ranked by TRUE detection count (from /daily-count),
        enriched with sp_code, scientific_name, last_seen, image, and the
        trailing-window rarity score.

        Replaces the old /detections-derived list, whose per-species counts were
        clamped at the ≤5-per-species sample cap — so its "top species" ranking
        was meaningless ties at 5 (issue #44). This uses the true calendar-day
        counts instead.
        """
        denom = max(self._baseline_species_count, 1)
        result: list[dict[str, Any]] = []
        for sp, count in today_species.items():
            sp_code = self._sp_code_for(sp)
            rank = self._baseline_ranks.get(sp, self._baseline_species_count)
            result.append({
                "species": sp,
                "scientific_name": self._sci_name_for(sp),
                "sp_code": sp_code,
                "image_url": self._images.url_for(sp_code),
                "last_seen": self._last_seen.get(sp),
                "count": count,
                "rarity_score": round(rank / denom, 4),
                "yearly_rank": rank,
            })
        result.sort(key=lambda x: x["count"], reverse=True)
        return result

    def _build_new_species_history(self) -> list[dict[str, Any]]:
        """The N most recently first-seen species, sorted by first_seen desc.

        Derived from the persisted seen_species log, so the list is sticky
        across polls and HA restarts. Powers the new_species sensor's
        `detections` attribute — a "new arrivals" feed rather than a
        this-poll-only delta. The single sticky `new_detection` record is
        just the head of this list.
        """
        if not self._seen_species:
            return []
        sorted_items = sorted(
            self._seen_species.items(),
            key=lambda kv: kv[1] or "",
            reverse=True,
        )[:NEW_SPECIES_HISTORY_LIMIT]
        denom = max(self._baseline_species_count, 1)
        result: list[dict[str, Any]] = []
        for species, first_seen in sorted_items:
            sp_code = self._sp_code_for(species)
            rank = self._baseline_ranks.get(species, self._baseline_species_count)  # cap at 1.0; see _apply_rarity_scores
            result.append({
                "species": species,
                "scientific_name": self._sci_name_for(species),
                "sp_code": sp_code,
                "image_url": self._images.url_for(sp_code),
                "last_seen": self._last_seen.get(species),
                "first_seen": first_seen,
                "rarity_score": round(rank / denom, 4),
                "yearly_rank": rank,
            })
        return result

    def _build_last_new_species(self) -> dict[str, Any] | None:
        """The species with the most recent first-detection — head of the
        new-species history list."""
        history = self._build_new_species_history()
        return history[0] if history else None

    def _build_watched(self) -> list[dict[str, Any]]:
        """Watch-list species this box has detected, most-recently-heard first —
        powers the "Birds of interest" list card. Watched species the box has
        never recorded aren't listed (nothing to render); they're still covered
        by the watched_species device trigger when they arrive."""
        watched = self._watched_species()
        if not watched:
            return []
        denom = max(self._baseline_species_count, 1)
        result: list[dict[str, Any]] = []
        for species in self._seen_species:
            if species.casefold() not in watched:
                continue
            sp_code = self._sp_code_for(species)
            rank = self._baseline_ranks.get(species, self._baseline_species_count)
            result.append({
                "species": species,
                "scientific_name": self._sci_name_for(species),
                "sp_code": sp_code,
                "image_url": self._images.url_for(sp_code),
                "last_seen": self._last_seen.get(species),
                "first_seen": self._seen_species.get(species),
                "rarity_score": round(rank / denom, 4),
                "yearly_rank": rank,
            })
        result.sort(key=lambda x: x.get("last_seen") or "", reverse=True)
        return result

    # ------------------------------------------------------------------
    # Public properties (used by diagnostics)
    # ------------------------------------------------------------------

    @property
    def baseline_species_count(self) -> int:
        return self._baseline_species_count

    @property
    def box_timezone(self) -> tzinfo | None:
        """The box's resolved timezone, or None until the first poll resolves
        it (callers fall back to HA's tz via dt_util)."""
        return self._box_tz

    @property
    def lifetime_species_count(self) -> int:
        return len(self._seen_species)

    async def _import_history_statistics(self) -> None:
        """Backfill HA long-term statistics from the per-day counts store (no
        API call): detection totals (cumulative `sum` → the Statistics card
        shows detections per day/week/month) and species richness (daily
        `mean`), over the box's full recorded history. Each day is anchored at
        the box's local midnight (its /daily-count days are box-local). Re-runs
        daily and is idempotent on (statistic_id, day), so it also picks up days
        as the deep backfill keeps extending the store."""
        # Lazy imports: only pull in recorder internals when actually backfilling.
        from homeassistant.components.recorder.models import (  # noqa: PLC0415
            StatisticData,
            StatisticMeanType,
            StatisticMetaData,
        )
        from homeassistant.components.recorder.statistics import (  # noqa: PLC0415
            async_add_external_statistics,
        )

        box_tz = await self._async_box_tz()  # cached; None → fall back to HA tz
        # statistic_id must be lowercase (like an entity_id); some serials are
        # uppercase hex (e.g. 348518979FA0) → valid_statistic_id rejects them.
        serial = self.serial.lower()
        det_stats: list[StatisticData] = []
        sp_stats: list[StatisticData] = []
        cumulative = 0.0
        for day_str in sorted(self._daily_counts):
            try:
                day = date.fromisoformat(day_str)
            except (TypeError, ValueError):
                continue
            counts = self._daily_counts[day_str] or {}
            total = sum(counts.values())
            species = float(len(counts))
            start = (
                datetime(day.year, day.month, day.day, tzinfo=box_tz)
                if box_tz
                else dt_util.start_of_local_day(day)
            )
            cumulative += total
            det_stats.append(
                StatisticData(start=start, state=float(total), sum=cumulative)
            )
            sp_stats.append(
                StatisticData(start=start, mean=species, min=species, max=species)
            )
        if not det_stats:
            return

        async_add_external_statistics(
            self.hass,
            StatisticMetaData(
                has_sum=True,
                has_mean=False,
                mean_type=StatisticMeanType.NONE,
                name=f"{self.device_name} daily detections",
                source=DOMAIN,
                statistic_id=f"{DOMAIN}:box_{serial}_daily_detections",
                unit_of_measurement="detections",
                unit_class=None,
            ),
            det_stats,
        )
        async_add_external_statistics(
            self.hass,
            StatisticMetaData(
                has_sum=False,
                mean_type=StatisticMeanType.ARITHMETIC,
                name=f"{self.device_name} daily species",
                source=DOMAIN,
                statistic_id=f"{DOMAIN}:box_{serial}_daily_species",
                unit_of_measurement="species",
                unit_class=None,
            ),
            sp_stats,
        )

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _async_box_tz(self) -> tzinfo | None:
        """The box's own timezone, from the box-info endpoint (cached).

        Resolved once and reused. Returns ``None`` until the lookup succeeds, in
        which case callers fall back to Home Assistant's configured tz via
        ``dt_util.now(None)``. Day-boundary math needs the *box's* local day
        because /daily-count is keyed to it, and the box can live in a different
        timezone than the HA host.
        """
        if self._box_tz is not None:
            return self._box_tz
        try:
            async with self._session.get(f"{API_BASE}/haikubox/{self.serial}") as resp:
                resp.raise_for_status()
                info = await resp.json()
            name = (info or {}).get("tz")
            if name:
                self._box_tz = await dt_util.async_get_time_zone(name)
        except (aiohttp.ClientError, ValueError) as err:
            _LOGGER.debug("Could not resolve box timezone (falling back to HA tz): %s", err)
        return self._box_tz

    async def _fetch_detections(self, hours: int) -> Any:
        url = f"{API_BASE}/haikubox/{self.serial}/detections"
        async with self._session.get(url, params={"hours": hours}) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _fetch_daily_count(self, date_str: str) -> dict[str, int] | None:
        """One calendar day's per-species counts as {species: count}.

        Returns **None only for a 404** — a date before the box existed, the
        backfill floor signal. A 200 with an empty or unparseable body returns
        `{}` ("the day exists, just no data"), which the backfill treats as a
        recorded no-data day rather than a floor hit. This distinction is what
        lets an in-history outage gap (offline days) be told apart from the
        pre-install void.
        """
        url = f"{API_BASE}/haikubox/{self.serial}/daily-count"
        async with self._session.get(url, params={"date": date_str}) as resp:
            if resp.status == 404:
                return None
            resp.raise_for_status()
            try:
                data = await resp.json(content_type=None)
            except (aiohttp.ContentTypeError, ValueError):
                return {}
        if not isinstance(data, list):
            return {}
        out: dict[str, int] = {}
        for item in data:
            if isinstance(item, dict) and item.get("bird"):
                out[item["bird"]] = int(item.get("count") or 0)
        return out


# ------------------------------------------------------------------
# Response normalisation
# ------------------------------------------------------------------

def _parse_dt(value: Any) -> datetime | None:
    """Parse an ISO-8601 `dt` string to a UTC-aware datetime.

    Returns None for missing/unparseable input — callers skip such
    items. Naive datetimes are assumed to be UTC (the API documents
    UTC; this is a defensive fallback). Centralising parsing here
    means comparisons elsewhere can be true datetime-vs-datetime
    rather than the older string-vs-string lexicographic compare,
    which was fragile to subtle format differences (mixed `+00:00`
    vs `Z`, missing microseconds, etc. — issue #19 item G).
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _filter_by_dt(raw: Any, threshold: datetime) -> list[dict[str, Any]]:
    """Return raw detection items whose `dt` is at or after the threshold.

    Used to derive the recent-window subset from the single 24h /detections
    response. Filtering at the raw level (before _normalise_detections sums
    them) preserves the per-window `count` semantic — a species's `count` on
    a recent-window record is detections-in-the-last-hour, not
    detections-in-the-last-24-hours.
    """
    if not isinstance(raw, dict):
        return []
    items = raw.get("detections", [])
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dt = _parse_dt(item.get("dt"))
        if dt is None:
            continue
        if dt >= threshold:
            out.append(item)
    return out


def _latest_wav_by_species(raw: Any) -> dict[str, str]:
    """Map species code → the `wav` (presigned clip URL) of its most-recent
    detection in the raw payload. Per-species records resolve audio against
    this (their record is that species' latest detection)."""
    out: dict[str, tuple[str, str]] = {}  # spCode → (dt, wav)
    items = raw.get("detections", []) if isinstance(raw, dict) else []
    if not isinstance(items, list):
        return {}
    for item in items:
        if not isinstance(item, dict):
            continue
        code = item.get("spCode")
        wav = item.get("wav")
        if not code or not wav or code == "soundscape":
            continue
        dt = item.get("dt") or ""
        cur = out.get(code)
        if cur is None or dt > cur[0]:
            out[code] = (dt, wav)
    return {code: wav for code, (dt, wav) in out.items()}


def _normalise_detections(raw: Any) -> list[dict[str, Any]]:
    """Collapse the flat detections list into one record per species.

    `last_seen` comparisons go through _parse_dt and are evaluated on
    timezone-aware datetimes, not on the raw ISO strings — see #19/G.
    The string form is what gets stored on the record (downstream code
    reads strings), but the question of "which dt is later" is answered
    on parsed datetimes.
    """
    if not isinstance(raw, dict):
        _LOGGER.debug("Unexpected detections payload type: %s", type(raw))
        return []

    items = raw.get("detections", [])
    if not isinstance(items, list):
        return []

    by_species: dict[str, dict[str, Any]] = {}

    for item in items:
        if not isinstance(item, dict):
            continue
        sp_code = item.get("spCode", "")
        if sp_code == "soundscape" or item.get("cn", "").lower() == "soundscape":
            continue
        key = sp_code or item.get("cn", "Unknown")
        dt_str = item.get("dt")
        parsed = _parse_dt(dt_str)

        if key not in by_species:
            by_species[key] = {
                "species": item.get("cn", "Unknown"),
                "scientific_name": item.get("sn", ""),
                "sp_code": sp_code,
                "image_url": f"{IMAGES_BASE}/{sp_code}.jpeg" if sp_code else None,
                "last_seen": dt_str,
                "_last_seen_dt": parsed,
                "count": 0,
                "rarity_score": 0.0,
                "yearly_rank": 0,
            }
        by_species[key]["count"] += 1
        existing = by_species[key]["_last_seen_dt"]
        if parsed is not None and (existing is None or parsed > existing):
            by_species[key]["last_seen"] = dt_str
            by_species[key]["_last_seen_dt"] = parsed

    # Strip the internal parsed-dt field; the sort key uses it directly
    # before we drop it.
    results = sorted(
        by_species.values(),
        key=lambda x: x.get("_last_seen_dt") or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    for r in results:
        r.pop("_last_seen_dt", None)
    return results


def _first_seen_per_species(raw: Any) -> dict[str, str]:
    """Earliest `dt` (as the original ISO string) per species in the raw
    payload. Used by the fresh-install bootstrap so seeded species get
    their actual first-observation timestamp rather than the latest one
    (issue #19 item F). Soundscape and unparseable-dt items are skipped,
    matching _normalise_detections' filtering.
    """
    out: dict[str, str] = {}
    best_parsed: dict[str, datetime] = {}
    if not isinstance(raw, dict):
        return out
    items = raw.get("detections", [])
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        sp_code = item.get("spCode", "")
        if sp_code == "soundscape" or item.get("cn", "").lower() == "soundscape":
            continue
        sp = item.get("cn", "Unknown")
        dt_str = item.get("dt")
        parsed = _parse_dt(dt_str)
        if parsed is None:
            continue
        existing = best_parsed.get(sp)
        if existing is None or parsed < existing:
            best_parsed[sp] = parsed
            out[sp] = dt_str  # the original string form
    return out


def _sanitize_daily_counts(raw: Any) -> dict[str, dict[str, int]]:
    """Validate a persisted daily-counts blob, dropping anything malformed.

    Keeps only entries keyed by a valid ISO date whose value is a mapping of
    species name (str) → integer count. A corrupt or hand-edited store thus
    degrades to "rebuild via backfill" instead of crashing the rebuild/poll.
    """
    if not isinstance(raw, dict):
        return {}
    clean: dict[str, dict[str, int]] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        try:
            date.fromisoformat(key)
        except ValueError:
            continue
        if not isinstance(value, dict):
            continue
        inner: dict[str, int] = {}
        for sp, count in value.items():
            if not isinstance(sp, str):
                continue
            try:
                inner[sp] = int(count)
            except (ValueError, TypeError):
                continue
        clean[key] = inner
    return clean


def _ranks_from_counts(
    totals: dict[str, int],
) -> tuple[dict[str, int], int, list[dict[str, Any]]]:
    """Return (species→rank, species_count, items) from a {species: count}
    aggregate (the trailing-window sum). `species_count` is the number of
    distinct species — the denominator used by rarity scoring. items entries:
    {"species": str, "count": int, "rank": int}, sorted by count descending.
    """
    sorted_items = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    ranks: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    for idx, (name, count) in enumerate(sorted_items):
        if not name:
            continue
        rank = idx + 1
        ranks[name] = rank
        items.append({"species": name, "count": int(count), "rank": rank})
    return ranks, len(ranks), items


def _apply_rarity_scores(
    detections: list[dict[str, Any]],
    baseline_ranks: dict[str, int],
    baseline_species_count: int,
) -> None:
    """Mutate detection records in-place to add rarity_score and yearly_rank.

    Species absent from the baseline fall back to rank=baseline_species_count,
    capping rarity_score at 1.0 — tied with the actually-rarest known
    species rather than overshooting it (issue #17). Without the cap,
    unknown species would always rank above ranked-rarest, which is a
    data-availability artifact rather than a genuine rarity signal.

    The record field is `yearly_rank` (not `baseline_rank`): the name predates
    the trailing-window baseline and is kept for backward compatibility — it's
    in the event payload, the card record contract, and the docs.
    """
    denom = max(baseline_species_count, 1)
    for d in detections:
        rank = baseline_ranks.get(d["species"], baseline_species_count)
        d["yearly_rank"] = rank
        d["rarity_score"] = round(rank / denom, 4)


def _apply_notability_scores(
    detections: list[dict[str, Any]],
    now: datetime,
    window_hours: int,
    rarity_weight: float,
) -> None:
    """Mutate detection records in-place to add notability_score.

    notability_score = w * rarity_score + (1-w) * recency_score, both in
    [0, ~1]. recency_score is a linear decay over `window_hours` — newest
    event scores 1.0, an event at the window edge scores 0.0. A record
    with no parseable last_seen contributes 0 to recency (only its rarity
    counts).

    Requires _apply_rarity_scores to have run first so rarity_score is
    present on every record.
    """
    window_seconds = max(window_hours * 3600, 1)
    recency_weight = 1.0 - rarity_weight
    for d in detections:
        rarity = d.get("rarity_score", 0.0) or 0.0
        recency = 0.0
        last_seen = d.get("last_seen")
        if isinstance(last_seen, str) and last_seen:
            try:
                dt = datetime.fromisoformat(last_seen)
            except ValueError:
                dt = None
            if dt is not None:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                age_seconds = max(0.0, (now - dt).total_seconds())
                recency = max(0.0, 1.0 - age_seconds / window_seconds)
        d["notability_score"] = round(
            rarity_weight * rarity + recency_weight * recency, 4
        )


def _ebird_url(sp_code: str | None) -> str | None:
    return f"https://ebird.org/species/{sp_code}" if sp_code else None


def _ml_url(sp_code: str | None) -> str | None:
    # Macaulay Library catalog keys on the eBird species code (taxonCode).
    return (
        f"https://search.macaulaylibrary.org/catalog?taxonCode={sp_code}"
        if sp_code
        else None
    )


def _allaboutbirds_url(species: str | None) -> str | None:
    # allaboutbirds.org guide URLs key on the common name (spaces → underscores).
    return f"https://www.allaboutbirds.org/guide/{species.replace(' ', '_')}" if species else None


def _wikipedia_url(scientific_name: str | None) -> str | None:
    # Template from the binomial: Wikipedia near-universally redirects a
    # scientific name to the species article (verified ~100% vs the common
    # name's ~91%, which drifts on vernacular-name differences and
    # disambiguation pages).
    if not scientific_name:
        return None
    return f"https://en.wikipedia.org/wiki/{scientific_name.replace(' ', '_')}"


def _ranked(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return copies stamped with a 1-based `rank` reflecting list order.

    Callers sort by their own criterion first, so a species' `rank` means
    "position by this sensor's measure" (recency, rarity, count, …). Copies
    are returned so the same underlying detection dict can be ranked
    differently across the recent / notable / new-species lists.
    """
    return [{**record, "rank": index + 1} for index, record in enumerate(records)]


def _build_recent_events(
    raw: Any,
    baseline_ranks: dict[str, int],
    baseline_species_count: int,
    image_url_for,
    limit: int,
) -> list[dict[str, Any]]:
    """Return the N most recent individual detection events from the raw
    24h payload, sorted by `dt` descending.

    Unlike the per-species lists, this preserves event-level detail: the
    same species detected multiple times yields multiple records, each
    with its own `dt`. Rarity is looked up by species so all events for
    the same species carry the same `rarity_score` / `yearly_rank`.

    `image_url_for` is `ImageCache.url_for` — returns the cached local
    URL when available, falling back to the API URL otherwise (matching
    how the per-species records' image_url is derived).
    """
    if not isinstance(raw, dict):
        return []
    items = raw.get("detections", [])
    if not isinstance(items, list):
        return []

    denom = max(baseline_species_count, 1)
    events: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        sp_code = item.get("spCode", "")
        if sp_code == "soundscape" or item.get("cn", "").lower() == "soundscape":
            continue
        dt_str = item.get("dt")
        if not isinstance(dt_str, str) or not dt_str:
            continue
        species = item.get("cn", "Unknown")
        rank = baseline_ranks.get(species, baseline_species_count)  # cap at 1.0; see _apply_rarity_scores
        # Use `last_seen` for the timestamp field (rather than `dt`) so this
        # list honours the cross-sensor record-shape contract — every other
        # `detections` list exposes `last_seen`, and the bird-list card reads
        # that field. On per-event records the value is just this event's
        # own timestamp (there's no "last of N" — there's only this one).
        events.append({
            "species": species,
            "scientific_name": item.get("sn", ""),
            "sp_code": sp_code,
            "image_url": image_url_for(sp_code),
            "last_seen": dt_str,
            "wav": item.get("wav"),  # transient; resolved to audio_url in _with_links
            "rarity_score": round(rank / denom, 4),
            "yearly_rank": rank,
        })

    events.sort(key=lambda e: e.get("last_seen") or "", reverse=True)
    return events[:limit]
