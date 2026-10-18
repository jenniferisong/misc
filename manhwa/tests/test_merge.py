"""Checks the merge logic on small hand-made inputs (no network)."""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import merge  # noqa: E402

NOW = dt.datetime(2026, 10, 18, 12, tzinfo=dt.timezone.utc)


def mu_release(series_id, chapter, group, hours_ago=1):
    return {
        "series_id": series_id,
        "series_title": f"Series {series_id}",
        "series_url": f"https://www.mangaupdates.com/series/{series_id}",
        "chapter": chapter,
        "volume": "",
        "group": group,
        "group_url": f"https://www.mangaupdates.com/group/{group}",
        "timestamp": (NOW - dt.timedelta(hours=hours_ago)).timestamp(),
    }


def md_chapter(manga_id, chapter, group="Scans", external=None, hours_ago=1):
    return {
        "chapter_id": f"c-{manga_id}-{chapter}",
        "manga_id": manga_id,
        "chapter": chapter,
        "volume": "",
        "language": "en",
        "group": group,
        "external_url": external,
        "readable_at": merge.iso(NOW - dt.timedelta(hours=hours_ago)),
    }


def test_mu_id_decodes_base36_and_rejects_legacy_ids():
    assert merge.mu_id("3jj07ch") == 7711126577
    assert merge.mu_id("12345") is None  # retired numeric id
    assert merge.mu_id("") is None
    assert merge.mu_id(None) is None


def test_mangadex_chapter_joins_mangaupdates_series_by_id():
    md_info = {"md-a": {"title": "A", "links": {"mu": "3jj07ch", "al": "42"}}, "md-b": {"title": "B", "links": {}}}
    ups = merge.updates_from_md([md_chapter("md-a", "5"), md_chapter("md-b", "1")], md_info)
    assert ups[0]["series"] == "mu:7711126577"
    assert ups[1]["series"] == "md:md-b"


def test_official_chapter_links_to_publisher_and_is_labeled():
    [u] = merge.updates_from_md([md_chapter("m", "3", group="", external="https://tapas.io/ep/1")], {})
    assert u["url"] == "https://tapas.io/ep/1"
    assert u["group"] == "Official"


def test_merge_drops_duplicates_and_old_entries():
    a = merge.updates_from_mu([mu_release(1, "10", "G", hours_ago=2)])
    a_again = merge.updates_from_mu([mu_release(1, "10", "g", hours_ago=1)])  # same release re-listed
    old = merge.updates_from_mu([mu_release(1, "1", "G", hours_ago=24 * 30)])
    merged = merge.merge_updates(a + old, a_again, NOW)
    assert len(merged) == 1
    assert merged[0]["time"] == a[0]["time"]  # earliest kept


def test_only_manhwa_kept_from_mangaupdates():
    ups = merge.updates_from_mu([mu_release(1, "5", "G"), mu_release(2, "5", "G")])
    mu_info = {"1": {"type": "Manhwa", "title": "Korean one"}, "2": {"type": "Manga", "title": "Japanese one"}}
    series = merge.build_series(ups, mu_info, {}, {})
    assert [s["title"] for s in series] == ["Korean one"]


def test_same_chapter_from_two_sites_becomes_one_row():
    md_info = {"md-a": {"title": "A", "links": {"mu": "1"}}}  # "1" is all digits -> legacy, not joined
    md_info["md-b"] = {"title": "B", "links": {"mu": "a"}}  # base 36 "a" == 10
    ups = merge.updates_from_mu([mu_release(10, "7", "LINE Webtoon")]) + merge.updates_from_md(
        [md_chapter("md-b", "7", group="Fan TL"), md_chapter("md-b", "6")], md_info
    )
    [s] = merge.build_series(ups, {"10": {"type": "Manhwa", "title": "B (MU)"}}, md_info, {})
    assert [c["chapter"] for c in s["chapters"]] == ["7", "6"]
    assert {r["group"] for r in s["chapters"][0]["releases"]} == {"LINE Webtoon", "Fan TL"}
    assert s["title"] == "B (MU)"
    assert set(s["links"]) == {"MangaDex"}  # no MangaUpdates url in this mu_info


