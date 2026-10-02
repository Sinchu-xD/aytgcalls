from __future__ import annotations

import pytest

from aytgcalls.media.youtube import (
    AYTUBE_AVAILABLE,
    is_youtube_query,
    is_youtube_url,
    is_ytdlp_url,
    resolve_url,
    search_aytube,
)
from aytgcalls.types import AudioSource, SourceKind


def test_aytube_availability():
    assert AYTUBE_AVAILABLE() is True


def test_youtube_url_detection():
    assert is_youtube_url("https://www.youtube.com/watch?v=1-xGerv5FOk")
    assert is_youtube_url("https://youtu.be/1-xGerv5FOk")
    assert is_ytdlp_url("https://www.youtube.com/watch?v=1-xGerv5FOk")
    assert not is_youtube_url("https://example.com/audio.mp3")


def test_youtube_query_detection():
    assert is_youtube_query("yt:Alone Alan Walker")
    assert is_youtube_query("youtube:Faded")
    assert is_youtube_query("YT:Believer")
    assert not is_youtube_query("saavn:Kesariya")
    assert not is_youtube_query("https://example.com/test.mp3")


@pytest.mark.asyncio
async def test_search_aytube_resolution():
    source = await search_aytube("yt:Alone Alan Walker")
    assert source is not None
    assert isinstance(source, AudioSource)
    assert source.kind is SourceKind.URL
    assert "Alone" in (source.title or "")
    assert source.uri.startswith("http")


@pytest.mark.asyncio
async def test_resolve_url():
    source = await resolve_url("https://www.youtube.com/watch?v=1-xGerv5FOk")
    assert source is not None
    assert isinstance(source, AudioSource)
    assert source.kind is SourceKind.URL
    assert source.uri.startswith("http")
