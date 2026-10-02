"""JioSaavn URL and search resolver using the SaavnAPI package."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from ..types import AudioSource, SourceKind

logger = logging.getLogger("media.saavn")

__all__ = ["resolve_saavn", "is_saavn_source", "SAAVN_API_AVAILABLE"]

_SAAVN_DOMAINS = frozenset({"jiosaavn.com", "www.jiosaavn.com", "saavn.com", "www.saavn.com"})


def SAAVN_API_AVAILABLE() -> bool:
    """Return True if SaavnAPI (JioSaavn) is installed."""
    try:
        import JioSaavn  # noqa: F401
        return True
    except ImportError:
        return False


def is_saavn_source(source: str) -> bool:
    """Return True if source is a saavn query ('saavn:...') or JioSaavn URL."""
    if not isinstance(source, str):
        return False
    if source.lower().startswith("saavn:"):
        return True
    try:
        host = urlparse(source).netloc.lower()
        host = host.split(":")[0].removeprefix("www.")
        return host in {"jiosaavn.com", "saavn.com"}
    except Exception:
        return False


async def resolve_saavn(source: str) -> AudioSource | None:
    """Resolve a JioSaavn URL or 'saavn:<query>' to a direct 320kbps CDN stream."""
    if not SAAVN_API_AVAILABLE():
        logger.debug("SaavnAPI (JioSaavn) is not installed; cannot resolve %r", source)
        return None

    import JioSaavn

    query = source
    if query.lower().startswith("saavn:"):
        query = query[6:].strip()

    try:
        # If it's a URL, search by title from path or extract
        if "jiosaavn.com" in query or "saavn.com" in query:
            path = urlparse(query).path.rstrip("/")
            parts = [p for p in path.split("/") if p]
            # e.g. /song/tum-hi-ho/BgwicBdfAQU -> search title "tum hi ho"
            title_guess = (
                parts[1].replace("-", " ")
                if len(parts) >= 2 and parts[0] == "song"
                else parts[-1].replace("-", " ")
            )
            songs = await JioSaavn.search_songs(title_guess, limit=3)
        else:
            songs = await JioSaavn.search_songs(query, limit=3)

        if not songs:
            logger.warning("No Saavn songs found for %r", source)
            return None

        song = songs[0]
        media_url = song.get("media_url")
        if not media_url:
            return None

        title = song.get("song") or song.get("title") or "JioSaavn Track"
        artists = song.get("primary_artists") or ""
        display_title = f"{title} - {artists}" if artists else title

        logger.info("Resolved Saavn %r -> %s", source, display_title)

        return AudioSource(
            uri=media_url,
            kind=SourceKind.URL,
            title=display_title,
            start_at=0.0,
            byte_offset=0,
        )
    except Exception as exc:
        logger.warning("SaavnAPI failed to resolve %r: %s", source, exc)
        return None
