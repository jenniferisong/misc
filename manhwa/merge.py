"""Combine the three sources into one list of series with their recent chapters.

No network here, so everything is testable with small hand-made inputs.

Series are matched across sites by id, never by title: MangaDex stores each
series' MangaUpdates id (in base 36, e.g. "3jj07ch") and AniList id in its
links. A series is keyed "mu:<MangaUpdates id>" when that's known, else
"md:<MangaDex id>".
"""

import datetime as dt
import re

import config

DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
# AniList link languages worth showing as "read officially" buttons, in display order.
OFFICIAL_LANGUAGES = {"English": 0, None: 1, "Korean": 2}


def mu_id(link):
    """MangaDex's "mu" link -> MangaUpdates numeric series id, or None.

    New MangaUpdates ids are base 36 strings like "3jj07ch". Very old entries
    hold the retired all-digit ids, which the API no longer accepts.
    """
    if not link or link.isdigit() or not re.fullmatch(r"[0-9a-z]+", link):
        return None
    return int(link, 36)


def parse_time(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


def iso(t):
    return t.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def chapter_number(ch):
    try:
        return float(re.match(r"\d+(\.\d+)?", ch or "").group())
    except (AttributeError, ValueError):
        return None


# ── Updates ─────────────────────────────────────────────────────────────────

def updates_from_mu(releases):
    return [
        {
            "series": f"mu:{r['series_id']}",
            "chapter": r["chapter"],
            "volume": r["volume"],
            "group": r["group"],
            "url": r["group_url"] or r["series_url"],
            "time": iso(dt.datetime.fromtimestamp(r["timestamp"], dt.timezone.utc)),
            "source": "MangaUpdates",
        }
        for r in releases
    ]


def series_key_for_md(manga_id, md_info):
    mid = mu_id((md_info.get(manga_id) or {}).get("links", {}).get("mu"))
    return f"mu:{mid}" if mid else f"md:{manga_id}"


def updates_from_md(chapters, md_info):
    return [
        {
            "series": series_key_for_md(c["manga_id"], md_info),
            "md_id": c["manga_id"],
            "chapter": c["chapter"],
            "volume": c["volume"],
            "group": c["group"] or ("Official" if c["external_url"] else "No group"),
            "url": c["external_url"] or f"https://mangadex.org/chapter/{c['chapter_id']}",
            "time": iso(parse_time(c["readable_at"])),
            "source": "MangaDex",
        }
        for c in chapters
    ]


def merge_updates(old, new, now):
    """Union of cached and fresh updates, without duplicates or entries older than KEEP_DAYS.

    MangaUpdates sometimes lists one release more than once as it is edited;
    the earliest time is kept.
    """
    cutoff = now - dt.timedelta(days=config.KEEP_DAYS)
    merged = {}
    for u in old + new:
        if parse_time(u["time"]) < cutoff:
            continue
        key = (u["series"], u["chapter"], u["volume"], u["group"].casefold(), u["source"])
        if key not in merged or u["time"] < merged[key]["time"]:
            merged[key] = u
    return sorted(merged.values(), key=lambda u: u["time"], reverse=True)


# ── Series ──────────────────────────────────────────────────────────────────

def keep_series(key, updates, mu_info):
    """Manhwa only: MangaDex already filters to Korean originals; MangaUpdates needs the series type."""
    if any(u["source"] == "MangaDex" for u in updates):
        return True
    info = mu_info.get(key.removeprefix("mu:")) or {}
    return info.get("type") in config.SERIES_TYPES


def official_links(al, md):
    links, seen = [], set()
    al_links = sorted((al or {}).get("externalLinks") or [], key=lambda l: OFFICIAL_LANGUAGES.get(l.get("language"), 9))
    for link in al_links:
        if link.get("type") == "STREAMING" and link.get("language") in OFFICIAL_LANGUAGES and link["site"] not in seen:
            seen.add(link["site"])
            links.append({"site": link["site"], "url": link["url"]})
    engtl = (md or {}).get("links", {}).get("engtl")
    if engtl and not any(link["url"] == engtl for link in links):
        links.insert(0, {"site": "Official English", "url": engtl})
    return links


def group_chapters(updates):
    """One row per chapter, listing every group/site that released it."""
    rows = {}
    for u in updates:
        key = (u["chapter"], u["volume"])
        row = rows.setdefault(key, {"chapter": u["chapter"], "volume": u["volume"], "time": u["time"], "releases": []})
        row["time"] = min(row["time"], u["time"])
        row["releases"].append({"group": u["group"], "url": u["url"], "source": u["source"]})
    return sorted(
        rows.values(),
        key=lambda r: (chapter_number(r["chapter"]) is not None, chapter_number(r["chapter"]) or 0, r["time"]),
        reverse=True,
    )


def build_series(updates, mu_info, md_info, al_info):
    by_series = {}
    for u in updates:
        by_series.setdefault(u["series"], []).append(u)

    out = []
    for key, ups in by_series.items():
        if not keep_series(key, ups, mu_info):
            continue
        mu = mu_info.get(key.removeprefix("mu:")) if key.startswith("mu:") else None
        md_id = next((u["md_id"] for u in ups if u.get("md_id")), key.removeprefix("md:") if key.startswith("md:") else None)
        md = md_info.get(md_id) if md_id else None
        al_id = (md or {}).get("links", {}).get("al")
        al = al_info.get(int(al_id)) if al_id and al_id.isdigit() else None

        al_title = ((al or {}).get("title") or {})
        numbers = [n for n in (chapter_number(u["chapter"]) for u in ups) if n is not None]
        out.append(
            {
                "key": key,
                "title": al_title.get("english") or (mu or {}).get("title") or (md or {}).get("title") or ups[0].get("title", "Untitled"),
                "cover": ((al or {}).get("coverImage") or {}).get("large") or (mu or {}).get("cover") or (md or {}).get("cover"),
                "genres": (al or {}).get("genres") or (mu or {}).get("genres") or (md or {}).get("genres") or [],
                "status": (mu or {}).get("status") or (md or {}).get("status"),
                "rating": (mu or {}).get("rating"),
                "score": (al or {}).get("averageScore"),
                "popularity": (al or {}).get("popularity"),
                "links": {
                    k: v
                    for k, v in {
                        "MangaUpdates": (mu or {}).get("url"),
                        "MangaDex": f"https://mangadex.org/title/{md_id}" if md_id else None,
                        "AniList": (al or {}).get("siteUrl"),
                    }.items()
                    if v
                },
                "official": official_links(al, md),
                "latest": max(u["time"] for u in ups),
                "is_new": bool(numbers) and min(numbers) <= 3,
                "chapters": group_chapters(ups),
            }
        )
    return sorted(out, key=lambda s: s["latest"], reverse=True)


def trending(media):
    return [
        {
            "title": (m["title"] or {}).get("english") or (m["title"] or {}).get("romaji"),
            "cover": (m.get("coverImage") or {}).get("large"),
            "score": m.get("averageScore"),
            "genres": m.get("genres") or [],
            "url": m["siteUrl"],
            "official": official_links(m, None),
        }
        for m in media
    ]
