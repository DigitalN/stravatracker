# Strava Running Coach Data Fetcher

Pulls the last 30 days of your Strava runs into a clean summary to paste into Claude for coaching. Includes per-run pace by minute and heart rate + elevation every 10 seconds.

## One-time setup

**1. Install Python dependencies**
```bash
pip install requests
```

**2. Create your Strava app**

Go to [strava.com/settings/api](https://www.strava.com/settings/api) and create an app. The only field that matters for local use:
- **Authorization Callback Domain**: `localhost`

Copy your **Client ID** and **Client Secret** from that page.

> **Important:** Do not copy the "Access Token" shown on that page — it only has public scope and will not work for reading your activities.

**3. Add your credentials**
```bash
cp strava_creds.json.example strava_creds.json
```
Open `strava_creds.json` and fill in `client_id` and `client_secret`. Leave everything else alone — it's filled in automatically.

**4. Authorize once**

Double-click `start.command`. It will detect that authorization hasn't happened yet, open Strava in your browser, and save your tokens automatically when you approve. You will never need to do this again.

## Daily use

Double-click `start.command`. That's it.

It will refresh your token automatically, fetch your last 30 days of runs, and save `running_data.txt` in the same folder. Open that file and paste it into a Claude chat for coaching.

## What's in the output

For each run:
- Date, distance, moving time, average pace
- Total elevation gain, average and max heart rate
- **Pace by minute** — average pace for each minute of the run
- **Heart rate & elevation every 10 seconds** — full detail stream for the entire run

## Files

| File | Purpose |
|---|---|
| `start.command` | Double-click this to fetch your data |
| `strava_creds.json` | Your credentials and tokens — gitignored, never committed |
| `strava_creds.json.example` | Template — copy this to `strava_creds.json` to get started |
| `authorize.py` | OAuth setup — called automatically by `start.command` when needed |
| `get_recent_data.py` | The main script — called by `start.command` |
| `running_data.txt` | Output — paste this into Claude for coaching |
