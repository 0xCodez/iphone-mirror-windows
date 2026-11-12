# This copy on Windows

A floating iPhone window. Plug in for the sharp picture. Pick Screen Mirroring when you want sound. One window, two pictures. This is a private working copy of [0xCodez/iphone-mirror-windows](https://github.com/0xCodez/iphone-mirror-windows). It is not a GitHub fork, because a fork of that public repo cannot stay private.

## Set up

1. Install Python 3.11 or newer from python.org and tick "Add python.exe to PATH".
2. Clone this repo and double-click `install.bat`. That creates `%LOCALAPPDATA%\iPhoneMirror\venv`, installs `requirements.txt`, and adds Desktop and Start shortcuts named iPhone Mirror.
3. For the cable picture, install iTunes and iCloud from apple.com. Sideloadly needs both. The Microsoft Store "Apple Devices" app does not find the phone over Wi-Fi. Unlock the phone and tap Trust. The cable picture needs iOS 27 or later. On an older phone, use Screen Mirroring, or the original project this copy is based on.
4. Turn on Developer Mode. `control.bat reveal-dev-mode` shows the switch. Turning it on, and the restart, happen on the phone.
5. For typing, and for mouse and keyboard while Screen Mirroring, run `control.bat get-wda`, sign that file with Sideloadly and a free Apple ID, then trust it under Settings > General > VPN & Device Management. `control.bat doctor` should pass. A free signature lasts 7 days. Leave the bar lock open. The helper starts on its own when a picture is up. `control.bat start` does the same, and that start mounts Apple's developer disk image. The home-screen line "automation running" is expected. Hold both volume buttons on the phone to stop it. The original project says unplugging usually ends that helper session. That has not been rechecked here.
6. Allow Python on private networks when Windows Firewall asks. The phone and the PC use the same Wi-Fi for Screen Mirroring.

The shortcut and `run.bat` both use `pythonw`, so no console window opens. A second launch only focuses the window that is already open. Watching over Wi-Fi, with no clicks, needs Python, `install.bat`, the firewall prompt, and Screen Mirroring. It does not need the helper.

Settings, the log, and the AirPlay identity live in `%LOCALAPPDATA%\iPhoneMirror\`. Do not commit `settings.json`. It holds the receiver key.

## The two pictures

Cable is the normal picture. It runs only while the phone is plugged into this PC. Unplugging stops the picture and does not switch to Wi-Fi. The window stays open and says Unplugged, with a Use Screen Mirroring button. Plugging the phone back in starts the cable picture again, including if Screen Mirroring was on.

Screen Mirroring is AirPlay. It starts only if you pick it or press Use Screen Mirroring. On the phone: Control Center, Screen Mirroring, then this PC's name. The waiting line uses that name. It is the computer name unless you renamed the receiver.

While the cable picture is up, the phone cannot use its camera or microphone. Unplugging is what gives them back. That release is not retested after the latest build.

## Mouse, wheel, and keys

The same rules apply on both pictures.

- Left click is a tap, a double tap, or a long press. Moving the left button more than 10 pixels does nothing.
- Middle button drags in both directions. A white line shows during that drag. A middle click with no movement does nothing.
- The wheel scrolls vertically. It can stutter. That is expected.
- A tap shows a small ripple. The line belongs to the middle button only.
- The top bar fades in when the pointer enters the window and fades out when it leaves.
- Drag the top bar, or hold Alt and drag, to move the window. A bright pin keeps the window on top and refuses that drag. Click the pin dim before moving it.
- The top-right X and Alt+F4 hide the window to the tray. The picture keeps running. Tray Quit exits. Tray Quit has not been tested.
- The bar lock replaces the hand. Open means the mouse and keyboard control the phone. Closed means they move the window instead. It stays as you set it when you switch pictures. Default is open.

Cable clicks use the USB picture's own touch path, so they do not wait for WebDriverAgent. Screen Mirroring clicks, drags, scrolls, and typing go through WebDriverAgent. That helper has to be installed, signed, trusted, and actually running. Clicks on Screen Mirroring have not been seen working yet. The last failure was the helper not running. Start it, then test again, before changing how control works.

Screen Mirroring is slower than the cable. That gap stays.

## Sound, size, and icons

The cable picture has no sound on Windows. Apple's audio decoder for that stream is macOS-only. There is no speaker picker. Screen Mirroring plays through the current Windows output. That sound check was interrupted and is not confirmed.

The cable picture is the phone's own pixels. Do not ask it for a larger frame. Screen Mirroring is a smaller AirPlay picture, on purpose, so it stays closer to live.

Icons are Material Icons Outlined, bundled beside the window code. Home is a circle from that set. The font is Apache-2.0. See `licenses/material-icons-outlined.md`.

## What is still open

Complete means the checks in `docs/superpowers/plans/2026-11-12-finish.md` pass, not a new feature. Still open: Screen Mirroring clicks with the helper actually running, sound only on Screen Mirroring, tray Quit, arrow keys, volume from the bar, resize, double-click to change size, Alt+drag while unpinned, a second launch only focusing, and the error screen (Try again, the other picture, Open log).

Two code gaps are confirmed and not fixed yet. A brand-new settings file starts on Screen Mirroring instead of the cable. Closing the lock does not throw away a tap or a wheel notch that was already waiting to be sent.

The wheel stays as it is. Wi-Fi delay stays as it is. A passcode keypad, Control Center inside the window, and a speaker picker are not part of this copy.
