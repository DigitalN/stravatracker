#!/usr/bin/env python3
"""
Fetches the last 30 days of Strava runs and writes running_data.txt and running_data.json.
Handles token refresh automatically. Just run it — no arguments needed.
"""

import bisect
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
import requests

CREDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strava_creds.json")
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


# ── Credentials ────────────────────────────────────────────────────────────────

def load_creds():
    if not os.path.exists(CREDS_FILE):
        print("ERROR: strava_creds.json not found. Run authorize.py first.")
        sys.exit(1)
    with open(CREDS_FILE) as f:
        return json.load(f)


def save_creds(creds):
    with open(CREDS_FILE, "w") as f:
        json.dump(creds, f, indent=2)


def do_token_refresh(creds):
    try:
        resp = requests.post("https://www.strava.com/oauth/token", data={
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "refresh_token": creds["refresh_token"],
            "grant_type": "refresh_token",
        })
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"\nERROR: Token refresh failed ({e}).")
        print("Re-run start.command to re-authorize with Strava.")
        sys.exit(1)

    tokens = resp.json()
    creds["access_token"] = tokens["access_token"]
    creds["refresh_token"] = tokens["refresh_token"]
    creds["token_expires_at"] = tokens["expires_at"]
    save_creds(creds)
    return creds["access_token"], creds


def get_valid_access_token(creds):
    if time.time() < creds.get("token_expires_at", 0) - 300:
        return creds["access_token"], creds
    return do_token_refresh(creds)


# ── Strava API ─────────────────────────────────────────────────────────────────

def fetch_activities(access_token, creds, after_timestamp):
    activities = []
    page = 1
    while True:
        resp = requests.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"after": after_timestamp, "per_page": 100, "page": page},
        )
        if resp.status_code == 401:
            print("Access token rejected by Strava, refreshing...")
            access_token, creds = do_token_refresh(creds)
            resp = requests.get(
                "https://www.strava.com/api/v3/athlete/activities",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"after": after_timestamp, "per_page": 100, "page": page},
            )
            if resp.status_code == 401:
                print("\nERROR: Strava is rejecting the access token even after a refresh.")
                print()
                print("The most common cause: the tokens in strava_creds.json were copied")
                print("from strava.com/settings/api, which only grants PUBLIC scope.")
                print("Reading your activities requires going through the authorization flow.")
                print()
                print("To fix:")
                print("  1. Open strava_creds.json")
                print('  2. Set  "access_token": ""')
                print('         "refresh_token": ""')
                print('         "token_expires_at": 0')
                print("  3. Save the file and run start.command again")
                sys.exit(1)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        activities.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return activities


def fetch_streams(access_token, activity_id):
    """Fetch time, heartrate, altitude, and distance streams for one activity."""
    resp = requests.get(
        f"https://www.strava.com/api/v3/activities/{activity_id}/streams",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"keys": "time,heartrate,altitude,distance", "key_by_type": "true"},
    )
    if resp.status_code in (404, 429):
        return None
    resp.raise_for_status()
    return resp.json()


# ── Formatting helpers ─────────────────────────────────────────────────────────

def meters_to_miles(m):
    return m / 1609.344

def meters_to_feet(m):
    return m * 3.28084

def seconds_to_hms(s):
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}h {m:02d}m {sec:02d}s" if h else f"{m}m {sec:02d}s"

def pace_per_mile(distance_m, time_s):
    if not distance_m:
        return "N/A"
    spm = time_s / meters_to_miles(distance_m)
    return f"{int(spm // 60)}:{int(spm % 60):02d}/mi"

