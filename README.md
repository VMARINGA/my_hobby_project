# Book Cricket MP (Refactored)

## Run server (one laptop)
```bash
python server.py
```

## Run client (both laptops)
```bash
python client_big_gui.py
```

### LAN play
- Server IP = the IPv4 address of the laptop running `server.py` (e.g., 192.168.1.142)
- Port = 5050
- Ensure Windows Firewall allows Python for Private networks

### Toss rules
- Server flips coin
- Only the designated caller (default: Player 2) can call Heads/Tails
- Only toss winner can choose BAT/BOWL
