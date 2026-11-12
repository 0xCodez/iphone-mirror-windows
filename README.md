# iPhone Mirror for Windows

iPhone Mirror turns a Windows PC into an AirPlay screen-mirroring receiver and shows your
iPhone in a frameless, rounded, iPhone-shaped window that floats on top of your other apps,
much like "iPhone Mirroring" on macOS. Picture and sound come over Wi-Fi with nothing to
install on the phone. If you also connect the iPhone with a cable once and set up
WebDriverAgent, you can control it from the PC with your mouse and keyboard.

This copy also draws the phone over the USB cable in the same window. Modified from
0xCodez/iphone-mirror-windows in November 2026. Read [docs/WINDOWS.md](docs/WINDOWS.md)
before the rest of this file. The sections below still describe the original AirPlay app
and do not match every control in this copy.

In this copy the top bar has a lock, not the old hand button. Leave the lock open and the
helper starts when a picture is showing. `control.bat start` does the same. The cable
picture needs iOS 27 or later.

## Features

- **Wireless AirPlay mirroring with sound.** The iPhone sees the PC as an AirPlay receiver
  under Control Center > Screen Mirroring. No app on the phone, no cable.
- **iPhone-shaped window.** Frameless, rounded, always on top by default, resizable, and it
  remembers its position.
