"""
Umpire Scouting Card — Flask Web App
Serves HTML umpire scouting cards from Moeller pitch-by-pitch data.
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path
import pandas as pd
from flask import Flask, render_template_string, redirect, url_for, jsonify, send_file

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
EXCEL_PATH = os.path.join(os.path.dirname(__file__),
                          "Moeller_2024_2025_2026_Final_Season.xlsx")
SHEET_NAME = "Moeller_2024_2025_Final_Season"

NAVY = "#1a1a2e"

SEASON_YEAR = 2026

def load_data():
    df = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME)
    df["Date"] = pd.to_datetime(df["Date"])
    # Filter to season year
    df = df[df["Date"].dt.year == SEASON_YEAR]
    # Called pitches only
    called = df[df["PitchResult"].isin(["Strike Looking", "Ball"])].copy()
    return df, called


DF_ALL, CALLED = load_data()


# ---------------------------------------------------------------------------
# Zone mapping helpers
# ---------------------------------------------------------------------------
# Location encoding: tens digit = ring (0=Heart,1=Shadow,2=Chase,3=Waste)
# units digit = zone position 1-9 on a 3x3 grid.
# Zone grid positions (row-major):
#   1  2  3        top-left   top-mid   top-right
#   4  5  6   ->   mid-left   center    mid-right
#   7  8  9        bot-left   bot-mid   bot-right

def loc_to_zone(loc):
    """Map Location value to 3x3 zone position (1-9) or None."""
    if pd.isna(loc):
        return None
    loc = int(loc)
    unit = loc % 10
    if 1 <= unit <= 9:
        return unit
    return None


def loc_to_ring(loc):
    if pd.isna(loc):
        return None
    loc = int(loc)
    tens = loc // 10
    ring_map = {0: "Heart", 1: "Shadow", 2: "Chase", 3: "Waste"}
    return ring_map.get(tens)


# ---------------------------------------------------------------------------
# Stat computation
# ---------------------------------------------------------------------------

def called_strk_pct(subset):
    total = len(subset)
    if total == 0:
        return 0.0
    strikes = (subset["PitchResult"] == "Strike Looking").sum()
    return strikes / total * 100


def compute_summary(called):
    total = len(called)
    strk = (called["PitchResult"] == "Strike Looking").sum()
    ball = (called["PitchResult"] == "Ball").sum()
    cs_pct = strk / total * 100 if total else 0

    shadow = called[called["AttackZone"] == "Shadow"]
    chase = called[called["AttackZone"] == "Chase"]
    heart = called[called["AttackZone"] == "Heart"]
    waste = called[called["AttackZone"] == "Waste"]

    shadow_pct = called_strk_pct(shadow)
    chase_pct = called_strk_pct(chase)
    heart_pct = called_strk_pct(heart)
    waste_pct = called_strk_pct(waste)
    ball_pct = ball / total * 100 if total else 0

    # FPS Called% — first pitch of at-bat that is a called pitch
    fps = called[called["Count"] == "0 and 0"]
    fps_pct = called_strk_pct(fps)

    return {
        "called": total,
        "cs_pct": cs_pct,
        "shadow_pct": shadow_pct,
        "chase_pct": chase_pct,
        "heart_pct": heart_pct,
        "waste_pct": waste_pct,
        "ball_pct": ball_pct,
        "fps_pct": fps_pct,
    }


def compute_zone_grids(called):
    """Return three 3x3 grids: strike%, volume, borderline rate."""
    called = called.copy()
    called["zone"] = called["Location"].apply(loc_to_zone)
    called["ring"] = called["Location"].apply(loc_to_ring)

    strike_pct = {}
    volume = {}
    borderline = {}

    for z in range(1, 10):
        zdata = called[called["zone"] == z]
        total = len(zdata)
        volume[z] = total
        strike_pct[z] = called_strk_pct(zdata) if total else None

        # Borderline = Shadow + Chase only
        border = zdata[zdata["ring"].isin(["Shadow", "Chase"])]
        btotal = len(border)
        borderline[z] = called_strk_pct(border) if btotal else None

    return strike_pct, volume, borderline


def compute_attack_table(called, league_called):
    """Attack zone table with league averages."""
    rows = []
    for zone in ["Heart", "Shadow", "Chase", "Waste"]:
        sub = called[called["AttackZone"] == zone]
        n = len(sub)
        cs = called_strk_pct(sub)
        bp = 100 - cs if n else 0

        league_sub = league_called[league_called["AttackZone"] == zone]
        league_cs = called_strk_pct(league_sub)

        rows.append({
            "zone": zone, "n": n, "cs_pct": cs, "ball_pct": bp,
            "league_avg": league_cs,
        })
    return rows


def count_situation(called):
    """Ahead / Behind / Even / Full."""
    def classify(count_str):
        if pd.isna(count_str):
            return None
        parts = count_str.split(" and ")
        if len(parts) != 2:
            return None
        b, s = int(parts[0]), int(parts[1])
        if b == 3 and s == 2:
            return "Full"
        if b > s:
            return "Behind"
        if s > b:
            return "Ahead"
        return "Even"

    called = called.copy()
    called["situation"] = called["Count"].apply(classify)
    rows = []
    for sit in ["Ahead", "Behind", "Even", "Full"]:
        sub = called[called["situation"] == sit]
        n = len(sub)
        cs = called_strk_pct(sub)
        bp = 100 - cs if n else 0
        rows.append({"situation": sit, "n": n, "cs_pct": cs, "ball_pct": bp})
    return rows


def game_by_game(called):
    """Game-by-game breakdown."""
    rows = []
    for (date, _), gdata in called.groupby(["Date", "BatterTeam"]):
        # Figure out opponent — the team that is NOT Moeller pitching to
        teams_batting = gdata["BatterTeam"].unique()
        teams_pitching = gdata["PitcherTeam"].unique()
        all_teams = set(teams_batting) | set(teams_pitching)
        team_str = " vs ".join(sorted(all_teams))

        n = len(gdata)
        cs = called_strk_pct(gdata)

        shadow = gdata[gdata["AttackZone"] == "Shadow"]
        chase = gdata[gdata["AttackZone"] == "Chase"]
        sp = called_strk_pct(shadow) if len(shadow) else 0
        cp = called_strk_pct(chase) if len(chase) else 0
        bp = 100 - cs if n else 0

        rows.append({
            "date": date.strftime("%Y-%m-%d"),
            "teams": team_str,
            "n": n, "cs_pct": cs, "shadow_pct": sp,
            "chase_pct": cp, "ball_pct": bp,
        })
    # Deduplicate — group by date + all teams for that date
    deduped = {}
    for (date,), gdata in called.groupby(["Date"]):
        all_teams = sorted(set(gdata["BatterTeam"].unique()) | set(gdata["PitcherTeam"].unique()))
        team_str = " vs ".join(all_teams)
        n = len(gdata)
        cs = called_strk_pct(gdata)
        shadow = gdata[gdata["AttackZone"] == "Shadow"]
        chase = gdata[gdata["AttackZone"] == "Chase"]
        sp = called_strk_pct(shadow) if len(shadow) else 0
        cp = called_strk_pct(chase) if len(chase) else 0
        bp = 100 - cs if n else 0
        deduped[date] = {
            "date": date.strftime("%Y-%m-%d"),
            "teams": team_str,
            "n": n, "cs_pct": cs, "shadow_pct": sp,
            "chase_pct": cp, "ball_pct": bp,
        }
    return sorted(deduped.values(), key=lambda r: r["date"])


def key_tendencies(summary, strike_pct, attack_rows):
    """Auto-generate bullet points."""
    bullets = []

    # Zone width
    if summary["shadow_pct"] >= 45:
        bullets.append("<b>WIDE ZONE:</b> Calls strikes on shadow pitches at a high rate ({:.1f}%). Be aggressive on borderline pitches.".format(summary["shadow_pct"]))
    elif summary["shadow_pct"] <= 30:
        bullets.append("<b>TIGHT ZONE:</b> Rarely calls strikes on shadow pitches ({:.1f}%). Take borderline pitches — they'll likely be balls.".format(summary["shadow_pct"]))
    else:
        bullets.append("<b>AVERAGE ZONE:</b> Shadow called strike rate is {:.1f}% (near league average).".format(summary["shadow_pct"]))

    # Chase expansion
    if summary["chase_pct"] >= 20:
        bullets.append("<b>EXPANDS:</b> Chase pitches get called strikes {:.1f}% of the time. Protect the plate — pitches just off may be called.".format(summary["chase_pct"]))
    else:
        bullets.append("<b>DOESN'T EXPAND:</b> Chase strike rate only {:.1f}%. Pitches off the plate will be called balls. Stay in the zone.".format(summary["chase_pct"]))

    # Heart consistency
    if summary["heart_pct"] >= 90:
        bullets.append("<b>CONSISTENT HEART:</b> {:.1f}% called strike rate on pitches over the middle. Very reliable.".format(summary["heart_pct"]))
    elif summary["heart_pct"] < 80:
        bullets.append("<b>MISSES HEART:</b> Only {:.1f}% called strike rate in the heart. May get some favorable calls on middle pitches.".format(summary["heart_pct"]))

    # Corner analysis (zones 1,3,7,9 — corners of the 3x3 grid)
    corners = [strike_pct.get(z) for z in [1, 3, 7, 9] if strike_pct.get(z) is not None]
    if corners:
        avg_corner = sum(corners) / len(corners)
        if avg_corner >= 50:
            bullets.append("<b>GIVES CORNERS:</b> Average corner called strike rate is {:.1f}%. Pitchers can work the edges.".format(avg_corner))
        elif avg_corner < 35:
            bullets.append("<b>TIGHT CORNERS:</b> Average corner called strike rate is only {:.1f}%. Work middle-in/middle-away instead.".format(avg_corner))

    # Top vs bottom
    top = [strike_pct.get(z) for z in [1, 2, 3] if strike_pct.get(z) is not None]
    bot = [strike_pct.get(z) for z in [7, 8, 9] if strike_pct.get(z) is not None]
    if top and bot:
        avg_top = sum(top) / len(top)
        avg_bot = sum(bot) / len(bot)
        diff = avg_top - avg_bot
        if abs(diff) >= 10:
            if diff > 0:
                bullets.append("<b>FAVORS HIGH:</b> Top row {:.1f}% vs bottom row {:.1f}%. Elevate with fastballs.".format(avg_top, avg_bot))
            else:
                bullets.append("<b>FAVORS LOW:</b> Bottom row {:.1f}% vs top row {:.1f}%. Attack the bottom of the zone.".format(avg_bot, avg_top))

    # Waste
    if summary["waste_pct"] >= 10:
        bullets.append("Caution: calls strikes on waste pitches at {:.1f}% — well off the plate.".format(summary["waste_pct"]))

    # FPS
    if summary["fps_pct"] >= 45:
        bullets.append("Hitter-unfriendly on first pitch — {:.1f}% called strike rate on 0-0 counts.".format(summary["fps_pct"]))
    elif summary["fps_pct"] <= 30:
        bullets.append("Favorable to hitters on first pitch — only {:.1f}% called strike rate on 0-0.".format(summary["fps_pct"]))

    return bullets


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

HOMEPAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Umpire Scouting Cards</title>
</head>
<body style="margin:0; padding:0; font-family:system-ui,-apple-system,sans-serif; background:#f5f5f5;">
<div style="max-width:600px; margin:80px auto; text-align:center;">
  <div style="background:{{ NAVY }}; color:white; padding:30px 40px; border-radius:8px 8px 0 0;">
    <h1 style="margin:0; font-size:28px; letter-spacing:1px;">UMPIRE SCOUTING CARDS</h1>
    <p style="margin:8px 0 0; opacity:0.8; font-size:14px;">Moeller Baseball — 2026 Season</p>
  </div>
  <div style="background:white; padding:40px; border-radius:0 0 8px 8px; box-shadow:0 2px 8px rgba(0,0,0,0.1);">
    <form action="/umpire" method="get" id="umpForm">
      <label style="font-size:16px; font-weight:600; display:block; margin-bottom:12px;">Select an Umpire</label>
      <select name="name" id="umpSelect" style="width:100%; padding:12px; font-size:16px; border:2px solid #ccc; border-radius:4px; margin-bottom:20px; font-family:inherit;">
        <option value="">-- Choose --</option>
        {% for u in umpires %}
        <option value="{{ u }}">{{ u }}</option>
        {% endfor %}
      </select>
      <button type="submit" style="background:{{ NAVY }}; color:white; border:none; padding:14px 40px; font-size:16px; border-radius:4px; cursor:pointer; font-family:inherit; font-weight:600; letter-spacing:0.5px;">View Report</button>
    </form>
    <hr style="margin:24px 0; border:none; border-top:1px solid #e0e0e0;">
    <button id="deploy-btn" onclick="doDeploy()" style="background:#24292e; color:white; border:none; padding:10px 24px; font-size:14px; border-radius:4px; cursor:pointer; font-family:inherit; font-weight:600;">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="white" style="vertical-align:-2px; margin-right:6px;"><path d="M12 2C6.48 2 2 6.48 2 12c0 4.42 2.87 8.17 6.84 9.5.5.08.66-.23.66-.5v-1.69c-2.77.6-3.36-1.34-3.36-1.34-.46-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.87 1.52 2.34 1.07 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.92 0-1.11.38-2 1.03-2.71-.1-.25-.45-1.29.1-2.64 0 0 .84-.27 2.75 1.02.79-.22 1.65-.33 2.5-.33.85 0 1.71.11 2.5.33 1.91-1.29 2.75-1.02 2.75-1.02.55 1.35.2 2.39.1 2.64.65.71 1.03 1.6 1.03 2.71 0 3.82-2.34 4.66-4.57 4.91.36.31.69.92.69 1.85V21c0 .27.16.59.67.5C19.14 20.16 22 16.42 22 12A10 10 0 0012 2z"/></svg>
      Push to GitHub
    </button>
    <span id="deploy-status" style="margin-left:10px; font-size:13px; color:#666;"></span>
  </div>
</div>
<script>
async function doDeploy() {
  const btn = document.getElementById('deploy-btn');
  const status = document.getElementById('deploy-status');
  btn.disabled = true; btn.textContent = 'Pushing...';
  status.textContent = '';
  try {
    const res = await fetch('/api/git-push', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      btn.textContent = 'Pushed!'; btn.style.background = '#2e7d32';
      status.textContent = '';
    } else {
      btn.textContent = 'Failed'; btn.style.background = '#c62828';
      status.textContent = data.message;
    }
  } catch(e) {
    btn.textContent = 'Error'; btn.style.background = '#c62828';
    status.textContent = e.message;
  }
  setTimeout(() => {
    btn.disabled = false; btn.style.background = '#24292e';
    btn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="white" style="vertical-align:-2px; margin-right:6px;"><path d="M12 2C6.48 2 2 6.48 2 12c0 4.42 2.87 8.17 6.84 9.5.5.08.66-.23.66-.5v-1.69c-2.77.6-3.36-1.34-3.36-1.34-.46-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.87 1.52 2.34 1.07 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.92 0-1.11.38-2 1.03-2.71-.1-.25-.45-1.29.1-2.64 0 0 .84-.27 2.75 1.02.79-.22 1.65-.33 2.5-.33.85 0 1.71.11 2.5.33 1.91-1.29 2.75-1.02 2.75-1.02.55 1.35.2 2.39.1 2.64.65.71 1.03 1.6 1.03 2.71 0 3.82-2.34 4.66-4.57 4.91.36.31.69.92.69 1.85V21c0 .27.16.59.67.5C19.14 20.16 22 16.42 22 12A10 10 0 0012 2z"/></svg> Push to GitHub';
  }, 3000);
}
</script>
<script>
document.getElementById('umpForm').addEventListener('submit', function(e) {
  e.preventDefault();
  var name = document.getElementById('umpSelect').value;
  if (name) window.location.href = '/umpire/' + encodeURIComponent(name);
});
</script>
</body>
</html>"""


