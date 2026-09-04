"""Four-step configuration wizard.
Step 1 - Site location    : ipyleaflet map centered on Geneva; draw a polygon
                            roughly the size of the building cluster to model.
Step 2 - Site & buildings : building-type list + per-type form, KPIs and
                            aggregated totals with hourly profile charts.
                            Every building type's demand comes from the
                            Sympheny API (use type -> building_type,
                            GFA -> building_ground_area). All building x
                            carrier requests run in one parallel batch.
Step 3 - System variants  : side-by-side energy-system variants, each a set
                            of selectable technologies.
Step 4 - Summary          : styled read-only recap, then Submit creates one
                            Sympheny scenario per variant — hub, stage,
                            technology package, then the aggregated 8760 h
                            demands on the carriers the technologies already
                            brought in — and prints the first scenario URL.

Layout of this file: UI first (theme, constants, widgets, wizard shell),
then every backend call and backend-side computation under the
"## BACKEND API CALLS" banner at the bottom.
"""
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import requests as r
import plotly.graph_objects as go
from IPython.core.display_functions import display
from ipyleaflet import Map, DrawControl, GeoJSON, basemaps
from ipystream.voila import utils_log
from ipystream.voila.kernel import get_token
from ipywidgets import widgets, HTML
from ipystream.renderer import plotly_fig_to_html
from ipystream.voila.spinned_print_out import get_spinner_html, Spinned
from ipystream.voila.utils_tdqm import tqdm_out
from ipystream.voila.utils_browser_ready import on_browser_ready

from utils_login import get_creds_from_token

CONTENT_MIN_PX = 560          # min height of the content area
CHART_PREVIEW_PX = 120        # per-building-type profile preview
CHART_PREVIEW_W = 470
CHART_COMBINED_PX = 150       # aggregated combined profile
CHART_SOLAR_PX = 175          # solar profile, shown in step 1
STEP_DEFS = [
    ("1", "Site location"),
    ("2", "Site & buildings"),
    ("3", "System variants"),
    ("4", "Summary"),
]
NAVY = "#1b2534"
TEAL = "#0f9d8f"
INK = "#1f2933"
MUTED = "#8a94a0"
LINE = "#e3e8ee"

WZ_CSS = f"""
<style>
.wz-nav{{background:{NAVY} !important;border-radius:10px;padding:0 14px;height:56px;display:flex;align-items:center;gap:4px;font-family:sans-serif;margin:0 0 14px}}
.wz-nav *{{font-family:sans-serif}}
.wz-nav .crumb{{display:flex;align-items:center;gap:9px;padding:7px 14px;font-size:14px !important;border-radius:20px;letter-spacing:.01em;color:#dbe3ec !important}}
.wz-nav .crumb.active{{color:#ffffff !important;font-weight:700 !important;background:rgba(255,255,255,.14)}}
.wz-nav .crumb.done{{color:#f0f4f8 !important;font-weight:500 !important}}
.wz-nav .dot{{width:24px;height:24px;border-radius:50%;font-size:12px !important;font-weight:700 !important;display:flex;align-items:center;justify-content:center;background:#5a6a7e !important;color:#ffffff !important;flex:0 0 24px}}
.wz-nav .crumb.active .dot{{background:{TEAL} !important;color:#fff !important;box-shadow:0 0 0 3px {TEAL}55}}
.wz-nav .crumb.done .dot{{background:{TEAL} !important;color:#fff !important}}
.wz-nav .sep{{color:#9aa7b8 !important;font-size:13px;padding:0 2px}}
.wz-title{{font-size:15px;font-weight:600;color:{INK};margin:0 0 8px;font-family:sans-serif}}
.wz-caption{{font-size:11px;color:{MUTED};margin:1px 0 6px 2px;font-family:sans-serif}}
.wz-label{{font-size:11px;color:#4a5568;margin:0 0 3px 2px;font-family:sans-serif}}
.wz-kpi{{border:1px solid {LINE};border-radius:10px;padding:8px 14px;min-width:118px;background:#fff;font-family:monospace}}
.wz-kpi .lab{{font-size:10px;letter-spacing:.08em;text-transform:uppercase}}
.wz-kpi .val{{font-size:21px;font-weight:700;color:{INK};line-height:1.25}}
.wz-kpi .sub{{font-size:10px;color:{MUTED}}}
.wz-row{{display:flex;gap:10px;flex-wrap:wrap;margin:2px 0}}
.wz-band{{background:#f3faf9;border:1px solid #d9ece9;border-radius:10px;padding:10px 14px;margin:6px 0 4px}}
.wz-band h4{{margin:0 0 7px;font-size:11px;letter-spacing:.1em;color:#0b5f57;text-transform:uppercase;font-family:monospace}}
.wz-side{{border:1px solid {LINE};border-radius:10px;padding:8px 12px;background:#fafbfc}}
.wz-tot{{font-size:12px;font-family:monospace;line-height:1.8}}
.wz-tot span{{float:right;font-weight:700}}
.wz-cat{{font-size:10px;letter-spacing:.1em;color:{MUTED};text-transform:uppercase;margin:9px 0 3px;font-family:monospace}}
.wz-sub{{font-size:11px;color:{MUTED};margin:-6px 0 5px 26px;font-family:sans-serif}}
.wz-sum{{border:1px solid {LINE};border-radius:12px;padding:14px 18px;background:#fff;margin:0 0 12px;font-family:sans-serif}}
.wz-sum h3{{margin:0 0 8px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#0b5f57}}
.wz-sum table{{border-collapse:collapse;width:100%;font-size:13px}}
.wz-sum td{{padding:5px 8px;border-bottom:1px solid #f0f2f5;vertical-align:top}}
.wz-sum td.k{{color:{MUTED};width:190px}}
.wz-sum td.v{{color:{INK};font-weight:600}}
.wz-chip{{display:inline-block;padding:2px 9px;border-radius:11px;font-size:11px;font-weight:600;margin:2px 6px 2px 0}}
.wz-tag{{display:inline-block;padding:1px 8px;border-radius:10px;font-size:10px;font-weight:700;letter-spacing:.06em;font-family:monospace;vertical-align:middle}}
.wz-tag.err{{background:#fdecec;color:#b3312c !important;border:1px solid #f4c9c7}}
@keyframes wz-spin{{to{{transform:rotate(360deg)}}}}
.wz-loader{{display:flex;align-items:center;justify-content:center;gap:10px;border:1px dashed {LINE};border-radius:10px;background:#fcfdfe;font-family:sans-serif;font-size:11px;color:{MUTED} !important}}
.wz-loader .ring{{width:20px;height:20px;border-radius:50%;border:2.5px solid #e3e8ee;border-top-color:{TEAL};animation:wz-spin .8s linear infinite;flex:0 0 20px}}
.wz-err{{border:1px solid #f4c9c7;background:#fdecec;border-radius:10px;padding:8px 12px;font-family:monospace;font-size:11px;color:#b3312c !important;margin:4px 0}}
.widget-text input[type="text"],.widget-text input[type="number"],.widget-dropdown > select{{border:1px solid #d7dde5 !important;border-radius:8px !important;height:32px !important;padding:2px 10px !important;font-size:13px !important;color:{INK} !important;background:#fff !important;box-shadow:none !important;}}
.widget-text input:focus,.widget-dropdown > select:focus{{border-color:{TEAL} !important;outline:none !important;box-shadow:0 0 0 2px {TEAL}22 !important;}}
.widget-label{{font-size:12px !important;color:#4a5568 !important}}
.widget-checkbox input[type="checkbox"]{{accent-color:{TEAL};width:15px;height:15px;margin-right:6px}}
.widget-checkbox label{{font-size:13px !important;color:{INK} !important}}
button.jupyter-button{{border-radius:8px !important;box-shadow:none !important;font-family:sans-serif !important;font-size:13px !important;border:1px solid #d7dde5 !important;}}
button.jupyter-button:hover{{filter:brightness(.97)}}
.wz-pill button.jupyter-button,button.jupyter-button.wz-pill{{border-radius:20px !important;font-weight:600 !important;height:36px !important;}}
button.jupyter-button.wz-primary{{background:{TEAL} !important;color:#fff !important;border:1px solid {TEAL} !important;}}
button.jupyter-button.wz-ghost{{background:#fff !important;color:{INK} !important;}}
button.jupyter-button.wz-chipbtn{{height:30px !important;border-radius:7px !important;font-family:monospace !important;}}
button.jupyter-button.wz-listitem{{border-radius:9px !important;justify-content:flex-start !important;text-align:left !important;font-size:13px !important;}}
.wz-footer{{border-top:1px solid {LINE};margin-top:8px;padding-top:10px}}
/* Voila ships `label,div,span,p,li,th,td,pre{{color:black!important}}` --these win it back for the wizard's own markup. */.wz-title{{color:{INK} !important}}
.wz-caption,.wz-sub,.wz-cat,.wz-kpi .sub,.wz-sum td.k{{color:{MUTED} !important}}
.wz-label{{color:#4a5568 !important}}
.wz-kpi .val,.wz-sum td.v{{color:{INK} !important}}
.wz-band h4{{color:#0b5f57 !important}}
.wz-sum h3{{color:#0b5f57 !important}}
.wz-tot{{color:{INK} !important}}
.wz-tech-name{{font-size:13px;font-weight:600;color:{INK} !important;font-family:sans-serif;line-height:1.25}}
.wz-tech-sub{{font-size:11px;color:{MUTED} !important;font-family:sans-serif}}
button.jupyter-button.wz-addtech{{border:1px dashed #cbd3dd !important;background:#fff !important;color:{MUTED} !important;border-radius:10px !important;font-size:12px !important;}}
button.jupyter-button.wz-addtech:hover{{border-color:{TEAL} !important;color:{TEAL} !important}}
button.jupyter-button.wz-x{{background:transparent !important;border:none !important;color:{MUTED} !important;font-size:14px !important;border-radius:50% !important;}}
button.jupyter-button.wz-x:hover{{background:#f2f4f7 !important;color:#e0524d !important}}
button.jupyter-button.wz-pick{{border:1px solid {LINE} !important;background:#fff !important;border-radius:10px !important;justify-content:flex-start !important;text-align:left !important;font-size:13px !important;color:{INK} !important;}}
button.jupyter-button.wz-pick:hover{{border-color:{TEAL} !important;background:#f3faf9 !important}}
.wz-modal{{position:fixed !important;top:0;left:0;right:0;bottom:0;background:rgba(17,25,36,.45);z-index:9999;align-items:center !important;justify-content:center !important;}}
.wz-modal-card{{background:#fff !important;border-radius:14px !important;padding:18px 20px !important;width:520px !important;max-height:74vh !important;overflow:auto !important;box-shadow:0 18px 50px rgba(0,0,0,.28) !important;}}
.wz-modal-title{{font-size:15px;font-weight:700;color:{INK} !important;font-family:sans-serif;margin:0 0 2px}}
</style>
"""

# --------------------------------------------------------------- domain data
CARRIERS = [ ("Heat", "#e0524d"), ("Elec", "#1fab8c"), ("DHW", "#f2a93b"), ]
CARRIER_COLOR = dict(CARRIERS)
SOLAR_COLOR = "#f5a623"       # accent used for the solar-profile bars & sun icon
SOLAR_COLOR_LINE = "#d98d12"  # slightly darker border on the same bars

# Sympheny `building_type` enum values, shown as-is in the dropdown.
USE_TYPES = [
    "RESIDENCE_MFH", "RESIDENCE_SFH", "ADMINISTRATION", "OFFICES", "SCHOOLS",
    "RETAIL", "RESTAURANT", "ASSEMBLY", "HOSPITALS", "INDUSTRY", "WAREHOUSE",
    "SPORTS_CENTER", "INDOOR_POOL", "HOTEL",
]
PERIODS = ["< 1950", "1950–1970", "1970–1990", "1990–2000", "2000–2010", "> 2010"]
CLIMATE_ZONES = ["Zürich, CH", "Genève, CH", "Basel, CH", "Lugano, CH", "Lyon, FR", "Milano, IT", "München, DE"]
# EPC class is descriptive metadata only — the demand comes from the API.
EPC_CLASSES = ["A", "B", "C", "D", "E", "F", "G"]
EPC_COLOR = {"A": "#2e9e4f", "B": "#6cb33f", "C": "#b7cf2b", "D": "#ef7215", "E": "#e8546a", "F": "#b45ad0", "G": "#8a94a0"}
DEFAULT_BUILDINGS = [
    {"name": "Residential MFH", "use": "RESIDENCE_MFH", "period": "1990–2000", "renovated": "No", "gfa": 23460.0, "zone": "Zürich, CH", "diversity": 8.0, "epc": "D"},
    {"name": "Offices", "use": "OFFICES", "period": "2000–2010", "renovated": "Yes", "gfa": 4800.0, "zone": "Zürich, CH", "diversity": 12.0, "epc": "C"},
    {"name": "Retail", "use": "RETAIL", "period": "1970–1990", "renovated": "No", "gfa": 1200.0, "zone": "Zürich, CH", "diversity": 15.0, "epc": "E"},
]