- **Rotation.** When the iPhone turns to landscape, the window turns with it.
- **Screenshots.** Save the current frame as a PNG in one click.
- **Optional mouse and keyboard control over USB.** Tap, long press, swipe, scroll, type,
  Home, App Switcher and volume, all through
  [WebDriverAgent](https://github.com/appium/WebDriverAgent).

## Requirements

- Windows 10 or Windows 11
- [Python](https://www.python.org/downloads/) 3.11 or newer (check "Add python.exe to PATH"
  during setup)
- The iPhone and the PC on the same Wi-Fi network

For the optional USB control you also need:

- a USB cable for the iPhone
- **iTunes from [apple.com](https://www.apple.com/itunes/)** (it installs Apple's USB driver
  service; Sideloadly needs the apple.com version rather than the Microsoft Store apps)
- an Apple ID; a free one is enough

## Install

1. Download this repository (**Code > Download ZIP**, or `git clone`) and put it in a folder
   you will keep, for example `C:\Apps\iphone-mirror`.
2. Double-click **`install.bat`**.

`install.bat`:

- checks that Python 3.11+ is available,
- creates a private virtual environment in `%LOCALAPPDATA%\iPhoneMirror\venv`,
- installs the dependencies from `requirements.txt` into it,
- creates an **iPhone Mirror** shortcut on the Desktop and in the Start menu. The shortcut
  runs `pythonw -m iphone_mirror` from the repository folder, so no console window opens.

If you move the folder later, run `install.bat` again so the shortcuts point to the new
location. `run.bat` starts the app without a shortcut, and `control.bat` runs the USB
control helper (see below).

## Usage

1. Start **iPhone Mirror**. An iPhone-shaped window appears with the text
   **"Waiting for iPhone"**. The footer shows the PC's addresses:
   `PC: <ips>  -  iPhone and PC must be on the same Wi-Fi`.
2. **First start only:** Windows Defender Firewall asks whether Python may use the network.
   Tick **Private networks** and click **Allow**.
3. Make sure Windows treats your Wi-Fi as a **private** network:
   Settings > Network & internet > Wi-Fi > *your network* > Network profile type > **Private**.
4. On the iPhone, open **Control Center > Screen Mirroring** and choose the name of this PC
   (by default the computer name; you can change it with right-click > **Rename PC...**).
5. The window shows **"Connecting..."** and then the iPhone screen.

Only one copy of the app runs at a time: starting it again just brings the existing window
to the front.

## Window controls

Move the mouse over the window to show the **top bar**. From left to right it has:

- a label with the device name, the frame rate and the control status,
- **Control** (hand pointer icon): turns USB control on or off. White when off, pulsing
  orange while starting, green when ready, red after an error,
- **Home** (circle),
- **Pin**: keep the window always on top,
- **Minimize**,
- **Close**.

### Mirroring only (control off, the default)

| Action | What it does |
|---|---|
| Left-drag anywhere | Move the window |
| Double-click | Switch between big and normal size |
| Ctrl + mouse wheel | Resize |
| Ctrl + Plus / Ctrl + Minus | Resize |
| Right-click | Open the menu |

### With control on

These apply once control is **ready** (green Control button) and the iPhone screen is shown.
While the window shows a placeholder instead of the iPhone screen, dragging still moves the
window.

| Action on the phone area | What the iPhone gets |
|---|---|
| Click | Tap. It is sent about 0.2 s after the click, in case a second click makes it a double tap |
| Press and hold for 0.5 s or longer without moving | Long press |
| Drag | Swipe. It is sent when you release the button and lasts as long as your drag did (clamped to 0.06 - 1.5 s) |
| Double-click | Double tap (both taps are sent together, so apps see a real double tap) |
| Mouse wheel | Scroll. Wheel steps are collected for about 120 ms and sent as one scroll |
| Typing | Text input. Characters are buffered for about 80 ms; Backspace and Enter work |
| Drag the top bar, or Alt + drag anywhere | Move the window |
| Ctrl + mouse wheel | Resize |

Every tap or long press shows a short fading ripple where it landed; a swipe shows a fading
line from its start to its end.

### Keyboard shortcuts (both modes)

| Shortcut | Action |
|---|---|
| Ctrl + H | Home |
| Ctrl + J | App Switcher |
| Ctrl + Up / Ctrl + Down | iPhone volume up / down |
| Ctrl + M | Mute / unmute the sound on the PC |
| Ctrl + U | Turn USB control on / off |
| Ctrl + Plus / Ctrl + Minus | Resize the window |

Home, App Switcher and iPhone volume act on the phone, so they only do something while
control is ready. App Switcher swipes up from the bottom edge and holds on iPhones with
Face ID, and double-presses Home on iPhones with a Home button.

Ctrl + mouse wheel resizes in proportion to how far the wheel turns (about 6% per notch), so
smooth scrolling with a touchpad resizes smoothly too.

### Right-click menu

| Item | Action |
|---|---|
| Control iPhone (USB) | Turn control on or off (checkable) |
| Home | Go to the Home Screen |
| App Switcher | Open the App Switcher |
| Volume Up / Volume Down | Change the iPhone volume |
| Always on Top | Keep the window above other windows |
| Sound | Play the iPhone sound on the PC |
| Size | Small, Medium or Large |
| Save Screenshot | Save the current frame to `Pictures\iPhone Mirror` |
| Rename PC... | Change the name the iPhone shows under Screen Mirroring |
| Open Log | Open `%LOCALAPPDATA%\iPhoneMirror\iphone_mirror.log` |
| Quit | Exit the app |

If the controller reports an error, the app shows it in a non-blocking message box titled
**"iPhone control"** with the full text, and the status also appears in the top bar label.

## USB control (optional)

AirPlay only carries picture and sound. To send taps and keystrokes back, iPhone Mirror
talks to [WebDriverAgent](https://github.com/appium/WebDriverAgent) (WDA), Appium's
open-source automation server built on Apple's XCUITest, which runs as a small app on the
phone. iPhone Mirror starts it over USB with
[pymobiledevice3](https://github.com/doronz88/pymobiledevice3). No Mac is needed, and on
iOS 17.4 or later (and on iOS 16 or earlier) no administrator rights either. iOS 17.0 - 17.3
can only be controlled with administrator rights: update the iPhone, or run
`pymobiledevice3 remote tunneld` as administrator before you turn control on.

The commands below run in a terminal (Command Prompt or PowerShell) opened in the repository
folder. `control.bat` runs the helper with the app's own Python environment, so nothing has
to be activated (it is the same as `python -m iphone_mirror.control ...` inside that
environment).

1. **Connect the iPhone.** Install **iTunes from apple.com**, connect the iPhone with a
   cable, unlock it and tap **Trust** when it asks about this computer.
2. **Turn on Developer Mode.** Run

   ```bat
   control.bat reveal-dev-mode
   ```

   This makes the Developer Mode switch appear on the phone (it also appears by itself once
   WebDriverAgent is installed in step 4). Then on the iPhone go to
   Settings > Privacy & Security > **Developer Mode**, turn it on and confirm. The phone
   restarts; after the restart, unlock it and confirm **Turn On** once more.
3. **Get WebDriverAgent.** Run

   ```bat
   control.bat get-wda
   ```

   It downloads Appium's prebuilt WebDriverAgent and saves it as
   `WebDriverAgentRunner.ipa` in your `Downloads` folder.
4. **Install it on the iPhone.** Open [Sideloadly](https://sideloadly.io), select the iPhone
   and `WebDriverAgentRunner.ipa`, enter your Apple ID and start. Sideloadly signs the app
   with your Apple ID and installs it. With a **free** Apple ID the signature is valid for
   **7 days**: after that, install it again with Sideloadly (paid developer accounts last a
   year).
5. **Trust the developer profile.** On the iPhone go to Settings > General >
   **VPN & Device Management**, tap your Apple ID under "Developer App" and tap **Trust**.
6. **Check everything.** Run

   ```bat
   control.bat doctor
   ```

   and fix whatever it reports until all checks pass.
7. **Turn control on.** In the iPhone Mirror window press **Ctrl + U**, click the hand
   button in the top bar, or right-click > **Control iPhone (USB)**. The button pulses orange
   while WDA starts (the first time also downloads and mounts the Developer Disk Image, which
   can take a minute) and turns green when it is ready.

WebDriverAgent listens on port 8100 of the iPhone, and that port is reachable over Wi-Fi as
well as through the USB forward. When you turn control on, the app first looks for a WDA
that is already running, both on the USB forward and on the iPhone's Wi-Fi address, and only
starts a new one over USB if it finds none. So once WDA is up, control traffic can go over
Wi-Fi too. Keep the cable connected anyway while you work: WDA lives only as long as the test
session that launched it, and unplugging the cable usually ends that session.

### Helper commands

`control.bat COMMAND` (or `python -m iphone_mirror.control COMMAND`; add `--help` to any
command for its options):

| Command | What it does |
|---|---|
| `doctor` | Check everything USB control needs (`--ip ADDRESS` also checks WDA over Wi-Fi) |
| `reveal-dev-mode` | Make the Developer Mode switch appear in the iPhone's Settings |
| `get-wda` | Download WebDriverAgent as `WebDriverAgentRunner.ipa` (`--out PATH` to save it elsewhere) |
| `start` | Start WebDriverAgent over USB without the app and keep it running until Ctrl+C |
| `tap X Y` | Tap at X, Y (in points) on a running WDA |
| `home` | Go to the Home Screen |
| `type TEXT` | Type TEXT into the focused field (`\n` = Return, `\b` = Backspace) |

`tap`, `home` and `type` talk to `http://127.0.0.1:8100` unless you pass `--url`.

## Troubleshooting

**The PC does not appear under Screen Mirroring**

- The Wi-Fi network must be **Private** in Windows (see [Usage](#usage)).
- Python must be allowed through the firewall on private networks: Start > "Allow an app
  through Windows Firewall" > find `pythonw.exe` / `python.exe` and tick **Private**.
- The iPhone and the PC must be on the same network and subnet. Guest networks and routers
  with "client isolation" / "AP isolation" block devices from seeing each other. A VPN on
  either device can do the same.
- Restart the app; it announces itself again with mDNS when it starts.

**"Could not decrypt the video"**

Stop Screen Mirroring on the iPhone and connect again. If it keeps happening, open the log
(right-click > **Open Log**) and attach it to an issue.

**"iPhone is locked"**

Unlock the iPhone; mirroring continues on its own.

**No sound**

Check that **Sound** is ticked in the right-click menu (or press Ctrl + M) and that Windows
plays to the right output device. The iPhone's own volume buttons also control the level.

**Control does not start or stops working**

- Run `control.bat doctor` (see [USB control](#usb-control-optional)) and fix what it
  reports. The error box titled "iPhone control" shows the same message.
- A free Apple ID signature expires after 7 days: if WDA suddenly fails to launch, install
  `WebDriverAgentRunner.ipa` again with Sideloadly.
- "Untrusted Developer" on the phone: trust the profile in Settings > General >
  VPN & Device Management.
- Logs are in `%LOCALAPPDATA%\iPhoneMirror\*.log`: `iphone_mirror.log` for the app and
  `wda_runner.log` / `wda_forward.log` for the WebDriverAgent processes.

## Limitations

- **Protected content is not mirrored.** Apps that use DRM (Netflix, Apple TV and similar)
  show a black screen. The iPhone decides this, not the receiver.
- **Resolution.** Screen Mirroring asks for 720×1560 at 60 fps. The cable picture is the
  phone's own pixels and does not use that setting.
- **Control latency.** Every action is an HTTP request to WebDriverAgent, so expect about
  100-200 ms before the iPhone reacts. A single click waits about 0.2 s more, to tell it
  from a double-click.
- **No live drag.** Swipes are sent when you release the mouse button, so you cannot drag
  an item and watch it follow the pointer, or draw.
- **Control needs setup.** It requires a cable, Developer Mode and a sideloaded WDA that
  has to be re-signed every 7 days with a free Apple ID.

## Settings

`%LOCALAPPDATA%\iPhoneMirror\settings.json` is created on the first start. Useful keys:

| Key | Default | Meaning |
|---|---|---|
| `name` | computer name | Name shown on the iPhone under Screen Mirroring |
| `width`, `height` | `720`, `1560` | Screen Mirroring size requested from the iPhone |
| `fps` | `60` | Frame rate requested from the iPhone |
| `audio` | `true` | Play the iPhone sound on the PC |
| `always_on_top` | `true` | Keep the window above other windows |

The file also stores the window position and the receiver's identity (a random MAC address
and an Ed25519 key). Delete the file to reset everything; the iPhone will then see a new
receiver.

## How it works

- **Discovery.** The app advertises `_airplay._tcp` and `_raop._tcp` services over mDNS
  (python-zeroconf) with the TXT records of an Apple TV, so the iPhone lists the PC under
  Screen Mirroring.
- **Control connection.** An asyncio RTSP server on TCP port 7000 handles `GET /info`, then
  AirPlay legacy pairing: `pair-setup` and `pair-verify` with Ed25519 signatures and an
  X25519 key exchange.
- **FairPlay.** `fp-setup` runs the FairPlay SAP handshake. A pure-Python port of the
  open-source *playfair* code unwraps the 16-byte AES session key that the iPhone sends
  FairPlay-encrypted during `SETUP`.
- **Video.** The mirroring stream is H.264 over TCP, encrypted with AES-128-CTR. The key is
  derived from the FairPlay key and the pair-verify shared secret. PyAV (FFmpeg) decodes it
  on a background thread and scales frames to the window's size in device pixels.
- **Audio.** AAC-ELD over RTP/UDP, encrypted with AES-CBC, decoded with PyAV and played with
  sounddevice.
- **Window.** PySide6 (Qt) draws a frameless, translucent, rounded window with the frame,
  placeholders and controls.
- **Control.** pymobiledevice3 finds the iPhone through usbmux, checks Developer Mode, mounts
  the Developer Disk Image, launches WebDriverAgent as an XCUITest (on iOS 17+ through a
  userspace tunnel) and forwards a local port to WDA's port 8100. Mouse and keyboard input
  becomes WDA HTTP calls (taps, swipes, text, buttons).

## Development

Use the app's environment (`%LOCALAPPDATA%\iPhoneMirror\venv\Scripts\python.exe`) or any
Python 3.11+ with `requirements.txt` installed, and run everything from the repository
folder.

```bat
rem FairPlay known-answer tests (21 recorded sessions)
python tests/test_fairplay.py

rem WebDriverAgent client tests
python tests/test_wda.py

rem Full AirPlay session without an iPhone or a network:
rem the receiver listens on 127.0.0.1:7100 only and does not announce itself
python -m iphone_mirror --local
rem in a second window: a simulated iPhone that pairs, does FairPlay and streams
rem an encrypted H.264 test pattern and an AAC tone (arguments: host port seconds)
python tools/fake_iphone.py 127.0.0.1 7100
```

`--local` also skips the single-instance check and uses a separate settings file, so it can
run next to a normal copy of the app. Other options:

| Option | Meaning |
|---|---|
| `--port N` | RTSP port (default 7000, or 7100 with `--local`) |
| `--control` | Turn on iPhone control (USB / WebDriverAgent) at launch |
| `--grab DIR` | Save a PNG of the window every 2 seconds |
| `--quit-after N` | Exit after N seconds |

`tools/gen_fairplay.py` regenerates `iphone_mirror/fairplay/_tables.py` and `_garble.py` from
the playfair C sources shipped with UxPlay:

```bat
python tools/gen_fairplay.py path\to\UxPlay\lib
```

### Project layout

| Path | Contents |
|---|---|
| `iphone_mirror/airplay.py` | RTSP server, session setup, `Receiver` |
| `iphone_mirror/pairing.py` | Legacy pair-setup / pair-verify |
| `iphone_mirror/fairplay/` | Pure-Python FairPlay SAP (playfair port) |
| `iphone_mirror/video.py` | Mirror stream decryption and H.264 decoding |
| `iphone_mirror/audio.py` | RTP audio decryption, decoding and playback |
| `iphone_mirror/discovery.py` | mDNS advertisement |
| `iphone_mirror/config.py` | Settings and receiver identity |
| `iphone_mirror/ui.py` | The iPhone-shaped window |
| `iphone_mirror/control/` | WebDriverAgent client and USB bring-up |
| `tests/` | FairPlay and WDA tests |
| `tools/` | Simulated iPhone, FairPlay table generator |

## Credits

- [UxPlay](https://github.com/FDH2/UxPlay), [RPiPlay](https://github.com/FD-/RPiPlay) and
  [shairplay](https://github.com/juhovh/shairplay), and the authors of the *playfair*
  FairPlay code they ship. The protocol handling here was checked against UxPlay.
- [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) for talking to the iPhone
  over USB.
- [Appium WebDriverAgent](https://github.com/appium/WebDriverAgent) for input on the iPhone.
- [PyAV](https://github.com/PyAV-Org/PyAV) and FFmpeg for decoding.
- [PySide6](https://doc.qt.io/qtforpython-6/) (Qt for Python) for the window.
- [python-zeroconf](https://github.com/python-zeroconf/python-zeroconf) for mDNS.
- The FairPlay test vectors come from
  [openairplay/airplay2-receiver](https://github.com/openairplay/airplay2-receiver) and
  [omarroth/doubletake](https://github.com/omarroth/doubletake).

## License

[GPL-3.0](LICENSE). The `iphone_mirror/fairplay/` module is a port of the GPL-3.0 playfair
code (see [licenses/playfair-LICENSE.md](licenses/playfair-LICENSE.md)), so the whole
application is distributed under the GPL-3.0.

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by Apple Inc. AirPlay,
iPhone, FairPlay and iOS are trademarks of Apple Inc., registered in the U.S. and other
countries. Use it only with devices and content you are allowed to mirror.
