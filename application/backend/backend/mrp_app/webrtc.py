"""Optional WebRTC bridge for the latest ROS compressed-camera frame.

The recording path never passes through this module: it is a viewer-only bridge.
``aiortc`` is intentionally optional so the regular local dashboard remains
usable in minimal/demo installations.
"""

import asyncio
import fractions
import threading

try:  # Importing ROS/demo application must not require a media stack.
    import av
    from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
except ImportError:  # pragma: no cover - depends on deployment extras
    av = None
    RTCPeerConnection = RTCSessionDescription = VideoStreamTrack = None


def available():
    return RTCPeerConnection is not None


class _LatestJpegTrack(VideoStreamTrack if VideoStreamTrack else object):
    """A bounded, pull-based video track backed by ``runtime.preview()``."""

    kind = "video"

    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime
        self.last = None
        self.frame_number = 0

    async def recv(self):
        # WebRTC requests frames; sampling avoids retaining or decoding a video history.
        await asyncio.sleep(0.1)
        jpeg = self.runtime.preview()
        if jpeg:
            self.last = jpeg
        if not self.last:
            raise RuntimeError("No camera frame is available yet.")
        decoder = av.codec.CodecContext.create("mjpeg", "r")
        frames = decoder.decode(av.Packet(self.last))
        if not frames:
            raise RuntimeError("Camera frame could not be decoded.")
        frame = frames[0]
        self.frame_number += 1
        frame.pts = self.frame_number
        frame.time_base = fractions.Fraction(1, 10)
        return frame


class WebRtcBridge:
    """Creates and owns short-lived browser peer connections."""

    def __init__(self, runtime):
        self.runtime = runtime
        self.peers = set()
        self.loop = None
        self.thread = None
        self.lock = threading.Lock()

    def _ensure_loop(self):
        with self.lock:
            if self.loop:
                return
            self.loop = asyncio.new_event_loop()
            self.thread = threading.Thread(target=self._run, daemon=True, name="mrp-webrtc")
            self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def answer_sync(self, offer):
        """Run negotiation on the persistent media loop, not an HTTP request loop."""
        self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(self.answer(offer), self.loop).result(timeout=15)

    async def answer(self, offer):
        if not available():
            raise RuntimeError("WebRTC is unavailable; install the optional aiortc media extra.")
        if (
            not isinstance(offer, dict)
            or not isinstance(offer.get("sdp"), str)
            or offer.get("type") != "offer"
        ):
            raise ValueError("WebRTC offer must contain an SDP offer.")
        peer = RTCPeerConnection()
        self.peers.add(peer)

        @peer.on("connectionstatechange")
        async def cleanup():
            if peer.connectionState in {"closed", "failed", "disconnected"}:
                await peer.close()
                self.peers.discard(peer)

        peer.addTrack(_LatestJpegTrack(self.runtime))
        await peer.setRemoteDescription(RTCSessionDescription(sdp=offer["sdp"], type="offer"))
        await peer.setLocalDescription(await peer.createAnswer())
        return {"type": peer.localDescription.type, "sdp": peer.localDescription.sdp}

    def close(self):
        if not self.loop:
            return

        async def close_all():
            peers, self.peers = list(self.peers), set()
            for peer in peers:
                await peer.close()

        try:
            asyncio.run_coroutine_threadsafe(close_all(), self.loop).result(timeout=5)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
