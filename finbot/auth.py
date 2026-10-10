"""FinBot - auth.py (split de bot.py)."""
import os
import json
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from finbot.config import ROOT


# ═══════════════════════════════════════════════════════
# GOOGLE AUTH (com cache global para economizar memória)
# ═══════════════════════════════════════════════════════
_sheets_service = None
_drive_service = None
_credentials_instance = None


def _get_credentials():
    global _credentials_instance
    if _credentials_instance is not None:
        return _credentials_instance
    """Carrega credenciais Google do token.json ou env vars."""
    token_path = ROOT / "google_token.json"        # raiz do repo, nao finbot/
    if not token_path.exists():
        token_path = Path.home() / "AppData" / "Local" / "hermes" / "google_token.json"
    if token_path.exists():
        with open(token_path) as f:
            d = json.load(f)
        _credentials_instance = Credentials(
            token=d["token"], refresh_token=d["refresh_token"],
            token_uri=d["token_uri"], client_id=d["client_id"],
            client_secret=d["client_secret"], scopes=d["scopes"]
        )
        return _credentials_instance
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    token_uri = os.environ.get("GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token")
    scopes = os.environ.get("GOOGLE_SCOPES", "https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/drive.file").split()
    if refresh_token and client_id and client_secret:
        token = os.environ.get("GOOGLE_TOKEN", "")
        _credentials_instance = Credentials(
            token=token, refresh_token=refresh_token,
            token_uri=token_uri, client_id=client_id,
            client_secret=client_secret, scopes=scopes
        )
        return _credentials_instance
    raise RuntimeError("Credenciais Google não encontradas.")

def get_sheets_service():
    global _sheets_service
    if _sheets_service is None:
        _sheets_service = build("sheets", "v4", credentials=_get_credentials())
    return _sheets_service

def get_drive_service():
    global _drive_service
    if _drive_service is None:
        _drive_service = build("drive", "v3", credentials=_get_credentials())
    return _drive_service