TECH_CATALOG = {
    "Heat supply": [
        ("Gas boiler", "η 92% · gas import · CH grid tariff", "🔥"),
        ("Air-source heat pump", "COP 3.0 · elec import", "💧"),
        ("Ground-source HP", "COP 4.5 · borehole", "🌡️"),
        ("Wood pellet boiler", "η 88% · pellet price CH", "🪵"),
    ],
    "Electricity & renewables": [
        ("Solar PV", "Roof area from GIS", "☀️"),
        ("CHP unit", "Gas engine · heat-led", "⚙️"),
    ],
}
TECH_INDEX = {name: (cat, sub, icon) for cat, items in TECH_CATALOG.items() for name, sub, icon in items}
VARIANT_COLORS = [TEAL, "#1a6fc4", "#e0952b", "#9c1a6f", "#5a4fcf"]
DEFAULT_VARIANTS = [
    {"name": "Heat pump + Solar PV", "techs": ["Air-source heat pump", "Solar PV", "Gas boiler"]},
    {"name": "Status quo / Gas boiler", "techs": ["Gas boiler"]},
    {"name": "District heating + PV", "techs": ["Solar PV"]},
]

# Geneva city center — fallback map view for the site-selection step.
GENEVA_CENTER = (46.2044, 6.1432)

# Default site outline, pre-drawn on load. Given as [lat, lon] pairs (as
# supplied); stored/consumed elsewhere as [lon, lat] (GeoJSON order).
DEFAULT_POLYGON_LATLON = [[46.238324, 6.206312], [46.238034, 6.206817], [46.238348, 6.20709], [46.238604, 6.20665], [46.238324, 6.206312]]
DEFAULT_POLYGON_LONLAT = [[lon, lat] for lat, lon in DEFAULT_POLYGON_LATLON]
# Map opens centered on the default polygon's centroid rather than Geneva
# city center, so the outline is visible immediately.
_lats = [lat for lat, _lon in DEFAULT_POLYGON_LATLON]
_lons = [lon for _lat, lon in DEFAULT_POLYGON_LATLON]
DEFAULT_MAP_CENTER = (sum(_lats) / len(_lats), sum(_lons) / len(_lons))


# ----------------------------------------------------------------- UI pieces
def _loader(label: str, height: int, width=None) -> HTML:
    """Spinning placeholder shown where a chart is about to appear."""
    w = f"width:{width}px;" if width else "width:100%;"
    return HTML(WZ_CSS + f"<div class='wz-loader' style='{w}height:{height}px'>"
                         f"<div class='ring'></div><span>{label}</span></div>")


def _error_box(msg: str, height: int, width=None) -> HTML:
    w = f"width:{width}px;" if width else "width:100%;"
    return HTML(WZ_CSS + f"<div class='wz-err' style='{w}min-height:{height}px;"
                         f"display:flex;align-items:center'>⚠ {msg}</div>")


def _loading_html(label: str = "Loading…", big: bool = False) -> HTML:
    if big:
        box = ( "width:420px;height:88px;border:none;background:transparent;" "gap:16px" )
        ring = "width:32px;height:32px;border-width:3.5px;flex:0 0 32px"
        text = ( f"font-size:15px;font-weight:700;letter-spacing:.04em;" f"color:{INK} !important" )
    else:
        box = "width:260px;height:64px;border:none;background:transparent"
        ring = ""
        text = ""
    ring_div = f"<div class='ring' style='{ring}'></div>" if ring else "<div class='ring'></div>"
    span = f"<span style='{text}'>{label}</span>" if text else f"<span>{label}</span>"
    return HTML(
        WZ_CSS +
        f"<div style='min-height:{CONTENT_MIN_PX}px;display:flex;align-items:center;"
        f"justify-content:center'>"
        f"<div class='wz-loader' style='{box}'>{ring_div}{span}</div></div>"
    )


def _profile_fig(curves: dict, title: str, height: int, width=None) -> go.Figure:
    """`curves` maps a carrier to its 24 hourly values in kW (daily average)."""
    hours = list(range(24))
    fig = go.Figure()
    for name, color in CARRIERS:
        y = curves.get(name) or []
        if not y or max(y) <= 0:
            continue
        fig.add_trace(go.Bar( x=hours, y=[round(v, 2) for v in y], name=name, marker_color=color, hovertemplate=f"{name} · %{{x}}h · %{{y}} kW<extra></extra>", ))
    layout = dict(
        title=dict(text=title, font=dict(size=11), x=0, y=0.97) if title else None,
        barmode="group", height=height,
        margin=dict(l=40, r=8, t=26 if title else 8, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.0,
                    xanchor="left", x=0.34, font=dict(size=10)),
        xaxis=dict(showticklabels=False, title="", showgrid=False),
        yaxis=dict(title="", showgrid=False, ticksuffix=" kW",
                   tickfont=dict(size=9)),
        plot_bgcolor="white", paper_bgcolor="white",
        bargap=0.15, bargroupgap=0.05,
    )
    if width:
        layout["width"] = width
    fig.update_layout(**layout)
    return fig


def _solar_fig(avg24: list, height: int) -> go.Figure:
    """`avg24` is the site-total solar profile's 24 hourly values (daily
    average of the 8760 h series)."""
    hours = list(range(24))
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=hours, y=[round(v, 3) for v in avg24], name="Solar",
        marker=dict(color=SOLAR_COLOR, line=dict(color=SOLAR_COLOR_LINE, width=0.6)),
        hovertemplate="%{x}:00 · %{y}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(
            # Sun is inline in the title, and the title's own font.size is
            # what makes it big. An inline <span> LARGER than the base font
            # gets clipped (Plotly sizes the title box from font.size), so
            # the glyph rides the base size and the text is shrunk back
            # down with spans instead — spans smaller than the base are
            # fine. Keeping it inline also means it flows with the text
            # rather than needing its own x/y, which is what made a
            # separate annotation overlap the title.
            # "☀" (U+2600) not the "☀️" emoji: without the variation
            # selector browsers render a plain glyph, so the span's color
            # applies instead of a built-in color emoji overriding it.
            text=(f"<span style='color:{SOLAR_COLOR}'>&#9728;</span>"
                  f"<span style='font-size:17px;color:{INK}'>"
                  f"&nbsp;&nbsp;Solar profile — site total</span>"
                  f"<span style='color:{MUTED};font-weight:400;font-size:13px'>"
                  f"&nbsp;&nbsp;daily avg of 8760 h</span>"),
            font=dict(size=30, color=INK), x=0, xanchor="left", y=0.97,
        ),
        height=height, showlegend=False,
        margin=dict(l=42, r=10, t=52, b=32),
        xaxis=dict(
            tickmode="array",
            tickvals=[0, 4, 8, 12, 16, 20],
            ticktext=["0h", "4h", "8h", "12h", "16h", "20h"],
            showgrid=False, tickfont=dict(size=10, color=MUTED),
            title=dict(text="Hour of day", font=dict(size=10, color=MUTED)),
        ),
        yaxis=dict(title="", showgrid=True, gridcolor=LINE, gridwidth=1,
                   zeroline=False, tickfont=dict(size=9, color=MUTED)),
        plot_bgcolor="white", paper_bgcolor="white", bargap=0.25,
    )
    return fig


def _kpi(label: str, value: str, sub: str, color: str) -> str:
    return (f"<div class='wz-kpi'><div class='lab' style='color:{color} !important'>{label}</div>" f"<div class='val'>{value}</div><div class='sub'>{sub}</div></div>")


def _render_nav_html(active: int) -> str:
    """Nav bar with inline styles so no host stylesheet can dim the labels."""
    bar = (f"background:{NAVY};border-radius:10px;padding:0 14px;height:56px;" f"display:flex;align-items:center;gap:4px;font-family:sans-serif;" f"margin:0 0 14px")
    parts = []
    for i, (num, label) in enumerate(STEP_DEFS):
        if i == active:
            txt, weight, bg = "#ffffff", 700, "rgba(255,255,255,.14)"
            dot_bg, shadow = TEAL, f"box-shadow:0 0 0 3px {TEAL}55;"
        elif i < active:
            txt, weight, bg = "#f0f4f8", 500, "transparent"
            dot_bg, shadow = TEAL, ""
        else:
            txt, weight, bg = "#dbe3ec", 500, "transparent"
            dot_bg, shadow = "#5a6a7e", ""
        crumb = (f"display:flex;align-items:center;gap:9px;padding:7px 14px;"
                 f"font-size:14px;border-radius:20px;color:{txt} !important;"
                 f"font-weight:{weight};background:{bg};font-family:sans-serif")
        dot = (f"width:24px;height:24px;border-radius:50%;font-size:12px;"
               f"font-weight:700;display:flex;align-items:center;"
               f"justify-content:center;background:{dot_bg};color:#ffffff !important;"
               f"flex:0 0 24px;{shadow}")
        mark = "\u2713" if i < active else num
        parts.append(f"<div class='crumb' style='{crumb}'>" f"<div style='{dot}'>{mark}</div>" f"<span style='color:{txt} !important'>{label}</span></div>")
        if i < len(STEP_DEFS) - 1:
            parts.append("<div style='color:#9aa7b8 !important;font-size:13px;padding:0 2px'>"
                         "\u25b8</div>")
    return WZ_CSS + f"<div class='wz-nav' style='{bar}'>{''.join(parts)}</div>"


