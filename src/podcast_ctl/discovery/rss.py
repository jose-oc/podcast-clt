"""RSS and Podcasting 2.0 Feed Parser for podcast metadata and transcript discovery."""

from __future__ import annotations

import logging
import re
from typing import Any

import defusedxml.ElementTree as ET
import feedparser
import httpx
from pydantic import BaseModel, ConfigDict, Field

from podcast_ctl.models.transcript import EpisodeMetadata

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "podcast-ctl/0.2.1"

# ISO 8601 Duration regex: e.g. PT1H30M15S, PT45M, PT30S
ISO_DURATION_REGEX = re.compile(
    r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?$",
    re.IGNORECASE,
)


class ShowMetadata(BaseModel):
    """Metadata describing a podcast series/channel extracted from an RSS feed."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(..., description="Podcast show title")
    description: str | None = Field(default=None, description="Show description or summary")
    feed_url: str | None = Field(default=None, description="Direct RSS feed URL")
    link: str | None = Field(default=None, description="Show website or homepage link")
    author: str | None = Field(default=None, description="Author / host / publisher")
    image_url: str | None = Field(default=None, description="Artwork image URL")
    language: str | None = Field(default=None, description="Feed primary language")
    total_episodes: int = Field(default=0, description="Total number of parsed episodes")


def parse_duration(duration_raw: Any) -> float | None:
    """Parse various duration formats into total seconds (float).

    Supported formats:
        - Numeric seconds: 1800, 1800.5, "1800", "1800.5"
        - Colon-separated time: "HH:MM:SS", "H:MM:SS", "MM:SS", "M:SS", "DD:HH:MM:SS"
        - Millisecond fractional colons: "01:15:30.500"
        - ISO 8601 duration: "PT1H30M15S", "PT45M"

    Returns:
        Duration in seconds as a float, or None if invalid or empty.
    """
    if duration_raw is None:
        return None

    if isinstance(duration_raw, (int, float)):
        val = float(duration_raw)
        return val if val >= 0 else None

    if not isinstance(duration_raw, str):
        return None

    raw = duration_raw.strip()
    if not raw:
        return None

    # Try ISO 8601 duration (e.g. PT1H23M45S)
    if raw.upper().startswith("PT"):
        match = ISO_DURATION_REGEX.match(raw.upper())
        if match:
            h = float(match.group("hours") or 0)
            m = float(match.group("minutes") or 0)
            s = float(match.group("seconds") or 0)
            return h * 3600.0 + m * 60.0 + s

    # Colon-separated time (HH:MM:SS or MM:SS)
    if ":" in raw:
        parts = raw.split(":")
        try:
            if len(parts) == 2:  # MM:SS
                minutes = float(parts[0])
                seconds = float(parts[1])
                return max(0.0, minutes * 60.0 + seconds)
            elif len(parts) == 3:  # HH:MM:SS
                hours = float(parts[0])
                minutes = float(parts[1])
                seconds = float(parts[2])
                return max(0.0, hours * 3600.0 + minutes * 60.0 + seconds)
            elif len(parts) == 4:  # DD:HH:MM:SS
                days = float(parts[0])
                hours = float(parts[1])
                minutes = float(parts[2])
                seconds = float(parts[3])
                return max(0.0, days * 86400.0 + hours * 3600.0 + minutes * 60.0 + seconds)
        except (ValueError, TypeError):
            return None

    # Plain seconds string
    try:
        val = float(raw)
        return val if val >= 0 else None
    except (ValueError, TypeError):
        return None


def _get_local_tag(tag: str) -> str:
    """Extract local element tag name ignoring XML namespace."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _extract_podcast_transcripts(item_element: ET.Element) -> list[dict[str, Any]]:
    """Extract Podcasting 2.0 <podcast:transcript> tags from an XML item element."""
    transcripts: list[dict[str, Any]] = []

    for child in item_element:
        local_tag = _get_local_tag(child.tag).lower()
        if local_tag == "transcript":
            url = (child.attrib.get("url") or "").strip()
            mime_type = (child.attrib.get("type") or "").strip()
            language = child.attrib.get("language") or child.attrib.get("lang")
            rel = child.attrib.get("rel")

            if url:
                entry: dict[str, Any] = {
                    "url": url,
                    "type": mime_type or "text/vtt",
                }
                if language:
                    entry["language"] = language.strip()
                if rel:
                    entry["rel"] = rel.strip()
                transcripts.append(entry)

    return transcripts


