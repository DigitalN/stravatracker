# Strava Running Coach Data Fetcher

Pulls the last 30 days of your Strava runs into a clean summary you can paste into Claude for coaching.

## One-time setup

**1. Install dependencies**
```bash
pip install requests
```

**2. Add your Strava credentials to `strava_creds.json`**
```bash
cp strava_creds.json.example strava_creds.json
```
Open `strava_creds.json` and fill in your `client_id` and `client_secret` from [strava.com/settings/api](https://www.strava.com/settings/api).
Set **Authorization Callback Domain** to `localhost` when creating your app.

**3. Authorize once**
```bash
./authorize.py
```
Opens your browser → approve access → tokens saved automatically to `strava_creds.json`.

## Daily use

Just run:
```bash
./get_recent_data.py
```

That's it. It refreshes your token automatically, fetches the last 30 days of runs, and writes:
- `running_data.txt` — paste this into Claude for coaching
- `running_data.json` — structured data if you need it

## Files

| File | Purpose |
|---|---|
| `strava_creds.json` | Your credentials and tokens (gitignored — never committed) |
| `strava_creds.json.example` | Template to copy from |
| `authorize.py` | One-time OAuth setup |
| `get_recent_data.py` | Run this anytime to refresh your data |
