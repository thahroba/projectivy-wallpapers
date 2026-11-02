#!/usr/bin/env python3
"""Build a Projectivy-compatible wallpaper list from Pixabay's video API.

The script makes one request per search term, keeps the API responses in a
24-hour cache, and never downloads the video files themselves.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "wallpapers.json"
AERIAL_PATH = ROOT / "aerial-entries.json"
CACHE_PATH = ROOT / "pixabay-cache.json"
API_URL = "https://pixabay.com/api/videos/"
API_KEY = os.environ.get("PIXABAY_API_KEY", "").strip()
MAX_ITEMS = 1000
AERIAL_MAX_ITEMS = 5000
CACHE_TTL = timedelta(hours=24)

# Wide, safe-for-work search terms cover the topics requested. Pixabay has
# stock footage rather than licensed footage from specific games or shows.
SEARCHES = [
    ("forest waterfall river", "طبيعة | غابات وشلالات"),
    ("ocean waves sea", "طبيعة | البحار والمحيطات"),
    ("mountain lake nature", "طبيعة | جبال وبحيرات"),
    ("cat kitten", "حيوانات | قطط"),
    ("dog puppy", "حيوانات | كلاب"),
    ("wildlife animals", "حيوانات | حياة برية"),
    ("city skyline night", "مدن | مشاهد ليلية"),
    ("Baghdad Iraq river", "العراق | بغداد"),
    ("ancient ruins archaeology", "حضارة | آثار قديمة"),
    ("mosque shrine architecture", "أماكن مقدسة | عمارة دينية"),
    ("technology artificial intelligence", "تقنية | ذكاء اصطناعي"),
    ("sports car supercar", "سيارات | رياضية"),
    ("football soccer", "رياضة | كرة القدم"),
    ("romance love roses", "حب | رومانسية"),
    ("friends friendship", "صداقة"),
    ("space galaxy", "فضاء"),
    ("anime animation", "أنمي | رسوم متحركة"),
    ("video games gaming", "ألعاب | ألعاب فيديو"),
    ("rain window cozy", "طبيعة | أجواء المطر"),
    ("sunset beach", "طبيعة | غروب وشواطئ"),
]

def read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback

def api_search(query: str) -> dict:
    params = urlencode({
        "key": API_KEY,
        "q": query,
        "per_page": 200,
        "safesearch": "true",
        "order": "popular",
    })
    request = Request(
        API_URL + "?" + params,
        headers={"User-Agent": "ProjectivyWallpaperFeed/1.0"},
    )
    try:
        with urlopen(request, timeout=40) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"Pixabay request failed with HTTP {exc.code}. Check the API key and quota.") from None
    except (URLError, TimeoutError, json.JSONDecodeError):
        raise RuntimeError("Could not reach or parse a Pixabay API response. Try again later.") from None
    return payload

def main() -> int:
    if not API_KEY:
        print("Missing PIXABAY_API_KEY. Add it as a GitHub Actions repository secret.")
        return 1

    now = datetime.now(timezone.utc)
    cache = read_json(CACHE_PATH, {"queries": {}})
    cached_queries = cache.get("queries", {}) if isinstance(cache, dict) else {}
    fresh_results: dict[str, list] = {}

    for index, (query, _location) in enumerate(SEARCHES):
        cached = cached_queries.get(query, {})
        try:
            fetched_at = datetime.fromisoformat(cached.get("fetched_at", ""))
        except (TypeError, ValueError):
            fetched_at = datetime.min.replace(tzinfo=timezone.utc)

        if now - fetched_at < CACHE_TTL and isinstance(cached.get("hits"), list):
            fresh_results[query] = cached["hits"]
            continue

        payload = api_search(query)
        hits = payload.get("hits", [])
        if not isinstance(hits, list):
            hits = []
        cached_queries[query] = {
            "fetched_at": now.isoformat(),
            "hits": hits,
        }
        fresh_results[query] = hits
        print(f"Fetched Pixabay results for: {query}")
        if index < len(SEARCHES) - 1:
            time.sleep(1)

    # Preserve hand-curated entries, replacing only generated Pixabay rows.
    manifest = read_json(MANIFEST_PATH, [])
    if not isinstance(manifest, list):
        print("wallpapers.json is not a JSON array.")
        return 1
    output = [item for item in manifest if item.get("provider") != "Pixabay"]

    seen_ids: set[str] = set()
    for query, location in SEARCHES:
        for hit in fresh_results.get(query, []):
            video_id = str(hit.get("id", ""))
            if not video_id or video_id in seen_ids:
                continue

            renditions = hit.get("videos", {})
            large = renditions.get("large", {}) if isinstance(renditions, dict) else {}
            medium = renditions.get("medium", {}) if isinstance(renditions, dict) else {}
            large_url = large.get("url", "") if isinstance(large, dict) else ""
            medium_url = medium.get("url", "") if isinstance(medium, dict) else ""
            large_width = int(large.get("width", 0) or 0) if isinstance(large, dict) else 0
            medium_width = int(medium.get("width", 0) or 0) if isinstance(medium, dict) else 0

            # Keep landscape footage at 4K or Full HD; skip phone and low-res clips.
            if large_width >= 3840 and large_url:
                url_key, video_url, resolution = "url_4k", large_url, f"{large_width}x{large.get('height', 0)}"
            elif medium_width >= 1920 and medium_url:
                url_key, video_url, resolution = "url_1080p", medium_url, f"{medium_width}x{medium.get('height', 0)}"
            else:
                continue

            width = large_width or medium_width
            height = int((large if large_width >= 3840 else medium).get("height", 0) or 0)
            if not width or not height or width / height < 1.3:
                continue

            tags = [part.strip() for part in str(hit.get("tags", "")).split(",") if part.strip()]
            title = " · ".join(tags[:5]) or f"Pixabay video {video_id}"
            entry = {
                "location": location,
                "title": title,
                "author": str(hit.get("user", "Pixabay creator")),
                "source": str(hit.get("pageURL", "")),
                "license": "https://pixabay.com/service/license-summary/",
                "provider": "Pixabay",
                "pixabay_id": video_id,
                "resolution": resolution,
                url_key: video_url,
            }

            # Offer Full HD fallback when the API provides it.
            if url_key == "url_4k" and medium_width >= 1920 and medium_url:
                entry["url_1080p"] = medium_url
            seen_ids.add(video_id)
            output.append(entry)

    aerial_assets = []
    for index, item in enumerate(output[:AERIAL_MAX_ITEMS], start=1):
        video_4k = item.get("url_4k")
        video_1080p = item.get("url_1080p")
        if not video_4k and not video_1080p:
            continue
        label_parts = [str(item.get(key, "")).strip() for key in ("location", "title", "author")]
        label = " — ".join(part for part in label_parts if part)
        asset = {
            "id": f"projectivy-wallpaper-{index:04d}",
            "accessibilityLabel": label or f"Video {index}",
            "type": "aerial",
        }
        if video_1080p:
            asset["url-1080-SDR"] = video_1080p
        if video_4k:
            asset["url-4K-SDR"] = video_4k
        aerial_assets.append(asset)

    AERIAL_PATH.write_text(
        json.dumps({"assets": aerial_assets}, ensure_ascii=False, indent=2) + "\\n",
        encoding="utf-8",
    )

    CACHE_PATH.write_text(
        json.dumps({"queries": cached_queries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    MANIFEST_PATH.write_text(
        json.dumps(output[:MAX_ITEMS], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    pixabay_count = sum(1 for item in output[:MAX_ITEMS] if item.get("provider") == "Pixabay")
    print(f"Wallpaper list now has {min(len(output), MAX_ITEMS)} entries ({pixabay_count} from Pixabay).")
    print(f"Aerial Views feed now has {len(aerial_assets)} entries.")
    if len(output) < MAX_ITEMS:
        print("Pixabay returned fewer than 1000 eligible unique clips; the script did not create duplicates.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
