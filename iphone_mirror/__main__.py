"""iPhone Mirror for Windows: AirPlay screen-mirroring receiver in an iPhone-shaped window."""
import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from . import net
from .airplay import Receiver
from .config import APP_DIR, LOG_FILE, SETTINGS_FILE, Settings, picture_mode
from .control import OFF, Controller
from .ui import Bridge, PhoneWindow, app_icon

INSTANCE_KEY = "iPhoneMirror-single-instance"
LOCAL_PORT = 7100  # --local self-tests must not collide with a normal instance on port 7000
LOCAL_SETTINGS = APP_DIR / "settings-local.json"  # ... nor overwrite its settings


def setup_logging():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    fh = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    fh.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(fh)
    if sys.stderr:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
    logging.getLogger("zeroconf").setLevel(logging.WARNING)
    try:
        import faulthandler

        # A native crash (the window vanishing with no Python error) writes its stack here.
        faulthandler.enable(open(LOG_FILE.with_name("iphone_mirror_fault.log"), "w", encoding="utf-8"), all_threads=True)
    except OSError:
        pass


def parse_args():
    p = argparse.ArgumentParser(prog="iphone_mirror")
    p.add_argument(
        "--local",
        action="store_true",
        help=f"self-test: listen on 127.0.0.1:{LOCAL_PORT} only, no mDNS, no single-instance check, "
        f"separate settings file",
    )
    p.add_argument("--port", type=int, help=f"RTSP port (default {net.PORT}, or {LOCAL_PORT} with --local)")
    p.add_argument("--usb", action="store_true", help="paint the USB/CoreDevice picture instead of AirPlay")
    p.add_argument("--control", action="store_true", help="start iPhone control (USB / WebDriverAgent) at launch")
    p.add_argument("--grab", metavar="DIR", help="self-test: save a PNG of the window every 2 s")
    p.add_argument("--quit-after", type=float, default=0, help="self-test: exit after N seconds")
    return p.parse_args()


def windows_taskbar_id():
    """Stop the taskbar from showing pythonw.exe's icon for this window."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("iPhoneMirror")
    except OSError:
        logging.getLogger(__name__).warning("could not set the Windows taskbar icon id")


def _preload_usb():
    """Load Apple's USB library on this thread, before the window pumps messages.

    The first import pulls in pywin32. Doing that on the picture thread while the
    window is opening makes Windows reject the call (0x8001010d) and the window dies.
    """
    try:
        import win32security  # noqa: F401  # pywin32. First import must happen on this thread.

        from pymobiledevice3.osu.os_utils import OsUtils

        OsUtils.create()
        from pymobiledevice3.usbmux import list_devices  # noqa: F401
    except Exception:
        logging.getLogger(__name__).warning("usb library did not load", exc_info=True)


def main():
    windows_taskbar_id()
    args = parse_args()
    if args.local:
        net.BIND_HOST = "127.0.0.1"
        net.ADVERTISE = False
        net.PORT = LOCAL_PORT
    if args.port:
        net.PORT = args.port
    setup_logging()
    app = QApplication(sys.argv[:1])
    _preload_usb()
    app.setApplicationName("iPhone Mirror")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())

    instance = None
    if not args.local:
        # one instance only: a second start just brings the window to the front
        probe = QLocalSocket()
        probe.connectToServer(INSTANCE_KEY)
        if probe.waitForConnected(300):
            probe.write(b"show")
            probe.waitForBytesWritten(300)
            return 0
        QLocalServer.removeServer(INSTANCE_KEY)
        instance = QLocalServer()
        instance.listen(INSTANCE_KEY)

    settings = Settings(LOCAL_SETTINGS if args.local else SETTINGS_FILE)
    logging.info(
        "starting, name=%r, port=%d, local=%s, pid=%d", settings["name"], net.PORT, args.local, os.getpid()
    )
    bridge = Bridge()
    # Controller.on_state runs on the control thread: hand it to the GUI thread via a queued signal
    ctrl = Controller(on_state=lambda state, message: bridge.control.emit(state, message))
    win = PhoneWindow(settings, None, ctrl)

    def open_receiver():
        mode = "wifi" if args.local else picture_mode(settings, force_usb=args.usb)
        box = {}

        def on_frame(arr, w, h, _box=box):
            bridge.frame.emit(_box.get("rx"), arr, w, h)

        def on_event(e, info, _box=box):
            bridge.event.emit(_box.get("rx"), e, info)

        if mode == "wifi":
            rx = Receiver(settings, on_frame=on_frame, on_event=on_event)
        else:
            from .usbvideo import UsbReceiver

            rx = UsbReceiver(settings, on_frame, on_event, require_usb=(mode == "cable"))
        box["rx"] = rx
        return rx

    win._open_receiver = open_receiver
    rx = open_receiver()
    win.rx = rx
    if args.local:
        rx.muted = True  # self-test: decode audio but keep the speakers silent
    bridge.frame.connect(win.on_frame)
    bridge.event.connect(win.on_event)
    bridge.control.connect(win.on_control)
    if instance is not None:
        instance.newConnection.connect(lambda: (instance.nextPendingConnection(), win._show_front()))
    win.show()
    win._update_target()
    # Start the cable check on the next turn. Starting it during the open
    # message makes Apple's USB call fail and the window closes.
    QTimer.singleShot(0, rx.start)
    if args.control:
        ctrl.start()
    if args.grab:
        grab_dir = Path(args.grab)
        grab_dir.mkdir(parents=True, exist_ok=True)
        counter = [0]

        def grab():
            counter[0] += 1
            win.grab().save(str(grab_dir / f"window_{counter[0]:02d}.png"))

        timer = QTimer(win, interval=2000, timeout=grab)
        timer.start()
    if args.quit_after:
        QTimer.singleShot(int(args.quit_after * 1000), app.quit)
    code = app.exec()
    settings.save()
    try:
        bridge.control.disconnect(win.on_control)  # the window is going away
    except (RuntimeError, TypeError):
        pass
    if ctrl.state != OFF:
        ctrl.stop()
    win._closing = True
    stopped = set()
    for live in (win.rx, getattr(win, "_parked", None), rx):
        if live is not None and live not in stopped:
            stopped.add(live)
            live.stop()
    logging.info("exit")
    return code


if __name__ == "__main__":
    sys.exit(main())
