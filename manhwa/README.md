# Manhwa Updates

**Live site: https://jenniferisong.github.io/misc/** (once GitHub Pages is on, see below)

One page that shows every new manhwa chapter from the last two weeks, collected
from three sites and refreshed every 3 hours by a GitHub Action. It's built the
same way as [korea-chips](https://github.com/jenniferisong/korea-chips).

## Where the data comes from

| Source | What it adds |
|---|---|
| [MangaUpdates](https://www.mangaupdates.com/releases.html) | Every chapter release it logs, from official publishers (LINE Webtoon, Tapas…) and scanlation groups. Also each series' type, genres, cover and rating. |
| [MangaDex](https://mangadex.org) | New English chapters of Korean-original series, with links to read them. |
| [AniList](https://anilist.co) | Official places to read each series (Webtoon, Tapas, Kakao, Naver…), scores, and the "Trending" row. |

The sites are matched by ID where possible: MangaDex stores each series'
MangaUpdates and AniList IDs. Otherwise a series is looked up on AniList by its
MangaUpdates titles, and only an exact title match with a Korean series is used. When two groups release the same chapter, it shows
as one row with both links. The orange **Read on …** buttons go to official
publishers.

## Using the site

- **☆** follows a series. The **Following** tab then shows just those series.
  Follows are saved in your browser.
- **New series** shows series whose updates include chapter 3 or lower, so
  recently started ones.
- Search matches titles and group names. You can also filter by genre and by
  how recent the update is.

## Files

| File | What it does |
|---|---|
| `config.py` | Settings: how many days to keep, languages, content ratings, series types (add `"Manhua"` / `"Manga"` to track those too). |
| `fetch.py` | Calls the three APIs (free, no keys). |
| `merge.py` | Joins the sources into one list of series and chapters. |
| `build.py` | Runs the fetch, keeps a cache in `data/`, and writes the site to `_site/`. |
| `site/index.html` | The page; draws everything from `data.json`. |
| `tests/` | Checks the merge logic on small hand-made data. |

## Run it yourself

```
cd manhwa
python build.py                         # first runs ~30 min each while series details fill in; then ~2 min
python -m http.server -d _site 8000     # open http://localhost:8000
python -m pytest -q tests               # pip install pytest
```

## Turning on the live site

In the `misc` repo on GitHub: **Settings → Pages → Build and deployment →
Source: GitHub Actions**. Then run the workflow under **Actions → Update manhwa
tracker → Run workflow**. It starts from `main`, so merge this branch first.
