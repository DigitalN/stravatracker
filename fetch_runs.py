#!/usr/bin/env python3
"""
Fetches the last 30 days of runs from Strava and writes a clean summary
to running_data.txt (human-readable) and running_data.json (structured).
"""

import os
import sys
import json
from datetime import datetime, timezone, timedelta
import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("STRAVA_REFRESH_TOKEN")

if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
    print("ERROR: STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, and STRAVA_REFRESH_TOKEN must be set in .env")
    print("Run authorize.py first to get your refresh token.")
    sys.exit(1)


def get_access_token():
    resp = requests.post("https://www.strava.com/oauth/token", data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
        "grant_type": "refresh_token",
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_activities(access_token, after_timestamp):
    activities = []
    page = 1
    while True:
        resp = requests.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"after": after_timestamp, "per_page": 100, "page": page},
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        activities.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return activities


def meters_to_miles(meters):
    return meters / 1609.344


def seconds_to_hms(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s"


def pace_per_mile(distance_meters, time_seconds):
    if distance_meters == 0:
        return "N/A"
    miles = meters_to_miles(distance_meters)
    seconds_per_mile = time_seconds / miles
    m = int(seconds_per_mile // 60)
    s = int(seconds_per_mile % 60)
    return f"{m}:{s:02d}/mi"


def meters_to_feet(meters):
    return meters * 3.28084


def parse_activity(a):
    date = datetime.fromisoformat(a["start_date_local"].replace("Z", "+00:00"))
    distance_m = a.get("distance", 0)
    moving_time_s = a.get("moving_time", 0)
    elevation_m = a.get("total_elevation_gain", 0)

    return {
        "name": a.get("name", "Untitled"),
        "date": date.strftime("%Y-%m-%d"),
        "day_of_week": date.strftime("%A"),
        "distance_miles": round(meters_to_miles(distance_m), 2),
        "moving_time": seconds_to_hms(moving_time_s),
        "moving_time_seconds": moving_time_s,
        "avg_pace": pace_per_mile(distance_m, moving_time_s),
        "elevation_gain_ft": round(meters_to_feet(elevation_m)),
        "avg_heart_rate": a.get("average_heartrate"),
        "max_heart_rate": a.get("max_heartrate"),
        "type": a.get("type", "Run"),
        "sport_type": a.get("sport_type", "Run"),
    }


def format_run_text(run, index):
    lines = [
        f"Run {index}: {run['name']}",
        f"  Date:          {run['day_of_week']}, {run['date']}",
        f"  Distance:      {run['distance_miles']} miles",
        f"  Moving Time:   {run['moving_time']}",
        f"  Avg Pace:      {run['avg_pace']}",
        f"  Elevation:     {run['elevation_gain_ft']} ft",
    ]
    if run["avg_heart_rate"]:
        lines.append(f"  Avg HR:        {int(run['avg_heart_rate'])} bpm")
    if run["max_heart_rate"]:
        lines.append(f"  Max HR:        {int(run['max_heart_rate'])} bpm")
    return "\n".join(lines)


def compute_summary(runs):
    if not runs:
        return {}
    total_miles = sum(r["distance_miles"] for r in runs)
    total_seconds = sum(r["moving_time_seconds"] for r in runs)
    total_elevation = sum(r["elevation_gain_ft"] for r in runs)
    hr_runs = [r for r in runs if r["avg_heart_rate"]]
    avg_hr = round(sum(r["avg_heart_rate"] for r in hr_runs) / len(hr_runs)) if hr_runs else None
    longest = max(runs, key=lambda r: r["distance_miles"])
    return {
        "total_runs": len(runs),
        "total_miles": round(total_miles, 1),
        "total_time": seconds_to_hms(total_seconds),
        "total_elevation_ft": round(total_elevation),
        "avg_miles_per_run": round(total_miles / len(runs), 2),
        "avg_pace_overall": pace_per_mile(total_miles * 1609.344, total_seconds),
        "avg_heart_rate": avg_hr,
        "longest_run_miles": longest["distance_miles"],
        "longest_run_date": longest["date"],
    }


def main():
    print("Fetching access token...")
    access_token = get_access_token()

    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    after_ts = int(thirty_days_ago.timestamp())

    print(f"Fetching activities since {thirty_days_ago.strftime('%Y-%m-%d')}...")
    activities = fetch_activities(access_token, after_ts)

    run_types = {"Run", "TrailRun", "VirtualRun"}
    runs_raw = [a for a in activities if a.get("type") == "Run" or a.get("sport_type") in run_types]

    if not runs_raw:
        print("No runs found in the last 30 days.")
        sys.exit(0)

    runs = [parse_activity(a) for a in runs_raw]
    runs.sort(key=lambda r: r["date"])
    summary = compute_summary(runs)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── Plain text output ──────────────────────────────────────────────────
    txt_lines = [
        "=" * 60,
        "STRAVA RUNNING DATA — LAST 30 DAYS",
        f"Generated: {now_str}",
        "=" * 60,
        "",
        "SUMMARY",
        "-" * 40,
        f"Total runs:        {summary['total_runs']}",
        f"Total distance:    {summary['total_miles']} miles",
        f"Total time:        {summary['total_time']}",
        f"Total elevation:   {summary['total_elevation_ft']} ft",
        f"Avg distance/run:  {summary['avg_miles_per_run']} miles",
        f"Avg pace:          {summary['avg_pace_overall']}",
    ]
    if summary.get("avg_heart_rate"):
        txt_lines.append(f"Avg heart rate:    {summary['avg_heart_rate']} bpm")
    txt_lines += [
        f"Longest run:       {summary['longest_run_miles']} miles ({summary['longest_run_date']})",
        "",
        "INDIVIDUAL RUNS",
        "-" * 40,
        "",
    ]

    for i, run in enumerate(runs, 1):
        txt_lines.append(format_run_text(run, i))
        txt_lines.append("")

    txt_output = "\n".join(txt_lines)

    with open("running_data.txt", "w") as f:
        f.write(txt_output)

    # ── JSON output ────────────────────────────────────────────────────────
    json_output = {
        "generated_at": now_str,
        "period": "last_30_days",
        "summary": summary,
        "runs": runs,
    }
    with open("running_data.json", "w") as f:
        json.dump(json_output, f, indent=2)

    print(txt_output)
    print(f"\nSaved to running_data.txt and running_data.json")
    print(f"\nTo use as coaching context: paste the contents of running_data.txt into Claude.")


if __name__ == "__main__":
    main()
