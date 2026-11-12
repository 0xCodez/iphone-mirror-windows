"""Screen-mirroring video: TCP stream parsing, AES-CTR decryption, H.264 decoding."""
import asyncio
import hashlib
import logging
import queue
import struct
import threading
import time
from fractions import Fraction

import av
import numpy as np
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from . import net

log = logging.getLogger(__name__)

START = b"\x00\x00\x00\x01"


def mirror_cipher(aeskey: bytes, stream_connection_id: int):
    """AES-128-CTR decryptor for the mirror stream (key/iv derived like the receiver)."""
    skey = f"AirPlayStreamKey{stream_connection_id}".encode()
    siv = f"AirPlayStreamIV{stream_connection_id}".encode()
    key = hashlib.sha512(skey + aeskey).digest()[:16]
    iv = hashlib.sha512(siv + aeskey).digest()[:16]
    return Cipher(algorithms.AES(key), modes.CTR(iv))


def avcc_to_annexb(data: bytes):
    """4-byte big-endian length prefixed NALs -> start-code NALs. None if malformed."""
    out = bytearray()
    pos, n = 0, len(data)
    while pos < n:
        if pos + 4 > n:
            return None
        size = int.from_bytes(data[pos:pos + 4], "big")
        if size <= 0 or pos + 4 + size > n or data[pos + 4] & 0x80:
            return None
        out += START
        out += data[pos + 4:pos + 4 + size]
        pos += 4 + size
    return bytes(out)


def visible_size(frame_w, frame_h, visible):
    """Drop encoder padding. Ignore a size that is not the same picture."""
    if not visible:
        return frame_w, frame_h
    vw, vh = int(visible[0]), int(visible[1])
    if frame_w - 64 <= vw <= frame_w and frame_h - 64 <= vh <= frame_h:
        return vw, vh
    return frame_w, frame_h


