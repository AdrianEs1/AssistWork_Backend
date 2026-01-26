import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
TOKEN_FILE = "token_agente.pickle"

client_config = {
    "installed": {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [
            "http://localhost",
            "http://localhost:8080"
        ]
    }
}

def generate_token():
    creds = None

    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        if not creds:
            flow = InstalledAppFlow.from_client_config(
                client_config,
                SCOPES
            )
            creds = flow.run_local_server(
                port=0,
                access_type="offline",
                prompt="consent"
            )

        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    print("✅ Token listo:", TOKEN_FILE)


if __name__ == "__main__":
    generate_token()