CARD_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Umpire Card — {{ umpire_name }}</title>
</head>
<body style="margin:0; padding:0; font-family:system-ui,-apple-system,sans-serif; background:#f5f5f5;">
<div style="max-width:1200px; margin:0 auto; padding:20px;">

  <!-- Back link -->
  <a href="/" style="display:inline-block; margin-bottom:12px; color:{{ NAVY }}; text-decoration:none; font-weight:600;">&larr; Back to Umpire List</a>

  <!-- HEADER -->
  <div style="background:{{ NAVY }}; color:white; padding:24px 32px; border-radius:8px 8px 0 0; position:relative;">
    <div style="text-align:center;">
      <h1 style="margin:0; font-size:32px; letter-spacing:1px;">{{ umpire_name }}</h1>
      <p style="margin:8px 0 0; font-size:16px; opacity:0.85;">{{ games }} Game{{ 's' if games != 1 else '' }} &nbsp;|&nbsp; {{ summary.called }} Called Pitches</p>
    </div>
    <a id="export-btn" href="/api/export/{{ umpire_name }}" style="position:absolute; top:24px; right:32px; background:white; color:{{ NAVY }}; text-decoration:none; padding:10px 18px; border-radius:6px; font-size:13px; font-weight:700; letter-spacing:0.5px; display:inline-flex; align-items:center; gap:6px; transition:opacity 0.2s;" onmouseover="this.style.opacity='0.85'" onmouseout="this.style.opacity='1'">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{{ NAVY }}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
      Export PNG
    </a>
  </div>

  <!-- SUMMARY BAR -->
  <div style="display:flex; flex-wrap:wrap; gap:0;">
    {% for item in summary_items %}
    <div style="flex:1; min-width:120px; background:{{ NAVY }}; color:white; text-align:center; padding:14px 8px; border-right:1px solid rgba(255,255,255,0.15); {% if loop.last %}border-right:none;{% endif %}">
      <div style="font-size:11px; text-transform:uppercase; letter-spacing:0.5px; opacity:0.7; margin-bottom:4px;">{{ item.label }}</div>
      <div style="font-size:22px; font-weight:700;">{{ item.value }}</div>
    </div>
    {% endfor %}
  </div>

  <!-- KEY NOTES (top box) -->
  <div style="background:#fff8e1; border-left:5px solid #f9a825; padding:18px 24px; margin-top:2px;">
    <h2 style="margin:0 0 10px; font-size:16px; color:{{ NAVY }}; text-transform:uppercase; letter-spacing:1px;">Key Notes</h2>
    <ul style="margin:0; padding-left:18px; line-height:1.9; font-size:14px; color:#333;">
      {% for b in tendencies %}
      <li>{{ b|safe }}</li>
      {% endfor %}
    </ul>
  </div>

  <!-- ATTACK ZONE DIAGRAM + 3x3 GRID -->
  <div style="background:white; padding:24px; margin-top:2px;">
    <h2 style="margin:0 0 16px; font-size:18px; color:{{ NAVY }};">Zone Breakdown</h2>
    <div style="display:flex; gap:40px; flex-wrap:wrap; justify-content:center; align-items:flex-start;">

      <!-- Attack Zone Ring Diagram -->
      <div style="text-align:center;">
        <div style="font-weight:600; margin-bottom:12px; font-size:14px; color:{{ NAVY }};">Attack Zone Called Strike %</div>
        <div style="position:relative; width:320px; height:320px; margin:0 auto;">
          <!-- Waste (outermost) -->
          <div style="position:absolute; top:0; left:0; width:320px; height:320px; background:{{ az_colors.Waste.bg }}; border:2px solid #90a4ae; border-radius:4px; display:flex; align-items:center; justify-content:center;">
          </div>
          <div style="position:absolute; top:8px; left:50%; transform:translateX(-50%); font-size:11px; font-weight:600; color:#546e7a;">WASTE</div>
          <div style="position:absolute; bottom:8px; left:50%; transform:translateX(-50%); font-size:18px; font-weight:700; color:{{ az_colors.Waste.fg }};">{{ '%.1f' | format(summary.waste_pct) }}%</div>

          <!-- Chase -->
          <div style="position:absolute; top:35px; left:35px; width:250px; height:250px; background:{{ az_colors.Chase.bg }}; border:2px solid #66bb6a; border-radius:4px;">
          </div>
          <div style="position:absolute; top:43px; left:50%; transform:translateX(-50%); font-size:11px; font-weight:600; color:#2e7d32;">CHASE</div>
          <div style="position:absolute; bottom:43px; left:50%; transform:translateX(-50%); font-size:18px; font-weight:700; color:{{ az_colors.Chase.fg }};">{{ '%.1f' | format(summary.chase_pct) }}%</div>

          <!-- Shadow -->
          <div style="position:absolute; top:75px; left:75px; width:170px; height:170px; background:{{ az_colors.Shadow.bg }}; border:2px solid #fbc02d; border-radius:4px;">
          </div>
          <div style="position:absolute; top:83px; left:50%; transform:translateX(-50%); font-size:11px; font-weight:600; color:#f57f17;">SHADOW</div>
          <div style="position:absolute; top:115px; left:50%; transform:translateX(-50%); font-size:18px; font-weight:700; color:{{ az_colors.Shadow.fg }};">{{ '%.1f' | format(summary.shadow_pct) }}%</div>

          <!-- Heart (center) -->
          <div style="position:absolute; top:120px; left:120px; width:80px; height:80px; background:{{ az_colors.Heart.bg }}; border:2px solid #e53935; border-radius:4px; display:flex; flex-direction:column; align-items:center; justify-content:center;">
            <div style="font-size:10px; font-weight:600; color:#c62828;">HEART</div>
            <div style="font-size:16px; font-weight:700; color:{{ az_colors.Heart.fg }};">{{ '%.1f' | format(summary.heart_pct) }}%</div>
          </div>
        </div>
        <div style="font-size:11px; color:#888; margin-top:8px;">Called Strike % by Attack Zone</div>
      </div>

      <!-- 3x3 Called Strike % Grid -->
      <div style="text-align:center;">
        <div style="font-weight:600; margin-bottom:12px; font-size:14px; color:{{ NAVY }};">Called Strike % (3&times;3 Grid)</div>
        <table style="border-collapse:collapse; margin:0 auto;">
          {% set grid = grids[0] %}
          {% for row in range(3) %}
          <tr>
            {% for col in range(3) %}
            {% set z = row * 3 + col + 1 %}
            {% set val = grid.data[z] %}
            {% if val is none %}
            <td style="width:80px; height:64px; text-align:center; font-size:15px; font-weight:600; border:1px solid #ccc; background:#eee; color:#999;">—</td>
            {% else %}
              {% if val >= 70 %}{% set bg = '#2e7d32' %}{% set fg = 'white' %}
              {% elif val >= 50 %}{% set bg = '#81c784' %}{% set fg = '#1a1a1a' %}
              {% elif val >= 30 %}{% set bg = '#fff176' %}{% set fg = '#1a1a1a' %}
              {% else %}{% set bg = '#e57373' %}{% set fg = 'white' %}{% endif %}
            <td style="width:80px; height:64px; text-align:center; font-weight:600; border:1px solid #ccc; background:{{ bg }}; color:{{ fg }};">
              <div style="font-size:16px;">{{ '%.0f' | format(val) }}%</div>
              <div style="font-size:10px; opacity:0.7;">n={{ grid.counts[z] }}</div>
            </td>
            {% endif %}
            {% endfor %}
          </tr>
          {% endfor %}
        </table>
        <div style="font-size:11px; color:#888; margin-top:8px;">Catcher's View &mdash; Strike Looking / Called Pitches</div>
      </div>

      <!-- Pitch Volume Grid -->
      <div style="text-align:center;">
        <div style="font-weight:600; margin-bottom:12px; font-size:14px; color:{{ NAVY }};">Pitch Volume (3&times;3 Grid)</div>
        <table style="border-collapse:collapse; margin:0 auto;">
          {% set grid = grids[1] %}
          {% for row in range(3) %}
          <tr>
            {% for col in range(3) %}
            {% set z = row * 3 + col + 1 %}
            {% set val = grid.data[z] %}
            {% if val is none %}
            <td style="width:80px; height:64px; text-align:center; font-size:15px; font-weight:600; border:1px solid #ccc; background:#eee; color:#999;">—</td>
            {% else %}
            <td style="width:80px; height:64px; text-align:center; font-size:16px; font-weight:600; border:1px solid #ccc; background:#e8eaf6; color:{{ NAVY }};">
              <div>{{ val }}</div>
              <div style="font-size:10px; opacity:0.7;">({{ grid.pcts[z] }}%)</div>
            </td>
            {% endif %}
            {% endfor %}
          </tr>
          {% endfor %}
        </table>
        <div style="font-size:11px; color:#888; margin-top:8px;">Called Pitches per Zone</div>
      </div>

    </div>
  </div>

  <!-- ATTACK ZONE TABLE -->
  <div style="background:white; padding:24px; margin-top:2px;">
    <h2 style="margin:0 0 6px; font-size:18px; color:{{ NAVY }};">Attack Zone Breakdown</h2>
    <p style="margin:0 0 12px; font-size:12px; color:#666; line-height:1.5;">
      <b>League Avg</b> = average called strike % across all umpires in our {{ season_year }} Moeller charting data ({{ league_umpires }} umpire{{ 's' if league_umpires != 1 else '' }}, {{ league_called }} called pitches).
      This is our dataset average, not an official league stat.
    </p>
    <table style="width:100%; border-collapse:collapse; font-size:14px;">
      <thead>
        <tr style="background:{{ NAVY }}; color:white;">
          <th style="padding:10px 12px; text-align:left;">Zone</th>
          <th style="padding:10px 12px; text-align:center;">Called N</th>
          <th style="padding:10px 12px; text-align:center;">Called Strk%</th>
          <th style="padding:10px 12px; text-align:center;">Ball%</th>
          <th style="padding:10px 12px; text-align:center;">Dataset Avg Strk%<br><span style="font-weight:400; font-size:10px; opacity:0.8;">All {{ league_umpires }} ump{{ 's' if league_umpires != 1 else '' }}, {{ league_called }} pitches</span></th>
        </tr>
      </thead>
      <tbody>
        {% set zone_colors = {'Heart':'#ffcdd2','Shadow':'#fff9c4','Chase':'#c8e6c9','Waste':'#e3f2fd'} %}
        {% for r in attack_rows %}
        <tr style="background:{{ zone_colors[r.zone] }};">
          <td style="padding:10px 12px; font-weight:600;">{{ r.zone }}</td>
          <td style="padding:10px 12px; text-align:center;">{{ r.n }}</td>
          <td style="padding:10px 12px; text-align:center;">{{ '%.1f' | format(r.cs_pct) }}%</td>
          <td style="padding:10px 12px; text-align:center;">{{ '%.1f' | format(r.ball_pct) }}%</td>
          <td style="padding:10px 12px; text-align:center;">{{ '%.1f' | format(r.league_avg) }}%</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- COUNT SITUATION TABLE -->
  <div style="background:white; padding:24px; margin-top:2px;">
    <h2 style="margin:0 0 12px; font-size:18px; color:{{ NAVY }};">Count Situation Breakdown</h2>
    <table style="width:100%; border-collapse:collapse; font-size:14px;">
      <thead>
        <tr style="background:{{ NAVY }}; color:white;">
          <th style="padding:10px 12px; text-align:left;">Situation</th>
          <th style="padding:10px 12px; text-align:center;">Called N</th>
          <th style="padding:10px 12px; text-align:center;">Called Strk%</th>
          <th style="padding:10px 12px; text-align:center;">Ball%</th>
        </tr>
      </thead>
      <tbody>
        {% set sit_colors = {'Ahead':'#c8e6c9','Behind':'#ffcdd2','Even':'#e3f2fd','Full':'#fff9c4'} %}
        {% for r in count_rows %}
        <tr style="background:{{ sit_colors[r.situation] }};">
          <td style="padding:10px 12px; font-weight:600;">{{ r.situation }}</td>
          <td style="padding:10px 12px; text-align:center;">{{ r.n }}</td>
          <td style="padding:10px 12px; text-align:center;">{{ '%.1f' | format(r.cs_pct) }}%</td>
          <td style="padding:10px 12px; text-align:center;">{{ '%.1f' | format(r.ball_pct) }}%</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- GAME-BY-GAME TABLE -->
  <div style="background:white; padding:24px; margin-top:2px;">
    <h2 style="margin:0 0 12px; font-size:18px; color:{{ NAVY }};">Game-by-Game Log</h2>
    <table style="width:100%; border-collapse:collapse; font-size:13px;">
      <thead>
        <tr style="background:{{ NAVY }}; color:white;">
          <th style="padding:8px 10px; text-align:left;">Date</th>
          <th style="padding:8px 10px; text-align:left;">Teams</th>
          <th style="padding:8px 10px; text-align:center;">Called N</th>
          <th style="padding:8px 10px; text-align:center;">Called Strk%</th>
          <th style="padding:8px 10px; text-align:center;">Shadow Strk%</th>
          <th style="padding:8px 10px; text-align:center;">Chase Strk%</th>
          <th style="padding:8px 10px; text-align:center;">Ball%</th>
        </tr>
      </thead>
      <tbody>
        {% for r in game_rows %}
        <tr style="background:{{ '#f8f9fa' if loop.index is odd else 'white' }};">
          <td style="padding:8px 10px;">{{ r.date }}</td>
          <td style="padding:8px 10px;">{{ r.teams }}</td>
          <td style="padding:8px 10px; text-align:center;">{{ r.n }}</td>
          <td style="padding:8px 10px; text-align:center;">{{ '%.1f' | format(r.cs_pct) }}%</td>
          <td style="padding:8px 10px; text-align:center;">{{ '%.1f' | format(r.shadow_pct) }}%</td>
          <td style="padding:8px 10px; text-align:center;">{{ '%.1f' | format(r.chase_pct) }}%</td>
          <td style="padding:8px 10px; text-align:center;">{{ '%.1f' | format(r.ball_pct) }}%</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- Bottom spacer -->
  <div style="height:40px;"></div>

