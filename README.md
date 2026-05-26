# Strava Running Coach Data Fetcher

Pulls the last 30 days of your Strava runs into a clean summary you can paste into Claude for coaching.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env and fill in your STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET
```

## Usage

**First time only — authorize your app:**
```bash
python authorize.py
```
This opens your browser, you approve access, and your refresh token is saved to `.env`.

**Fetch your runs:**
```bash
python fetch_runs.py
```
Outputs `running_data.txt` (paste into Claude) and `running_data.json` (structured data).

## Getting Strava Credentials

1. Go to https://www.strava.com/settings/api
2. Create an app — set **Authorization Callback Domain** to `localhost`
3. Copy your **Client ID** and **Client Secret** into `.env`
