#!/bin/bash
# Double-click this file to fetch your latest Strava running data.

# Always run from the folder this file lives in
cd "$(dirname "$0")"

echo ""
echo "========================================"
echo "  Strava Running Data Fetcher"
echo "========================================"
echo ""

# Check Python 3 is available
if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python 3 is not installed."
    echo "Install it from https://www.python.org/downloads/"
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi

# Install dependencies silently if missing
python3 -c "import requests" 2>/dev/null || {
    echo "Installing required packages..."
    pip3 install -q requests
    echo ""
}

# Check credentials file exists and has been filled in
if [ ! -f "strava_creds.json" ]; then
    echo "First-time setup: creating strava_creds.json..."
    cp strava_creds.json.example strava_creds.json
    echo ""
    echo "ACTION NEEDED:"
    echo "  Open strava_creds.json and fill in your client_id and client_secret."
    echo "  Then double-click start.command again."
    echo ""
    open strava_creds.json
    read -p "Press Enter to close..."
    exit 1
fi

if grep -q "YOUR_CLIENT_ID" strava_creds.json; then
    echo "ACTION NEEDED:"
    echo "  strava_creds.json still has placeholder values."
    echo "  Open it and fill in your client_id and client_secret from:"
    echo "  https://www.strava.com/settings/api"
    echo ""
    open strava_creds.json
    read -p "Press Enter to close..."
    exit 1
fi

# Check if the OAuth flow has been completed.
# token_expires_at is 0 in the example file and only gets a real value after
# authorize.py completes — so if it's 0 the user hasn't authorized yet.
# NOTE: the tokens on strava.com/settings/api have public scope only and will
# NOT work here. Authorization must go through authorize.py to get activity:read_all.
EXPIRES=$(python3 -c "import json; d=json.load(open('strava_creds.json')); print(d.get('token_expires_at', 0))" 2>/dev/null)
if [ -z "$EXPIRES" ] || [ "$EXPIRES" = "0" ]; then
    echo "Authorization required — your browser will open Strava."
    echo "Log in and click 'Authorize' to grant activity access."
    echo ""
    echo "NOTE: Do NOT copy tokens from strava.com/settings/api — those"
    echo "tokens only have public access and cannot read your activities."
    echo ""
    python3 authorize.py || { echo ""; read -p "Authorization failed. Press Enter to close..."; exit 1; }
    echo ""
fi

# Fetch the data
python3 get_recent_data.py
EXIT_CODE=$?
echo ""
if [ $EXIT_CODE -ne 0 ]; then
    echo "Something went wrong (see error above)."
fi
read -p "Press Enter to close..."
