# iPhone Mirror for Windows

One floating iPhone window. Plug in for the sharp picture. Choose Screen Mirroring when you want sound. Both pictures use the same gestures.

This is a working copy of [0xCodez/iphone-mirror-windows](https://github.com/0xCodez/iphone-mirror-windows), changed in November 2026. The cable picture is new. The click helper starts on its own. The notes for this copy are in [docs/WINDOWS.md](docs/WINDOWS.md).

## What you need

- Windows 10 or Windows 11
- [Python](https://www.python.org/downloads/) 3.11 or newer. During setup, tick **Add python.exe to PATH**.
- The iPhone and the PC on the same Wi-Fi, set to **Private** in Windows

For clicks, typing, and the cable picture you also need:

- a USB cable
- [iTunes](https://www.apple.com/itunes/) and [iCloud](https://www.apple.com/icloud/) from apple.com. Sideloadly needs both. The Microsoft Store app named Apple Devices does not see the phone over Wi-Fi.
- [Sideloadly](https://sideloadly.io)
- an Apple ID. A free one is enough. The signature lasts about 7 days, then Sideloadly has to sign the helper again.
- Developer Mode on the iPhone

The cable picture needs iOS 27 or later. On an older phone, use Screen Mirroring.

You can watch Screen Mirroring with no clicks after Python, `install.bat`, and the firewall prompt. Clicks and typing need the helper below.

## Set up

1. Download this repository and put it in a folder you will keep, for example `C:\Apps\iphone-mirror`. Double-click `install.bat`.

   `install.bat` checks Python, creates `%LOCALAPPDATA%\iPhoneMirror\venv`, installs `requirements.txt`, and adds an **iPhone Mirror** shortcut on the Desktop and in the Start menu. The shortcut uses `pythonw`, so no console window opens. If you move the folder later, run `install.bat` again. `run.bat` starts the same window without a shortcut.

2. Start **iPhone Mirror**. The first time, Windows Firewall asks about Python. Tick **Private networks** and allow it. In Windows, set the Wi-Fi profile to Private: Settings > Network & internet > Wi-Fi > your network > **Private**.

3. Install iTunes and iCloud from apple.com. Plug in the iPhone, unlock it, and tap **Trust**.

4. Turn on Developer Mode. In the repository folder, run:

   ```bat
   control.bat reveal-dev-mode
   ```

   On the iPhone: Settings > Privacy & Security > **Developer Mode**. Turn it on. The phone restarts. Unlock it and confirm **Turn On** again.

5. Build the helper and sign it once:

   ```bat
   control.bat get-wda
   ```

   That saves `WebDriverAgentRunner.ipa` in your Downloads folder. Open Sideloadly, choose the iPhone and that file, enter your Apple ID, and start. Then on the iPhone: Settings > General > **VPN & Device Management**, tap your Apple ID under Developer App, and tap **Trust**.

6. Check the setup:

   ```bat
   control.bat doctor
   ```

   Fix what it reports until the checks pass.

7. Open the window and leave the lock open. When a picture is up, the window starts the helper. You do not open Sideloadly every day. When the free signature dies, about every 7 days, sign the same file in Sideloadly again.

The phone may show **automation running** while the helper is up. Hold both volume buttons on the phone to stop it.

## Use it

Plug the phone in. The cable picture starts on its own. It is the phone's own pixels, and it is silent on Windows. Unplugging leaves the window on **Unplugged**, with a **Use Screen Mirroring** button. The window does not switch by itself. Plugging the cable back in starts the cable picture again.

While the cable picture is up, the phone's camera and microphone are in use. Unplugging gives them back.

Screen Mirroring is the picture with sound. Open it from the gear, from a right-click > **Picture**, or from **Use Screen Mirroring**. On the iPhone: Control Center > Screen Mirroring > **PC**. Rename it with right-click > **Rename PC...** if you want a different name. A name that matches the computer is switched back to PC on the next launch. The phone and the PC have to be on the same Wi-Fi.

Plug the cable in while Screen Mirroring is showing, and the window returns to the cable picture. Choose Screen Mirroring from the gear while the cable is already plugged in, and the window stays on Screen Mirroring. If that picture was still connected, it can already be moving when you come back.

The top bar appears when the pointer is over the window. It shows the picture, the phone name, and the frame rate. While clicks are still starting, the bar says **Starting controls** and the lock pulses. When they are ready, the normal label comes back. If the helper fails, the lock turns red. Hover it for the reason. The bar does not print the error.

From left to right the bar is the label, the gear, the lock, Home, the pin, minimize, and close. The gear and a right-click open the same menu.

The bright pin keeps the window on top and refuses a drag. Click the pin dim, then drag the top bar, or hold Alt and drag, to move the window. The X and Alt+F4 hide the window to the tray. The picture keeps running. The tray icon brings the same picture back. **Quit** in the tray menu, or in the gear menu, exits. Starting the app again only focuses the window that is already open.

## Gestures

The same gestures work on both pictures. The lock has to be open. Closed, the mouse and keyboard leave the phone alone. Ctrl+U toggles the lock. It stays as you set it when you switch pictures. The default is open.

| Action | Result |
|---|---|
| Left click | Tap. A second click within a moment is a double tap, which selects text. Hold still for half a second for a long press. |
| Move more than 10 pixels with the left button down | Nothing is sent. Resize with Ctrl+scroll. |
| Middle button, then move | Drag in both directions. A white line follows in the window. |
| Middle click with no movement | Nothing |
| Wheel | Scroll up and down |
| Type | Text, on both pictures. Backspace and Enter work. |
| Arrow keys | One page swipe |
| Scroll on the top bar, Ctrl+Up, Ctrl+Down | iPhone volume |
| Ctrl+scroll, Ctrl+Plus, Ctrl+Minus | Resize the window |
| Ctrl+H | Home |
| Ctrl+J | App Switcher |
| Ctrl+M | Mute or unmute Screen Mirroring sound on the PC |

Cable taps, drags, and scrolling go through the cable. Typing uses the helper. Screen Mirroring sends every gesture through the helper, so it is slower. That gap stays.

Screen Mirroring plays through the current Windows output. There is no speaker list. The cable picture has no sound on Windows.

## Your network

The window announces **PC** on the local network. There is no password. Another phone on that Wi-Fi can choose PC and send its screen to this window.

While the helper is running, the phone accepts taps and typing from the network, also with no password. Closing the lock stops this window from sending clicks. It does not stop the helper. Hiding to the tray leaves the helper running. **Quit** closes it. Use a private network you trust. A guest network or a cafe is a poor place to leave this open.

`settings.json` holds the receiver key. It stays on the PC. Do not commit it, and do not paste the log into a public page until you have read it.

## When something is wrong

**The PC does not appear under Screen Mirroring**

- The Wi-Fi profile in Windows has to be Private.
- Python has to be allowed on private networks. Start > "Allow an app through Windows Firewall", find `pythonw.exe` and `python.exe`, and tick Private.
- The iPhone and the PC have to be on the same network. Guest Wi-Fi, AP isolation, and a VPN on either device can hide the PC.
- Quit and start the app again. It announces itself when it starts.

**Could not decrypt the video**

Stop Screen Mirroring on the iPhone and start it again. If it keeps happening, use **Open log** on the error screen, or right-click > **Open Log**.

**The iPhone is locked**

Unlock it. Mirroring continues.

**No sound**

The cable picture is silent on Windows. On Screen Mirroring, tick **Sound** in the menu or press Ctrl+M, and check the Windows output device. The phone's volume buttons change the level too.

**Clicks never start, or the lock is red**

- Read the lock tooltip.
- Run `control.bat doctor` and fix what it reports.
- A free Apple ID signature dies after about 7 days. Sign `WebDriverAgentRunner.ipa` again in Sideloadly.
- "Untrusted Developer" on the phone: Settings > General > VPN & Device Management > your Apple ID > Trust.
- Logs are in `%LOCALAPPDATA%\iPhoneMirror\`. `iphone_mirror.log` is the window. `wda_runner.log` is the helper.

Do not open a window titled `pymobiledevice3 screen`. That is a separate viewer. This app does not use it.

iOS 17.0 through 17.3 can need an administrator tunnel before clicks work. Update the phone if `doctor` says so. iOS 17.4 and later, and the cable picture on iOS 27, do not need that.

## Settings

`%LOCALAPPDATA%\iPhoneMirror\settings.json` is created the first time the window opens. Do not commit it or send it to anyone. It holds the receiver key.

Change the Screen Mirroring name from the menu. A new settings file starts on the cable picture.

| Key | Default | Meaning |
|---|---|---|
| `name` | `PC` | Name in Control Center > Screen Mirroring. The computer name is not used. |
| `picture` | `cable` | `cable` or `wifi` |
| `width`, `height` | `720`, `1560` | Screen Mirroring size requested from the phone |
| `fps` | `60` | Frame rate requested for Screen Mirroring |
| `audio` | `true` | Play Screen Mirroring sound on the PC |
| `always_on_top` | `true` | The pin. On also keeps the window from being dragged. |

The file also stores the window position. Delete it to reset. The iPhone will then see a new receiver, and you choose the PC again.

## How it works

- **Discovery.** The app advertises `_airplay._tcp` and `_raop._tcp` over mDNS, with the TXT records of an Apple TV, so the iPhone lists the PC under Screen Mirroring.
- **AirPlay.** An RTSP server on TCP port 7000 handles pairing and FairPlay. Screen Mirroring video is H.264 over TCP. Audio is AAC-ELD. PyAV decodes both. Sound plays with sounddevice.
- **Cable picture.** [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) reads the phone's own pixels over USB. That stream is HEVC. Its audio codec does not decode on Windows, so the cable picture stays silent. The library runs inside this app. You do not open pymobiledevice3's own screen window.
- **Clicks.** [WebDriverAgent](https://github.com/appium/WebDriverAgent) runs on the phone. On Screen Mirroring, every gesture goes through it. On the cable picture, taps, drags, and scrolling use the USB touch path, and typing still uses the helper. The helper starts over Wi-Fi when the phone is on this network, at port 8100 on the phone. The cable path is the fallback when that address is missing.

## Development

Use `%LOCALAPPDATA%\iPhoneMirror\venv\Scripts\python.exe`, or any Python 3.11+ with `requirements.txt` installed. Run from the repository folder.

```bat
python tests/test_fairplay.py
python tests/test_wda.py
python -m unittest tests.test_picture_switch tests.test_airplay_stop tests.test_video_discard

python -m iphone_mirror --local
python tools/fake_iphone.py 127.0.0.1 7100
```

`--local` listens on 127.0.0.1:7100, does not announce itself, skips the single-instance check, and uses a separate settings file.

| Option | Meaning |
|---|---|
| `--port N` | RTSP port. Default 7000, or 7100 with `--local`. |
| `--control` | Turn on clicks at launch |
| `--grab DIR` | Save a PNG of the window every 2 seconds |
| `--quit-after N` | Exit after N seconds |

`tools/gen_fairplay.py` regenerates the FairPlay tables from the playfair C sources shipped with UxPlay:

```bat
python tools/gen_fairplay.py path\to\UxPlay\lib
```

### Helper commands

`control.bat COMMAND` uses the app's own Python. `python -m iphone_mirror.control COMMAND` is the same thing. Add `--help` for options.

| Command | What it does |
|---|---|
| `doctor` | Check the cable, Developer Mode, and the helper. `--ip ADDRESS` also checks the helper over Wi-Fi. |
| `reveal-dev-mode` | Show the Developer Mode switch in Settings |
| `get-wda` | Save `WebDriverAgentRunner.ipa`. `--out PATH` picks a different file. The file is the current Appium build, downloaded over HTTPS, with no separate fingerprint check. |
| `start` | Start the helper and leave it running until Ctrl+C |
| `tap X Y` | Tap at X, Y, in points, on a running helper |
| `home` | Go to the Home Screen |
| `type TEXT` | Type into the focused field. `\n` is Return. `\b` is Backspace. |

`tap`, `home`, and `type` talk to `http://127.0.0.1:8100` unless you pass `--url`.

### Project layout

| Path | Contents |
|---|---|
| `iphone_mirror/ui.py` | The window |
| `iphone_mirror/airplay.py` | RTSP server and session setup |
| `iphone_mirror/video.py` | Screen Mirroring video |
| `iphone_mirror/usbvideo.py` | Cable picture |
| `iphone_mirror/audio.py` | Screen Mirroring audio |
| `iphone_mirror/control/wifi_wda.py` | The Wi-Fi helper |
| `iphone_mirror/control/` | WebDriverAgent client and cable bring-up |
| `iphone_mirror/pairing.py` | AirPlay pairing |
| `iphone_mirror/fairplay/` | FairPlay SAP, ported from playfair |
| `iphone_mirror/discovery.py` | mDNS advertisement |
| `iphone_mirror/config.py` | Settings and receiver identity |
| `tests/` | Checks that do not need a phone, plus the FairPlay vectors |
| `tools/` | Simulated iPhone, FairPlay table generator |

## Credits

- [UxPlay](https://github.com/FDH2/UxPlay), [RPiPlay](https://github.com/FD-/RPiPlay) and [shairplay](https://github.com/juhovh/shairplay), and the authors of the playfair FairPlay code they ship. The protocol handling here was checked against UxPlay.
- [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) for the cable picture and for talking to the phone.
- [Appium WebDriverAgent](https://github.com/appium/WebDriverAgent) for clicks and typing on the phone.
- [PyAV](https://github.com/PyAV-Org/PyAV) and FFmpeg for decoding.
- [PySide6](https://doc.qt.io/qtforpython-6/) for the window.
- [python-zeroconf](https://github.com/python-zeroconf/python-zeroconf) for mDNS.
- The FairPlay test vectors come from [openairplay/airplay2-receiver](https://github.com/openairplay/airplay2-receiver) and [omarroth/doubletake](https://github.com/omarroth/doubletake).
- Window icons are Material Icons Outlined, Apache-2.0. See [licenses/material-icons-outlined.md](licenses/material-icons-outlined.md).

## License

[GPL-3.0](LICENSE). The `iphone_mirror/fairplay/` module is a port of the GPL-3.0 playfair code (see [licenses/playfair-LICENSE.md](licenses/playfair-LICENSE.md)), so the whole application is GPL-3.0.

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by Apple Inc. AirPlay, iPhone, FairPlay, and iOS are trademarks of Apple Inc. Use it only with devices and content you are allowed to mirror.

Apps that use DRM, such as Netflix and Apple TV, show a black screen. The iPhone decides that.
