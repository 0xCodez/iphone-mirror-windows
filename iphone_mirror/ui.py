"""iPhone-shaped floating window (PySide6).

The lock on the top bar turns the mouse and keyboard on or off, on the cable
and on Screen Mirroring. Scroll the top bar for the phone's volume. Drag the
top bar, or Alt+drag, to move the window, unless it is pinned. Close hides
the window in the tray.
"""
import logging
import math
import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QToolTip, QWidget

from .control import ERROR, OFF, READY, STARTING

log = logging.getLogger(__name__)

SHADOW = 22  # px around the phone for the drop shadow
BAR = 46  # px above the phone for the hover bar
DEFAULT_ASPECT = 1179 / 2556  # iPhone portrait

# input mapping when iPhone control is on
LONG_PRESS_S = 0.5  # hold at least this long without moving = long press
TAP_SLOP = 10.0  # px the pointer may move before a left click is ignored, or a middle drag starts
SWIPE_MIN_S, SWIPE_MAX_S = 0.06, 1.5  # swipe duration = real drag time, clamped
# One page per press. Ctrl+arrows stay volume. Auto-repeat is ignored.
_ARROW_SWIPE = {
    Qt.Key_Left: ((0.9, 0.5), (0.1, 0.5)),
    Qt.Key_Right: ((0.1, 0.5), (0.9, 0.5)),
    Qt.Key_Up: ((0.5, 0.82), (0.5, 0.35)),
    Qt.Key_Down: ((0.5, 0.35), (0.5, 0.82)),
}
DOUBLE_TAP_MS = 120  # a click is held back this long in case a second click makes it a double tap
WHEEL_BATCH_MS = 120  # the original: notches in one beat become one drag
TYPE_BATCH_MS = 16  # one frame; a burst still goes out as one string
HINT_S = 2.6  # how long a status hint stays in the top bar
BAR_FADE_S = 0.2  # top bar fade when the pointer enters or leaves the window

# Ctrl+wheel resizing: per 120 units of wheel delta (one notch). Touchpad pinches and smooth
# scrolling send many small deltas, which are summed and applied at most every ZOOM_MS.
ZOOM_PER_NOTCH = 1.06
ZOOM_MS = 30

# Windows virtual-key codes: shortcuts must also work with non-Latin keyboard layouts
VK_H, VK_J, VK_M, VK_U = 0x48, 0x4A, 0x4D, 0x55
VK_OEM_PLUS, VK_OEM_MINUS, VK_ADD, VK_SUBTRACT = 0xBB, 0xBD, 0x6B, 0x6D

GREEN, ORANGE, RED = QColor("#30d158"), QColor("#ff9f0a"), QColor("#ff453a")

# Material Icons Outlined, bundled next to this file. Home stays a circle.
_BAR_GLYPH = {
    "settings": "\uE8B8",
    "lock": "\uE897",
    "unlock": "\uE898",
    "pin": "\uF10D",
    "unpin": "\uF10D",
    "home": "\uE836",
    "min": "\uE15B",
    "close": "\uE5CD",
}


class Bridge(QObject):
    """Carries callbacks from worker threads to the GUI thread (queued signals)."""

    frame = Signal(object, object, int, int)  # receiver, pixels, width, height
    event = Signal(object, str, dict)  # receiver, name, info
    control = Signal(str, str)  # Controller.on_state(state, message)


