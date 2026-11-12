"""USB picture for the existing phone window.

The CoreDevice display stream (pymobiledevice3, iOS 27+) is HEVC. Its HTTP
feed at /stream.bin is length-prefixed access units. This turns those into
Annex-B and hands them to the same decoder the AirPlay window already paints.
Nothing in site-packages is patched. There is no sound: Windows cannot decode
the phone's AAC-ELD.
"""
import asyncio
import base64
import http.client
import json
import logging
import queue
import threading
import time

from .video import VideoDecoder, avcc_to_annexb

log = logging.getLogger(__name__)

PORT = 8091


class UsbReceiver:
    """Same start/stop/mute/rename surface as the AirPlay receiver."""

    def __init__(self, settings, on_frame, on_event, require_usb=True):
        self.settings = settings
        self.on_event = on_event
        self.decoder = VideoDecoder(on_frame, codec="hevc")
        self.require_usb = True  # a Wi-Fi picture is Screen Mirroring, not this stream
        self.has_audio = False
        self.muted = True  # no USB audio on Windows
        self.loop = None
        self._thread = None
        self._stop = threading.Event()
        self._did_stop = False
        self._aus = 0

    def emit(self, event, **info):
        try:
            self.on_event(event, info)
        except Exception:
            log.exception("event handler failed")

    def set_muted(self, muted: bool):
        self.muted = muted  # remembered for the menu; this path has no audio

    def rename(self, name: str):
        self.settings["name"] = name
        self.settings.save()
        self.emit("connecting", name=name)

    def start(self):
        self.decoder.start()
        self._thread = threading.Thread(target=self._run, name="usb-picture", daemon=True)
        self._thread.start()

    def _run(self):
        # The device check used to keep one asyncio loop alive and sleep inside it.
        # That sleep sits in a Windows completion port. While the window is handling
        # messages, Windows rejects the call (0x8001010d) and the process dies.
        # Nothing being plugged in is normal: pause with a thread wait, and open a
        # loop only for an actual check or an actual picture.
        waiting = False
        list_failed = False
        while not self._stop.is_set():
            try:
                chosen = _call(_first_usb_device())
            except Exception:
                if not list_failed:
                    log.exception("usb device list failed")
                    list_failed = True
                chosen = None
            else:
                list_failed = False
            if chosen is None:
                if not waiting:
                    self.emit("unplugged")
                    waiting = True
                if self._stop.wait(1.0):
                    return
                continue
            waiting = False
            self._aus = 0
            self.emit("connecting", name="iPhone", via="Cable")
            log.info("usb picture using %s (%s)", chosen.serial, chosen.connection_type)
            try:
                reason = _call(self._stream(chosen))
            except Exception:
                log.exception("usb picture crashed")
                if not self._stop.is_set():
                    self.emit("error", message="USB picture stopped. Unlock the phone, quit Camera, and try again.")
                return
            if self._stop.is_set() or reason == "stop":
                return
            if reason == "error":
                return
            if reason in ("unplugged", "ended") and not _call(_serial_is_usb(chosen.serial)):
                self.emit("unplugged")
                try:
                    _call(_release_phone(chosen.serial))
                except Exception:
                    log.warning("could not release the phone camera", exc_info=True)
                waiting = True
                continue
            if self._stop.wait(0.5):
                return

    async def _stream(self, chosen):
        from pymobiledevice3.remote.core_device.screen_stream import ScreenStreamServer
        from pymobiledevice3.remote.rsd_tunnel import PreferredRsdTunnel

        try:
            async with PreferredRsdTunnel(serial=chosen.serial, autopair=True) as rsd:
                await self._remember_display(rsd)
                server = ScreenStreamServer(
                    rsd,
                    bind="127.0.0.1",
                    http_port=PORT,
                    audio_default_on=False,
                    # The browser asks for extra keyframes so a stall snaps back.
                    # Those requests stall this encoder on a still screen. ffmpeg
                    # does not need them.
                    motion_idr=False,
                )
                serve_task = asyncio.create_task(server.serve(), name="usb-serve")
                read_task = asyncio.create_task(self._read(), name="usb-read")
                stop_task = asyncio.create_task(self._until_stopped(), name="usb-stop")
                cable_task = asyncio.create_task(self._until_unplugged(chosen.serial), name="usb-cable")
                lock_task = asyncio.create_task(self._watch_lock(rsd), name="usb-lock")
                done, pending = await asyncio.wait(
                    {serve_task, read_task, stop_task, cable_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                lock_task.cancel()
                for task in pending:
                    task.cancel()
                if not serve_task.done():
                    serve_task.cancel()
                # Awaiting the cancelled server runs its shutdown, which releases
                # the phone's camera and microphone.
                failure = None
                for task in (serve_task, read_task, cable_task):
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    except Exception as exc:
                        failure = failure or exc
                try:
                    await lock_task
                except (asyncio.CancelledError, Exception):
                    pass
                try:
                    await stop_task
                except (asyncio.CancelledError, Exception):
                    pass
                if self._stop.is_set():
                    return "stop"
                if cable_task in done:
                    return "unplugged"
                if failure is not None and self._aus == 0:
                    log.error("usb picture server: %s", failure)
                    self.emit("error", message=_short_error(failure))
                    return "error"
                if self._aus == 0:
                    self.emit(
                        "error",
                        message="USB picture did not start. Unlock the phone and quit Camera or Voice Memos.",
                    )
                    return "error"
                return "ended"
        except Exception as exc:
            log.exception("usb picture failed")
            if not self._stop.is_set():
                self.emit("error", message=_short_error(exc))
            return "error"

    async def _remember_display(self, rsd):
        from pymobiledevice3.remote.core_device.device_info import DeviceInfoService, select_display

        try:
            async with DeviceInfoService(rsd) as info:
                display = select_display(await info.get_display_info(), None)
            size = (display.get("currentMode") or {}).get("size") or ()
            if len(size) >= 2 and size[0] > 0 and size[1] > 0:
                self.decoder.visible = (round(size[0]), round(size[1]))
                log.info("usb display %dx%d", self.decoder.visible[0], self.decoder.visible[1])
        except Exception:
            log.warning("usb display size unavailable", exc_info=True)

    async def _watch_lock(self, rsd):
        """Same locked message as Screen Mirroring. SpringBoard state 1 means locked."""
        from pymobiledevice3.services.notification_proxy import RemoteNotificationProxyService

        name = "com.apple.springboard.lockstate"
        current = None
        try:
            async with RemoteNotificationProxyService(rsd) as proxy:
                try:
                    current = bool(await proxy.notify_get_state(name))
                    self.emit("paused" if current else "resumed")
                    log.info("phone %s", "locked" if current else "unlocked")
                except Exception:
                    log.info("phone lock state unreadable")
                await proxy.notify_register_dispatch(name)
                async for event in proxy.receive_notification():
                    if getattr(event, "name", None) != name or getattr(event, "state", None) is None:
                        continue
                    locked = bool(event.state)
                    if locked == current:
                        continue
                    current = locked
                    log.info("phone %s", "locked" if locked else "unlocked")
                    self.emit("paused" if locked else "resumed")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.info("phone lock watch stopped", exc_info=True)

    async def _until_unplugged(self, serial):
        from pymobiledevice3.usbmux import list_devices

        misses = 0
        while not self._stop.is_set():
            await asyncio.sleep(1.0)
            try:
                devices = await list_devices()
            except Exception:
                continue
            if any(d.is_usb and d.serial == serial for d in devices):
                misses = 0
                continue
            misses += 1
            if misses >= 2:
                return

    async def _until_stopped(self):
        while not self._stop.is_set():
            await asyncio.sleep(0.2)

    async def _read(self):
        reader, writer = await self._connect()
        try:
            buf = bytearray()
            while not self._stop.is_set():
                line = await reader.readline()
                if not line:
                    return
                size = int(line.strip() or b"0", 16)
                if size == 0:
                    return
                buf += await reader.readexactly(size)
                await reader.readexactly(2)
                while len(buf) >= 4:
                    n = int.from_bytes(buf[:4], "big")
                    if n <= 0 or len(buf) < 4 + n:
                        break
                    body = bytes(buf[4:4 + n])
                    del buf[:4 + n]
                    if body:
                        self._unit(body[0], body[1:])
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _connect(self):
        deadline = time.monotonic() + 45
        last = "USB picture server did not answer"
        while time.monotonic() < deadline and not self._stop.is_set():
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", PORT), timeout=2
                )
            except (OSError, asyncio.TimeoutError):
                await asyncio.sleep(0.3)
                continue
            writer.write(
                f"GET /stream.bin HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\nConnection: close\r\n\r\n".encode()
            )
            await writer.drain()
            status = await reader.readline()
            while True:
                header = await reader.readline()
                if header in (b"\r\n", b""):
                    break
            if status.startswith(b"HTTP/1.1 200") or status.startswith(b"HTTP/1.0 200"):
                log.info("usb picture stream connected")
                return reader, writer
            last = status.decode("ascii", "replace").strip() or last
            log.info("usb picture stream not ready: %s", last)
            writer.close()
            await asyncio.sleep(0.5)
        raise TimeoutError(last)

    def _unit(self, kind, payload):
        if kind == 3:
            self._config(payload)
            return
        if kind not in (0, 1, 2):
            return
        nal = avcc_to_annexb(payload)
        if not nal:
            log.warning("usb access unit was not length-prefixed HEVC")
            return
        if kind == 2:
            self.decoder.reset()
        self._aus += 1
        if self._aus == 1:
            log.info("first usb access unit, %d bytes, type %d", len(nal), kind)
        self.decoder.submit(nal)

    def _config(self, payload):
        try:
            cfg = json.loads(payload)
            raw = base64.b64decode(cfg["description"])
        except Exception:
            log.warning("usb decoder config was not usable")
            return
        display = cfg.get("display") or {}
        try:
            visible = (int(display.get("width") or 0), int(display.get("height") or 0))
        except (TypeError, ValueError):
            visible = (0, 0)
        if visible[0] > 0 and visible[1] > 0:
            self.decoder.visible = visible
            log.info("usb display %dx%d", visible[0], visible[1])
        if raw and raw != self.decoder.extradata:
            self.decoder.extradata = raw
            self.decoder.reset()
            log.info("usb hevc config %s (%d bytes)", cfg.get("codec"), len(raw))

    def stop(self):
        if self._did_stop:
            return
        self._did_stop = True
        self._stop.set()
        self.decoder.stop()
        if self._thread:
            self._thread.join(timeout=8)


class StreamTouch:
    """Finger events for the cable picture. One queue, so a drag stays in order."""

    def __init__(self, port):
        self.port = port
        self.q = queue.Queue(maxsize=64)
        self._conn = None
        self._carry = 0.0
        self._carry_axis = "y"
        self._carry_t = 0.0
        threading.Thread(target=self._run, name="usb-touch", daemon=True).start()

    def send(self, kind, xf, yf):
        self._put(("touch", kind, _hid(xf), _hid(yf)))

    def swipe(self, x1, y1, x2, y2):
        self._put(("path", _hid(x1), _hid(y1), _hid(x2), _hid(y2)))

    def scroll(self, x, y, dx, dy):
        """Keep one finger down and move it. A pause lifts the finger."""
        self._put(("scroll", _hid(x), _hid(y), int(round(dx * 65535)), int(round(dy * 65535))))

    def scroll_notches(self, x, y, notches, axis="y"):
        """One beat of the wheel: a slow drag that rests before the finger lifts."""
        self._put(("notches", float(x), float(y), float(notches), axis))

    def double_tap(self, xf, yf):
        """Two taps, 80 ms apart. Same gap WebDriverAgent uses."""
        self._put(("double", _hid(xf), _hid(yf)))

    def long_press(self, xf, yf):
        """Hold for 700 ms, then lift. Same hold WebDriverAgent uses."""
        self._put(("long", _hid(xf), _hid(yf)))

    def button(self, name):
        self._put(("button", name))

    def _put(self, item):
        try:
            self.q.put_nowait(item)
        except queue.Full:
            pass

    def _run(self):
        finger = None
        while True:
            try:
                item = self.q.get(timeout=0.16 if finger else None)
            except queue.Empty:
                if finger:
                    self._lift(finger)
                    finger = None
                continue
            try:
                if item[0] == "scroll":
                    finger = self._scroll_finger(finger, item)
                elif item[0] == "notches":
                    if finger:
                        self._lift(finger)
                        finger = None
                    self._notch_drag(item)
                else:
                    if finger:
                        self._lift(finger)
                        finger = None
                    if item[0] == "touch":
                        self._post("/touch", {"type": item[1], "x": item[2], "y": item[3]})
                    elif item[0] == "button":
                        self._post("/button", {"name": item[1], "state": "press"})
                    elif item[0] == "double":
                        self._post("/touch", {"type": "tap", "x": item[1], "y": item[2]})
                        time.sleep(0.08)
                        self._post("/touch", {"type": "tap", "x": item[1], "y": item[2]})
                    elif item[0] == "long":
                        self._post("/touch", {"type": "contact", "x": item[1], "y": item[2]})
                        time.sleep(0.7)
                        self._post("/touch", {"type": "release", "x": item[1], "y": item[2]})
                    else:
                        self._path(*item[1:])
            except Exception:
                log.debug("usb touch failed", exc_info=True)
                self._conn = None
                finger = None

    def _lift(self, finger):
        self._post("/touch", {"type": "release", "x": finger[0], "y": finger[1]})

    def _notch_drag(self, item):
        """The original scroll: up to three slow drags, each one resting before the lift."""
        xf, yf, notches, axis = item[1:]
        now = time.monotonic()
        if now - self._carry_t > 1.0 or axis != self._carry_axis or self._carry * notches < 0:
            self._carry = 0.0
        notches += self._carry
        total = notches * 0.12
        min_frac = 24 / 874
        steps = 0
        for _ in range(3):
            if abs(total) < min_frac:
                break
            step = max(-0.45, min(0.45, total))
            if axis == "x":
                self._resting_drag(xf, yf, step, 0.0)
            else:
                self._resting_drag(xf, yf, 0.0, step)
            total -= step
            steps += 1
        self._carry = (total / 0.12) if abs(total) < min_frac else 0.0
        self._carry_axis = axis
        self._carry_t = time.monotonic()
        log.info("scroll drag notches=%.2f steps=%d axis=%s", notches, steps, axis)

    def _resting_drag(self, xf, yf, dx, dy):
        if abs(dy) >= abs(dx):
            y1 = yf
            if dy >= 0:
                y1 = min(max(y1, 0.15), 0.85 - dy)
            else:
                y1 = min(max(y1, 0.15 - dy), 0.85)
            x1 = min(max(xf, 0.08), 0.92)
            x2, y2 = x1, y1 + dy
        else:
            x1 = xf
            if dx >= 0:
                x1 = min(max(x1, 0.15), 0.85 - dx)
            else:
                x1 = min(max(x1, 0.15 - dx), 0.85)
            y1 = min(max(yf, 0.08), 0.92)
            x2, y2 = x1 + dx, y1
        self._post("/touch", {"type": "contact", "x": _hid(x1), "y": _hid(y1)})
        n = 8
        for i in range(1, n + 1):
            t = i / n
            self._post("/touch", {
                "type": "contact",
                "x": _hid(x1 + (x2 - x1) * t),
                "y": _hid(y1 + (y2 - y1) * t),
            })
            if i < n:
                time.sleep(0.15 / n)
        time.sleep(0.06)
        self._post("/touch", {"type": "release", "x": _hid(x2), "y": _hid(y2)})

    def _scroll_finger(self, finger, item):
        """Keep dragging. A new notch moves the same finger. A pause lifts it."""
        anchor_x, anchor_y, dx, dy = item[1:]
        t0 = time.monotonic()

        lo, hi = 18000, 48000

        def inside(px, py):
            return lo <= px <= hi and lo <= py <= hi

        mode = "drag"
        if finger is not None and not inside(finger[0] + dx, finger[1] + dy):
            # Only a very long roll gets here. Hold briefly so the lift is not a flick.
            x, y = finger
            self._post("/touch", {"type": "contact", "x": x, "y": y})
            time.sleep(0.04)
            self._lift(finger)
            finger = None
            mode = "edge"
        if finger is None:
            if mode != "edge":
                mode = "fresh"
            # Park at the far side of the list, so a roll has room to finish.
            if abs(dy) >= abs(dx):
                start_x = min(hi, max(lo, anchor_x))
                start_y = hi if dy < 0 else lo
            else:
                start_y = min(hi, max(lo, anchor_y))
                start_x = hi if dx < 0 else lo
            self._post("/touch", {"type": "contact", "x": _hid_px(start_x), "y": _hid_px(start_y)})
        else:
            start_x, start_y = finger
        target_x, target_y = start_x + dx, start_y + dy
        steps = 4
        x, y = start_x, start_y
        for i in range(1, steps + 1):
            t = i / steps
            x = _hid_px(start_x + (target_x - start_x) * t)
            y = _hid_px(start_y + (target_y - start_y) * t)
            self._post("/touch", {"type": "contact", "x": x, "y": y})
            if i < steps:
                time.sleep(0.004)
        log.info(
            "scroll finger mode=%s dx=%d dy=%d start=%d,%d end=%d,%d q=%d ms=%d",
            mode, dx, dy, int(start_x), int(start_y), x, y, self.q.qsize(), int((time.monotonic() - t0) * 1000),
        )
        return (x, y)

    def _path(self, x1, y1, x2, y2):
        steps = 6
        for i in range(steps + 1):
            t = i / steps
            self._post("/touch", {"type": "contact", "x": round(x1 + (x2 - x1) * t), "y": round(y1 + (y2 - y1) * t)})
            time.sleep(0.02)
        self._post("/touch", {"type": "release", "x": x2, "y": y2})

    def _post(self, path, payload):
        body = json.dumps(payload).encode()
        if self._conn is None:
            self._conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=1)
        self._conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        resp = self._conn.getresponse()
        resp.read()