class VideoDecoder(threading.Thread):
    """Decodes Annex-B access units; hands the newest frame (BGRA ndarray) to on_frame."""

    def __init__(self, on_frame, codec="h264"):
        super().__init__(name="video-decoder", daemon=True)
        self.on_frame = on_frame
        self.codec_name = codec  # "h264" for AirPlay, "hevc" for the USB picture
        self.extradata = None  # HEVC hvcC record, when the USB stream sends one
        self.visible = None  # (w, h) real screen; the HEVC frame is padded on the right and bottom
        self.q = queue.Queue(maxsize=240)
        self.target = None  # (w, h) in device pixels, set by the UI
        self.last_frame = None  # full-resolution av.VideoFrame (for screenshots)
        self._codec = None
        self._stop = False
        self._announced = False
        self._crop_logged = False
        self._last_deliver = 0.0
        self._scale_key = None
        self._scale_src = None
        self._scale_sink = None
        self._scale_bad = None
        self._epoch = 0  # discard() bumps this so a packet already taken is not painted

    def submit(self, data: bytes):
        try:
            self.q.put_nowait(data)
        except queue.Full:
            log.warning("decoder queue full, dropping frame")

    def reset(self):
        self.submit(None)

    def discard(self):
        """Drop packets still queued. A closed stream must not paint another frame."""
        self._epoch += 1
        while True:
            try:
                self.q.get_nowait()
            except queue.Empty:
                break

    def stop(self):
        self._stop = True
        self.submit(b"")

    def _new_codec(self):
        c = av.CodecContext.create(self.codec_name, "r")
        try:
            c.thread_type = "SLICE"  # no frame-threading delay
        except Exception:
            pass
        try:
            c.options = {"flags": "low_delay"}
        except Exception:
            pass
        if self.extradata:
            c.extradata = self.extradata
        return c

    def run(self):
        while not self._stop:
            epoch = self._epoch
            data = self.q.get()
            if self._stop or epoch != self._epoch:
                continue
            if data is None:
                self._codec = None
                continue
            if self._codec is None:
                self._codec = self._new_codec()
            try:
                frames = self._codec.decode(av.Packet(data))
            except av.error.FFmpegError as e:
                log.debug("decode error: %s", e)
                continue
            if not frames:
                continue
            # Drop a frame only when a newer one is already waiting and we just
            # painted. That catches up without holding the picture for 50ms.
            if epoch != self._epoch or (not self.q.empty() and time.monotonic() - self._last_deliver < 0.008):
                continue
            frame = frames[-1]
            try:
                if epoch != self._epoch:
                    continue
                self._deliver(frame)
            except Exception:
                log.exception("frame conversion failed")

    def _deliver(self, frame):
        self.last_frame = frame
        if not self._announced:
            self._announced = True
            log.info("first frame %dx%d (%s)", frame.width, frame.height, self.codec_name)
        self._last_deliver = time.monotonic()
        vw, vh = visible_size(frame.width, frame.height, self.visible)
        tw, th = self.target or (vw, vh)
        tw, th = max(16, int(tw)), max(16, int(th))
        # keep the source aspect if the UI has not adapted yet
        if abs(tw / th - vw / vh) > 0.02:
            th = max(16, round(tw * vh / vw))
        if (vw, vh) != (frame.width, frame.height) and not self._crop_logged:
            self._crop_logged = True
            log.info("cropping frame %dx%d to %dx%d", frame.width, frame.height, vw, vh)
        try:
            img = self._scale(frame, vw, vh, tw, th)
        except Exception:
            log.exception("fast scale failed")
            self._scale_bad = (frame.width, frame.height, frame.format.name, vw, vh, tw, th)
            self._scale_key = None
            img = self._scale_slow(frame, vw, vh, tw, th)
        self.on_frame(img, vw, vh)

    def _scale(self, frame, vw, vh, tw, th):
        """Crop, then one scale. full_chroma_int keeps the gray dashes off the left edge."""
        key = (frame.width, frame.height, frame.format.name, vw, vh, tw, th)
        if key == self._scale_bad:
            return self._scale_slow(frame, vw, vh, tw, th)
        if key != self._scale_key:
            graph = av.filter.Graph()
            src = graph.add_buffer(template=frame, time_base=frame.time_base or Fraction(1, 1000))
            nodes = [src]
            if (vw, vh) != (frame.width, frame.height):
                nodes.append(graph.add("crop", f"{int(vw)}:{int(vh)}:0:0"))
            nodes.append(graph.add("scale", f"{int(tw)}:{int(th)}:flags=area+accurate_rnd+full_chroma_int"))
            nodes.append(graph.add("format", "bgra"))
            sink = graph.add("buffersink")
            nodes.append(sink)
            graph.link_nodes(*nodes)
            graph.configure()
            self._scale_graph = graph
            self._scale_src = src
            self._scale_sink = sink
            self._scale_key = key
        self._scale_src.push(frame)
        return np.ascontiguousarray(self._scale_sink.pull().to_ndarray())

    def _scale_slow(self, frame, vw, vh, tw, th):
        """Cut to the real screen before scaling. Scaling the pad leaves dashes."""
        if (vw, vh) != (frame.width, frame.height):
            raw = frame.reformat(format="bgra").to_ndarray()
            cropped = np.ascontiguousarray(raw[:vh, :vw])
            img = av.VideoFrame.from_ndarray(cropped, format="bgra").reformat(
                width=tw, height=th, format="bgra", interpolation="AREA"
            ).to_ndarray()
        else:
            img = frame.reformat(width=tw, height=th, format="bgra", interpolation="AREA").to_ndarray()
        return np.ascontiguousarray(img)


