from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ACTIVITY_BASELINE_DAYS,
    API_BASE,
    BACKFILL_REQUEST_DELAY,
    BACKFILL_STOP_AFTER_404,
    CONF_ABSENCE_DAYS,
    CONF_DEVICE_NAME,
    CONF_NOTABLE_RARITY_WEIGHT,
    CONF_SERIAL,
    DAILY_WINDOW_HOURS,
    DEFAULT_ABSENCE_DAYS,
    DEFAULT_NOTABLE_RARITY_WEIGHT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_HAIKUBOX,
    HISTORY_BACKFILL_CHUNK,
    IMAGES_BASE,
    LAST_DETECTION_EVENT_LIMIT,
    NEW_SPECIES_HISTORY_LIMIT,
    NEW_SPECIES_WINDOW_DAYS,
    NOTABILITY_WINDOW_HOURS,
    RARITY_BACKFILL_CHUNK,
    RARITY_WINDOW_DAYS,
    RECENT_WINDOW_HOURS,
    TRIGGER_NEW_SPECIES,
    TRIGGER_UNUSUAL_VISITOR,
)
from .image_cache import ImageCache

_LOGGER = logging.getLogger(__name__)

_STORE_VERSION = 1

# Config entry whose runtime_data is the coordinator (lazily evaluated,
# so the forward reference to the class below is fine).
type HaikuboxConfigEntry = ConfigEntry[HaikuboxCoordinator]


# Bundled common-name → eBird species_code fallback map. Haikubox's sp_code is
# the eBird species code, and the image S3 is keyed by it — but we only *learn*
# a species' code from the /detections sample, which omits rarely-heard species.
# This derived map (from the eBird/Clements taxonomy) lets daily-count-only
# species still resolve an image. See data/ebird_species_codes.json + NOTICE.
#
# Loaded once, off the event loop (it's ~350 KB of JSON), via
# _async_load_ebird_codes; _sp_code_for reads the module-level cache.
_EBIRD_CODES: dict[str, str] | None = None


def _read_ebird_codes() -> dict[str, str]:
    """Blocking read+parse of the bundled map. Call only via the executor."""
    path = Path(__file__).parent / "data" / "ebird_species_codes.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("names", {})
    except (OSError, ValueError):
        _LOGGER.warning("Could not load bundled eBird species-code map")
        return {}


async def _async_load_ebird_codes(hass: HomeAssistant) -> None:
    """Populate the module-level eBird-code cache once, off the event loop."""
    global _EBIRD_CODES
    if _EBIRD_CODES is None:
        _EBIRD_CODES = await hass.async_add_executor_job(_read_ebird_codes)


class HaikuboxCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the Haikubox API and normalises the response for sensors."""

    def __init__(self, hass: HomeAssistant, entry: HaikuboxConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.serial = serial = entry.data[CONF_SERIAL]
        self.device_name = entry.data.get(CONF_DEVICE_NAME, "Haikubox")
        self._session = async_get_clientsession(hass)

        # Yearly counts — refreshed once per calendar day
        self._yearly_ranks: dict[str, int] = {}   # species → rank (1 = most common)
        self._yearly_species_count: int = 0
        self._yearly_fetched_date: date | None = None

        # Sticky records — set on first detection, never cleared; persisted
        # so last_detection / notable_species survive an HA restart instead
        # of resetting to "unknown" until the next live detection.
        self._last_detected: dict[str, Any] | None = None
        self._last_notable: dict[str, Any] | None = None

        # Persistent stores
        self._store            = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.seen_species")
        self._sp_codes_store   = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.sp_codes")
        self._sci_names_store  = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.sci_names")
        self._last_seen_store  = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.last_seen")
        self._daily_store      = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.daily_counts")
        self._sticky_store     = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.sticky")

        # In-memory store state
        self._seen_species: dict[str, str] = {}          # species → first_seen ISO
        self._sp_codes: dict[str, str] = {}              # species → sp_code
        self._sci_names: dict[str, str] = {}             # species → scientific_name
        self._last_seen: dict[str, str] = {}             # species → last_seen ISO
        self._yearly_items: list[dict[str, Any]] = []    # trailing-window baseline [{species, count, rank}]
        self._daily_counts: dict[str, dict[str, int]] = {}  # date_str → {species: count}, full lifetime
        self._backfill_complete: bool = False            # reached the pre-install 404 floor
        self._backfill_cursor: str | None = None         # oldest date the deep backfill has probed
        self._backfill_misses: int = 0                   # consecutive 404s at the leading (oldest) edge
        self._stores_loaded: bool = False

        # Automation-event edge detection. Species present in the recent
        # window on the previous poll — used to fire unusual_visitor only on
        # a species's (re)appearance, not every poll while it lingers. None
        # until the first poll of the session establishes the baseline; that
        # first poll fires no unusual_visitor events (avoids a restart flood).
        self._prev_recent_species: set[str] | None = None

        # Species photo cache (downloads once, serves from /local/)
        self._images = ImageCache(hass, self._session)

    # ------------------------------------------------------------------
    # DataUpdateCoordinator interface
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        if not self._stores_loaded:
            await self._load_stores()

        # UTC-anchored so that day-boundary semantics (7-day store keys,
        # once-per-day yearly refresh) align with the API's UTC dt stamps
        # and behave the same on every host regardless of local timezone
        # (issue #16).
        today = datetime.now(timezone.utc).date()

        # Keep the per-day counts store fresh (fetch newly-completed days +
        # a throttled chunk of historical backfill), then rebuild the rarity
        # baseline by aggregating the trailing RARITY_WINDOW_DAYS. This slides
        # continuously, so it never resets on Jan 1 the way /yearly-count did.
        try:
            await self._ensure_daily_counts(today)
        except aiohttp.ClientError as err:
            _LOGGER.warning("Could not fetch daily counts: %s", err)
        self._rebuild_baseline(today)

        # If we still have no baseline, every rarity_score would collapse to
        # 1.0 and notable_species / rarest_species would lose their meaning.
        # Fail loudly instead of computing silently-wrong rankings. Only a true
        # fresh install whose first /daily-count fetch failed reaches here; any
        # prior success rehydrates _daily_counts from .storage at load time, and
        # HA retries the first refresh automatically, so this self-heals.
        if not self._yearly_ranks:
            raise UpdateFailed(
                "Rarity baseline not yet available — /daily-count backfill has "
                "no data yet and there is no cached history"
            )

        try:
            daily_raw = await self._fetch_detections(DAILY_WINDOW_HOURS)
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error communicating with Haikubox API: {err}") from err

        # Single API call: the 24h window is a superset of the 1h window we
        # used to fetch separately. Derive the recent subset client-side at
        # the raw level so `count` on recent_detections items reflects
        # detections-in-last-hour, not detections-in-last-24h.
        recent_threshold = datetime.now(timezone.utc) - timedelta(hours=RECENT_WINDOW_HOURS)
        recent_raw = {"detections": _filter_by_dt(daily_raw, recent_threshold)}

        detections = _normalise_detections(recent_raw)
        _apply_rarity_scores(detections, self._yearly_ranks, self._yearly_species_count)

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
        _apply_rarity_scores(daily_count, self._yearly_ranks, self._yearly_species_count)

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

        # Reconcile the lifetime first-seen log with the TRUE per-day history.
        # On its own _seen_species only records when the *integration* first
        # observed a species, so a recent (re)install makes everything look new
        # (e.g. new-in-30-days == lifetime). daily_counts holds the box's real
        # backfilled history, so a species' first_seen should be the earliest
        # day it actually appears there. Walking oldest-first, set or lower each
        # species' first_seen accordingly. This also stops the live new_species
        # event from firing for species already present in that history.
        for _day in sorted(self._daily_counts):
            for _sp in self._daily_counts[_day]:
                _prev = self._seen_species.get(_sp)
                if _prev is None or _day < _prev[:10]:
                    self._seen_species[_sp] = _day
                    seen_dirty = True

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
        # (which reads via url_for) returns /local/ URLs for seeded species.
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

        sticky_dirty = False
        if detections:
            if not self._last_detected or detections[0].get("species") != self._last_detected.get("species"):
                sticky_dirty = True
            self._last_detected = detections[0]

        # Notability: weighted blend of rarity_score (yearly-rank-derived,
        # stable across the day) and recency_score (linear decay over a 24h
        # window). The user controls the blend via a config option; high
        # weight on rarity → stable list dominated by long-tail species
        # (close to the historical behaviour); high weight on recency →
        # dynamic list dominated by what just happened. Computed over the
        # 24h list (not the 1h subset) so the recency component has real
        # dynamic range to express.
        rarity_weight = self.config_entry.options.get(
            CONF_NOTABLE_RARITY_WEIGHT, DEFAULT_NOTABLE_RARITY_WEIGHT
        ) / 100.0
        _apply_notability_scores(
            daily_count,
            datetime.now(timezone.utc),
            NOTABILITY_WINDOW_HOURS,
            rarity_weight,
        )
        notable = sorted(
            daily_count, key=lambda x: x.get("notability_score", 0), reverse=True
        )
        if notable:
            if not self._last_notable or notable[0].get("species") != self._last_notable.get("species"):
                sticky_dirty = True
            self._last_notable = notable[0]

        if sticky_dirty:
            await self._sticky_store.async_save(
                {"last_detected": self._last_detected, "last_notable": self._last_notable}
            )

        # Sticky-record bootstrap (independent of the _seen_species bootstrap
        # above). If a sticky sensor is still empty after the recent-window
        # block — fresh install during a quiet hour, or a restart with no
        # .sticky store yet — seed it from the 24-hour window we already
        # have in hand. No extra API call; fires at most once per sticky
        # sensor over the lifetime of the integration.
        if (self._last_detected is None or self._last_notable is None) and daily_count:
            # Cache images on the seeded record(s) so they carry /local/
            # URLs, matching the 1-hour pipeline above. (No-op for records
            # already cached during the _seen_species bootstrap.)
            for d in daily_count:
                if d.get("sp_code"):
                    d["image_url"] = await self._images.async_fetch(d["sp_code"])
            bootstrap_dirty = False
            if self._last_detected is None:
                by_recency = sorted(
                    daily_count, key=lambda x: x.get("last_seen") or "", reverse=True
                )
                if by_recency:
                    self._last_detected = by_recency[0]
                    bootstrap_dirty = True
            if self._last_notable is None:
                by_rarity = sorted(
                    daily_count, key=lambda x: x.get("rarity_score", 0), reverse=True
                )
                if by_rarity:
                    self._last_notable = by_rarity[0]
                    bootstrap_dirty = True
            if bootstrap_dirty:
                await self._sticky_store.async_save(
                    {"last_detected": self._last_detected, "last_notable": self._last_notable}
                )

        # Every list the sensors expose carries a 1-based `rank` reflecting
        # that sensor's own ordering criterion. Each list is sorted by its
        # criterion, then _ranked() stamps the position. (yearly_top_species
        # already carries its rank from the baseline aggregate.)

        # Per-event list for last_detection.detections — distinct from the
        # per-species `detections` lists every other sensor exposes (same
        # attribute name; different records-per-x semantic). The 24h raw
        # payload preserves event-level detail; we surface the N most
        # recent events here, capped to bound attribute size.
        recent_events = _build_recent_events(
            daily_raw,
            self._yearly_ranks,
            self._yearly_species_count,
            self._images.url_for,
            LAST_DETECTION_EVENT_LIMIT,
        )

        # Fire automation events (new_species / unusual_visitor) for this
        # poll's qualifying species, then advance the recent-window baseline.
        self._fire_detection_events(detections, newly_seen, prior_last_seen)

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

        # Activity-vs-typical: compare the most recent *completed* day to the
        # mean of completed days over the trailing ACTIVITY_BASELINE_DAYS
        # (excluding zero/offline days). Completed days only (not today's
        # partial), so the ratio is a stable full-day-vs-full-day comparison.
        today_str = today.isoformat()
        baseline_cutoff = (today - timedelta(days=ACTIVITY_BASELINE_DAYS)).isoformat()
        completed = {
            d: sum(c.values()) for d, c in self._daily_counts.items() if d < today_str
        }
        window_totals = [
            t for d, t in completed.items() if d >= baseline_cutoff and t > 0
        ]
        typical_daily = (
            round(sum(window_totals) / len(window_totals), 1) if window_totals else None
        )
        latest_day = max(completed) if completed else None
        latest_day_total = completed[latest_day] if latest_day else None

        # New-species momentum: how many species were first heard in the last
        # NEW_SPECIES_WINDOW_DAYS, and days since the most recent lifetime
        # first. first_seen values are ISO strings (date or datetime); compare
        # on the YYYY-MM-DD prefix (lexicographic == chronological for ISO).
        new_cutoff = (today - timedelta(days=NEW_SPECIES_WINDOW_DAYS)).isoformat()
        first_seen_dates = [fs[:10] for fs in self._seen_species.values() if fs]
        new_species_window = sum(1 for fs in first_seen_dates if fs >= new_cutoff)
        days_since_new: int | None = None
        if first_seen_dates:
            try:
                days_since_new = (today - date.fromisoformat(max(first_seen_dates))).days
            except ValueError:
                days_since_new = None

        return {
            # key == sensor id; the public list attribute is always
            # `detections`. Singular keys are sticky single records;
            # plural keys are ranked lists. The lists are per-species in
            # every case EXCEPT last_detection.detections (= recent_events
            # below), which is per-event — same field shape, but the same
            # species can appear multiple times.
            "recent_detections": _ranked(detections),       # by recency
            "last_detection": self._last_detected,           # sticky
            "recent_events": _ranked(recent_events),         # per-event by dt desc
            "notable_detection": self._last_notable,         # sticky
            # Capped (≤5/species) trailing-24h list from /detections. No longer
            # the daily_count *sensor's* value (that's today_total now) — kept
            # for the extended-silence emptiness check and rarest's "seen today"
            # membership, both of which only need presence, not true counts.
            "daily_count": daily_count,
            "daily_top_species": _ranked(self._build_today_top(today_species)),  # true counts, today
            "notable_detections": _ranked(notable),          # by rarity
            # Sticky lifetime-history list (N most recently first-seen
            # species, newest first). Derived from _seen_species, not from
            # the current poll's new arrivals — populated on a fresh box
            # as soon as the bootstrap fills _seen_species, and stays
            # populated forever after.
            "new_detections": _ranked(self._build_new_species_history()),
            "new_detection": self._build_last_new_species(), # sticky
            "lifetime_species_count": len(self._seen_species),
            "yearly_top_species": self._build_yearly_top(),  # by yearly count (own rank)
            "rarest_species": _ranked(seven_day_rare),       # by rarity
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
            self._fire_event(TRIGGER_NEW_SPECIES, by_species[sp])

        # unusual_visitor — a known species reappearing after a long absence.
        # Skipped on the first poll of the session (no baseline yet) so a
        # restart doesn't replay every long-absent bird currently in the
        # window. The "newly present vs. previous window" gate then prevents
        # re-firing while a bird lingers across polls.
        if self._prev_recent_species is not None:
            threshold_days = self.config_entry.options.get(
                CONF_ABSENCE_DAYS, DEFAULT_ABSENCE_DAYS
            )
            now = datetime.now(timezone.utc)
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

        self._prev_recent_species = current_recent

    def _fire_event(
        self, trigger_type: str, record: dict[str, Any], **extra: Any
    ) -> None:
        """Assemble and fire one haikubox_event for a species record."""
        device = dr.async_get(self.hass).async_get_device(
            identifiers={(DOMAIN, self.serial)}
        )
        if device is None:
            return  # device not in the registry yet (only on first-ever setup)
        self.hass.bus.async_fire(
            EVENT_HAIKUBOX,
            {
                "device_id": device.id,
                "serial": self.serial,
                "device_name": self.device_name,
                "type": trigger_type,
                "species": record.get("species"),
                "scientific_name": record.get("scientific_name"),
                "sp_code": record.get("sp_code"),
                "image_url": record.get("image_url"),
                "last_seen": record.get("last_seen"),
                "rarity_score": record.get("rarity_score"),
                "yearly_rank": record.get("yearly_rank"),
                **extra,
            },
        )

    # ------------------------------------------------------------------
    # Store helpers
    # ------------------------------------------------------------------

    async def _load_stores(self) -> None:
        seen      = await self._store.async_load()
        sp_codes  = await self._sp_codes_store.async_load()
        sci_names = await self._sci_names_store.async_load()
        last_seen = await self._last_seen_store.async_load()
        daily     = await self._daily_store.async_load()
        sticky    = await self._sticky_store.async_load()

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

        # Rehydrate the sticky records so last_detection / notable_species
        # show their last value immediately after a restart instead of
        # "unknown" until the next live detection.
        if isinstance(sticky, dict):
            ld = sticky.get("last_detected")
            ln = sticky.get("last_notable")
            if isinstance(ld, dict):
                self._last_detected = ld
            if isinstance(ln, dict):
                self._last_notable = ln

        # Rebuild the rarity baseline from the persisted daily counts so
        # rarity is available immediately on restart, before the first poll's
        # daily-count fetch. No-op-safe when the store is empty.
        self._rebuild_baseline(datetime.now(timezone.utc).date())

        # One-time cleanup of the legacy stores that earlier versions wrote.
        # The trailing-window baseline supersedes both, so they're orphaned;
        # async_remove no-ops if a file is already gone. Runs once per session
        # (this method is gated by _stores_loaded).
        for legacy in ("yearly", "seven_day"):
            await Store(
                self.hass, _STORE_VERSION, f"{DOMAIN}.{self.serial}.{legacy}"
            ).async_remove()

        await self._images.async_init()

        # Preload the bundled eBird-code fallback map off the event loop, so
        # the synchronous _sp_code_for() lookups during a poll never touch disk.
        await _async_load_ebird_codes(self.hass)

        self._stores_loaded = True

    async def _ensure_daily_counts(self, today: date) -> None:
        """Keep _daily_counts current and gap-free, then extend history.

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
        window_floor = (today - timedelta(days=RARITY_WINDOW_DAYS)).isoformat()
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

    def _rebuild_baseline(self, today: date) -> None:
        """Aggregate the trailing RARITY_WINDOW_DAYS of daily counts into the
        rarity baseline (species → rank). Replaces the calendar-year fetch;
        cheap enough to run every poll."""
        cutoff = (today - timedelta(days=RARITY_WINDOW_DAYS)).isoformat()
        totals: dict[str, int] = {}
        for date_str, counts in self._daily_counts.items():
            if date_str >= cutoff:  # ISO dates compare lexicographically
                for sp, c in counts.items():
                    totals[sp] = totals.get(sp, 0) + int(c)
        self._yearly_ranks, self._yearly_species_count, self._yearly_items = (
            _ranks_from_counts(totals)
        )
        self._yearly_fetched_date = today

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

        denom = max(self._yearly_species_count, 1)
        out: list[dict[str, Any]] = []
        for sp, c in counts7.items():
            sp_code = self._sp_code_for(sp)
            rank = self._yearly_ranks.get(sp, self._yearly_species_count)
            out.append({
                "species": sp,
                "scientific_name": self._sci_names.get(sp, ""),
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
        return self._sp_codes.get(species) or (_EBIRD_CODES or {}).get(species, "")

    def _build_yearly_top(self) -> list[dict[str, Any]]:
        """Yearly species list enriched with sp_code, scientific_name, last_seen, and image."""
        result = []
        for item in self._yearly_items:
            sp = item["species"]
            sp_code = self._sp_code_for(sp)
            result.append({
                **item,
                "sp_code": sp_code,
                "scientific_name": self._sci_names.get(sp, ""),
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
        denom = max(self._yearly_species_count, 1)
        result: list[dict[str, Any]] = []
        for sp, count in today_species.items():
            sp_code = self._sp_code_for(sp)
            rank = self._yearly_ranks.get(sp, self._yearly_species_count)
            result.append({
                "species": sp,
                "scientific_name": self._sci_names.get(sp, ""),
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
        denom = max(self._yearly_species_count, 1)
        result: list[dict[str, Any]] = []
        for species, first_seen in sorted_items:
            sp_code = self._sp_code_for(species)
            rank = self._yearly_ranks.get(species, self._yearly_species_count)  # cap at 1.0; see _apply_rarity_scores
            result.append({
                "species": species,
                "scientific_name": self._sci_names.get(species, ""),
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

    # ------------------------------------------------------------------
    # Public properties (used by diagnostics)
    # ------------------------------------------------------------------

    @property
    def yearly_fetched_date(self) -> date | None:
        return self._yearly_fetched_date

    @property
    def yearly_species_count(self) -> int:
        return self._yearly_species_count

    @property
    def lifetime_species_count(self) -> int:
        return len(self._seen_species)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

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
        dt = dt.replace(tzinfo=timezone.utc)
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
        key=lambda x: x.get("_last_seen_dt") or datetime.min.replace(tzinfo=timezone.utc),
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
    yearly_ranks: dict[str, int],
    yearly_species_count: int,
) -> None:
    """Mutate detection records in-place to add rarity_score and yearly_rank.

    Species absent from the yearly count fall back to rank=yearly_species_count,
    capping rarity_score at 1.0 — tied with the actually-rarest known
    species rather than overshooting it (issue #17). Without the cap,
    unknown species would always rank above ranked-rarest, which is a
    data-availability artifact rather than a genuine rarity signal.
    """
    denom = max(yearly_species_count, 1)
    for d in detections:
        rank = yearly_ranks.get(d["species"], yearly_species_count)
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
                    dt = dt.replace(tzinfo=timezone.utc)
                age_seconds = max(0.0, (now - dt).total_seconds())
                recency = max(0.0, 1.0 - age_seconds / window_seconds)
        d["notability_score"] = round(
            rarity_weight * rarity + recency_weight * recency, 4
        )


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
    yearly_ranks: dict[str, int],
    yearly_species_count: int,
    image_url_for,
    limit: int,
) -> list[dict[str, Any]]:
    """Return the N most recent individual detection events from the raw
    24h payload, sorted by `dt` descending.

    Unlike the per-species lists, this preserves event-level detail: the
    same species detected multiple times yields multiple records, each
    with its own `dt`. Rarity is looked up by species so all events for
    the same species carry the same `rarity_score` / `yearly_rank`.

    `image_url_for` is `ImageCache.url_for` — returns the cached `/local/`
    URL when available, falling back to the API URL otherwise (matching
    how the per-species records' image_url is derived).
    """
    if not isinstance(raw, dict):
        return []
    items = raw.get("detections", [])
    if not isinstance(items, list):
        return []

    denom = max(yearly_species_count, 1)
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
        rank = yearly_ranks.get(species, yearly_species_count)  # cap at 1.0; see _apply_rarity_scores
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
            "rarity_score": round(rank / denom, 4),
            "yearly_rank": rank,
        })

    events.sort(key=lambda e: e.get("last_seen") or "", reverse=True)
    return events[:limit]
