"""System Monitor - a clean, minimal system monitor for Windows."""
import csv
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from collections import deque
from datetime import datetime

import psutil

try:
    import winsound
except ImportError:
    winsound = None

try:  # crisp text on high-DPI screens
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

VERSION = "1.0.0"
FONT = "Segoe UI"
W, SETTINGS_H, PAD = 360, 600, 28
WARN, CRIT = "#f6c177", "#eb6f92"
DATA_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "SystemMonitor")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")

THEMES = {
    "Dark": dict(bg="#0f1115", track="#1c2028", text="#e8eaed", muted="#6f7685"),
    "Black": dict(bg="#000000", track="#16181d", text="#f2f2f2", muted="#6b7280"),
    "Nord": dict(bg="#2e3440", track="#3b4252", text="#eceff4", muted="#8f9bb3"),
    "Light": dict(bg="#f6f7f9", track="#e3e6eb", text="#1b1e24", muted="#7a8190"),
}
ACCENTS = {"Blue": "#6ea8fe", "Green": "#6fd9a0", "Purple": "#b79cff",
           "Orange": "#ffb86b", "Pink": "#ff8fb1", "Teal": "#5fd3d0"}

DEFAULTS = {
    "show_cpu": True, "cpu_graph": True, "show_cores": False, "cpu_freq": False,
    "show_mem": True, "show_swap": False,
    "show_disk": True, "disk_drive": "auto", "show_diskio": False,
    "show_net": True, "net_graph": False, "net_units": "MB/s",
    "show_gpu": False, "temp_unit": "C",
    "show_battery": True, "show_uptime": False,
    "show_procs": True, "proc_count": 3, "proc_sort": "cpu",
    "theme": "Dark", "accent": "Blue", "opacity": 100,
    "compact": False, "always_on_top": False, "borderless": False,
    "refresh": 1000, "graph_len": 60,
    "alert_cpu": 0, "alert_mem": 0, "alert_sound": False,
    "log_csv": False, "start_with_windows": False,
    "remember_pos": True, "pos": None,
}

TOGGLE, CHOICE, NUMBER, ACTION, SECTION = "toggle", "choice", "number", "action", "section"
ALERTS = [(0, "Off")] + [(v, f"{v}%") for v in (70, 80, 90, 95)]
ROWS = [
    ("Metrics", None, SECTION, None),
    ("CPU usage", "show_cpu", TOGGLE, None),
    ("CPU graph", "cpu_graph", TOGGLE, None),
    ("Per-core bars", "show_cores", TOGGLE, None),
    ("CPU speed", "cpu_freq", TOGGLE, None),
    ("Memory", "show_mem", TOGGLE, None),
    ("Swap / page file", "show_swap", TOGGLE, None),
    ("Disk usage", "show_disk", TOGGLE, None),
    ("Drive", "disk_drive", CHOICE, "drives"),
    ("Disk read / write", "show_diskio", TOGGLE, None),
    ("Network speed", "show_net", TOGGLE, None),
    ("Network graph", "net_graph", TOGGLE, None),
    ("Network units", "net_units", CHOICE, [("MB/s", "MB/s"), ("Mbps", "Mbps")]),
    ("GPU (NVIDIA)", "show_gpu", TOGGLE, None),
    ("Temperature unit", "temp_unit", CHOICE, [("C", "°C"), ("F", "°F")]),
    ("Battery", "show_battery", TOGGLE, None),
    ("Uptime", "show_uptime", TOGGLE, None),
    ("Top processes", "show_procs", TOGGLE, None),
    ("Processes shown", "proc_count", NUMBER, None),
    ("Sort processes by", "proc_sort", CHOICE, [("cpu", "CPU"), ("mem", "Memory")]),
    ("Appearance", None, SECTION, None),
    ("Theme", "theme", CHOICE, [(k, k) for k in THEMES]),
    ("Accent color", "accent", CHOICE, [(k, k) for k in ACCENTS]),
    ("Opacity", "opacity", CHOICE, [(v, f"{v}%") for v in (100, 90, 80, 70, 60, 50)]),
    ("Compact layout", "compact", TOGGLE, None),
    ("Always on top", "always_on_top", TOGGLE, None),
    ("Borderless window", "borderless", TOGGLE, None),
    ("Behavior", None, SECTION, None),
    ("Update speed", "refresh", CHOICE, [(500, "0.5 s"), (1000, "1 s"), (2000, "2 s"), (5000, "5 s")]),
    ("Graph history", "graph_len", CHOICE, [(30, "30 points"), (60, "60 points"), (120, "120 points")]),
    ("Alert when CPU above", "alert_cpu", CHOICE, ALERTS),
    ("Alert when memory above", "alert_mem", CHOICE, ALERTS),
    ("Alert sound", "alert_sound", TOGGLE, None),
    ("Log to CSV file", "log_csv", TOGGLE, None),
    ("Start with Windows", "start_with_windows", TOGGLE, None),
    ("Remember window position", "remember_pos", TOGGLE, None),
    ("Open data folder", "open_folder", ACTION, None),
    ("Reset all settings", "reset", ACTION, None),
]


