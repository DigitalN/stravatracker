#!/usr/bin/env python3
"""
Step 1: Run this script once to authorize your Strava app and get a refresh token.
It will open your browser, you log in and approve, then paste the redirect URL back here.
The refresh token is saved to .env so fetch_runs.py can use it automatically.
"""

import os
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")

if not CLIENT_ID or not CLIENT_SECRET:
    print("ERROR: STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET must be set in .env")
    sys.exit(1)

REDIRECT_URI = "http://localhost:8765/callback"
SCOPE = "activity:read_all"

auth_code = None


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

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
        pass  # suppress request logs


def exchange_code_for_tokens(code):
    resp = requests.post("https://www.strava.com/oauth/token", data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
    })
    resp.raise_for_status()
    return resp.json()


def save_refresh_token(refresh_token):
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    lines = []
    found = False

    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            if line.startswith("STRAVA_REFRESH_TOKEN="):
                lines[i] = f"STRAVA_REFRESH_TOKEN={refresh_token}\n"
                found = True
                break

    if not found:
        lines.append(f"STRAVA_REFRESH_TOKEN={refresh_token}\n")

    with open(env_path, "w") as f:
        f.writelines(lines)


def main():
    auth_url = (
        "https://www.strava.com/oauth/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&response_type=code"
        f"&scope={SCOPE}"
    )

    print("Starting local callback server on port 8765...")
    server = HTTPServer(("localhost", 8765), CallbackHandler)
    server_thread = threading.Thread(target=server.handle_request)
    server_thread.daemon = True
    server_thread.start()

    print(f"\nOpening Strava authorization page in your browser...")
    print(f"If it doesn't open automatically, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    print("Waiting for authorization (approve access in your browser)...")
    server_thread.join(timeout=120)

    if not auth_code:
        print("ERROR: Timed out waiting for authorization. Try again.")
        sys.exit(1)

    print("Authorization code received. Exchanging for tokens...")
    tokens = exchange_code_for_tokens(auth_code)

    refresh_token = tokens.get("refresh_token")
    athlete = tokens.get("athlete", {})
    name = f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip()

    save_refresh_token(refresh_token)

    print(f"\nSuccess! Authorized as: {name or 'Unknown athlete'}")
    print(f"Refresh token saved to .env")
    print(f"\nYou can now run: python fetch_runs.py")


if __name__ == "__main__":
    main()
