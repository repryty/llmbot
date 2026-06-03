from collections import defaultdict
from typing import Optional
import httpx

DANBOORU_BASE = "https://danbooru.donmai.us"

_CAT_FIELDS: dict[str, tuple[str, ...]] = {
    "general": ("tag_string_general",),
    "style": ("tag_string_character", "tag_string_copyright", "tag_string_artist"),
    "meta": ("tag_string_meta",),
}


async def fetch_tag_frequencies(
    artist: str,
    max_pages: int = 3,
    login: Optional[str] = None,
    api_key: Optional[str] = None,
) -> tuple[dict[str, dict[str, int]], int]:
    """
    Fetch up to max_pages×200 posts for an artist and return tag counts by category.

    Returns (counts, total_posts) where counts is:
        {"general": {tag: n}, "style": {tag: n}, "meta": {tag: n}}
    """
    counts: dict[str, defaultdict[str, int]] = {
        "general": defaultdict(int),
        "style": defaultdict(int),
        "meta": defaultdict(int),
    }
    total_posts = 0

    params_base: dict = {"tags": f"artist:{artist}", "limit": 200}
    if login and api_key:
        params_base["login"] = login
        params_base["api_key"] = api_key

    async with httpx.AsyncClient(timeout=30.0) as client:
        for page in range(1, max_pages + 1):
            resp = await client.get(
                f"{DANBOORU_BASE}/posts.json",
                params={**params_base, "page": page},
            )
            resp.raise_for_status()
            posts = resp.json()
            if not posts:
                break

            for post in posts:
                if post.get("is_deleted") or post.get("is_banned"):
                    continue
                total_posts += 1
                for cat, fields in _CAT_FIELDS.items():
                    for field in fields:
                        for tag in post.get(field, "").split():
                            counts[cat][tag] += 1

            if len(posts) < 200:
                break

    return {cat: dict(d) for cat, d in counts.items()}, total_posts
