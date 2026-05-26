# Strava Running Coach Data Fetcher

On first run, fetches the past 180 days of runs with full stream data. Every run after that, archives the previous data and fetches only new runs — so your history grows over time without ever re-pulling everything. Each run includes per-run pace by minute and heart rate + elevation every 10 seconds.

## One-time setup

**1. Create your Strava app**

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

It refreshes your token automatically, fetches any runs since your last update, and saves `running_data.txt`. The previous file is archived to `historical_running_data.txt` automatically. Paste either file into a Claude chat for coaching.

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
| `historical_running_data.txt` | All previous fetches, archived automatically |

## Sample coaching prompt

Paste this into a new Claude chat along with your `running_data.txt` file to get started with a coaching session. Fill in the blanks before sending.

---

Dear Coach,

I want you to act as my expert running coach. Your mission is to get me in the best shape possible to achieve my goal.

Before we start building my training plans, I want you to fully understand my background, habits, and context.

**Base info:**
- What is your running goal? Acheiving a distance by a certain date?:
- Age:
- Weight:
- Height:
- Sport history:
- Running experience:
- Past injuries:
- Work & lifestyle:
- Weekly availability for training:
- Terrain preference: trails, roads, or both?
- Equipment:

Before we build the plan, I will upload some historical running data from my Strava account as a txt file.

Can you confirm you understand this data, or do you need me to clarify anything?

Before you build a plan, please ask me any questions that would help you design the best possible training plan for me.

---
