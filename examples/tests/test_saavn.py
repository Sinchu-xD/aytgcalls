"""Tests for JioSaavn resolution via SaavnAPI package."""

from __future__ import annotations

import pytest

from aytgcalls.media.saavn import SAAVN_API_AVAILABLE, is_saavn_source, resolve_saavn
from aytgcalls.types import SourceKind


def test_is_saavn_source() -> None:
    assert is_saavn_source("saavn:Tum Hi Ho")
    assert is_saavn_source("saavn:kesariya")
    assert is_saavn_source("https://www.jiosaavn.com/song/tum-hi-ho/BgwicBdfAQU")
    assert is_saavn_source("https://jiosaavn.com/song/kesariya/12345")
    assert not is_saavn_source("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert not is_saavn_source("song.mp3")
    assert not is_saavn_source("http://example.com/radio")


@pytest.mark.asyncio
async def test_resolve_saavn_query() -> None:
    if not SAAVN_API_AVAILABLE():
        pytest.skip("SaavnAPI (JioSaavn) not installed")

    source = await resolve_saavn("saavn:Tum Hi Ho")
    assert source is not None
    assert source.kind is SourceKind.URL
    assert "saavncdn.com" in source.uri or "saavn" in source.uri
    assert "Tum Hi Ho" in source.display_name
