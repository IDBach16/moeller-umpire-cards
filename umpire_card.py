#!/usr/bin/env python3
"""
Moeller Baseball Analytics — Umpire Scouting Card Generator
Generates professional PNG umpire scouting cards from pitch-by-pitch Excel data.

Only analyzes pitches where the UMPIRE made the decision:
  - "Strike Looking" and "Ball" pitches.
  - Swings (whiffs, fouls, in play) are batter decisions and are excluded.

Usage:
    python umpire_card.py --umpire "Jeff Davis"
    python umpire_card.py --all
"""

import argparse
import sys
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from PIL import Image
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------
BASE_DIR = Path(r"C:\Users\IDBac\OneDrive\Desktop\Moeller\Umpire_Card")
EXCEL_PATH = BASE_DIR / "Moeller_2024_2025_2026_Final_Season.xlsx"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOGO_PATH = Path(r"C:\Users\IDBac\OneDrive\Desktop\Moeller\Pitcher_Card\shield_new.png")

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------
NAVY = "#1a1a2e"
LIGHT_BG = "#f8f9fa"
WHITE = "#ffffff"
GREY_LINE = "#dee2e6"
HEADER_BG = NAVY
HEADER_FG = WHITE
ROW_EVEN = "#f0f2f5"
ROW_ODD = WHITE

CALLED_STRK_COLORS = [(65, "#a8e6a3"), (50, "#fff9c4"), (0, "#ef9a9a")]


