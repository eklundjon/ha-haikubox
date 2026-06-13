"""Pure response-normalisation, scoring, and link helpers.

Stateless functions extracted from coordinator.py: they take raw API payloads
or detection records and return transformed data, with no coordinator/HA state.
Kept together so the coordinator module stays focused on orchestration.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from .const import IMAGES_BASE

_LOGGER = logging.getLogger(__name__)


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
