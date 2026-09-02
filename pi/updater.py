#!/usr/bin/env python3
"""WTP Scale — desktop control panel for the Raspberry Pi.

Double-click the icon on the desktop, press a button. Nothing else to know.

  Check for updates   ask GitHub whether a newer version exists
  Update now          download it, validate the data, restart the kiosk
  Restart kiosk       restart without downloading anything
  Show status         is the reader running, which version is installed

Deliberately Tkinter: it ships with Raspberry Pi OS (python3-tk), needs no
network at launch and no extra packages.
"""

import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import scrolledtext

REPO = Path(__file__).resolve().parent.parent

BLUE = "#002e5a"
ORANGE = "#ff6b26"
PAPER = "#f1f1f1"


class Updater(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WTP Scale")
        self.configure(bg=BLUE)
        self.geometry("720x520")
        self.minsize(600, 440)

        self.output = queue.Queue()
        self.busy = False

        heading = tkfont.Font(family="DejaVu Sans", size=20, weight="bold")
        label = tkfont.Font(family="DejaVu Sans", size=11)

        tk.Label(self, text="WTP Scale", font=heading, bg=BLUE, fg=ORANGE).pack(pady=(18, 0))
        self.version = tk.Label(self, text="", font=label, bg=BLUE, fg="white")
        self.version.pack(pady=(2, 12))

        bar = tk.Frame(self, bg=BLUE)
        bar.pack(fill="x", padx=18)
        self.buttons = []
        for text, handler in (
            ("Check for updates", self.check),
            ("Update now", self.update_now),
            ("Restart kiosk", self.restart),
            ("Show status", self.status),
        ):
            b = tk.Button(bar, text=text, font=label, command=handler,
                          bg=ORANGE if text == "Update now" else "white",
                          fg="white" if text == "Update now" else BLUE,
                          activebackground=ORANGE, relief="flat",
                          padx=14, pady=10, cursor="hand2")
            b.pack(side="left", expand=True, fill="x", padx=4)
            self.buttons.append(b)

        self.log = scrolledtext.ScrolledText(
            self, font=("DejaVu Sans Mono", 10), bg=PAPER, fg="#111",
            relief="flat", wrap="word", height=16)
        self.log.pack(fill="both", expand=True, padx=18, pady=18)
        self.log.configure(state="disabled")

        self.show_version()
        self.after(120, self.drain)

    # ---------------------------------------------------------------- utils

    def write(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def drain(self):
        while not self.output.empty():
            self.write(self.output.get())
        self.after(120, self.drain)

    def set_busy(self, busy):
        self.busy = busy
        for b in self.buttons:
            b.configure(state="disabled" if busy else "normal")

    def run(self, args, title):
        """Run a command on a worker thread, streaming output into the log."""
        if self.busy:
            return
        self.set_busy(True)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.output.put(f"{title}\n{'-' * len(title)}\n")

        def worker():
            try:
                proc = subprocess.Popen(
                    args, cwd=REPO, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, bufsize=1)
                for line in proc.stdout:
                    self.output.put(line)
                proc.wait()
                self.output.put(
                    "\nFinished.\n" if proc.returncode == 0
                    else f"\nStopped with an error (code {proc.returncode}).\n")
            except FileNotFoundError as exc:
                self.output.put(f"\nCould not run: {exc}\n")
            finally:
                self.after(0, lambda: self.set_busy(False))
                self.after(0, self.show_version)

        threading.Thread(target=worker, daemon=True).start()

    def show_version(self):
        try:
            desc = subprocess.run(
                ["git", "log", "-1", "--format=%h  %cd  %s", "--date=format:%d %b %Y"],
                cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
        except Exception:                                    # noqa: BLE001
            desc = "version unknown"
        self.version.configure(text=f"Installed: {desc}")

    # -------------------------------------------------------------- actions

    def check(self):
        self.run(["bash", str(REPO / "pi" / "update.sh"), "--check"],
                 "Checking for updates")

    def update_now(self):
        self.run(["bash", str(REPO / "pi" / "update.sh")], "Updating")

    def restart(self):
        self.run(["systemctl", "--user", "restart",
                  "wtp-kiosk.service", "wtp-browser.service"], "Restarting the kiosk")

    def status(self):
        self.run(["bash", "-c",
                  "systemctl --user --no-pager status wtp-kiosk.service | head -12; echo; "
                  "python3 tools/validate.py"],
                 "Status")


if __name__ == "__main__":
    Updater().mainloop()
