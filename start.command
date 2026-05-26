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

# Check if we have a refresh token — if not, run authorization first
REFRESH=$(python3 -c "import json; d=json.load(open('strava_creds.json')); print(d.get('refresh_token',''))" 2>/dev/null)
if [ -z "$REFRESH" ]; then
    echo "First-time authorization — your browser will open."
    echo "Log in to Strava and click 'Authorize'."
    echo ""
    python3 authorize.py
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
