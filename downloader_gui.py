"""
GitHub Workflow Downloader — GUI  v2.1
Requires: pip install PyGithub requests
"""

import os
import re
import time
import shutil
import tempfile
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from urllib.parse import urlparse
from datetime import datetime
import requests
from github import Auth, Github

# ─────────────────────────────────────────────────────────────────────────────
# THEME
# ─────────────────────────────────────────────────────────────────────────────
BG      = "#0d1117"
BG2     = "#161b27"
BG3     = "#1c2333"
BG4     = "#21283a"
ACCENT  = "#58a6ff"
ACCENT2 = "#79c0ff"
ACCENT3 = "#1f6feb"
NEON    = "#39d353"
NEON2   = "#26a641"
GOLD    = "#e3b341"
DANGER  = "#f85149"
DANGER2 = "#da3633"
PURPLE  = "#bc8cff"
GRAY    = "#484f58"
GRAY2   = "#8b949e"
GRAY3   = "#c9d1d9"
WHITE   = "#e6edf3"
BORDER  = "#30363d"

FONT_BOLD  = ("Consolas", 10, "bold")
FONT_MAIN  = ("Consolas", 9)
FONT_MONO  = ("Consolas", 9)
FONT_SMALL = ("Consolas", 8)
FONT_BIG   = ("Consolas", 22, "bold")

MIN_SPEED      = 200 * 1024
MAX_RETRIES    = 2000
RETRY_DELAY    = 1
INTER_DL_DELAY = 10   # seconds to wait between downloads


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def generate_folder_name():
    return datetime.now().strftime("%m%d%H%M%S")


def fmt_bytes(b):
    if b >= 1_073_741_824:
        return f"{b / 1_073_741_824:.2f} GB"
    if b >= 1_048_576:
        return f"{b / 1_048_576:.1f} MB"
    if b >= 1024:
        return f"{b / 1024:.0f} KB"
    return f"{b} B"


def extract_urls(text):
    """Extract all valid http(s) URLs from arbitrary text."""
    found = re.findall(r'https?://[^\s,\'"<>\[\]]+', text)
    seen = []
    for u in found:
        u = u.rstrip(".,;)")
        if u not in seen:
            seen.append(u)
    return seen


# ─────────────────────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────────────────────

class DownloaderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GitHub Workflow Downloader")
        self.geometry("960x880")
        self.minsize(780, 640)
        self.configure(bg=BG)
        self.resizable(True, True)

        self._urls    = []
        self._running = False
        self._abort   = threading.Event()

        self._style_ttk()
        self._build_ui()

    # ─── ttk styles ──────────────────────────────────────────────────────────
    def _style_ttk(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=GRAY3, font=FONT_MAIN)

        s.configure("Horizontal.TProgressbar",
                    troughcolor=BG4, background=ACCENT,
                    thickness=6, bordercolor=BG4,
                    lightcolor=ACCENT2, darkcolor=ACCENT3)
        s.configure("Green.Horizontal.TProgressbar",
                    troughcolor=BG4, background=NEON,
                    thickness=6, bordercolor=BG4,
                    lightcolor=NEON, darkcolor=NEON2)

        s.configure("Primary.TButton",
                    background=ACCENT3, foreground=WHITE,
                    font=FONT_BOLD, padding=(18, 10),
                    relief="flat", bordercolor=ACCENT3, focuscolor="none")
        s.map("Primary.TButton",
              background=[("active", ACCENT), ("disabled", BG3)],
              foreground=[("disabled", GRAY)])

        s.configure("Ghost.TButton",
                    background=BG3, foreground=GRAY2,
                    font=FONT_MAIN, padding=(10, 7),
                    relief="flat", bordercolor=BORDER, focuscolor="none")
        s.map("Ghost.TButton",
              background=[("active", BG4)],
              foreground=[("active", WHITE)])

        s.configure("Danger.TButton",
                    background=BG3, foreground=DANGER,
                    font=FONT_MAIN, padding=(8, 5),
                    relief="flat", bordercolor=BORDER, focuscolor="none")
        s.map("Danger.TButton",
              background=[("active", "#2d1a1a")],
              foreground=[("active", "#ff6b6b")])

        s.configure("Abort.TButton",
                    background="#2d1a1a", foreground=DANGER,
                    font=FONT_BOLD, padding=(14, 9),
                    relief="flat", bordercolor=DANGER2, focuscolor="none")
        s.map("Abort.TButton",
              background=[("active", "#3d2020")],
              foreground=[("active", "#ff8080")])

    # ─── UI ──────────────────────────────────────────────────────────────────
    def _build_ui(self):

        # ── bottom action bar ─────────────────────────────────────────────────
        act = tk.Frame(self, bg=BG2)
        act.pack(side="bottom", fill="x")
        tk.Frame(act, bg=ACCENT3, height=1).pack(fill="x")
        btn_row = tk.Frame(act, bg=BG2)
        btn_row.pack(fill="x", padx=20, pady=14)

        self._dl_btn = ttk.Button(btn_row, text="  Start Download",
                                  style="Primary.TButton",
                                  command=self._start_thread)
        self._dl_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self._abort_btn = ttk.Button(btn_row, text="x Abort",
                                     style="Abort.TButton",
                                     command=self._do_abort,
                                     state="disabled")
        self._abort_btn.pack(side="left", padx=(0, 8))

        ttk.Button(btn_row, text="Clear All",
                   style="Ghost.TButton",
                   command=self._clear_all).pack(side="left")

        # ── scrollable canvas ─────────────────────────────────────────────────
        vsb = ttk.Scrollbar(self, orient="vertical")
        canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0,
                           yscrollcommand=vsb.set)
        vsb.configure(command=canvas.yview)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=BG)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        inner.bind("<Configure>",
                   lambda e: canvas.configure(
                       scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win_id, width=e.width))
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(
                            int(-1 * (e.delta / 120)), "units"))

        pad = tk.Frame(inner, bg=BG)
        pad.pack(fill="both", expand=True, padx=20, pady=16)

        # ── header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(pad, bg=BG)
        hdr.pack(fill="x", pady=(0, 4))

        logo = tk.Frame(hdr, bg=BG)
        logo.pack(side="left")
        tk.Label(logo, text="^", bg=BG, fg=ACCENT,
                 font=("Consolas", 30, "bold")).pack(side="left",
                                                     padx=(0, 10))
        titles = tk.Frame(logo, bg=BG)
        titles.pack(side="left")
        tk.Label(titles, text="GITHUB WORKFLOW DOWNLOADER",
                 bg=BG, fg=WHITE,
                 font=("Consolas", 15, "bold")).pack(anchor="w")
        tk.Label(titles,
                 text="v2.1  —  multi-url  |  auto-retry  |  chunked",
                 bg=BG, fg=GRAY2, font=FONT_SMALL).pack(anchor="w")

        self._badge = tk.Label(hdr, text=" o IDLE ",
                               bg=BG3, fg=GRAY2,
                               font=("Consolas", 9, "bold"),
                               padx=10, pady=4)
        self._badge.pack(side="right", anchor="n")

        tk.Frame(pad, bg=BORDER, height=1).pack(fill="x",
                                                pady=(8, 14))

        # ── stat cards ────────────────────────────────────────────────────────
        stats = tk.Frame(pad, bg=BG)
        stats.pack(fill="x", pady=(0, 14))
        self._stat_queued = self._stat_card(stats, "QUEUED", "0",  ACCENT)
        self._stat_done   = self._stat_card(stats, "DONE",   "0",  NEON)
        self._stat_failed = self._stat_card(stats, "FAILED", "0",  DANGER)
        self._stat_speed  = self._stat_card(stats, "SPEED",  "--", GOLD)

        # ── URL queue card ────────────────────────────────────────────────────
        url_c = self._card(pad, "DOWNLOAD QUEUE", ACCENT)

        tk.Label(url_c, text="Paste one or more URLs  (one per line or space-separated):",
                 bg=BG2, fg=GRAY2, font=FONT_SMALL).pack(anchor="w",
                                                          pady=(0, 4))

        txt_wrap = tk.Frame(url_c, bg=BORDER)
        txt_wrap.pack(fill="x", pady=(0, 6))
        self._url_text = tk.Text(txt_wrap, bg=BG3, fg=WHITE,
                                 insertbackground=ACCENT,
                                 relief="flat", font=FONT_MONO,
                                 bd=6, height=3, wrap="none")
        txt_sb = ttk.Scrollbar(txt_wrap, orient="vertical",
                               command=self._url_text.yview)
        self._url_text.configure(yscrollcommand=txt_sb.set)
        self._url_text.pack(side="left", fill="both", expand=True)
        txt_sb.pack(side="right", fill="y")
        self._url_text.bind("<Control-Return>",
                            lambda e: self._add_urls())

        ar = tk.Frame(url_c, bg=BG2)
        ar.pack(fill="x", pady=(0, 8))
        ttk.Button(ar, text="+ Add URL(s)",
                   style="Ghost.TButton",
                   command=self._add_urls).pack(side="left")
        tk.Label(ar, text="   Ctrl+Enter to quick-add",
                 bg=BG2, fg=GRAY,
                 font=FONT_SMALL).pack(side="left")

        lb_wrap = tk.Frame(url_c, bg=BG3)
        lb_wrap.pack(fill="both", expand=True)
        self._url_lb = tk.Listbox(lb_wrap, bg=BG3, fg=GRAY3,
                                  selectbackground=ACCENT3,
                                  selectforeground=WHITE,
                                  relief="flat", bd=0,
                                  font=FONT_MONO,
                                  activestyle="none", height=5)
        lb_sb = ttk.Scrollbar(lb_wrap, orient="vertical",
                              command=self._url_lb.yview)
        self._url_lb.configure(yscrollcommand=lb_sb.set)
        self._url_lb.pack(side="left", fill="both",
                          expand=True, padx=6, pady=6)
        lb_sb.pack(side="right", fill="y")

        rm_row = tk.Frame(url_c, bg=BG2)
        rm_row.pack(fill="x", pady=(4, 0))
        ttk.Button(rm_row, text="x Remove Selected",
                   style="Danger.TButton",
                   command=self._remove_url).pack(side="right")
        ttk.Button(rm_row, text="x Remove All",
                   style="Danger.TButton",
                   command=self._remove_all_urls).pack(side="right",
                                                       padx=(0, 6))

        # ── output dir card ───────────────────────────────────────────────────
        dir_c = self._card(pad, "OUTPUT DIRECTORY", GOLD)
        dir_row = tk.Frame(dir_c, bg=BG2)
        dir_row.pack(fill="x")
        self._dir_var = tk.StringVar(value=os.getcwd())
        tk.Entry(dir_row, textvariable=self._dir_var,
                 bg=BG3, fg=WHITE, insertbackground=ACCENT,
                 relief="flat", font=FONT_MONO,
                 bd=6).pack(side="left", fill="x",
                             expand=True, ipady=6)
        ttk.Button(dir_row, text="Browse...",
                   style="Ghost.TButton",
                   command=self._browse).pack(side="left",
                                              padx=(8, 0))

        # ── github config card ────────────────────────────────────────────────
        cfg_c = self._card(pad, "GITHUB CONFIGURATION", PURPLE)
        grid = tk.Frame(cfg_c, bg=BG2)
        grid.pack(fill="x")
        fields = [
            ("GitHub Token",      "GH_TOKEN", True),
            ("Repo Owner",        "astwdnya",           False),
            ("Repo Name",         "downloader",         False),
            ("Branch",            "main",               False),
            ("Download Workflow", "download-split.yml", False),
            ("Delete Workflow",   "delete-folder.yml",  False),
        ]
        self._cfg = {}
        for i, (lbl, default, secret) in enumerate(fields):
            row, col = divmod(i, 2)
            tk.Label(grid, text=lbl, bg=BG2, fg=GRAY2,
                     font=FONT_SMALL).grid(
                row=row * 2, column=col,
                sticky="w", padx=(0, 16), pady=(8, 2))
            e = tk.Entry(grid, bg=BG3, fg=WHITE,
                         insertbackground=ACCENT,
                         relief="flat", font=FONT_MONO, bd=6,
                         show="*" if secret else "")
            e.insert(0, default)
            e.grid(row=row * 2 + 1, column=col,
                   sticky="ew", padx=(0, 16), ipady=6)
            self._cfg[lbl] = e
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        # ── progress card ─────────────────────────────────────────────────────
        prg_c = self._card(pad, "PROGRESS", NEON)

        tk.Label(prg_c, text="OVERALL",
                 bg=BG2, fg=GRAY2,
                 font=FONT_SMALL).pack(anchor="w", pady=(0, 2))
        ov_top = tk.Frame(prg_c, bg=BG2)
        ov_top.pack(fill="x", pady=(0, 2))
        self._prog_label = tk.Label(ov_top, text="Ready to download",
                                    bg=BG2, fg=GRAY3, font=FONT_MAIN)
        self._prog_label.pack(side="left")
        self._prog_pct = tk.Label(ov_top, text="0%",
                                  bg=BG2, fg=ACCENT2, font=FONT_BOLD)
        self._prog_pct.pack(side="right")
        self._prog_bar = ttk.Progressbar(
            prg_c, style="Horizontal.TProgressbar",
            mode="determinate", maximum=100)
        self._prog_bar.pack(fill="x", pady=(0, 10))

        tk.Label(prg_c, text="CURRENT FILE",
                 bg=BG2, fg=GRAY2,
                 font=FONT_SMALL).pack(anchor="w", pady=(0, 2))
        fi_top = tk.Frame(prg_c, bg=BG2)
        fi_top.pack(fill="x", pady=(0, 2))
        self._file_label = tk.Label(fi_top, text="--",
                                    bg=BG2, fg=GRAY3, font=FONT_MAIN)
        self._file_label.pack(side="left")
        self._file_pct = tk.Label(fi_top, text="",
                                  bg=BG2, fg=NEON, font=FONT_BOLD)
        self._file_pct.pack(side="right")
        self._file_bar = ttk.Progressbar(
            prg_c, style="Green.Horizontal.TProgressbar",
            mode="determinate", maximum=100)
        self._file_bar.pack(fill="x", pady=(0, 10))

        sub = tk.Frame(prg_c, bg=BG2)
        sub.pack(fill="x")
        self._lbl_elapsed = self._sub_stat(sub, "ELAPSED", "--")
        self._lbl_bytes   = self._sub_stat(sub, "SIZE",    "-- / --")
        self._lbl_retries = self._sub_stat(sub, "RETRIES", "0")
        self._lbl_item    = self._sub_stat(sub, "FILE #",  "--")
        self._lbl_wait    = self._sub_stat(sub, "NEXT IN", "--")

        # ── log card ──────────────────────────────────────────────────────────
        log_c = self._card(pad, "ACTIVITY LOG", ACCENT)
        log_hdr = tk.Frame(log_c, bg=BG2)
        log_hdr.pack(fill="x", pady=(0, 4))
        ttk.Button(log_hdr, text="Clear Log",
                   style="Ghost.TButton",
                   command=self._log_clear).pack(side="right")

        log_wrap = tk.Frame(log_c, bg=BG3)
        log_wrap.pack(fill="both", expand=True)
        self._log = tk.Text(log_wrap, bg=BG3, fg=GRAY2,
                            insertbackground=WHITE,
                            relief="flat", font=FONT_MONO,
                            state="disabled", height=10,
                            bd=6, wrap="none")
        log_vsb = ttk.Scrollbar(log_wrap, orient="vertical",
                                command=self._log.yview)
        self._log.configure(yscrollcommand=log_vsb.set)
        self._log.pack(side="left", fill="both",
                       expand=True, padx=4, pady=4)
        log_vsb.pack(side="right", fill="y")

        self._log.tag_configure("ok",   foreground=NEON)
        self._log.tag_configure("err",  foreground=DANGER)
        self._log.tag_configure("info", foreground=ACCENT2)
        self._log.tag_configure("warn", foreground=GOLD)
        self._log.tag_configure("head", foreground=PURPLE)

    # ─── widget helpers ───────────────────────────────────────────────────────
    def _card(self, parent, title, color=ACCENT):
        outer = tk.Frame(parent, bg=BG2)
        outer.pack(fill="x", pady=(0, 10))
        tk.Frame(outer, bg=color, height=2).pack(fill="x")
        tk.Label(outer, text="  " + title,
                 bg=BG2, fg=color,
                 font=("Consolas", 8, "bold")).pack(
            anchor="w", padx=14, pady=6)
        body = tk.Frame(outer, bg=BG2)
        body.pack(fill="both", expand=True, padx=14)
        # bottom padding via empty frame
        tk.Frame(outer, bg=BG2, height=12).pack(fill="x")
        return body

    def _stat_card(self, parent, label, val, color):
        f = tk.Frame(parent, bg=BG2)
        f.pack(side="left", fill="x", expand=True, padx=(0, 8))
        tk.Frame(f, bg=color, height=2).pack(fill="x")
        v = tk.Label(f, text=val, bg=BG2, fg=color, font=FONT_BIG)
        v.pack(pady=(8, 0))
        tk.Label(f, text=label, bg=BG2, fg=GRAY2,
                 font=("Consolas", 7, "bold")).pack(pady=(0, 8))
        return v

    def _sub_stat(self, parent, label, val):
        f = tk.Frame(parent, bg=BG2)
        f.pack(side="left", padx=(0, 18))
        tk.Label(f, text=label, bg=BG2, fg=GRAY2,
                 font=("Consolas", 7, "bold")).pack(anchor="w")
        lbl = tk.Label(f, text=val, bg=BG2, fg=WHITE, font=FONT_MONO)
        lbl.pack(anchor="w")
        return lbl

    # ─── user actions ─────────────────────────────────────────────────────────
    def _add_urls(self):
        raw = self._url_text.get("1.0", "end").strip()
        if not raw:
            return
        urls = extract_urls(raw)
        added = 0
        for u in urls:
            if u not in self._urls:
                self._urls.append(u)
                self._url_lb.insert("end", u)
                added += 1
        self._url_text.delete("1.0", "end")
        self._stat_queued.configure(text=str(len(self._urls)))
        if added:
            self._log_write(f"+ Added {added} URL(s) to queue.", "info")
        else:
            self._log_write("No new valid URLs found.", "warn")

    def _remove_url(self):
        for i in reversed(self._url_lb.curselection()):
            self._url_lb.delete(i)
            self._urls.pop(i)
        self._stat_queued.configure(text=str(len(self._urls)))

    def _remove_all_urls(self):
        if self._running:
            return
        self._urls.clear()
        self._url_lb.delete(0, "end")
        self._stat_queued.configure(text="0")

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self._dir_var.get())
        if d:
            self._dir_var.set(d)

    def _clear_all(self):
        if self._running:
            return
        self._urls.clear()
        self._url_lb.delete(0, "end")
        self._url_text.delete("1.0", "end")
        self._log_clear()
        self._reset_ui()

    def _reset_ui(self):
        self._prog_bar["value"]  = 0
        self._file_bar["value"]  = 0
        self._prog_pct.configure(text="0%")
        self._file_pct.configure(text="")
        self._prog_label.configure(text="Ready to download")
        self._file_label.configure(text="--")
        self._stat_queued.configure(text=str(len(self._urls)))
        self._stat_done.configure(text="0")
        self._stat_failed.configure(text="0")
        self._stat_speed.configure(text="--")
        self._lbl_elapsed.configure(text="--")
        self._lbl_bytes.configure(text="-- / --")
        self._lbl_retries.configure(text="0")
        self._lbl_item.configure(text="--")
        self._lbl_wait.configure(text="--")
        self._set_badge("idle")

    def _do_abort(self):
        self._abort.set()
        self._log_write("Abort requested...", "warn")
        self._abort_btn.configure(state="disabled")

    def _set_badge(self, state):
        s = {
            "idle":    (BG3,     GRAY2,   " o IDLE "),
            "running": (ACCENT3, ACCENT2, " o DOWNLOADING "),
            "waiting": (BG4,     GOLD,    " o WAITING "),
            "done":    (NEON2,   BG,      " o DONE "),
            "error":   (DANGER2, WHITE,   " o ERROR "),
            "aborted": (BG3,     GOLD,    " o ABORTED "),
        }
        bg, fg, txt = s.get(state, s["idle"])
        self._badge.configure(bg=bg, fg=fg, text=txt)

    # ─── log helpers ──────────────────────────────────────────────────────────
    def _log_clear(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _log_write(self, msg, tag=""):
        def _do():
            ts = datetime.now().strftime("%H:%M:%S")
            self._log.configure(state="normal")
            self._log.insert("end", f"[{ts}] {msg}\n", tag)
            self._log.see("end")
            self._log.configure(state="disabled")
        self.after(0, _do)

    def _set_progress(self, pct, label=None):
        def _do():
            self._prog_bar["value"] = pct
            self._prog_pct.configure(text=f"{int(pct)}%")
            if label:
                self._prog_label.configure(text=label)
        self.after(0, _do)

    def _set_file_progress(self, pct, label=None):
        def _do():
            self._file_bar["value"] = pct
            self._file_pct.configure(
                text=f"{int(pct)}%" if pct > 0 else "")
            if label is not None:
                self._file_label.configure(text=label)
        self.after(0, _do)

    # ─── countdown between downloads ─────────────────────────────────────────
    def _countdown(self, seconds):
        for remaining in range(seconds, 0, -1):
            if self._abort.is_set():
                return
            self.after(0, lambda r=remaining:
                       self._lbl_wait.configure(text=f"{r}s"))
            self._set_badge("waiting")
            time.sleep(1)
        self.after(0, lambda: self._lbl_wait.configure(text="--"))
        self._set_badge("running")

    # ─── download thread ──────────────────────────────────────────────────────
    def _start_thread(self):
        if self._running:
            return
        if not self._urls:
            messagebox.showwarning(
                "No URLs",
                "Please add at least one URL to the queue.")
            return

        token  = self._cfg["GitHub Token"].get().strip()
        owner  = self._cfg["Repo Owner"].get().strip()
        repo   = self._cfg["Repo Name"].get().strip()
        branch = self._cfg["Branch"].get().strip() or "main"
        dl_wf  = self._cfg["Download Workflow"].get().strip()
        del_wf = self._cfg["Delete Workflow"].get().strip()
        out    = self._dir_var.get().strip() or os.getcwd()

        if not token or not owner or not repo:
            messagebox.showwarning(
                "Config",
                "Please fill in Token, Owner, and Repo Name.")
            return

        self._running = True
        self._abort.clear()

        self._stat_done.configure(text="0")
        self._stat_failed.configure(text="0")
        self._stat_speed.configure(text="--")
        self._lbl_retries.configure(text="0")
        self._lbl_bytes.configure(text="-- / --")
        self._lbl_wait.configure(text="--")
        self._file_bar["value"] = 0
        self._file_pct.configure(text="")

        self._dl_btn.configure(state="disabled")
        self._abort_btn.configure(state="normal")
        self._set_badge("running")
        self._log_write(
            f"=== Starting batch: {len(self._urls)} URL(s) ===",
            "head")

        threading.Thread(
            target=self._download_all,
            args=(token, owner, repo, branch, dl_wf, del_wf, out),
            daemon=True
        ).start()

    def _download_all(self, token, owner, repo_name,
                      branch, dl_wf, del_wf, out_dir):
        session = requests.Session()
        session.trust_env = False
        session.proxies   = {"http": None, "https": None}
        for v in ["HTTP_PROXY", "HTTPS_PROXY",
                  "http_proxy", "https_proxy"]:
            os.environ.pop(v, None)

        try:
            gh_repo = Github(auth=Auth.Token(token)).get_repo(
                f"{owner}/{repo_name}")
            self._log_write(
                f"Authenticated  {owner}/{repo_name}", "ok")
        except Exception as e:
            self._log_write(f"GitHub auth failed: {e}", "err")
            self._finish(error=True)
            return

        os.makedirs(out_dir, exist_ok=True)

        done   = 0
        failed = 0
        total  = len(self._urls)
        start  = time.time()

        def tick():
            if self._running:
                elapsed = int(time.time() - start)
                m, s = divmod(elapsed, 60)
                self.after(0, lambda m=m, s=s:
                           self._lbl_elapsed.configure(
                               text=f"{m:02d}:{s:02d}"))
                self.after(1000, tick)
        self.after(1000, tick)

        urls_snapshot = list(self._urls)

        for idx, url in enumerate(urls_snapshot):
            if self._abort.is_set():
                self._log_write("Aborted by user.", "warn")
                break

            self.after(0, lambda i=idx, t=total:
                       self._lbl_item.configure(
                           text=f"{i + 1}/{t}"))
            self._set_progress(
                idx / total * 100,
                f"File {idx + 1} of {total}")

            fname_short = (
                os.path.basename(urlparse(url).path)
                or f"file_{idx + 1}")
            self._log_write(
                f"--- [{idx+1}/{total}]  {fname_short}", "head")
            self._log_write(f"    {url}", "info")
            self._set_file_progress(0, fname_short)

            folder = generate_folder_name()
            self._log_write(f"  folder: {folder}", "info")

            try:
                # trigger workflow
                self._set_file_progress(5, "Triggering workflow...")
                gh_repo.get_workflow(dl_wf).create_dispatch(
                    ref=branch,
                    inputs={"file_url": url,
                            "folder_name": folder})
                self._log_write("  Workflow triggered", "ok")

                # wait for folder
                self._set_file_progress(
                    15, "Waiting for Actions runner...")
                commit_sha = self._wait_for_folder(
                    gh_repo, folder, branch)
                self._log_write(
                    f"  Folder ready  sha={commit_sha[:8]}", "ok")

                # download files
                self._set_file_progress(25, "Downloading...")
                self._download_folder(
                    session, token, owner, repo_name,
                    commit_sha, folder, out_dir, url, idx, total)

                # cleanup
                try:
                    gh_repo.get_workflow(del_wf).create_dispatch(
                        ref=branch,
                        inputs={"folder_name": folder})
                    self._log_write(
                        "  Delete workflow triggered", "warn")
                except Exception:
                    pass

                done += 1
                self.after(0, lambda d=done:
                           self._stat_done.configure(text=str(d)))
                self._log_write(f"  DONE: {fname_short}", "ok")
                self._set_file_progress(100,
                                        f"Done: {fname_short}")

            except Exception as e:
                failed += 1
                self.after(0, lambda f=failed:
                           self._stat_failed.configure(text=str(f)))
                self._log_write(f"  FAILED: {e}", "err")
                self._set_file_progress(
                    0, f"Failed: {fname_short}")

            # ── 10-second cooldown between files ─────────────────────
            if not self._abort.is_set() and idx < total - 1:
                self._log_write(
                    f"  Waiting {INTER_DL_DELAY}s before next "
                    f"download...", "warn")
                self._countdown(INTER_DL_DELAY)

        final_pct = (100 if not self._abort.is_set()
                     else done / total * 100)
        self._set_progress(
            final_pct,
            f"Finished  {done} done, {failed} failed")

        self._finish(
            error=(failed > 0 and done == 0),
            aborted=self._abort.is_set())

    # ─── GitHub helpers ───────────────────────────────────────────────────────
    def _wait_for_folder(self, repo, folder, branch, timeout=3600):
        """Wait until done.txt appears in folder/chunks/ — means all chunks are pushed."""
        deadline = time.time() + timeout
        done_path = f"{folder}/chunks/done.txt"
        while time.time() < deadline:
            if self._abort.is_set():
                raise Exception("Aborted while waiting for folder.")
            try:
                repo.get_contents(done_path, ref=branch)
                # done.txt found — all chunks are committed, get latest sha
                time.sleep(3)
                return repo.get_commits(sha=branch)[0].sha
            except Exception:
                time.sleep(8)
        raise TimeoutError(
            f"done.txt did not appear in '{folder}/chunks/' within "
            f"{timeout // 60} min.")

    def _download_folder(self, session, token, owner, repo_name,
                         commit_sha, folder, out_dir,
                         original_url, file_idx, total_files):
        # Fallback filename from URL (strip query string first)
        url_path       = urlparse(original_url).path
        fname_fallback = os.path.basename(url_path) or "downloaded_file"

        resp = session.get(
            f"https://api.github.com/repos/{owner}/{repo_name}"
            f"/git/trees/{commit_sha}",
            headers={"Authorization": f"token {token}"},
            params={"recursive": "1"})
        resp.raise_for_status()

        prefix  = f"{folder}/"
        entries = [e for e in resp.json()["tree"]
                   if e["path"].startswith(prefix)
                   and e["type"] == "blob"]
        if not entries:
            raise Exception("No files found in folder.")

        # Read filename.txt written by workflow (has the real filename)
        fname = fname_fallback
        fname_entry = next(
            (e for e in entries
             if e["path"].endswith("/chunks/filename.txt")), None)
        if fname_entry:
            raw_fn = (
                "https://raw.githubusercontent.com/"
                f"{owner}/{repo_name}/{commit_sha}/"
                f"{fname_entry['path']}")
            try:
                r = session.get(raw_fn, timeout=10)
                r.raise_for_status()
                name = r.text.strip()
                if name:
                    fname = name
                    self._log_write(f"  Real filename: {fname}", "info")
            except Exception:
                pass

        chunk_entries = [e for e in entries
                         if "/chunks/" in e["path"]
                         and not e["path"].endswith("filename.txt")
                         and e.get("size", 0) > 0]

        if chunk_entries:
            # ── chunked download ──────────────────────────────────────────
            # Sort numerically by the leading digits in the chunk filename
            # Handles: chunk_0001, chunk_0001_video.mp4, chunk_0002 etc.
            def chunk_sort_key(e):
                cname = os.path.basename(e["path"])
                # extract the first run of digits after "chunk_"
                m = re.search(r'chunk_(\d+)', cname)
                return int(m.group(1)) if m else 0

            chunk_entries = sorted(chunk_entries, key=chunk_sort_key)
            n_chunks      = len(chunk_entries)

            # If only one chunk, try to recover original name from its name
            # e.g. chunk_0001_video.mp4  -> video.mp4
            if n_chunks == 1:
                cname_full = os.path.basename(chunk_entries[0]["path"])
                m = re.match(r'chunk_\d+_(.*)', cname_full)
                if m and m.group(1):
                    fname = m.group(1)   # restore real filename

            out_path = os.path.join(out_dir, fname)
            tmp      = tempfile.mkdtemp()
            try:
                chunk_paths = []
                for ci, entry in enumerate(chunk_entries):
                    if self._abort.is_set():
                        raise Exception("Aborted during chunk download.")
                    cname = os.path.basename(entry["path"])
                    cpath = os.path.join(tmp, f"{ci:06d}_{cname}")
                    raw   = (
                        "https://raw.githubusercontent.com/"
                        f"{owner}/{repo_name}/{commit_sha}/"
                        f"{entry['path']}")
                    pct = 25 + int(ci / n_chunks * 70)
                    self._set_file_progress(
                        pct, f"Chunk {ci+1}/{n_chunks}: {cname}")
                    self._log_write(f"  chunk {ci+1}/{n_chunks}: {cname}",
                                    "info")
                    if not self._dl_file(session, raw, cpath):
                        raise Exception(f"Failed chunk {cname}")
                    chunk_paths.append(cpath)

                # Sort by the numeric prefix we added so order is guaranteed
                chunk_paths.sort()

                self._set_file_progress(96, f"Reassembling -> {fname}")
                self._log_write(
                    f"  Reassembling {n_chunks} chunks -> {fname}", "info")

                with open(out_path, "wb") as out_f:
                    for cp in chunk_paths:
                        with open(cp, "rb") as cf:
                            shutil.copyfileobj(cf, out_f, 1024 * 1024)

                size_mb = os.path.getsize(out_path) / 1_048_576
                self._log_write(
                    f"  Saved: {out_path}  ({size_mb:.1f} MB)", "ok")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

        else:
            # ── single-file download ──────────────────────────────────────
            out_path = os.path.join(out_dir, fname)
            for entry in entries:
                if self._abort.is_set():
                    raise Exception("Aborted during download.")
                raw = (
                    "https://raw.githubusercontent.com/"
                    f"{owner}/{repo_name}/{commit_sha}/"
                    f"{entry['path']}")
                en = os.path.basename(entry["path"])
                self._set_file_progress(30, f"Downloading: {en}")
                self._log_write(f"  Downloading: {en}", "info")
                if self._dl_file(session, raw, out_path):
                    size_mb = os.path.getsize(out_path) / 1_048_576
                    self._log_write(
                        f"  Saved: {out_path}  ({size_mb:.1f} MB)", "ok")
                    self._set_file_progress(100, f"Done: {en}")
                else:
                    raise Exception("Download failed after all retries.")
                return

    def _dl_file(self, session, url, path,
                 threshold=MIN_SPEED,
                 max_retries=MAX_RETRIES,
                 delay=RETRY_DELAY):
        os.makedirs(
            os.path.dirname(os.path.abspath(path)),
            exist_ok=True)
        remote_size = 0
        try:
            r = session.head(url, allow_redirects=True,
                             timeout=10)
            remote_size = int(
                r.headers.get("Content-Length", 0))
        except Exception:
            pass

        if (os.path.exists(path)
                and os.path.getsize(path) == remote_size > 0):
            return True

        downloaded   = (os.path.getsize(path)
                        if os.path.exists(path) else 0)
        retries_used = 0

        for attempt in range(max_retries):
            if self._abort.is_set():
                return False
            try:
                headers = {}
                if downloaded > 0:
                    headers["Range"] = f"bytes={downloaded}-"
                resp = session.get(url, headers=headers,
                                   stream=True, timeout=30)
                resp.raise_for_status()
                total = remote_size or int(
                    resp.headers.get("Content-Length", 0))
                if downloaded > 0 and resp.status_code != 206:
                    downloaded = 0
                mode   = "ab" if downloaded > 0 else "wb"
                last_t = time.time()
                last_b = downloaded
                with open(path, mode) as f:
                    for chunk in resp.iter_content(8192):
                        if self._abort.is_set():
                            return False
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            now = time.time()
                            if now - last_t >= 0.8:
                                speed = ((downloaded - last_b)
                                         / (now - last_t))
                                last_b, last_t = downloaded, now
                                spd = f"{speed / 1024:.0f} KB/s"
                                pct = (
                                    int(downloaded / total * 100)
                                    if total else 0)
                                byt = (
                                    f"{fmt_bytes(downloaded)}"
                                    f" / {fmt_bytes(total)}")
                                rt  = retries_used
                                self.after(
                                    0, lambda s=spd:
                                    self._stat_speed.configure(
                                        text=s))
                                self.after(
                                    0, lambda b=byt:
                                    self._lbl_bytes.configure(
                                        text=b))
                                self.after(
                                    0, lambda r=rt:
                                    self._lbl_retries.configure(
                                        text=str(r)))
                                self.after(
                                    0, lambda p=pct:
                                    self._file_bar.configure(
                                        value=p))
                                self.after(
                                    0, lambda p=pct:
                                    self._file_pct.configure(
                                        text=f"{p}%"
                                        if p > 0 else ""))
                                if (speed < threshold
                                        and downloaded < total):
                                    raise Exception(
                                        "Speed below threshold,"
                                        " retrying")
                return True
            except Exception as e:
                retries_used += 1
                self._log_write(
                    f"  Retry {retries_used}: {e}", "warn")
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    downloaded = (
                        os.path.getsize(path)
                        if os.path.exists(path) else 0)
        return False

    def _finish(self, error=False, aborted=False):
        """Always re-enables the download button."""
        self._running = False

        def _do():
            self._dl_btn.configure(state="normal")
            self._abort_btn.configure(state="disabled")
            self._stat_speed.configure(text="--")
            self._lbl_wait.configure(text="--")
            if aborted:
                self._set_badge("aborted")
            elif error:
                self._set_badge("error")
            else:
                self._set_badge("done")
                self._set_progress(100, "All done!")

        self.after(0, _do)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = DownloaderApp()
    app.mainloop()
