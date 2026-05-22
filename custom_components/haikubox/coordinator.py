from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_BASE,
    CONF_DEVICE_NAME,
    CONF_NOTABLE_RARITY_WEIGHT,
    CONF_SERIAL,
    DAILY_WINDOW_HOURS,
    DEFAULT_NOTABLE_RARITY_WEIGHT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    IMAGES_BASE,
    LAST_DETECTION_EVENT_LIMIT,
    NEW_SPECIES_HISTORY_LIMIT,
    NOTABILITY_WINDOW_HOURS,
    RECENT_WINDOW_HOURS,
)
from .image_cache import ImageCache

_LOGGER = logging.getLogger(__name__)

_STORE_VERSION = 1

# Config entry whose runtime_data is the coordinator (lazily evaluated,
# so the forward reference to the class below is fine).
type HaikuboxConfigEntry = ConfigEntry[HaikuboxCoordinator]


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
        self._yearly_total: int = 0
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
        self._yearly_store     = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.yearly")
        self._seven_day_store  = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.seven_day")
        self._sticky_store     = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.sticky")

        # In-memory store state
        self._seen_species: dict[str, str] = {}          # species → first_seen ISO
        self._sp_codes: dict[str, str] = {}              # species → sp_code
        self._sci_names: dict[str, str] = {}             # species → scientific_name
        self._last_seen: dict[str, str] = {}             # species → last_seen ISO
        self._yearly_items: list[dict[str, Any]] = []    # [{species, count, rank}]
        self._seven_day_data: dict[str, list] = {}       # date_str → [species records]
        self._stores_loaded: bool = False

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

        # Refresh yearly baseline once per calendar day
        if self._yearly_fetched_date != today:
            try:
                yearly_raw = await self._fetch_yearly_count()
                self._yearly_ranks, self._yearly_total, self._yearly_items = (
                    _process_yearly_count(yearly_raw)
                )
                self._yearly_fetched_date = today
                await self._yearly_store.async_save(self._yearly_items)
            except aiohttp.ClientError as err:
                _LOGGER.warning("Could not fetch yearly counts: %s", err)

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
        _apply_rarity_scores(detections, self._yearly_ranks, self._yearly_total)

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
        _apply_rarity_scores(daily_count, self._yearly_ranks, self._yearly_total)

        # Cache images and rewrite image_url to local path
        for d in detections:
            if d.get("sp_code"):
                d["image_url"] = await self._images.async_fetch(d["sp_code"])

        # Update sp_codes, scientific_name, and last_seen lookups from current detections
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
        if sp_codes_dirty:
            await self._sp_codes_store.async_save(self._sp_codes)
        if sci_names_dirty:
            await self._sci_names_store.async_save(self._sci_names)
        if last_seen_dirty:
            await self._last_seen_store.async_save(self._last_seen)

        seen_dirty = False

        # Fresh-install bootstrap for _seen_species. Must run BEFORE the
        # recent-window loop below; otherwise that loop would seed
        # _seen_species from the 1h subset only and species detected 2-24h
        # ago would silently miss their "new" flagging until they next
        # appear in a recent window (issue #14).
        #
        # We use each detection's own dt as first_seen — accurate for our
        # observation window (the box's true lifetime first-detection date
        # is fundamentally inaccessible). Image fetches populate the cache
        # so _build_new_species_history (which reads via url_for) returns
        # /local/ URLs for these seeded species.
        if not self._seen_species and daily_count:
            for d in daily_count:
                sp = d["species"]
                if not sp:
                    continue
                if d.get("sp_code"):
                    await self._images.async_fetch(d["sp_code"])
                self._seen_species[sp] = d.get("last_seen") or today.isoformat()
                seen_dirty = True

        # Track new (never-before-seen) species from the recent window.
        # On a fresh install this is a no-op (the bootstrap above already
        # covered everything in the 24h superset); on established installs
        # this is the live new-species detector.
        for d in detections:
            sp = d["species"]
            if sp not in self._seen_species:
                self._seen_species[sp] = d.get("last_seen") or today.isoformat()
                seen_dirty = True
        if seen_dirty:
            await self._store.async_save(self._seen_species)

        # Update 7-day rolling store with today's detections. Feed in the
        # 24h-normalised list, not the 1h recent subset, so a species heard
        # once outside the recent window still refreshes today's bucket on
        # this poll (issue #15). Within-day dedup by species is handled by
        # _update_seven_day's today_map; rarity scores are identical on both
        # lists (both have had _apply_rarity_scores called on them).
        seven_day_rare = await self._update_seven_day(daily_count, today)

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
        # already carries its yearly rank from _process_yearly_count.)

        # Per-event list for last_detection.detections — distinct from the
        # per-species `detections` lists every other sensor exposes (same
        # attribute name; different records-per-x semantic). The 24h raw
        # payload preserves event-level detail; we surface the N most
        # recent events here, capped to bound attribute size.
        recent_events = _build_recent_events(
            daily_raw,
            self._yearly_ranks,
            self._yearly_total,
            self._images.url_for,
            LAST_DETECTION_EVENT_LIMIT,
        )

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
            "daily_count": daily_count,                      # 24h per-species — total only
            "daily_top_species": _ranked(self._build_daily_list(daily_count)),  # by 24h count
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
        }

    # ------------------------------------------------------------------
    # Store helpers
    # ------------------------------------------------------------------

    async def _load_stores(self) -> None:
        seen      = await self._store.async_load()
        sp_codes  = await self._sp_codes_store.async_load()
        sci_names = await self._sci_names_store.async_load()
        last_seen = await self._last_seen_store.async_load()
        yearly    = await self._yearly_store.async_load()
        seven_day = await self._seven_day_store.async_load()
        sticky    = await self._sticky_store.async_load()

        self._seen_species   = seen      if isinstance(seen, dict)      else {}
        self._sp_codes       = sp_codes  if isinstance(sp_codes, dict)  else {}
        self._sci_names      = sci_names if isinstance(sci_names, dict) else {}
        self._last_seen      = last_seen if isinstance(last_seen, dict) else {}
        self._yearly_items   = yearly    if isinstance(yearly, list)    else []
        self._seven_day_data = seven_day if isinstance(seven_day, dict) else {}

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

        # Rehydrate the rank lookup from the persisted yearly list. Without
        # this, _yearly_ranks/_yearly_total stay empty after a restart until
        # the once-per-day yearly API fetch succeeds — so if that endpoint is
        # down at restart, every species would score rarity 1.0 even though
        # the data needed to score them is sitting in the store.
        self._yearly_ranks = {
            item["species"]: item["rank"]
            for item in self._yearly_items
            if isinstance(item, dict) and item.get("species") and item.get("rank")
        }
        self._yearly_total = len(self._yearly_ranks)

        await self._images.async_init()

        self._stores_loaded = True

    async def _update_seven_day(
        self, detections: list[dict[str, Any]], today: date
    ) -> list[dict[str, Any]]:
        """Merge today's detections into the rolling 7-day store.

        Returns the merged list of unique species across 7 days, sorted by
        rarity_score descending.
        """
        today_str = today.isoformat()
        today_map: dict[str, dict] = {
            item["species"]: item
            for item in self._seven_day_data.get(today_str, [])
        }

        dirty = False
        for d in detections:
            sp = d["species"]
            existing = today_map.get(sp)
            if existing is None or d.get("rarity_score", 0) >= existing.get("rarity_score", 0):
                today_map[sp] = {
                    "species": sp,
                    "sp_code": d.get("sp_code", ""),
                    "scientific_name": d.get("scientific_name", ""),
                    "rarity_score": d.get("rarity_score", 0.0),
                    "yearly_rank": d.get("yearly_rank", 0),
                    "count": d.get("count", 0),
                    "image_url": d.get("image_url"),
                    "last_seen": d.get("last_seen"),
                }
                dirty = True

        self._seven_day_data[today_str] = list(today_map.values())

        # Prune days older than 7
        cutoff = (today - timedelta(days=7)).isoformat()
        stale = [k for k in self._seven_day_data if k < cutoff]
        for k in stale:
            del self._seven_day_data[k]
            dirty = True

        if dirty:
            await self._seven_day_store.async_save(self._seven_day_data)

        # Merge across all stored days: per species, keep highest rarity_score
        merged: dict[str, dict] = {}
        for day_items in self._seven_day_data.values():
            for item in day_items:
                sp = item["species"]
                existing = merged.get(sp)
                if existing is None:
                    merged[sp] = dict(item)
                elif item.get("rarity_score", 0) > existing.get("rarity_score", 0):
                    merged[sp] = dict(item)
                elif item.get("last_seen", "") > existing.get("last_seen", ""):
                    merged[sp] = {**existing, "last_seen": item["last_seen"]}

        return sorted(merged.values(), key=lambda x: x.get("rarity_score", 0), reverse=True)

    # ------------------------------------------------------------------
    # Dataset builders (store-only, no API calls)
    # ------------------------------------------------------------------

    def _build_yearly_top(self) -> list[dict[str, Any]]:
        """Yearly species list enriched with sp_code, scientific_name, last_seen, and image."""
        result = []
        for item in self._yearly_items:
            sp = item["species"]
            sp_code = self._sp_codes.get(sp, "")
            result.append({
                **item,
                "sp_code": sp_code,
                "scientific_name": self._sci_names.get(sp, ""),
                "last_seen": self._last_seen.get(sp),
                "image_url": self._images.url_for(sp_code),
            })
        return result

    def _build_daily_list(self, daily_count: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Today's species (count desc) enriched with sp_code, scientific_name, last_seen, image."""
        result = []
        for item in daily_count:
            sp = item["species"]
            sp_code = self._sp_codes.get(sp, "")
            result.append({
                **item,
                "sp_code": sp_code,
                "scientific_name": self._sci_names.get(sp, ""),
                "last_seen": self._last_seen.get(sp),
                "image_url": self._images.url_for(sp_code),
            })
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
        denom = max(self._yearly_total, 1)
        result: list[dict[str, Any]] = []
        for species, first_seen in sorted_items:
            sp_code = self._sp_codes.get(species, "")
            rank = self._yearly_ranks.get(species, self._yearly_total + 1)
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
    def yearly_total(self) -> int:
        return self._yearly_total

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

    async def _fetch_yearly_count(self) -> Any:
        url = f"{API_BASE}/haikubox/{self.serial}/yearly-count"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()


# ------------------------------------------------------------------
# Response normalisation
# ------------------------------------------------------------------

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
        dt_str = item.get("dt")
        if not isinstance(dt_str, str) or not dt_str:
            continue
        try:
            dt = datetime.fromisoformat(dt_str)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt >= threshold:
            out.append(item)
    return out


def _normalise_detections(raw: Any) -> list[dict[str, Any]]:
    """Collapse the flat detections list into one record per species."""
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
        dt = item.get("dt")

        if key not in by_species:
            by_species[key] = {
                "species": item.get("cn", "Unknown"),
                "scientific_name": item.get("sn", ""),
                "sp_code": sp_code,
                "image_url": f"{IMAGES_BASE}/{sp_code}.jpeg" if sp_code else None,
                "last_seen": dt,
                "count": 0,
                "rarity_score": 0.0,
                "yearly_rank": 0,
            }
        by_species[key]["count"] += 1
        if dt and (by_species[key]["last_seen"] is None or dt > by_species[key]["last_seen"]):
            by_species[key]["last_seen"] = dt

    return sorted(by_species.values(), key=lambda x: x.get("last_seen") or "", reverse=True)


def _process_yearly_count(
    raw: Any,
) -> tuple[dict[str, int], int, list[dict[str, Any]]]:
    """Return (species→rank, total, items_list) from the yearly-count response.

    items_list entries: {"species": str, "count": int, "rank": int}
    """
    if not isinstance(raw, list):
        return {}, 0, []

    sorted_items = sorted(
        [item for item in raw if isinstance(item, dict)],
        key=lambda x: int(x.get("count", 0)),
        reverse=True,
    )
    ranks: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    for idx, item in enumerate(sorted_items):
        name = item.get("bird", "")
        if not name:
            continue
        rank = idx + 1
        ranks[name] = rank
        items.append({"species": name, "count": int(item.get("count", 0)), "rank": rank})

    return ranks, len(ranks), items


def _apply_rarity_scores(
    detections: list[dict[str, Any]],
    yearly_ranks: dict[str, int],
    yearly_total: int,
) -> None:
    """Mutate detection records in-place to add rarity_score and yearly_rank."""
    denom = max(yearly_total, 1)
    for d in detections:
        rank = yearly_ranks.get(d["species"], yearly_total + 1)
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
    yearly_total: int,
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

    denom = max(yearly_total, 1)
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
        rank = yearly_ranks.get(species, yearly_total + 1)
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
