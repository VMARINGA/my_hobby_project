# ==================================================================================================
#  Book Cricket Multiplayer — Server Runner (keeps filename stable)
#  Watermark: This is Vishnu's code — Vishnu
# ==================================================================================================

from server_app import ServerApp
from common_schema import DEFAULT_HOST, DEFAULT_PORT

if __name__ == "__main__":
    ServerApp(DEFAULT_HOST, DEFAULT_PORT).serve_forever()
