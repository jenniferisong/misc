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

        need_mu = sorted({u["series"][3:] for u in updates if u["series"].startswith("mu:")} - {k for k, v in mu_info.items() if fresh(v, now)})

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
    else:
        updates = merge.merge_updates(updates, [], now)

    al_ids = {
        md_info[u["md_id"]]["links"]["al"]
        for u in updates
        if u.get("md_id") in md_info and md_info[u["md_id"]].get("links", {}).get("al", "").isdigit()
    }
    al_info = {} if offline else attempt(status, f"AniList details ({len(al_ids)})", lambda: fetch.al_media(al_ids), {})
    trend = [] if offline else attempt(status, "AniList trending", lambda: fetch.al_trending(config.TRENDING_COUNT), [])
    if offline:
        trend = load("trending.json", [])
    else:
        save("trending.json", trend)

    series = merge.build_series(updates, mu_info, md_info, al_info)
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
