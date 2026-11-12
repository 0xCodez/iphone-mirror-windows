"""Persistent settings and identity (name, MAC, Ed25519 key) of the receiver."""
import json
import logging
import os
import secrets
import socket
from pathlib import Path

log = logging.getLogger(__name__)

APP_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "iPhoneMirror"
SETTINGS_FILE = APP_DIR / "settings.json"
LOG_FILE = APP_DIR / "iphone_mirror.log"
# Shown in Control Center. A computer name would identify the PC.
PUBLIC_NAME = "PC"

DEFAULTS = {
    # name shown on the iPhone in Control Center -> Screen Mirroring
    "name": "",
    # resolution requested from the iPhone. Smaller than 1080p so the Wi-Fi
    # stream stays close to live. The window is only a few hundred pixels wide.
    "width": 720,
    "height": 1560,
    "fps": 60,
    "audio": True,
    "always_on_top": True,
    # window geometry (logical pixels); 0 = automatic
    "x": None,
    "y": None,
    "phone_height": 0,
    # identity, generated on first start
    "mac": "",
    "ed25519_seed": "",
}


class Settings:
    def __init__(self, path: Path = SETTINGS_FILE, default_name: str = ""):
        self.path = path
        self.data = dict(DEFAULTS, name=default_name)
        APP_DIR.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                self.data.update(json.loads(path.read_text(encoding="utf-8")))
            except Exception as e:  # corrupt file: keep defaults, rewrite
                log.warning("settings.json unreadable (%s), using defaults", e)
        changed = False
        chosen = receiver_name(self.data.get("name") or "", socket.gethostname())
        if self.data.get("name") != chosen:
            self.data["name"] = chosen
            changed = True
        if not self.data.get("mac"):
            mac = bytearray(secrets.token_bytes(6))
            mac[0] = (mac[0] | 0x02) & 0xFE  # locally administered, unicast
            self.data["mac"] = mac.hex()
            changed = True
        if not self.data.get("ed25519_seed"):
            self.data["ed25519_seed"] = secrets.token_hex(32)
            changed = True
        if changed:
            self.save()

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v

    def get(self, k, default=None):
        return self.data.get(k, default)

    def save(self):
        try:
            self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            log.warning("could not save settings: %s", e)

    @property
    def mac_bytes(self) -> bytes:
        return bytes.fromhex(self.data["mac"])

    @property
    def device_id(self) -> str:  # aa:bb:cc:dd:ee:ff
        return ":".join(f"{b:02x}" for b in self.mac_bytes)

    @property
    def raop_prefix(self) -> str:  # AABBCCDDEEFF
        return self.mac_bytes.hex().upper()


def receiver_name(saved, hostname) -> str:
    """Name advertised to the iPhone. A blank name, or the computer's own name, becomes PC."""
    host = (hostname or "").split(".")[0]
    folded = (saved or "").casefold()
    if not saved or folded == host.casefold() or folded == (hostname or "").casefold():
        return PUBLIC_NAME
    return saved


def picture_mode(settings, force_usb=False) -> str:
    """cable = fast picture over USB only, wifi = AirPlay. Missing and auto are cable."""
    if force_usb:
        return "cable"
    if settings.get("picture") == "wifi":
        return "wifi"
    return "cable"


def _picture_mode_check():
    assert receiver_name("", "EXAMPLE-PC") == "PC"
    assert receiver_name("EXAMPLE-PC", "example-pc") == "PC"
    assert receiver_name("EXAMPLE-PC.local", "example-pc.local") == "PC"
    assert receiver_name("Living Room", "EXAMPLE-PC") == "Living Room"
    assert picture_mode({}) == "cable"
    assert picture_mode({"backend": "usb"}) == "cable"
    assert picture_mode({"picture": "auto"}) == "cable"
    assert picture_mode({"picture": "cable", "backend": "usb"}) == "cable"
    assert picture_mode({"picture": "wifi"}) == "wifi"
    assert picture_mode({}, force_usb=True) == "cable"


if __name__ == "__main__":
    _picture_mode_check()