def format_elapsed(total_seconds):
    m, s = divmod(total_seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ── Stream processing ──────────────────────────────────────────────────────────

def nearest_idx(sorted_times, target):
    """Return index of the closest value in a sorted list."""
    i = bisect.bisect_left(sorted_times, target)
    if i == 0:
        return 0
    if i >= len(sorted_times):
        return len(sorted_times) - 1
    # pick whichever neighbor is closer
    if sorted_times[i] - target < target - sorted_times[i - 1]:
        return i
    return i - 1


def process_streams(raw):
    """
    Returns:
      {
        'ten_second_marks': [{'elapsed_s': int, 'heartrate': int, 'elevation_ft': float}, ...],
        'minute_paces':     [{'minute': int, 'pace': str}, ...]
      }
    or None if no usable stream data.
    """
    if not raw or "time" not in raw:
        return None

    times = raw["time"]["data"]
    hrs   = raw.get("heartrate", {}).get("data", [])
    alts  = raw.get("altitude",  {}).get("data", [])
    dists = raw.get("distance",  {}).get("data", [])

    n = len(times)
    if n == 0:
        return None

    max_t = times[-1]

    # Every 10 seconds: HR and elevation at that moment
    ten_sec = []
    t = 0
    while t <= max_t:
        i = nearest_idx(times, t)
        mark = {"elapsed_s": t}
        if hrs:
            mark["heartrate"] = hrs[i]
        if alts:
            mark["elevation_ft"] = round(alts[i] * 3.28084, 1)
        ten_sec.append(mark)
        t += 10

    # Every minute: average pace over that minute window
    min_paces = []
    minute = 1
    while (minute - 1) * 60 < max_t:
        start_t = (minute - 1) * 60
        end_t   = minute * 60
        si = nearest_idx(times, start_t)
        ei = nearest_idx(times, end_t)
        ei = min(ei, n - 1)

        if ei > si and dists:
            dist_m = dists[ei] - dists[si]
            time_s = times[ei] - times[si]
            pace = pace_per_mile(dist_m, time_s) if dist_m > 0 else "N/A"
        else:
            pace = "N/A"

        min_paces.append({"minute": minute, "pace": pace})
        minute += 1

    return {"ten_second_marks": ten_sec, "minute_paces": min_paces}


# ── Activity parsing ───────────────────────────────────────────────────────────

RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}

def parse_activity(a):
    date   = datetime.fromisoformat(a["start_date_local"].replace("Z", "+00:00"))
    dist   = a.get("distance", 0)
    time_s = a.get("moving_time", 0)
    elev   = a.get("total_elevation_gain", 0)
    return {
        "id":               a["id"],
        "name":             a.get("name", "Untitled"),
        "date":             date.strftime("%Y-%m-%d"),
        "day_of_week":      date.strftime("%A"),
        "distance_miles":   round(meters_to_miles(dist), 2),
        "moving_time":      seconds_to_hms(time_s),
        "moving_time_seconds": time_s,
        "avg_pace":         pace_per_mile(dist, time_s),
        "elevation_gain_ft": round(meters_to_feet(elev)),
        "avg_heart_rate":   a.get("average_heartrate"),
        "max_heart_rate":   a.get("max_heartrate"),
        "sport_type":       a.get("sport_type", "Run"),
        "streams":          None,
    }

def compute_summary(runs):
    total_miles = sum(r["distance_miles"] for r in runs)
    total_s     = sum(r["moving_time_seconds"] for r in runs)
    total_elev  = sum(r["elevation_gain_ft"] for r in runs)
    hr_runs     = [r for r in runs if r["avg_heart_rate"]]
    avg_hr      = round(sum(r["avg_heart_rate"] for r in hr_runs) / len(hr_runs)) if hr_runs else None
    longest     = max(runs, key=lambda r: r["distance_miles"])
    return {
        "total_runs":        len(runs),
        "total_miles":       round(total_miles, 1),
        "total_time":        seconds_to_hms(total_s),
        "total_elevation_ft": round(total_elev),
        "avg_miles_per_run": round(total_miles / len(runs), 2),
        "avg_pace_overall":  pace_per_mile(total_miles * 1609.344, total_s),
        "avg_heart_rate":    avg_hr,
        "longest_run_miles": longest["distance_miles"],
        "longest_run_date":  longest["date"],
    }


# ── Text output ────────────────────────────────────────────────────────────────

