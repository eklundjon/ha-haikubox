from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import aiohttp
import aiofiles

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import API_BASE, DEFAULT_SCAN_INTERVAL, DETECTION_HOURS, DOMAIN, IMAGES_BASE

_LOGGER = logging.getLogger(__name__)

_STORE_VERSION = 1


class HaikuboxCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the Haikubox API and normalises the response for sensors."""

    def __init__(self, hass: HomeAssistant, serial: str, device_name: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.serial = serial
        self.device_name = device_name
        self._session = async_get_clientsession(hass)

        # Yearly counts — refreshed once per calendar day
        self._yearly_ranks: dict[str, int] = {}   # species → rank (1 = most common)
        self._yearly_total: int = 0
        self._yearly_fetched_date: date | None = None

        # Sticky records — set on first detection, never cleared
        self._last_detected: dict[str, Any] | None = None
        self._last_notable: dict[str, Any] | None = None

        # Persistent stores
        self._store            = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.seen_species")
        self._sp_codes_store   = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.sp_codes")
        self._sci_names_store  = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.sci_names")
        self._last_seen_store  = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.last_seen")
        self._yearly_store     = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.yearly")
        self._seven_day_store  = Store(hass, _STORE_VERSION, f"{DOMAIN}.{serial}.seven_day")

        # In-memory store state
        self._seen_species: dict[str, str] = {}          # species → first_seen ISO
        self._sp_codes: dict[str, str] = {}              # species → sp_code
        self._sci_names: dict[str, str] = {}             # species → scientific_name
        self._last_seen: dict[str, str] = {}             # species → last_seen ISO
        self._yearly_items: list[dict[str, Any]] = []    # [{species, count, rank}]
        self._seven_day_data: dict[str, list] = {}       # date_str → [species records]
        self._stores_loaded: bool = False

        # Local image cache directory (served via /local/haikubox/)
        self._image_cache_dir: Path = Path(hass.config.path("www", "haikubox"))
        # In-memory set of sp_codes with a cached image; avoids repeated stat calls
        self._cached_images: set[str] = set()

    # ------------------------------------------------------------------
    # DataUpdateCoordinator interface
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        if not self._stores_loaded:
            await self._load_stores()

        today = date.today()

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
            detections_raw = await self._fetch_detections()
            daily_raw = await self._fetch_daily_count()
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error communicating with Haikubox API: {err}") from err

        detections = _normalise_detections(detections_raw)
        _apply_rarity_scores(detections, self._yearly_ranks, self._yearly_total)

        # Cache images and rewrite image_url to local path
        for d in detections:
            if d.get("sp_code"):
                d["image_url"] = await self._cache_image(d["sp_code"])

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

        # Track new (never-before-seen) species
        new_species: list[dict[str, Any]] = []
        seen_dirty = False
        for d in detections:
            sp = d["species"]
            if sp not in self._seen_species:
                first_seen = d.get("last_seen") or today.isoformat()
                self._seen_species[sp] = first_seen
                d["first_seen"] = first_seen
                new_species.append(d)
                seen_dirty = True
        if seen_dirty:
            await self._store.async_save(self._seen_species)

        # Update 7-day rolling store with today's detections
        seven_day_rare = await self._update_seven_day(detections, today)

        if detections:
            self._last_detected = detections[0]

        notable = sorted(detections, key=lambda x: x["rarity_score"], reverse=True)
        if notable:
            self._last_notable = notable[0]

        daily_count = _normalise_daily_count(daily_raw)

        return {
            "detections": detections,
            "last_detected": self._last_detected,
            "last_notable": self._last_notable,
            "daily_count": daily_count,
            "notable_detections": notable,
            "new_species": new_species,
            "lifetime_species_count": len(self._seen_species),
            # Details datasets — built entirely from stores + current poll
            "yearly_top": self._build_yearly_top(),
            "daily_top": self._build_daily_top(daily_count),
            "seven_day_rare": seven_day_rare,
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

        self._seen_species   = seen      if isinstance(seen, dict)      else {}
        self._sp_codes       = sp_codes  if isinstance(sp_codes, dict)  else {}
        self._sci_names      = sci_names if isinstance(sci_names, dict) else {}
        self._last_seen      = last_seen if isinstance(last_seen, dict) else {}
        self._yearly_items   = yearly    if isinstance(yearly, list)    else []
        self._seven_day_data = seven_day if isinstance(seven_day, dict) else {}

        # Create image cache directory and index existing files — one executor
        # call at startup, then all image lookups are in-memory.
        await self.hass.async_add_executor_job(self._init_image_cache)

        self._stores_loaded = True

    def _init_image_cache(self) -> None:
        """Create the image cache directory and populate _cached_images."""
        self._image_cache_dir.mkdir(parents=True, exist_ok=True)
        for p in self._image_cache_dir.glob("*.jpeg"):
            self._cached_images.add(p.stem)

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

    def _image_url_for(self, sp_code: str) -> str | None:
        """Return local image URL if the file is cached, else None."""
        if not sp_code or sp_code not in self._cached_images:
            return None
        return f"/local/haikubox/{sp_code}.jpeg"

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
                "image_url": self._image_url_for(sp_code),
            })
        return result

    def _build_daily_top(self, daily_count: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Daily count list enriched with sp_code, scientific_name, last_seen, and image."""
        result = []
        for item in daily_count:
            sp = item["species"]
            sp_code = self._sp_codes.get(sp, "")
            result.append({
                **item,
                "sp_code": sp_code,
                "scientific_name": self._sci_names.get(sp, ""),
                "last_seen": self._last_seen.get(sp),
                "image_url": self._image_url_for(sp_code),
            })
        return result

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

    async def _cache_image(self, sp_code: str) -> str:
        """Return a local /local/ URL for the species image, downloading it if needed."""
        if sp_code in self._cached_images:
            return f"/local/haikubox/{sp_code}.jpeg"

        local_path = self._image_cache_dir / f"{sp_code}.jpeg"
        url = f"{IMAGES_BASE}/{sp_code}.jpeg"
        try:
            async with self._session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    async with aiofiles.open(local_path, "wb") as f:
                        await f.write(data)
                    self._cached_images.add(sp_code)
                else:
                    _LOGGER.debug("No image for %s (HTTP %s)", sp_code, resp.status)
                    return f"{IMAGES_BASE}/{sp_code}.jpeg"
        except aiohttp.ClientError as err:
            _LOGGER.debug("Could not cache image for %s: %s", sp_code, err)
            return f"{IMAGES_BASE}/{sp_code}.jpeg"
        return f"/local/haikubox/{sp_code}.jpeg"

    async def _fetch_detections(self) -> Any:
        url = f"{API_BASE}/haikubox/{self.serial}/detections"
        async with self._session.get(url, params={"hours": DETECTION_HOURS}) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _fetch_daily_count(self) -> Any:
        url = f"{API_BASE}/haikubox/{self.serial}/daily-count"
        async with self._session.get(url) as resp:
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


def _normalise_daily_count(raw: Any) -> list[dict[str, Any]]:
    """Return a list of {species, count} sorted by count descending."""
    if not isinstance(raw, list):
        _LOGGER.debug("Unexpected daily-count payload type: %s", type(raw))
        return []

    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        result.append({"species": item.get("bird", "Unknown"), "count": int(item.get("count", 0))})

    return sorted(result, key=lambda x: x["count"], reverse=True)