# ---- helpers -----------------------------------------------------------
def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for k in DEFAULTS:
            if k in data:
                s[k] = data[k]
    except (OSError, ValueError):
        pass
    return s


def save_settings(s):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except OSError:
        pass


def fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def fmt_speed(n):
    return fmt_bytes(n) + "/s"


def fmt_duration(secs):
    d, rem = divmod(int(secs), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return f"{d}d {h}h {m}m" if d else f"{h}h {m}m"


def read_gpu():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.check_output(
            [exe, "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            text=True, timeout=2, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).splitlines()[0]
        util, used, total, temp = [float(x) for x in out.split(",")]
        return util, used, total, temp
    except Exception:
        return None


def set_startup(enable):
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        if enable:
            if getattr(sys, "frozen", False):
                cmd = f'"{sys.executable}"'
            else:
                cmd = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
            winreg.SetValueEx(key, "SystemMonitor", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, "SystemMonitor")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception:
        pass


def dark_title_bar(root, dark=True):
    """Match the Windows title bar to the theme (Windows 10/11)."""
    try:
        root.update()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


# ---- app ---------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        self.s = load_settings()
        self.view = "main"
        self.hits, self.scroll, self.content_h, self.cur_h, self.drag = [], 0, 0, 0, None
        self.alerts = {"cpu": False, "mem": False}
        self.last_beep, self.last_log = {}, 0
        self.gpu, self.gpu_t, self.freq = None, 0, None
        self.read = self.write = self.down = self.up = 0.0
        self.ticks = 0
        self.sys_drive = (os.environ.get("SystemDrive", "C:") + "\\") if os.name == "nt" else "/"

        root.title("System Monitor")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self.hfont = tkfont.Font(root=root, family=FONT, size=9, weight="bold")
        self.c = tk.Canvas(root, width=W, height=SETTINGS_H, highlightthickness=0, bd=0)
        self.c.pack()
        self.proc_var = tk.StringVar()
        self.proc_entry = tk.Entry(self.c, textvariable=self.proc_var, width=5, justify="center",
                                   relief="flat", bd=0, highlightthickness=1, font=(FONT, 10))
        self.proc_entry.bind("<Return>", lambda e: self.c.focus_set())
        self.proc_entry.bind("<FocusOut>", self.commit_count)
        self.proc_entry.bind("<Escape>", self.cancel_count)
        self.c.bind("<Button-1>", self.on_click)
        self.c.bind("<Button-3>", lambda e: self.on_click(e, -1))
        self.c.bind("<B1-Motion>", self.on_drag)
        self.c.bind("<ButtonRelease-1>", lambda e: setattr(self, "drag", None))
        self.c.bind("<MouseWheel>", self.on_wheel)

        n = self.s["graph_len"]
        self.history, self.down_hist = deque([0.0] * n, maxlen=n), deque([0.0] * n, maxlen=n)
        self.cores = psutil.cpu_count() or 1
        self.per_core = [0.0] * self.cores
        self.cpu = 0.0
        self.mem = psutil.virtual_memory()
        self.last_net = psutil.net_io_counters()
        self.last_dio = psutil.disk_io_counters()
        self.last_time = time.time()
        psutil.cpu_percent(percpu=True)
        self.procs = self.scan_processes()

        pos = self.s.get("pos")
        if self.s["remember_pos"] and isinstance(pos, list) and len(pos) == 2:
            x, y = pos
            if 0 <= x < root.winfo_screenwidth() - 100 and 0 <= y < root.winfo_screenheight() - 100:
                root.geometry(f"+{x}+{y}")
        self.apply_all()
        self.tick()

    # -- theme ------------------------------------------------------------
    @property
    def t(self):
        return THEMES.get(self.s["theme"], THEMES["Dark"])

    @property
    def accent(self):
        return ACCENTS.get(self.s["accent"], ACCENTS["Blue"])

    def color_for(self, pct):
        return CRIT if pct >= 90 else WARN if pct >= 75 else self.accent

    # -- settings plumbing ------------------------------------------------
    def apply_window(self):
        self.root.attributes("-topmost", bool(self.s["always_on_top"]))
        try:
            self.root.attributes("-alpha", self.s["opacity"] / 100)
        except tk.TclError:
            pass
        self.root.configure(bg=self.t["bg"])
        self.c.configure(bg=self.t["bg"])

    def apply_borderless(self):
        self.root.withdraw()
        self.root.overrideredirect(bool(self.s["borderless"]))
        self.root.deiconify()
        self.apply_window()
        if not self.s["borderless"]:
            dark_title_bar(self.root, self.s["theme"] != "Light")

    def resize_history(self):
        n = self.s["graph_len"]
        for name in ("history", "down_hist"):
            old = list(getattr(self, name))[-n:]
            setattr(self, name, deque([0.0] * (n - len(old)) + old, maxlen=n))

    def apply_all(self):
        self.apply_window()
        if bool(self.root.overrideredirect()) != bool(self.s["borderless"]):
            self.apply_borderless()
        elif not self.s["borderless"]:
            dark_title_bar(self.root, self.s["theme"] != "Light")
        self.resize_history()
        set_startup(self.s["start_with_windows"])

    def set_value(self, key, val):
        self.s[key] = val
        save_settings(self.s)
        if key == "borderless":
            self.apply_borderless()
        elif key == "theme":
            self.apply_window()
            if not self.s["borderless"]:
                dark_title_bar(self.root, val != "Light")
        elif key == "graph_len":
            self.resize_history()
        elif key == "start_with_windows":
            set_startup(val)
        else:
            self.apply_window()
        self.draw()

    def options_for(self, opts):
        if opts == "drives":
            out = [("auto", "System drive")]
            try:
                for p in psutil.disk_partitions(all=False):
                    if "cdrom" not in p.opts and p.fstype:
                        out.append((p.mountpoint, p.mountpoint.rstrip("\\/") or p.mountpoint))
            except Exception:
                pass
            return out
        return opts

    def change(self, key, kind, opts, direction):
        if kind == TOGGLE:
            self.set_value(key, not self.s[key])
        elif kind == CHOICE:
            values = [v for v, _ in self.options_for(opts)]
            i = values.index(self.s[key]) if self.s[key] in values else -1
            self.set_value(key, values[(i + direction) % len(values)])
        elif key == "open_folder":
            os.makedirs(DATA_DIR, exist_ok=True)
            try:
                os.startfile(DATA_DIR)
            except Exception:
                pass
        elif key == "reset":
            pos = self.s.get("pos")
            self.s = dict(DEFAULTS)
            self.s["pos"] = pos
            save_settings(self.s)
            self.apply_all()
            self.draw()

    # -- data -------------------------------------------------------------
    def scan_processes(self):
        totals = {}
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            info = p.info
            name = info.get("name")
            if info.get("pid") == 0 or not name:
                continue
            if name.lower().endswith(".exe"):
                name = name[:-4]
            mi = info.get("memory_info")
            row = totals.setdefault(name, [0.0, 0])
            row[0] += (info.get("cpu_percent") or 0.0) / self.cores
            row[1] += mi.rss if mi else 0
        return [(n, v[0], v[1]) for n, v in totals.items()]

    def check_alert(self, name, value, threshold):
        hot = bool(threshold) and value >= threshold
        if (hot and self.s["alert_sound"] and winsound
                and time.time() - self.last_beep.get(name, 0) > 60):
            self.last_beep[name] = time.time()
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        self.alerts[name] = hot

    def log_row(self):
        if time.time() - self.last_log < 5:
            return
        self.last_log = time.time()
        path = os.path.join(DATA_DIR, "log.csv")
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            new = not os.path.exists(path)
            with open(path, "a", newline="") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(["time", "cpu_percent", "memory_percent", "download_bytes_s", "upload_bytes_s"])
                w.writerow([datetime.now().isoformat(timespec="seconds"), round(self.cpu, 1),
                            self.mem.percent, int(self.down), int(self.up)])
        except OSError:
            pass

    def tick(self):
        s = self.s
        now = time.time()
        dt = max(now - self.last_time, 0.001)
        self.last_time = now

        self.per_core = psutil.cpu_percent(percpu=True)
        self.cpu = sum(self.per_core) / max(len(self.per_core), 1)
        self.history.append(self.cpu)
        self.mem = psutil.virtual_memory()

        net = psutil.net_io_counters()
        self.down = (net.bytes_recv - self.last_net.bytes_recv) / dt
        self.up = (net.bytes_sent - self.last_net.bytes_sent) / dt
        self.last_net = net
        self.down_hist.append(self.down)

        dio = psutil.disk_io_counters()
        if dio and self.last_dio:
            self.read = (dio.read_bytes - self.last_dio.read_bytes) / dt
            self.write = (dio.write_bytes - self.last_dio.write_bytes) / dt
        self.last_dio = dio

        if s["cpu_freq"]:
            f = psutil.cpu_freq()
            self.freq = f.current if f else None
        if s["show_gpu"] and now - self.gpu_t >= 2:
            self.gpu, self.gpu_t = read_gpu(), now
        if s["show_procs"] and self.ticks % 2 == 0:
            self.procs = self.scan_processes()
        self.ticks += 1

        self.check_alert("cpu", self.cpu, s["alert_cpu"])
        self.check_alert("mem", self.mem.percent, s["alert_mem"])
        if s["log_csv"]:
            self.log_row()

        if self.view == "main":
            self.draw()
        self.root.after(int(s["refresh"]), self.tick)

    # -- interaction ------------------------------------------------------
    def commit_count(self, _=None):
        """Apply the number typed into the 'Processes shown' box."""
        try:
            n = max(1, min(999, int(self.proc_var.get().strip())))
        except ValueError:
            n = None
        if n is None or n == self.s["proc_count"]:
            self.proc_var.set(str(self.s["proc_count"]))
        elif self.view == "settings":
            self.set_value("proc_count", n)

    def cancel_count(self, _=None):
        self.proc_var.set(str(self.s["proc_count"]))
        self.c.focus_set()

    def on_click(self, event, direction=1):
        self.c.focus_set()  # lets the number box commit when you click elsewhere
        for x0, y0, x1, y1, cb in reversed(self.hits):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                cb(direction)
                return
        if self.s["borderless"]:
            self.drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def on_drag(self, event):
        if self.drag:
            self.root.geometry(f"+{event.x_root - self.drag[0]}+{event.y_root - self.drag[1]}")

    def on_wheel(self, event):
        if self.view == "settings":
            top = max(0, self.content_h - SETTINGS_H)
            self.scroll = max(0, min(top, self.scroll - event.delta * 0.5))
            self.draw()

    def open_settings(self, _=1):
        self.view, self.scroll = "settings", 0
        self.draw()

    def close_settings(self, _=1):
        self.view = "main"
        self.draw()

    def quit(self, *_):
        if self.s["remember_pos"]:
            self.s["pos"] = [self.root.winfo_x(), self.root.winfo_y()]
        save_settings(self.s)
        self.root.destroy()

    # -- drawing primitives ----------------------------------------------
    def resize(self, h):
        if h != self.cur_h:
            self.cur_h = h
            self.c.config(height=h)
            self.root.geometry(f"{W}x{h}")

    def header(self, title, buttons):
        c, t = self.c, self.t
        c.create_text(PAD, 30, text=title, anchor="w", fill=t["muted"], font=self.hfont)
        x = W - PAD
        for text, cb, color in buttons:
            w = self.hfont.measure(text)
            c.create_text(x, 30, text=text, anchor="e", fill=color, font=self.hfont)
            self.hits.append((x - w - 6, 8, x + 6, 52, cb))
            x -= w + 18

    def bar(self, y, pct, color):
        c = self.c
        c.create_line(PAD, y, W - PAD, y, width=6, capstyle="round", fill=self.t["track"])
        if pct >= 1:
            end = PAD + (W - 2 * PAD) * min(pct, 100) / 100
            c.create_line(PAD, y, max(end, PAD + 1), y, width=6, capstyle="round", fill=color)

    def sparkline(self, x0, y0, x1, y1, data, color, vmax=100):
        step = (x1 - x0) / (len(data) - 1)
        pts = []
        for i, v in enumerate(data):
            pts += [x0 + i * step, y1 - min(v / vmax, 1) * (y1 - y0)]
        self.c.create_line(*pts, smooth=True, width=2, fill=color, capstyle="round", joinstyle="round")

    def metric(self, y, label, value, pct, detail="", alert=False, color=None):
        c, t, cp = self.c, self.t, self.s["compact"]
        color = color or self.color_for(pct)
        if alert:
            label += "  ·  HIGH"
        c.create_text(PAD, y, text=label, anchor="w", fill=CRIT if alert else t["muted"], font=self.hfont)
        vcol = CRIT if alert else t["text"]
        if cp:
            if detail:
                c.create_text(PAD + self.hfont.measure(label) + 12, y, text=detail, anchor="w",
                              fill=t["muted"], font=(FONT, 9))
            c.create_text(W - PAD, y, text=value, anchor="e", fill=vcol, font=(FONT, 11, "bold"))
            self.bar(y + 20, pct, color)
            return y + 46
        if detail:
            c.create_text(W - PAD, y, text=detail, anchor="e", fill=t["muted"], font=(FONT, 9))
        c.create_text(PAD, y + 32, text=value, anchor="w", fill=vcol, font=(FONT, 26))
        self.bar(y + 68, pct, color)
        return y + 100

    def pair(self, y, l1, v1, l2, v2):
        c, t, cp = self.c, self.t, self.s["compact"]
        for x, label, val in ((PAD, l1, v1), (W // 2 + 10, l2, v2)):
            c.create_text(x, y, text=label, anchor="w", fill=t["muted"], font=self.hfont)
            if cp:
                c.create_text(x + self.hfont.measure(label) + 8, y, text=val, anchor="w",
                              fill=t["text"], font=(FONT, 10))
            else:
                c.create_text(x, y + 28, text=val, anchor="w", fill=t["text"], font=(FONT, 15))
        return y + (30 if cp else 70)

    def line(self, y, label, value):
        self.c.create_text(PAD, y, text=label, anchor="w", fill=self.t["muted"], font=self.hfont)
        self.c.create_text(W - PAD, y, text=value, anchor="e", fill=self.t["text"], font=(FONT, 10))
        return y + 30

    def fmt_net(self, n):
        return f"{n * 8 / 1e6:.1f} Mbps" if self.s["net_units"] == "Mbps" else fmt_speed(n)

    def cores_row(self, y):
        c, cp = self.c, self.s["compact"]
        n, gap, h = len(self.per_core), 4, 20 if cp else 30
        bw = (W - 2 * PAD - gap * (n - 1)) / n
        for i, v in enumerate(self.per_core):
            x = PAD + i * (bw + gap)
            c.create_rectangle(x, y, x + bw, y + h, fill=self.t["track"], outline="")
            if h * v / 100 > 1:
                c.create_rectangle(x, y + h - h * v / 100, x + bw, y + h, fill=self.color_for(v), outline="")
        return y + h + (18 if cp else 28)

    # -- views ------------------------------------------------------------
    def draw(self):
        self.c.delete("all")
        self.hits = []
        self.draw_settings() if self.view == "settings" else self.draw_main()

    def draw_main(self):
        c, s, t, cp = self.c, self.s, self.t, self.s["compact"]
        buttons = []
        if s["borderless"]:
            buttons.append(("✕", self.quit, t["muted"]))
        pin = s["always_on_top"]
        buttons.append(("PINNED" if pin else "PIN", lambda _: self.set_value("always_on_top", not pin),
                        self.accent if pin else t["muted"]))
        buttons.append(("SETTINGS", self.open_settings, t["muted"]))
        self.header("SYSTEM", buttons)

        y = 64
        if s["show_cpu"]:
            y0 = y
            detail = f"{self.freq / 1000:.1f} GHz" if s["cpu_freq"] and self.freq else ""
            y = self.metric(y, "CPU", f"{self.cpu:.0f}%", self.cpu, detail, self.alerts["cpu"])
            if s["cpu_graph"] and not cp:
                self.sparkline(W // 2 + 10, y0 + 20, W - PAD, y0 + 50, self.history, self.color_for(self.cpu))
        if s["show_cores"]:
            y = self.cores_row(y)
        if s["show_mem"]:
            m = self.mem
            y = self.metric(y, "MEMORY", f"{m.percent:.0f}%", m.percent,
                            f"{fmt_bytes(m.used)} / {fmt_bytes(m.total)}", self.alerts["mem"])
        if s["show_swap"]:
            sw = psutil.swap_memory()
            if sw.total:
                y = self.metric(y, "SWAP", f"{sw.percent:.0f}%", sw.percent,
                                f"{fmt_bytes(sw.used)} / {fmt_bytes(sw.total)}")
        if s["show_disk"]:
            path = self.sys_drive if s["disk_drive"] == "auto" else s["disk_drive"]
            try:
                d = psutil.disk_usage(path)
                name = path.rstrip("\\/") or path
                y = self.metric(y, f"DISK  {name}", f"{d.percent:.0f}%", d.percent,
                                f"{fmt_bytes(d.used)} / {fmt_bytes(d.total)}")
            except OSError:
                y = self.line(y, "DISK", "unavailable")
        if s["show_diskio"]:
            y = self.pair(y, "READ", fmt_speed(self.read), "WRITE", fmt_speed(self.write))
        if s["show_net"]:
            y = self.pair(y, "DOWNLOAD", self.fmt_net(self.down), "UPLOAD", self.fmt_net(self.up))
            if s["net_graph"]:
                h = 24 if cp else 36
                self.sparkline(PAD, y - 6, W - PAD, y - 6 + h, self.down_hist, self.accent,
                               vmax=max(max(self.down_hist), 1e5))
                y += h + 10
        if s["show_gpu"]:
            if self.gpu:
                util, used, total, temp = self.gpu
                tmp = f"{temp * 9 / 5 + 32:.0f}°F" if s["temp_unit"] == "F" else f"{temp:.0f}°C"
                y = self.metric(y, "GPU", f"{util:.0f}%", util,
                                f"{used / 1024:.1f} / {total / 1024:.1f} GB  ·  {tmp}")
            else:
                y = self.line(y, "GPU", "not detected (NVIDIA only)")
        if s["show_battery"]:
            b = psutil.sensors_battery()
            if b:
                if b.power_plugged:
                    detail = "charging"
                elif b.secsleft and b.secsleft > 0:
                    detail = f"{fmt_duration(b.secsleft)} left"
                else:
                    detail = "on battery"
                y = self.metric(y, "BATTERY", f"{b.percent:.0f}%", b.percent, detail,
                                color=self.color_for(100 - b.percent))
        if s["show_uptime"]:
            y = self.line(y, "UPTIME", fmt_duration(time.time() - psutil.boot_time()))
        if s["show_procs"] and self.procs:
            by_cpu = s["proc_sort"] == "cpu"
            rows = sorted(self.procs, key=lambda r: r[1 if by_cpu else 2], reverse=True)[:int(s["proc_count"])]
            c.create_text(PAD, y, text="TOP PROCESSES", anchor="w", fill=t["muted"], font=self.hfont)
            y += 24 if cp else 28
            for name, cpu_p, rss in rows:
                c.create_text(PAD, y, text=name[:28], anchor="w", fill=t["text"], font=(FONT, 10))
                c.create_text(W - PAD, y, text=f"{cpu_p:.1f}%" if by_cpu else fmt_bytes(rss),
                              anchor="e", fill=t["muted"], font=(FONT, 10))
                y += 20 if cp else 24
        self.resize(max(int(y) + 12, 120))

    def draw_settings(self):
        c, t = self.c, self.t
        self.resize(SETTINGS_H)
        y = 80 - self.scroll
        for label, key, kind, opts in ROWS:
            if kind == SECTION:
                y += 10
                c.create_text(PAD, y, text=label.upper(), anchor="w", fill=self.accent, font=self.hfont)
                y += 28
                continue
            if kind == NUMBER:
                e = self.proc_entry
                c.create_text(PAD, y, text=label, anchor="w", fill=t["text"], font=(FONT, 10))
                e.configure(bg=t["track"], fg=t["text"], insertbackground=t["text"],
                            highlightbackground=t["track"], highlightcolor=self.accent)
                if self.c.focus_get() is not e:
                    self.proc_var.set(str(self.s["proc_count"]))
                if 70 < y < SETTINGS_H - 10:
                    c.create_window(W - PAD, y, window=e, anchor="e", width=64, height=24)
                y += 34
                continue
            if kind == ACTION:
                c.create_text(PAD, y, text=label, anchor="w", fill=self.accent, font=(FONT, 10))
            else:
                c.create_text(PAD, y, text=label, anchor="w", fill=t["text"], font=(FONT, 10))
            if kind == TOGGLE:
                on, cx = self.s[key], W - PAD - 16
                c.create_line(cx - 14, y, cx + 14, y, width=18, capstyle="round",
                              fill=self.accent if on else t["track"])
                kx = cx + 7 if on else cx - 7
                c.create_oval(kx - 6, y - 6, kx + 6, y + 6, fill="#ffffff" if on else t["muted"], outline="")
            elif kind == CHOICE:
                text = next((lab for v, lab in self.options_for(opts) if v == self.s[key]), str(self.s[key]))
                c.create_text(W - PAD, y, text=text, anchor="e", fill=self.accent, font=(FONT, 10))
            self.hits.append((0, y - 16, W, y + 16,
                              lambda d, k=key, kd=kind, o=opts: self.change(k, kd, o, d)))
            y += 34
        c.create_text(W // 2, y + 6, text=f"System Monitor v{VERSION}", fill=t["muted"], font=(FONT, 9))
        y += 36
        self.content_h = y + self.scroll + 20
        c.create_rectangle(0, 0, W, 58, fill=t["bg"], outline=t["bg"])
        self.hits.append((0, 0, W, 58, lambda d: None))
        self.header("SETTINGS", [("BACK", self.close_settings, self.accent)])


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
