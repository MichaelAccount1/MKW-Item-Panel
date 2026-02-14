"""
MKW Item Panel - Give yourself any item in Mario Kart Wii (Dolphin)

A real-time item injector for Mario Kart Wii running on Dolphin Emulator.
Works with Retro Rewind, CTGP, and vanilla MKW (PAL - RMCP01).

Attaches to the Dolphin process, locates MEM1 (Wii RAM), and writes directly
to the KartItem structures in memory:
  - Offset +0x7C: item-held flag (bit 0x200 = "player has an item")
  - Offset +0x8C: item ID (see ITEMS table below)
  - Offset +0x90: item count

https://github.com/MichaelAccount1/MKW-Item-Panel
"""

import ctypes
from ctypes import wintypes
import json
import os
import struct
import sys
import threading
import time
import tkinter as tk

# ─────────────────────────────────────────────────────────────────────────────
#  Win32 setup — kernel32, user32, winmm
# ─────────────────────────────────────────────────────────────────────────────
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
winmm = ctypes.WinDLL("winmm", use_last_error=True)
SIZE_T = ctypes.c_size_t

user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", SIZE_T),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.ReadProcessMemory.restype = wintypes.BOOL
kernel32.ReadProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, SIZE_T, ctypes.POINTER(SIZE_T),
]
kernel32.WriteProcessMemory.restype = wintypes.BOOL
kernel32.WriteProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, SIZE_T, ctypes.POINTER(SIZE_T),
]
kernel32.VirtualQueryEx.restype = SIZE_T
kernel32.VirtualQueryEx.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION), SIZE_T,
]
kernel32.CloseHandle.restype = wintypes.HANDLE

# Process enumeration (no subprocess needed — avoids flashing console windows)
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
MAX_PATH = 260


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * MAX_PATH),
    ]


kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.Process32First.restype = wintypes.BOOL
kernel32.Process32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
kernel32.Process32Next.restype = wintypes.BOOL
kernel32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]

# ── Joystick API (winmm) ────────────────────────────────────────────────────
JOYERR_NOERROR = 0
JOY_RETURNBUTTONS = 0x00000080


class JOYINFOEX(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("dwXpos", wintypes.DWORD),
        ("dwYpos", wintypes.DWORD),
        ("dwZpos", wintypes.DWORD),
        ("dwRpos", wintypes.DWORD),
        ("dwUpos", wintypes.DWORD),
        ("dwVpos", wintypes.DWORD),
        ("dwButtons", wintypes.DWORD),
        ("dwButtonNumber", wintypes.DWORD),
        ("dwPOV", wintypes.DWORD),
        ("dwReserved1", wintypes.DWORD),
        ("dwReserved2", wintypes.DWORD),
    ]


winmm.joyGetPosEx.restype = wintypes.UINT
winmm.joyGetPosEx.argtypes = [wintypes.UINT, ctypes.POINTER(JOYINFOEX)]
winmm.joyGetNumDevs.restype = wintypes.UINT
winmm.joyGetNumDevs.argtypes = []

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000

# ─────────────────────────────────────────────────────────────────────────────
#  MKW item definitions
# ─────────────────────────────────────────────────────────────────────────────
ITEMS = [
    # (item_id, count, display_name, button_color)
    (0x09, 1, "Star",           "#FFD700"),
    (0x0F, 1, "Bullet Bill",    "#BBBBBB"),
    (0x0A, 1, "Golden Mush",    "#FFA500"),
    (0x0B, 1, "Mega Mushroom",  "#FF6347"),
    (0x07, 1, "Blue Shell",     "#4499FF"),
    (0x08, 1, "Lightning",      "#FFEE44"),
    (0x0D, 1, "POW Block",      "#8899FF"),
    (0x0C, 1, "Blooper",        "#CCCCCC"),
    (0x04, 1, "Mushroom",       "#EE9944"),
    (0x05, 3, "3x Mushroom",    "#EE9944"),
    (0x01, 1, "Red Shell",      "#EE4444"),
    (0x11, 3, "3x Red Shell",   "#EE4444"),
    (0x00, 1, "Green Shell",    "#44CC44"),
    (0x10, 3, "3x Green Shell", "#44CC44"),
    (0x02, 1, "Banana",         "#EEDD33"),
    (0x12, 3, "3x Banana",      "#EEDD33"),
    (0x06, 1, "Bob-omb",        "#777777"),
    (0x03, 1, "Fake Item Box",  "#DD6644"),
    (0x0E, 1, "Thunder Cloud",  "#9966CC"),
]

