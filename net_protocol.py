# ==================================================================================================
#  Book Cricket Multiplayer — JSON Line Protocol Helpers
#  Watermark: This is Vishnu's code — Vishnu
# ==================================================================================================

from __future__ import annotations
import json
import socket
from typing import Dict, Any, Iterable

def send_json(sock: socket.socket, obj: Dict[str, Any]) -> None:
    sock.sendall((json.dumps(obj) + "\n").encode("utf-8"))

def iter_json_lines(sock: socket.socket, bufsize: int = 4096) -> Iterable[Dict[str, Any]]:
    """
    Yields parsed JSON objects delimited by newline. Stops on disconnect.
    """
    buf = ""
    while True:
        data = sock.recv(bufsize)
        if not data:
            return
        buf += data.decode("utf-8", errors="ignore")
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)