# ------------------------------------------------------- step 1: site location
def _polygon_area_m2(coords, center_lat: float) -> float:
    """Shoelace formula on a local equirectangular projection.

    `coords` is a list of [lon, lat] pairs (GeoJSON order). This is accurate
    to a fraction of a percent for a few-hundred-meter footprint at a given
    latitude — fine for a "roughly several buildings" sanity check, not for
    cadastral purposes.
    """
    if not coords or len(coords) < 3:
        return 0.0
    lat0 = math.radians(center_lat)
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(lat0)
    pts = [(lon * m_per_deg_lon, lat * m_per_deg_lat) for lon, lat in coords]
    area = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _build_step_location(site: dict, vbox: widgets.VBox, spinner_html,
                         on_gis_loaded=None) -> tuple:
    """Draw-a-polygon map, centered on Geneva, sized for a handful of buildings.

    `site` is a plain dict the wizard shell owns; this function mutates
    `site["polygon"]` (list of [lon, lat] pairs, or None) as the user draws,
    `site["gis"]` (the raw GIS response, once loaded) after the "Load GIS
    data" button runs, and `site["gis_scenario_guid"]` (the Sympheny
    scenario the GIS data was fetched into) alongside it — step 4 uses the
    latter to copy that same GIS layer onto every variant scenario.

    `vbox` / `spinner_html` are the shell's shared Spinned() output area —
    the same ones used by the Submit button in step 4 — so the GIS fetch
    gets the same in-place progress/spinner treatment.

    `on_gis_loaded`, if given, is called (no args) right after a successful
    GIS fetch — the shell uses it to invalidate step 2's cached panel so the
    building list rebuilds from the newly-fetched addresses next visit.
    """
    gis_layer_holder = {"layer": None}
    # The polygon outline is rendered as our own plain map layer (below),
    # not through the draw control's own display — see _show_site_polygon.
    site_layer_holder = {"layer": None}

    m = Map(
        center=DEFAULT_MAP_CENTER, zoom=18,
        basemap=basemaps.OpenStreetMap.Mapnik,
        layout=widgets.Layout(width="100%", height="480px", border=f"1px solid {LINE}"),
        scroll_wheel_zoom=True,
    )
    # Solar profile for the site — populated once GIS data is loaded, sits
    # between the map and the button row (see `panel` at the end of this
    # function). Cleared alongside the GIS building layer since it's
    # derived from the same fetch.
    solar_box = widgets.VBox()

    draw_control = DrawControl(
        polygon={"shapeOptions": {"color": TEAL, "fillColor": TEAL, "fillOpacity": 0.25}},
        polyline={}, circlemarker={}, rectangle={}, circle={}, marker={},
        edit=True, remove=True,
    )
    m.add_control(draw_control)

    def _refresh_readout():
        """No visual readout is shown for step 1 anymore; kept as a no-op
        hook since the wizard shell calls this each time the step is shown."""
        pass

    def _clear_building_layer():
        """Drop any previously loaded GIS building layer — used when the
        outline changes so stale buildings from an old polygon don't linger."""
        if gis_layer_holder["layer"] is not None:
            try:
                m.remove_layer(gis_layer_holder["layer"])
            except Exception:
                pass
            gis_layer_holder["layer"] = None
        site["gis"] = None
        site["gis_scenario_guid"] = None
        site["solar_series"] = None
        site["solar_area"] = None
        solar_box.children = []

    def _show_building_layer(features: list):
        _clear_building_layer_only()
        if not features:
            return
        layer = GeoJSON(
            data={"type": "FeatureCollection", "features": features},
            style={"color": "#1a6fc4", "weight": 1, "fillColor": "#1a6fc4", "fillOpacity": 0.35},
            hover_style={"fillOpacity": 0.65},
        )
        m.add_layer(layer)
        gis_layer_holder["layer"] = layer

    def _clear_building_layer_only():
        """Like `_clear_building_layer` but doesn't touch `site["gis"]` or
        the status line — used right before drawing a freshly-fetched layer."""
        if gis_layer_holder["layer"] is not None:
            try:
                m.remove_layer(gis_layer_holder["layer"])
            except Exception:
                pass
            gis_layer_holder["layer"] = None

    def _clear_site_polygon():
        """Remove the currently-shown outline layer, if any."""
        if site_layer_holder["layer"] is not None:
            try:
                m.remove_layer(site_layer_holder["layer"])
            except Exception:
                pass
            site_layer_holder["layer"] = None

    def _show_site_polygon(coords_lonlat):
        """Render the site outline as a plain map layer that we add/remove
        ourselves — the same pattern `_show_building_layer` already uses
        successfully for the GIS footprints below.

        The draw control's *own* rendering of a finished/edited shape lives
        entirely on the frontend and, once the widget is already on screen,
        isn't reliably controllable by re-assigning `draw_control.data`
        from Python (that only works for the very first shape, set before
        the map is ever displayed). Managing our own `GeoJSON` layer here —
        clearing it and adding a fresh one every time — sidesteps that
        entirely, so exactly one outline is ever visible.
        """
        _clear_site_polygon()
        if not coords_lonlat:
            return
        ring = list(coords_lonlat)
        if ring[0] != ring[-1]:
            ring = ring + [ring[0]]  # GeoJSON polygons must be closed rings
        layer = GeoJSON(
            data={
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            },
            style={"color": TEAL, "weight": 2, "fillColor": TEAL, "fillOpacity": 0.25},
        )
        m.add_layer(layer)
        site_layer_holder["layer"] = layer

    def _center_on_polygon(_b=None):
        """Recenter the map on the currently drawn polygon.

        Deliberately sets `m.center`/`m.zoom` directly instead of calling
        `m.fit_bounds(...)`: fit_bounds only sends an async instruction to
        the Leaflet.js frontend, which computes the resulting view from the
        map container's current pixel size — under Voila that size is
        often not yet known to the frontend when the message arrives, so
        the call silently does nothing. Plain traitlet assignment has no
        such dependency and always takes effect.
        """
        poly = site.get("polygon")
        if not poly:
            return
        lons = [pt[0] for pt in poly]
        lats = [pt[1] for pt in poly]
        lat_min, lat_max = min(lats), max(lats)
        lon_min, lon_max = min(lons), max(lons)
        m.center = ((lat_min + lat_max) / 2, (lon_min + lon_max) / 2)
        m.zoom = 18  # matches the map's initial zoom, tuned for a building cluster

    def _on_draw(_target, action, geo_json):
        if action == "created":
            coords = geo_json["geometry"]["coordinates"][0]  # [ [lon, lat], ... ]
            site["polygon"] = coords
            # Wipe the draw tool's own (just-finished) shape from the map —
            # see _show_site_polygon for why this can't be left to render
            # itself — then show the new outline as our own layer. Only one
            # outline is ever on the map at a time.
            draw_control.clear()
            _show_site_polygon(coords)
            _clear_building_layer()  # outline changed: old buildings are stale
        elif action == "edited":
            existing = list(draw_control.data)
            if existing:
                coords = existing[-1]["geometry"]["coordinates"][0]
                site["polygon"] = coords
                draw_control.clear()
                _show_site_polygon(coords)
            _clear_building_layer()
        elif action == "deleted":
            if not draw_control.data:
                site["polygon"] = None
                _clear_site_polygon()
            _clear_building_layer()
        _refresh_readout()

    draw_control.on_draw(_on_draw)

    # Pre-draw the default outline unless the caller already set one
    # (e.g. returning to this step after drawing something else).
    if site.get("polygon") is None:
        site["polygon"] = [list(pt) for pt in DEFAULT_POLYGON_LONLAT]
    _show_site_polygon(site["polygon"])

    _refresh_readout()

    btn_load_gis = widgets.Button(
        description="Load GIS data",
        tooltip="Fetch real building footprints for the drawn polygon from Sympheny GIS",
        layout=widgets.Layout(width="160px", height="34px"),
    )
    btn_load_gis.add_class("wz-primary")
    btn_load_gis.add_class("wz-pill")

    def _work_load_gis(out):
        poly = site.get("polygon")
        if not poly or len(poly) < 3:
            out.print("✗ draw a polygon on the map before loading GIS data.")
            return
        try:
            data, gis_scenario_guid = _load_site_gis(out, poly)
        except Exception as exc:
            out.print(f"✗ {type(exc).__name__}: {exc}")
            return
        site["gis"] = data
        site["gis_scenario_guid"] = gis_scenario_guid
        features = (data.get("building_layer") or {}).get("features", [])
        _show_building_layer(features)

        solar_box.children = [_loader("Fetching solar profile…", CHART_SOLAR_PX)]
        lonlat = _gis_first_building_lonlat(data)
        total_area = _gis_total_area(data)
        if not lonlat or total_area <= 0:
            site["solar_series"] = None
            site["solar_area"] = None
            solar_box.children = [_error_box(
                "no building footprint/area available for a solar lookup.",
                CHART_SOLAR_PX)]
        else:
            lon, lat = lonlat
            try:
                series = _fetch_solar_profile(lon, lat, total_area)
                # Kept on `site` (rather than only rendered here) so a
                # Solar-PV variant's on-site resource in step 4 reuses this
                # exact profile instead of re-fetching it.
                site["solar_series"] = series
                site["solar_area"] = total_area
                out.print(f"  · solar: lon {lon:.5f}, lat {lat:.5f}, "
                          f"area {total_area:,.0f} m² · peak {max(series):,.3f}")
                solar_box.children = [plotly_fig_to_html(
                    _solar_fig(_avg24_series(series), CHART_SOLAR_PX))]
            except Exception as exc:
                site["solar_series"] = None
                site["solar_area"] = None
                solar_box.children = [_error_box(
                    f"{type(exc).__name__}: {exc}", CHART_SOLAR_PX)]

        if on_gis_loaded is not None:
            on_gis_loaded()

    Spinned(vbox, spinner_html).bind(_work_load_gis, btn_load_gis)

    btn_center = widgets.Button(
        description="Center",
        tooltip="Recenter the map on the drawn polygon",
        layout=widgets.Layout(width="100px", height="34px"),
    )
    btn_center.add_class("wz-ghost")
    btn_center.add_class("wz-pill")
    btn_center.on_click(_center_on_polygon)

    panel = widgets.VBox([
        m,
        solar_box,
        widgets.HBox([btn_load_gis, btn_center], layout=widgets.Layout(margin="8px 0 0 0", gap="10px")),
    ])
    return panel, _refresh_readout


# ------------------------------------------------------- step 2: site & bldgs
def _buildings_from_gis_addresses(addresses: list) -> list:
    """Turn the addresses fetched from GIS in step 1 into step 2's building
    list — one building type per address footprint.

    Only `use`/`gfa` (and, indirectly, `name`) are sent to the Sympheny
    demand API; the remaining fields (construction period, renovation,
    climate zone, diversity, EPC class) aren't present in the GIS payload,
    so they fall back to sensible defaults and stay editable in the form.
    """
    out = []
    for a in addresses:
        use = a.get("building_type") or USE_TYPES[0]
        if use not in USE_TYPES:
            use = USE_TYPES[0]
        out.append({
            "name": a.get("address") or "Unnamed building",
            "use": use,
            "period": "2000–2010",
            "renovated": "No",
            "gfa": float(a.get("building_ground_area") or 0.0),
            "zone": CLIMATE_ZONES[0],
            "diversity": 10.0,
            "epc": "C",
        })
    return out or [dict(b) for b in DEFAULT_BUILDINGS]


