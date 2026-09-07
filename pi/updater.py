#!/usr/bin/env python3
"""WTP Scale — desktop control panel for the Raspberry Pi.

Double-click the icon on the desktop, press a button. Nothing else to know.

  Check for updates   ask GitHub whether a newer version exists
  Update now          download it, validate the data, restart the kiosk
  Start kiosk         bring the kiosk up (e.g. after stopping it to work here)
  Stop kiosk          drop back to the desktop
  Restart kiosk       restart without downloading anything
  Show status         is the reader running, which version is installed
  Log                 live feed: every tag read, what it mapped to, screen
                      changes and reader health, as they happen

A line under the title shows whether the kiosk is currently running, so you
can tell at a glance without reading the log.

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
        self.log_proc = None          # journalctl -f while the Log view is open

        heading = tkfont.Font(family="DejaVu Sans", size=20, weight="bold")
        label = tkfont.Font(family="DejaVu Sans", size=11)

        tk.Label(self, text="WTP Scale", font=heading, bg=BLUE, fg=ORANGE).pack(pady=(18, 0))
        self.version = tk.Label(self, text="", font=label, bg=BLUE, fg="white")
        self.version.pack(pady=(2, 0))
        self.state = tk.Label(self, text="", font=label, bg=BLUE, fg="white")
        self.state.pack(pady=(0, 12))

        self.buttons = []
        # Updates on one row, kiosk control on the next: four buttons across a
        # 720px window on a Pi screen would be too cramped to hit reliably.
        self.by_text = {}
        for row_spec in (
            (("Check for updates", self.check), ("Update now", self.update_now),
             ("Log", self.toggle_log)),
            (("Start kiosk", self.start), ("Stop kiosk", self.stop),
             ("Restart kiosk", self.restart), ("Show status", self.status)),
        ):
            bar = tk.Frame(self, bg=BLUE)
            bar.pack(fill="x", padx=18, pady=(0, 6))
            for text, handler in row_spec:
                primary = text in ("Update now", "Start kiosk")
                b = tk.Button(bar, text=text, font=label, command=handler,
                              bg=ORANGE if primary else "white",
                              fg="white" if primary else BLUE,
                              activebackground=ORANGE, relief="flat",
                              padx=12, pady=10, cursor="hand2")
                b.pack(side="left", expand=True, fill="x", padx=4)
                self.buttons.append(b)
                self.by_text[text] = b

        self.log = scrolledtext.ScrolledText(
            self, font=("DejaVu Sans Mono", 10), bg=PAPER, fg="#111",
            relief="flat", wrap="word", height=16)
        self.log.pack(fill="both", expand=True, padx=18, pady=18)
        self.log.configure(state="disabled")

        self.show_version()
        self.refresh_state()
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
        self.stop_log()
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

    def refresh_state(self):
        """Poll systemd so the header reflects reality, not the last button pressed."""
        def active(unit):
            try:
                return subprocess.run(["systemctl", "--user", "is-active", unit],
                                      capture_output=True, text=True).stdout.strip()
            except Exception:                                # noqa: BLE001
                return "unknown"

        reader, browser = active("wtp-kiosk.service"), active("wtp-browser.service")
        if reader == "active" and browser == "active":
            text, colour = "Kiosk: running", "#8ef0a0"
        elif reader == "active" or browser == "active":
            text, colour = f"Kiosk: partly up (reader {reader}, screen {browser})", "#ffd28a"
        elif "unknown" in (reader, browser):
            text, colour = "Kiosk: state unavailable", "white"
        else:
            text, colour = "Kiosk: stopped", "#ffb0a0"

        self.state.configure(text=text, fg=colour)
        self.after(3000, self.refresh_state)

    # ------------------------------------------------------------ live log

    LOG_KEEP = ("[reader]", "[page] view", "[page] tag", "[page] unknown-tag",
                "[page] video-reload", "[kiosk]")

    @staticmethod
    def tidy(line):
        """'Sep 07 11:05:18 raspberrypi python3[13000]: [reader] tag read -> X'
        becomes '11:05:18  tag read -> X'. The journal prefix is noise here."""
        head, sep, msg = line.partition("]: ")
        if not sep:
            return line
        stamp = head.split()[2] if len(head.split()) > 2 else ""
        msg = msg.replace("[reader] ", "").replace("[page] ", "screen: ").replace("[kiosk] ", "")
        return f"{stamp}  {msg}"

    def toggle_log(self):
        if self.log_proc:
            self.stop_log()
            return
        if self.busy:
            return
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.output.put("Live log -- tag reads, screen changes, reader health\n"
                        "----------------------------------------------------\n")
        try:
            self.log_proc = subprocess.Popen(
                ["journalctl", "--user", "-u", "wtp-kiosk.service", "-f", "-n", "40",
                 "--no-pager", "-o", "short"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        except FileNotFoundError as exc:
            self.output.put(f"Could not start the log: {exc}\n")
            self.log_proc = None
            return
        self.by_text["Log"].configure(text="Stop log", bg=ORANGE, fg="white")

        def pump(proc):
            for line in proc.stdout:
                if any(k in line for k in self.LOG_KEEP):
                    self.output.put(self.tidy(line.rstrip()) + "\n")
            if self.log_proc is proc:
                self.after(0, self.stop_log)

        threading.Thread(target=pump, args=(self.log_proc,), daemon=True).start()

    def stop_log(self):
        proc, self.log_proc = self.log_proc, None
        if proc:
            try:
                proc.terminate()
            except OSError:
                pass
            self.by_text["Log"].configure(text="Log", bg="white", fg=BLUE)

    # -------------------------------------------------------------- actions

    def check(self):
        self.run(["bash", str(REPO / "pi" / "update.sh"), "--check"],
                 "Checking for updates")

    def update_now(self):
        self.run(["bash", str(REPO / "pi" / "update.sh")], "Updating")

    def start(self):
        self.run(["systemctl", "--user", "start",
                  "wtp-kiosk.service", "wtp-browser.service"], "Starting the kiosk")

    def stop(self):
        # Browser first: stopping the reader out from under it would leave the
        # page briefly showing a dead connection before the window closed.
        self.run(["systemctl", "--user", "stop",
                  "wtp-browser.service", "wtp-kiosk.service"], "Stopping the kiosk")

    def restart(self):
        self.run(["systemctl", "--user", "restart",
                  "wtp-kiosk.service", "wtp-browser.service"], "Restarting the kiosk")

    def status(self):
        # Both units, then their recent logs. `systemctl start` prints nothing
        # when a unit starts and then immediately dies, so the logs are the
        # only way to see what actually happened without opening a terminal.
        self.run(["bash", "-c", r"""
echo "--- reader service ---"
systemctl --user --no-pager --lines=0 status wtp-kiosk.service 2>&1 | head -6
echo
echo "--- browser service ---"
systemctl --user --no-pager --lines=0 status wtp-browser.service 2>&1 | head -6
echo
echo "--- display session ---"
echo "session type : ${XDG_SESSION_TYPE:-unknown}"
echo "DISPLAY      : ${DISPLAY:-unset}"
echo "WAYLAND      : ${WAYLAND_DISPLAY:-unset}"
echo
echo "--- is the page being served? ---"
curl -sf -o /dev/null -w "  localhost:8080 -> HTTP %{http_code}
" http://127.0.0.1:8080/state   || echo "  no answer from the reader service"
echo
echo "--- last 20 log lines, browser ---"
journalctl --user -u wtp-browser.service -n 20 --no-pager 2>&1 | tail -20
echo
echo "--- last 10 log lines, reader ---"
journalctl --user -u wtp-kiosk.service -n 10 --no-pager 2>&1 | tail -10
"""], "Status")


if __name__ == "__main__":
    Updater().mainloop()