def build_text(runs, summary, generated_at):
    lines = [
        "=" * 60,
        "STRAVA RUNNING DATA — LAST 30 DAYS",
        f"Generated: {generated_at}",
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
        lines.append(f"Avg heart rate:    {summary['avg_heart_rate']} bpm")
    lines += [
        f"Longest run:       {summary['longest_run_miles']} miles ({summary['longest_run_date']})",
        "",
        "INDIVIDUAL RUNS",
        "-" * 40,
        "",
    ]

    for i, r in enumerate(runs, 1):
        # ── Run header ──
        lines += [
            f"Run {i}: {r['name']}",
            f"  Date:          {r['day_of_week']}, {r['date']}",
            f"  Distance:      {r['distance_miles']} miles",
            f"  Moving Time:   {r['moving_time']}",
            f"  Avg Pace:      {r['avg_pace']}",
            f"  Elevation:     {r['elevation_gain_ft']} ft",
        ]
        if r["avg_heart_rate"]:
            lines.append(f"  Avg HR:        {int(r['avg_heart_rate'])} bpm")
        if r["max_heart_rate"]:
            lines.append(f"  Max HR:        {int(r['max_heart_rate'])} bpm")

        streams = r.get("streams")

        # ── Minute-by-minute pace ──
        if streams and streams.get("minute_paces"):
            lines.append("")
            lines.append("  Pace by Minute:")
            for mp in streams["minute_paces"]:
                lines.append(f"    Min {mp['minute']:3d}:  {mp['pace']}")

        # ── Per-10-second HR and elevation ──
        if streams and streams.get("ten_second_marks"):
            marks    = streams["ten_second_marks"]
            has_hr   = any("heartrate"    in m for m in marks)
            has_elev = any("elevation_ft" in m for m in marks)

            if has_hr or has_elev:
                lines.append("")
                # Build a compact header
                col_heads = ["  Elapsed"]
                if has_hr:
                    col_heads.append("   HR")
                if has_elev:
                    col_heads.append("   Elevation")
                lines.append("  Heart Rate & Elevation (every 10s):")
                lines.append("  " + "  ".join(col_heads).strip())

                for mark in marks:
                    elapsed = format_elapsed(mark["elapsed_s"])
                    row = f"    {elapsed:>7}"
                    if has_hr:
                        hr_val = mark.get("heartrate")
                        row += f"   {hr_val:3d} bpm" if hr_val is not None else "       ---"
                    if has_elev:
                        el_val = mark.get("elevation_ft")
                        row += f"   {el_val:7.1f} ft" if el_val is not None else "          ---"
                    lines.append(row)

        lines.append("")

    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    creds = load_creds()

    if not creds.get("refresh_token"):
        print("ERROR: No refresh token found. Run authorize.py first.")
        sys.exit(1)

    access_token, creds = get_valid_access_token(creds)

    after_ts   = int((datetime.now(timezone.utc) - timedelta(days=30)).timestamp())
    activities = fetch_activities(access_token, creds, after_ts)

    runs_raw = [a for a in activities if a.get("sport_type") in RUN_TYPES or a.get("type") == "Run"]
    if not runs_raw:
        print("No runs found in the last 30 days.")
        print("\nTask completed successfully.")
        sys.exit(0)

    runs = sorted([parse_activity(a) for a in runs_raw], key=lambda r: r["date"])

    # Fetch detailed stream data for each run
    print(f"Fetching stream data for {len(runs)} run(s)...")
    for i, run in enumerate(runs, 1):
        print(f"  [{i}/{len(runs)}] {run['name']}", end="\r")
        raw = fetch_streams(access_token, run["id"])
        run["streams"] = process_streams(raw)
    print()

    summary      = compute_summary(runs)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    txt      = build_text(runs, summary, generated_at)
    txt_path  = os.path.join(OUTPUT_DIR, "running_data.txt")
    json_path = os.path.join(OUTPUT_DIR, "running_data.json")

    with open(txt_path, "w") as f:
        f.write(txt)

    with open(json_path, "w") as f:
        json.dump({"generated_at": generated_at, "period": "last_30_days",
                   "summary": summary, "runs": runs}, f, indent=2)

    print(f"Fetched {len(runs)} runs from the last 30 days.")
    print(f"  Total distance:  {summary['total_miles']} miles")
    print(f"  Avg pace:        {summary['avg_pace_overall']}")
    print(f"  Saved to:        running_data.txt + running_data.json")
    print()
    print("Task completed successfully.")


if __name__ == "__main__":
    main()