def _build_step_site(buildings: list) -> tuple:
    sel = [0]
    loading = [False]
    side_header = HTML()
    type_list = widgets.VBox()
    btn_add = widgets.Button(description="+ Add", tooltip="Add a building type", layout=widgets.Layout(width="80px", height="30px", margin="0 8px 8px 0"))
    btn_del = widgets.Button(description="Remove", tooltip="Remove selected type", layout=widgets.Layout(width="90px", height="30px", margin="0 0 8px 0"))
    for b in (btn_add, btn_del):
        b.add_class("wz-ghost")
    totals_box = HTML()
    side = widgets.VBox( [side_header, widgets.HBox([btn_add, btn_del]), type_list, totals_box], layout=widgets.Layout(width="250px", margin="0 20px 0 0"), )
    fw = widgets.Layout(width="97%", height="32px")
    f_name = widgets.Text(layout=fw)
    f_use = widgets.Dropdown(options=USE_TYPES, layout=fw)
    f_period = widgets.Dropdown(options=PERIODS, layout=widgets.Layout(width="200px", height="32px"))
    f_renov = widgets.Dropdown(options=["No", "Yes"], layout=fw)
    f_gfa = widgets.FloatText(layout=fw)
    f_zone = widgets.Dropdown(options=CLIMATE_ZONES, layout=fw)
    f_div = widgets.FloatText(layout=fw)
    epc_btns = []
    for cls in EPC_CLASSES:
        b = widgets.Button(description=cls, layout=widgets.Layout(width="38px", height="30px", margin="0 5px 0 0"))
        b.add_class("wz-chipbtn")
        b._epc = cls
        epc_btns.append(b)

    def _col(label, w, caption):
        return widgets.VBox( [HTML(f"<div class='wz-label'>{label}</div>"), w, HTML(f"<div class='wz-caption'>{caption}</div>")], layout=widgets.Layout(width="32%"), )

    form = widgets.VBox([
        widgets.HBox([
            _col("Name", f_name, "Label used in the report"),
            _col("Use type", f_use, "Sympheny building_type"),
            _col("Renovated", f_renov, "Envelope refurbishment done"),
        ]),
        widgets.HBox([
            _col("Gross floor area", f_gfa, "m² · sent as building_ground_area"),
            _col("Climate zone", f_zone, "Climate zone · solar irradiation"),
            _col("Diversity factor", f_div, "% reduction in aggregated peak"),
        ]),
        widgets.HBox([
            HTML("<div class='wz-label' style='margin:8px 10px 0 2px'>Energy class "
                 "<span style='color:#8a94a0'>(EU EPC / SIA 380/1)</span></div>"),
            widgets.HBox(epc_btns, layout=widgets.Layout(margin="4px 24px 0 0")),
            HTML("<div class='wz-label' style='margin:8px 10px 0 0'>Construction "
                 "period</div>"),
            f_period,
        ], layout=widgets.Layout(align_items="center", margin="0 0 10px")),
    ])
    kpi_row = HTML()
    preview_box = widgets.VBox(layout=widgets.Layout(margin="0 0 0 14px"))
    kpi_and_chart = widgets.HBox([kpi_row, preview_box], layout=widgets.Layout(align_items="center"))
    right = widgets.VBox([HTML(), form, kpi_and_chart], layout=widgets.Layout(width="calc(100% - 270px)"))
    right_title = right.children[0]
    status = HTML()
    agg_kpis = HTML()
    agg_chart = widgets.VBox()
    panel = widgets.VBox([ HTML("<div class='wz-title'>Site &amp; buildings</div>"), status, widgets.HBox([side, right], layout=widgets.Layout(align_items="flex-start")), agg_kpis, agg_chart, ])

    def _totals():
        surface = 0.0
        peaks = {c: 0.0 for c, _ in CARRIERS}
        annuals = {c: 0.0 for c, _ in CARRIERS}
        curves = {c: [0.0] * 24 for c, _ in CARRIERS}
        for b in buildings:
            surface += float(b["gfa"] or 0)
            pk, an, cv = _peaks(b), _annuals(b), _avg24(b)
            for c, _ in CARRIERS:
                peaks[c] += pk[c]
                annuals[c] += an[c]
                curves[c] = [x + y for x, y in zip(curves[c], cv[c])]
        div = (sum(float(b["diversity"] or 0) for b in buildings) / len(buildings)) \
            if buildings else 0.0
        coinc = max(0.0, 1.0 - div / 100.0)
        return (surface,
                {c: v * coinc for c, v in peaks.items()},
                annuals,                                     # energy: no coincidence
                {c: [v * coinc for v in s] for c, s in curves.items()},
                div, coinc)

    def _show_loaders():
        """Swap both charts for spinners before the (blocking) batch starts."""
        pending = sum(1 for b in buildings if _demand_key(b) != b.get("_key"))
        if not pending:
            return
        n = pending * len(CARRIERS)
        status.value = (WZ_CSS + f"<div class='wz-caption'>⏳ Fetching {n} demand "
                                 f"profile(s) from Sympheny in parallel…</div>")
        preview_box.children = [_loader("Loading profile…", CHART_PREVIEW_PX, CHART_PREVIEW_W)]
        agg_chart.children = [_loader("Aggregating all building types…", CHART_COMBINED_PX)]

    def _compute():
        _load_demands(buildings)
        errs = [f"{b['name']} — {b['_error']}" for b in buildings if b.get("_error")]
        status.value = WZ_CSS + ("".join(
            f"<div class='wz-err'>⚠ {e}</div>" for e in errs) if errs else "")

    def _refresh_list():
        side_header.value = (WZ_CSS + f"<div class='wz-title'>Building types ({len(buildings)})</div>")
        rows = []
        for i, b in enumerate(buildings):
            active = i == sel[0]
            mark = "⚠" if b.get("_error") else "🏢"
            btn = widgets.Button( description=f"{mark}  {b['name']}", tooltip=f"{b['gfa']:,.0f} m² · {b['use']} · Class {b['epc']}", layout=widgets.Layout(width="100%", height="32px", margin="0 0 1px 0"), )
            btn.add_class("wz-listitem")
            btn.style.button_color = "#e6f6f3" if active else "#ffffff"
            btn.style.font_weight = "bold" if active else "normal"
            btn.on_click(partial(_pick, i))
            rows.append(widgets.VBox([ btn, HTML(f"<div class='wz-caption' style='margin:-3px 0 5px 30px'>" f"{b['gfa']:,.0f} m² · {b['use']}</div>"), ]))
        type_list.children = rows
        surface, peaks, _annual_tot, _curves, _div, _coinc = _totals()
        totals_box.value = (
            "<div class='wz-side wz-tot' style='margin-top:8px'>"
            "<div style='font-size:10px;letter-spacing:.1em;color:#8a94a0'>"
            "AGGREGATE TOTALS</div>"
            f"Surface <span>{surface:,.0f} m²</span><br>"
            f"Heat peak <span style='color:{CARRIER_COLOR['Heat']}'>{peaks['Heat']:,.0f} kW</span><br>"
            f"Elec peak <span style='color:{CARRIER_COLOR['Elec']}'>{peaks['Elec']:,.0f} kW</span><br>"
            f"DHW peak <span style='color:{CARRIER_COLOR['DHW']}'>{peaks['DHW']:,.0f} kW</span>"
            "</div>"
        )

    def _refresh_epc(cur):
        for b in epc_btns:
            on = b._epc == cur["epc"]
            b.style.button_color = EPC_COLOR[b._epc] if on else "#f2f4f7"
            b.style.font_weight = "bold" if on else "normal"
            b.style.text_color = "#ffffff" if on else "#6b7280"

    def _refresh_right():
        if not buildings:
            right_title.value = "<i style='color:#8a94a0'>No building type defined.</i>"
            kpi_row.value = ""
            preview_box.children = []
            return
        cur = buildings[sel[0]]
        tag = "&nbsp;<span class='wz-tag err'>FAILED</span>" if cur.get("_error") else ""
        right_title.value = (
                WZ_CSS +
                f"<div style='font-family:sans-serif;font-size:15px;font-weight:600;"
                f"margin:0 0 8px'>🏢 {cur['name']}{tag}"
                f"<span style='font-size:11px;color:#8a94a0;font-weight:400'>"
                f"&nbsp;&nbsp;type {sel[0] + 1} of {len(buildings)} · "
                f"{cur['use']}</span></div>")
        _refresh_epc(cur)
        if cur.get("_error"):
            kpi_row.value = (WZ_CSS + "<div class='wz-caption'>No demand data — the "
                                      "Sympheny request failed.</div>")
            preview_box.children = [_error_box(cur["_error"], CHART_PREVIEW_PX, CHART_PREVIEW_W)]
            return
        pk, an, cv = _peaks(cur), _annuals(cur), _avg24(cur)
        cards = [
            _kpi("Heat peak", f"{pk['Heat']:,.0f}",
                 f"kW · {an['Heat']:,.0f} MWh/y", CARRIER_COLOR["Heat"]),
            _kpi("Elec peak", f"{pk['Elec']:,.0f}",
                 f"kW · {an['Elec']:,.0f} MWh/y", CARRIER_COLOR["Elec"]),
            _kpi("DHW peak", f"{pk['DHW']:,.0f}",
                 f"kW · {an['DHW']:,.0f} MWh/y", CARRIER_COLOR["DHW"]),
        ]
        kpi_row.value = WZ_CSS + f"<div class='wz-row'>{''.join(cards)}</div>"
        preview_box.children = [plotly_fig_to_html(_profile_fig( cv, "Hourly profile preview (daily avg of 8760 h)", CHART_PREVIEW_PX, CHART_PREVIEW_W))]

    def _refresh_band():
        surface, peaks, annuals, curves, _div, _coinc = _totals()
        cards = [
            _kpi("Surface", f"{surface:,.0f}", "m²", "#4a5568"),
            _kpi("Heat peak", f"{peaks['Heat']:,.0f}", "kW · coincident", CARRIER_COLOR["Heat"]),
            _kpi("Heat annual", f"{annuals['Heat']:,.0f}", "MWh/y", CARRIER_COLOR["Heat"]),
            _kpi("Elec peak", f"{peaks['Elec']:,.0f}", "kW · coincident", CARRIER_COLOR["Elec"]),
            _kpi("Elec annual", f"{annuals['Elec']:,.0f}", "MWh/y", CARRIER_COLOR["Elec"]),
            _kpi("DHW peak", f"{peaks['DHW']:,.0f}", "kW · coincident", CARRIER_COLOR["DHW"]),
        ]
        missing = sum(1 for b in buildings if b.get("_error"))
        note = (f" <span style='text-transform:none;letter-spacing:0;color:#b3312c "
                f"!important'>· {missing} type(s) missing</span>") if missing else ""
        agg_kpis.value = ( WZ_CSS + f"<div class='wz-band'><h4>Σ Aggregated totals — all {len(buildings)} " f"building types{note}</h4><div class='wz-row'>{''.join(cards)}</div></div>")
        agg_chart.children = [plotly_fig_to_html(_profile_fig( curves, "Combined hourly profile – all zones & carriers", CHART_COMBINED_PX))]

    def refresh_all(recompute: bool = True):
        if recompute:
            _show_loaders()
            _compute()
        _refresh_list()
        _refresh_right()
        _refresh_band()

    def _load_form():
        if not buildings:
            return
        loading[0] = True
        cur = buildings[sel[0]]
        f_name.value = cur["name"]
        f_use.value = cur["use"] if cur["use"] in USE_TYPES else USE_TYPES[0]
        f_period.value = cur["period"]
        f_renov.value = cur["renovated"]
        f_gfa.value = float(cur["gfa"])
        f_zone.value = cur["zone"]
        f_div.value = float(cur["diversity"])
        loading[0] = False

    def _on_field(_change=None):
        if loading[0] or not buildings:
            return
        cur = buildings[sel[0]]
        cur.update(name=f_name.value or "Unnamed", use=f_use.value, period=f_period.value, renovated=f_renov.value, gfa=max(0.0, f_gfa.value), zone=f_zone.value, diversity=f_div.value)
        refresh_all()

    for w in (f_name, f_use, f_period, f_renov, f_gfa, f_zone, f_div):
        w.observe(_on_field, names="value")

    def _pick(index, _btn=None):
        if 0 <= index < len(buildings):
            sel[0] = index
            _load_form()
            refresh_all(recompute=False)

    def _on_epc(b):
        if not buildings:
            return
        buildings[sel[0]]["epc"] = b._epc     # metadata only, no refetch
        refresh_all(recompute=False)

    for b in epc_btns:
        b.on_click(_on_epc)

    def _on_add(_b):
        buildings.append({"name": f"Building type {len(buildings) + 1}",
                          "use": "OFFICES", "period": "2000–2010", "renovated": "No",
                          "gfa": 1000.0, "zone": CLIMATE_ZONES[0],
                          "diversity": 10.0, "epc": "C"})
        sel[0] = len(buildings) - 1
        _load_form()
        refresh_all()

    def _on_del(_b):
        if len(buildings) <= 1:
            return
        buildings.pop(sel[0])
        sel[0] = max(0, sel[0] - 1)
        _load_form()
        refresh_all(recompute=False)

    btn_add.on_click(_on_add)
    btn_del.on_click(_on_del)
    _load_form()
    refresh_all()
    return panel, refresh_all


# --------------------------------------------------- step 3: system variants
def _build_step_variants(variants: list) -> tuple:
    """Variant columns; technologies are added through a modal picker."""
    target = [0]  # variant the modal is currently adding to
    row = widgets.HBox(layout=widgets.Layout(align_items="flex-start", overflow="auto"))
    modal_title = HTML()
    modal_body = widgets.VBox()
    btn_close = widgets.Button(description="Cancel", layout=widgets.Layout(width="100px", height="34px"))
    btn_close.add_class("wz-ghost")
    btn_close.add_class("wz-pill")
    modal_card = widgets.VBox( [modal_title, modal_body, widgets.HBox([btn_close], layout=widgets.Layout(justify_content="flex-end", margin="12px 0 0 0"))])
    modal_card.add_class("wz-modal-card")
    modal = widgets.Box([modal_card])
    modal.add_class("wz-modal")
    modal.layout.display = "none"

    def _open_modal(vi, _b=None):
        target[0] = vi
        var = variants[vi]
        color = VARIANT_COLORS[vi % len(VARIANT_COLORS)]
        modal_title.value = ( WZ_CSS + f"<div class='wz-modal-title'>Add technology</div>" f"<div class='wz-caption'>to <b style='color:{color} !important'>" f"V{vi + 1}</b> · {var['name']}</div>")
        blocks = []
        for cat, techs in TECH_CATALOG.items():
            available = [t for t in techs if t[0] not in var["techs"]]
            if not available:
                continue
            blocks.append(HTML(f"<div class='wz-cat'>{cat}</div>"))
            for tech, sub, icon in available:
                b = widgets.Button(description=f"{icon}   {tech}", tooltip=sub, layout=widgets.Layout(width="99%", height="34px", margin="0 0 2px 0"))
                b.add_class("wz-pick")
                b.on_click(partial(_add_tech, vi, tech))
                blocks.append(b)
                blocks.append(HTML(f"<div class='wz-sub' style='margin:-4px 0 6px 30px'>" f"{sub}</div>"))
        if not blocks:
            blocks = [HTML("<div class='wz-caption'>Every technology is already " "part of this variant.</div>")]
        modal_body.children = blocks
        modal.layout.display = "flex"

    def _close_modal(_b=None):
        modal.layout.display = "none"

    btn_close.on_click(_close_modal)

    def _add_tech(vi, tech, _b=None):
        if tech not in variants[vi]["techs"]:
            variants[vi]["techs"].append(tech)
        _close_modal()
        _render()

    def _remove_tech(vi, tech, _b=None):
        if tech in variants[vi]["techs"]:
            variants[vi]["techs"].remove(tech)
        _render()

    def _tech_card(vi, tech, color):
        cat, sub, icon = TECH_INDEX.get(tech, ("", "", "•"))
        text = HTML(f"<div style='display:flex;align-items:center;gap:9px'>"
                    f"<span style='font-size:16px'>{icon}</span><span>"
                    f"<div class='wz-tech-name'>{tech}</div>"
                    f"<div class='wz-tech-sub'>{sub}</div></span></div>",
                    layout=widgets.Layout(width="205px"))
        badge = HTML(f"<div style='width:20px;height:20px;border-radius:50%;"
                     f"background:{color};color:#fff !important;font-size:11px;"
                     f"display:flex;align-items:center;justify-content:center'>"
                     f"\u2713</div>")
        rm = widgets.Button(description="✕", tooltip=f"Remove {tech}", layout=widgets.Layout(width="26px", height="26px"))
        rm.add_class("wz-x")
        rm.on_click(partial(_remove_tech, vi, tech))
        return widgets.HBox(
            [text, badge, rm],
            layout=widgets.Layout(width="272px", margin="0 0 6px 0",
                                  padding="8px 10px", align_items="center",
                                  justify_content="space-between",
                                  border=f"1px solid {color}66",
                                  border_radius="10px"))

    def _render():
        cols = []
        for vi, var in enumerate(variants):
            color = VARIANT_COLORS[vi % len(VARIANT_COLORS)]
            name = widgets.Text(value=var["name"], layout=widgets.Layout(width="200px", height="32px"))
            name.observe(partial(_on_name, vi), names="value")
            head = [HTML(f"<div style='background:{color};color:#fff !important;"
                         f"border-radius:50%;width:24px;height:24px;line-height:24px;"
                         f"text-align:center;font-size:11px;font-weight:700;"
                         f"font-family:sans-serif'>V{vi + 1}</div>"), name]
            if len(variants) > 1:
                close = widgets.Button(description="✕", tooltip="Remove variant", layout=widgets.Layout(width="28px", height="28px"))
                close.add_class("wz-x")
                close.on_click(partial(_on_remove_variant, vi))
                head.append(close)
            items = [widgets.HBox(head, layout=widgets.Layout(align_items="center", margin="0 0 8px 0"))]
            for cat in TECH_CATALOG:
                chosen = [t for t, _s, _i in TECH_CATALOG[cat] if t in var["techs"]]
                if not chosen:
                    continue
                items.append(HTML(f"<div class='wz-cat'>{cat}</div>"))
                items.extend(_tech_card(vi, t, color) for t in chosen)
            if not var["techs"]:
                items.append(HTML("<div class='wz-caption'>No technology yet.</div>"))
            add_tech = widgets.Button(description="+ Add technology", layout=widgets.Layout(width="272px", height="34px", margin="6px 0 0 0"))
            add_tech.add_class("wz-addtech")
            add_tech.on_click(partial(_open_modal, vi))
            items.append(add_tech)
            cols.append(widgets.VBox(items, layout=widgets.Layout( width="310px", padding="12px 14px", margin="0 12px 0 0", border=f"1px solid {color}55", border_radius="12px")))
        add_var = widgets.Button(description="+  Add variant", layout=widgets.Layout(width="150px", height="38px"))
        add_var.add_class("wz-addtech")
        add_var.on_click(_on_add_variant)
        cols.append(widgets.VBox(
            [HTML("<div class='wz-caption' style='margin:40px 0 8px'>&nbsp;</div>"),
             add_var],
            layout=widgets.Layout(width="180px", padding="12px",
                                  align_items="center",
                                  border="1px dashed #d5dbe2",
                                  border_radius="12px")))
        row.children = cols

    def _on_name(vi, change):
        variants[vi]["name"] = change["new"] or f"Variant {vi + 1}"

    def _on_add_variant(_b):
        variants.append({"name": f"Variant {len(variants) + 1}", "techs": []})
        _render()

    def _on_remove_variant(vi, _b):
        if len(variants) > 1:
            variants.pop(vi)
            _render()

    panel = widgets.VBox([
        HTML(WZ_CSS +
             "<div class='wz-title'>Define your energy system variants</div>"
             "<div class='wz-caption'>Add technologies to each variant with the "
             "+ button. Each variant is optimised separately.</div>"),
        row,
    ])
    _render()
    return panel, _render, modal