# Location number -> 3x3 zone (1-9)
def loc_to_zone(loc):
    """Map Location 1-27 to 3x3 zone grid (1-9)."""
    try:
        loc = int(loc)
    except (ValueError, TypeError):
        return np.nan
    if loc < 1 or loc > 27:
        return np.nan
    return ((loc - 1) // 3) + 1


# ---------------------------------------------------------------------------
# DATA LOADING
# ---------------------------------------------------------------------------
def load_data():
    """Load and lightly clean the master Excel file."""
    df = pd.read_excel(EXCEL_PATH, sheet_name="Moeller_2024_2025_Final_Season")
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["PitchVelo"] = pd.to_numeric(df["PitchVelo"], errors="coerce")
    df["Location"] = pd.to_numeric(df["Location"], errors="coerce")
    df["Zone"] = df["Location"].apply(loc_to_zone)
    df["Balls"] = pd.to_numeric(df["Balls"], errors="coerce")
    df["Strikes"] = pd.to_numeric(df["Strikes"], errors="coerce")
    df["Inning"] = pd.to_numeric(df["Inning"], errors="coerce")
    return df


def get_called_pitches(df):
    """Return only pitches where the umpire made the decision (Strike Looking or Ball)."""
    return df[df["PitchResult"].isin(["Strike Looking", "Ball"])].copy()


# ---------------------------------------------------------------------------
# STAT HELPERS
# ---------------------------------------------------------------------------
def safe_fmt(val, fmt=".1f"):
    try:
        return f"{val:{fmt}}"
    except (ValueError, TypeError):
        return "-"


def called_strk_pct(df):
    """Called strike % = Strike Looking / (Strike Looking + Ball)."""
    if len(df) == 0:
        return 0.0
    sl = (df["PitchResult"] == "Strike Looking").sum()
    return (sl / len(df)) * 100


def called_ball_pct(df):
    """Ball % of called pitches."""
    if len(df) == 0:
        return 0.0
    balls = (df["PitchResult"] == "Ball").sum()
    return (balls / len(df)) * 100


def fps_called_pct(df):
    """First-pitch (0-0 count) called strike rate among called pitches."""
    first = df[(df["Balls"] == 0) & (df["Strikes"] == 0)]
    if len(first) == 0:
        return 0.0
    sl = (first["PitchResult"] == "Strike Looking").sum()
    return (sl / len(first)) * 100


def color_for_metric(val, thresholds):
    """Return background color based on thresholds list of (min_val, color)."""
    try:
        val = float(val)
    except (ValueError, TypeError):
        return WHITE
    for threshold, color in thresholds:
        if val >= threshold:
            return color
    return thresholds[-1][1] if thresholds else WHITE


# ---------------------------------------------------------------------------
# TABLE DRAWING HELPER (matching pitcher card style)
# ---------------------------------------------------------------------------
def draw_table(ax, col_labels, rows, col_widths=None, header_color=NAVY,
               header_text_color=WHITE, row_colors=None, cell_colors=None,
               font_size=11, header_font_size=12, title=None, title_size=14):
    """Draw a professional table on the given axes."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    n_cols = len(col_labels)
    n_rows = len(rows)
    if col_widths is None:
        col_widths = [1.0 / n_cols] * n_cols

    total_rows = n_rows + 1  # +1 for header
    title_offset = 0
    if title:
        total_rows += 1
        title_offset = 1

    row_h = 1.0 / (total_rows + 0.5)

    # Title
    if title:
        ax.text(0.5, 1.0 - row_h * 0.5, title, ha="center", va="center",
                fontsize=title_size, fontweight="bold", color=NAVY)

    # Header row
    y_top = 1.0 - row_h * (title_offset + 0.25)
    x = 0.0
    for j, label in enumerate(col_labels):
        w = col_widths[j]
        rect = mpatches.FancyBboxPatch((x, y_top - row_h), w, row_h,
                                        boxstyle="square,pad=0", facecolor=header_color,
                                        edgecolor=NAVY, linewidth=0.5)
        ax.add_patch(rect)
        ax.text(x + w / 2, y_top - row_h / 2, str(label), ha="center", va="center",
                fontsize=header_font_size, fontweight="bold", color=header_text_color)
        x += w

    # Data rows
    for i, row in enumerate(rows):
        y_top_row = 1.0 - row_h * (title_offset + 1.25 + i)
        if row_colors and i < len(row_colors):
            bg = row_colors[i]
        else:
            bg = ROW_EVEN if i % 2 == 0 else ROW_ODD
        x = 0.0
        for j, val in enumerate(row):
            w = col_widths[j]
            cbg = bg
            if cell_colors and i < len(cell_colors) and j < len(cell_colors[i]):
                cc = cell_colors[i][j]
                if cc is not None:
                    cbg = cc
            rect = mpatches.FancyBboxPatch((x, y_top_row - row_h), w, row_h,
                                            boxstyle="square,pad=0", facecolor=cbg,
                                            edgecolor=GREY_LINE, linewidth=0.5)
            ax.add_patch(rect)
            fw = "bold" if j == 0 else "normal"
            ax.text(x + w / 2, y_top_row - row_h / 2, str(val), ha="center", va="center",
                    fontsize=font_size, fontweight=fw, color="#212529")
            x += w


# ---------------------------------------------------------------------------
# HEATMAP HELPERS
# ---------------------------------------------------------------------------
def plot_called_strike_heatmap(ax, called_df):
    """3x3 zone heatmap: Called Strike % per zone."""
    ax.set_facecolor(LIGHT_BG)
    grid = np.full((3, 3), np.nan)
    grid_n = np.full((3, 3), 0)

    for zone_num in range(1, 10):
        row_idx = (zone_num - 1) // 3
        col_idx = (zone_num - 1) % 3
        zdf = called_df[called_df["Zone"] == zone_num]
        grid_n[row_idx, col_idx] = len(zdf)
        if len(zdf) > 0:
            grid[row_idx, col_idx] = called_strk_pct(zdf)
        else:
            grid[row_idx, col_idx] = 0

    cmap = LinearSegmentedColormap.from_list("cstrk", ["#ef5350", "#fff176", "#66bb6a"])
    masked = np.ma.array(grid, mask=np.isnan(grid))
    ax.imshow(masked, cmap=cmap, vmin=0, vmax=100, aspect="equal")

    for i in range(3):
        for j in range(3):
            val = grid[i, j]
            n = grid_n[i, j]
            if not np.isnan(val):
                text_color = "white" if val > 80 or val < 20 else "#212529"
                ax.text(j, i, f"{val:.0f}%\n(n={n})", ha="center", va="center",
                        fontsize=12, fontweight="bold", color=text_color)

    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("Called Strike %\n(by Zone)", fontsize=13,
                 fontweight="bold", color=NAVY, pad=15)
    for spine in ax.spines.values():
        spine.set_edgecolor(NAVY)
        spine.set_linewidth(2)


def plot_volume_heatmap(ax, called_df):
    """3x3 zone heatmap: Pitch volume per zone."""
    ax.set_facecolor(LIGHT_BG)
    grid = np.full((3, 3), 0.0)

    for zone_num in range(1, 10):
        row_idx = (zone_num - 1) // 3
        col_idx = (zone_num - 1) % 3
        zdf = called_df[called_df["Zone"] == zone_num]
        grid[row_idx, col_idx] = len(zdf)

    max_val = grid.max() if grid.max() > 0 else 1
    cmap = LinearSegmentedColormap.from_list("vol", ["#e3f2fd", "#1565c0"])
    ax.imshow(grid, cmap=cmap, vmin=0, vmax=max_val, aspect="equal")

    for i in range(3):
        for j in range(3):
            n = int(grid[i, j])
            pct = (n / len(called_df) * 100) if len(called_df) > 0 else 0
            text_color = "white" if n > max_val * 0.6 else "#212529"
            ax.text(j, i, f"{n}\n({pct:.0f}%)", ha="center", va="center",
                    fontsize=12, fontweight="bold", color=text_color)

    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("Pitch Volume\n(Called Pitches)", fontsize=13,
                 fontweight="bold", color=NAVY, pad=15)
    for spine in ax.spines.values():
        spine.set_edgecolor(NAVY)
        spine.set_linewidth(2)


def plot_borderline_heatmap(ax, called_df):
    """3x3 zone heatmap: Borderline (Shadow + Chase) called strike %."""
    ax.set_facecolor(LIGHT_BG)
    grid = np.full((3, 3), np.nan)
    grid_n = np.full((3, 3), 0)

    borderline = called_df[called_df["AttackZone"].isin(["Shadow", "Chase"])]

    for zone_num in range(1, 10):
        row_idx = (zone_num - 1) // 3
        col_idx = (zone_num - 1) % 3
        zdf = borderline[borderline["Zone"] == zone_num]
        grid_n[row_idx, col_idx] = len(zdf)
        if len(zdf) > 0:
            grid[row_idx, col_idx] = called_strk_pct(zdf)

    cmap = LinearSegmentedColormap.from_list("border", ["#ef5350", "#fff176", "#66bb6a"])
    masked = np.ma.array(grid, mask=np.isnan(grid))
    ax.imshow(masked, cmap=cmap, vmin=0, vmax=100, aspect="equal")

    for i in range(3):
        for j in range(3):
            val = grid[i, j]
            n = grid_n[i, j]
            if np.isnan(val):
                ax.text(j, i, "-", ha="center", va="center",
                        fontsize=12, fontweight="bold", color="#aaaaaa")
            else:
                text_color = "white" if val > 80 or val < 20 else "#212529"
                ax.text(j, i, f"{val:.0f}%\n(n={n})", ha="center", va="center",
                        fontsize=12, fontweight="bold", color=text_color)

    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("Borderline Call Rate\n(Shadow + Chase Only)", fontsize=13,
                 fontweight="bold", color=NAVY, pad=15)
    for spine in ax.spines.values():
        spine.set_edgecolor(NAVY)
        spine.set_linewidth(2)


# ---------------------------------------------------------------------------
# KEY TENDENCIES TEXT GENERATOR
# ---------------------------------------------------------------------------
def generate_tendencies(called_df, league_avg_strk, league_shadow_strk,
                        game_strk_rates):
    """Auto-generate bullet-point tendency text."""
    bullets = []
    overall = called_strk_pct(called_df)

    # Wide vs tight zone
    diff = overall - league_avg_strk
    if diff > 5:
        bullets.append(f"WIDE ZONE: Called strike rate ({overall:.1f}%) is {diff:.1f}% above league average ({league_avg_strk:.1f}%). Expect a bigger zone.")
    elif diff < -5:
        bullets.append(f"TIGHT ZONE: Called strike rate ({overall:.1f}%) is {abs(diff):.1f}% below league average ({league_avg_strk:.1f}%). Expect a smaller zone.")
    else:
        bullets.append(f"AVERAGE ZONE: Called strike rate ({overall:.1f}%) is near league average ({league_avg_strk:.1f}%).")

    # Shadow (corners)
    shadow_df = called_df[called_df["AttackZone"] == "Shadow"]
    if len(shadow_df) > 5:
        shadow_rate = called_strk_pct(shadow_df)
        shadow_diff = shadow_rate - league_shadow_strk
        if shadow_diff > 5:
            bullets.append(f"GIVES THE CORNERS: Shadow zone called strike rate ({shadow_rate:.1f}%) is above league avg ({league_shadow_strk:.1f}%). Pitchers should attack edges.")
        elif shadow_diff < -5:
            bullets.append(f"DOESN'T GIVE THE CORNERS: Shadow zone called strike rate ({shadow_rate:.1f}%) is below league avg ({league_shadow_strk:.1f}%). Need to paint inside the zone.")
        else:
            bullets.append(f"AVERAGE ON CORNERS: Shadow zone called strike rate ({shadow_rate:.1f}%) is near league avg ({league_shadow_strk:.1f}%).")

    # Chase (expansion)
    chase_df = called_df[called_df["AttackZone"] == "Chase"]
    if len(chase_df) > 5:
        chase_rate = called_strk_pct(chase_df)
        if chase_rate > 20:
            bullets.append(f"EXPANDS THE ZONE: Chase zone called strike rate ({chase_rate:.1f}%) is elevated. This ump calls strikes off the plate. Pitchers can work just off the edge.")
        elif chase_rate < 10:
            bullets.append(f"DOESN'T EXPAND: Chase zone called strike rate ({chase_rate:.1f}%) is low. Pitches off the plate will be called balls. Stay in the zone.")
        else:
            bullets.append(f"MODERATE EXPANSION: Chase zone called strike rate ({chase_rate:.1f}%). Some borderline calls go his way.")

    # Consistency (game-to-game variation)
    if len(game_strk_rates) >= 3:
        std = np.std(game_strk_rates)
        if std > 8:
            bullets.append(f"INCONSISTENT: Game-to-game called strike rate varies significantly (std={std:.1f}%). Zone may shift during the game.")
        elif std < 4:
            bullets.append(f"CONSISTENT: Game-to-game called strike rate is very stable (std={std:.1f}%). Expect a predictable zone.")
        else:
            bullets.append(f"MODERATELY CONSISTENT: Game-to-game called strike rate variability is average (std={std:.1f}%).")

    return bullets


# ---------------------------------------------------------------------------
# MAIN CARD GENERATOR
# ---------------------------------------------------------------------------
def generate_card(umpire_name, ump_all_pitches, all_called_df):
    """Generate a single umpire scouting card (aggregated across all games)."""

    # Called pitches for this umpire
    called_df = get_called_pitches(ump_all_pitches)
    if len(called_df) == 0:
        print(f"  No called pitches found for {umpire_name}, skipping.")
        return None

    total_called = len(called_df)
    n_games = ump_all_pitches["Date"].dt.date.nunique()

    # League averages (across all umpires)
    league_called_strk = called_strk_pct(all_called_df)
    league_shadow = all_called_df[all_called_df["AttackZone"] == "Shadow"]
    league_shadow_strk = called_strk_pct(league_shadow)
    league_chase = all_called_df[all_called_df["AttackZone"] == "Chase"]
    league_chase_strk = called_strk_pct(league_chase)
    league_heart = all_called_df[all_called_df["AttackZone"] == "Heart"]
    league_heart_strk = called_strk_pct(league_heart)
    league_waste = all_called_df[all_called_df["AttackZone"] == "Waste"]
    league_waste_strk = called_strk_pct(league_waste)

    # Umpire-level stats
    overall_strk = called_strk_pct(called_df)
    overall_ball = called_ball_pct(called_df)

    shadow_df = called_df[called_df["AttackZone"] == "Shadow"]
    shadow_strk = called_strk_pct(shadow_df)

    chase_df = called_df[called_df["AttackZone"] == "Chase"]
    chase_strk = called_strk_pct(chase_df)

    heart_df = called_df[called_df["AttackZone"] == "Heart"]
    heart_strk = called_strk_pct(heart_df)

    waste_df = called_df[called_df["AttackZone"] == "Waste"]
    waste_strk = called_strk_pct(waste_df)

    fps_rate = fps_called_pct(called_df)

    # Game-by-game data
    game_dates = sorted(ump_all_pitches["Date"].dt.date.dropna().unique())
    game_rows = []
    game_strk_rates = []
    for gdate in game_dates:
        gdf = ump_all_pitches[ump_all_pitches["Date"].dt.date == gdate]
        g_called = get_called_pitches(gdf)
        if len(g_called) == 0:
            continue
        g_strk = called_strk_pct(g_called)
        game_strk_rates.append(g_strk)

        g_shadow = g_called[g_called["AttackZone"] == "Shadow"]
        g_shadow_strk = called_strk_pct(g_shadow) if len(g_shadow) > 0 else 0
        g_chase = g_called[g_called["AttackZone"] == "Chase"]
        g_chase_strk = called_strk_pct(g_chase) if len(g_chase) > 0 else 0
        g_ball = called_ball_pct(g_called)

        # Build team matchup string
        teams = set()
        for col in ["PitcherTeam", "BatterTeam"]:
            if col in gdf.columns:
                for t in gdf[col].dropna().unique():
                    cleaned = str(t).replace(" High School", "").replace(" HS", "").strip()
                    teams.add(cleaned)
        teams_str = " vs ".join(sorted(teams)[:2]) if teams else "Unknown"

        game_rows.append([
            gdate.strftime("%m/%d/%y"),
            teams_str,
            str(len(g_called)),
            safe_fmt(g_strk, ".1f") + "%",
            safe_fmt(g_shadow_strk, ".1f") + "%",
            safe_fmt(g_chase_strk, ".1f") + "%",
            safe_fmt(g_ball, ".1f") + "%",
        ])

    # --- CREATE FIGURE ---
    fig = plt.figure(figsize=(20, 22), facecolor=WHITE)
    fig.subplots_adjust(left=0.03, right=0.97, top=0.97, bottom=0.02, hspace=0.25, wspace=0.15)

    # Master grid: 7 row sections
    outer = gridspec.GridSpec(7, 1, figure=fig,
                              height_ratios=[1.1, 0.65, 2.4, 2.0, 2.2, 1.2, 0.35],
                              hspace=0.18)

    # --- Center watermark logo ---
    if LOGO_PATH.exists():
        try:
            logo_img = Image.open(LOGO_PATH).convert("RGBA")
            alpha = logo_img.split()[3]
            alpha = alpha.point(lambda p: int(p * 0.06))
            logo_img.putalpha(alpha)
            logo_arr = np.array(logo_img)
            wm_ax = fig.add_axes([0.30, 0.25, 0.40, 0.50], zorder=0)
            wm_ax.imshow(logo_arr, aspect="equal")
            wm_ax.axis("off")
        except Exception:
            pass

    # ===================================================================
    # ROW 0: HEADER
    # ===================================================================
    header_ax = fig.add_subplot(outer[0])
    header_ax.set_xlim(0, 1)
    header_ax.set_ylim(0, 1)
    header_ax.axis("off")

    # Initials circle (no headshot for umpires)
    initials = "".join([p[0] for p in umpire_name.split() if p])[:2].upper()
    header_ax.add_patch(mpatches.FancyBboxPatch(
        (0.01, 0.15), 0.10, 0.70, boxstyle="round,pad=0.01",
        facecolor=NAVY, edgecolor="none", transform=header_ax.transAxes, zorder=4
    ))
    header_ax.text(0.06, 0.5, initials, transform=header_ax.transAxes,
                   ha="center", va="center", fontsize=28, fontweight="bold",
                   color=WHITE, zorder=6)

    header_ax.text(0.14, 0.78, f"{umpire_name} — Scouting Report",
                   transform=header_ax.transAxes, fontsize=30, fontweight="bold",
                   color=NAVY, va="center")
    header_ax.text(0.14, 0.45, f"{n_games} Game(s)  |  {total_called} Total Pitches Called",
                   transform=header_ax.transAxes, fontsize=18, color="#555555", va="center")
    header_ax.text(0.14, 0.18, "Moeller Baseball Analytics",
                   transform=header_ax.transAxes, fontsize=14, color="#888888",
                   va="center", style="italic")

    # Logo in top-right
    if LOGO_PATH.exists():
        try:
            logo_hdr = Image.open(LOGO_PATH)
            logo_hdr.thumbnail((200, 200))
            logo_hdr_arr = np.array(logo_hdr)
            imagebox_logo = OffsetImage(logo_hdr_arr, zoom=0.9)
            ab_logo = AnnotationBbox(imagebox_logo, (0.95, 0.5),
                                     xycoords=header_ax.transAxes, frameon=False)
            header_ax.add_artist(ab_logo)
        except Exception:
            pass

    # Navy accent line
    header_ax.axhline(y=0.02, xmin=0.01, xmax=0.99, color=NAVY, linewidth=3)

    # ===================================================================
    # ROW 1: SUMMARY STATS BAR
    # ===================================================================
    summary_ax = fig.add_subplot(outer[1])
    summary_labels = ["Called Pitches", "Called Strk%", "Shadow Strk%", "Chase Strk%",
                      "Heart Strk%", "Waste Strk%", "Ball%", "FPS Called%"]
    summary_values = [
        str(total_called),
        safe_fmt(overall_strk, ".1f") + "%",
        safe_fmt(shadow_strk, ".1f") + "%",
        safe_fmt(chase_strk, ".1f") + "%",
        safe_fmt(heart_strk, ".1f") + "%",
        safe_fmt(waste_strk, ".1f") + "%",
        safe_fmt(overall_ball, ".1f") + "%",
        safe_fmt(fps_rate, ".1f") + "%",
    ]

    summary_ax.set_xlim(0, 1)
    summary_ax.set_ylim(0, 1)
    summary_ax.axis("off")

    n_summary = len(summary_labels)
    sw = 1.0 / n_summary
    for i, (lbl, val) in enumerate(zip(summary_labels, summary_values)):
        x_center = sw * i + sw / 2
        bg_color = NAVY if i % 2 == 0 else "#2a2a4e"
        rect = mpatches.FancyBboxPatch((sw * i, 0.05), sw, 0.90,
                                        boxstyle="square,pad=0", facecolor=bg_color,
                                        edgecolor=NAVY, linewidth=0.5)
        summary_ax.add_patch(rect)
        summary_ax.text(x_center, 0.65, val, ha="center", va="center",
                        fontsize=16, fontweight="bold", color=WHITE)
        summary_ax.text(x_center, 0.28, lbl, ha="center", va="center",
                        fontsize=9, color="#aaaacc")

    # ===================================================================
    # ROW 2: THREE ZONE HEATMAPS
    # ===================================================================
    heatmaps = gridspec.GridSpecFromSubplotSpec(1, 3, subplot_spec=outer[2], wspace=0.30)

    ax_strk_hm = fig.add_subplot(heatmaps[0, 0])
    plot_called_strike_heatmap(ax_strk_hm, called_df)

    ax_vol_hm = fig.add_subplot(heatmaps[0, 1])
    plot_volume_heatmap(ax_vol_hm, called_df)

    ax_border_hm = fig.add_subplot(heatmaps[0, 2])
    plot_borderline_heatmap(ax_border_hm, called_df)

    # ===================================================================
    # ROW 3: ATTACK ZONE TABLE + COUNT SITUATION TABLE
    # ===================================================================
    row3 = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=outer[3],
                                            wspace=0.15, width_ratios=[1.0, 1.2])

    # --- Attack Zone Performance ---
    ax_atz = fig.add_subplot(row3[0, 0])
    atz_cols = ["Zone", "Called N", "Called Strk%", "Ball%", "Lg Avg Strk%"]
    atz_rows = []
    atz_cell_colors = []
    zone_order = ["Heart", "Shadow", "Chase", "Waste"]
    zone_bg_map = {"Heart": "#ffcdd2", "Shadow": "#fff9c4", "Chase": "#c8e6c9", "Waste": "#e3f2fd"}
    league_zone_strk = {"Heart": league_heart_strk, "Shadow": league_shadow_strk,
                        "Chase": league_chase_strk, "Waste": league_waste_strk}

    for z in zone_order:
        zdf = called_df[called_df["AttackZone"] == z]
        n = len(zdf)
        cs = called_strk_pct(zdf)
        bp = called_ball_pct(zdf)
        la = league_zone_strk[z]
        atz_rows.append([z, str(n), safe_fmt(cs, ".1f") + "%",
                         safe_fmt(bp, ".1f") + "%", safe_fmt(la, ".1f") + "%"])
        row_bg = zone_bg_map.get(z, WHITE)
        atz_cell_colors.append([row_bg] * 5)

    atz_w = [0.18, 0.18, 0.22, 0.18, 0.24]
    tw = sum(atz_w)
    atz_w = [w / tw for w in atz_w]
    draw_table(ax_atz, atz_cols, atz_rows, col_widths=atz_w,
               cell_colors=atz_cell_colors, font_size=11, header_font_size=11,
               title="Attack Zone Performance", title_size=14)

    # --- Count Situation Table ---
    ax_count = fig.add_subplot(row3[0, 1])
    count_groups = {
        "Ahead":  ["0-1", "0-2", "1-2"],
        "Behind": ["1-0", "2-0", "2-1", "3-0", "3-1"],
        "Even":   ["0-0", "1-1", "2-2"],
        "Full":   ["3-2"],
    }
    group_colors = {
        "Ahead": "#c8e6c9",
        "Behind": "#ffcdd2",
        "Even": "#e3f2fd",
        "Full": "#fff9c4",
    }

    called_valid = called_df.dropna(subset=["Balls", "Strikes"]).copy()
    called_valid["Count"] = (called_valid["Balls"].astype(int).astype(str) + "-" +
                              called_valid["Strikes"].astype(int).astype(str))

    cnt_cols = ["Situation", "Called N", "Called Strk%", "Ball%"]
    cnt_rows = []
    cnt_cell_colors = []

    for group_name, counts in count_groups.items():
        grp = called_valid[called_valid["Count"].isin(counts)]
        n_g = len(grp)
        if n_g == 0:
            cnt_rows.append([group_name, "0", "-", "-"])
            cnt_cell_colors.append([group_colors.get(group_name, WHITE)] * 4)
            continue
        cs = called_strk_pct(grp)
        bp = called_ball_pct(grp)
        cnt_rows.append([group_name, str(n_g), safe_fmt(cs, ".1f") + "%",
                         safe_fmt(bp, ".1f") + "%"])
        bg = group_colors.get(group_name, WHITE)
        cc = [bg] * 4
        cc[2] = color_for_metric(cs, CALLED_STRK_COLORS)
        cnt_cell_colors.append(cc)

    cnt_w = [0.25, 0.20, 0.28, 0.27]
    tw = sum(cnt_w)
    cnt_w = [w / tw for w in cnt_w]
    draw_table(ax_count, cnt_cols, cnt_rows, col_widths=cnt_w,
               cell_colors=cnt_cell_colors, font_size=11, header_font_size=11,
               title="Count Situation Calls", title_size=14)

    # ===================================================================
    # ROW 4: GAME-BY-GAME TABLE
    # ===================================================================
    ax_games = fig.add_subplot(outer[4])
    game_cols = ["Date", "Teams", "Called N", "Called Strk%", "Shadow Strk%",
                 "Chase Strk%", "Ball%"]

    game_cell_colors = []
    for row in game_rows:
        cc = [None] * 7
        # Color-code Called Strk% (index 3)
        try:
            val = float(row[3].replace("%", ""))
            cc[3] = color_for_metric(val, CALLED_STRK_COLORS)
        except (ValueError, TypeError):
            pass
        game_cell_colors.append(cc)

    game_w = [0.10, 0.28, 0.10, 0.14, 0.14, 0.14, 0.10]
    tw = sum(game_w)
    game_w = [w / tw for w in game_w]
    draw_table(ax_games, game_cols, game_rows, col_widths=game_w,
               cell_colors=game_cell_colors, font_size=10, header_font_size=11,
               title="Game-by-Game Breakdown", title_size=14)

    # ===================================================================
    # ROW 5: KEY TENDENCIES
    # ===================================================================
    ax_tend = fig.add_subplot(outer[5])
    ax_tend.set_xlim(0, 1)
    ax_tend.set_ylim(0, 1)
    ax_tend.axis("off")

    # Title
    ax_tend.text(0.5, 0.95, "Key Tendencies", ha="center", va="top",
                 fontsize=16, fontweight="bold", color=NAVY)

    bullets = generate_tendencies(called_df, league_called_strk, league_shadow_strk,
                                  game_strk_rates)

    # Draw rounded background box
    ax_tend.add_patch(mpatches.FancyBboxPatch(
        (0.02, 0.02), 0.96, 0.85, boxstyle="round,pad=0.02",
        facecolor=LIGHT_BG, edgecolor=GREY_LINE, linewidth=1.5,
        transform=ax_tend.transAxes
    ))

    y_pos = 0.82
    for bullet in bullets:
        ax_tend.text(0.05, y_pos, f"\u2022  {bullet}", transform=ax_tend.transAxes,
                     fontsize=11, color="#212529", va="top", wrap=True,
                     fontfamily="sans-serif",
                     bbox=dict(facecolor="none", edgecolor="none", pad=0))
        y_pos -= 0.20

    # ===================================================================
    # ROW 6: FOOTER
    # ===================================================================
    footer_ax = fig.add_subplot(outer[6])
    footer_ax.set_xlim(0, 1)
    footer_ax.set_ylim(0, 1)
    footer_ax.axis("off")

    footer_ax.axhline(y=0.85, xmin=0.01, xmax=0.99, color=NAVY, linewidth=2)
    footer_ax.text(0.02, 0.40, "Moeller Baseball Analytics", fontsize=12,
                   fontweight="bold", color=NAVY, va="center")
    footer_ax.text(0.50, 0.40, f"Generated {pd.Timestamp.now().strftime('%B %d, %Y')}",
                   fontsize=11, color="#888888", va="center", ha="center")
    footer_ax.text(0.98, 0.40, "@MoeAnalytics", fontsize=12, fontweight="bold",
                   color=NAVY, va="center", ha="right")

    # ===================================================================
    # SAVE
    # ===================================================================
    safe_name = umpire_name.replace(" ", "_")
    filename = f"Umpire_{safe_name}.png"
    filepath = OUTPUT_DIR / filename
    fig.savefig(filepath, dpi=150, bbox_inches="tight", facecolor=WHITE,
                edgecolor="none", pad_inches=0.3)
    plt.close(fig)
    print(f"  Saved: {filepath}")
    return filepath


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Moeller Umpire Scouting Card Generator")
    parser.add_argument("--umpire", type=str, help="Umpire name (as in data)")
    parser.add_argument("--all", action="store_true",
                        help="Generate cards for ALL umpires in the dataset")
    args = parser.parse_args()

    if not args.umpire and not args.all:
        parser.error("Must specify --umpire or --all")

    print("Loading data...")
    df = load_data()
    print(f"  Loaded {len(df)} total rows")

    # Filter to rows that have an umpire listed
    df_with_ump = df[df["Umpire"].notna() & (df["Umpire"].str.strip() != "")].copy()
    df_with_ump["Umpire"] = df_with_ump["Umpire"].str.strip()
    print(f"  {len(df_with_ump)} rows have an umpire assigned")

    # All called pitches (league-wide) for comparison
    all_called_df = get_called_pitches(df_with_ump)
    print(f"  {len(all_called_df)} total called pitches (Strike Looking + Ball) across all umpires")

    if args.all:
        umpires = sorted(df_with_ump["Umpire"].unique())
        print(f"  Found {len(umpires)} umpires")
        for ump in umpires:
            ump_df = df_with_ump[df_with_ump["Umpire"] == ump]
            ump_called = get_called_pitches(ump_df)
            if len(ump_called) < 10:
                print(f"  Skipping {ump} (only {len(ump_called)} called pitches)")
                continue
            print(f"Generating: {ump} ({len(ump_called)} called pitches, "
                  f"{ump_df['Date'].dt.date.nunique()} games)")
            try:
                generate_card(ump, ump_df, all_called_df)
            except Exception as e:
                print(f"  ERROR: {e}")
    else:
        umpire = args.umpire
        ump_df = df_with_ump[df_with_ump["Umpire"] == umpire]
        if len(ump_df) == 0:
            # Try case-insensitive match
            match = df_with_ump[df_with_ump["Umpire"].str.lower() == umpire.lower()]
            if len(match) > 0:
                umpire = match.iloc[0]["Umpire"]
                ump_df = match
            else:
                print(f"Umpire '{umpire}' not found. Available umpires:")
                for u in sorted(df_with_ump["Umpire"].unique()):
                    print(f"  {u}")
                sys.exit(1)

        ump_called = get_called_pitches(ump_df)
        print(f"  {umpire}: {len(ump_called)} called pitches, "
              f"{ump_df['Date'].dt.date.nunique()} games")
        generate_card(umpire, ump_df, all_called_df)

    print("\nDone!")


if __name__ == "__main__":
    main()
