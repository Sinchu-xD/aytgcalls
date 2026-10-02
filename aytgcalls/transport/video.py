"""H.264 video stream track for aiortc.

FFmpeg outputs raw Annex-B H.264 NAL units to stdout.  This track decodes them
with PyAV's :class:`av.CodecContext` into :class:`av.VideoFrame` objects, which
aiortc's :class:`RTCRtpSender` then re-encodes into H.264 RTP packets.
"""

from __future__ import annotations

import asyncio
import collections
import time
from collections.abc import Awaitable, Callable
from fractions import Fraction
from typing import TYPE_CHECKING

from aiortc.mediastreams import MediaStreamError, MediaStreamTrack

from ..logger import get_logger
from ..types import CallStats

if TYPE_CHECKING:
    from av import CodecContext, VideoFrame

logger = get_logger("transport.video")

__all__ = ["H264StreamTrack", "VideoFrameProvider"]

#: ``async () -> bytes | None`` returning raw Annex-B H.264 NAL units.
VideoFrameProvider = Callable[[], Awaitable[bytes | None]]

#: Target video pacing: 30 fps.
_FRAME_INTERVAL = Fraction(1, 30)
#: H.264 encoder time-base (90 kHz).
_TIME_BASE = Fraction(1, 90000)

# Defaults
_DEFAULT_WIDTH = 1280
_DEFAULT_HEIGHT = 720


class H264StreamTrack(MediaStreamTrack):
    """A ``sendonly`` video track that decodes raw H.264 NAL units into VideoFrames."""

    kind = "video"

    def __init__(
        self,
        provider: VideoFrameProvider | None = None,
        *,
        stats: CallStats | None = None,
        width: int = _DEFAULT_WIDTH,
        height: int = _DEFAULT_HEIGHT,
        fps: int = 30,
    ) -> None:
        super().__init__()
        self._provider = provider
        self._stats = stats if stats is not None else CallStats()
        self._width = width
        self._height = height
        self._fps = fps

        self._pts = 0
        self._pts_step = 90000 // fps
        self._deadline: float | None = None
        self._closed = False

        # Decoder context (lazily created on first frame).
        self._codec_ctx: "CodecContext | None" = None
        self._frame_queue: collections.deque[VideoFrame] = collections.deque()

    # -- wiring -------------------------------------------------------------------

    def set_provider(self, provider: VideoFrameProvider | None) -> None:
        """Swap the NAL-unit source (used when the player starts/stops)."""
        self._provider = provider
        self._frame_queue.clear()

    @property
    def stats(self) -> CallStats:
        return self._stats

    # -- pacing -------------------------------------------------------------------

    async def _pace(self) -> None:
        now = time.monotonic()
        if self._deadline is None:
            self._deadline = now
        self._deadline += float(_FRAME_INTERVAL)
        delay = self._deadline - now
        if delay > 0:
            await asyncio.sleep(delay)
        elif delay < -1.0:
            self._deadline = time.monotonic()

    # -- decoding -----------------------------------------------------------------

    def _ensure_codec(self) -> None:
        """Lazily create the H.264 decoder context."""
        if self._codec_ctx is not None:
            return
        try:
            import av
            self._codec_ctx = av.CodecContext.create("h264", "r")
        except Exception as exc:
            raise RuntimeError(f"Cannot create H.264 decoder: {exc}") from exc

    def _decode_nalus(self, data: bytes) -> list["VideoFrame"]:
        """Feed raw Annex-B NAL units through the decoder and return VideoFrames."""
        if not data:
            return []
        self._ensure_codec()
        assert self._codec_ctx is not None

        try:
            packets = self._codec_ctx.parse(data)
        except Exception:
            return []

        decoded: list[VideoFrame] = []
        for packet in packets:
            try:
                frames = self._codec_ctx.decode(packet)  # type: ignore[attr-defined]
            except Exception:
                continue
            for frame in frames:
                frame.pts = self._pts
                frame.time_base = _TIME_BASE
                self._pts += self._pts_step
                decoded.append(frame)
        return decoded

    # -- MediaStreamTrack ---------------------------------------------------------

    async def recv(self) -> "VideoFrame":
        if self._closed or self.readyState != "live":
            raise MediaStreamError("Video track is not live")

        await self._pace()

        if not self._frame_queue and self._provider is not None:
            try:
                # Read NAL units until at least one frame is decoded or stream ends.
                for _ in range(15):
                    nalus = await self._provider()
                    if not nalus:
                        break
                    decoded = self._decode_nalus(nalus)
                    if decoded:
                        self._frame_queue.extend(decoded)
                        break
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Video frame provider raised; emitting black frame")

        if self._frame_queue:
            self._stats.frames_encoded += 1
            return self._frame_queue.popleft()

        self._stats.frames_silence += 1
        return self._black_frame()

    def _black_frame(self) -> "VideoFrame":
        from av import VideoFrame

        frame = VideoFrame(width=self._width, height=self._height, format="yuv420p")
        frame.pts = self._pts
        frame.time_base = _TIME_BASE
        self._pts += self._pts_step
        return frame

    def stop(self) -> None:
        self._closed = True
        self._provider = None
        self._codec_ctx = None
        self._frame_queue.clear()
        super().stop()