# ----------------------------------------------------------- step 4: summary
def _summary_html(buildings: list, variants: list) -> str:
    surface = sum(float(b["gfa"] or 0) for b in buildings)
    peaks = {c: 0.0 for c, _ in CARRIERS}
    annuals = {c: 0.0 for c, _ in CARRIERS}
    for b in buildings:
        pk, an = _peaks(b), _annuals(b)
        for c, _ in CARRIERS:
            peaks[c] += pk[c]
            annuals[c] += an[c]
    div = (sum(float(b["diversity"] or 0) for b in buildings) / len(buildings)) \
        if buildings else 0.0
    coinc = max(0.0, 1.0 - div / 100.0)
    peaks = {c: v * coinc for c, v in peaks.items()}
    parts = [WZ_CSS, "<div class='wz-title'>Summary</div>"]
    rows = []
    for i, b in enumerate(buildings):
        pk = _peaks(b)
        epc_color = EPC_COLOR[b["epc"]]
        if b.get("_error"):
            demand_line = (f"<span style='color:#b3312c !important'>"
                           f"no demand data — {b['_error']}</span>")
        else:
            demand_line = (f"heat {pk['Heat']:,.0f} kW · elec {pk['Elec']:,.0f} kW · "
                           f"DHW {pk['DHW']:,.0f} kW")
        tag = "&nbsp;<span class='wz-tag err'>FAILED</span>" if b.get("_error") else ""
        rows.append(
            f"<tr><td class='k'>#{i + 1} &nbsp;{b['name']}</td><td class='v'>"
            f"{b['use']} · {b['period']} · renovated: {b['renovated']}{tag}<br>"
            f"<span style='font-weight:400;color:#6b7280'>"
            f"{b['gfa']:,.0f} m² · {b['zone']} · diversity {b['diversity']:.0f}% · "
            f"class <b style='color:{epc_color} !important'>{b['epc']}</b><br>"
            f"{demand_line}</span></td></tr>")
    parts.append("<div class='wz-sum'><h3>Site &amp; buildings " f"({len(buildings)} types)</h3><table>{''.join(rows)}</table></div>")
    missing = [b["name"] for b in buildings if b.get("_error")]
    warn = (f"<tr><td class='k'>Incomplete</td><td class='v' "
            f"style='color:#b3312c !important'>{', '.join(missing)} excluded — "
            f"demand fetch failed</td></tr>") if missing else ""
    parts.append(
        "<div class='wz-sum'><h3>Aggregated totals</h3><table>"
        f"<tr><td class='k'>Surface</td><td class='v'>{surface:,.0f} m²</td></tr>"
        f"<tr><td class='k'>Heat peak / annual</td><td class='v'>{peaks['Heat']:,.0f} kW · "
        f"{annuals['Heat']:,.0f} MWh/y</td></tr>"
        f"<tr><td class='k'>Elec peak / annual</td><td class='v'>{peaks['Elec']:,.0f} kW · "
        f"{annuals['Elec']:,.0f} MWh/y</td></tr>"
        f"<tr><td class='k'>DHW peak / annual</td><td class='v'>{peaks['DHW']:,.0f} kW · "
        f"{annuals['DHW']:,.0f} MWh/y</td></tr>"
        f"<tr><td class='k'>Coincidence applied</td><td class='v'>{coinc:.2f} "
        f"(mean diversity {div:.0f}%)</td></tr>"
        f"{warn}</table></div>")
    vrows = []
    for vi, var in enumerate(variants):
        color = VARIANT_COLORS[vi % len(VARIANT_COLORS)]
        chips = "".join( f"<span class='wz-chip' style='background:{color}1a;color:{color} !important'>{t}</span>" for t in var["techs"]) or "<i style='color:#8a94a0'>no technology selected</i>"
        vrows.append(f"<tr><td class='k'><b style='color:{color}'>V{vi + 1}</b> " f"{var['name']}</td><td class='v'>{chips}</td></tr>")
    parts.append("<div class='wz-sum'><h3>System variants " f"({len(variants)})</h3><table>{''.join(vrows)}</table></div>")
    return "".join(parts)


def _build_step_summary(buildings: list, variants: list) -> tuple:
    body = HTML()
    btn_submit = widgets.Button(description="Submit", layout=widgets.Layout(width="150px", height="36px"))
    btn_submit.add_class("wz-primary")
    btn_submit.add_class("wz-pill")

    def refresh():
        body.value = _summary_html(buildings, variants)

    refresh()
    return widgets.VBox([body]), btn_submit, refresh


# ------------------------------------------------------------- wizard shell
def run():
    # ---- Phase 1: bare empty shell, displayed immediately ---------------
    nav_widget = HTML()
    content_area = widgets.VBox([_loading_html()], layout=widgets.Layout(min_height=f"{CONTENT_MIN_PX}px", overflow="visible"))
    footer = widgets.HBox(
        layout=widgets.Layout(width="100%", justify_content="space-between",
                              align_items="center",
                              margin="10px 0 0 0", padding="10px 0 0 0",
                              border_top=f"1px solid {LINE}"),
    )
    spinner_html = get_spinner_html()
    vbox = widgets.VBox()
    modal_container = widgets.VBox()

    display(nav_widget, content_area, footer, HTML("<br/>"), spinner_html, vbox, modal_container)

    def _init_app():
        _authenticate()

        # ---- Phase 2: everything real, built only once the browser is
        #      ready. The location step is built eagerly since it's the
        #      wizard's first page; the rest are lazy (see _ensure_step).
        site = {"polygon": None}
        buildings = [dict(b) for b in DEFAULT_BUILDINGS]
        variants = [{"name": v["name"], "techs": list(v["techs"])} for v in DEFAULT_VARIANTS]

        panels = {}
        refreshers = {}
        step_extras = {}  # e.g. {"btn_submit": widgets.Button}
        current_step = [0]

        def _invalidate_step(index: int):
            """Drop a lazily-built panel so it's reconstructed on next visit."""
            panels.pop(index, None)
            refreshers.pop(index, None)

        panel_location, refresh_location = _build_step_location(
            site, vbox, spinner_html,
            on_gis_loaded=lambda: _invalidate_step(1))  # rebuild step 2 from new addresses
        panel_location.layout.margin = "4px 0 0 0"
        panels[0] = panel_location
        refreshers[0] = refresh_location

        btn_prev = widgets.Button(description="←  Back", layout=widgets.Layout(width="120px", height="36px"))
        btn_prev.add_class("wz-ghost")
        btn_prev.add_class("wz-pill")
        btn_next = widgets.Button(description="Continue  →", layout=widgets.Layout(width="150px", height="36px"))
        btn_next.add_class("wz-primary")
        btn_next.add_class("wz-pill")
        right_actions = widgets.HBox(
            [btn_next],
            layout=widgets.Layout(align_items="center", gap="10px"),
        )
        footer.children = [btn_prev, right_actions]

        def _ensure_step(index: int):
            """Lazily build the panel for `index` on first visit."""
            if index in panels:
                return
            if index == 1:
                # If GIS data was fetched in step 1, replace the default
                # building types with one per address found on the site.
                addresses = (site.get("gis") or {}).get("addresses") or []
                if addresses:
                    buildings[:] = _buildings_from_gis_addresses(addresses)
                panel_site, refresh_site = _build_step_site(buildings)
                panel_site.layout.margin = "4px 0 0 0"
                panels[1] = panel_site
                refreshers[1] = refresh_site
            elif index == 2:
                panel_var, refresh_var, modal_var = _build_step_variants(variants)
                panel_var.layout.margin = "4px 0 0 0"
                panels[2] = panel_var
                refreshers[2] = refresh_var
                modal_container.children = [modal_var]
            elif index == 3:
                panel_sum, btn_submit, refresh_sum = _build_step_summary(buildings, variants)
                panel_sum.layout.margin = "4px 0 0 0"
                panels[3] = panel_sum
                refreshers[3] = refresh_sum
                step_extras["btn_submit"] = btn_submit
                Spinned(vbox, spinner_html).bind(
                    lambda out: _work_submit(out, buildings, variants, site), btn_submit)

        def go_to(index: int):
            index = max(0, min(len(STEP_DEFS) - 1, index))
            # Immediate feedback: loading message
            nav_widget.value = _render_nav_html(index)
            btn_prev.layout.visibility = "hidden" if index == 0 else "visible"
            if index == 1:
                content_area.children = [_loading_html(
                    "LOADING DEMANDS FROM SYMPHENY BACKEND …", big=True)]
            else:
                content_area.children = [_loading_html()]
            _ensure_step(index)
            refreshers[index]()
            current_step[0] = index
            content_area.children = [panels[index]]
            last = index == len(STEP_DEFS) - 1
            right_actions.children = (step_extras["btn_submit"],) if last else (btn_next,)

        btn_prev.on_click(lambda _: go_to(current_step[0] - 1))
        btn_next.on_click(lambda _: go_to(current_step[0] + 1))
        go_to(0)

    on_browser_ready(_init_app)


# ===========================================================================
## BACKEND API CALLS
# Everything below talks to Sympheny or derives numbers from what it returned.
# Nothing here touches ipywidgets: the UI above calls into this section and
# renders whatever comes back (including the error strings).
# ===========================================================================