class MirrorStream:
    """Accepts the iPhone's mirror TCP connection and feeds the decoder."""

    def __init__(self, aeskey: bytes, stream_connection_id: int, decoder: VideoDecoder, events):
        self.decryptor = mirror_cipher(aeskey, stream_connection_id).decryptor()
        self.decoder = decoder
        self.events = events  # callable(event: str, **info)
        self.server = None
        self.port = 0
        self._writer = None
        self._sps_pps = None
        self._checked = False
        self._bad = 0
        self._task = None
        self.frames = 0

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._handle, host=net.BIND_HOST, port=0)
        self.port = self.server.sockets[0].getsockname()[1]
        log.info("mirror data port %d", self.port)
        return self.port

    async def stop(self):
        writer = self._writer
        if writer is not None:
            transport = getattr(writer, "transport", None)
            try:
                writer.close()
            except Exception:
                pass
            if transport is not None:
                try:
                    transport.abort()
                except Exception:
                    pass
        server = self.server
        self.server = None
        if server is not None:
            server.close()
        task = self._task
        self._task = None
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=1)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        if server is not None:
            try:
                await asyncio.wait_for(server.wait_closed(), timeout=1)
            except (asyncio.TimeoutError, Exception):
                pass

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._task = asyncio.current_task()
        self._writer = writer
        peer = writer.get_extra_info("peername")
        log.info("mirror stream connected from %s", peer)
        sock = writer.get_extra_info("socket")
        try:
            import socket as _s
            # A multi-megabyte buffer lets old video pile up and the picture falls behind.
            sock.setsockopt(_s.SOL_SOCKET, _s.SO_RCVBUF, 256 * 1024)
        except Exception:
            pass
        self.decoder.reset()
        try:
            while True:
                hdr = await reader.readexactly(128)
                size = struct.unpack_from("<I", hdr, 0)[0]
                payload = await reader.readexactly(size) if size else b""
                self._packet(hdr, payload)
        except (asyncio.IncompleteReadError, ConnectionError):
            log.info("mirror stream closed")
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("mirror stream error")
        finally:
            self._writer = None
            try:
                writer.close()
            except Exception:
                pass
            self.decoder.discard()
            self.events("mirror_stopped")

    def _packet(self, hdr: bytes, payload: bytes):
        ptype = hdr[4]
        if ptype == 0:  # encrypted video access unit
            dec = self.decryptor.update(payload)
            nal = avcc_to_annexb(dec)
            if nal is None:
                self._bad += 1
                if not self._checked:
                    self._checked = True
                    log.error("first video packet failed to decrypt into valid H.264 (key mismatch?)")
                    self.events("decrypt_error")
                return
            if not self._checked:
                self._checked = True
                log.info("video decryption OK")
            if self._sps_pps:
                nal = self._sps_pps + nal
                self._sps_pps = None
            self.frames += 1
            self.decoder.submit(nal)
        elif ptype == 1:  # unencrypted codec config (SPS + PPS)
            if payload[4:8] == b"hvc1":
                log.error("client sent H.265, which is not supported")
                return
            sps_size = struct.unpack_from(">H", payload, 6)[0]
            sps = payload[8:8 + sps_size]
            pps_size = struct.unpack_from(">H", payload, sps_size + 9)[0]
            pps = payload[sps_size + 11:sps_size + 11 + pps_size]
            self._sps_pps = START + sps + START + pps
            w, h = struct.unpack_from("<ff", hdr, 56)
            sw, sh = struct.unpack_from("<ff", hdr, 40)
            log.info("codec config: video %dx%d (source %dx%d) option %02x", w, h, sw, sh, hdr[6])
            if hdr[6] in (0x56, 0x5E):
                self.events("paused")
            else:
                self.events("format", width=int(w), height=int(h))
        # 2 = heartbeat (old protocol), 5 = streaming report: nothing to do


def _visible_size_check():
    assert visible_size(1216, 2656, (1206, 2622)) == (1206, 2622)
    assert visible_size(1216, 2656, None) == (1216, 2656)
    assert visible_size(1216, 2656, (1216, 2656)) == (1216, 2656)
    assert visible_size(1216, 2656, (402, 874)) == (1216, 2656)


if __name__ == "__main__":
    _visible_size_check()
