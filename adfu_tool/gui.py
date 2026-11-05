"""adfu-tool GUI: a clean, production-tool style front end.

Layout follows the classic vendor flashing tools: toolbar on top, device
panel on the left, function buttons on the right, progress bar and a
timestamped log at the bottom. Every operation runs on a worker thread and
talks to the UI through an event queue, so the window never freezes; only
one operation runs at a time and nothing is ever retried (same rules as the
CLI). Read-only by design: there is no flash write/erase function here for
the same reason there is none in the CLI.
"""
import datetime
import queue
import threading
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
from tkinter import ttk

from . import __version__, device as device_mod, loader as loader_mod
from .protocol import GETINFO_IDENTITY, AdfuError, Session
from .reader import run_read
from .transition import enter_adfu as switch_to_adfu

BG = "#f6f8fa"
PANEL = "#ffffff"
BAR = "#1f2d3d"
ACCENT = "#0969da"
GREEN = "#1a7f37"
RED = "#cf222e"
GREY = "#57606a"
FONT = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI", 9, "bold")
FONT_TITLE = ("Segoe UI", 11, "bold")
MONO = ("Consolas", 9)

PROJECT_URL = "https://github.com/BlackLikeaCat/actions-adfu-tool"


def timestamp() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


class GuiApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.events: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.adfu_info: dict | None = None

        root.title(f"adfu-tool {__version__} — Actions ADFU Recovery Suite")
        root.geometry("920x660")
        root.minsize(820, 580)
        root.configure(bg=BG)

        self._build_style()
        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._build_progress()
        self._build_log()
        self._build_statusbar()

        self.log(f"adfu-tool {__version__} ready — connect a card and press Refresh Devices.", "info")
        self.root.after(80, self._poll_events)
        self.root.after(200, self.refresh_devices)

    # ---- construction -------------------------------------------------
    def _build_style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=BG, font=FONT)
        style.configure("Bar.TFrame", background=BAR)
        style.configure("Bar.TLabel", background=BAR, foreground="#ffffff")
        style.configure("Bar.TButton", background="#33475b", foreground="#ffffff",
                        relief="flat", focusthickness=0)
        style.map("Bar.TButton", background=[("active", "#48627d")])
        style.configure("Panel.TLabelframe", background=PANEL, borderwidth=1,
                        relief="solid")
        style.configure("Panel.TLabelframe.Label", background=PANEL,
                        foreground=GREY, font=FONT_BOLD)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Panel.TLabel", background=PANEL)
        style.configure("Panel.TCheckbutton", background=PANEL)
        style.configure("Panel.TCombobox", fieldbackground="#ffffff")
        style.configure("Primary.TButton", background=ACCENT, foreground="#ffffff",
                        font=FONT_BOLD, relief="flat", focusthickness=0, padding=(10, 6))
        style.map("Primary.TButton", background=[("active", "#0757ba"), ("disabled", "#a8c4e8")])
        style.configure("Function.TButton", padding=(10, 6), relief="flat", focusthickness=0)
        style.configure("Horizontal.TProgressbar", background=ACCENT,
                        troughcolor="#dfe3e8", borderwidth=0)

    def _build_menu(self):
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=0)
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menu.add_cascade(label="File", menu=file_menu)
        help_menu = tk.Menu(menu, tearoff=0)
        help_menu.add_command(label="About", command=self._about)
        help_menu.add_command(label="Project page", command=lambda: webbrowser.open(PROJECT_URL))
        menu.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menu)

    def _build_toolbar(self):
        bar = ttk.Frame(self.root, style="Bar.TFrame", padding=(10, 8))
        bar.pack(fill="x")
        ttk.Label(bar, text="Actions ADFU Recovery Suite", style="Bar.TLabel",
                  font=FONT_TITLE).pack(side="left")
        ttk.Label(bar, text=f"v{__version__}  ·  read-only  ·  two-pass verified dumps",
                  style="Bar.TLabel").pack(side="left", padx=(12, 0))
        self.refresh_btn = ttk.Button(bar, text="Refresh Devices", style="Bar.TButton",
                                      command=self.refresh_devices)
        self.refresh_btn.pack(side="right")

    def _build_body(self):
        body = ttk.Frame(self.root, style="Panel.TFrame", padding=(12, 10))
        body.pack(fill="both", expand=True)

        # Left: device panel
        device = ttk.Labelframe(body, text=" Device ", style="Panel.TLabelframe", padding=12)
        device.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.device_fields = {}
        rows = [("mode", "Mode"), ("vidpid", "USB ID"), ("port", "Port path"),
                ("serial", "Serial"), ("stamp", "BootROM stamp"), ("cpu", "CPU")]
        for n, (key, label) in enumerate(rows):
            ttk.Label(device, text=label, style="Panel.TLabel", foreground=GREY)\
                .grid(row=n, column=0, sticky="w", pady=3)
            value = ttk.Label(device, text="—", style="Panel.TLabel", font=FONT_BOLD)
            value.grid(row=n, column=1, sticky="w", padx=(14, 0), pady=3)
            self.device_fields[key] = value
        device.columnconfigure(1, weight=1)

        # Right: functions
        functions = ttk.Labelframe(body, text=" Functions ", style="Panel.TLabelframe", padding=12)
        functions.grid(row=0, column=1, sticky="nsew")
        functions.columnconfigure((0, 1), weight=1, uniform="f")

        ttk.Label(functions, text="Mode entry", style="Panel.TLabel", foreground=GREY)\
            .grid(row=0, column=0, columnspan=2, sticky="w")
        drive_row = ttk.Frame(functions, style="Panel.TFrame")
        drive_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 8))
        self.drive_box = ttk.Combobox(drive_row, width=4, state="readonly",
                                      style="Panel.TCombobox")
        self.drive_box.pack(side="left")
        ttk.Label(drive_row, text="  drive letter of the card in normal mode",
                  style="Panel.TLabel").pack(side="left")
        self.adfu_btn = ttk.Button(functions, text="Enter ADFU Mode",
                                   command=self.enter_adfu)
        self.adfu_btn.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.info_btn = ttk.Button(functions, text="Read BootROM Info",
                                   command=self.read_info)
        self.info_btn.grid(row=2, column=1, sticky="ew", pady=(0, 8), padx=(8, 0))

        ttk.Separator(functions).grid(row=3, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Label(functions, text="Recovery", style="Panel.TLabel", foreground=GREY)\
            .grid(row=4, column=0, columnspan=2, sticky="w")
        self.dump_btn = ttk.Button(functions, text="Dump BootROM (32 KiB, two-pass)",
                                   style="Primary.TButton", command=self.dump_rom)
        self.dump_btn.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(2, 10))
        ttk.Label(functions, text="Output file:", style="Panel.TLabel")\
            .grid(row=6, column=0, sticky="w")
        self.output_var = tk.StringVar(value="rom.bin")
        ttk.Label(functions, textvariable=self.output_var, style="Panel.TLabel",
                  foreground=GREY).grid(row=6, column=1, sticky="e")
        ttk.Button(functions, text="Choose output location…",
                   command=self._choose_output).grid(row=7, column=0, columnspan=2,
                                                     sticky="ew", pady=(2, 10))

        ttk.Label(functions, text="Advanced (experimental)",
                  style="Panel.TLabel", foreground=GREY).grid(row=8, column=0, columnspan=2, sticky="w")
        adv = ttk.Frame(functions, style="Panel.TFrame")
        adv.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        self.start_var = tk.StringVar(value="0xBFC00000")
        self.chunks_var = tk.StringVar(value="1024")
        ttk.Label(adv, text="Start", style="Panel.TLabel").pack(side="left")
        ttk.Entry(adv, width=12, textvariable=self.start_var).pack(side="left", padx=(4, 10))
        ttk.Label(adv, text="Chunks/pass", style="Panel.TLabel").pack(side="left")
        ttk.Entry(adv, width=7, textvariable=self.chunks_var).pack(side="left", padx=4)
        self.adv_btn = ttk.Button(functions, text="Dump Window (experimental)",
                                  command=self.dump_window)
        self.adv_btn.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(functions, text="Unproven addresses run at your own risk; the "
                  "default dump below the toolbar always uses the sealed, "
                  "hardware-proven image.", style="Panel.TLabel", foreground=GREY,
                  wraplength=380, justify="left").grid(row=11, column=0, columnspan=2, sticky="w", pady=(6, 0))

        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

    def _build_progress(self):
        bar = ttk.Frame(self.root, style="Bar.TFrame", padding=(12, 6))
        bar.pack(fill="x")
        self.progress = ttk.Progressbar(bar, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True)
        self.progress_label = ttk.Label(bar, text="idle", style="Bar.TLabel", width=44)
        self.progress_label.pack(side="right", padx=(10, 0))

    def _build_log(self):
        frame = ttk.Frame(self.root, style="Panel.TFrame", padding=(12, 0, 12, 8))
        frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(frame, height=10, font=MONO, bg="#0d1117",
                                fg="#c9d1d9", relief="flat", state="disabled",
                                wrap="none")
        scroll = ttk.Scrollbar(frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for tag, color in (("info", "#8b949e"), ("ok", "#3fb950"),
                           ("warn", "#d29922"), ("error", "#f85149"),
                           ("data", "#58a6ff")):
            self.log_text.tag_configure(tag, foreground=color)

    def _build_statusbar(self):
        bar = ttk.Frame(self.root, style="Bar.TFrame", padding=(12, 5))
        bar.pack(fill="x", side="bottom")
        self.status = ttk.Label(bar, text="Ready", style="Bar.TLabel")
        self.status.pack(side="left")

    # ---- helpers -------------------------------------------------------
    def log(self, message: str, tag: str = "info"):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp()}] {message}\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _about(self):
        messagebox.showinfo(
            "About adfu-tool",
            f"adfu-tool {__version__}\n\n"
            "Read-only recovery and diagnostics for Actions Semiconductor\n"
            "ADFU devices. Dumps are two-pass verified; nothing is written\n"
            "to flash. GPL-2.0-or-later.\n\n" + PROJECT_URL)

    def _choose_output(self):
        chosen = filedialog.asksaveasfilename(
            defaultextension=".bin", initialfile="rom.bin",
            filetypes=[("ROM image", "*.bin"), ("All files", "*.*")])
        if chosen:
            self.output_var.set(chosen)

    def _set_busy(self, busy: bool, status: str = ""):
        state = "disabled" if busy else "normal"
        for button in (self.refresh_btn, self.adfu_btn, self.info_btn,
                       self.dump_btn, self.adv_btn):
            button.configure(state=state)
        if status:
            self.status.configure(text=status)

    def _poll_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self.log(payload[0], payload[1])
                elif kind == "status":
                    self.status.configure(text=payload)
                elif kind == "progress":
                    done, total, label = payload
                    self.progress.configure(mode="determinate", maximum=total, value=done)
                    self.progress_label.configure(text=label)
                elif kind == "indeterminate":
                    self.progress.configure(mode="indeterminate")
                    self.progress.start(12)
                    self.progress_label.configure(text=payload)
                elif kind == "progress_stop":
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0, maximum=100)
                    self.progress_label.configure(text=payload)
                elif kind == "device":
                    self._show_device(payload)
                elif kind == "done":
                    self._set_busy(False, payload)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_events)

    def _show_device(self, info: dict | None):
        if not info:
            for field in self.device_fields.values():
                field.configure(text="—", foreground="#000000")
            self.adfu_info = None
            return
        self.adfu_info = info
        stamp = info.get("stamp")
        values = {
            "mode": info["mode"].upper(),
            "vidpid": info["vid_pid"],
            "port": ".".join(map(str, info["port_numbers"])) or "?",
            "serial": info.get("serial") or "—",
            "stamp": stamp or "—",
            "cpu": info.get("cpu") or "—",
        }
        for key, value in values.items():
            self.device_fields[key].configure(
                text=value, foreground=GREEN if key == "mode" and info["mode"] == "adfu" else "#000000")

    def _spawn(self, name, target, status):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Busy", "An operation is already running.")
            return
        self._set_busy(True, status)
        self.events.put(("indeterminate", status))
        self.log(f"{name}…", "info")

        def runner():
            try:
                target()
            except AdfuError as error:
                self.events.put(("log", (f"error: {error}", "error")))
                self.events.put(("log", ("the device recovers with "
                                         "unplug → power off → power on", "warn")))
                self.events.put(("done", f"error: {str(error)[:80]}"))
            except Exception as error:  # unexpected - still surface it
                self.events.put(("log", (f"unexpected {type(error).__name__}: {error}", "error")))
                self.events.put(("done", "unexpected error"))
            else:
                pass
        self.worker = threading.Thread(target=runner, daemon=True)
        self.worker.start()

    # ---- operations ----------------------------------------------------
    def refresh_devices(self):
        self._spawn("Refreshing devices", self._refresh_devices, "Enumerating USB devices…")

    def _refresh_devices(self):
        adfu = device_mod.find_adfu()
        normal = device_mod.find_normal()
        self.events.put(("log", (f"found {len(adfu)} ADFU device(s), "
                                 f"{len(normal)} in normal mode", "info")))
        drives = [f"{letter}:" for letter in "EFGHIJKLMNOPQRSTUVWXYZ"
                  if Path(f"{letter}:/").exists()]
        self.events.put(("drives", drives))
        if adfu:
            info = device_mod.describe(adfu[0])
            info["mode"] = "adfu"
            info["stamp"] = None
            info["cpu"] = None
            self.events.put(("device", info))
            self.events.put(("status", "ADFU device found — you can read info or dump"))
            self.events.put(("log", ("card is already in ADFU mode", "ok")))
        elif normal:
            info = device_mod.describe(normal[0])
            info["mode"] = "normal"
            self.events.put(("device", info))
            self.events.put(("status", "card found in normal mode — use Enter ADFU Mode"))
            self.events.put(("log", ("card in normal mode; pick its drive letter "
                                     "and press Enter ADFU Mode", "info")))
        else:
            self.events.put(("device", None))
            self.events.put(("status", "no Actions devices found (VID 10d6)"))
        self.events.put(("done", "ready"))

    def enter_adfu(self):
        drive = self.drive_box.get().rstrip(":")
        if not drive:
            messagebox.showinfo("Pick a drive", "Select the card's drive letter first.")
            return

        def target():
            result = switch_to_adfu(drive, wait_seconds=30)
            self.events.put(("log", (f"mode switch sent; ADFU on port "
                                     f"{'.'.join(map(str, result['adfu_port_numbers'])) or '?'}", "ok")))
            self._refresh_devices()
        self._spawn("Entering ADFU mode", target, "Switching to ADFU — do not unplug…")

    def read_info(self):
        def target():
            session = Session(device_mod.open_single_adfu())
            identity = session.getinfo()
            stamp = identity[1:9].decode("ascii", "replace")
            self.events.put(("log", (f"GetInfo identity {identity.hex()}", "data")))
            self.events.put(("log", (f"bootROM stamp '{stamp}' "
                                     f"version {identity[9]:02x} '{chr(identity[10])}'", "ok")))
            if self.adfu_info:
                self.adfu_info["stamp"] = stamp
                self.events.put(("device", self.adfu_info))
            self.events.put(("status", "bootROM identity read"))
            self.events.put(("done", "identity read"))
        self._spawn("Reading bootROM info", target, "Talking to the bootROM…")

    def dump_rom(self):
        self._dump(loader_mod.DEFAULT_WINDOW, Path(self.output_var.get()))

    def dump_window(self):
        try:
            window = loader_mod.Window(int(self.start_var.get(), 0),
                                       int(self.chunks_var.get(), 0))
            loader_mod.validate_window(window)
        except (ValueError, AdfuError) as error:
            messagebox.showerror("Invalid window", str(error))
            return
        if not messagebox.askyesno(
                "Experimental window",
                "This window is not the hardware-proven default. Reading "
                "unproven addresses may hang the card (recovery: power cycle).\n\n"
                "Continue?"):
            return
        output = Path(self.output_var.get())
        self._dump(window, output.with_name(f"{output.stem}_{window.start:08x}{output.suffix}"))

    def _dump(self, window, output: Path):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Busy", "An operation is already running.")
            return
        if output.exists() and not messagebox.askyesno("Overwrite", f"{output} exists. Overwrite?"):
            return
        self._set_busy(True, f"Dumping {window.window_bytes} bytes…")

        def progress(kind, sequence, total, **extra):
            if kind == "cpu":
                matched = extra["cpu"]["matches_reference_v100"]
                self.events.put(("log", ("loader executing; CPU identity "
                                         + ("matched" if matched else "DIFFERS from reference"),
                                           "ok" if matched else "warn")))
                self.events.put(("progress", (0, total, f"0/{total} chunks")))
            else:
                self.events.put(("progress", (sequence, total, f"{sequence}/{total} chunks")))

        def target():
            _, encoded = loader_mod.image_for_window(window)
            session = Session(device_mod.open_single_adfu())
            identity = session.getinfo()
            self.events.put(("log", (f"GetInfo OK ({identity[1:9].decode('ascii', 'replace')})", "ok")))
            started = datetime.datetime.now()
            rom, info = run_read(session, encoded, window, on_progress=progress)
            elapsed = (datetime.datetime.now() - started).total_seconds()
            output.write_bytes(rom)
            import hashlib
            import json
            digest = hashlib.sha256(rom).hexdigest()
            output.with_suffix(output.suffix + ".report.json").write_text(
                json.dumps({"tool_version": __version__, "window": info["window"],
                            "cpu": info["cpu"], "rom_sha256": digest,
                            "rom_bytes": len(rom), "elapsed_seconds": round(elapsed, 3),
                            "passes_match": info["passes_match"]}, indent=2) + "\n",
                encoding="utf-8")
            self.events.put(("progress", (window.total_chunks, window.total_chunks,
                                          "complete")))
            self.events.put(("log", (f"saved {output} ({len(rom)} bytes)", "ok")))
            self.events.put(("log", (f"SHA-256 {digest}", "data")))
            self.events.put(("log", (f"two passes matched in {elapsed:.1f}s", "ok")))
            self.events.put(("status", "dump complete"))
            self.events.put(("done", "dump complete"))
        self._spawn(f"Dumping window {window.start:08x}", target, "Dumping…")


def run(smoke: bool = False) -> int:
    root = tk.Tk()
    app = GuiApp(root)
    if smoke:
        root.after(1200, root.destroy)
    root.mainloop()
    if smoke:
        print("gui smoke ok")
    return 0
