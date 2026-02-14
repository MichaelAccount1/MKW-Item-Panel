# MKW Item Panel

A real-time item injector for **Mario Kart Wii** running on **Dolphin Emulator**. Give yourself any item during a race with a single click.

Works with **Retro Rewind**, **CTGP**, and vanilla MKW (PAL — RMCP01).

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **19 items** — Star, Bullet Bill, Golden Mushroom, Blue Shell, Lightning, and more
- **Hold mode** — check "Hold" and the item is continuously re-given every frame (~60 Hz), so you never lose it
- **Clear button** — instantly remove your held item
- **Auto-detect** — automatically figures out which player slot you're in
- **Always on top** — dark-themed overlay window, great for a second monitor
- **Joystick / side panel support** — auto-detects game controllers and maps buttons directly to items (no remapping software needed)
- **Configurable keyboard hotkeys** — bind any key to any item via `keybinds.json`
- **Zero setup** — just run the `.exe` while Dolphin is open

## Download

Grab the latest **`MKW-Item-Panel.exe`** from the [Releases](https://github.com/MichaelAccount1/MKW-Item-Panel/releases) page.

> Windows Defender may flag it because the app reads process memory — this is how it communicates with Dolphin. You can review the full source code in this repo.

## Usage

1. Open **Dolphin** and launch Mario Kart Wii
2. Run **MKW-Item-Panel.exe** (or `python item_panel.py`)
3. Start or join a race
4. Click any item button — it appears in your item slot instantly
5. Enable **Hold** to keep that item permanently (great for Star!)

The status indicator shows:
| Color | Meaning |
|-------|---------|
| Red | Not connected to Dolphin |
| Yellow | Connected, waiting for a race to start |
| Green | In race — ready to give items |
| Gold | Hold mode active |

## Joystick / Side Panel Support

If you have a game controller, side panel, or button box plugged in, the panel **automatically detects it** and maps its buttons to items:

| Button | Action | Button | Action |
|--------|--------|--------|--------|
| 1 | Star | 11 | Red Shell |
| 2 | Bullet Bill | 12 | 3x Red Shell |
| 3 | Golden Mushroom | 13 | Green Shell |
| 4 | Mega Mushroom | 14 | 3x Green Shell |
| 5 | Blue Shell | 15 | Banana |
| 6 | Lightning | 16 | 3x Banana |
| 7 | POW Block | 17 | Bob-omb |
| 8 | Blooper | 18 | Fake Item Box |
| 9 | Mushroom | 19 | Thunder Cloud |
| 10 | 3x Mushroom | 20 | Clear Item |
| | | 21 | Toggle Hold |

No remapping software needed — just plug in and press buttons. To disable joystick input, set `"joystick": false` in `keybinds.json`.

## Keyboard Hotkeys

On first launch, a `keybinds.json` file is created next to the exe. Edit it to bind any key to any item:

```json
{
    "joystick": true,
    "keys": {
        "Star": "f1",
        "Bullet Bill": "f2",
        "Clear": "f11",
        "Toggle Hold": "f12",
        ...
    }
}
```

Supported key names: `f1`–`f24`, `0`–`9`, `a`–`z`, `numpad0`–`numpad9`, `insert`, `delete`, `home`, `end`, `pageup`, `pagedown`, `pause`, `scrolllock`, and numpad operators (`multiply`, `add`, `subtract`, `decimal`, `divide`).

Leave a value as `""` to unbind that item. Hotkeys work globally (even when the panel window is not focused).

## How It Works

The tool attaches to the Dolphin process and locates **MEM1** (the Wii's 24 MB main RAM) by scanning for committed memory regions that start with the game ID (`RMC`).

Inside MEM1, Mario Kart Wii stores an **ItemManager** singleton at address `0x809C3618` (PAL). This points to an array of 12 **KartItem** structs (one per player, each `0x248` bytes). Each KartItem has:

| Offset | Type | Description |
|--------|------|-------------|
| `+0x7C` | `u32` | Flags — bit `0x200` = "player is holding an item" |
| `+0x8C` | `s32` | Item ID (see table below) |
| `+0x90` | `s32` | Item count (1 for most items, 3 for triples) |

To give an item, the tool:
1. Sets bit `0x200` in the flag field at `+0x7C`
2. Writes the item ID to `+0x8C`
3. Writes the count to `+0x90`

### Item IDs

| ID | Item | ID | Item |
|----|------|----|------|
| 0 | Green Shell | 10 | Golden Mushroom |
| 1 | Red Shell | 11 | Mega Mushroom |
| 2 | Banana | 12 | Blooper |
| 3 | Fake Item Box | 13 | POW Block |
| 4 | Mushroom | 14 | Thunder Cloud |
| 5 | Triple Mushrooms | 15 | Bullet Bill |
| 6 | Bob-omb | 16 | Triple Green Shells |
| 7 | Blue Shell | 17 | Triple Red Shells |
| 8 | Lightning | 18 | Triple Bananas |
| 9 | Star | 20 | No Item |

## Run from Source

Requires **Python 3.10+** on Windows. No external dependencies (uses only `tkinter`, `ctypes`, and standard library).

```
python item_panel.py
```

## Build the Executable

```
pip install pyinstaller
python -m PyInstaller --onefile --noconsole --name MKW-Item-Panel item_panel.py
```

The `.exe` will be in the `dist/` folder.

## Disclaimer

This tool is intended for **fun with friends in private lobbies**. Use responsibly — don't ruin other people's online experience. The authors are not responsible for any bans or account actions.

## License

[MIT](LICENSE)
