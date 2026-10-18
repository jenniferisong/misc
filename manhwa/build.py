"""Fetch new manhwa updates, merge them with the cache, and write the site to _site/.

    python build.py            # fetch + build
    python build.py --offline  # rebuild the site from data/ without fetching

data/ holds the cache between runs (on GitHub Actions it's kept with
actions/cache): recent updates, plus series details that rarely change.
A source that's down is skipped and noted on the page; the others still update.
"""

import argparse
import datetime as dt
import json
import shutil
import sys
import traceback
from pathlib import Path

import config
import fetch
import merge

HERE = Path(__file__).parent
DATA = HERE / "data"
OUT = HERE / "_site"


def load(name, default):
    path = DATA / name
    return json.loads(path.read_text()) if path.exists() else default


def save(name, value):
    DATA.mkdir(exist_ok=True)
    (DATA / name).write_text(json.dumps(value, ensure_ascii=False, indent=1))


def fresh(entry, now):
    return entry and now - merge.parse_time(entry["fetched"]) < dt.timedelta(days=config.SERIES_CACHE_DAYS)


def attempt(status, name, fn, default):
    print(f"{name}...")
    try:
        result = fn()
        status[name] = "ok"
        return result
    except Exception as e:  # one broken source shouldn't stop the others
        traceback.print_exc()
        status[name] = f"failed: {type(e).__name__}"
        return default


def run(offline):
    now = dt.datetime.now(dt.timezone.utc)
    stamp = merge.iso(now)
    updates = load("updates.json", [])
    mu_info = load("mu_series.json", {})
    md_info = load("md_manga.json", {})
    al_match = load("al_match.json", {})
    status = {}

    if not offline:
        # Backfill the whole window when the cache is empty; afterwards the newest page is enough.
        pages = 1 if updates else -(-config.KEEP_DAYS // 2)
        releases = attempt(status, "MangaUpdates releases", lambda: fetch.mu_releases(pages), [])
        since = now - dt.timedelta(hours=config.MANGADEX_LOOKBACK_HOURS)
        chapters = attempt(status, "MangaDex chapters", lambda: fetch.md_chapters(since), [])

        need_md = {c["manga_id"] for c in chapters if not fresh(md_info.get(c["manga_id"]), now)}
        got = attempt(status, f"MangaDex series ({len(need_md)})", lambda: fetch.md_manga(need_md), {})
        md_info.update({k: {**v, "fetched": stamp} for k, v in got.items()})

        new = merge.updates_from_mu(releases) + merge.updates_from_md(chapters, md_info)
        updates = merge.merge_updates(updates, new, now)

        # Series not looked up yet stay hidden (their type is unknown). The cap keeps
        # a cold start inside the Action's time limit; the rest follow on later runs.
        known = {k for k, v in mu_info.items() if fresh(v, now)}
        need_mu = [s for s in dict.fromkeys(u["series"][3:] for u in updates if u["series"].startswith("mu:")) if s not in known]
        if len(need_mu) > config.MAX_SERIES_LOOKUPS:
            print(f"  {len(need_mu) - config.MAX_SERIES_LOOKUPS} series left for the next run")
            need_mu = need_mu[: config.MAX_SERIES_LOOKUPS]

        def fetch_mu():
            for i, sid in enumerate(need_mu, 1):
                info = fetch.mu_series(sid)
                mu_info[sid] = {**(info or {"type": None}), "fetched": stamp}
                if i % 50 == 0:
                    print(f"  {i}/{len(need_mu)}")
                    save("mu_series.json", mu_info)  # keep progress if the run is cut short

        attempt(status, f"MangaUpdates series ({len(need_mu)})", fetch_mu, None)
        save("updates.json", updates)
        save("mu_series.json", mu_info)
        save("md_manga.json", md_info)

        # MangaUpdates series that MangaDex doesn't link to AniList: find them by title.
        have_al = {u["series"] for u in updates if (md_info.get(u.get("md_id")) or {}).get("links", {}).get("al")}
        to_search = [
            s[3:]
            for s in dict.fromkeys(u["series"] for u in updates)
            if s.startswith("mu:") and s not in have_al and (mu_info.get(s[3:]) or {}).get("type") in config.SERIES_TYPES
            and not fresh(al_match.get(s[3:]), now)
        ][: config.MAX_ANILIST_SEARCHES]

        def search_al():
            names = [mu_info[sid].get("names") or [mu_info[sid]["title"]] for sid in to_search]
            for sid, n, found in zip(to_search, names, fetch.al_search([n[0] for n in names])):
                al_match[sid] = {"al": merge.pick_anilist(n, found), "fetched": stamp}

        attempt(status, f"AniList title search ({len(to_search)})", search_al, None)
        save("al_match.json", al_match)

        al_ids = {
            merge.anilist_id(u["series"], md_info.get(u.get("md_id")), al_match) for u in updates
        } - {None}
        al_info = attempt(status, f"AniList details ({len(al_ids)})", lambda: fetch.al_media(al_ids), {})
        trend = attempt(status, "AniList trending", lambda: fetch.al_trending(config.TRENDING_COUNT), [])
        save("al_media.json", al_info)
        save("trending.json", trend)
    else:
        updates = merge.merge_updates(updates, [], now)
        al_info = {int(k): v for k, v in load("al_media.json", {}).items()}
        trend = load("trending.json", [])

    series = merge.build_series(updates, mu_info, md_info, al_info, al_match)
    OUT.mkdir(exist_ok=True)
    shutil.copy(HERE / "site" / "index.html", OUT / "index.html")
    (OUT / "data.json").write_text(
        json.dumps(
            {"updated": stamp, "keep_days": config.KEEP_DAYS, "sources": status, "series": series, "trending": merge.trending(trend)},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    print(f"\n{len(series)} series, {len(updates)} updates -> {OUT}")
    for name, s in status.items():
        print(f"  {name}: {s}")
    return 1 if status and all(s != "ok" for s in status.values()) else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--offline", action="store_true", help="rebuild from data/ without fetching")
    sys.exit(run(p.parse_args().offline))
