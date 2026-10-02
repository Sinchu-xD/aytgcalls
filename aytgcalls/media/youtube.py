"""YouTube (and yt-dlp supported sites) stream resolution with aytube and YouTubeMusic.

Prioritizes the high-performance ``aytube`` package (developed by Abhishek Thakur) for
instant, pure-Python stream extraction without yt-dlp binary overhead.
Falls back to ``YouTubeMusic`` (yt-dlp) if needed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from urllib.parse import urlparse

from ..exceptions import MediaSourceError
from ..types import AudioSource, SourceKind

logger = logging.getLogger("media.youtube")

__all__ = [
    "resolve_url",
    "resolve_aytube",
    "search_aytube",
    "is_youtube_url",
    "is_ytdlp_url",
    "is_youtube_query",
    "AYTUBE_AVAILABLE",
    "YOUTUBE_MUSIC_AVAILABLE",
]

#: Well-known domains that aytube / YouTubeMusic / yt-dlp can handle.
_YT_DOMAINS: frozenset[str] = frozenset(
    {
        "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
        "youtube-nocookie.com", "www.youtube-nocookie.com",
        "vimeo.com", "www.vimeo.com", "player.vimeo.com",
        "soundcloud.com", "www.soundcloud.com", "on.soundcloud.com",
        "twitch.tv", "www.twitch.tv", "m.twitch.tv",
        "dailymotion.com", "www.dailymotion.com", "dai.ly",
        "streamable.com", "www.streamable.com",
        "bilibili.com", "www.bilibili.com",
        "tiktok.com", "www.tiktok.com",
        "instagram.com", "www.instagram.com",
        "twitter.com", "x.com", "www.twitter.com", "www.x.com",
        "facebook.com", "www.facebook.com", "fb.watch",
        "reddit.com", "www.reddit.com", "v.redd.it",
        "streamtape.com", "streamsb.net", "dood.to", "dood.watch",
        "mixdrop.co", "upstream.to",
        "jiosaavn.com", "www.jiosaavn.com", "saavn.com", "www.saavn.com",
    }
)


def _cookie_path() -> str | None:
    """Return a cookie file path if one exists."""
    candidates = [
        os.environ.get("AYTG_COOKIES_FILE", ""),
        os.environ.get("YOUTUBE_COOKIES_FILE", ""),
        os.environ.get("AYTUBE_COOKIES_FILE", ""),
        os.path.join(os.getcwd(), "cookies.txt"),
        os.path.join(os.getcwd(), "cookies_file"),
        os.path.expanduser("~/.config/aytube/cookies_file"),
        os.path.expanduser("~/.config/aytube/cookies.txt"),
        os.path.join(tempfile.gettempdir(), "aytgcalls_cookies.txt"),
        "/home/ubuntu/YouTubeMusic/cookies.txt",
    ]
    for path in candidates:
        if path and os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
    return None


def AYTUBE_AVAILABLE() -> bool:
    """Return True if the aytube package is installed."""
    try:
        import aytube  # noqa: F401
        return True
    except ImportError:
        return False


def YOUTUBE_MUSIC_AVAILABLE() -> bool:
    """Return True if the YouTubeMusic package or yt-dlp binary is available."""
    return shutil.which("yt-dlp") is not None


def is_youtube_url(url: str) -> bool:
    """Return True if the URL looks like a site aytube or YouTubeMusic can handle."""
    try:
        host = urlparse(url).netloc.lower()
        host = host.split(":")[0].removeprefix("www.")
        return host in _YT_DOMAINS
    except Exception:
        return False


#: Backward-compatible alias for the player module.
is_ytdlp_url = is_youtube_url


def is_youtube_query(source: str) -> bool:
    """Return True if source is a YouTube search prefix like 'yt:...' or 'youtube:...'."""
    if not isinstance(source, str):
        return False
    lower = source.lower()
    return lower.startswith("yt:") or lower.startswith("youtube:")


async def resolve_aytube(url: str, *, audio_only: bool = True) -> AudioSource | None:
    """Extract a direct stream using the aytube package."""
    if not AYTUBE_AVAILABLE():
        return None

    import aytube

    cookies = _cookie_path()
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: aytube.get_stream_url(url, audio_only=audio_only, cookies_file=cookies),
        )
        if not result or not result.url:
            return None

        # Reject HLS/DASH manifests
        parsed = urlparse(result.url)
        if parsed.path.endswith((".m3u8", ".mpd")):
            return None

        logger.info("Resolved via aytube: %r -> %s", url, result.title)
        return AudioSource(
            uri=result.url,
            kind=SourceKind.URL,
            title=result.title or None,
            start_at=0.0,
            byte_offset=0,
        )
    except Exception as exc:
        logger.debug("aytube failed to resolve %r: %s", url, exc)
        return None


async def search_aytube(query: str, *, audio_only: bool = True) -> AudioSource | None:
    """Search YouTube via aytube and resolve the top result."""
    if not AYTUBE_AVAILABLE():
        return None

    import aytube

    clean_query = query
    for prefix in ("yt:", "youtube:", "YT:", "YOUTUBE:"):
        if clean_query.startswith(prefix):
            clean_query = clean_query[len(prefix):].strip()
            break

    loop = asyncio.get_running_loop()
    try:
        results = await loop.run_in_executor(None, aytube.search, clean_query)
        if not results:
            logger.warning("aytube search returned no results for %r", clean_query)
            return None

        top = results[0]
        url = top.get("url") or f"https://www.youtube.com/watch?v={top.get('video_id')}"
        title = top.get("title")
        source = await resolve_aytube(url, audio_only=audio_only)
        if source is None:
            source = await resolve_url(url)
        if source and title:
            from dataclasses import replace
            return replace(source, title=title)
        return source
    except Exception as exc:
        logger.warning("aytube search failed for %r: %s", clean_query, exc)
        return None


async def resolve_url(url: str) -> AudioSource | None:
    """Resolve a YouTube / streaming URL to a direct playable source.

    Prioritizes ``aytube`` for YouTube domains, falling back to ``YouTubeMusic`` (yt-dlp).
    """
    # 1. Try aytube first for YouTube URLs
    is_yt = any(d in url.lower() for d in ("youtube.com", "youtu.be", "youtube-nocookie.com"))
    if is_yt and AYTUBE_AVAILABLE():
        source = await resolve_aytube(url, audio_only=True)
        if source is not None:
            return source

    # 2. Fallback to YouTubeMusic (yt-dlp)
    if not YOUTUBE_MUSIC_AVAILABLE():
        logger.debug("yt-dlp not available; cannot resolve %r", url)
        return None

    cookies = _cookie_path()
    try:
        from YouTubeMusic import get_stream
        direct_url = await get_stream(url, cookies)
    except ImportError:
        logger.debug("YouTubeMusic package not installed; cannot resolve %r", url)
        return None
    except Exception as exc:
        raise MediaSourceError(
            f"YouTubeMusic failed to resolve {url!r}: {exc}"
        ) from exc

    if not direct_url:
        logger.error("YouTubeMusic returned no stream URL for %r — cannot fall back to original URL", url)
        raise MediaSourceError(
            f"YouTubeMusic returned no stream URL for {url!r}. "
            "The track may be geo-restricted, age-restricted, or unavailable."
        )

    # Reject HLS/DASH manifests as a safety net
    parsed = urlparse(direct_url)
    if parsed.path.endswith((".m3u8", ".mpd")):
        logger.error("YouTubeMusic returned an HLS/DASH manifest for %r: %s — rejecting", url, parsed.path)
        raise MediaSourceError(
            f"Resolved URL is an HLS/DASH manifest, not a direct audio stream: {direct_url}"
        )

    logger.info("Resolved via YouTubeMusic %r -> direct videoplayback URL (%s)", url, parsed.hostname)

    return AudioSource(
        uri=direct_url,
        kind=SourceKind.URL,
        title=None,
        start_at=0.0,
        byte_offset=0,
    )