ITEM_NAMES = {
    -1: "Empty",     0: "Green Shell",  1: "Red Shell",    2: "Banana",
     3: "Fake Item", 4: "Mushroom",     5: "3x Mushroom",  6: "Bob-omb",
     7: "Blue Shell", 8: "Lightning",   9: "Star",        10: "Golden Mush",
    11: "Mega Mush", 12: "Blooper",    13: "POW Block",   14: "Thunder Cloud",
    15: "Bullet Bill",16: "3x Green",  17: "3x Red",      18: "3x Banana",
    20: "No Item",
}

# ─────────────────────────────────────────────────────────────────────────────
#  MKW memory layout constants  (PAL — RMCP01)
# ─────────────────────────────────────────────────────────────────────────────
ITEM_MANAGER_STATIC = 0x809C3618   # Pointer to the ItemManager singleton
KART_ITEM_SIZE      = 0x248        # Size of one KartItem struct
NUM_SLOTS           = 12           # Max players in a race

# Offsets inside each KartItem struct
FLAG_OFFSET  = 0x7C   # u32 — bit 0x200 = "player is holding an item"
ITEM_OFFSET  = 0x8C   # s32 — current item ID  (see ITEM_NAMES)
COUNT_OFFSET = 0x90   # s32 — item quantity     (1 for most, 3 for triples)

HAS_ITEM_BIT = 0x200  # The flag bit that must be set for the game to show the item

# ─────────────────────────────────────────────────────────────────────────────
#  Configurable keybinds  (loaded from keybinds.json next to the exe/script)
# ─────────────────────────────────────────────────────────────────────────────
# All action names that can appear in the config (items + special actions)
ACTION_NAMES = [item[2] for item in ITEMS] + ["Clear", "Toggle Hold"]

# Key name → Win32 virtual-key code
KEY_NAME_TO_VK = {}
for _i in range(1, 25):
    KEY_NAME_TO_VK[f"f{_i}"] = 0x6F + _i
for _i in range(10):
    KEY_NAME_TO_VK[str(_i)] = 0x30 + _i
for _i in range(26):
    KEY_NAME_TO_VK[chr(0x61 + _i)] = 0x41 + _i
for _i in range(10):
    KEY_NAME_TO_VK[f"numpad{_i}"] = 0x60 + _i
KEY_NAME_TO_VK.update({
    "multiply": 0x6A, "add": 0x6B, "subtract": 0x6D,
    "decimal": 0x6E, "divide": 0x6F,
    "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22,
    "scrolllock": 0x91, "pause": 0x13, "capslock": 0x14,
})

VK_TO_DISPLAY = {v: k.upper() for k, v in KEY_NAME_TO_VK.items()}


