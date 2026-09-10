"""iTunes Search and Lookup API client for podcast discovery."""

from __future__ import annotations

import logging
from typing import Any, Optional, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"
DEFAULT_USER_AGENT = "podcast-ctl/0.1.0"


class PodcastSearchResult(BaseModel):
    """Normalized podcast search result from Apple Podcasts / iTunes API."""

    model_config = ConfigDict(extra="ignore")

    collection_id: Union[int, str] = Field(..., description="Unique iTunes collection or podcast ID")
    title: str = Field(..., description="Podcast show title")
    author: str = Field(default="", description="Podcast author / artist name")
    feed_url: Optional[str] = Field(default=None, description="Direct RSS feed URL")
    artwork_url: Optional[str] = Field(default=None, description="Artwork image URL")
    episode_count: int = Field(default=0, description="Total episode count")
    genres: list[str] = Field(default_factory=list, description="List of genre names")
    country: Optional[str] = Field(default=None, description="Country code (e.g., USA)")
    release_date: Optional[str] = Field(default=None, description="Latest release date string")


# Alias for backward/naming compatibility
ItunesPodcast = PodcastSearchResult


def _parse_itunes_item(item: dict[str, Any]) -> PodcastSearchResult:
    """Parse a single raw iTunes API item dictionary into a PodcastSearchResult model."""
    collection_id = item.get("collectionId") or item.get("trackId") or ""
    title = item.get("collectionName") or item.get("trackName") or ""
    author = item.get("artistName") or ""
    feed_url = item.get("feedUrl")

    artwork_url = (
        item.get("artworkUrl600")
        or item.get("artworkUrl100")
        or item.get("artworkUrl60")
        or item.get("artworkUrl30")
    )
    episode_count = int(item.get("trackCount") or 0)

    genres = item.get("genres")
    if not genres and item.get("primaryGenreName"):
        genres = [item["primaryGenreName"]]
    elif not genres:
        genres = []

    return PodcastSearchResult(
        collection_id=collection_id,
        title=title,
        author=author,
        feed_url=feed_url,
        artwork_url=artwork_url,
        episode_count=episode_count,
        genres=genres,
        country=item.get("country"),
        release_date=item.get("releaseDate"),
    )


def search_itunes(
    query: str,
    limit: int = 10,
    client: Optional[httpx.Client] = None,
    timeout: float = 10.0,
) -> list[PodcastSearchResult]:
    """Search Apple Podcasts via iTunes Search API.

    Args:
        query: Podcast title, topic, or author search term.
        limit: Maximum number of results to return (default: 10).
        client: Optional pre-configured httpx.Client (useful for testing or session pooling).
        timeout: Request timeout in seconds.

    Returns:
        List of matching PodcastSearchResult objects.
    """
    if not query or not query.strip():
        return []

    params: dict[str, Any] = {
        "term": query.strip(),
        "media": "podcast",
        "entity": "podcast",
        "limit": max(1, min(limit, 200)),
    }
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"}

    try:
        if client is not None:
            resp = client.get(ITUNES_SEARCH_URL, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
        else:
            with httpx.Client(timeout=timeout, follow_redirects=True) as http_client:
                resp = http_client.get(ITUNES_SEARCH_URL, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()

        results: list[PodcastSearchResult] = []
        for item in data.get("results", []):
            if isinstance(item, dict):
                results.append(_parse_itunes_item(item))
        return results

    except Exception as exc:
        logger.warning("iTunes search failed for query %r: %s", query, exc)
        return []


def lookup_itunes(
    collection_id: Union[int, str],
    client: Optional[httpx.Client] = None,
    timeout: float = 10.0,
) -> Optional[PodcastSearchResult]:
    """Lookup a single podcast by its iTunes collection ID.

    Args:
        collection_id: iTunes collection/track ID.
        client: Optional httpx.Client.
        timeout: Request timeout in seconds.

    Returns:
        PodcastSearchResult if found, None otherwise.
    """
    if not collection_id:
        return None

    params = {"id": str(collection_id)}
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"}

    try:
        if client is not None:
            resp = client.get(ITUNES_LOOKUP_URL, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
        else:
            with httpx.Client(timeout=timeout, follow_redirects=True) as http_client:
                resp = http_client.get(ITUNES_LOOKUP_URL, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()

        results = data.get("results", [])
        if results and isinstance(results[0], dict):
            return _parse_itunes_item(results[0])
        return None

    except Exception as exc:
        logger.warning("iTunes lookup failed for ID %r: %s", collection_id, exc)
        return None


# Convenient aliases
search_podcast = search_itunes
lookup_podcast = lookup_itunes
