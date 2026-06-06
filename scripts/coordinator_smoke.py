"""Drive the real HaikuboxCoordinator._async_update_data with canned,
deterministic inputs (no network, no HA), and print a stable structural
summary of the result. Used to prove behaviour-preserving refactors: run it
before and after a change and diff the output.

    python scripts/coordinator_smoke.py

Determinism: detection timestamps are generated relative to "now" so the
recency/24h windows have stable membership, but raw timestamps are excluded
from the summary; notability is forced to pure-rarity (recency-independent).
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")
from custom_components.haikubox.coordinator import HaikuboxCoordinator  # noqa: E402
from custom_components.haikubox.const import CONF_NOTABLE_RARITY_WEIGHT  # noqa: E402

_NOW = datetime.now(timezone.utc)


def _iso(minutes_ago: int) -> str:
    return (_NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


# Canned /detections payload: a few species, multiple events, varied recency.
_DETECTIONS = {"detections": [
    {"cn": "American Robin", "sn": "Turdus migratorius", "spCode": "amerob", "dt": _iso(15)},
    {"cn": "American Robin", "sn": "Turdus migratorius", "spCode": "amerob", "dt": _iso(40)},
    {"cn": "American Robin", "sn": "Turdus migratorius", "spCode": "amerob", "dt": _iso(200)},
    {"cn": "Northern Cardinal", "sn": "Cardinalis cardinalis", "spCode": "norcar", "dt": _iso(50)},
    {"cn": "Barred Owl", "sn": "Strix varia", "spCode": "brdowl", "dt": _iso(600)},
    {"cn": "soundscape", "sn": "", "spCode": "soundscape", "dt": _iso(5)},
]}


class _FakeStore:
    async def async_load(self): return None
    async def async_save(self, data): return None
    async def async_remove(self): return None


class _FakeImages:
    async def async_init(self): return None
    def url_for(self, sp_code): return f"/local/haikubox/{sp_code}.jpeg" if sp_code else None
    async def async_fetch(self, sp_code): return f"/local/haikubox/{sp_code}.jpeg"


class _FakeEntry:
    options = {CONF_NOTABLE_RARITY_WEIGHT: 100}  # pure rarity → no "now" dependence


async def main() -> None:
    c = HaikuboxCoordinator.__new__(HaikuboxCoordinator)
    c.serial = "TESTSERIAL"
    c.device_name = "Test Box"
    c.hass = None
    c.config_entry = _FakeEntry()
    c._box_tz = timezone.utc
    c._images = _FakeImages()
    c._audio = None  # canned data has no wav → audio resolve short-circuits
    c._latest_wav_by_species = {}
    c._last_detected = None
    c._last_notable = None
    c._prev_recent_species = None
    c._stores_loaded = True
    for attr in ("_store", "_sp_codes_store", "_sci_names_store", "_last_seen_store",
                 "_daily_store", "_sticky_store"):
        setattr(c, attr, _FakeStore())
    c._sp_codes, c._sci_names, c._last_seen, c._seen_species = {}, {}, {}, {}
    c._baseline_ranks, c._baseline_species_count, c._baseline_items = {}, 0, []
    c._reconciled_once = False

    # Per-day history: 8 completed days + a deep tail, fully covering [today-8..
    # yesterday] with backfill_complete so _ensure_daily_counts fetches nothing.
    today = _NOW.date()
    c._daily_counts = {}
    for n in range(1, 9):
        d = (today - timedelta(days=n)).isoformat()
        c._daily_counts[d] = {"American Robin": 80 + n, "Northern Cardinal": 30,
                              "Barred Owl": 1 if n % 4 == 0 else 0}
    c._backfill_complete = True
    c._backfill_cursor = (today - timedelta(days=9)).isoformat()
    c._backfill_misses = 14
    c._stats_imported_date = None

    async def fake_detections(hours): return _DETECTIONS
    async def fake_daily_count(date_str):
        if date_str == today.isoformat():
            return {"American Robin": 120, "Northern Cardinal": 44, "Barred Owl": 2}
        return c._daily_counts.get(date_str, {})
    async def fake_box_tz(): return timezone.utc
    c._fetch_detections = fake_detections
    c._fetch_daily_count = fake_daily_count
    c._async_box_tz = fake_box_tz

    data = await c._async_update_data()

    def summarise_list(key):
        out = []
        for r in data.get(key) or []:
            out.append((r.get("species"), r.get("count"), r.get("yearly_rank"),
                        r.get("rarity_score"), r.get("rank")))
        return out

    print("=== scalars ===")
    for k in ("today_total", "typical_daily_count", "latest_day_total", "latest_day_date",
              "new_species_window", "days_since_new_species", "lifetime_species_count",
              "history_earliest", "history_days_recorded", "history_complete"):
        print(f"  {k:24} {data.get(k)!r}")
    print("=== list keys (species, count, yearly_rank, rarity_score, rank) ===")
    for k in ("recent_detections", "recent_events", "detections_24h", "daily_top_species",
              "notable_detections", "new_detections", "yearly_top_species", "rarest_species"):
        print(f"  {k}: {summarise_list(k)}")
    print("=== sticky / sets ===")
    print(f"  last_detection:  {(data.get('last_detection') or {}).get('species')!r}")
    print(f"  notable_detection: {(data.get('notable_detection') or {}).get('species')!r}")
    print(f"  new_detection:   {(data.get('new_detection') or {}).get('species')!r}")
    print(f"  today_species:   {data.get('today_species')!r}")
    print(f"  seen_species:    {sorted(c._seen_species.items())}")


if __name__ == "__main__":
    asyncio.run(main())