def _parse_xml_element_tree(
    xml_content: str, feed_url: str | None = None
) -> tuple[ShowMetadata, list[EpisodeMetadata]]:
    """Parse RSS feed XML content using defusedxml ElementTree."""
    root = ET.fromstring(xml_content.encode("utf-8") if isinstance(xml_content, str) else xml_content)
    root_tag = _get_local_tag(root.tag).lower()

    # Handle standard RSS (<rss><channel>...</channel></rss>) or Atom (<feed>...)
    channel: ET.Element | None = None
    if root_tag == "rss":
        for child in root:
            if _get_local_tag(child.tag).lower() == "channel":
                channel = child
                break
        if channel is None:
            channel = root
    else:
        channel = root

    # Extract show metadata
    show_title = "Untitled Podcast"
    show_desc: str | None = None
    show_link: str | None = None
    show_author: str | None = None
    show_image: str | None = None
    show_lang: str | None = None

    for elem in channel:
        ltag = _get_local_tag(elem.tag).lower()
        text = (elem.text or "").strip()

        if ltag == "title" and text:
            show_title = text
        elif ltag in ("description", "summary", "subtitle") and text and not show_desc:
            show_desc = text
        elif ltag == "link":
            show_link = text or elem.attrib.get("href")
        elif ltag in ("author", "managingeditor", "creator") and text and not show_author:
            show_author = text
        elif ltag == "image":
            # Can be <image><url>...</url></image> or <itunes:image href="..." />
            href = elem.attrib.get("href")
            if href:
                show_image = href.strip()
            else:
                for img_child in elem:
                    if _get_local_tag(img_child.tag).lower() == "url" and img_child.text:
                        show_image = img_child.text.strip()
        elif ltag == "language" and text:
            show_lang = text

    episodes: list[EpisodeMetadata] = []

    # Find all items (<item> in RSS or <entry> in Atom)
    for child in channel:
        cltag = _get_local_tag(child.tag).lower()
        if cltag not in ("item", "entry"):
            continue

        item_elem = child
        ep_title = "Untitled Episode"
        ep_guid: str | None = None
        ep_audio_url: str | None = None
        ep_duration_raw: str | None = None
        ep_pub_date: str | None = None

        # Extract Podcasting 2.0 transcripts
        ep_transcripts = _extract_podcast_transcripts(item_elem)

        for item_child in item_elem:
            iltag = _get_local_tag(item_child.tag).lower()
            itext = (item_child.text or "").strip()

            if iltag == "title" and itext:
                ep_title = itext
            elif iltag in ("guid", "id") and itext:
                ep_guid = itext
            elif iltag == "enclosure":
                enc_url = item_child.attrib.get("url")
                if enc_url:
                    ep_audio_url = enc_url.strip()
            elif iltag in ("content", "media:content") and not ep_audio_url:
                media_url = item_child.attrib.get("url")
                if media_url:
                    ep_audio_url = media_url.strip()
            elif iltag == "duration" and itext:
                ep_duration_raw = itext
            elif iltag in ("pubdate", "published", "date") and itext:
                ep_pub_date = itext
            elif iltag == "link" and not ep_guid:
                ep_guid = itext or item_child.attrib.get("href")

        duration_sec = parse_duration(ep_duration_raw)
        effective_guid = ep_guid or ep_audio_url or f"{show_title}-{len(episodes) + 1}"

        episodes.append(
            EpisodeMetadata(
                show_title=show_title,
                episode_title=ep_title,
                episode_id=effective_guid,
                show_id=show_title,
                audio_url=ep_audio_url,
                duration_seconds=duration_sec,
                published_date=ep_pub_date,
                rss_transcripts=ep_transcripts,
                source_type="rss",
            )
        )

    show_meta = ShowMetadata(
        title=show_title,
        description=show_desc,
        feed_url=feed_url,
        link=show_link,
        author=show_author,
        image_url=show_image,
        language=show_lang,
        total_episodes=len(episodes),
    )

    return show_meta, episodes