CONSTRUCTION_END = 2000       # fixed – not driven by the form
NBR_FLOOR = 1                 # fixed – so building_ground_area == GFA
HTTP_TIMEOUT = 90
MAX_WORKERS = 12              # ceiling for one batch of building x carrier calls
PROJECT_NAME = "light-app"    # reused across submits; only its variants
# analysis is deleted & recreated each time
HUB_NAME = "Hub 1"
STAGE_NAME = "Stage 1"

# Dedicated analysis — within the same PROJECT_NAME project — used solely
# to preview real GIS building footprints for the drawn site polygon
# (step 1). Kept separate from the per-variant analysis created at final
# submit (step 4). The analysis itself is reused across repeated "Load GIS
# data" clicks, but its scenario is deleted & recreated on every click (see
# `_reset_scenario`) so it always ends up with exactly one hub. That
# scenario is also the source scenario copied onto every variant scenario
# at submit time (see _copy_scenario_gis). Its hub uses the same HUB_NAME
# as the variant scenarios' own hub (above), so both steps share a single
# global hub-name definition.
GIS_ANALYSIS_NAME = "site-gis"
GIS_SCENARIO_NAME = "site-gis"
GIS_JOB_MAX_ATTEMPTS = 300
GIS_JOB_POLL_SECONDS = 1.0

CARRIER_DEMAND_TYPE = {
    "Heat": "SPACE_HEATING",
    "Elec": "ELECTRICITY",
    "DHW": "HOT_WATER",
}
# Energy-carrier subtype (EnergyCarrierRequestDtoV2.subType) per app carrier.
# Also the key used to reuse a carrier the technology package already created:
# the imported technologies emit HEAT_8 for space heating and HEAT_4 for DHW,
# so these must match or every scenario ends up with duplicate heat carriers.
CARRIER_SUBTYPE = {
    "Heat": "HEAT_8",
    "Elec": "ELECTRICITY",
    "DHW": "HEAT_4",
}
CARRIER_FULL_NAME = {
    "Heat": "Space heating",
    "Elec": "Electricity",
    "DHW": "Domestic hot water",
}
# Carrier subtype (EnergyCarrierRequestDtoV2.subType) that importing the
# "Solar PV - Roof" database technology creates for its incoming solar
# resource — distinct from the ELECTRICITY carrier the same import creates
# for its output. The solar-on-site-resource endpoint only accepts carriers
# whose subType is one of a fixed resource-type list (SOLAR_ROOF, BIOMASS,
# GEOTHERMAL, HYDRO, PROCESS_WASTE_HEAT, SOLAR_FACADE, SOLAR_PARAPET, TIDAL,
# WIND); SOLAR_ROOF is the one "Solar PV - Roof" brings in, so it's reused
# rather than created again — same reuse-by-subtype pattern CARRIER_SUBTYPE
# already uses for the demand carriers.
SOLAR_RESOURCE_SUBTYPE = "SOLAR_ROOF"
# Electricity import/export prices [CHF/kWh] written onto every variant
# that ends up with an ELECTRICITY carrier. Import is deliberately very
# high so the optimiser treats grid draw as a last resort rather than a
# cheap substitute for the on-site technologies; export is nominal.
IMPEX_ELEC_PRICE = {"IMPORT": 10000.0, "EXPORT": 1.0}
# Solver job submitted for the first scenario once every variant is built,
# so the summary can link straight to a solved dashboard.
SOLVER_OBJECTIVE = "MIN_LIFE_CYCLE_COST"
SOLVER_TIME_LIMIT = 30
SOLVER_MIP_GAP = 10
SOLVER_POINTS = 1
SOLVER_TEMPORAL_RESOLUTION = "LOW"
SOLVER_WAIT_SECONDS = 300     # give up waiting after this long
SOLVER_POLL_SECONDS = 5
# App label -> technology name in the Sympheny database.
APP_TO_DB = {
    "Gas boiler": "Gas Boiler (Linearized cost)",
    "Air-source heat pump": "Air-to-water HP (Linearized cost)",
    "Ground-source HP": "Brine-Water HP- < 100 kW (Linearized cost)",
    "Wood pellet boiler": "Pellet Boiler- < 100 kW (Linearized cost)",
    "Solar PV": "Solar PV - Roof",
    "CHP unit": "Gas CHP (Linearized cost)",
}

_HEADERS = {}                 # set by _authenticate()
SYMPHENY_BASE_URL = None
BE_URL = None
_DEMAND_CACHE = {}            # (building_type, area, carrier) -> {peak, annual, avg24, series}


def _authenticate() -> None:
    """Read the kernel token once and build the auth header for every call."""
    global _HEADERS
    global SYMPHENY_BASE_URL
    global BE_URL

    creds = get_creds_from_token(get_token())
    _HEADERS = creds["h"]
    SYMPHENY_BASE_URL = creds["base_url"]
    BE_URL = creds["be"]
    utils_log.log(SYMPHENY_BASE_URL)


# ------------------------------------------------- step 2: demand retrieval
def _fetch_carrier(building_type: str, area: float, carrier: str) -> dict:
    """One hub_demand + profile round-trip for a single carrier.

    Returns the peak [kW], the annual energy [MWh/y], the 24 h daily-average
    curve [kW] and the full 8760 h series [kW] (kept for the submit step).
    Raises on any transport / payload problem — callers surface the message.
    """
    if area <= 0:
        return {"peak": 0.0, "annual": 0.0, "avg24": [0.0] * 24,
                "series": [0.0] * 8760}
    key = (building_type, round(float(area), 3), carrier)
    if key in _DEMAND_CACHE:
        return _DEMAND_CACHE[key]

    demand_type = CARRIER_DEMAND_TYPE[carrier]
    payload = [{"construction_end": CONSTRUCTION_END,
                "building_ground_area": float(area),
                "nbr_floor": NBR_FLOOR}]
    meta = r.post(
        f"{SYMPHENY_BASE_URL}api-services/demand/hub_demand"
        f"?demand_type={demand_type}&building_type={building_type}",
        headers=_HEADERS, json=payload, timeout=HTTP_TIMEOUT,
    )
    meta.raise_for_status()
    resp = meta.json()[0]
    guid, total = resp["energyDemandMetadataGuid"], resp["totalAnnualDemand"]

    prof = r.get(
        f"{BE_URL}database-energy-demands/{guid}/profile",
        headers=_HEADERS, timeout=HTTP_TIMEOUT,
    )
    prof.raise_for_status()
    data = prof.json()["data"]
    if len(data) != 8760:
        raise ValueError(f"{demand_type}: expected 8760 periods, got {len(data)}")

    # `data` is [{"period": 1, "demandValue": 0.000157784}, ...] — a normalised
    # share of the annual total. Sort by period: order is not guaranteed.
    series = [item["demandValue"] * total
              for item in sorted(data, key=lambda d: d["period"])]

    out = {
        "peak": max(series),                                       # kW
        "annual": total / 1000.0,                                  # MWh/y
        "avg24": [sum(series[h::24]) / 365.0 for h in range(24)],  # kW
        "series": series,                                          # 8760 x kW
    }
    _DEMAND_CACHE[key] = out
    return out


def _demand_key(b: dict) -> tuple:
    """The only two form fields that drive the API call."""
    return (b["use"], round(float(b["gfa"] or 0), 3))


def _load_demands(buildings: list) -> None:
    """Fetch every stale building's carriers in ONE parallel batch.

    On the first render that is 3 buildings x 3 carriers = 9 concurrent
    round-trips instead of 9 sequential ones. Failures are recorded per
    building in `_error` and never replaced by invented numbers.
    """
    stale = []
    for b in buildings:
        key = _demand_key(b)
        if b.get("_key") == key and (b.get("_demand") or b.get("_error")):
            continue
        b["_pending"] = key
        stale.append(b)
    if not stale:
        return

    names = [c for c, _ in CARRIERS]
    jobs = {}
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(stale) * len(names))) as pool:
        for b in stale:
            use, area = b["_pending"]
            for c in names:
                jobs[(id(b), c)] = pool.submit(_fetch_carrier, use, area, c)

    for b in stale:
        demand, error = {}, ""
        for c in names:
            try:
                demand[c] = jobs[(id(b), c)].result()
            except Exception as exc:
                error = error or f"{type(exc).__name__}: {exc}"
        b["_demand"] = None if error else demand
        b["_error"] = error
        b["_key"] = b.pop("_pending")   # set even on failure: no retry storm


def _peaks(b: dict) -> dict:
    d = b.get("_demand") or {}
    return {c: d.get(c, {}).get("peak", 0.0) for c, _ in CARRIERS}


def _annuals(b: dict) -> dict:
    d = b.get("_demand") or {}
    return {c: d.get(c, {}).get("annual", 0.0) for c, _ in CARRIERS}


def _avg24(b: dict) -> dict:
    d = b.get("_demand") or {}
    return {c: d.get(c, {}).get("avg24", [0.0] * 24) for c, _ in CARRIERS}


def _aggregate_series(buildings: list) -> dict:
    """Site-wide 8760 h demand per carrier [kW], summed over building types.

    Buildings whose fetch failed contribute nothing — they are reported
    separately rather than silently filled in.
    """
    total = {c: [0.0] * 8760 for c, _ in CARRIERS}
    for b in buildings:
        d = b.get("_demand") or {}
        for c, _ in CARRIERS:
            s = d.get(c, {}).get("series")
            if not s:
                continue
            acc = total[c]
            for i, v in enumerate(s):
                acc[i] += v
    return total