def _config_path():
    """Return the path to keybinds.json, next to the exe (frozen) or script."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "keybinds.json")


def _default_config():
    """Return the default config dict (joystick on, no keyboard binds)."""
    keys = {}
    for name in ACTION_NAMES:
        keys[name] = ""
    return {"joystick": True, "keys": keys}


def load_config():
    """Load keybinds.json, creating it with defaults if missing.
    Returns (joystick_enabled, hotkey_map) where hotkey_map is
    list of (vk_code, action_index_or_string)."""
    path = _config_path()
    if not os.path.exists(path):
        cfg = _default_config()
        with open(path, "w") as f:
            json.dump(cfg, f, indent=4)
    else:
        with open(path) as f:
            cfg = json.load(f)
        # Merge any new items that might have been added
        default = _default_config()
        for k in default["keys"]:
            if k not in cfg.get("keys", {}):
                cfg.setdefault("keys", {})[k] = ""
        if "joystick" not in cfg:
            cfg["joystick"] = True

    joy_enabled = cfg.get("joystick", True)

    hotkey_map = []  # [(vk_code, action)]
    key_labels = {}  # {action_name: display_string}
    keys = cfg.get("keys", {})
    for action_name, key_str in keys.items():
        if not key_str:
            continue
        vk = KEY_NAME_TO_VK.get(key_str.strip().lower())
        if vk is None:
            continue
        # Determine action
        if action_name == "Clear":
            hotkey_map.append((vk, "clear"))
            key_labels["Clear"] = key_str.strip().upper()
        elif action_name == "Toggle Hold":
            hotkey_map.append((vk, "hold"))
            key_labels["Toggle Hold"] = key_str.strip().upper()
        else:
            # Find item index by name
            for idx, (_, _, name, _) in enumerate(ITEMS):
                if name == action_name:
                    hotkey_map.append((vk, idx))
                    key_labels[action_name] = key_str.strip().upper()
                    break

    return joy_enabled, hotkey_map, key_labels


# ─────────────────────────────────────────────────────────────────────────────
#  Dolphin process helpers
# ─────────────────────────────────────────────────────────────────────────────
def find_dolphin_pid():
    """Return the PID of the first running Dolphin process, or None.
    Uses Win32 CreateToolhelp32Snapshot — no subprocess, no console flash."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return None
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if not kernel32.Process32First(snap, ctypes.byref(entry)):
            return None
        while True:
            name = entry.szExeFile.split(b"\x00", 1)[0].decode("utf-8", errors="ignore").lower()
            if name == "dolphin.exe":
                return entry.th32ProcessID
            if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snap)
    return None


def _read(handle, addr, size):
    buf = ctypes.create_string_buffer(size)
    read = SIZE_T(0)
    ok = kernel32.ReadProcessMemory(
        handle, ctypes.c_void_p(addr), buf, size, ctypes.byref(read),
    )
    return buf.raw[: read.value] if ok else None


def _write(handle, addr, data):
    buf = ctypes.create_string_buffer(data, len(data))
    written = SIZE_T(0)
    return kernel32.WriteProcessMemory(
        handle, ctypes.c_void_p(addr), buf, len(data), ctypes.byref(written),
    )


def find_mem1(handle):
    """
    Scan Dolphin's virtual memory to find MEM1 (Wii RAM).
    MEM1 is a 24 MB committed region whose first bytes are the game ID ("RMC").
    Returns the host base address, or None.
    """
    addr = 0
    mbi = MEMORY_BASIC_INFORMATION()
    while addr < 0x7FFFFFFFFFFF:
        ret = kernel32.VirtualQueryEx(
            handle, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi),
        )
        if ret == 0:
            break
        if mbi.State == MEM_COMMIT and mbi.RegionSize >= 0x1800000:
            header = _read(handle, mbi.BaseAddress, 4)
            if header and header[:3] == b"RMC":
                return mbi.BaseAddress
        nxt = (mbi.BaseAddress or 0) + mbi.RegionSize
        addr = nxt if nxt > addr else addr + 0x10000
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  Wii memory accessor
# ─────────────────────────────────────────────────────────────────────────────
class WiiMemory:
    """Read/write big-endian Wii memory through Dolphin's host process."""

    def __init__(self, handle, mem1_base):
        self._handle = handle
        self._base = mem1_base

    def _host_addr(self, wii_addr):
        return self._base + (wii_addr & 0x01FFFFFF)

    def read_u32(self, addr):
        data = _read(self._handle, self._host_addr(addr), 4)
        return struct.unpack(">I", data)[0] if data and len(data) == 4 else None

    def read_s32(self, addr):
        data = _read(self._handle, self._host_addr(addr), 4)
        return struct.unpack(">i", data)[0] if data and len(data) == 4 else None

    def write_u32(self, addr, value):
        return _write(self._handle, self._host_addr(addr), struct.pack(">I", value))

    def is_valid_ptr(self, value):
        return value is not None and 0x80000000 <= value <= 0x93FFFFFF