</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def homepage():
    umpires = sorted(CALLED["Umpire"].dropna().unique())
    return render_template_string(HOMEPAGE_TEMPLATE, umpires=umpires, NAVY=NAVY)


@app.route("/umpire/<name>")
def umpire_card(name):
    ump_data = CALLED[CALLED["Umpire"] == name]
    if ump_data.empty:
        return f"<h1>No data found for umpire: {name}</h1><a href='/'>Back</a>", 404

    games = ump_data["Date"].nunique()
    summary = compute_summary(ump_data)

    summary_items = [
        {"label": "Called Pitches", "value": summary["called"]},
        {"label": "Called Strk%", "value": "{:.1f}%".format(summary["cs_pct"])},
        {"label": "Shadow Strk%", "value": "{:.1f}%".format(summary["shadow_pct"])},
        {"label": "Chase Strk%", "value": "{:.1f}%".format(summary["chase_pct"])},
        {"label": "Heart Strk%", "value": "{:.1f}%".format(summary["heart_pct"])},
        {"label": "Waste Strk%", "value": "{:.1f}%".format(summary["waste_pct"])},
        {"label": "Ball%", "value": "{:.1f}%".format(summary["ball_pct"])},
        {"label": "FPS Called%", "value": "{:.1f}%".format(summary["fps_pct"])},
    ]

    strike_pct, volume, borderline = compute_zone_grids(ump_data)

    # Compute counts and percentages for the grids
    total_called = sum(volume.get(z, 0) for z in range(1, 10))
    vol_pcts = {}
    for z in range(1, 10):
        vol_pcts[z] = round(volume.get(z, 0) / total_called * 100) if total_called > 0 else 0

    grids = [
        {"title": "Called Strike %", "data": strike_pct, "is_pct": True, "counts": volume},
        {"title": "Pitch Volume", "data": volume, "is_pct": False, "pcts": vol_pcts},
    ]

    # Attack zone colors based on called strike rate
    def az_color(pct):
        if pct >= 70:
            return {"bg": "#ffcdd2", "fg": "#b71c1c"}
        elif pct >= 50:
            return {"bg": "#fff9c4", "fg": "#f57f17"}
        elif pct >= 20:
            return {"bg": "#c8e6c9", "fg": "#1b5e20"}
        else:
            return {"bg": "#e3f2fd", "fg": "#0d47a1"}

    az_colors = {
        "Heart": az_color(summary["heart_pct"]),
        "Shadow": az_color(summary["shadow_pct"]),
        "Chase": az_color(summary["chase_pct"]),
        "Waste": az_color(summary["waste_pct"]),
    }

    attack_rows = compute_attack_table(ump_data, CALLED)
    count_rows = count_situation(ump_data)
    game_rows = game_by_game(ump_data)
    tendencies = key_tendencies(summary, strike_pct, attack_rows)

    league_umpires = CALLED["Umpire"].nunique()
    league_called_n = len(CALLED)

    return render_template_string(
        CARD_TEMPLATE,
        umpire_name=name,
        games=games,
        summary=summary,
        summary_items=summary_items,
        grids=grids,
        az_colors=az_colors,
        attack_rows=attack_rows,
        count_rows=count_rows,
        game_rows=game_rows,
        tendencies=tendencies,
        season_year=SEASON_YEAR,
        league_umpires=league_umpires,
        league_called=league_called_n,
        NAVY=NAVY,
    )


