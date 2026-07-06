# ==================================================================================================
#  Book Cricket Multiplayer — Host Launcher (GUI) : starts server (no console) + opens client window
#  Watermark: This is Vishnu's code — Vishnu
# ==================================================================================================

import threading
import tkinter as tk
from tkinter import ttk

from common_schema import DEFAULT_HOST, DEFAULT_PORT
from server_app import ServerApp
from client_ui import ClientBigGUI


class HostLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Book Cricket — Host (Server + Client)")
        self.geometry("520x220")
        self.resizable(False, False)

        self._server_thread = None
        self._server_app = None

        frm = ttk.Frame(self, padding=14)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Host mode", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(frm, text=f"Server will listen on {DEFAULT_HOST}:{DEFAULT_PORT} (no console).").pack(anchor="w", pady=(6,0))
        ttk.Label(frm, text="Tip: Use the client 'Copy My IP' button to share your LAN IP with your friend.").pack(anchor="w", pady=(6,0))

        self.status = ttk.Label(frm, text="Ready to start.", foreground="#333")
        self.status.pack(anchor="w", pady=(12, 0))

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(14,0))
        self.btn_start = ttk.Button(btns, text="Start Server + Open Client", command=self.start_all)
        self.btn_start.pack(side="left", expand=True, fill="x")
        ttk.Button(btns, text="Close", command=self.destroy).pack(side="left", padx=(10,0))

    def start_all(self):
        if self._server_thread:
            return
        self.status.config(text="Starting server...")
        self.btn_start.config(state="disabled")

        def run_server():
            try:
                self._server_app = ServerApp(DEFAULT_HOST, DEFAULT_PORT)
                self._server_app.serve_forever()
            except Exception:
                pass

        self._server_thread = threading.Thread(target=run_server, daemon=True)
        self._server_thread.start()

        # open client window (same process)
        self.after(350, self._open_client)

    def _open_client(self):
        self.status.config(text="Server running. Opening client window...")
        # Hide launcher window and open the real client
        self.withdraw()
        app = ClientBigGUI()
        app.host_var.set("127.0.0.1")
        app.port_var.set(DEFAULT_PORT)
        app.mainloop()
        self.destroy()


if __name__ == "__main__":
    HostLauncher().mainloop()