def app_icon(size: int = 64) -> QIcon:
    ico = Path(__file__).with_name("icon.ico")
    if ico.is_file():
        icon = QIcon(str(ico))
        if not icon.isNull():
            return icon
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 64, size / 64)
    g = QLinearGradient(0, 0, 64, 64)
    g.setColorAt(0, QColor("#5e5ce6"))
    g.setColorAt(1, QColor("#bf5af2"))
    p.setBrush(g)
    p.setPen(QPen(QColor("#1c1c1e"), 3))
    p.drawRoundedRect(QRectF(16, 3, 32, 58), 9, 9)
    p.setBrush(QColor("#1c1c1e"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(26, 8, 12, 4), 2, 2)
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------- input helpers
def clamp01(v: float) -> float:
    return 0.0 if v < 0 else 1.0 if v > 1 else float(v)


def to_fraction(rect: QRectF, pos) -> tuple:
    """Window position -> (x, y) as fractions 0..1 of the phone screen rect, clamped."""
    w, h = rect.width() or 1.0, rect.height() or 1.0
    return clamp01((pos.x() - rect.x()) / w), clamp01((pos.y() - rect.y()) / h)


def swipe_seconds(held: float) -> float:
    return max(SWIPE_MIN_S, min(SWIPE_MAX_S, held))


def key_text(event) -> str:
    """Text a key press types on the iPhone: printable characters, '\\b' or '\\n' ('' = none)."""
    mods = event.modifiers()
    ctrl, alt = bool(mods & Qt.ControlModifier), bool(mods & Qt.AltModifier)
    if ctrl != alt:  # Ctrl+key / Alt+key are shortcuts; Ctrl+Alt is AltGr on Windows (still typing)
        return ""
    k = event.key()
    if k == Qt.Key_Backspace:
        return "\b"
    if k in (Qt.Key_Return, Qt.Key_Enter):
        return "\n"
    t = event.text()
    return t if t and all(c.isprintable() for c in t) else ""


def is_key(event, keys, vks=()) -> bool:
    return event.key() in keys or (bool(vks) and event.nativeVirtualKey() in vks)


def keep_wifi_in_background(target_mode, old_is_wifi, was_mirroring) -> bool:
    """The cable picture can take the window without hanging up Screen Mirroring."""
    return target_mode == "cable" and old_is_wifi and was_mirroring


def background_wifi_is_live(seconds_since_frame, limit=2.0) -> bool:
    """A recent frame means the phone is still sending the Wi-Fi picture."""
    return seconds_since_frame is not None and 0 <= seconds_since_frame < limit


def controls_are_pending(controls_open, failed, picture_busy, gestures_on) -> bool:
    """The picture is up, or on its way, and clicks are not accepted yet."""
    return bool(controls_open) and not failed and picture_busy and not gestures_on


class PhoneWindow(QWidget):
    picture_stopped = Signal()
    cable_arrived = Signal(bool)

    def __init__(self, settings, receiver_ref, controller=None):
        super().__init__()
        self.settings = settings
        self.rx = receiver_ref  # set later by main
        self.ctrl = controller  # control.Controller (optional)
        self.setWindowTitle("iPhone Mirror")
        self.setWindowIcon(app_icon())
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_AlwaysShowToolTips)
        self.setMouseTracking(True)
        self._apply_flags()

        self.image = None  # QImage of the current frame (device pixels)
        self._array = None  # keeps the ndarray behind self.image alive
        self.src_size = None
        self.aspect = DEFAULT_ASPECT
        self.state = "starting"
        self._hold_frames = False  # a frame left over after Screen Mirroring stops must not revive the picture
        self.info = {}
        self.client = None
        self.via = ""
        self.hover = False
        self._menu_open = False
        self._bar = 0.0
        self._bar_t = time.monotonic()
        self._open_receiver = None
        self._switching = False
        self._switch_again = False
        self._closing = False
        self._parked = None  # Screen Mirroring receiver kept alive behind the cable picture
        self._parked_frame_at = None
        self._parked_muted = False
        self._wifi_snap = None  # last Wi-Fi frame, so coming back is not a blank card
        self._adopt_parked = False
        self.picture_stopped.connect(self._start_switched_picture)
        self._cable_busy = False
        self._cable_left = False  # a cable that was already in does not count as plugging in
        self.cable_arrived.connect(self._on_cable)
        self._cable_timer = QTimer(self, interval=1500, timeout=self._watch_cable)
        self._cable_timer.start()
        self._pan = None
        self._wheel_axis = "y"
        self.drag_offset = None
        self.fps = 0.0
        self._frames = 0
        self._fps_t = time.time()
        self._hide_bar = QTimer(self, singleShot=True, interval=1200, timeout=self._bar_off)
        self._hover_btn = None
        self._hint_text = ""
        self._hint_until = 0.0
        self._status_hits = []
        self._zoom_acc = 0  # Ctrl+wheel delta not applied yet
        self._zoom_timer = QTimer(self, singleShot=True, interval=ZOOM_MS, timeout=self._apply_zoom)

        # iPhone control
        self.control_state = OFF  # controller state as of the last on_control (GUI thread)
        self.control_message = ""
        self._control_serial = 0  # Controller.snapshot() serial of the shown state
        self._error_serial = None  # serial of the last error already shown in the window
        self._g = None  # gesture in progress: dict(pos0, pos, t0, moved, done, double)
        self._long_timer = QTimer(self, singleShot=True, interval=int(LONG_PRESS_S * 1000), timeout=self._on_long_press)
        self._pending_tap = None  # (x, y) fractions of a click that may still become a double tap
        self._tap_timer = QTimer(self, singleShot=True, interval=DOUBLE_TAP_MS, timeout=self._flush_tap)
        self._wheel_acc = 0.0
        self._vol_acc = 0
        self._wheel_pos = (0.5, 0.5)
        self._wheel_timer = QTimer(self, singleShot=True, interval=WHEEL_BATCH_MS, timeout=self._flush_wheel)
        self._type_buf = ""
        self._type_timer = QTimer(self, singleShot=True, interval=TYPE_BATCH_MS, timeout=self._flush_type)
        self._effects = []  # touch feedback: dict(kind, a, b, t, life), positions as fractions
        self._anim = QTimer(self, interval=16, timeout=self._tick)

        screen = QApplication.primaryScreen().availableGeometry()
        ph = int(settings.get("phone_height") or 0) or int(screen.height() * 0.72)
        self.phone_h = max(320, min(ph, screen.height() - BAR - 2 * SHADOW))
        self._relayout(keep_center=False)
        x, y = settings.get("x"), settings.get("y")
        if x is not None and y is not None:
            c = QPoint(int(x) + self.width() // 2, int(y) + self.height() // 2)
            if QApplication.screenAt(c) is None:  # saved position is off-screen now
                x = y = None
        if x is None or y is None:
            x = screen.right() - self.width() - 40
            y = screen.top() + (screen.height() - self.height()) // 2
        self.move(int(x), int(y))

        self._tray = None
        self._setup_tray()

    # ------------------------------------------------------------ geometry
    def _apply_flags(self):
        flags = Qt.FramelessWindowHint | Qt.Window
        if self.settings.get("always_on_top", True):
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def phone_size(self):
        if self.aspect <= 1:  # portrait: height is the reference
            h = self.phone_h
            w = round(h * self.aspect)
        else:  # landscape: keep the same long side
            w = self.phone_h
            h = round(w / self.aspect)
        return w, h

    def phone_rect(self) -> QRectF:
        w, h = self.phone_size()
        return QRectF(SHADOW, SHADOW + BAR, w, h)

    def corner_radius(self) -> float:
        w, h = self.phone_size()
        return min(w, h) * 0.135

    def _relayout(self, keep_center=True):
        w, h = self.phone_size()
        center = self.geometry().center()
        self.setFixedSize(w + 2 * SHADOW, h + 2 * SHADOW + BAR)
        if keep_center:
            g = self.geometry()
            g.moveCenter(center)
            self.move(g.topLeft())
        self._update_target()
        self.update()

    def _update_target(self):
        if self.rx is None:
            return
        w, h = self.phone_size()
        dpr = self.devicePixelRatioF()
        self.rx.decoder.target = (round(w * dpr), round(h * dpr))

    def set_phone_height(self, h):
        screen = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        self.phone_h = int(max(320, min(h, screen.height() + 400)))
        self._relayout()
        self.settings["phone_height"] = self.phone_h

    def _toggle_size(self):
        screen = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        target = int((screen.height() - BAR - 2 * SHADOW) * (0.97 if self.aspect <= 1 else 0.55))
        if abs(self.phone_h - target) < 20:
            target = int(screen.height() * 0.6)
        self.set_phone_height(target)

    # ------------------------------------------------------------ data from receiver / controller
    def on_frame(self, rx, arr, src_w, src_h):
        if rx is self._parked:
            self._parked_frame_at = time.monotonic()
            self._wifi_snap = (arr.copy(), src_w, src_h)
            return
        if rx is not self.rx:
            return
        if self._hold_frames:
            return  # the stream already closed; this frame was still in the decoder
        h, w = arr.shape[:2]
        self._array = arr
        self.image = QImage(arr.data, w, h, arr.strides[0], QImage.Format_RGB32)
        aspect = src_w / src_h
        if self.src_size != (src_w, src_h):
            self.src_size = (src_w, src_h)
            if self.ctrl is not None:
                self.ctrl.screen_aspect = aspect  # lets the controller notice a rotation at once
            if abs(aspect - self.aspect) > 0.01:
                self.aspect = aspect
                self._relayout()
        # Cable keeps sending black frames while the phone is locked. Leave the message up.
        if self.state == "paused" and self._picture_mode() == "cable":
            pass
        elif self.state != "mirroring":
            self.state = "mirroring"
            self._flash_bar()
            if self._controls_open():
                self._ensure_control()
        self._frames += 1
        now = time.time()
        if now - self._fps_t >= 1:
            self.fps = self._frames / (now - self._fps_t)
            self._frames, self._fps_t = 0, now
        self.update()

    def on_event(self, rx, event, info):
        log.debug("ui event %s %s", event, info)
        if rx is not self.rx:
            if rx is self._parked and event == "mirror_stopped":
                self._parked_frame_at = None
                self._wifi_snap = None
            return
        if event == "listening":
            self.info = info
            self.via = "Wi-Fi"
            # Switching pictures sets "connecting" before the receiver is listening.
            # Leave it there and the Control Center steps never show.
            # A held frame is an old picture. Do not leave it up as if it were live.
            if self._hold_frames or self.state != "mirroring":
                self.state = "waiting"
                self.fps = 0.0
                self._frames = 0
                if self._hold_frames:
                    self.image = None
                    self._array = None
        elif event == "connecting":
            self._hold_frames = False
            self.client = info.get("name")
            if info.get("via"):
                self.via = info["via"]
            self.state = "connecting"
            ip = info.get("ip")
            if self.ctrl is not None and ip:
                self.ctrl.device_ip = ip  # WebDriverAgent may already listen on the phone's Wi-Fi address
        elif event == "format":
            if self.state != "mirroring":
                self.state = "connecting"
        elif event == "paused":
            self.state = "paused"
            self._cancel_gesture()
        elif event == "resumed":
            if self.state == "paused" and self.image is not None:
                self.state = "mirroring"
        elif event == "mirror_stopped":
            self._hold_frames = True
            self.state = "waiting"
            self.fps = 0.0
            self._frames = 0
            self.image = None
            self._array = None
            self.src_size = None
            if self.ctrl is not None:
                self.ctrl.screen_aspect = None
            self._drop_tap()  # the screen it was aimed at is gone
            self._cancel_gesture()
            if abs(self.aspect - DEFAULT_ASPECT) > 0.01:
                self.aspect = DEFAULT_ASPECT
                self._relayout()
        elif event == "decrypt_error":
            self.state = "decrypt_error"
        elif event == "error":
            self.state = "error"
            self.info = dict(self.info, message=info.get("message", ""))
        elif event == "unplugged":
            self.state = "unplugged"
            self.image = None
            self._array = None
            self.via = ""
            self.fps = 0.0
            self._release_finger()
        self.update()

    def on_control(self, state, message):
        """Controller state change; connected through Bridge.control, so this runs on the GUI thread.

        Notifications from the control thread are queued, while stop() on the GUI thread
        notifies directly, so they can arrive out of order. The arguments are therefore only
        a wake-up call: the controller's current state is what gets shown."""
        if self.ctrl is not None:
            state, message, serial = self.ctrl.snapshot()
        else:
            serial = self._control_serial + 1
        message = message or ""
        changed = (state, message) != (self.control_state, self.control_message)
        new_error = state == ERROR and serial != self._error_serial  # each failure once, also a repeated one
        self.control_state, self.control_message = state, message
        self._control_serial = serial
        # Cable taps, drags and the wheel use the picture stream. A helper that is
        # starting or has failed must not throw those away or claim the mouse is off.
        cable = self._direct_touch()
        if state != READY and not cable:
            self._drop_tap()
            self._cancel_gesture()
            if state != STARTING:
                self._type_buf = ""
            self._wheel_acc = 0.0
        elif state == READY and self._type_buf and self._controls_open():
            self._flush_type()
        if new_error:
            self._error_serial = serial
            log.warning("control error shown in the window: %s", (self.control_message or "").splitlines()[0])
        if (changed or new_error) and not (cable and state in (STARTING, ERROR)):
            self._hint_text = ""  # the new control status replaces any older hint
            self._flash_bar()
        self._update_anim()
        self.update()

    # ------------------------------------------------------------ painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = self.phone_rect()
        r = self.corner_radius()

        # soft shadow
        p.setPen(Qt.NoPen)
        for i in range(SHADOW, 0, -2):
            a = int(34 * (1 - i / SHADOW) ** 2) + 2
            p.setBrush(QColor(0, 0, 0, a))
            p.drawRoundedRect(rect.adjusted(-i, -i + 6, i, i + 6), r + i, r + i)

        if self.image is not None and self.state in ("mirroring", "paused", "connecting"):
            brush = QBrush(self.image)
            dpr = self.devicePixelRatioF()
            t = QTransform()
            t.translate(rect.x(), rect.y())
            t.scale(rect.width() / (self.image.width() / dpr) / dpr, rect.height() / (self.image.height() / dpr) / dpr)
            brush.setTransform(t)
            p.setBrush(brush)
            p.drawRoundedRect(rect, r, r)
            if self.state == "paused":
                p.setBrush(QColor(0, 0, 0, 150))
                p.drawRoundedRect(rect, r, r)
                self._center_text(p, rect, "iPhone is locked", "Unlock your iPhone to continue")
        else:
            self._paint_placeholder(p, rect, r)

        self._paint_touches(p, rect, r)

        # A light stroke on this edge broke into little ticks. Keep only the dark rim.
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 120), 1))
        p.drawRoundedRect(rect.adjusted(-0.5, -0.5, 0.5, 0.5), r + 0.5, r + 0.5)

        self._paint_faded_bar(p)
        p.end()

    def _paint_faded_bar(self, p):
        """Fade the bar by its pixels. setOpacity does not show on this translucent window."""
        if self._bar <= 0.004:
            return
        dpr = max(1.0, self.devicePixelRatioF())
        w, h = self.width(), int(SHADOW + BAR + 4)
        img = QImage(max(1, round(w * dpr)), max(1, round(h * dpr)), QImage.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(0)
        bp = QPainter(img)
        bp.setRenderHint(QPainter.Antialiasing)
        self._paint_bar(bp)
        bp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        bp.fillRect(QRectF(0, 0, w, h), QColor(0, 0, 0, int(self._bar * 255)))
        bp.end()
        p.drawImage(QPointF(0, 0), img)

    def _paint_placeholder(self, p, rect, r):
        g = QLinearGradient(rect.topLeft(), rect.bottomRight())
        g.setColorAt(0.0, QColor("#2b1d3f"))
        g.setColorAt(0.55, QColor("#16131f"))
        g.setColorAt(1.0, QColor("#0b0b10"))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(rect, r, r)
        glow = QRadialGradient(rect.center() + QPointF(0, -rect.height() * 0.12), rect.width() * 0.6)
        glow.setColorAt(0, QColor(140, 110, 255, 70))
        glow.setColorAt(1, QColor(140, 110, 255, 0))
        p.setBrush(glow)
        p.drawRoundedRect(rect, r, r)

        # dynamic island
        iw, ih = rect.width() * 0.32, rect.width() * 0.09
        p.setBrush(QColor("#000000"))
        p.drawRoundedRect(QRectF(rect.center().x() - iw / 2, rect.y() + rect.width() * 0.035, iw, ih), ih / 2, ih / 2)

        title, sub, actions, glyph = self._status_copy()
        if glyph:
            self._paint_status_icon(p, rect, glyph)
        self._center_text(p, rect, title, sub)
        self._paint_status_actions(p, rect, actions)

        addrs = self.info.get("addresses") or []
        if addrs and self._picture_mode() == "wifi":
            f = QFont("Segoe UI", 8)
            p.setFont(f)
            p.setPen(QColor(255, 255, 255, 90))
            p.drawText(
                QRectF(rect.x(), rect.bottom() - rect.width() * 0.16, rect.width(), 20),
                Qt.AlignHCenter,
                "PC: " + ", ".join(addrs) + "  -  iPhone and PC must be on the same Wi-Fi",
            )

    def _status_copy(self):
        """Title, body, buttons, and a Material icon for the empty phone."""
        mode = self._picture_mode()
        name = self.info.get("name") or self.settings["name"]
        other = ("cable", "Use Cable") if mode == "wifi" else ("wifi", "Use Screen Mirroring")
        wifi_steps = (
            f'On your iPhone, open Control Center, tap Screen Mirroring, and choose "{name}". '
            "The iPhone and this PC need the same Wi-Fi."
        )
        if self.state == "decrypt_error":
            return (
                "Could not decrypt the video",
                "Stop Screen Mirroring on the iPhone and start it again. If it keeps happening, open the log.",
                (("retry", "Try again"), other, ("log", "Open log")),
                "\uE001",  # error: circle with an exclamation
            )
        if self.state == "error":
            return (
                "Something went wrong",
                self.info.get("message") or "The picture stopped.",
                (("retry", "Try again"), other, ("log", "Open log")),
                "\uE001",
            )
        if mode == "wifi":
            return ("Start Screen Mirroring", wifi_steps, (("cable", "Use Cable"),), "\uE0E2")  # screen_share
        if self.state == "unplugged":
            return (
                "Unplugged",
                "Plug the iPhone into this PC. The picture starts on its own.",
                (("wifi", "Use Screen Mirroring"),),
                "\uE1E0",  # usb
            )
        return (
            "Starting the picture",
            "Keep the iPhone plugged in and unlocked.",
            (("wifi", "Use Screen Mirroring"),),
            "\uE1E0",
        )

    def _paint_status_icon(self, p, rect, glyph):
        family = self._icon_family()
        if not family:
            return
        font = QFont(family)
        font.setPixelSize(max(42, int(rect.width() * 0.24)))
        font.setStyleStrategy(QFont.NoFontMerging)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 220))
        p.drawText(
            QRectF(rect.x(), rect.y() + rect.height() * 0.30, rect.width(), rect.width() * 0.22),
            Qt.AlignCenter,
            glyph,
        )

    def _paint_status_actions(self, p, rect, actions):
        hits = []
        if not actions:
            self._status_hits = hits
            return
        w = min(rect.width() * 0.72, 240)
        h = 40
        gap = 8
        total = len(actions) * h + (len(actions) - 1) * gap
        y = rect.bottom() - rect.width() * 0.22 - total
        x = rect.center().x() - w / 2
        font = QFont("Segoe UI Semibold", 10)
        p.setFont(font)
        for i, (name, label) in enumerate(actions):
            box = QRectF(x, y + i * (h + gap), w, h)
            hits.append((name, box))
            primary = i == 0
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 230 if primary else 28))
            p.drawRoundedRect(box, 10, 10)
            p.setPen(QColor(20, 20, 24) if primary else QColor(255, 255, 255, 220))
            p.drawText(box, Qt.AlignCenter, label)
        self._status_hits = hits

    def _picture_visible(self):
        return self.image is not None and self.state in ("mirroring", "paused", "connecting")

    def _status_action_at(self, pos):
        if self._picture_visible():
            return None
        for name, box in self._status_hits:
            if box.contains(pos):
                return name
        return None

    def _status_action(self, name):
        if name == "wifi":
            self._set_picture("wifi")
        elif name == "cable":
            self._set_picture("cable")
        elif name == "retry":
            self._hint("Trying again")
            self._restart_picture()
            if self.control_state == ERROR:
                self._ensure_control()
        elif name == "log":
            self._open_log()

    def _center_text(self, p, rect, title, sub):
        w = rect.width()
        tf = QFont("Segoe UI Semibold", max(11, int(w * 0.055)))
        p.setFont(tf)
        p.setPen(QColor(255, 255, 255, 240))
        y = rect.y() + rect.height() * 0.5
        p.drawText(QRectF(rect.x() + w * 0.08, y, w * 0.84, w * 0.12), Qt.AlignHCenter | Qt.AlignTop, title)
        sf = QFont("Segoe UI", max(9, int(w * 0.034)))
        p.setFont(sf)
        p.setPen(QColor(255, 255, 255, 170))
        p.drawText(
            QRectF(rect.x() + w * 0.1, y + w * 0.12, w * 0.8, rect.height() * 0.3),
            Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
            sub,
        )

    def _paint_touches(self, p, rect, r):
        """Touch feedback: ripples for taps, a drag line only while the middle button is down."""
        pan = self._pan if self._pan is not None and self._pan.get("down") else None
        if not self._effects and pan is None:
            return
        now = time.monotonic()

        def pt(f):
            return QPointF(rect.x() + f[0] * rect.width(), rect.y() + f[1] * rect.height())

        p.save()
        clip = QPainterPath()
        clip.addRoundedRect(rect, r, r)
        p.setClipPath(clip)
        for fx in self._effects:
            k = (now - fx["t"]) / fx["life"]
            if not 0 <= k < 1:
                continue
            fade = 1 - k
            if fx["kind"] == "swipe":
                a, b = pt(fx["a"]), pt(fx["b"])
                p.setPen(QPen(QColor(255, 255, 255, int(170 * fade)), 3 + 4 * fade, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(a, b)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, int(210 * fade)))
                p.drawEllipse(b, 3 + 4 * fade, 3 + 4 * fade)
            else:
                big = fx["kind"] == "long"
                radius = 10 + (34 if big else 20) * k
                p.setPen(QPen(QColor(255, 255, 255, int(220 * fade)), 2.5 if big else 2))
                p.setBrush(QColor(255, 255, 255, int((80 if big else 60) * fade)))
                p.drawEllipse(pt(fx["a"]), radius, radius)
        if pan is not None:
            p.setPen(QPen(QColor(255, 255, 255, 110), 3, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(pan["origin"], pan["pos"])
            p.setPen(QPen(QColor(255, 255, 255, 150), 1.5))
            p.setBrush(QColor(255, 255, 255, 60))
            p.drawEllipse(pan["pos"], 11, 11)
        p.restore()

    # hover bar: [label .......... control  home  pin  -  x]
    def _bar_rect(self) -> QRectF:
        rect = self.phone_rect()
        return QRectF(rect.x() + 6, SHADOW + 2, rect.width() - 12, BAR - 10)

    def _buttons(self):
        b = self._bar_rect()
        names = ("settings", "lock", "home", "pin", "min", "close")
        gap = 8.0
        room = max(0.0, b.width() - 64)
        s = min(22.0, max(16.0, (room - gap * (len(names) - 1)) / len(names)))
        y = b.center().y() - s / 2
        right = b.right() - 8
        step = s + gap
        return {n: QRectF(right - s - (len(names) - 1 - i) * step, y, s, s) for i, n in enumerate(names)}

    def _button_at(self, pos):
        for name, r in self._buttons().items():
            if r.contains(pos):
                return name
        return None

    def _control_status(self) -> str:
        if not self._controls_open():
            return "Locked"
        if self.control_state == STARTING:
            return "Starting"
        return ""

    def _controls_pending(self) -> bool:
        busy = self.state == "connecting" or self._picture_visible()
        return controls_are_pending(
            self._controls_open(), self._lock_is_error(), busy, self._gestures_on()
        )

    def _bar_labels(self) -> list:
        """Top bar label, most detailed first; the painter uses the first one that fits."""
        if self._controls_pending():
            return ["Starting controls"]
        if self._hint_text and time.monotonic() < self._hint_until:
            return [self._hint_text]
        if self.state == "unplugged":
            return ["Unplugged"]
        name = self.client or "iPhone"
        fps = f"{self.fps:.0f} fps" if self.state == "mirroring" and self.fps else ""
        status = self._control_status()
        sep = "  ·  "
        labels = [sep.join(x for x in (self.via, name, fps, status) if x)]
        if fps:
            labels.append(sep.join(x for x in (self.via, fps) if x))
        if self.via:
            labels.append(self.via)
        if status:
            labels.append(status)
        return labels or [name]

    def _bar_label(self) -> str:
        return self._bar_labels()[0]

    def _control_color(self) -> QColor:
        st = self.control_state
        if st == READY:
            return QColor(GREEN)
        if st == STARTING:
            return self._pulse_orange()
        if st == ERROR:
            return QColor(RED)
        return QColor(255, 255, 255, 220)

    def _paint_bar(self, p):
        b = self._bar_rect()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(30, 30, 34, 225))
        p.drawRoundedRect(b, b.height() / 2, b.height() / 2)
        btn = self._buttons()

        font = QFont("Segoe UI Semibold", 11)
        p.setFont(font)
        text_rect = QRectF(b.x() + 14, b.y(), max(0.0, btn["settings"].left() - b.x() - 18), b.height())
        fm = QFontMetrics(font)
        labels = self._bar_labels()
        label = next((t for t in labels if fm.horizontalAdvance(t) <= text_rect.width()), None)
        if label is None:
            label = fm.elidedText(labels[-1], Qt.ElideRight, int(text_rect.width()))
        p.setPen(QColor(255, 255, 255, 220))
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, label)

        s = btn["close"].width()
        k = s / 30  # glyph scale
        white = QColor(255, 255, 255, 220)
        if self._icon_family():
            self._paint_glyphs(p, btn, white)
        else:
            self._paint_drawn_icons(p, btn, k, white)

    def _icon_family(self):
        name = getattr(self, "_icon_family_name", None)
        if name is None:
            path = Path(__file__).with_name("MaterialIconsOutlined-Regular.otf")
            fid = QFontDatabase.addApplicationFont(str(path))
            families = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            name = families[0] if families else ""
            self._icon_family_name = name
            if not name:
                log.warning("Material icons font did not load from %s", path)
        return name or None

    def _paint_glyphs(self, p, btn, white):
        font = QFont(self._icon_family())
        font.setPixelSize(max(16, int(btn["close"].height())))
        font.setStyleStrategy(QFont.NoFontMerging)
        p.setFont(font)
        home_on = self.image is not None and self.state == "mirroring"
        pinned = self.settings.get("always_on_top", True)
        glyphs = (
            ("settings", white),
            ("unlock" if self._controls_open() else "lock", self._lock_color()),
            ("home", white if home_on else QColor(255, 255, 255, 110)),
            ("pin" if pinned else "unpin", white if pinned else QColor(255, 255, 255, 110)),
            ("min", white),
            ("close", white),
        )
        # The lock and pin glyphs are not button names. Draw them in those slots.
        slot = {"unlock": "lock", "lock": "lock", "unpin": "pin", "pin": "pin"}
        for name, color in glyphs:
            slot_name = slot.get(name, name)
            # A hovered icon goes white. An error lock stays red so the failure stays visible.
            if self._hover_btn == slot_name and not (slot_name == "lock" and self._lock_is_error()):
                color = QColor(255, 255, 255)
            p.setPen(color)
            p.drawText(btn[slot_name], Qt.AlignCenter, _BAR_GLYPH[name])

    def _paint_drawn_icons(self, p, btn, k, white):
        """Used only when the Windows icon font is missing."""
        self._paint_gear(p, btn["settings"].center(), k, white)
        self._paint_lock(p, btn["lock"].center(), k, self._controls_open(), self._lock_color())
        d = 4.5 * k
        c = btn["home"].center()
        home_on = self.image is not None and self.state == "mirroring"
        p.setPen(QPen(white if home_on else QColor(255, 255, 255, 110), 1.6))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c, 5.6 * k, 5.6 * k)
        p.setPen(QPen(white, 1.6, Qt.SolidLine, Qt.RoundCap))
        c = btn["close"].center()
        p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
        p.drawLine(QPointF(c.x() - d, c.y() + d), QPointF(c.x() + d, c.y() - d))
        c = btn["min"].center()
        p.drawLine(QPointF(c.x() - d, c.y()), QPointF(c.x() + d, c.y()))
        c = btn["pin"].center()
        on = self.settings.get("always_on_top", True)
        p.setBrush(white if on else Qt.NoBrush)
        p.drawEllipse(QPointF(c.x(), c.y() - 1.6 * k), 3.6 * k, 3.6 * k)
        p.drawLine(QPointF(c.x(), c.y() + 2.0 * k), QPointF(c.x(), c.y() + 6.4 * k))

    def _lock_color(self) -> QColor:
        """Open, closed, or red when Screen Mirroring clicks have failed."""
        if not self._controls_open():
            return QColor(255, 255, 255, 120)
        if self._lock_is_error():
            return QColor(RED)
        if self._controls_pending() or (self.control_state == STARTING and not self._direct_touch()):
            return self._pulse_orange()
        return QColor(255, 255, 255, 230)

    def _pulse_orange(self) -> QColor:
        c = QColor(ORANGE)
        c.setAlphaF(0.35 + 0.65 * (0.5 + 0.5 * math.sin(time.monotonic() * 2 * math.pi / 1.1)))
        return c

    def _lock_is_error(self) -> bool:
        return self._controls_open() and not self._direct_touch() and self.control_state == ERROR

    def _lock_error_tip(self) -> str:
        msg = (self.control_message or "").splitlines()[0]
        if self._picture_mode() == "wifi" and "cable" in msg.lower():
            return "Clicks are off. The helper can't see the phone."
        return msg or "Clicks are off."

    @staticmethod
    def _paint_lock(p, c, k, open_, color):
        """Open lock means the mouse and keyboard reach the phone."""
        p.save()
        p.translate(c)
        p.scale(k, k)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(-4.2, -0.4, 8.4, 6.4), 1.2, 1.2)
        p.setBrush(QColor(30, 30, 34))
        p.drawEllipse(QPointF(0, 2.0), 1.05, 1.05)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(color, 1.6, Qt.SolidLine, Qt.RoundCap))
        if open_:
            p.drawArc(QRectF(-0.4, -7.2, 5.4, 5.6), 30 * 16, 220 * 16)
        else:
            p.drawArc(QRectF(-2.7, -6.2, 5.4, 5.6), 0, 180 * 16)
        p.restore()

    @staticmethod
    def _paint_gear(p, c, k, color):
        """Filled gear. A stroked one disappears at this size."""
        p.save()
        p.translate(c)
        p.scale(k, k)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawEllipse(QPointF(0, 0), 4.8, 4.8)
        for i in range(8):
            p.save()
            p.rotate(i * 45)
            p.drawRoundedRect(QRectF(-1.15, -7.0, 2.3, 2.8), 0.45, 0.45)
            p.restore()
        p.setBrush(QColor(30, 30, 34))
        p.drawEllipse(QPointF(0, 0), 1.9, 1.9)
        p.restore()

    def _bar_off(self):
        self.hover = False
        self._hover_btn = None
        self._bar_t = time.monotonic()
        self._update_anim()
        self.update()

    def _flash_bar(self, seconds=HINT_S):
        """Show the top bar for a moment (status changes, hints) even if the mouse is elsewhere."""
        self.hover = True
        self._bar_t = time.monotonic()
        if not self.underMouse():
            self._hide_bar.start(int(seconds * 1000))
        self._update_anim()
        self.update()

    def _hint(self, text):
        self._hint_text = text
        self._hint_until = time.monotonic() + HINT_S
        self._flash_bar()
        QTimer.singleShot(int(HINT_S * 1000) + 50, self.update)

    # ------------------------------------------------------------ animation
    def _needs_anim(self):
        fading = abs(self._bar - (1.0 if self.hover else 0.0)) > 0.004
        pulsing = self._controls_pending() or (self._bar > 0.01 and self.control_state == STARTING)
        return bool(self._effects) or fading or pulsing

    def _update_anim(self):
        if self._needs_anim() and not self._anim.isActive():
            self._anim.start()

    def _tick(self):
        now = time.monotonic()
        self._effects = [fx for fx in self._effects if now - fx["t"] < fx["life"]]
        target = 1.0 if self.hover or self._controls_pending() else 0.0
        if self._bar != target:
            dt = min(0.05, max(0.0, now - self._bar_t))
            step = dt / BAR_FADE_S
            self._bar = min(target, self._bar + step) if self._bar < target else max(target, self._bar - step)
        self._bar_t = now
        if not self._needs_anim():
            self._anim.stop()
        self.update()

    def _add_effect(self, kind, a, b=None):
        life = {"tap": 0.45, "long": 0.7, "swipe": 0.5}[kind]
        self._effects.append({"kind": kind, "a": a, "b": b, "t": time.monotonic(), "life": life})
        self._update_anim()
        self.update()

    # ------------------------------------------------------------ iPhone control
    def _control_ready(self):
        return self.ctrl is not None and self.control_state == READY

    def _direct_touch(self):
        """The cable picture has its own finger path. Screen Mirroring uses WebDriverAgent."""
        rx = self.rx
        return self.image is not None and self.state == "mirroring" and rx is not None and not getattr(rx, "has_audio", True)

    def _controls_open(self) -> bool:
        return self.settings.get("controls", "open") != "locked"

    def _gestures_on(self):
        """Mouse input goes to the iPhone while it is unlocked, on screen, and a finger path is ready."""
        return (
            self.state == "mirroring"
            and self._controls_open()
            and self._picture_visible()
            and (self._direct_touch() or self._control_ready())
        )

    def _set_controls(self, open_):
        open_ = bool(open_)
        self.settings["controls"] = "open" if open_ else "locked"
        self.settings.save()
        self._release_finger()
        if not open_:
            self._drop_tap()
            self._wheel_acc = 0.0
            self._wheel_timer.stop()
            self._type_buf = ""
            self._type_timer.stop()
            self._g = None
            self._long_timer.stop()
            if self.mouseGrabber() is self:
                self.releaseMouse()
        elif self._g is not None:
            self._cancel_gesture()
        self._hint("Unlocked" if open_ else "Locked")
        if open_:
            self._ensure_control()
        self.update()

    def _toggle_lock(self):
        self._set_controls(not self._controls_open())

    def _ensure_control(self):
        """Start typing as soon as the picture is up, so the first letter is not waiting."""
        if self.ctrl is None or self.control_state == STARTING or self.ctrl.active:
            return
        self.ctrl.start()

    def _volume(self, up):
        if self._direct_touch():
            from .usbvideo import stream_touch

            stream_touch().button("volume-up" if up else "volume-down")
            return
        if not self._control_ready():
            self._ensure_control()
            self._hint("Volume is starting")
            return
        self._flush_tap()
        self.ctrl.button("volumeUp" if up else "volumeDown")

    def _touch_at(self, kind, pos):
        from .usbvideo import stream_touch

        stream_touch().send(kind, *to_fraction(self.phone_rect(), pos))

    def _release_finger(self):
        g = self._g
        if g and g.get("live"):
            self._touch_at("release", g["pos"])
        if self._pan is not None:
            self._end_pan(self._pan["pos"], finish=False)
        if self.mouseGrabber() is self:
            self.releaseMouse()

    def _end_pan(self, pos, finish=True):
        """Lift the middle-button finger. Screen Mirroring sends one swipe when the button comes up."""
        pan, self._pan = self._pan, None
        if not pan:
            return
        origin = pan["origin"]
        moved = math.hypot(pos.x() - origin.x(), pos.y() - origin.y()) > TAP_SLOP
        if pan.get("live"):
            if pan.get("down"):
                self._touch_at("release", pos)
            if self.mouseGrabber() is self:
                self.releaseMouse()
        elif finish and self._control_ready() and moved:
            rect = self.phone_rect()
            a = to_fraction(rect, origin)
            b = to_fraction(rect, pos)
            held = time.monotonic() - pan.get("t0", time.monotonic())
            self.ctrl.swipe(a[0], a[1], b[0], b[1], swipe_seconds(held), 0.0)
        if moved:
            rect = self.phone_rect()
            self._add_effect("swipe", to_fraction(rect, origin), to_fraction(rect, pos))

    def _page_swipe(self, start, end):
        if self._direct_touch():
            from .usbvideo import stream_touch

            stream_touch().swipe(start[0], start[1], end[0], end[1])
            return
        if self._control_ready():
            self._flush_tap()
            self.ctrl.swipe(start[0], start[1], end[0], end[1], 0.2, 0.0)

    def _watch_cable(self):
        if self._closing or self._switching or self._cable_busy or self._picture_mode() != "wifi":
            return
        self._cable_busy = True
        threading.Thread(target=self._probe_cable, name="cable-watch", daemon=True).start()

    def _probe_cable(self):
        try:
            from .usbvideo import usb_present

            present = usb_present()
        except Exception:
            present = False
        self.cable_arrived.emit(present)

    def _on_cable(self, present):
        self._cable_busy = False
        if not present:
            self._cable_left = True
            return
        # Only a cable that arrives while Screen Mirroring is up returns to the cable picture.
        if self._cable_left and not self._closing and not self._switching and self._picture_mode() == "wifi":
            self._hint("Cable connected")
            self._set_picture("cable")

    def _toggle_control(self):
        if self.ctrl is None:
            self._hint("iPhone control is not available")
        elif self.ctrl.active:  # the controller's own state: the shown one may lag behind
            self.ctrl.stop()
        else:
            self.ctrl.start()

    def _phone(self, method, *args):
        """Send a command (home, app_switcher, button) to the iPhone, or explain why not."""
        if not self._control_ready():
            if self.ctrl is None:
                self._hint("iPhone control is not available")
            elif self.control_state == STARTING:
                self._hint("iPhone control is still starting...")
            else:
                self._hint("Turn on iPhone control first (Ctrl+U)")
            return
        self._flush_tap()
        getattr(self.ctrl, method)(*args)

    def _gesture_begin(self, pos, double=False):
        """Left button: tap, double tap, or long press. A move is not a drag."""
        self._g = {
            "pos0": QPointF(pos),
            "pos": QPointF(pos),
            "t0": time.monotonic(),
            "moved": False,
            "done": False,
            "double": double,  # second press of a double-click whose first click is still held back
        }
        self.grabMouse()
        self._long_timer.start()
        self.update()

    def _send_tap(self, xy):
        if self._direct_touch():
            from .usbvideo import stream_touch

            stream_touch().send("tap", *xy)
            return
        if self._control_ready():
            self.ctrl.tap(*xy)

    def _send_double(self, xy):
        if self._direct_touch():
            from .usbvideo import stream_touch

            stream_touch().double_tap(*xy)
            return
        if self._control_ready():
            self.ctrl.double_tap(*xy)

    def _send_long(self, xy):
        if self._direct_touch():
            from .usbvideo import stream_touch

            stream_touch().long_press(*xy)
            return
        if self._control_ready():
            self.ctrl.long_press(*xy)

    def _cancel_gesture(self):
        self._release_finger()
        self._g = None
        self._long_timer.stop()
        if self._pending_tap is not None and not self._tap_timer.isActive():
            self._flush_tap()  # its double-click will not complete now

    def _flush_tap(self):
        """Send the held-back click as a single tap (no second click came in time)."""
        self._tap_timer.stop()
        if not self._controls_open():
            self._pending_tap = None
            return
        a, self._pending_tap = self._pending_tap, None
        if a is not None:
            self._send_tap(a)

    def _drop_tap(self):
        self._tap_timer.stop()
        self._pending_tap = None

    def _on_long_press(self):
        g = self._g
        if g is None or g["moved"] or g["done"]:
            return
        if not self._direct_touch() and not self._control_ready():
            return
        g["done"] = True
        self._flush_tap()  # a click before this press stays a tap of its own
        a = to_fraction(self.phone_rect(), g["pos0"])
        self._send_long(a)
        self._add_effect("long", a)

    def _gesture_end(self, pos):
        g, self._g = self._g, None
        self._long_timer.stop()
        if self.mouseGrabber() is self:
            self.releaseMouse()
        if not self._direct_touch() and not self._control_ready():
            self._drop_tap()
            self.update()
            return
        if g["done"]:
            self.update()
            return
        a = to_fraction(self.phone_rect(), g["pos0"])
        held = time.monotonic() - g["t0"]
        if g["moved"]:
            # Past the slop this was not a click. Do not tap and do not drag.
            self._flush_tap()
            self.update()
            return
        if held >= LONG_PRESS_S:  # the timer did not get to run (busy event loop)
            self._flush_tap()
            self._send_long(a)
            self._add_effect("long", a)
        elif g["double"] and self._pending_tap is not None:
            first = self._pending_tap
            self._drop_tap()
            self._send_double(first)  # both taps in one go, at the first click's position
            self._add_effect("tap", first)
        else:
            # hold the tap back briefly: a second click turns it into a double tap
            self._flush_tap()
            self._pending_tap = a
            self._tap_timer.start()
            self._add_effect("tap", a)

    def _flush_wheel(self):
        if not self._controls_open():
            self._wheel_acc = 0.0
            return
        n, self._wheel_acc = self._wheel_acc, 0.0
        if abs(n) < 0.02:
            return
        if self._direct_touch():
            from .usbvideo import stream_touch

            x, y = self._wheel_pos
            log.info("wheel flush notches=%.2f axis=%s", n, self._wheel_axis)
            stream_touch().scroll_notches(x, y, n, self._wheel_axis)
            return
        if self._control_ready():
            self._flush_tap()  # keep the order: a click made before the scroll goes first
            self.ctrl.scroll(self._wheel_pos[0], self._wheel_pos[1], n, self._wheel_axis)

    def _type(self, text):
        self._type_buf += text
        if not self._type_timer.isActive():
            self._type_timer.start()

    def _flush_type(self):
        text, self._type_buf = self._type_buf, ""
        if not text or not self._controls_open():
            return
        if self._control_ready():
            self._flush_tap()  # the click that focused a text field must arrive before the text
            self.ctrl.type_text(text)
            return
        if self.ctrl is None:
            self._hint("Typing is not available")
            return
        self._type_buf = text
        self._ensure_control()

    def _update_cursor(self, pos):
        touch = (
            self._gestures_on()
            and self.phone_rect().contains(pos)
            and not (QApplication.keyboardModifiers() & Qt.AltModifier)
        )
        want = Qt.PointingHandCursor if touch else Qt.ArrowCursor
        if self.cursor().shape() != want:
            self.setCursor(want)

    # ------------------------------------------------------------ input
    def enterEvent(self, e):
        self._hide_bar.stop()
        self.hover = True
        self._bar_t = time.monotonic()
        self._update_anim()
        self.update()

    def leaveEvent(self, e):
        # The settings menu is its own window, so opening it looks like the mouse left.
        if self._menu_open:
            return
        self._hide_bar.stop()
        self.hover = False
        self._hover_btn = None
        self._bar_t = time.monotonic()
        self._update_anim()
        self.update()

    def event(self, e):
        if e.type() == QEvent.ToolTip:
            name = self._button_at(QPointF(e.pos())) if self.hover else None
            if name:
                QToolTip.showText(e.globalPos(), self._button_tip(name), self)
            else:
                QToolTip.hideText()
                e.ignore()
            return True
        return super().event(e)

    def _button_tip(self, name):
        if name == "lock":
            if self._lock_is_error():
                return self._lock_error_tip()
            if self._controls_pending():
                return "Starting controls"
            if self._controls_open():
                return "Unlocked. Click to ignore the mouse and keyboard (Ctrl+U)"
            return "Locked. Click to control the phone (Ctrl+U)"
        return {
            "settings": "Settings",
            "home": "Home (Ctrl+H)",
            "pin": "Pinned. It stays put and on top." if self.settings.get("always_on_top", True) else "Pin. It stays put and on top.",
            "min": "Minimize",
            "close": "Hide. It keeps running in the tray.",
        }[name]

    def mousePressEvent(self, e):
        pos = e.position()
        if e.button() == Qt.MiddleButton and self._g is None and self._gestures_on() and self.phone_rect().contains(pos):
            self._pan = {
                "pos": QPointF(pos),
                "origin": QPointF(pos),
                "t0": time.monotonic(),
                "live": self._direct_touch(),
                "down": False,
            }
            if self._pan["live"]:
                self.grabMouse()
            return
        if e.button() != Qt.LeftButton:
            return
        action = self._status_action_at(pos)
        if action:
            self._status_action(action)
            return
        if self.hover:
            name = self._button_at(pos)
            if name:
                self._button(name)
                return
        alt = bool(e.modifiers() & Qt.AltModifier)
        if self._gestures_on() and not alt and self.phone_rect().contains(pos):
            self._gesture_begin(pos)
            return
        if self.state != "paused" and self._picture_visible() and self._controls_open() and not alt and self.phone_rect().contains(pos):
            # The picture is up, but the finger path is not. A click here used to drag the window.
            if self.control_state in (ERROR, OFF):
                self._ensure_control()
            return
        if self.settings.get("always_on_top", True):
            return  # the pin is the original always-on-top switch, and it also holds the window still
        self.drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if not self.hover and self.rect().contains(QPoint(int(pos.x()), int(pos.y()))):
            self._hide_bar.stop()
            self.hover = True
            self._bar_t = time.monotonic()
            self._update_anim()
        if self._pan is not None and e.buttons() & Qt.MiddleButton:
            origin = self._pan["origin"]
            self._pan["pos"] = QPointF(pos)
            if not self._pan["down"]:
                if math.hypot(pos.x() - origin.x(), pos.y() - origin.y()) <= TAP_SLOP:
                    return
                self._pan["down"] = True
                if self._pan.get("live"):
                    self._touch_at("contact", origin)
            if self._pan.get("live"):
                self._touch_at("contact", pos)
            self.update()
            return
        g = self._g
        if g is not None:
            g["pos"] = QPointF(pos)
            if not g["moved"] and not g["done"]:
                d = pos - g["pos0"]
                if math.hypot(d.x(), d.y()) > TAP_SLOP:
                    g["moved"] = True
                    self._long_timer.stop()
            self.update()
            return
        if self.drag_offset is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self.drag_offset)
            return
        name = self._button_at(pos) if self.hover else None
        if name != self._hover_btn:
            self._hover_btn = name
            if name:
                QToolTip.showText(e.globalPosition().toPoint(), self._button_tip(name), self)
            else:
                QToolTip.hideText()
            self.update()
        self._update_cursor(pos)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MiddleButton:
            self._end_pan(e.position())
            return
        if e.button() != Qt.LeftButton:
            return
        if self._g is not None:
            self._gesture_end(e.position())
            return
        if self.drag_offset is not None:
            self.drag_offset = None
            self._save_pos()

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        pos = e.position()
        if self._status_action_at(pos) or (self.hover and self._button_at(pos)):
            return  # the first click already pressed the button
        alt = bool(e.modifiers() & Qt.AltModifier)
        if self._gestures_on() and not alt and self.phone_rect().contains(pos):
            # second press of a double-click. If the first click is still held back, both are
            # sent together as a double tap on release; if it already went out, this is a tap.
            double = self._tap_timer.isActive()
            self._tap_timer.stop()  # keep the first click until this press ends
            self._gesture_begin(pos, double=double)
            return
        self._toggle_size()

    def _apply_zoom(self):
        """Resize by the Ctrl+wheel delta collected so far, then wait ZOOM_MS before the next step."""
        dy, self._zoom_acc = self._zoom_acc, 0
        if dy:
            self.set_phone_height(round(self.phone_h * ZOOM_PER_NOTCH ** (dy / 120)))
            self._zoom_timer.start()

    def wheelEvent(self, e):
        dx, dy = e.angleDelta().x(), e.angleDelta().y()
        if not dx and not dy:
            # A precision wheel reports pixels and leaves the angle at zero.
            px, py = e.pixelDelta().x(), e.pixelDelta().y()
            dx, dy = px * 3, py * 3
        if e.modifiers() & Qt.ControlModifier:
            if dy:
                self._zoom_acc += dy  # proportional: a touchpad pinch sends many small deltas
                if not self._zoom_timer.isActive():
                    self._apply_zoom()
            return
        if self.hover and self._bar_rect().contains(e.position()):
            self._vol_acc += dy
            while self._vol_acc >= 120:
                self._vol_acc -= 120
                self._volume(True)
            while self._vol_acc <= -120:
                self._vol_acc += 120
                self._volume(False)
            return
        if self.state != "paused" and self._picture_visible() and self._controls_open() and not self._gestures_on() and self.phone_rect().contains(e.position()):
            if self.control_state in (ERROR, OFF):
                self._ensure_control()
            return
        if not self._gestures_on() or not self.phone_rect().contains(e.position()):
            return
        amount, axis = (dx, "x") if abs(dx) > abs(dy) else (dy, "y")
        if not amount:
            return
        if self._wheel_timer.isActive() and axis != self._wheel_axis:
            self._flush_wheel()
        if not self._wheel_timer.isActive():
            self._wheel_pos = to_fraction(self.phone_rect(), e.position())
            self._wheel_axis = axis
            self._wheel_timer.start()
        self._wheel_acc += amount / 120  # > 0: wheel rotated away from the user, or to the right

    def keyPressEvent(self, e):
        mods = e.modifiers()
        if (mods & Qt.ControlModifier) and not (mods & Qt.AltModifier):
            rep = e.isAutoRepeat()
            if is_key(e, (Qt.Key_Plus, Qt.Key_Equal), (VK_OEM_PLUS, VK_ADD)):
                self.set_phone_height(self.phone_h * 1.1)
            elif is_key(e, (Qt.Key_Minus,), (VK_OEM_MINUS, VK_SUBTRACT)):
                self.set_phone_height(self.phone_h / 1.1)
            elif is_key(e, (Qt.Key_Up,)):
                self._volume(True)
            elif is_key(e, (Qt.Key_Down,)):
                self._volume(False)
            elif rep:
                pass  # Home / App Switcher / toggles: once per key press
            elif is_key(e, (Qt.Key_H,), (VK_H,)):
                self._home()
            elif is_key(e, (Qt.Key_J,), (VK_J,)):
                self._phone("app_switcher")
            elif is_key(e, (Qt.Key_M,), (VK_M,)):
                self._toggle_mute()
            elif is_key(e, (Qt.Key_U,), (VK_U,)):
                self._toggle_lock()
            else:
                super().keyPressEvent(e)
            return
        if not self._controls_open():
            super().keyPressEvent(e)
            return
        if (
            not e.isAutoRepeat()
            and not (mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))
            and e.key() in _ARROW_SWIPE
            and self._gestures_on()
        ):
            start, end = _ARROW_SWIPE[e.key()]
            self._page_swipe(start, end)
            return
        text = key_text(e)
        if text:
            self._type(text)
            return
        super().keyPressEvent(e)

    def contextMenuEvent(self, e):
        self._cancel_gesture()
        self._open_menu(e.globalPos())

    def _picture_mode(self) -> str:
        from .config import picture_mode

        return picture_mode(self.settings)

    def _open_menu(self, global_pos):
        self._menu_open = True
        self.hover = True
        self._hide_bar.stop()
        try:
            self._exec_menu(global_pos)
        finally:
            self._menu_open = False
            if not self.underMouse():
                self.hover = False
                self._hover_btn = None
                self._bar_t = time.monotonic()
                self._update_anim()
            self.update()

    def _exec_menu(self, global_pos):
        m = QMenu(self)
        picture = m.addMenu("Picture")
        group = QActionGroup(picture)
        group.setExclusive(True)
        current = self._picture_mode()
        for label, mode, tip in (
            ("Cable", "cable", "Fast picture while the phone is plugged in. Unplugging stops it. No sound."),
            ("Screen Mirroring", "wifi", "The Wi-Fi picture, with sound. Plugging in a cable switches back."),
        ):
            action = QAction(label, picture, checkable=True, checked=current == mode, toolTip=tip)
            action.setData(mode)
            group.addAction(action)
            picture.addAction(action)
        group.triggered.connect(lambda action: self._set_picture(action.data()))
        m.addSeparator()
        ready = self._control_ready()
        ctl = QAction("Mouse and keyboard\tCtrl+U", m, checkable=True, checked=self._controls_open())
        ctl.triggered.connect(self._set_controls)
        m.addAction(ctl)
        home = m.addAction("Home\tCtrl+H", self._home)
        home.setEnabled(self.image is not None or ready)
        switcher = m.addAction("App Switcher\tCtrl+J", lambda: self._phone("app_switcher"))
        switcher.setEnabled(ready)
        m.addAction("Volume Up\tCtrl+Up", lambda: self._volume(True))
        m.addAction("Volume Down\tCtrl+Down", lambda: self._volume(False))
        m.addSeparator()
        top = QAction("Pin", m, checkable=True, checked=self.settings.get("always_on_top", True))
        top.setToolTip("Stays put, and stays on top.")
        top.triggered.connect(lambda: self._button("pin"))
        m.addAction(top)
        has_audio = getattr(self.rx, "has_audio", True)
        snd = QAction("Sound\tCtrl+M", m, checkable=True, checked=has_audio and not (self.rx and self.rx.muted))
        snd.setEnabled(has_audio)
        if not has_audio:
            snd.setToolTip("Sound is on Screen Mirroring.")
        snd.triggered.connect(self._toggle_mute)
        m.addAction(snd)
        size = m.addMenu("Size")
        screen = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        for label, k in (("Small", 0.5), ("Medium", 0.72), ("Large", 0.92)):
            size.addAction(label, lambda k=k: self.set_phone_height(screen.height() * k))
        m.addSeparator()
        m.addAction("Save Screenshot", self.screenshot)
        m.addAction("Rename PC...", self._rename)
        m.addAction("Open Log", self._open_log)
        m.addSeparator()
        m.addAction("Quit", self._quit_app)
        m.exec(global_pos)

    def _set_picture(self, mode):
        if mode not in ("auto", "cable", "wifi") or mode == self._picture_mode():
            return
        self.settings["picture"] = mode
        self.settings.data.pop("backend", None)
        self.settings.save()
        words = {"auto": "Cable", "cable": "Cable", "wifi": "Screen Mirroring"}
        self._hint(words[mode])
        if mode == "wifi":
            self._cable_left = False
        self._restart_picture()

    def _restart_picture(self):
        if not self._open_receiver or self._closing:
            return
        if self._switching:
            self._switch_again = True
            return
        self._switching = True
        self._switch_again = False
        self._hold_frames = True
        self.fps = 0.0
        self._frames = 0
        self.via = ""
        self._release_finger()
        old = self.rx
        target = self._picture_mode()
        old_is_wifi = old is not None and getattr(old, "has_audio", True)
        extra = None
        self._adopt_parked = False
        if keep_wifi_in_background(target, old_is_wifi, self.state == "mirroring"):
            self._parked = old
            self._parked_frame_at = time.monotonic()
            self._parked_muted = bool(getattr(old, "muted", False))
            if self._array is not None and self.src_size:
                self._wifi_snap = (self._array.copy(), self.src_size[0], self.src_size[1])
            try:
                old.set_muted(True)
            except Exception:
                log.exception("mute behind the cable picture failed")
            old = None
        elif target == "wifi" and self._background_wifi_live():
            parked = self._parked
            self._parked = None
            self.rx = parked
            try:
                parked.set_muted(self._parked_muted)
            except Exception:
                log.exception("unmute failed")
            self._hold_frames = False
            self.via = "Wi-Fi"
            self.state = "mirroring"
            self._update_target()
            snap = self._wifi_snap
            if snap is not None:
                arr, src_w, src_h = snap
                self.on_frame(parked, arr, src_w, src_h)
            self._adopt_parked = True

            def finish():
                try:
                    if old is not None:
                        old.stop()
                finally:
                    self.picture_stopped.emit()

            threading.Thread(target=finish, name="picture-switch", daemon=True).start()
            return
        elif self._parked is not None:
            extra = self._parked
            self._parked = None
            self._parked_frame_at = None
            self._wifi_snap = None
        self.state = "connecting"
        self.image = None
        self._array = None
        self._hint("Switching picture...")

        def work():
            try:
                if old is not None:
                    old.stop()
                if extra is not None:
                    extra.stop()
            finally:
                self.picture_stopped.emit()

        threading.Thread(target=work, name="picture-switch", daemon=True).start()

    def _background_wifi_live(self) -> bool:
        if self._parked is None or self._parked_frame_at is None:
            return False
        return background_wifi_is_live(time.monotonic() - self._parked_frame_at)

    def _start_switched_picture(self):
        if self._closing:
            self._switching = False
            return
        if self._adopt_parked:
            self._adopt_parked = False
            self._switching = False
            if self._switch_again:
                self._switch_again = False
                self._restart_picture()
            return
        self._adopt_parked = False
        self.rx = self._open_receiver()
        self._update_target()
        self.rx.start()
        self._switching = False
        if self._switch_again:
            self._switch_again = False
            self._restart_picture()

    def _button(self, name):
        if name == "close":
            self._hide_to_tray()
        elif name == "min":
            self.showMinimized()
        elif name == "settings":
            btn = self._buttons()["settings"]
            self._open_menu(self.mapToGlobal(btn.bottomLeft().toPoint()))
        elif name == "lock":
            self._toggle_lock()
        elif name == "home":
            self._home()
        elif name == "pin":
            on = not self.settings.get("always_on_top", True)
            self.settings["always_on_top"] = on
            self.settings.save()
            pos = self.pos()
            self._apply_flags()
            self.move(pos)
            self.show()
        self.update()

    def _rename(self):
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(
            self, "PC Name", "Name of this PC in Screen Mirroring on the iPhone:", text=self.settings["name"]
        )
        name = name.strip()
        if ok and name and self.rx:
            self.rx.rename(name)
            self.info = dict(self.info, name=name)
            self.update()

    def _toggle_mute(self):
        if self.rx and not getattr(self.rx, "has_audio", True):
            self._hint("Sound is on Screen Mirroring")
            return
        if self.rx:
            self.rx.set_muted(not self.rx.muted)
            self._hint("Sound off" if self.rx.muted else "Sound on")

    def _open_log(self):
        from .config import LOG_FILE

        if LOG_FILE.exists():
            os.startfile(str(LOG_FILE))

    def screenshot(self):
        frame = getattr(self.rx.decoder, "last_frame", None) if self.rx else None
        if frame is None:
            self._hint("Nothing to save yet")
            return
        try:
            arr = frame.to_ndarray(format="bgra")
            img = QImage(arr.data, arr.shape[1], arr.shape[0], arr.strides[0], QImage.Format_RGB32).copy()
            folder = Path.home() / "Pictures" / "iPhone Mirror"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / time.strftime("iPhone %Y-%m-%d %H-%M-%S.png")
            img.save(str(path))
            if self._tray:
                self._tray.showMessage("Screenshot saved", str(path), app_icon(), 3000)
            else:
                self._hint("Screenshot saved")
        except Exception:
            log.exception("screenshot failed")

    def _save_pos(self):
        self.settings["x"], self.settings["y"] = self.x(), self.y()
        self.settings.save()

    def moveEvent(self, e):
        self._update_target()

    def _home(self):
        if self._direct_touch():
            from .usbvideo import stream_touch

            stream_touch().button("home")
            return
        self._phone("home")

    def focusOutEvent(self, e):
        self._cancel_gesture()
        super().focusOutEvent(e)

    def closeEvent(self, e):
        if not self._really_quit and self._tray is not None:
            e.ignore()
            self._hide_to_tray()
            return
        self._closing = True
        self._release_finger()
        self._save_pos()
        super().closeEvent(e)

    def _hide_to_tray(self):
        if self._tray is None:
            self._quit_app()
            return
        self.hide()
        if not self._tray_noted:
            self._tray_noted = True
            self._tray.showMessage(
                "iPhone Mirror",
                "Still running. Right-click the icon to quit.",
                app_icon(),
                4000,
            )

    def _quit_app(self):
        self._really_quit = True
        self._closing = True
        self._release_finger()
        self._save_pos()
        QApplication.quit()

    # ------------------------------------------------------------ tray
    def _setup_tray(self):
        self._really_quit = False
        self._tray_noted = False
        if not QSystemTrayIcon.isSystemTrayAvailable():
            QApplication.instance().setQuitOnLastWindowClosed(True)
            return
        tray = QSystemTrayIcon(app_icon(), self)
        tray.setToolTip("iPhone Mirror")
        menu = QMenu()
        menu.addAction("Show Window", self._show_front)
        menu.addAction("Quit", self._quit_app)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: self._show_front() if reason == QSystemTrayIcon.Trigger else None)
        tray.show()
        self._tray = tray
        self._tray_menu = menu  # the tray does not take ownership of the menu

    def _show_front(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
