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
import struct
import threading
import time
import tkinter as tk

# ─────────────────────────────────────────────────────────────────────────────
#  Win32 setup — ReadProcessMemory / WriteProcessMemory / VirtualQueryEx
# ─────────────────────────────────────────────────────────────────────────────
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
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
#  Global hotkey mapping — F13 through F24
#  Designed for Logitech side panels and other controllers with "esoteric" keys
#  that don't conflict with Dolphin or other applications.
# ─────────────────────────────────────────────────────────────────────────────
VK_F13 = 0x7C
# Index into ITEMS[] for each hotkey, plus special actions at the end
HOTKEY_MAP = [
    # (VK code,  action)  — action is an ITEMS index, or "clear" / "hold"
    (VK_F13 + 0,  0),       # F13 → Star
    (VK_F13 + 1,  1),       # F14 → Bullet Bill
    (VK_F13 + 2,  2),       # F15 → Golden Mushroom
    (VK_F13 + 3,  3),       # F16 → Mega Mushroom
    (VK_F13 + 4,  4),       # F17 → Blue Shell
    (VK_F13 + 5,  5),       # F18 → Lightning
    (VK_F13 + 6,  6),       # F19 → POW Block
    (VK_F13 + 7,  7),       # F20 → Blooper
    (VK_F13 + 8,  8),       # F21 → Mushroom
    (VK_F13 + 9,  9),       # F22 → 3x Mushroom
    (VK_F13 + 10, "clear"), # F23 → Clear item
    (VK_F13 + 11, "hold"),  # F24 → Toggle hold
]

# Friendly key name for each VK code (shown in the UI)
VK_NAMES = {VK_F13 + i: f"F{13 + i}" for i in range(12)}


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

        self._build_ui()

        # Background threads
        threading.Thread(target=self._connection_loop, daemon=True).start()
        threading.Thread(target=self._monitor_loop, daemon=True).start()
        threading.Thread(target=self._hold_loop, daemon=True).start()
        threading.Thread(target=self._hotkey_loop, daemon=True).start()

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

        # Build a lookup: ITEMS index → hotkey name (for labeling buttons)
        hotkey_labels = {}
        for vk, action in HOTKEY_MAP:
            if isinstance(action, int):
                hotkey_labels[action] = VK_NAMES[vk]

        # Item button grid
        grid = tk.Frame(self.root, bg=BG)
        grid.pack(padx=8, pady=2)
        self.buttons = []
        for i, (item_id, count, name, color) in enumerate(ITEMS):
            row, col = divmod(i, 4)
            label = name
            if i in hotkey_labels:
                label = f"{name}\n[{hotkey_labels[i]}]"
            btn = tk.Button(
                grid, text=label, font=(FONT, 9, "bold"),
                fg=color, bg=BTN_BG, activebackground="#333", activeforeground=color,
                relief=tk.FLAT, width=14, height=2, state=tk.DISABLED,
                command=lambda iid=item_id, c=count, n=name: self._give(iid, c, n),
            )
            btn.grid(row=row, column=col, padx=3, pady=3)
            self.buttons.append(btn)

        # Clear button
        frame = tk.Frame(self.root, bg=BG)
        frame.pack(pady=(4, 2))
        self.clear_btn = tk.Button(
            frame, text="CLEAR ITEM  [F23]", font=(FONT, 11, "bold"),
            fg="#ff5555", bg=BTN_BG, activebackground="#333",
            relief=tk.FLAT, width=20, state=tk.DISABLED,
            command=self._clear,
        )
        self.clear_btn.pack()

        # Hold checkbox
        self.hold_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            self.root, text="Hold (auto re-give)  [F24]",
            variable=self.hold_var, font=(FONT, 10),
            fg="#888", bg=BG, selectcolor="#222",
            activebackground=BG, activeforeground="#aaa",
            command=self._on_hold_toggled,
        ).pack(pady=(2, 2))

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

    # ── Global hotkey loop (~30 Hz polling) ──────────────────────────────────
    def _hotkey_loop(self):
        """Poll F13-F24 via GetAsyncKeyState for global hotkeys."""
        prev_down = set()
        while self.running:
            for vk, action in HOTKEY_MAP:
                state = user32.GetAsyncKeyState(vk)
                is_down = bool(state & 0x8000)
                if is_down and vk not in prev_down:
                    # Key just pressed — trigger action
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

    def _toggle_hold(self):
        """Toggle the Hold checkbox (called from hotkey)."""
        self.hold_var.set(not self.hold_var.get())
        self._on_hold_toggled()


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ItemPanel()
