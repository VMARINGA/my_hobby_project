# ==================================================================================================
#  Book Cricket Multiplayer — Server App (socket plumbing)
#  Watermark: This is Vishnu's code — Vishnu
# ==================================================================================================

from __future__ import annotations
import socket
import threading
import uuid
from typing import Dict, Any, Optional, List, Tuple

from common_schema import DEFAULT_HOST, DEFAULT_PORT, safe_int
from net_protocol import send_json, iter_json_lines
from server_state import BookCricketState

class ServerApp:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.state = BookCricketState()
        self.host = host
        self.port = port
        self.lock = threading.Lock()
        self.clients: List[Optional[socket.socket]] = [None, None]
        self.tokens: Dict[str, int] = {}

    def allocate_slot(self) -> Optional[int]:
        for i in range(2):
            if self.clients[i] is None:
                return i
        return None

    def broadcast_state(self):
        st = self.state.get_state()
        for sock in self.clients:
            if sock:
                try:
                    send_json(sock, {"type": "STATE", "state": st})
                except Exception:
                    pass

    def send_error(self, slot: int, msg: str):
        sock = self.clients[slot]
        if sock:
            try:
                send_json(sock, {"type": "ERROR", "message": msg})
            except Exception:
                pass

    def client_thread(self, sock: socket.socket, addr):
        slot = None
        token = None
        try:
            with self.lock:
                slot = self.allocate_slot()
                if slot is None:
                    send_json(sock, {"type": "ERROR", "message": "Server full (2 players)."})
                    sock.close()
                    return
                self.clients[slot] = sock
                self.state.connected[slot] = True
                token = str(uuid.uuid4())
                self.tokens[token] = slot

            send_json(sock, {"type": "WELCOME", "player_id": slot, "token": token})
            self.state.last_event = f"Client connected: Player {slot+1} from {addr}"
            self.broadcast_state()

            for msg in iter_json_lines(sock):
                with self.lock:
                    self.handle_msg(slot, msg)
        except Exception:
            pass
        finally:
            with self.lock:
                if slot is not None and self.clients[slot] is sock:
                    self.clients[slot] = None
                    self.state.connected[slot] = False
                    self.state.ready[slot] = False
                    self.state.last_event = f"Player {slot+1} disconnected."
                    self.broadcast_state()
            try:
                sock.close()
            except Exception:
                pass

    def handle_msg(self, slot: int, msg: Dict[str, Any]):
        t = msg.get("type")

        if t == "SETUP":
            name = (msg.get("name") or f"Player {slot+1}")[:24]
            self.state.names[slot] = name
            self.state.last_event = f"{name} joined as Player {slot+1}."
            self.broadcast_state()
            return

        if t == "READY":
            self.state.ready[slot] = bool(msg.get("ready"))
            self.state.last_event = f"{self.state.names[slot]} READY={self.state.ready[slot]}"
            self.broadcast_state()
            return

        if t == "START":
            if not (self.state.ready[0] and self.state.ready[1]):
                self.send_error(slot, "Both players must be READY to start.")
                return
            if self.state.phase not in ("LOBBY", "FINISHED"):
                self.send_error(slot, f"Cannot START in phase {self.state.phase}.")
                return
            self.state.start_match(
                overs=safe_int(msg.get("overs"), 2),
                wickets=safe_int(msg.get("wickets"), 2),
                pitch=msg.get("pitch", "FLAT"),
                dew=msg.get("dew", "LOW"),
            )
            self.broadcast_state()
            return

        if t == "NEW_GAME":
            if self.state.phase != "FINISHED":
                self.send_error(slot, "NEW_GAME allowed only after FINISHED.")
                return
            self.state.new_game()
            self.broadcast_state()
            return

        if t == "TOSS_CALL":
            err = self.state.do_toss_call(slot, msg.get("call"))
            if err:
                self.send_error(slot, err)
            self.broadcast_state()
            return

        if t == "TOSS_CHOICE":
            err = self.state.do_toss_choice(slot, msg.get("choice"))
            if err:
                self.send_error(slot, err)
            self.broadcast_state()
            return

        if t == "SELECT_BOWLER":
            err = self.state.select_bowler(slot, msg.get("bowler_tag"))
            if err:
                self.send_error(slot, err)
            self.broadcast_state()
            return

        if t == "ACTION_BAT":
            err = self.state.action_bat(slot, msg.get("shot"))
            if err:
                self.send_error(slot, err)
            self.broadcast_state()
            return

        if t == "ACTION_BOWL":
            err = self.state.action_bowl(slot, msg.get("intent"), msg.get("length"))
            if err:
                self.send_error(slot, err)
            self.broadcast_state()
            return

        self.send_error(slot, f"Unknown message type: {t}")

    def serve_forever(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(5)
        print(f"[Server] Listening on {self.host}:{self.port}")

        try:
            while True:
                sock, addr = srv.accept()
                th = threading.Thread(target=self.client_thread, args=(sock, addr), daemon=True)
                th.start()
        finally:
            try:
                srv.close()
            except Exception:
                pass
