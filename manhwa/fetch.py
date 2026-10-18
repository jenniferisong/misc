"""Download manhwa updates from MangaUpdates, MangaDex and AniList.

All three are free public APIs with no key. Each function returns plain dicts;
merge.py turns them into the site's data.

- MangaUpdates: every chapter release (official publishers and scanlation
  groups), two days per page, plus each series' type, genres and cover.
- MangaDex: chapters of Korean-original series uploaded recently.
- AniList: official places to read, scores, and what's trending.
"""

import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import config

MU = "https://api.mangaupdates.com/v1"
MD = "https://api.mangadex.org"
AL = "https://graphql.anilist.co"

_last_call = {}


def get_json(source, url, body=None):
    """GET (or POST a JSON body) with a polite pause and retries on rate limits / server errors."""
    wait = config.PAUSE_SECONDS[source] - (time.monotonic() - _last_call.get(source, 0))
    if wait > 0:
        time.sleep(wait)

    headers = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"

    for attempt in range(5):
        _last_call[source] = time.monotonic()
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code not in (429, 500, 502, 503, 504) or attempt == 4:
                raise
            delay = int(e.headers.get("Retry-After") or 0) or 2 ** (attempt + 1)
        except (urllib.error.URLError, TimeoutError):
            if attempt == 4:
                raise
            delay = 2 ** (attempt + 1)
        print(f"  {source}: retrying in {delay}s", file=sys.stderr)
        time.sleep(delay)


# ── MangaUpdates ────────────────────────────────────────────────────────────

def mu_releases(pages=1):
    """Chapter releases MangaUpdates logged recently. Each page is two days, newest first."""
    out = []
    for page in range(1, pages + 1):
        d = get_json("mangaupdates", f"{MU}/releases/days?include_metadata=true&page={page}")
        results = (d or {}).get("results") or []
        for r in results:
            rec, series = r["record"], (r.get("metadata") or {}).get("series") or {}
            if not series.get("series_id"):
                continue
            groups = rec.get("groups") or [{}]
            out.append(
                {
                    "series_id": series["series_id"],
                    "series_title": series.get("title") or rec["title"],
                    "series_url": series.get("url"),
                    "chapter": rec.get("chapter") or "",
                    "volume": rec.get("volume") or "",
                    "group": ", ".join(g.get("name", "") for g in groups if g.get("name")),
                    "group_url": groups[0].get("url"),
                    "timestamp": rec["time_added"]["timestamp"],
                }
            )
        if not results:
            break
    return out


def mu_series(series_id):
    """Type, genres, cover and rating for one series, or None if it's gone."""
    d = get_json("mangaupdates", f"{MU}/series/{series_id}")
    if not d:
        return None
    return {
        "type": d.get("type"),
        "title": d.get("title"),
        "url": d.get("url"),
        "year": d.get("year"),
        "status": d.get("status"),
        "completed": d.get("completed"),
        "genres": [g["genre"] for g in d.get("genres") or []],
        "rating": d.get("bayesian_rating"),
        "cover": ((d.get("image") or {}).get("url") or {}).get("original"),
    }


# ── MangaDex ────────────────────────────────────────────────────────────────

def md_chapters(since):
    """Chapters of Korean-original series published since `since` (aware datetime)."""
    params = [
        ("originalLanguage[]", "ko"),
        ("publishAtSince", since.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")),
        ("order[readableAt]", "desc"),
        ("includes[]", "scanlation_group"),
        ("limit", "100"),
    ]
    params += [("translatedLanguage[]", lang) for lang in config.LANGUAGES]
    params += [("contentRating[]", r) for r in config.CONTENT_RATINGS]

    out, offset = [], 0
    while offset < 2000:
        d = get_json("mangadex", f"{MD}/chapter?" + urllib.parse.urlencode(params + [("offset", offset)]))
        for c in d["data"]:
            a = c["attributes"]
            rel = c["relationships"]
            manga = next((r["id"] for r in rel if r["type"] == "manga"), None)
            if not manga:
                continue
            groups = [r.get("attributes", {}).get("name") for r in rel if r["type"] == "scanlation_group"]
            out.append(
                {
                    "chapter_id": c["id"],
                    "manga_id": manga,
                    "chapter": a.get("chapter") or "",
                    "volume": a.get("volume") or "",
                    "language": a.get("translatedLanguage"),
                    "group": ", ".join(g for g in groups if g),
                    "external_url": a.get("externalUrl"),
                    "readable_at": a["readableAt"],
                }
            )
        offset += len(d["data"])
        if offset >= d["total"] or not d["data"]:
            return out
    return out


def md_manga(ids):
    """Title, links (incl. MangaUpdates / AniList ids) and cover for MangaDex series, keyed by id."""
    out = {}
    ids = sorted(set(ids))
    for i in range(0, len(ids), 100):
        params = [("ids[]", x) for x in ids[i : i + 100]]
        params += [("includes[]", "cover_art"), ("limit", "100")]
        params += [("contentRating[]", r) for r in ["safe", "suggestive", "erotica", "pornographic"]]
        d = get_json("mangadex", f"{MD}/manga?" + urllib.parse.urlencode(params))
        for m in d["data"]:
            a = m["attributes"]
            cover = next(
                (r["attributes"]["fileName"] for r in m["relationships"] if r["type"] == "cover_art" and r.get("attributes")),
                None,
            )
            out[m["id"]] = {
                "title": md_title(a),
                "links": a.get("links") or {},
                "status": a.get("status"),
                "year": a.get("year"),
                "content_rating": a.get("contentRating"),
                "genres": [t["attributes"]["name"]["en"] for t in a.get("tags", []) if t["attributes"]["group"] == "genre"],
                "cover": f"https://uploads.mangadex.org/covers/{m['id']}/{cover}.512.jpg" if cover else None,
            }
    return out


def md_title(attrs):
    """Prefer an English title, then romanized Korean, then whatever exists."""
    titles = [attrs.get("title") or {}] + list(attrs.get("altTitles") or [])
    for lang in ("en", "ko-ro"):
        for t in titles:
            if t.get(lang):
                return t[lang]
    return next((v for t in titles for v in t.values()), "Untitled")


# ── AniList ─────────────────────────────────────────────────────────────────

_AL_FIELDS = """
  id siteUrl title { english romaji } coverImage { large } averageScore popularity genres status
  externalLinks { site url type language }
"""


def al_media(ids):
    """AniList details for these AniList ids, keyed by id."""
    out = {}
    ids = sorted({int(i) for i in ids})
    query = "query ($ids: [Int]) { Page(perPage: 50) { media(id_in: $ids, type: MANGA) {" + _AL_FIELDS + "} } }"
    for i in range(0, len(ids), 50):
        d = get_json("anilist", AL, {"query": query, "variables": {"ids": ids[i : i + 50]}})
        for m in d["data"]["Page"]["media"]:
            out[m["id"]] = m
    return out


def al_trending(n):
    """Korean series trending on AniList right now."""
    query = (
        "query ($n: Int) { Page(perPage: $n) { media(type: MANGA, countryOfOrigin: \"KR\", sort: TRENDING_DESC, isAdult: false) {"
        + _AL_FIELDS
        + "} } }"
    )
    d = get_json("anilist", AL, {"query": query, "variables": {"n": n}})
    return d["data"]["Page"]["media"]
