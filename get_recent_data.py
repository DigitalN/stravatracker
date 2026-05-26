#!/usr/bin/env python3
"""
Fetches Strava runs and writes running_data.txt.
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

TIMEOUT_TOKEN  = 10          # seconds — OAuth POSTs
TIMEOUT_API    = 30          # seconds — activity list and stream GETs
RETRY_STATUSES = {500, 502, 503}
RETRY_BACKOFF  = [2, 4]      # wait before attempt 2, then attempt 3
MAX_PAGES      = 50          # 50 × 100 = 5,000 activities
STREAM_DELAY        = 0.5    # seconds between consecutive stream fetches
STREAM_HISTORY_DAYS = 180    # fetch streams for runs within this window


# ── Credentials ────────────────────────────────────────────────────────────────

def load_creds():
    if not os.path.exists(CREDS_FILE):
        print("ERROR: strava_creds.json not found. Run authorize.py first.")
        sys.exit(1)
    try:
        with open(CREDS_FILE) as f:
            return json.load(f)
    except ValueError:
        print("ERROR: strava_creds.json is corrupted. Fix or delete it and re-run authorize.py.")
        sys.exit(1)


def save_creds(creds):
    with open(CREDS_FILE, "w") as f:
        json.dump(creds, f, indent=2)
    os.chmod(CREDS_FILE, 0o600)


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _make_session(access_token=None):
    s = requests.Session()
    if access_token:
        s.headers["Authorization"] = f"Bearer {access_token}"
    return s


def _api_request(session, method, url, **kwargs):
    """Single entry point for all HTTP calls: retries on transient errors, waits on rate limits."""
    for attempt in range(3):
        try:
            resp = session.request(method, url, **kwargs)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            if attempt == 2:
                raise
            wait = RETRY_BACKOFF[attempt]
            print(f"Network error ({exc.__class__.__name__}), retrying in {wait}s...")
            time.sleep(wait)
            continue

        if resp.status_code == 429:
            usage = resp.headers.get("X-RateLimit-Usage", "unknown")
            print(f"Rate limit hit (usage: {usage}). Waiting 15 minutes before retrying...")
            time.sleep(900)
            continue

        if resp.status_code in RETRY_STATUSES:
            if attempt == 2:
                resp.raise_for_status()
            wait = RETRY_BACKOFF[attempt]
            print(f"Server error {resp.status_code}, retrying in {wait}s...")
            time.sleep(wait)
            continue

        return resp

    raise RuntimeError(f"Request to {url} failed after 3 attempts.")


# ── Token management ───────────────────────────────────────────────────────────

def do_token_refresh(session, creds):
    resp = _api_request(session, "POST", "https://www.strava.com/oauth/token",
                        data={
                            "client_id":     creds["client_id"],
                            "client_secret": creds["client_secret"],
                            "refresh_token": creds["refresh_token"],
                            "grant_type":    "refresh_token",
                        },
                        timeout=TIMEOUT_TOKEN)
    try:
        resp.raise_for_status()
        tokens = resp.json()
    except requests.exceptions.HTTPError as e:
        print(f"\nERROR: Token refresh failed ({e}).")
        print("Re-run start.command to re-authorize with Strava.")
        sys.exit(1)
    except ValueError:
        print("ERROR: Strava returned an unexpected response during token refresh. Try again.")
        sys.exit(1)

    try:
        creds["access_token"]     = tokens["access_token"]
        creds["refresh_token"]    = tokens["refresh_token"]
        creds["token_expires_at"] = tokens["expires_at"]
    except KeyError as e:
        print(f"ERROR: Token response missing expected field {e}. Try again.")
        sys.exit(1)

    save_creds(creds)
    return creds["access_token"], creds


def get_valid_access_token(session, creds):
    if time.time() < creds.get("token_expires_at", 0) - 300:
        return creds["access_token"], creds
    return do_token_refresh(session, creds)


# ── Strava API ─────────────────────────────────────────────────────────────────

def fetch_activities(session, creds, after_timestamp):
    activities = []
    url = "https://www.strava.com/api/v3/athlete/activities"

    for page in range(1, MAX_PAGES + 1):
        resp = _api_request(session, "GET", url,
                            params={"after": after_timestamp, "per_page": 100, "page": page},
                            timeout=TIMEOUT_API)

        if resp.status_code == 401:
            print("Access token rejected by Strava, refreshing...")
            new_token, creds = do_token_refresh(session, creds)
            session.headers["Authorization"] = f"Bearer {new_token}"
            resp = _api_request(session, "GET", url,
                                params={"after": after_timestamp, "per_page": 100, "page": page},
                                timeout=TIMEOUT_API)
            if resp.status_code == 401:
                print("\nERROR: Strava is rejecting the access token even after a refresh.")
                print()
                print("The most common cause: tokens in strava_creds.json were copied from")
                print("strava.com/settings/api, which only grants public scope.")
                print()
                print("To fix:")
                print("  1. Open strava_creds.json")
                print('  2. Set  "access_token": ""')
                print('         "refresh_token": ""')
                print('         "token_expires_at": 0')
                print("  3. Save and run start.command again")
                sys.exit(1)

        resp.raise_for_status()

        try:
            batch = resp.json()
        except ValueError:
            print(f"Warning: unexpected response on page {page}, stopping pagination.")
            break

        if not isinstance(batch, list) or not batch:
            break

        activities.extend(batch)
        if len(batch) < 100:
            break
    else:
        print(f"Warning: reached {MAX_PAGES}-page limit — some older activities may be missing.")

    return activities, creds


def fetch_streams(session, activity_id):
    """Fetch time, heartrate, altitude, and distance streams for one activity."""
    resp = _api_request(session, "GET",
                        f"https://www.strava.com/api/v3/activities/{activity_id}/streams",
                        params={"keys": "time,heartrate,altitude,distance", "key_by_type": "true"},
                        timeout=TIMEOUT_API)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        print(f"  Warning: could not parse stream data for activity {activity_id}.")
        return None


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
    i = bisect.bisect_left(sorted_times, target)
    if i == 0:
        return 0
    if i >= len(sorted_times):
        return len(sorted_times) - 1
    if sorted_times[i] - target < target - sorted_times[i - 1]:
        return i
    return i - 1


def process_streams(raw):
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

    min_paces = []
    minute = 1
    while (minute - 1) * 60 < max_t:
        start_t = (minute - 1) * 60
        end_t   = minute * 60
        si = nearest_idx(times, start_t)
        ei = min(nearest_idx(times, end_t), n - 1)

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
        "id":                  a["id"],
        "name":                a.get("name", "Untitled"),
        "date":                date.strftime("%Y-%m-%d"),
        "day_of_week":         date.strftime("%A"),
        "distance_miles":      round(meters_to_miles(dist), 2),
        "moving_time":         seconds_to_hms(time_s),
        "moving_time_seconds": time_s,
        "avg_pace":            pace_per_mile(dist, time_s),
        "elevation_gain_ft":   round(meters_to_feet(elev)),
        "avg_heart_rate":      a.get("average_heartrate"),
        "max_heart_rate":      a.get("max_heartrate"),
        "sport_type":          a.get("sport_type", "Run"),
        "streams":             None,
    }

def compute_summary(runs):
    total_miles = sum(r["distance_miles"] for r in runs)
    total_s     = sum(r["moving_time_seconds"] for r in runs)
    total_elev  = sum(r["elevation_gain_ft"] for r in runs)
    hr_runs     = [r for r in runs if r["avg_heart_rate"]]
    avg_hr      = round(sum(r["avg_heart_rate"] for r in hr_runs) / len(hr_runs)) if hr_runs else None
    longest     = max(runs, key=lambda r: r["distance_miles"])
    return {
        "total_runs":          len(runs),
        "total_miles":         round(total_miles, 1),
        "total_time":          seconds_to_hms(total_s),
        "total_elevation_ft":  round(total_elev),
        "avg_miles_per_run":   round(total_miles / len(runs), 2),
        "avg_pace_overall":    pace_per_mile(total_miles * 1609.344, total_s),
        "avg_heart_rate":      avg_hr,
        "longest_run_miles":   longest["distance_miles"],
        "longest_run_date":    longest["date"],
    }


# ── Text output ────────────────────────────────────────────────────────────────

def build_text(runs, summary, generated_at, period_label):
    lines = [
        "=" * 60,
        f"STRAVA RUNNING DATA — {period_label}",
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

        if streams and streams.get("minute_paces"):
            lines.append("")
            lines.append("  Pace by Minute:")
            for mp in streams["minute_paces"]:
                lines.append(f"    Min {mp['minute']:3d}:  {mp['pace']}")

        if streams and streams.get("ten_second_marks"):
            marks    = streams["ten_second_marks"]
            has_hr   = any("heartrate"    in m for m in marks)
            has_elev = any("elevation_ft" in m for m in marks)

            if has_hr or has_elev:
                lines.append("")
                lines.append("  Heart Rate & Elevation (every 10s):")
                col_heads = ["  Elapsed"]
                if has_hr:
                    col_heads.append("   HR")
                if has_elev:
                    col_heads.append("   Elevation")
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

    bootstrap = _make_session()
    access_token, creds = get_valid_access_token(bootstrap, creds)
    session = _make_session(access_token)

    txt_path  = os.path.join(OUTPUT_DIR, "running_data.txt")
    hist_path = os.path.join(OUTPUT_DIR, "historical_running_data.txt")

    last_fetch    = creds.get("last_fetch_at", 0)
    hist_missing  = not os.path.exists(hist_path)
    first_run     = last_fetch == 0 or hist_missing

    if first_run:
        after_ts     = 0  # fetch all run summaries ever
        period_label = "ALL TIME"
        if hist_missing and last_fetch != 0:
            print(f"historical_running_data.txt not found — re-fetching all runs (streams for past {STREAM_HISTORY_DAYS} days)...")
        else:
            print(f"First run — fetching all runs ever (streams for past {STREAM_HISTORY_DAYS} days)...")
    else:
        after_ts   = last_fetch
        since_date = datetime.fromtimestamp(last_fetch).strftime("%Y-%m-%d")
        period_label = f"NEW RUNS SINCE {since_date}"
        print(f"Fetching new runs since {since_date}...")

        if os.path.exists(txt_path):
            with open(txt_path) as f:
                old = f.read()
            with open(hist_path, "a") as f:
                f.write(old)
                f.write("\n")
            os.remove(txt_path)
            print("  Previous data archived to historical_running_data.txt")

    activities, creds = fetch_activities(session, creds, after_ts)
    runs_raw = [a for a in activities if a.get("sport_type") in RUN_TYPES or a.get("type") == "Run"]

    creds["last_fetch_at"] = int(datetime.now(timezone.utc).timestamp())
    save_creds(creds)

    if not runs_raw:
        print("No runs found.")
        print("\nTask completed successfully.")
        sys.exit(0)

    runs = sorted([parse_activity(a) for a in runs_raw], key=lambda r: r["date"])

    stream_cutoff     = (datetime.now(timezone.utc) - timedelta(days=STREAM_HISTORY_DAYS)).strftime("%Y-%m-%d")
    runs_with_streams = [r for r in runs if r["date"] >= stream_cutoff]

    if runs_with_streams:
        print(f"Fetching stream data for {len(runs_with_streams)} run(s) from the past {STREAM_HISTORY_DAYS} days...")
        if len(runs_with_streams) > 90:
            print("  (This may take a few minutes — Strava rate limits stream requests.)")
        for i, run in enumerate(runs_with_streams, 1):
            print(f"  [{i}/{len(runs_with_streams)}] {run['name']}", end="\r")
            run["streams"] = process_streams(fetch_streams(session, run["id"]))
            if i < len(runs_with_streams):
                time.sleep(STREAM_DELAY)
        print()

    summary      = compute_summary(runs)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    txt          = build_text(runs, summary, generated_at, period_label)

    output_path = hist_path if first_run else txt_path
    with open(output_path, "w") as f:
        f.write(txt)

    if first_run:
        label = "Rebuilt" if (hist_missing and last_fetch != 0) else "Saved"
        print(f"Fetched {len(runs)} runs ({len(runs_with_streams)} with stream detail).")
        print(f"  Total distance:  {summary['total_miles']} miles")
        print(f"  {label} to:       historical_running_data.txt")
    else:
        print(f"Fetched {len(runs)} new run(s).")
        print(f"  Total distance:  {summary['total_miles']} miles")
        print(f"  Avg pace:        {summary['avg_pace_overall']}")
        print(f"  Saved to:        running_data.txt")
    print()
    print("Task completed successfully.")


if __name__ == "__main__":
    main()