# --------------------------------------------- step 4: scenario construction
def _db_tech_index() -> dict:
    """technologyName -> conversionTechGuid from the Sympheny database."""
    resp = r.get(f"{BE_URL}conversion-technologies/profile-types/database",
                 headers=_HEADERS, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return {item["technologyName"]: item["conversionTechGuid"]
            for item in resp.json()["data"]}


def _delete_analysis(analysis_guid: str) -> None:
    """DELETE /analysis/{analysisGuid}."""
    resp = r.delete(f"{BE_URL}analysis/{analysis_guid}",
                    headers=_HEADERS, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()


def _reset_analysis(project_guid: str, name: str) -> str:
    """Delete any analysis named `name` within the project, then create a
    fresh one — used instead of deleting/recreating the whole project so
    other analyses in the same project (in particular the step-1 GIS
    scenario, which lives in this same project) are left untouched."""
    resp = r.get(f"{BE_URL}projects/{project_guid}/analyses",
                 headers=_HEADERS, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    for a in resp.json()["data"] or []:
        if a.get("analysisName") == name:
            _delete_analysis(a["analysisGuid"])
    return _create_analysis(project_guid, name)


def _create_analysis(project_guid: str, name: str) -> str:
    resp = r.post(f"{BE_URL}projects/{project_guid}/analyses", headers=_HEADERS,
                  json={"analysisName": name}, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["data"]["analysisGuid"]


def _create_scenario(analysis_guid: str, name: str) -> str:
    resp = r.post(f"{BE_URL}analysis/{analysis_guid}/scenario", headers=_HEADERS,
                  json={"scenarioName": name}, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["data"]["scenarioGuid"]


def _delete_scenario(scenario_guid: str) -> None:
    """DELETE /scenario/{scenarioGuid}."""
    resp = r.delete(f"{BE_URL}scenario/{scenario_guid}",
                    headers=_HEADERS, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()


def _reset_scenario(analysis_guid: str, name: str) -> str:
    """Delete any scenario named `name` within the analysis, then create a
    fresh one — a brand-new scenario has no hubs yet, so the hub created
    right after it (see `_get_or_create_hub`) ends up as the scenario's
    only hub, rather than sitting alongside a stale one left over from an
    earlier, differently-named hub."""
    resp = r.get(f"{BE_URL}analysis/{analysis_guid}",
                 headers=_HEADERS, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    for s in resp.json()["data"]["scenarios"]:
        if s.get("scenarioName") == name:
            _delete_scenario(s["scenarioGuid"])
    return _create_scenario(analysis_guid, name)


def _create_impex(scenario_guid: str, name: str, carrier_guid: str, hub_guid: str,
                  stage_guid: str, impex_type: str, price: float) -> str:
    """POST /v2_1/scenario/{guid}/impex -> impex guid.

    `impex_type` is "IMPORT" or "EXPORT"; `price` is energyPriceCHFkWh.
    """
    resp = r.post(f"{BE_URL}v2_1/scenario/{scenario_guid}/impex",
                  headers=_HEADERS,
                  json={"name": name,
                        "energyCarrierGuid": carrier_guid,
                        "type": impex_type,
                        "hubs": [{"hubGuid": hub_guid}],
                        "energyPriceCHFkWh": price,
                        "stages": [stage_guid]},
                  timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["data"]["guid"]


def _close_scenario_diagram(scenario_guid: str) -> int:
    """PUT /sympheny-app/scenarios/{scenarioGuid}/close-diagram.

    Called once a variant scenario is fully built. Unlike most calls in
    this section this one lives under SYMPHENY_BASE_URL, not BE_URL.
    Returns the HTTP status; raises on anything other than 200.
    """
    resp = r.put(f"{SYMPHENY_BASE_URL}sympheny-app/scenarios/{scenario_guid}"
                 f"/close-diagram",
                 data=None, headers=_HEADERS, timeout=HTTP_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"close-diagram returned HTTP {resp.status_code}")
    return resp.status_code


def _scenario_url(scenario_guid: str) -> str:
    resp = r.get(f"{BE_URL}scenario/{scenario_guid}/frontend-url",
                 headers=_HEADERS, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["data"]["frontendUrl"]


def _copy_scenario_gis(scenario_guid_from: str, scenario_guid_to: str) -> None:
    """PUT /scenarios/copy/{scenarioGuid}/gis?scenarioGuidTo=... — copies the
    GIS layer already fetched into the step-1 site scenario onto another
    (variant) scenario."""
    resp = r.put(f"{BE_URL}scenarios/copy/{scenario_guid_from}/gis",
                 headers=_HEADERS,
                 params={"scenarioGuidTo": scenario_guid_to},
                 timeout=HTTP_TIMEOUT)
    resp.raise_for_status()


def _get_or_create_hub(scenario_guid: str, name: str = HUB_NAME) -> str:
    """Reuse the hub called `name`, or create it."""
    resp = r.get(f"{BE_URL}scenarios/{scenario_guid}/hubs",
                 headers=_HEADERS, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    for h in resp.json()["data"] or []:
        if h.get("hubName") == name:
            return h["hubGuid"]
    created = r.post(f"{BE_URL}scenarios/{scenario_guid}/hubs", headers=_HEADERS,
                     json={"hubName": name}, timeout=HTTP_TIMEOUT)
    created.raise_for_status()
    return created.json()["data"]["hubGuid"]


def _get_or_create_stage(scenario_guid: str, name: str = STAGE_NAME) -> str:
    """Reuse the stage called `name`, or create it."""
    resp = r.get(f"{BE_URL}scenarios/{scenario_guid}/stages",
                 headers=_HEADERS, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    stages = resp.json()["data"] or []
    for s in stages:
        if s.get("name") == name:
            return s["guid"]
    created = r.post(f"{BE_URL}scenarios/{scenario_guid}/stages", headers=_HEADERS,
                     json={"name": name, "index": len(stages) + 1, "length": 1},
                     timeout=HTTP_TIMEOUT)
    created.raise_for_status()
    return created.json()["data"]["guid"]


# ------------------------------------------------- step 1: GIS retrieval
def _get_or_create_project(name: str) -> dict:
    """Reuse the project called `name`, or create it (never deletes)."""
    resp = r.get(f"{BE_URL}projects", headers=_HEADERS, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    for p in resp.json()["data"]["projects"]:
        if p["projectName"] == name:
            return p
    created = r.post(f"{BE_URL}projects", headers=_HEADERS,
                     json={"projectName": name, "version": "V2"},
                     timeout=HTTP_TIMEOUT)
    created.raise_for_status()
    return created.json()["data"]


def _get_or_create_analysis(project_guid: str, name: str) -> str:
    """Reuse the analysis called `name` within a project, or create it."""
    resp = r.get(f"{BE_URL}projects/{project_guid}/analyses",
                 headers=_HEADERS, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    for a in resp.json()["data"] or []:
        if a.get("analysisName") == name:
            return a["analysisGuid"]
    return _create_analysis(project_guid, name)


def _gis_create_hub_job(scenario_guid: str, hub_guid: str, hub_name: str,
                        polygon_lonlat: list) -> str:
    """Kick off the background GIS-population job for a hub.

    `polygon_lonlat` is a closed ring of [lon, lat] pairs (standard GeoJSON
    order — the same order `site["polygon"]` is stored in, so it can be
    passed straight through). Returns the background job id.
    """
    url = (f"{SYMPHENY_BASE_URL}api-services/gis/background/scenarios/"
           f"{scenario_guid}/hubs/{hub_guid}?geoadmin=true")
    payload = {
        "hub_name": hub_name,
        "feature": {"type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [polygon_lonlat]}},
    }
    resp = r.post(url, headers=_HEADERS, json=payload, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["job_id"]


def _gis_wait_job(out, job_id: str,
                  max_attempts: int = GIS_JOB_MAX_ATTEMPTS,
                  poll_seconds: float = GIS_JOB_POLL_SECONDS) -> None:
    """Poll the GIS background-job endpoint until `job_id` reports done."""
    for i in range(1, max_attempts + 1):
        try:
            resp = r.get(f"{SYMPHENY_BASE_URL}api-services/gis/background",
                         headers=_HEADERS, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            job = next((x for x in resp.json() if x.get("job_id") == job_id), None)
            if job and job.get("is_done"):
                return
        except Exception:
            pass  # transient poll failure — keep trying until max_attempts
        if i == 1 or i % 5 == 0:
            out.print(f"    – waiting for GIS job… {i}s elapsed")
        time.sleep(poll_seconds)
    raise TimeoutError(f"GIS job {job_id} did not complete within {max_attempts} seconds")


def _gis_fetch(scenario_guid: str, hub_guid: str) -> dict:
    """GET the populated GIS data (building_layer + addresses) for a hub."""
    url = f"{SYMPHENY_BASE_URL}api-services/gis/scenarios/{scenario_guid}/hubs/{hub_guid}"
    resp = r.get(url, headers=_HEADERS, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _load_site_gis(out, polygon_lonlat: list) -> tuple:
    """End-to-end: ensure the GIS scenario/hub exist, populate them from the
    drawn polygon, wait for the background job, then fetch and return the
    GIS payload (`building_layer` features + `addresses`) together with the
    scenario guid it lives in — the latter is later used in step 4 to copy
    this same GIS layer onto every variant scenario.

    The scenario itself is deleted and recreated on every call (rather than
    reused) so it always starts with zero hubs — the hub created right
    after (see `_get_or_create_hub`) then ends up as its only hub, instead
    of sitting alongside a stale hub left over from an earlier load."""
    ring = list(polygon_lonlat)
    if ring[0] != ring[-1]:
        ring = ring + [ring[0]]  # GeoJSON polygons must be closed rings

    out.print("Creating GIS hub from the drawn polygon…")
    project = _get_or_create_project(PROJECT_NAME)
    out.print(f"  · project '{PROJECT_NAME}': {project['projectGuid']}")
    analysis_guid = _get_or_create_analysis(project["projectGuid"], GIS_ANALYSIS_NAME)
    scenario_guid = _reset_scenario(analysis_guid, GIS_SCENARIO_NAME)
    hub_guid = _get_or_create_hub(scenario_guid, HUB_NAME)
    out.print(f"  · scenario: {scenario_guid}  ·  hub: {hub_guid}")

    job_id = _gis_create_hub_job(scenario_guid, hub_guid, HUB_NAME, ring)
    out.print(f"  · background job {job_id} started")
    _gis_wait_job(out, job_id)
    out.print("  · job complete — fetching GIS data…")

    data = _gis_fetch(scenario_guid, hub_guid)
    features = (data.get("building_layer") or {}).get("features", [])
    addresses = data.get("addresses") or []
    out.print(f"✓ {len(features)} building(s), {len(addresses)} address(es) loaded.")
    return data, scenario_guid


_SOLAR_CACHE = {}   # (lon, lat, area) -> 8760-value solar series


def _feature_lonlat(feature: dict):
    """Vertex-average centroid (lon, lat) of a building footprint feature.
    Not area-weighted, but fine for picking a representative point for a
    solar lookup."""
    geom = feature.get("geometry") or {}
    gtype = geom.get("type")
    coords = geom.get("coordinates") or []
    if gtype == "Polygon":
        ring = coords[0] if coords else []
    elif gtype == "MultiPolygon":
        ring = coords[0][0] if coords and coords[0] else []
    else:
        ring = []
    pts = [p for p in ring if p and p[0] is not None and p[1] is not None]
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _gis_first_building_lonlat(data: dict):
    """(lon, lat) of the first building in a GIS payload. Prefers
    coordinates carried directly on the address entry (checking the common
    key spellings); falls back to the centroid of the first building_layer
    footprint."""
    addresses = data.get("addresses") or []
    if addresses:
        a = addresses[0]
        lon = a.get("lon", a.get("longitude"))
        lat = a.get("lat", a.get("latitude"))
        if lon is not None and lat is not None:
            return float(lon), float(lat)
    features = (data.get("building_layer") or {}).get("features") or []
    if features:
        return _feature_lonlat(features[0])
    return None


def _gis_total_area(data: dict) -> float:
    """Sum of building_ground_area across every address in a GIS payload —
    the same field the Sympheny demand calls use for GFA (see
    `_buildings_from_gis_addresses`). Falls back to per-feature properties
    if the addresses carry no area."""
    addresses = data.get("addresses") or []
    total = sum(float(a.get("building_ground_area") or 0.0) for a in addresses)
    if total > 0:
        return total
    features = (data.get("building_layer") or {}).get("features") or []
    return sum(
        float((f.get("properties") or {}).get("building_ground_area")
              or (f.get("properties") or {}).get("area") or 0.0)
        for f in features
    )


def _fetch_solar_profile(lon: float, lat: float, area: float) -> list:
    """8760 h solar profile [kW] for one point + surface area."""
    key = (round(lon, 5), round(lat, 5), round(area, 1))
    if key in _SOLAR_CACHE:
        return _SOLAR_CACHE[key]
    payload = [{"lon": lon, "lat": lat, "area": area}]
    resp = r.post(f"{SYMPHENY_BASE_URL}api-services/jrc/solar/profile",
                  headers=_HEADERS, json=payload, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    series = resp.json()
    if len(series) != 8760:
        raise ValueError(f"solar profile: expected 8760 periods, got {len(series)}")
    _SOLAR_CACHE[key] = series
    return series


def _avg24_series(series: list) -> list:
    """Collapse an 8760 h series to its 24 h daily average — same
    reduction `_fetch_carrier` applies to demand series."""
    return [sum(series[h::24]) / 365.0 for h in range(24)]


def _import_technologies(scenario_guid: str, hub_guid: str, techs: list,
                         guid_of: dict) -> tuple:
    """Import the variant's database technologies into the hub.

    Runs BEFORE the demands so the carriers the technologies bring in can be
    reused. Returns (imported_count, http_status, unmapped_names).
    """
    guids, unmapped = [], []
    for t in techs:
        guid = guid_of.get(APP_TO_DB.get(t, ""))
        (guids.append(guid) if guid else unmapped.append(t))
    if not guids:
        return 0, None, unmapped
    resp = r.post(
        f"{BE_URL}scenarios/{scenario_guid}/hubs/{hub_guid}"
        f"/import-database-technology-package?technologiesOptional=true",
        headers=_HEADERS, json={"conversionTechGuids": guids},
        timeout=HTTP_TIMEOUT)
    return len(guids), resp.status_code, unmapped


def _carriers_by_subtype(scenario_guid: str) -> dict:
    """subtypeKey -> energyCarrierGuid for everything already in the scenario."""
    resp = r.get(f"{BE_URL}scenarios/{scenario_guid}/carriers",
                 headers=_HEADERS, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    found = {}
    for c in (resp.json()["data"] or {}).get("energyCarriers", []) or []:
        # Imported technologies name their carriers "HEAT_4@tp=25447"; the
        # subtype is the part before the "@".
        key = (c.get("subtypeKey") or "").upper().split("@")[0].strip()
        if key and key not in found:          # first one wins
            found[key] = c["energyCarrierGuid"]
    return found


def _create_carrier(scenario_guid: str, carrier: str) -> str:
    """POST /v2/scenarios/{guid}/carriers -> energyCarrierGuid."""
    resp = r.post(f"{BE_URL}v2/scenarios/{scenario_guid}/carriers", headers=_HEADERS,
                  json={"energyCarrierName": CARRIER_FULL_NAME[carrier],
                        "subType": CARRIER_SUBTYPE[carrier],
                        "colorHexCode": CARRIER_COLOR[carrier]},
                  timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["data"]["energyCarrierGuid"]


def _upload_profile(scenario_guid: str, name: str, series: list) -> int:
    """POST /scenarios/{guid}/profiles-json -> profile id.

    The endpoint wants exactly 8760 entries, periods 1..8760, positive values.
    """
    values = [{"period": i + 1, "demandValue": round(max(0.0, v), 6)}
              for i, v in enumerate(series)]
    resp = r.post(f"{BE_URL}scenarios/{scenario_guid}/profiles-json", headers=_HEADERS,
                  json={"name": name, "values": values}, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["data"]["id"]


def _create_energy_demand(scenario_guid: str, name: str, carrier_guid: str,
                          profile_id: int, hub_guid: str, stage_guid: str) -> str:
    """POST /v2_1/scenarios/{guid}/energy-demands -> energyDemandGuid."""
    resp = r.post(f"{BE_URL}v2_1/scenarios/{scenario_guid}/energy-demands",
                  headers=_HEADERS,
                  json={"name": name,
                        "hubGuids": [hub_guid],
                        "energyCarrierGuid": carrier_guid,
                        "demandProfileId": profile_id,
                        "demandScalingFactor": 1,
                        "stages": [stage_guid]},
                  timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["data"]["energyDemandGuid"]


def _create_solar_on_site_resource(scenario_guid: str, hub_guid: str, stage_guid: str,
                                   carrier_guid: str, profile_id: int,
                                   area: float) -> str:
    """POST /v2_1/scenarios/{guid}/solar-on-site-resource -> solarResourceGuid.

    `carrier_guid` must be a carrier whose subType is one of the resource
    types the endpoint accepts (SOLAR_ROOF, BIOMASS, GEOTHERMAL, HYDRO,
    PROCESS_WASTE_HEAT, SOLAR_FACADE, SOLAR_PARAPET, TIDAL, WIND) — here the
    SOLAR_ROOF carrier the "Solar PV - Roof" import already created (see
    SOLAR_RESOURCE_SUBTYPE), reused rather than created again.
    `area` is reported to Sympheny as an "Area"-type available resource,
    i.e. it must be expressed in the same m² the collector area is
    metered in — here the same site-total roof area the JRC profile
    (`profile_id`) itself was fetched for, so the two stay consistent.
    """
    resp = r.post(f"{BE_URL}v2_1/scenarios/{scenario_guid}/solar-on-site-resource",
                  headers=_HEADERS,
                  json={"name": "Solar irradiance – site total",
                        "energyCarrierGuid": carrier_guid,
                        "hubs": [{"hubGuid": hub_guid,
                                  "availableSolarCollectorArea": area,
                                  "availableResourceType": "Area"}],
                        "profileId": profile_id,
                        "stages": [stage_guid]},
                  timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["data"]["solarResourceGuid"]


def _populate_scenario(out, scenario_guid: str, agg: dict, var: dict,
                       guid_of: dict, solar_series: list = None,
                       solar_area: float = None) -> None:
    """Hub + stage + technologies first, then the solar on-site resource
    (if this variant has Solar PV and step 1 fetched a site solar profile),
    then demands on reused carriers."""
    hub_guid = _get_or_create_hub(scenario_guid)
    stage_guid = _get_or_create_stage(scenario_guid)

    count, status, unmapped = _import_technologies(
        scenario_guid, hub_guid, var["techs"], guid_of)
    out.print(f"    – technologies: {count} imported"
              + (f" (HTTP {status})" if status is not None else " — nothing to import"))
    if unmapped:
        out.print(f"    ⚠ no database match for: {', '.join(unmapped)}")

    existing = _carriers_by_subtype(scenario_guid)
    out.print(f"    – carriers in scenario after import: "
              f"{', '.join(sorted(existing)) or 'none'}")

    if "Solar PV" in var["techs"]:
        if not solar_series or max(solar_series) <= 0:
            out.print("    ⚠ Solar PV selected but no site solar profile is "
                      "available — load GIS data in step 1 first. Skipping "
                      "on-site resource.")
        else:
            resource_carrier_guid = existing.get(SOLAR_RESOURCE_SUBTYPE)
            if not resource_carrier_guid:
                out.print(f"    ⚠ Solar PV selected but no "
                          f"{SOLAR_RESOURCE_SUBTYPE} carrier was created by "
                          f"the import — skipping on-site resource.")
            else:
                solar_profile_id = _upload_profile(
                    scenario_guid, "Solar irradiance – site total", solar_series)
                resource_guid = _create_solar_on_site_resource(
                    scenario_guid, hub_guid, stage_guid,
                    resource_carrier_guid, solar_profile_id, solar_area or 0.0)
                out.print(f"    – solar on-site resource (reused "
                          f"{SOLAR_RESOURCE_SUBTYPE} carrier): "
                          f"{solar_area or 0.0:,.0f} m² · "
                          f"profile #{solar_profile_id} · {resource_guid}")

    for carrier, _color in CARRIERS:
        series = agg.get(carrier) or []
        if not series or max(series) <= 0:
            out.print(f"    – {carrier}: no demand, skipped")
            continue
        subtype = CARRIER_SUBTYPE[carrier]
        carrier_guid = existing.get(subtype)
        if carrier_guid:
            origin = f"reused {subtype}"
        else:
            carrier_guid = _create_carrier(scenario_guid, carrier)
            existing[subtype] = carrier_guid
            origin = f"created {subtype}"
        profile_id = _upload_profile(
            scenario_guid, f"{CARRIER_FULL_NAME[carrier]} – site total", series)
        _create_energy_demand(
            scenario_guid, f"{CARRIER_FULL_NAME[carrier]} demand",
            carrier_guid, profile_id, hub_guid, stage_guid)
        out.print(f"    – {carrier} ({origin}): {sum(series) / 1000:,.0f} MWh/y · "
                  f"peak {max(series):,.0f} kW · profile #{profile_id}")


def _create_variant_scenario(out, analysis_guid: str, var: dict, agg: dict,
                             guid_of: dict, gis_scenario_guid: str = None,
                             solar_series: list = None,
                             solar_area: float = None) -> str:
    """One scenario per variant. Returns its frontend URL."""
    scenario_guid = _create_scenario(analysis_guid, var["name"])
    # Hub, stage, technologies and demands first — the GIS copy below needs
    # this scenario's own hub to already exist.
    _populate_scenario(out, scenario_guid, agg, var, guid_of,
                       solar_series, solar_area)
    if gis_scenario_guid:
        try:
            _copy_scenario_gis(gis_scenario_guid, scenario_guid)
            out.print(f"    – GIS data copied from site scenario "
                      f"{gis_scenario_guid}")
        except Exception as exc:
            out.print(f"    ⚠ GIS copy failed: {type(exc).__name__}: {exc}")
    else:
        out.print("    – no GIS data loaded in step 1, skipping GIS copy")

    # Electricity import/export, if this scenario ended up with an
    # ELECTRICITY carrier at all — it may come from the technology import
    # (e.g. a heat pump's input) or from the demand step, so this is
    # re-read here rather than assumed.
    elec_subtype = CARRIER_SUBTYPE["Elec"]
    elec_carrier_guid = _carriers_by_subtype(scenario_guid).get(elec_subtype)
    if elec_carrier_guid:
        hub_guid = _get_or_create_hub(scenario_guid)
        stage_guid = _get_or_create_stage(scenario_guid)
        for impex_type in ("IMPORT", "EXPORT"):
            _create_impex(
                scenario_guid,
                f"Electricity {impex_type.lower()}",
                elec_carrier_guid, hub_guid, stage_guid,
                impex_type, IMPEX_ELEC_PRICE[impex_type])
        out.print(f"    – electricity import @ "
                  f"{IMPEX_ELEC_PRICE['IMPORT']:,.0f} · export @ "
                  f"{IMPEX_ELEC_PRICE['EXPORT']:,.0f} CHF/kWh")
    else:
        out.print(f"    – no {elec_subtype} carrier, skipping import/export")

    # Everything for this variant is in place — close its diagram last.
    _close_scenario_diagram(scenario_guid)
    out.print("    – diagram closed")
    return scenario_guid, _scenario_url(scenario_guid)


def _submit_solver_job(scenario_guid: str, scenario_name: str) -> None:
    """POST /sense-api/ext/solver/jobs — queue an optimisation run."""
    payload = [{
        "objective1": SOLVER_OBJECTIVE,
        "objective2": None,
        "scenarioGuid": scenario_guid,
        "scenarioName": scenario_name,
        "name": "j",
        "clientType": "APP",
        "temporalResolution": SOLVER_TEMPORAL_RESOLUTION,
        "points": SOLVER_POINTS,
        "timeLimit": SOLVER_TIME_LIMIT,
        "mipGap": SOLVER_MIP_GAP,
    }]
    resp = r.post(f"{SYMPHENY_BASE_URL}sense-api/ext/solver/jobs",
                  headers=_HEADERS, json=payload, timeout=HTTP_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"solver job returned HTTP {resp.status_code}")


def _wait_solver_job(out, scenario_guid: str) -> str:
    """Poll until the scenario's solver jobs report terminated; return the
    job id to build the dashboard URL from."""
    payload = {"scenarioGuids": [scenario_guid], "limit": SOLVER_WAIT_SECONDS}
    jobs = []
    for i in range(max(1, SOLVER_WAIT_SECONDS // SOLVER_POLL_SECONDS)):
        resp = r.post(f"{SYMPHENY_BASE_URL}sense-api/ext/solver/jobs/get-scenarios",
                      headers=_HEADERS, json=payload, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        jobs = [j for j in resp.json() if j["scenarioGuid"] == scenario_guid]
        if jobs and not [j for j in jobs if not j["terminated"]]:
            return jobs[0]["id"]
        out.print(f"    – waiting for solver… {i * SOLVER_POLL_SECONDS}s elapsed")
        time.sleep(SOLVER_POLL_SECONDS)
    raise TimeoutError(f"solver job did not finish within {SOLVER_WAIT_SECONDS}s")


def _dashboard_url(analysis_guid: str, job_id) -> str:
    """Frontend URL of a solved scenario's dashboard."""
    domain = "app.dev.sympheny.com" if "dev" in BE_URL else "app.sympheny.com"
    resp = r.get(f"{BE_URL}analysis/{analysis_guid}",
                 headers=_HEADERS, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    project_guid = resp.json()["data"]["projectGuid"]
    return (f"https://{domain}/projects/{project_guid}/analysis/{analysis_guid}"
            f"/execution/{job_id}/solution/1")


def _work_submit(out, buildings, variants, site):
    """Create one Sympheny scenario per variant, then solve the first one
    and print its dashboard URL."""
    out.print(f"Creating {len(variants)} scenario(s) from {len(buildings)} "
              f"building type(s)…")

    agg = _aggregate_series(buildings)
    skipped = [b["name"] for b in buildings if b.get("_error")]
    if skipped:
        out.print(f"  ⚠ excluded from the aggregate (no demand data): "
                  f"{', '.join(skipped)}")
    if all(max(s) <= 0 for s in agg.values()):
        out.print("✗ no demand data at all — go back to step 2 and fix the errors.")
        return

    gis_scenario_guid = site.get("gis_scenario_guid")
    solar_series = site.get("solar_series")
    solar_area = site.get("solar_area")

    try:
        guid_of = _db_tech_index()
        out.print(f"  · database technologies: {len(guid_of)}")
        # Reuse the project instead of deleting/recreating it — the
        # step-1 GIS scenario lives in this same project and must survive
        # a submit. Only the variants' own analysis is reset.
        project = _get_or_create_project(PROJECT_NAME)
        out.print(f"  · project '{PROJECT_NAME}': {project['projectGuid']}")
        analysis_guid = _reset_analysis(project["projectGuid"], PROJECT_NAME)
        out.print(f"  · analysis: {analysis_guid}")
    except Exception as exc:
        out.print(f"✗ setup failed — {type(exc).__name__}: {exc}")
        return

    created = []
    for var in tqdm_out(variants, out):
        out.print(f"  • {var['name']}")
        try:
            scenario_guid, url = _create_variant_scenario(
                out, analysis_guid, var, agg, guid_of, gis_scenario_guid,
                solar_series, solar_area)
            created.append((var["name"], scenario_guid, url))
        except Exception as exc:
            out.print(f"    ✗ {type(exc).__name__}: {exc}")

    if not created:
        out.print("✗ no scenario was created.")
        return

    out.print("")
    out.print(f"✓ {len(created)} scenario(s) created. First scenario:")
    out.print(created[0][2])

    # Solve the first scenario so the run ends on a dashboard link.
    name, scenario_guid, _url = created[0]
    out.print("")
    out.print(f"Running the optimisation for '{name}'…")
    try:
        _submit_solver_job(scenario_guid, name)
        job_id = _wait_solver_job(out, scenario_guid)
        out.print("✓ optimisation finished. Dashboard:")
        out.print(_dashboard_url(analysis_guid, job_id))
    except Exception as exc:
        out.print(f"✗ optimisation failed — {type(exc).__name__}: {exc}")