@app.route("/api/export/<name>")
def export_card(name):
    """Generate the umpire card PNG via umpire_card.py and serve it as a download."""
    app_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(app_dir, "output")
    safe_name = name.replace(" ", "_")
    png_path = os.path.join(output_dir, f"Umpire_{safe_name}.png")

    # Run umpire_card.py to generate/refresh the PNG
    python_exe = r"C:\Users\IDBac\AppData\Local\Programs\Python\Python313\python.exe"
    try:
        result = subprocess.run(
            [python_exe, "umpire_card.py", "--umpire", name],
            cwd=app_dir, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0 and not os.path.exists(png_path):
            return jsonify({"error": "Card generation failed", "detail": result.stderr}), 500
    except Exception as e:
        # If generation fails but a cached PNG exists, serve that
        if not os.path.exists(png_path):
            return jsonify({"error": str(e)}), 500

    if not os.path.exists(png_path):
        return jsonify({"error": f"PNG not found for {name}"}), 404

    return send_file(
        png_path,
        mimetype="image/png",
        as_attachment=True,
        download_name=f"Umpire_{safe_name}.png",
    )


@app.route("/api/git-push", methods=["POST"])
def git_push():
    """Stage all changes, commit with a timestamp, and push to origin."""
    try:
        ts = datetime.now().strftime("%a %m/%d/%Y %H:%M")
        msg = f"Data update - {ts}"
        app_dir = os.path.dirname(os.path.abspath(__file__))
        cmds = [
            ["git", "add", "-A"],
            ["git", "commit", "-m", msg],
            ["git", "push", "origin", "main"],
        ]
        output_lines = []
        for cmd in cmds:
            r = subprocess.run(cmd, cwd=app_dir, capture_output=True, text=True, timeout=30)
            out = (r.stdout + r.stderr).strip()
            if out:
                output_lines.append(out)
            if r.returncode != 0 and "nothing to commit" not in out:
                return jsonify({"ok": False, "message": out}), 500
        return jsonify({"ok": True, "message": "\n".join(output_lines) or "Pushed successfully."})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