# ─────────────────────────────────────────────────────────────────────────────
#  GUI
# ─────────────────────────────────────────────────────────────────────────────
BG = "#111111"
BTN_BG = "#1a1a1a"
FONT = "Consolas"


class ItemPanel:
    """Main application window."""

    def __init__(self):
        # Load config before building UI
        self.joy_enabled, self.hotkey_map, self.key_labels = load_config()

        self.root = tk.Tk()
        self.root.title("MKW Item Panel")
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG)
        self.root.resizable(False, False)

        # Place on second monitor if available
        try:
            screen_w = self.root.winfo_screenwidth()
            self.root.geometry(f"+{screen_w + 60}+40")
        except Exception:
            pass

        # State
        self.running = True
        self.mem: WiiMemory | None = None
        self.connected = False
        self.in_race = False
        self.items_ptr = None
        self.player_slot = None
        self.hold_item = None          # (item_id, count) when holding
        self.last_give_name = ""
        self.joy_connected = False

        self._build_ui()

        # Background threads
        threading.Thread(target=self._connection_loop, daemon=True).start()
        threading.Thread(target=self._monitor_loop, daemon=True).start()
        threading.Thread(target=self._hold_loop, daemon=True).start()
        if self.hotkey_map:
            threading.Thread(target=self._hotkey_loop, daemon=True).start()
        if self.joy_enabled:
            threading.Thread(target=self._joystick_loop, daemon=True).start()

        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        self.root.mainloop()

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Status bar
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill=tk.X, padx=10, pady=(10, 4))
        self.dot = tk.Label(top, text="\u25CF", font=(FONT, 14), fg="#f33", bg=BG)
        self.dot.pack(side=tk.LEFT, padx=(0, 6))
        self.status_label = tk.Label(
            top, text="Connecting...", font=(FONT, 11), fg="#888", bg=BG,
        )
        self.status_label.pack(side=tk.LEFT)

        # Current item
        self.held_label = tk.Label(
            self.root, text="Held: ---", font=(FONT, 11, "bold"), fg="#aaa", bg=BG,
        )
        self.held_label.pack(pady=(0, 2))

        self.slot_label = tk.Label(
            self.root, text="Slot: detecting...", font=(FONT, 9), fg="#555", bg=BG,
        )
        self.slot_label.pack(pady=(0, 6))

        # Item button grid
        grid = tk.Frame(self.root, bg=BG)
        grid.pack(padx=8, pady=2)
        self.buttons = []
        for i, (item_id, count, name, color) in enumerate(ITEMS):
            row, col = divmod(i, 4)
            # Build label with optional keybind / joystick tag
            tags = []
            if name in self.key_labels:
                tags.append(self.key_labels[name])
            if self.joy_enabled:
                tags.append(f"J{i + 1}")
            label = f"{name}\n[{' | '.join(tags)}]" if tags else name
            btn = tk.Button(
                grid, text=label, font=(FONT, 9, "bold"),
                fg=color, bg=BTN_BG, activebackground="#333", activeforeground=color,
                relief=tk.FLAT, width=14, height=2, state=tk.DISABLED,
                command=lambda iid=item_id, c=count, n=name: self._give(iid, c, n),
            )
            btn.grid(row=row, column=col, padx=3, pady=3)
            self.buttons.append(btn)

        # Clear button
        clear_tags = []
        if "Clear" in self.key_labels:
            clear_tags.append(self.key_labels["Clear"])
        if self.joy_enabled:
            clear_tags.append(f"J{len(ITEMS) + 1}")
        clear_suffix = f"  [{' | '.join(clear_tags)}]" if clear_tags else ""
        frame = tk.Frame(self.root, bg=BG)
        frame.pack(pady=(4, 2))
        self.clear_btn = tk.Button(
            frame, text=f"CLEAR ITEM{clear_suffix}", font=(FONT, 11, "bold"),
            fg="#ff5555", bg=BTN_BG, activebackground="#333",
            relief=tk.FLAT, width=24, state=tk.DISABLED,
            command=self._clear,
        )
        self.clear_btn.pack()

        # Hold checkbox
        hold_tags = []
        if "Toggle Hold" in self.key_labels:
            hold_tags.append(self.key_labels["Toggle Hold"])
        if self.joy_enabled:
            hold_tags.append(f"J{len(ITEMS) + 2}")
        hold_suffix = f"  [{' | '.join(hold_tags)}]" if hold_tags else ""
        self.hold_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            self.root, text=f"Hold (auto re-give){hold_suffix}",
            variable=self.hold_var, font=(FONT, 10),
            fg="#888", bg=BG, selectcolor="#222",
            activebackground=BG, activeforeground="#aaa",
            command=self._on_hold_toggled,
        ).pack(pady=(2, 2))

        # Joystick status line
        if self.joy_enabled:
            self.joy_label = tk.Label(
                self.root, text="Joystick: scanning...", font=(FONT, 9),
                fg="#555", bg=BG,
            )
            self.joy_label.pack(pady=(0, 0))

        # Feedback line
        self.feedback_label = tk.Label(
            self.root, text="", font=(FONT, 10), fg="#3e6", bg=BG,
        )
        self.feedback_label.pack(pady=(2, 10))

    # ── UI helpers ──────────────────────────────────────────────────────────
    def _ui(self, fn):
        try:
            self.root.after(0, fn)
        except Exception:
            pass

    def _set_status(self, text, color):
        self._ui(lambda: (
            self.status_label.config(text=text), self.dot.config(fg=color),
        ))

    def _set_held(self, text):
        self._ui(lambda: self.held_label.config(text=text))

    def _set_slot(self, text):
        self._ui(lambda: self.slot_label.config(text=text))

    def _set_feedback(self, text, color="#3e6"):
        self._ui(lambda: self.feedback_label.config(text=text, fg=color))

    def _set_joy(self, text, color="#555"):
        if self.joy_enabled:
            self._ui(lambda: self.joy_label.config(text=text, fg=color))

    def _set_buttons_state(self, state):
        self._ui(lambda: [b.config(state=state) for b in self.buttons])
        self._ui(lambda: self.clear_btn.config(state=state))

    def _quit(self):
        self.running = False
        self.root.destroy()

    # ── Dolphin connection ──────────────────────────────────────────────────
    def _connection_loop(self):
        while self.running:
            if not self.connected:
                pid = find_dolphin_pid()
                if pid:
                    handle = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
                    if handle:
                        base = find_mem1(handle)
                        if base:
                            self.mem = WiiMemory(handle, base)
                            self.connected = True
                            self._set_status(f"Connected (PID {pid})", "#3e6")
                            time.sleep(1)
                            continue
                        kernel32.CloseHandle(handle)
                self._set_status("Waiting for Dolphin...", "#ea3")
            else:
                # Verify connection is still alive
                test = _read(self.mem._handle, self.mem._base, 4)
                if not test:
                    self.connected = False
                    self.in_race = False
                    self.items_ptr = None
                    self.player_slot = None
                    self.mem = None
                    self._set_buttons_state(tk.DISABLED)
                    self._set_status("Disconnected", "#f33")
            time.sleep(2)

    # ── Race & item monitor ─────────────────────────────────────────────────
    def _monitor_loop(self):
        prev_items = {}
        while self.running:
            if not self.connected or not self.mem:
                time.sleep(0.5)
                continue

            # Check if ItemManager is valid (we're in a race)
            mgr = self.mem.read_u32(ITEM_MANAGER_STATIC)
            if not self.mem.is_valid_ptr(mgr):
                self.in_race = False
                self.items_ptr = None
                self._set_buttons_state(tk.DISABLED)
                self._set_status("Not in race", "#ea3")
                self._set_held("Held: ---")
                self._set_slot("Slot: ---")
                prev_items.clear()
                time.sleep(0.5)
                continue

            items_ptr = self.mem.read_u32(mgr + 0x14)
            if not self.mem.is_valid_ptr(items_ptr):
                self.in_race = False
                self._set_buttons_state(tk.DISABLED)
                self._set_status("Waiting for race...", "#ea3")
                time.sleep(0.5)
                continue

            self.in_race = True
            self.items_ptr = items_ptr
            self._set_buttons_state(tk.NORMAL)

            # Read item data from every slot
            slot_items = {}
            for slot in range(NUM_SLOTS):
                base = items_ptr + slot * KART_ITEM_SIZE
                item_id = self.mem.read_s32(base + ITEM_OFFSET)
                count = self.mem.read_s32(base + COUNT_OFFSET)
                slot_items[slot] = (item_id, count)

            # Auto-detect local player slot: watch for natural item pickups
            if self.player_slot is None and prev_items:
                for slot in range(NUM_SLOTS):
                    old_id = prev_items.get(slot, (20, 0))[0]
                    new_id = slot_items[slot][0]
                    if (old_id in (20, -1)
                            and new_id not in (20, -1, None)
                            and self.hold_item is None):
                        self.player_slot = slot
                        self._set_slot(f"Slot: {slot} (auto-detected)")
                        break

            prev_items = slot_items

            # Update held-item display
            if self.player_slot is not None:
                item_id, count = slot_items.get(self.player_slot, (None, None))
                if item_id is not None and item_id not in (20, -1):
                    self._set_held(f"Held: {ITEM_NAMES.get(item_id, f'?{item_id}')} x{count}")
                else:
                    self._set_held("Held: None")
                if not self.hold_item:
                    self._set_status("In race — ready!", "#3e6")
            else:
                for slot in range(NUM_SLOTS):
                    item_id, count = slot_items[slot]
                    if item_id is not None and item_id not in (20, -1, None):
                        self._set_held(
                            f"Held: {ITEM_NAMES.get(item_id, '?')} x{count} (slot {slot})"
                        )
                        break
                else:
                    self._set_held("Held: None")
                self._set_status("In race — pick up an item to detect your slot", "#3e6")
                self._set_slot("Slot: detecting...")

            time.sleep(0.25)

    # ── Item injection ──────────────────────────────────────────────────────
    def _write_item(self, item_id, count):
        """Write item data to all 12 KartItem slots."""
        if not self.mem or not self.items_ptr:
            return False
        for slot in range(NUM_SLOTS):
            base = self.items_ptr + slot * KART_ITEM_SIZE
            # Set the "has item" flag
            flag = self.mem.read_u32(base + FLAG_OFFSET)
            if flag is not None:
                self.mem.write_u32(base + FLAG_OFFSET, flag | HAS_ITEM_BIT)
            # Set item ID and count
            self.mem.write_u32(base + ITEM_OFFSET, item_id & 0xFFFFFFFF)
            self.mem.write_u32(base + COUNT_OFFSET, count & 0xFFFFFFFF)
        return True

    def _clear_item(self):
        """Remove the held item from all slots."""
        if not self.mem or not self.items_ptr:
            return
        for slot in range(NUM_SLOTS):
            base = self.items_ptr + slot * KART_ITEM_SIZE
            flag = self.mem.read_u32(base + FLAG_OFFSET)
            if flag is not None:
                self.mem.write_u32(base + FLAG_OFFSET, flag & ~HAS_ITEM_BIT)
            self.mem.write_u32(base + ITEM_OFFSET, 20)  # NoItem
            self.mem.write_u32(base + COUNT_OFFSET, 0)

    # ── Button handlers ─────────────────────────────────────────────────────
    def _give(self, item_id, count, name):
        if not self.in_race:
            self._set_feedback("Not in race!", "#f33")
            return
        if self._write_item(item_id, count):
            self._set_feedback(f"Gave: {name} x{count}", "#3e6")
            self.last_give_name = name
            if self.hold_var.get():
                self.hold_item = (item_id, count)
        else:
            self._set_feedback("Write failed!", "#f33")

    def _clear(self):
        self.hold_item = None
        self._clear_item()
        self._set_feedback("Cleared", "#ea3")

    def _on_hold_toggled(self):
        if not self.hold_var.get():
            self.hold_item = None

    def _toggle_hold(self):
        """Toggle the Hold checkbox (called from hotkey/joystick)."""
        self.hold_var.set(not self.hold_var.get())
        self._on_hold_toggled()

    # ── Hold loop (continuous re-injection at ~60 Hz) ───────────────────────
    def _hold_loop(self):
        while self.running:
            if self.hold_item and self.in_race and self.mem and self.items_ptr:
                item_id, count = self.hold_item
                self._write_item(item_id, count)
                self._set_status(f"Holding: {self.last_give_name}", "#FFD700")
                time.sleep(1 / 60)
            else:
                time.sleep(0.1)

    # ── Keyboard hotkey loop (~30 Hz polling) ────────────────────────────────
    def _hotkey_loop(self):
        """Poll configured keys via GetAsyncKeyState."""
        prev_down = set()
        while self.running:
            for vk, action in self.hotkey_map:
                state = user32.GetAsyncKeyState(vk)
                is_down = bool(state & 0x8000)
                if is_down and vk not in prev_down:
                    if action == "clear":
                        self._ui(self._clear)
                    elif action == "hold":
                        self._ui(self._toggle_hold)
                    elif isinstance(action, int) and action < len(ITEMS):
                        item_id, count, name, _ = ITEMS[action]
                        self._ui(lambda iid=item_id, c=count, n=name: self._give(iid, c, n))
                if is_down:
                    prev_down.add(vk)
                else:
                    prev_down.discard(vk)
            time.sleep(1 / 30)

    # ── Joystick input loop (~30 Hz polling) ─────────────────────────────────
    def _joystick_loop(self):
        """Poll all connected joysticks and map buttons to items.
        Buttons 0-18 → items, button 19 → clear, button 20 → toggle hold."""
        prev_buttons = {}  # joy_id → previous dwButtons bitmask
        num_actions = len(ITEMS) + 2  # items + clear + hold
        was_connected = False

        while self.running:
            found_any = False
            max_devs = winmm.joyGetNumDevs()

            for joy_id in range(min(max_devs, 16)):
                info = JOYINFOEX()
                info.dwSize = ctypes.sizeof(JOYINFOEX)
                info.dwFlags = JOY_RETURNBUTTONS
                result = winmm.joyGetPosEx(joy_id, ctypes.byref(info))
                if result != JOYERR_NOERROR:
                    prev_buttons.pop(joy_id, None)
                    continue

                found_any = True
                old = prev_buttons.get(joy_id, 0)
                new = info.dwButtons

                # Check each button for rising edge (just pressed)
                for btn in range(min(32, num_actions)):
                    mask = 1 << btn
                    if (new & mask) and not (old & mask):
                        if btn < len(ITEMS):
                            item_id, count, name, _ = ITEMS[btn]
                            self._ui(
                                lambda iid=item_id, c=count, n=name: self._give(iid, c, n)
                            )
                        elif btn == len(ITEMS):
                            self._ui(self._clear)
                        elif btn == len(ITEMS) + 1:
                            self._ui(self._toggle_hold)

                prev_buttons[joy_id] = new

            # Update joystick status in UI
            if found_any and not was_connected:
                self._set_joy("Joystick: connected", "#3e6")
                was_connected = True
            elif not found_any and was_connected:
                self._set_joy("Joystick: disconnected", "#f33")
                was_connected = False
            elif not found_any and not was_connected:
                self._set_joy("Joystick: not found", "#555")

            time.sleep(1 / 30)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ItemPanel()
