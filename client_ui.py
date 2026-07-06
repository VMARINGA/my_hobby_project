# ==================================================================================================
#  Book Cricket Multiplayer Client (Tier3) v3.3 — Winner Display + Big Dashboard + Strike Rotation
#  Watermark: This is Vishnu's code — Vishnu
# ==================================================================================================

import socket
import threading
import json
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Dict, Any, List, Tuple

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

DEFAULT_PORT = 5050

SHOTS = ("DEFEND", "DRIVE", "CUT", "PULL", "SLOG")
LENGTHS = ("YORKER", "GOOD", "SHORT", "FULL")
INTENTS = ("BD", "BN", "BA")
EXTRA_TYPES = ("WD", "NB", "B", "LB")
WICKET_TYPES = ("CAUGHT", "BOWLED", "LBW", "RUNOUT", "STUMPED")


def balls_to_overs_float(balls: int) -> float:
    return (balls // 6) + (balls % 6) / 6.0

def overs_str(balls: int) -> str:
    return f"{balls//6}.{balls%6}"

def send_json(sock: socket.socket, obj: Dict[str, Any]) -> None:
    sock.sendall((json.dumps(obj) + "\n").encode("utf-8"))

def safe_int(x, default=0) -> int:
    try:
        return int(x)
    except Exception:
        return default

def rr_required(target: int, score: int, balls_left: int) -> float:
    if balls_left <= 0:
        return 99.0
    need = target - score
    if need <= 0:
        return 0.0
    return (need / balls_left) * 6.0


class ClientBigGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Book Cricket MP v3.3 — Vishnu (Winner + Strike Rotation + Rich Dashboard)")
        self.geometry("1680x1020")
        self.minsize(1320, 860)

        self.sock: Optional[socket.socket] = None
        self.listener: Optional[threading.Thread] = None

        self.player_id: Optional[int] = None
        self.token: Optional[str] = None
        self.state: Optional[Dict[str, Any]] = None

        self._toast_win: Optional[tk.Toplevel] = None
        self._toast_after_id = None
        self._last_myturn = False
        self._last_event_seen = ""
        self._last_result_seen = ""  # NEW

        self.sel_intent = tk.StringVar(value="BN")
        self.sel_length = tk.StringVar(value="GOOD")

        self._build_ui()
        self._disable_all_controls()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------- UI ----------------

    def _build_ui(self):
        top = ttk.LabelFrame(self, text="Connection")
        top.pack(fill="x", padx=10, pady=10)

        self.host_var = tk.StringVar(value="127.0.0.1")
        self.port_var = tk.IntVar(value=DEFAULT_PORT)
        self.name_var = tk.StringVar(value="Vishnu")

        ttk.Label(top, text="Server IP").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.host_var, width=18).grid(row=0, column=1, padx=6)
        ttk.Label(top, text="Port").grid(row=0, column=2, sticky="w")
        ttk.Entry(top, textvariable=self.port_var, width=8).grid(row=0, column=3, padx=6)
        ttk.Label(top, text="Your name").grid(row=0, column=4, sticky="w")
        ttk.Entry(top, textvariable=self.name_var, width=18).grid(row=0, column=5, padx=6)

        ttk.Button(top, text="Connect", command=self.connect).grid(row=0, column=6, padx=8)
        ttk.Button(top, text="Disconnect", command=self.disconnect).grid(row=0, column=7, padx=6)

        # Auto IP helpers (LAN friendly)
        self.my_ips_var = tk.StringVar(value=self._format_local_ips())
        ttk.Label(top, textvariable=self.my_ips_var, foreground="#444")            .grid(row=1, column=0, columnspan=5, sticky="w", pady=(6, 0))
        ttk.Button(top, text="Use Local (127.0.0.1)", command=lambda: self.host_var.set("127.0.0.1"))            .grid(row=1, column=5, padx=6, pady=(6, 0), sticky="e")
        self.btn_auto_find = ttk.Button(top, text="Auto-Find Host (LAN)", command=self.auto_find_host)
        self.btn_auto_find.grid(row=1, column=6, padx=6, pady=(6, 0), sticky="e")
        ttk.Button(top, text="Copy My IP", command=self.copy_my_ip).grid(row=1, column=7, padx=6, pady=(6, 0))

        setup = ttk.LabelFrame(self, text="Lobby + Match Setup (Tier3)")
        setup.pack(fill="x", padx=10, pady=(0, 10))

        self.overs_var = tk.IntVar(value=1)
        self.wkts_var = tk.IntVar(value=2)
        self.pitch_var = tk.StringVar(value="FLAT")
        self.dew_var = tk.StringVar(value="LOW")

        # Auto-derived config from overs (matches server rules)
        self.overs_var.trace_add('write', lambda *_: self._apply_derived_match_config())
        self._apply_derived_match_config()

        ttk.Label(setup, text="Overs").grid(row=0, column=0, padx=(8, 0), sticky="w")
        self.overs_spin = ttk.Spinbox(setup, from_=1, to=20, textvariable=self.overs_var, width=6, command=self._on_overs_changed)
        self.overs_spin.grid(row=0, column=1, padx=6)
        ttk.Label(setup, text="Wickets").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(setup, from_=1, to=10, textvariable=self.wkts_var, width=6, state='disabled').grid(row=0, column=3, padx=6)
        self.bowlers_info = ttk.Label(setup, text="Bowlers: 1")
        self.bowlers_info.grid(row=0, column=4, padx=(12,0), sticky='w')

        ttk.Label(setup, text="Pitch").grid(row=0, column=5, padx=(14, 0), sticky="w")
        self.pitch_combo = ttk.Combobox(setup, textvariable=self.pitch_var,
                     values=["GREEN", "FLAT", "DUSTY", "TWO_PACED"], width=12, state="readonly")
        self.pitch_combo.grid(row=0, column=6, padx=6)

        ttk.Label(setup, text="Dew").grid(row=0, column=7, padx=(14, 0), sticky="w")
        self.dew_combo = ttk.Combobox(setup, textvariable=self.dew_var, values=["OFF", "LOW", "HIGH"],
                     width=8, state="readonly")
        self.dew_combo.grid(row=0, column=8, padx=6)

        self.ready_var = tk.BooleanVar(value=False)
        self.btn_ready = ttk.Checkbutton(setup, text="I am READY", variable=self.ready_var, command=self.set_ready)
        self.btn_ready.grid(row=0, column=9, padx=(14, 6))

        self.btn_start = ttk.Button(setup, text="Start Match (needs READY)", command=self.start_match)
        self.btn_start.grid(row=0, column=10, padx=6)

        self.btn_new_game = ttk.Button(setup, text="New Game (Rematch)", command=self.new_game)
        self.btn_new_game.grid(row=0, column=11, padx=6)

        main = ttk.Frame(self)
        main.pack(fill="both", expand=True, padx=10, pady=10)

        left = ttk.Frame(main)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        right = ttk.Frame(main)
        right.pack(side="left", fill="both", expand=True)

        self.header = ttk.Label(left, text="Not connected.", font=("Segoe UI", 12, "bold"))
        self.header.pack(anchor="w", pady=(0, 6))

        # NEW: Winner banner
        self.winner_banner = ttk.Label(left, text="", font=("Segoe UI", 13, "bold"))
        self.winner_banner.pack(fill="x", pady=(0, 6))

        self.turn_banner = ttk.Label(left, text="TURN: -", font=("Segoe UI", 14, "bold"), anchor="center")
        self.turn_banner.pack(fill="x", pady=(0, 6))

        row = ttk.Frame(left)
        row.pack(fill="x", pady=(0, 8))
        self.toast_var = tk.BooleanVar(value=True)
        self.sound_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="Toast on my turn", variable=self.toast_var).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(row, text="Sound on my turn", variable=self.sound_var).pack(side="left")

        hint = ttk.LabelFrame(left, text="Cricket Hint (realistic)")
        hint.pack(fill="x", pady=(0, 10))
        self.hint_label = ttk.Label(hint, text="Connect + start match to see hints.",
                                    wraplength=760, justify="left")
        self.hint_label.pack(fill="x", padx=10, pady=10)

        logbox = ttk.LabelFrame(left, text="Event Log (latest)")
        logbox.pack(fill="both", expand=True)
        self.log_text = tk.Text(logbox, height=12, wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.log_text.configure(state="disabled")

        statebox = ttk.LabelFrame(left, text="State")
        statebox.pack(fill="both", expand=True, pady=(10, 0))
        self.state_text = tk.Text(statebox, height=16, wrap="word")
        self.state_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.state_text.configure(state="disabled")

        actions = ttk.LabelFrame(right, text="Actions (Turn-locked)")
        actions.pack(fill="x", pady=(0, 10))

        toss = ttk.Frame(actions)
        toss.pack(fill="x", padx=8, pady=8)
        ttk.Label(toss, text="TOSS: Server flips. Only the designated caller can call Heads/Tails. Winner chooses BAT/BOWL.",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 6))
        btnrow = ttk.Frame(toss)
        btnrow.pack(fill="x")
        self.btn_call_h = ttk.Button(btnrow, text="Call HEADS", command=lambda: self.toss_call("H"))
        self.btn_call_t = ttk.Button(btnrow, text="Call TAILS", command=lambda: self.toss_call("T"))
        self.btn_choose_bat = ttk.Button(btnrow, text="BAT", command=lambda: self.toss_choice("BAT"))
        self.btn_choose_bowl = ttk.Button(btnrow, text="BOWL", command=lambda: self.toss_choice("BOWL"))
        self.btn_call_h.pack(side="left", padx=6)
        self.btn_call_t.pack(side="left", padx=6)
        self.btn_choose_bat.pack(side="left", padx=16)
        self.btn_choose_bowl.pack(side="left", padx=6)

        sel = ttk.LabelFrame(actions, text="Start of Over: Bowling side selects bowler")
        sel.pack(fill="x", padx=10, pady=(10, 0))

        self.bowler_btn_frame = ttk.Frame(sel)
        self.bowler_btn_frame.pack(fill="x")
        # buttons rendered dynamically by overs -> num bowlers rule
        self._render_bowler_buttons(1)

        bat = ttk.LabelFrame(actions, text="Batter: Choose shot")
        bat.pack(fill="x", padx=8, pady=(0, 8))
        self.btn_shots = {}
        for sh in SHOTS:
            self.btn_shots[sh] = ttk.Button(bat, text=sh, command=lambda s=sh: self.bat_shot(s))
            self.btn_shots[sh].pack(side="left", padx=4, pady=6)

        bowl = ttk.LabelFrame(actions, text="Bowler: Choose intent + length (then Bowl)")
        bowl.pack(fill="x", padx=8, pady=(0, 8))

        intent_row = ttk.Frame(bowl)
        intent_row.pack(fill="x", pady=(6, 2))
        ttk.Label(intent_row, text="Intent:").pack(side="left", padx=(0, 8))
        for it in INTENTS:
            ttk.Radiobutton(intent_row, text=it, value=it, variable=self.sel_intent).pack(side="left", padx=6)

        len_row = ttk.Frame(bowl)
        len_row.pack(fill="x", pady=(2, 6))
        ttk.Label(len_row, text="Length:").pack(side="left", padx=(0, 8))
        for ln in LENGTHS:
            ttk.Radiobutton(len_row, text=ln, value=ln, variable=self.sel_length).pack(side="left", padx=6)

        self.btn_bowl_send = ttk.Button(bowl, text="BOWL (send)", command=self.bowl_send)
        self.btn_bowl_send.pack(side="left", padx=6, pady=6)

        dash = ttk.LabelFrame(right, text="Dashboard (Rich)")
        dash.pack(fill="both", expand=True)

        self.tabs = ttk.Notebook(dash)
        self.tabs.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_rr = ttk.Frame(self.tabs)
        self.tab_worm = ttk.Frame(self.tabs)
        self.tab_wk = ttk.Frame(self.tabs)
        self.tab_manh = ttk.Frame(self.tabs)
        self.tab_extras = ttk.Frame(self.tabs)
        self.tab_wtypes = ttk.Frame(self.tabs)
        self.tab_shots = ttk.Frame(self.tabs)
        self.tab_lengths = ttk.Frame(self.tabs)
        self.tab_heat = ttk.Frame(self.tabs)
        self.tab_card = ttk.Frame(self.tabs)

        self.tabs.add(self.tab_rr, text="Run Rate")
        self.tabs.add(self.tab_worm, text="Worm")
        self.tabs.add(self.tab_wk, text="Wickets")
        self.tabs.add(self.tab_manh, text="Manhattan")
        self.tabs.add(self.tab_extras, text="Extras")
        self.tabs.add(self.tab_wtypes, text="Wicket Types")
        self.tabs.add(self.tab_shots, text="Shots")
        self.tabs.add(self.tab_lengths, text="Lengths")
        self.tabs.add(self.tab_heat, text="Shot×Length")
        self.tabs.add(self.tab_card, text="Scorecard")

        self.fig_rr = Figure(figsize=(6.4, 4.0), dpi=100); self.ax_rr = self.fig_rr.add_subplot(111)
        self.can_rr = FigureCanvasTkAgg(self.fig_rr, master=self.tab_rr); self.can_rr.get_tk_widget().pack(fill="both", expand=True)

        self.fig_worm = Figure(figsize=(6.4, 4.0), dpi=100); self.ax_worm = self.fig_worm.add_subplot(111)
        self.can_worm = FigureCanvasTkAgg(self.fig_worm, master=self.tab_worm); self.can_worm.get_tk_widget().pack(fill="both", expand=True)

        self.fig_wk = Figure(figsize=(6.4, 4.0), dpi=100); self.ax_wk = self.fig_wk.add_subplot(111)
        self.can_wk = FigureCanvasTkAgg(self.fig_wk, master=self.tab_wk); self.can_wk.get_tk_widget().pack(fill="both", expand=True)

        self.fig_manh = Figure(figsize=(6.4, 4.0), dpi=100); self.ax_manh = self.fig_manh.add_subplot(111)
        self.can_manh = FigureCanvasTkAgg(self.fig_manh, master=self.tab_manh); self.can_manh.get_tk_widget().pack(fill="both", expand=True)

        self.fig_extras = Figure(figsize=(6.4, 4.0), dpi=100); self.ax_extras = self.fig_extras.add_subplot(111)
        self.can_extras = FigureCanvasTkAgg(self.fig_extras, master=self.tab_extras); self.can_extras.get_tk_widget().pack(fill="both", expand=True)

        self.fig_wtypes = Figure(figsize=(6.4, 4.0), dpi=100); self.ax_wtypes = self.fig_wtypes.add_subplot(111)
        self.can_wtypes = FigureCanvasTkAgg(self.fig_wtypes, master=self.tab_wtypes); self.can_wtypes.get_tk_widget().pack(fill="both", expand=True)

        self.fig_shots = Figure(figsize=(6.4, 4.0), dpi=100); self.ax_shots = self.fig_shots.add_subplot(111)
        self.can_shots = FigureCanvasTkAgg(self.fig_shots, master=self.tab_shots); self.can_shots.get_tk_widget().pack(fill="both", expand=True)

        self.fig_lengths = Figure(figsize=(6.4, 4.0), dpi=100); self.ax_lengths = self.fig_lengths.add_subplot(111)
        self.can_lengths = FigureCanvasTkAgg(self.fig_lengths, master=self.tab_lengths); self.can_lengths.get_tk_widget().pack(fill="both", expand=True)

        self.fig_heat = Figure(figsize=(6.4, 4.0), dpi=100); self.ax_heat = self.fig_heat.add_subplot(111)
        self.can_heat = FigureCanvasTkAgg(self.fig_heat, master=self.tab_heat); self.can_heat.get_tk_widget().pack(fill="both", expand=True)

        self._build_scorecard(self.tab_card)

    def _build_scorecard(self, parent):
        top = ttk.Frame(parent); top.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(top, text="Ball-by-ball (latest 250)").pack(side="left")

        self.tree = ttk.Treeview(
            parent,
            columns=("inn","over","batter","bowler","shot","intent","len","kind","bat","extra","etype","tot","w","wtype","fh","score","wkts","target"),
            show="headings", height=18
        )
        cols = [
            ("inn","Inn",50), ("over","Over",70), ("batter","Batter",150), ("bowler","Bowler",150),
            ("shot","Shot",80), ("intent","Intent",70), ("len","Len",80),
            ("kind","Kind",55), ("bat","BatRuns",70), ("extra","Extra",60), ("etype","ExType",65), ("tot","Total",60),
            ("w","W",40), ("wtype","WicketType",90), ("fh","FreeHit",60),
            ("score","Score",70), ("wkts","Wkts",55), ("target","Target",70),
        ]
        for k, txt, w in cols:
            self.tree.heading(k, text=txt)
            self.tree.column(k, width=w, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)

    # ---------------- Toast / sound ----------------

    # ---------------- match config (client-side helper) ----------------

    @staticmethod
    def _derive_cfg_from_overs(overs: int):
        o = max(1, min(20, int(overs)))
        if o <= 1:
            return o, 2, 1
        if o <= 4:
            return o, 4, 2
        return o, 10, 5

    def _apply_derived_match_config(self):
        """Update wickets + bowler buttons based on overs selection."""
        try:
            overs = int(self.overs_var.get())
        except Exception:
            overs = 1
        o, wkts, nb = self._derive_cfg_from_overs(overs)
        if o != overs:
            self.overs_var.set(o)
        # Wickets auto-set (spinbox disabled)
        if int(self.wkts_var.get()) != wkts:
            self.wkts_var.set(wkts)
        if hasattr(self, 'bowlers_info'):
            self.bowlers_info.config(text=f"Bowlers: {nb}")
        self._render_bowler_buttons(nb)

    def _on_overs_changed(self):
        """Spinbox callback (PyInstaller needs an actual bound method)."""
        self._apply_derived_match_config()
        # If connected and still in lobby, you can optionally sync config later
        # (server is authoritative once match config is locked).

    def _render_bowler_buttons(self, num_bowlers: int):
        if not hasattr(self, 'bowler_btn_frame'):
            return
        for w in self.bowler_btn_frame.winfo_children():
            w.destroy()
        self.bowler_buttons = []
        for i in range(1, num_bowlers + 1):
            tag = f"B{i}"
            b = ttk.Button(self.bowler_btn_frame, text=f"Select Bowler {tag}",
                           command=lambda t=tag: self.select_bowler(t))
            b.pack(side='left', padx=6, pady=6)
            self.bowler_buttons.append(b)


    def _beep(self):
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            try:
                self.bell()
            except Exception:
                pass


    def _local_ipv4_candidates(self):
        """Best-effort list of local IPv4 addresses (excluding loopback)."""
        ips = []
        try:
            import socket
            hostname = socket.gethostname()
            for fam, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
                if fam == socket.AF_INET:
                    ip = sockaddr[0]
                    if ip.startswith("127."):
                        continue
                    ips.append(ip)
        except Exception:
            pass
        # de-dup preserve order
        seen=set()
        out=[]
        for ip in ips:
            if ip not in seen:
                seen.add(ip); out.append(ip)
        return out

    def _format_local_ips(self) -> str:
        ips = self._local_ipv4_candidates()
        if not ips:
            return "Your LAN IP: (not detected)"
        # show first 2 for compact UI
        shown = ", ".join(ips[:2])
        more = "" if len(ips) <= 2 else f" (+{len(ips)-2} more)"
        return f"Your LAN IP: {shown}{more}  |  Port: {int(self.port_var.get())}"

    def copy_my_ip(self):
        ips = self._local_ipv4_candidates()
        if not ips:
            self._show_toast("No LAN IP detected.", ms=2200)
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(ips[0])
            self._show_toast(f"Copied IP: {ips[0]}", ms=2200)
        except Exception:
            self._show_toast(f"IP: {ips[0]}", ms=2200)

    def auto_find_host(self):
        """Scan local /24 for a host listening on the port. Stops on first hit."""
        if getattr(self, "_scan_running", False):
            return
        self._scan_running = True
        try:
            self.btn_auto_find.state(["disabled"])
        except Exception:
            self.btn_auto_find.configure(state="disabled")
        self._show_toast("Scanning LAN for host on port 5050...", ms=1800)
        import threading
        t = threading.Thread(target=self._scan_for_host, daemon=True)
        t.start()

    def _scan_for_host(self):
        import socket
        port = int(self.port_var.get())
        ips = self._local_ipv4_candidates()
        # try to infer /24 from first private-ish IP
        base = None
        for ip in ips:
            parts = ip.split(".")
            if len(parts) == 4:
                base = ".".join(parts[:3])
                break
        found = None
        if base:
            for i in range(1, 255):
                cand = f"{base}.{i}"
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(0.18)
                    s.connect((cand, port))
                    s.close()
                    found = cand
                    break
                except Exception:
                    try:
                        s.close()
                    except Exception:
                        pass
        def done():
            self._scan_running = False
            try:
                self.btn_auto_find.state(["!disabled"])
            except Exception:
                self.btn_auto_find.configure(state="normal")
            if found:
                self.host_var.set(found)
                self._show_toast(f"Host found: {found}", ms=2600)
            else:
                self._show_toast("No host found on this LAN.", ms=2600)
            self.my_ips_var.set(self._format_local_ips())
        self.after(0, done)

    def _show_toast(self, text: str, ms: int = 2200):
        if not self.toast_var.get():
            return
        try:
            if self._toast_after_id is not None:
                self.after_cancel(self._toast_after_id)
                self._toast_after_id = None
        except Exception:
            pass
        try:
            if self._toast_win is not None and self._toast_win.winfo_exists():
                self._toast_win.destroy()
        except Exception:
            pass

        toast = tk.Toplevel(self)
        self._toast_win = toast
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)

        frame = ttk.Frame(toast, padding=10)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=text, font=("Segoe UI", 11, "bold"), justify="left").pack()

        self.update_idletasks()
        x = self.winfo_rootx() + self.winfo_width() - 360
        y = self.winfo_rooty() + 40
        toast.geometry(f"340x90+{x}+{y}")

        def close_toast():
            try:
                if toast.winfo_exists():
                    toast.destroy()
            except Exception:
                pass

        self._toast_after_id = self.after(ms, close_toast)

    # ---------------- Networking ----------------

    def connect(self):
        if self.sock:
            messagebox.showinfo("Connect", "Already connected.")
            return
        host = self.host_var.get().strip()
        port = int(self.port_var.get())

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((host, port))
        except Exception as e:
            self.sock = None
            messagebox.showerror("Connect failed", str(e))
            return

        self.listener = threading.Thread(target=self.listen_loop, daemon=True)
        self.listener.start()

        name = (self.name_var.get().strip() or "Player")[:24]
        self._send({"type": "SETUP", "name": name})

    def disconnect(self):
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.sock = None
        self.state = None
        self.player_id = None
        self.ready_var.set(False)
        self._disable_all_controls()
        self.header.config(text="Disconnected.")
        self.winner_banner.config(text="")
        self.turn_banner.config(text="TURN: -")
        self._render_text(self.state_text, "Disconnected.")
        self._render_text(self.log_text, "")
        for item in self.tree.get_children():
            self.tree.delete(item)

    def on_close(self):
        self.disconnect()
        self.destroy()

    def listen_loop(self):
        buf = ""
        try:
            while True:
                data = self.sock.recv(4096)
                if not data:
                    break
                buf += data.decode("utf-8", errors="ignore")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    msg = json.loads(line)
                    self.handle_msg(msg)
        except Exception:
            pass
        self.after(0, self.disconnect)

    def handle_msg(self, msg: Dict[str, Any]):
        t = msg.get("type")
        if t == "WELCOME":
            self.player_id = msg.get("player_id")
            self.token = msg.get("token")
        elif t == "STATE":
            self.state = msg.get("state")
            self.after(0, self.render_all)
        elif t == "ERROR":
            m = msg.get("message", "Error")
            self.after(0, lambda: self._show_toast(f"⚠️ {m}", ms=2600))

    def _send(self, obj: Dict[str, Any]):
        if not self.sock:
            return
        try:
            send_json(self.sock, obj)
        except Exception:
            pass

    # ---------------- Actions ----------------

    def set_ready(self):
        self._send({"type": "READY", "ready": bool(self.ready_var.get())})

    def start_match(self):
        self._send({
            "type": "START",
            "overs": int(self.overs_var.get()),
            "wickets": int(self.wkts_var.get()),
            "pitch": self.pitch_var.get(),
            "dew": self.dew_var.get()
        })

    def new_game(self):
        self._send({"type": "NEW_GAME"})

    def toss_call(self, call: str):
        self._send({"type": "TOSS_CALL", "call": call})

    def toss_choice(self, choice: str):
        self._send({"type": "TOSS_CHOICE", "choice": choice})

    def select_bowler(self, tag: str):
        self._send({"type": "SELECT_BOWLER", "bowler_tag": tag})

    def bat_shot(self, shot: str):
        self._send({"type": "ACTION_BAT", "shot": shot})

    def bowl_send(self):
        self._send({"type": "ACTION_BOWL", "intent": self.sel_intent.get(), "length": self.sel_length.get()})

    # ---------------- rendering helpers ----------------

    def _render_text(self, widget: tk.Text, txt: str):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", txt)
        widget.configure(state="disabled")

    def _append_log(self, line: str, max_lines: int = 160):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        content = self.log_text.get("1.0", "end").splitlines()
        if len(content) > max_lines:
            keep = content[-max_lines:]
            self.log_text.delete("1.0", "end")
            self.log_text.insert("1.0", "\n".join(keep) + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _disable_all_controls(self):
        widgets = [
            self.btn_ready, self.btn_start, self.btn_new_game,
            self.btn_call_h, self.btn_call_t, self.btn_choose_bat, self.btn_choose_bowl,
            self.btn_bowl_send,
        ]
        widgets += list(self.btn_shots.values())
        widgets += getattr(self, 'bowler_buttons', [])
        for w in widgets:
            try:
                w.state(["disabled"])
            except Exception:
                try:
                    w.configure(state="disabled")
                except Exception:
                    pass

    def _enable(self, btn: ttk.Widget, ok: bool):
        try:
            btn.state(["!disabled"] if ok else ["disabled"])
        except Exception:
            try:
                btn.configure(state=("normal" if ok else "disabled"))
            except Exception:
                pass

    # ---------------- Dashboard (same as before, kept) ----------------

    def _current_innings_history(self, s: Dict[str, Any]) -> List[Dict[str, Any]]:
        hist = s.get("history", []) or []
        inn = safe_int(s.get("innings", 1), 1)
        cur = [h for h in hist if safe_int(h.get("innings", 0), 0) == inn]
        return cur if cur else hist

    def _legal_ball_progress(self, cur: List[Dict[str, Any]]) -> Tuple[List[int], List[int], List[int]]:
        x, score, wk = [], [], []
        for h in cur:
            if h.get("kind") == "LEGAL":
                x.append(safe_int(h.get("ball_no", 0), 0))
                score.append(safe_int(h.get("score_now", 0), 0))
                wk.append(safe_int(h.get("wkts_now", 0), 0))
        return x, score, wk

    def _runs_per_over(self, cur: List[Dict[str, Any]]) -> Tuple[List[int], List[int], List[int]]:
        over_runs = {}
        over_wk = {}
        for h in cur:
            bno = safe_int(h.get("ball_no", 0), 0)
            if bno <= 0:
                continue
            over_idx = (bno - 1) // 6 + 1
            over_runs.setdefault(over_idx, 0)
            over_wk.setdefault(over_idx, 0)
            over_runs[over_idx] += safe_int(h.get("runs_total", 0), 0)
            if h.get("wicket"):
                over_wk[over_idx] += 1
        if not over_runs:
            return [], [], []
        overs = sorted(over_runs.keys())
        return overs, [over_runs[o] for o in overs], [over_wk[o] for o in overs]

    def _breakdowns(self, cur: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
        extras = {k: 0 for k in EXTRA_TYPES}
        wtypes = {k: 0 for k in WICKET_TYPES}
        shots = {k: 0 for k in SHOTS}
        lengths = {k: 0 for k in LENGTHS}
        heat = {sh: {ln: 0 for ln in LENGTHS} for sh in SHOTS}

        for h in cur:
            et = (h.get("extra_type") or "").strip()
            if et in extras:
                extras[et] += safe_int(h.get("runs_extra", 0), 0)

            if h.get("wicket"):
                wt = (h.get("wicket_type") or "").strip()
                if wt in wtypes:
                    wtypes[wt] += 1

            sh = (h.get("shot") or "").strip()
            ln = (h.get("length") or "").strip()
            if sh in shots:
                shots[sh] += 1
            if ln in lengths:
                lengths[ln] += 1
            if sh in SHOTS and ln in LENGTHS:
                heat[sh][ln] += 1

        return {"extras": extras, "wtypes": wtypes, "shots": shots, "lengths": lengths, "heat": heat}

    def _update_dashboard(self):
        s = self.state
        if not s:
            return

        cur = self._current_innings_history(s)
        if not cur:
            return

        innings = safe_int(s.get("innings", 1), 1)
        target = s.get("target", None)
        balls_total = safe_int(s.get("balls_total", 0), 0)

        bx, score_series, wk_series = self._legal_ball_progress(cur)

        self.ax_rr.clear()
        self.ax_rr.set_title("Run Rate (Actual vs Required)")
        self.ax_rr.set_xlabel("Legal Ball #")
        self.ax_rr.set_ylabel("Runs per over")
        if bx:
            rr_series = []
            req_x, req_y = [], []
            for bno, sc in zip(bx, score_series):
                rr_series.append(sc / max(1e-9, balls_to_overs_float(bno)))
                if target is not None and innings == 2:
                    balls_left = balls_total - bno
                    req_x.append(bno)
                    req_y.append(rr_required(int(target), sc, balls_left))
            self.ax_rr.plot(bx, rr_series, label="Actual RR")
            if req_x:
                self.ax_rr.plot(req_x, req_y, label="Required RR")
            self.ax_rr.legend(loc="best")
        self.can_rr.draw()

        self.ax_worm.clear()
        self.ax_worm.set_title("Cumulative Score (Worm)")
        self.ax_worm.set_xlabel("Legal Ball #")
        self.ax_worm.set_ylabel("Runs")
        if bx:
            self.ax_worm.plot(bx, score_series, label="Score")
            if target is not None and innings == 2:
                self.ax_worm.axhline(y=int(target), linestyle="--", label=f"Target {target}")
            self.ax_worm.legend(loc="best")
        self.can_worm.draw()

        self.ax_wk.clear()
        self.ax_wk.set_title("Wickets Fallen (Cumulative)")
        self.ax_wk.set_xlabel("Legal Ball #")
        self.ax_wk.set_ylabel("Wickets")
        if bx:
            self.ax_wk.plot(bx, wk_series, label="Wickets")
            self.ax_wk.legend(loc="best")
        self.can_wk.draw()

        self.ax_manh.clear()
        self.ax_manh.set_title("Manhattan (Runs per Over) + Wickets")
        self.ax_manh.set_xlabel("Over #")
        self.ax_manh.set_ylabel("Runs")
        overs, over_runs, over_wk = self._runs_per_over(cur)
        if overs:
            self.ax_manh.bar(overs, over_runs, label="Runs/over")
            xs, ys = [], []
            for o, r, w in zip(overs, over_runs, over_wk):
                if w > 0:
                    xs.append(o); ys.append(r + 0.5)
            if xs:
                self.ax_manh.plot(xs, ys, marker="o", linestyle="None", label="Wicket in over")
            self.ax_manh.legend(loc="best")
        self.can_manh.draw()

        bd = self._breakdowns(cur)
        extras = bd["extras"]; wtypes = bd["wtypes"]; shots = bd["shots"]; lengths = bd["lengths"]; heat = bd["heat"]

        self.ax_extras.clear()
        self.ax_extras.set_title("Extras Breakdown (runs)")
        self.ax_extras.set_xlabel("Extra type")
        self.ax_extras.set_ylabel("Runs")
        ex_keys = list(EXTRA_TYPES)
        ex_vals = [extras[k] for k in ex_keys]
        xs = list(range(len(ex_keys)))
        self.ax_extras.bar(xs, ex_vals)
        self.ax_extras.set_xticks(xs); self.ax_extras.set_xticklabels(ex_keys)
        self.can_extras.draw()

        self.ax_wtypes.clear()
        self.ax_wtypes.set_title("Wicket Types (count)")
        self.ax_wtypes.set_xlabel("Type")
        self.ax_wtypes.set_ylabel("Count")
        wk_keys = list(WICKET_TYPES)
        wk_vals = [wtypes[k] for k in wk_keys]
        xs2 = list(range(len(wk_keys)))
        self.ax_wtypes.bar(xs2, wk_vals)
        self.ax_wtypes.set_xticks(xs2); self.ax_wtypes.set_xticklabels(wk_keys, rotation=20, ha="right")
        self.can_wtypes.draw()

        self.ax_shots.clear()
        self.ax_shots.set_title("Shot Usage (count)")
        self.ax_shots.set_xlabel("Shot")
        self.ax_shots.set_ylabel("Count")
        sh_keys = list(SHOTS)
        sh_vals = [shots[k] for k in sh_keys]
        xs3 = list(range(len(sh_keys)))
        self.ax_shots.bar(xs3, sh_vals)
        self.ax_shots.set_xticks(xs3); self.ax_shots.set_xticklabels(sh_keys, rotation=20, ha="right")
        self.can_shots.draw()

        self.ax_lengths.clear()
        self.ax_lengths.set_title("Length Usage (count)")
        self.ax_lengths.set_xlabel("Length")
        self.ax_lengths.set_ylabel("Count")
        ln_keys = list(LENGTHS)
        ln_vals = [lengths[k] for k in ln_keys]
        xs4 = list(range(len(ln_keys)))
        self.ax_lengths.bar(xs4, ln_vals)
        self.ax_lengths.set_xticks(xs4); self.ax_lengths.set_xticklabels(ln_keys, rotation=20, ha="right")
        self.can_lengths.draw()

        self.ax_heat.clear()
        self.ax_heat.set_title("Shot × Length Heatmap (count)")
        self.ax_heat.set_xlabel("Length")
        self.ax_heat.set_ylabel("Shot")
        mat = [[heat[sh][ln] for ln in LENGTHS] for sh in SHOTS]
        im = self.ax_heat.imshow(mat, aspect="auto")
        self.ax_heat.set_xticks(list(range(len(LENGTHS))))
        self.ax_heat.set_xticklabels(LENGTHS, rotation=20, ha="right")
        self.ax_heat.set_yticks(list(range(len(SHOTS))))
        self.ax_heat.set_yticklabels(SHOTS)
        for i in range(len(SHOTS)):
            for j in range(len(LENGTHS)):
                self.ax_heat.text(j, i, str(mat[i][j]), ha="center", va="center")
        try:
            self.fig_heat.colorbar(im, ax=self.ax_heat, fraction=0.046, pad=0.04)
        except Exception:
            pass
        self.can_heat.draw()

        hist = s.get("history", []) or []
        for item in self.tree.get_children():
            self.tree.delete(item)
        for h in hist[-250:]:
            self.tree.insert("", "end", values=(
                h.get("innings",""),
                h.get("over",""),
                h.get("batter",""),
                h.get("bowler",""),
                h.get("shot",""),
                h.get("bowl_intent",""),
                h.get("length",""),
                h.get("kind",""),
                h.get("runs_bat",""),
                h.get("runs_extra",""),
                h.get("extra_type",""),
                h.get("runs_total",""),
                ("W" if h.get("wicket") else ""),
                h.get("wicket_type",""),
                ("YES" if h.get("free_hit_after") else "NO"),
                h.get("score_now",""),
                h.get("wkts_now",""),
                h.get("target",""),
            ))

    # ---------------- Main render ----------------

    def render_all(self):
        s = self.state
        if not s or self.player_id is None:
            self._disable_all_controls()
            return

        pid = int(self.player_id)
        phase = s.get("phase")
        allowed = s.get("allowed_bowlers") or ["B1"]
        nb = len(allowed)
        if getattr(self, "_cur_nb", None) != nb:
            self._cur_nb = nb
            self._render_bowler_buttons(nb)
        innings = safe_int(s.get("innings", 1), 1)
        bat_idx = safe_int(s.get("batting_idx", 0), 0)
        bowl_idx = safe_int(s.get("bowling_idx", 1), 1)
        turn = s.get("turn")

        self.header.config(text=f"Player {pid+1} | Phase={phase} | Innings={innings} | Pitch={s.get('pitch')} | Dew={s.get('dew')}")
        # Tier3++: show phase + partnership + striker skill
        try:
            phase_tag = s.get('phase_tag') or phase
            part = s.get('partnership') or {}
            bats = s.get('batters') or {}
            striker_no = safe_int(bats.get('striker_no', 1), 1)
            skill_map = (s.get('batter_skill') or {}).get(bat_idx, {}) if isinstance(s.get('batter_skill'), dict) else {}
            striker_skill = safe_int(skill_map.get(striker_no, 60), 60)
            pr = safe_int(part.get('runs', 0), 0)
            pb = safe_int(part.get('balls', 0), 0)
            self.hint_label.config(text=f"Phase: {phase_tag} | Partnership: {pr} runs ({overs_str(pb)} ov) | Striker BAT{striker_no} skill {striker_skill}")
        except Exception:
            pass


        # Match config lock after toss: prevent changing overs/pitch/dew once toss starts
        config_editable = phase in ("LOBBY", "FINISHED")
        try:
            self.overs_spin.configure(state=("normal" if config_editable else "disabled"))
            self.pitch_combo.configure(state=("readonly" if config_editable else "disabled"))
            self.dew_combo.configure(state=("readonly" if config_editable else "disabled"))
        except Exception:
            pass
        # wickets are derived from overs (server-enforced) -> keep disabled always
        try:
            self.wkts_spin.configure(state="disabled")
        except Exception:
            pass
        # refresh IP display
        try:
            self.my_ips_var.set(self._format_local_ips())
        except Exception:
            pass


        # ✅ Winner banner (NEW)
        res = s.get("result")
        if phase == "FINISHED" and isinstance(res, dict):
            msg = res.get("message", "Match finished.")
            summ = res.get("summary", "")
            banner = f"🏆 {msg}   |   {summ}"
            self.winner_banner.config(text=banner)

            # Toast winner once
            if banner != self._last_result_seen:
                self._last_result_seen = banner
                self._show_toast(f"🏆 {msg}", ms=3000)
        else:
            self.winner_banner.config(text="")

        # turn banner + notifications
        my_turn = False
        note = ""
        if phase == "PLAYING":
            if turn == "SELECT_BOWLER":
                if pid == bowl_idx:
                    my_turn = True
                    sug = ((s.get("suggested_bowler_tag") or {}).get(bowl_idx))
                    note = f"🎯 Select bowler ({', '.join(allowed)})" + (f" | Suggested: {sug}" if sug else "")
                self.turn_banner.config(text=f"TURN: SELECT_BOWLER | {s['players'][bowl_idx]}")
            elif turn == "BAT":
                if pid == bat_idx:
                    my_turn = True
                    note = "✅ Your turn to BAT"
                self.turn_banner.config(text=f"TURN: BAT | {s['players'][bat_idx]}")
            elif turn == "BOWL":
                if pid == bowl_idx:
                    my_turn = True
                    note = "🎯 Your turn to BOWL"
                self.turn_banner.config(text=f"TURN: BOWL | {s['players'][bowl_idx]}")
        else:
            if phase == "TOSS":
                self.turn_banner.config(text="TURN: TOSS")
            elif phase == "CHOOSE_BATBOWL":
                self.turn_banner.config(text="TURN: CHOOSE BAT/BOWL")
            elif phase == "FINISHED":
                self.turn_banner.config(text="TURN: FINISHED ✅")
            else:
                self.turn_banner.config(text="TURN: -")

        if my_turn and not self._last_myturn:
            if self.sound_var.get():
                self._beep()
            self._show_toast(note, ms=2200)
        self._last_myturn = my_turn

        # state panel (with striker)
        target = s.get("target")
        toss_call = s.get("toss_call")
        toss_res = s.get("toss_result")
        toss_win = s.get("toss_winner")

        toss_line = "Toss: -"
        if toss_call:
            call_txt = "Heads" if toss_call == "H" else "Tails"
            res_txt = "Heads" if toss_res == "H" else "Tails" if toss_res else "-"
            win_txt = s["players"][toss_win] if toss_win is not None else "-"
            caller_idx = safe_int(s.get('toss_caller', 1), 1)
            toss_line = f"Toss: {s['players'][caller_idx]} called {call_txt} | Server flip={res_txt} | Winner={win_txt}"

        free_hit = bool((s.get("free_hit") or {}).get(bat_idx, False))

        striker_no = safe_int((s.get("current_batter_no") or {}).get(bat_idx, 1), 1)
        non_striker_no = safe_int((s.get("non_striker_no") or {}).get(bat_idx, 2), 2)

        faced_map = (s.get("batter_balls_faced") or {}).get(bat_idx, {}) or {}
        runs_map = (s.get("batter_runs") or {}).get(bat_idx, {}) or {}
        striker_faced = safe_int(faced_map.get(striker_no, 0), 0)
        non_faced = safe_int(faced_map.get(non_striker_no, 0), 0)
        striker_runs = safe_int(runs_map.get(striker_no, 0), 0)
        non_runs = safe_int(runs_map.get(non_striker_no, 0), 0)

        bowler_tag = (s.get("current_bowler_tag") or {}).get(bowl_idx, "B1")
        bowler_name = f"{s['players'][bowl_idx]}-{bowler_tag}"

        lines = [
            "Players:",
            f"  1) {s['players'][0]} | READY={s['ready'][0]} | Connected={s['connected'][0]}",
            f"  2) {s['players'][1]} | READY={s['ready'][1]} | Connected={s['connected'][1]}",
            "",
            f"{s['players'][0]}: {s['scores'][0]}/{s['wkts'][0]} in {s['overs_str'][0]}",
            f"{s['players'][1]}: {s['scores'][1]}/{s['wkts'][1]} in {s['overs_str'][1]}",
            "",
            f"Target: {target if target is not None else '-'}",
            toss_line,
            "",
            f"STRIKER: {s['players'][bat_idx]}-BAT{striker_no}  {striker_runs}({striker_faced})  | FREE HIT={'YES' if free_hit else 'NO'}",
            f"NON-STRIKER: {s['players'][bat_idx]}-BAT{non_striker_no}  {non_runs}({non_faced})",
            f"Current bowler: {bowler_name}  |  Fatigue: {int(100*float(((s.get('bowler_fatigue') or {}).get(bowl_idx, {}) or {}).get(bowler_tag, 0.0)))}%",
            f"Last: {s.get('last_event','')}",
        ]
        self._render_text(self.state_text, "\n".join(lines))

        last_event = s.get("last_event", "")
        if last_event and last_event != self._last_event_seen:
            self._append_log(last_event)
            self._last_event_seen = last_event

        if phase != "PLAYING":
            self.hint_label.config(text="Hints appear during PLAYING.")
        else:
            if target is None or innings == 1:
                self.hint_label.config(text="Strike rotation is ON ✅ Odd totals swap striker; end of over swaps. Mix DEFEND/DRIVE vs GOOD. Boundaries: PULL/SLOG vs SHORT/FULL.")
            else:
                balls_total = safe_int(s.get("balls_total", 0), 0)
                balls_bowled = safe_int(s.get("balls", [0, 0])[bat_idx], 0)
                balls_left = balls_total - balls_bowled
                score_now = safe_int(s.get("scores", [0, 0])[bat_idx], 0)
                need = safe_int(target, 0) - score_now if target else 0
                req = rr_required(int(target), score_now, balls_left) if target else 0.0
                self.hint_label.config(text=f"Chase: need {need} off {balls_left} balls | Req RR={req:.1f}. Use singles to manage striker for big overs.")

        # Enable/disable controls
        self._disable_all_controls()

        if phase in ("LOBBY",):
            self._enable(self.btn_ready, True)
            self._enable(self.btn_start, True)

        if phase == "FINISHED":
            self._enable(self.btn_new_game, True)

        if phase == "TOSS":
            self._enable(self.btn_call_h, pid == safe_int(s.get('toss_caller', 1), 1))
            self._enable(self.btn_call_t, pid == safe_int(s.get('toss_caller', 1), 1))

        if phase == "CHOOSE_BATBOWL":
            tw = s.get("toss_winner")
            if tw is not None:
                self._enable(self.btn_choose_bat, pid == int(tw))
                self._enable(self.btn_choose_bowl, pid == int(tw))

        if phase == "PLAYING":
            if turn == "SELECT_BOWLER" and pid == bowl_idx:
                for b in getattr(self, 'bowler_buttons', []):
                    self._enable(b, True)
            if turn == "BAT" and pid == bat_idx:
                for sh in SHOTS:
                    self._enable(self.btn_shots[sh], True)
            if turn == "BOWL" and pid == bowl_idx:
                self._enable(self.btn_bowl_send, True)

        self._update_dashboard()


if __name__ == "__main__":
    app = ClientBigGUI()
    app.mainloop()