_touch = None


def stream_touch():
    global _touch
    if _touch is None:
        _touch = StreamTouch(PORT)
    return _touch


def _hid(fraction):
    return _hid_px(float(fraction) * 65535)


def _hid_px(value):
    return max(0, min(65535, int(round(value))))


def _call(coro):
    """Run one USB task, then close the loop before the caller waits."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


async def _first_usb_device():
    from pymobiledevice3.usbmux import list_devices

    for device in await list_devices():
        if device.is_usb:
            return device
    return None


async def _serial_is_usb(serial) -> bool:
    from pymobiledevice3.usbmux import list_devices

    try:
        devices = await list_devices()
    except Exception:
        return False
    return any(d.is_usb and d.serial == serial for d in devices)


async def _release_phone(serial):
    """Tell the phone to drop the capture after the cable is already gone.

    The USB tunnel is dead by then, so the stop has to go over the network.
    It does not start a new picture.
    """
    from pymobiledevice3.remote.core_device.display_service import DisplayService
    from pymobiledevice3.remote.rsd_tunnel import PreferredRsdTunnel
    from pymobiledevice3.usbmux import list_devices

    try:
        devices = await list_devices()
    except Exception:
        log.warning("could not release the phone camera", exc_info=True)
        return
    if not any(d.serial == serial for d in devices):
        log.info("phone is gone, so the camera release was skipped")
        return
    try:
        async with PreferredRsdTunnel(serial=serial, autopair=True) as rsd:
            await asyncio.wait_for(DisplayService.stop_all_streams(rsd), timeout=6)
        log.info("released the phone camera")
    except Exception:
        log.warning("could not release the phone camera", exc_info=True)


def usb_present() -> bool:
    from pymobiledevice3.usbmux import list_devices

    async def once():
        return any(d.is_usb for d in await list_devices())

    return asyncio.run(once())


def _short_error(exc):
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    if "camera or microphone" in text.lower() or "9022" in text:
        return "Quit Camera or Voice Memos on the iPhone, then open this again."
    if "address already in use" in text.lower() or "10048" in text:
        return "Port 8091 is already in use. Close the other phone viewer and try again."
    if len(text) > 180:
        text = text[:177] + "..."
    return text
