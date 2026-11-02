#!/usr/bin/env python3
"""Add openly licensed Wikimedia Commons stills to the Aerial Views feed."""
from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
FEED_PATH = ROOT / "aerial-entries.json"
CACHE_PATH = ROOT / "commons-cache.json"
API_URL = "https://commons.wikimedia.org/w/api.php"
CACHE_TTL = timedelta(days=7)
MAX_PHOTOS = 1200
USER_AGENT = (
    "ProjectivyAerialFeed/1.0 "
    "(https://github.com/thahroba/projectivy-wallpapers)"
)

# Commons only permits freely reusable media. These searches span the user's
# interests; specific commercial characters may not have reusable images.
SEARCHES = [
    ("forest waterfall river", "Nature | Forests and waterfalls"),
    ("ocean coral reef sea", "Nature | Oceans"),
    ("mountain lake landscape", "Nature | Mountains and lakes"),
    ("cat kitten", "Animals | Cats"),
    ("dog puppy", "Animals | Dogs"),
    ("wildlife animal", "Animals | Wildlife"),
    ("bird wildlife", "Animals | Birds"),
    ("Baghdad Iraq Tigris", "Iraq | Baghdad and Tigris"),
    ("Amarah Maysan Iraq", "Iraq | Amarah and Maysan"),
    ("Babylon Iraq ancient", "Civilization | Babylon"),
    ("Mesopotamia archaeology", "Civilization | Mesopotamia"),
    ("Karbala shrine Iraq", "Holy places | Karbala"),
    ("Najaf Imam Ali shrine", "Holy places | Najaf"),
    ("mosque Islamic architecture", "Faith | Mosques and architecture"),
    ("Arabic calligraphy Persian poetry", "Faith | Calligraphy and poetry"),
    ("Muqtada al-Sadr Iraq", "Public figures | Muqtada al-Sadr"),
    ("Saddam Hussein Iraq", "History | Saddam Hussein"),
    ("Farqad al-Qazwini", "Religious figures | Farqad al-Qazwini"),
    ("Kamal al-Haidari", "Religious figures | Kamal al-Haidari"),
    ("Mansur al-Hallaj", "Sufi figures | Al-Hallaj"),
    ("Shams Tabrizi", "Sufi figures | Shams al-Din Tabrizi"),
    ("Ibn Arabi", "Sufi figures | Ibn Arabi"),
    ("Imam Ali calligraphy", "Faith | Imam Ali"),
    ("Barcelona Messi football", "Sports | Barcelona and Messi"),
    ("sports car classic automobile", "Cars | Sports and classic"),
    ("artificial intelligence robotics computer", "Technology | AI and robotics"),
    ("anime manga illustration", "Anime | Illustrations"),
    ("video game console character", "Games | Video games"),
    ("film cinema movie poster", "Film | Cinema"),
    ("romantic couple love", "Love | Romance"),
    ("friendship people", "Friendship"),
    ("city skyline night", "Cities | Night skylines"),
]

def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback

def clean(value: str) -> str:
    value = re.sub(r"<[^>]*>", " ", str(value or ""))
    return " ".join(html.unescape(value).split())

def api_search(query: str) -> list[dict]:
    params = urlencode({
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,
        "gsrlimit": 50,
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": 3840,
        "format": "json",
        "formatversion": 2,
    })
    request = Request(
        API_URL + "?" + params,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"Wikimedia Commons request failed with HTTP {exc.code}.") from None
    except (URLError, TimeoutError, json.JSONDecodeError):
        raise RuntimeError("Could not reach or parse a Wikimedia Commons API response.") from None

    pages = payload.get("query", {}).get("pages", [])
    if isinstance(pages, dict):
        pages = list(pages.values())

    results = []
    for page in pages:
        info_list = page.get("imageinfo") or []
        if not info_list:
            continue
        info = info_list[0]
        mime = info.get("mime", "")
        width = int(info.get("width", 0) or 0)
        height = int(info.get("height", 0) or 0)
        if not mime.startswith("image/") or width < 1920 or height < 1080:
            continue
        if width / height < 1.3:
            continue

        metadata = info.get("extmetadata") or {}
        license_name = clean((metadata.get("LicenseShortName") or {}).get("value", ""))
        license_url = clean((metadata.get("LicenseUrl") or {}).get("value", ""))
        artist = clean((metadata.get("Artist") or {}).get("value", ""))
        if not license_name:
            continue

        results.append({
            "file_title": page.get("title", "").removeprefix("File:").replace("_", " "),
            "source": info.get("descriptionurl", ""),
            "original_url": info.get("url", ""),
            "thumbnail_url": info.get("thumburl", ""),
            "width": width,
            "height": height,
            "author": artist or "Wikimedia Commons contributor",
            "license_name": license_name,
            "license_url": license_url,
        })
    return results

def main() -> int:
    feed = read_json(FEED_PATH, {})
    if not isinstance(feed, dict) or not isinstance(feed.get("assets"), list):
        print("aerial-entries.json is missing its assets array.")
        return 1

    now = datetime.now(timezone.utc)
    cache = read_json(CACHE_PATH, {"queries": {}})
    cached_queries = cache.get("queries", {}) if isinstance(cache, dict) else {}
    fresh_results = {}

    for index, (query, _label) in enumerate(SEARCHES):
        cached = cached_queries.get(query, {})
        try:
            fetched_at = datetime.fromisoformat(cached.get("fetched_at", ""))
        except (TypeError, ValueError):
            fetched_at = datetime.min.replace(tzinfo=timezone.utc)

        if now - fetched_at < CACHE_TTL and isinstance(cached.get("hits"), list) and cached.get("hits"):
            fresh_results[query] = cached["hits"]
            continue

        hits = api_search(query)
        fresh_results[query] = hits
        cached_queries[query] = {"fetched_at": now.isoformat(), "hits": hits}
        print(f"Fetched Commons photos for: {query}")
        if index < len(SEARCHES) - 1:
            time.sleep(1)

    photos = [
        photo for photo in feed.get("photos", [])
        if photo.get("provider") != "Wikimedia Commons"
    ]
    seen_urls = {
        photo.get("url-4K") or photo.get("url-1080")
        for photo in photos
        if photo.get("url-4K") or photo.get("url-1080")
    }
    for query, label in SEARCHES:
        for hit in fresh_results.get(query, []):
            if len(photos) >= MAX_PHOTOS:
                break
            chosen = hit.get("thumbnail_url") if hit.get("width", 0) >= 3840 else hit.get("original_url")
            if not chosen or chosen in seen_urls:
                continue
            title = f"{label} | {hit.get('file_title', 'Commons photo')}"
            photo = {
                "title": title[:220],
                "source": hit.get("source", ""),
                "author": hit.get("author", ""),
                "license": hit.get("license_url", ""),
                "license_name": hit.get("license_name", ""),
                "provider": "Wikimedia Commons",
            }
            if hit.get("width", 0) >= 3840 and hit.get("thumbnail_url"):
                photo["url-4K"] = hit["thumbnail_url"]
            else:
                photo["url-1080"] = hit.get("original_url", "")
            if not photo.get("url-4K") and not photo.get("url-1080"):
                continue
            photos.append(photo)
            seen_urls.add(chosen)

    feed["photos"] = photos
    FEED_PATH.write_text(
        json.dumps(feed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    CACHE_PATH.write_text(
        json.dumps({"queries": cached_queries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    commons_count = sum(1 for photo in photos if photo.get("provider") == "Wikimedia Commons")
    print(f"Aerial Views feed now has {len(feed['assets'])} videos and {commons_count} Commons photos.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
