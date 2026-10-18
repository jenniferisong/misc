"""What the manhwa tracker collects. fetch.py and build.py read everything from here."""

# How many days of updates the site shows. The first run backfills this many
# days from MangaUpdates; after that, updates build up in the cache in data/.
# (MangaDex is only read MANGADEX_LOOKBACK_HOURS back, so its history builds up over time.)
KEEP_DAYS = 14

# How far back to read MangaDex's chapter feed on each run.
MANGADEX_LOOKBACK_HOURS = 48

# MangaDex chapters translated into these languages count as updates.
LANGUAGES = ["en"]

# MangaDex content ratings to include. Add "erotica" / "pornographic" if you want them.
CONTENT_RATINGS = ["safe", "suggestive"]

# MangaUpdates series types that count as manhwa. ("Manhua" is Chinese,
# "Manga" Japanese; add them here to track those too.)
SERIES_TYPES = ["Manhwa"]

# How many trending Korean series to pull from AniList.
TRENDING_COUNT = 24

# Seconds to wait between calls to the same API, to stay well under rate limits.
PAUSE_SECONDS = {"mangaupdates": 1.0, "mangadex": 0.3, "anilist": 1.0}

# How long cached series details (type, genres, cover) are trusted before re-fetching.
SERIES_CACHE_DAYS = 30

USER_AGENT = "manhwa-updates/1.0 (+https://github.com/jenniferisong/misc)"