def _parse_with_feedparser_fallback(
    xml_content: str, feed_url: str | None = None
) -> tuple[ShowMetadata, list[EpisodeMetadata]]:
    """Fallback feed parser using feedparser library."""
    parsed = feedparser.parse(xml_content)
    feed_data = parsed.get("feed", {})

    show_title = feed_data.get("title", "Untitled Podcast")
    show_desc = feed_data.get("description") or feed_data.get("summary")
    show_link = feed_data.get("link")
    show_author = feed_data.get("author")
    image_dict = feed_data.get("image", {})
    show_image = image_dict.get("href") if isinstance(image_dict, dict) else None
    show_lang = feed_data.get("language")

    episodes: list[EpisodeMetadata] = []
    for idx, entry in enumerate(parsed.get("entries", [])):
        ep_title = entry.get("title", "Untitled Episode")
        ep_guid = entry.get("id") or entry.get("guid") or entry.get("link")

        audio_url: str | None = None
        for enc in entry.get("enclosures", []):
            if isinstance(enc, dict) and enc.get("href"):
                audio_url = enc["href"]
                break

        duration_raw = (
            entry.get("itunes_duration")
            or entry.get("duration")
            or entry.get("total_time")
        )
        duration_sec = parse_duration(duration_raw)
        pub_date = entry.get("published") or entry.get("updated")

        effective_guid = ep_guid or audio_url or f"{show_title}-{idx + 1}"

        episodes.append(
            EpisodeMetadata(
                show_title=show_title,
                episode_title=ep_title,
                episode_id=effective_guid,
                show_id=show_title,
                audio_url=audio_url,
                duration_seconds=duration_sec,
                published_date=pub_date,
                rss_transcripts=[],
                source_type="rss",
            )
        )

    show_meta = ShowMetadata(
        title=show_title,
        description=show_desc,
        feed_url=feed_url,
        link=show_link,
        author=show_author,
        image_url=show_image,
        language=show_lang,
        total_episodes=len(episodes),
    )

    return show_meta, episodes


def parse_feed_content(
    xml_content: str, feed_url: str | None = None
) -> tuple[ShowMetadata, list[EpisodeMetadata]]:
    """Parse RSS/Atom XML feed content into ShowMetadata and list of EpisodeMetadata.

    Tries defusedxml ElementTree first (for strict security and full Podcasting 2.0 transcript support),
    falling back to feedparser if XML has structural issues.
    """
    if not xml_content or not xml_content.strip():
        return (
            ShowMetadata(title="Empty Feed", feed_url=feed_url, total_episodes=0),
            [],
        )

    try:
        return _parse_xml_element_tree(xml_content, feed_url=feed_url)
    except Exception as exc:
        logger.debug("defusedxml parsing encountered error (%s), falling back to feedparser", exc)
        try:
            return _parse_with_feedparser_fallback(xml_content, feed_url=feed_url)
        except Exception as fallback_exc:
            logger.warning("All feed parsing attempts failed: %s", fallback_exc)
            return (
                ShowMetadata(title="Unparsable Feed", feed_url=feed_url, total_episodes=0),
                [],
            )


def fetch_feed(
    feed_url: str,
    client: httpx.Client | None = None,
    timeout: float = 15.0,
) -> str:
    """Fetch raw XML content of an RSS feed.

    Args:
        feed_url: URL to the podcast RSS feed.
        client: Optional httpx.Client.
        timeout: Request timeout in seconds.

    Returns:
        Raw XML response string.
    """
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }

    if client is not None:
        resp = client.get(feed_url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    else:
        with httpx.Client(timeout=timeout, follow_redirects=True) as http_client:
            resp = http_client.get(feed_url, headers=headers)
            resp.raise_for_status()
            return resp.text


def fetch_and_parse_feed(
    feed_url: str,
    client: httpx.Client | None = None,
    timeout: float = 15.0,
) -> tuple[ShowMetadata, list[EpisodeMetadata]]:
    """Fetch an RSS feed from a URL and parse its show and episode metadata.

    Args:
        feed_url: URL to the podcast RSS feed.
        client: Optional httpx.Client.
        timeout: Request timeout in seconds.

    Returns:
        Tuple of (ShowMetadata, list of EpisodeMetadata).
    """
    xml_content = fetch_feed(feed_url, client=client, timeout=timeout)
    return parse_feed_content(xml_content, feed_url=feed_url)
