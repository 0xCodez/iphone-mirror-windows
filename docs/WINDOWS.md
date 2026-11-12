# This copy on Windows

A floating iPhone window. Plug in for the sharp picture. Pick Screen Mirroring when you want sound. One window, two pictures. These notes describe the changes on top of [0xCodez/iphone-mirror-windows](https://github.com/0xCodez/iphone-mirror-windows).

## Set up

1. Install Python 3.11 or newer from python.org and tick "Add python.exe to PATH".
2. Clone this repo and double-click `install.bat`. That creates `%LOCALAPPDATA%\iPhoneMirror\venv`, installs `requirements.txt`, and adds Desktop and Start shortcuts named iPhone Mirror.
3. For the cable picture, install iTunes and iCloud from apple.com. Sideloadly needs both. The Microsoft Store "Apple Devices" app does not find the phone over Wi-Fi. Unlock the phone and tap Trust. The cable picture needs iOS 27 or later. On an older phone, use Screen Mirroring, or the original project this copy is based on.
4. Turn on Developer Mode. `control.bat reveal-dev-mode` shows the switch. Turning it on, and the restart, happen on the phone.
5. For typing, and for mouse and keyboard while Screen Mirroring, run `control.bat get-wda`, sign that file with Sideloadly and a free Apple ID, then trust it under Settings > General > VPN & Device Management. `control.bat doctor` should pass. A free signature lasts 7 days. Leave the bar lock open. The helper starts on its own when a picture is up. `control.bat start` does the same, and that start mounts Apple's developer disk image. The home-screen line "automation running" is expected. Hold both volume buttons on the phone to stop it. The helper starts over Wi-Fi, so it keeps answering after the cable comes out. Unplugging keeps the Screen Mirroring picture where it is.
6. Allow Python on private networks when Windows Firewall asks. The phone and the PC use the same Wi-Fi for Screen Mirroring. There is no pairing password. Another phone on that Wi-Fi can choose this PC. While the helper is running, the phone accepts taps from the network with no password. Quit the app to stop the helper. Closing the lock does not.

The shortcut and `run.bat` both use `pythonw`, so no console window opens. A second launch only focuses the window that is already open. Watching over Wi-Fi, with no clicks, needs Python, `install.bat`, the firewall prompt, and Screen Mirroring. It does not need the helper.

Settings, the log, and the AirPlay identity live in `%LOCALAPPDATA%\iPhoneMirror\`. Do not commit `settings.json`. It holds the receiver key.

## The two pictures

Cable is the normal picture. It runs only while the phone is plugged into this PC. Unplugging stops the picture and does not switch to Wi-Fi. The window stays open and says Unplugged, with a Use Screen Mirroring button. Plugging the phone back in starts the cable picture again, including if Screen Mirroring was on.

Screen Mirroring is AirPlay. It starts only if you pick it or press Use Screen Mirroring. On the phone: Control Center, Screen Mirroring, then the name in the waiting line. A new install uses PC. Rename PC in the menu changes it. A saved computer name is replaced with PC on the next launch.

While the cable picture is up, the phone cannot use its camera or microphone. Unplugging gives them back.

## Mouse, wheel, and keys

The same rules apply on both pictures.

- Left click is a tap, a double tap, or a long press. Moving the left button more than 10 pixels does nothing.
- Middle button drags in both directions. A white line shows during that drag. A middle click with no movement does nothing.
- The wheel scrolls vertically. It can stutter. That is expected.
- A tap shows a small ripple. The line belongs to the middle button only.
- The top bar fades in when the pointer enters the window and fades out when it leaves.
- Drag the top bar, or hold Alt and drag, to move the window. A bright pin keeps the window on top and refuses that drag. Click the pin dim before moving it.
- The top-right X and Alt+F4 hide the window to the tray. The picture keeps running. The tray icon brings the same picture back. Quit exits.
- The bar lock replaces the hand. Open means the mouse and keyboard control the phone. Closed means they leave the phone alone. It stays as you set it when you switch pictures. Default is open.

Cable taps, drags, and scrolling use the USB picture's own touch path. Typing uses the helper on both pictures. Screen Mirroring sends every gesture through the helper. The helper starts over Wi-Fi, so those clicks keep working after the cable comes out. If the helper fails, the lock turns red.

Screen Mirroring is slower than the cable. That gap stays.

## Sound, size, and icons

The cable picture has no sound on Windows. Apple's audio decoder for that stream is macOS-only. There is no speaker picker. Screen Mirroring plays through the current Windows output. The cable picture stays silent.

The cable picture is the phone's own pixels. Do not ask it for a larger frame. Screen Mirroring is a smaller AirPlay picture, on purpose, so it stays closer to live.

Icons are Material Icons Outlined, bundled beside the window code. Home is a circle from that set. The font is Apache-2.0. See `licenses/material-icons-outlined.md`.

## What is still open

The error screen has Try again, the other picture, and Open log. It has not been walked, because it only shows up when the picture actually fails. Closing the lock is written to drop a tap, a wheel notch, or typed letters that were still waiting. That race has not been checked by hand.

A double-click selects text. It does not resize the window. The wheel stays as it is. Screen Mirroring clicks stay slower than the cable. A passcode keypad, Control Center inside the window, and a speaker picker are not part of this copy.