def test_anilist_supplies_title_cover_and_official_links():
    md_info = {"m": {"title": "Romanized", "links": {"al": "99", "engtl": "https://webtoons.com/x"}, "cover": "md.jpg"}}
    al_info = {
        99: {
            "title": {"english": "English Title"},
            "coverImage": {"large": "al.jpg"},
            "siteUrl": "https://anilist.co/manga/99",
            "genres": ["Action"],
            "externalLinks": [
                {"site": "KakaoPage", "url": "https://page.kakao.com/s", "type": "STREAMING", "language": "Korean"},
                {"site": "Tapas","url": "https://tapas.io/s", "type": "STREAMING", "language": "English"},
                {"site": "Piccoma", "url": "https://piccoma.com/s", "type": "STREAMING", "language": "Japanese"},
                {"site": "Twitter", "url": "https://x.com/s", "type": "SOCIAL", "language": None},
            ],
        }
    }
    [s] = merge.build_series(merge.updates_from_md([md_chapter("m", "2")], md_info), {}, md_info, al_info)
    assert s["title"] == "English Title"
    assert s["cover"] == "al.jpg"
    assert [link["site"] for link in s["official"]] == ["Official English", "Tapas", "KakaoPage"]
    assert s["is_new"]


def test_chapters_sorted_newest_number_first_and_new_series_flag():
    ups = merge.updates_from_mu([mu_release(1, "9", "G", 5), mu_release(1, "10.5", "G", 1), mu_release(1, "", "G", 3)])
    [s] = merge.build_series(ups, {"1": {"type": "Manhwa", "title": "T"}}, {}, {})
    assert [c["chapter"] for c in s["chapters"]] == ["10.5", "9", ""]
    assert not s["is_new"]


def test_anilist_title_match_is_exact_and_korean_only():
    found = [
        {"id": 1, "countryOfOrigin": "JP", "title": {"english": "The Boxer"}, "synonyms": []},
        {"id": 2, "countryOfOrigin": "KR", "title": {"english": "The Boxer 2"}, "synonyms": []},
        {"id": 3, "countryOfOrigin": "KR", "title": {"english": None, "romaji": "Deo Bokseo"}, "synonyms": ["the boxer!"]},
    ]
    assert merge.pick_anilist(["The Boxer"], found) == 3  # via synonym, punctuation ignored
    assert merge.pick_anilist(["Boxer"], found) is None
    assert merge.pick_anilist(["Other name", "Deo Bokseo"], found) == 3  # any MangaUpdates alt title works


def test_title_search_match_supplies_official_links():
    ups = merge.updates_from_mu([mu_release(5, "20", "Asura")])
    mu_info = {"5": {"type": "Manhwa", "title": "T"}}
    al_info = {77: {"title": {"english": "T"}, "externalLinks": [{"site": "WEBTOON", "url": "https://webtoons.com/t", "type": "STREAMING", "language": "English"}]}}
    [s] = merge.build_series(ups, mu_info, {}, al_info, {"5": {"al": 77}})
    assert s["official"] == [{"site": "WEBTOON", "url": "https://webtoons.com/t"}]


def test_status_is_shortened():
    assert merge.short_status("**S1:** 42 Chapters (001-042) **S2:** 37 Chapters (Ongoing) 121~") == "Ongoing"
    assert merge.short_status("110 Chapters (Complete)") == "Completed"
    assert merge.short_status("Season 2 on hiatus") == "Hiatus"
    assert merge.short_status("ongoing") == "Ongoing"  # MangaDex style
    assert merge.short_status("75 Chapters", completed=True) == "Completed"
    assert merge.short_status(None) is None
