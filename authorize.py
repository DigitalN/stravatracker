#!/usr/bin/env python3
"""
Run this ONCE to authorize your Strava app.
It opens your browser, you approve access, then your tokens are saved to strava_creds.json.
After this, get_recent_data.py handles everything automatically.
"""

import json
import os
import sys
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import requests

CREDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strava_creds.json")
REDIRECT_URI = "http://localhost:8765/callback"
SCOPE = "activity:read_all"

auth_code = None


def load_creds():
    if not os.path.exists(CREDS_FILE):
        example = CREDS_FILE + ".example"
        if os.path.exists(example):
            import shutil
            shutil.copy(example, CREDS_FILE)
            print(f"Created strava_creds.json from example — please fill in your client_id and client_secret.")
            sys.exit(1)
        else:
            print(f"ERROR: {CREDS_FILE} not found. Create it with your client_id and client_secret.")
            sys.exit(1)

    with open(CREDS_FILE) as f:
        return json.load(f)


def save_creds(creds):
    with open(CREDS_FILE, "w") as f:
        json.dump(creds, f, indent=2)


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html><body style="font-family:sans-serif;padding:40px">
                <h2>Authorization successful!</h2>
                <p>You can close this tab and return to the terminal.</p>
                </body></html>
            """)
        else:
            error = params.get("error", ["unknown"])[0]
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(f"<html><body>Authorization failed: {error}</body></html>".encode())

    def log_message(self, format, *args):
        pass


def main():
    creds = load_creds()
    client_id = creds.get("client_id", "")
    client_secret = creds.get("client_secret", "")

    if not client_id or client_id == "YOUR_CLIENT_ID":
        print("ERROR: Fill in client_id in strava_creds.json first.")
        sys.exit(1)
    if not client_secret or client_secret == "YOUR_CLIENT_SECRET":
        print("ERROR: Fill in client_secret in strava_creds.json first.")
        sys.exit(1)

    auth_url = (
        "https://www.strava.com/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&response_type=code"
        f"&scope={SCOPE}"
    )

    print("Starting local callback server on port 8765...")
    server = HTTPServer(("localhost", 8765), CallbackHandler)
    server_thread = threading.Thread(target=server.handle_request)
    server_thread.daemon = True
    server_thread.start()

    print("Opening Strava authorization in your browser...")
    print(f"If it doesn't open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    print("Waiting for you to approve access in the browser...")
    server_thread.join(timeout=120)

    if not auth_code:
        print("ERROR: Timed out. Try again.")
        sys.exit(1)

    resp = requests.post("https://www.strava.com/oauth/token", data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": auth_code,
        "grant_type": "authorization_code",
    })
    resp.raise_for_status()
    tokens = resp.json()

    creds["refresh_token"] = tokens["refresh_token"]
    creds["access_token"] = tokens["access_token"]
    creds["token_expires_at"] = tokens["expires_at"]
    save_creds(creds)

    athlete = tokens.get("athlete", {})
    name = f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip()
    print(f"\nSuccess! Authorized as: {name or 'Unknown athlete'}")
    print("Tokens saved to strava_creds.json")
    print("\nSetup complete. You can now run get_recent_data.py anytime.")


if __name__ == "__main__":
    main()
