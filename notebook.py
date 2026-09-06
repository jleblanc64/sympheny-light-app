"""Four-step configuration wizard (Voila / ipywidgets).

1 Site location    : draw a polygon on an ipyleaflet map; "Load GIS data" fetches
                     real footprints plus a site solar profile.
2 Site & buildings : building-type list + form, KPIs, aggregated totals. Demand
                     comes from the Sympheny API (use -> building_type,
                     GFA -> building_ground_area); all building x carrier calls
                     run in one batch.
3 System variants  : side-by-side variants, each a set of technologies.
4 Summary          : read-only recap; Submit creates one Sympheny scenario per
                     variant (hub, stage, technology package, aggregated 8760 h
                     demands), solves the first one and prints its dashboard URL.

UI first, then every backend call under the "## BACKEND API CALLS" banner.
"""
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
from utils_token import token_to_user

CONTENT_MIN_PX = 560
CHART_PREVIEW_PX, CHART_PREVIEW_W, CHART_COMBINED_PX, CHART_SOLAR_PX = 120, 470, 150, 175
STEP_DEFS = [("1", "Site location"), ("2", "Site & buildings"), ("3", "System variants"), ("4", "Summary")]
TEAL, INK, MUTED, LINE = "#0f9d8f", "#1f2933", "#8a94a0", "#e3e8ee"

WZ_CSS = """
<style>
:root{--teal:#0f9d8f;--ink:#1f2933;--muted:#8a94a0;--line:#e3e8ee;--deep:#0b5f57;--red:#b3312c}
[class*="wz-"]:not(button),[class*="wz-"] :is(div,span,p,li,th,td,label,pre,h1,h2,h3,h4){color:var(--c,inherit) !important}
/*base*/ [class*="wz-"]{font-family:sans-serif}.wz-cat,.wz-kpi,.wz-tot,.wz-tag,.wz-err,.wz-band h4{font-family:monospace}.wz-caption,.wz-sub,.wz-cat,.wz-kpi .sub,.wz-sum td.k,.wz-tech-sub,.wz-loader{--c:var(--muted)}.wz-title,.wz-kpi .val,.wz-sum td.v,.wz-tot,.wz-tech-name,.wz-modal-title{--c:var(--ink)}.wz-kpi,.wz-side,.wz-sum,.wz-loader,.wz-err{border:1px solid var(--line);border-radius:10px;background:#fff}
/*nav*/ .wz-nav{--c:#dbe3ec;background:#1b2534 !important;border-radius:10px;padding:0 14px;height:56px;display:flex;align-items:center;gap:4px;margin:0 0 14px}.wz-nav .crumb{display:flex;align-items:center;gap:9px;padding:7px 14px;font-size:14px;border-radius:20px}.wz-nav .crumb.done{--c:#f0f4f8}.wz-nav .crumb.active{--c:#fff;font-weight:700;background:rgba(255,255,255,.14)}.wz-nav .sep{--c:#9aa7b8;font-size:13px;padding:0 2px}.wz-nav .dot{--c:#fff;flex:0 0 24px;width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:#5a6a7e;font-size:12px;font-weight:700}.wz-nav .crumb.done .dot{background:var(--teal)}.wz-nav .crumb.active .dot{background:var(--teal);box-shadow:0 0 0 3px #0f9d8f55}
/*text*/ .wz-title{font-size:15px;font-weight:600;margin:0 0 8px}.wz-caption{font-size:11px;margin:1px 0 6px 2px}.wz-sub{font-size:11px;margin:-6px 0 5px 26px}.wz-cat{font-size:10px;letter-spacing:.1em;text-transform:uppercase;margin:9px 0 3px}.wz-label{--c:#4a5568;font-size:11px;margin:0 0 3px 2px}
/*kpi*/ .wz-kpi{padding:8px 14px;min-width:118px}.wz-kpi .lab{font-size:10px;letter-spacing:.08em;text-transform:uppercase}.wz-kpi .val{font-size:21px;font-weight:700;line-height:1.25}.wz-kpi .sub{font-size:10px}.wz-row{display:flex;gap:10px;flex-wrap:wrap;margin:2px 0}
/*band+side*/ .wz-band{background:#f3faf9;border:1px solid #d9ece9;border-radius:10px;padding:10px 14px;margin:6px 0 4px}.wz-band h4,.wz-sum h3{--c:var(--deep);text-transform:uppercase}.wz-band h4{margin:0 0 7px;font-size:11px;letter-spacing:.1em}.wz-side{padding:8px 12px;background:#fafbfc}.wz-tot{font-size:12px;line-height:1.8}.wz-tot span{float:right;font-weight:700}
/*summary*/ .wz-sum{padding:14px 18px;border-radius:12px;margin:0 0 12px}.wz-sum h3{margin:0 0 8px;font-size:12px;letter-spacing:.08em}.wz-sum table{border-collapse:collapse;width:100%;font-size:13px}.wz-sum td{padding:5px 8px;border-bottom:1px solid #f0f2f5;vertical-align:top}.wz-sum td.k{width:190px}.wz-sum td.v{font-weight:600}
/*chips+tech*/ .wz-chip{display:inline-block;padding:2px 9px;border-radius:11px;font-size:11px;font-weight:600;margin:2px 6px 2px 0}.wz-tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:10px;font-weight:700;letter-spacing:.06em;vertical-align:middle}.wz-tag.err,.wz-err{--c:var(--red);background:#fdecec;border:1px solid #f4c9c7}.wz-tech-name{font-size:13px;font-weight:600;line-height:1.25}.wz-tech-sub{font-size:11px}
/*loader+error*/ @keyframes wz-spin{to{transform:rotate(360deg)}}.wz-loader{display:flex;align-items:center;justify-content:center;gap:10px;border-style:dashed;background:#fcfdfe;font-size:11px}.wz-loader .ring{flex:0 0 20px;width:20px;height:20px;border-radius:50%;border:2.5px solid var(--line);border-top-color:var(--teal);animation:wz-spin .8s linear infinite}.wz-err{padding:8px 12px;font-size:11px;margin:4px 0}
/*inputs*/ .widget-text input,.widget-dropdown>select{border:1px solid #d7dde5 !important;border-radius:8px !important;height:32px !important;padding:2px 10px !important;font-size:13px !important;color:var(--ink) !important;background:#fff !important;box-shadow:none !important}.widget-text input:focus,.widget-dropdown>select:focus{border-color:var(--teal) !important;outline:none !important;box-shadow:0 0 0 2px #0f9d8f22 !important}
/*buttons*/ button.jupyter-button{border:1px solid #d7dde5 !important;border-radius:8px !important;box-shadow:none !important;font-family:sans-serif !important;font-size:13px !important}button.jupyter-button:hover{filter:brightness(.97)}.jupyter-button.wz-pill{border-radius:20px !important;font-weight:600 !important;height:36px !important}.jupyter-button.wz-primary{background:var(--teal) !important;border-color:var(--teal) !important;color:#fff !important}.jupyter-button.wz-ghost{background:#fff !important;color:var(--ink) !important}.jupyter-button.wz-chipbtn{height:30px !important;border-radius:7px !important;font-family:monospace !important}
/*buttons2*/ .jupyter-button.wz-listitem,.jupyter-button.wz-pick{border-radius:9px !important;justify-content:flex-start !important;text-align:left !important}.jupyter-button.wz-pick,.jupyter-button.wz-addtech{background:#fff !important;border-radius:10px !important}.jupyter-button.wz-pick{border:1px solid var(--line) !important;color:var(--ink) !important}.jupyter-button.wz-addtech{border:1px dashed #cbd3dd !important;color:var(--muted) !important;font-size:12px !important}.jupyter-button.wz-pick:hover{border-color:var(--teal) !important;background:#f3faf9 !important}.jupyter-button.wz-addtech:hover{border-color:var(--teal) !important;color:var(--teal) !important}.jupyter-button.wz-x{background:transparent !important;border:none !important;color:var(--muted) !important;font-size:14px !important;border-radius:50% !important}.jupyter-button.wz-x:hover{background:#f2f4f7 !important;color:#e0524d !important}
/*modal*/ .wz-modal{position:fixed !important;inset:0;background:rgba(17,25,36,.45);z-index:9999;align-items:center !important;justify-content:center !important}.wz-modal-card{background:#fff !important;border-radius:14px !important;padding:18px 20px !important;width:520px !important;max-height:74vh !important;overflow:auto !important;box-shadow:0 18px 50px rgba(0,0,0,.28) !important}.wz-modal-title{font-size:15px;font-weight:700;margin:0 0 2px}
</style>
"""

# --------------------------------------------------------------- domain data
CARRIERS = [("Heat", "#e0524d"), ("Elec", "#1fab8c"), ("DHW", "#f2a93b")]
CARRIER_COLOR = dict(CARRIERS)
SOLAR_COLOR, SOLAR_COLOR_LINE = "#f5a623", "#d98d12"
USE_TYPES = ["RESIDENCE_MFH", "RESIDENCE_SFH", "ADMINISTRATION", "OFFICES", "SCHOOLS", "RETAIL", "RESTAURANT",
             "ASSEMBLY", "HOSPITALS", "INDUSTRY", "WAREHOUSE", "SPORTS_CENTER", "INDOOR_POOL", "HOTEL"]
PERIODS = ["< 1950", "1950–1970", "1970–1990", "1990–2000", "2000–2010", "> 2010"]
CLIMATE_ZONES = ["Zürich, CH", "Genève, CH", "Basel, CH", "Lugano, CH", "Lyon, FR", "Milano, IT", "München, DE"]
# EPC class is descriptive metadata only — the demand comes from the API.
EPC_COLOR = {"A": "#2e9e4f", "B": "#6cb33f", "C": "#b7cf2b", "D": "#ef7215", "E": "#e8546a", "F": "#b45ad0", "G": "#8a94a0"}
DEFAULT_BUILDINGS = [
    {"name": "Residential MFH", "use": "RESIDENCE_MFH", "period": "1990–2000", "renovated": "No", "gfa": 23460.0, "zone": "Zürich, CH", "diversity": 8.0, "epc": "D"},
    {"name": "Offices", "use": "OFFICES", "period": "2000–2010", "renovated": "Yes", "gfa": 4800.0, "zone": "Zürich, CH", "diversity": 12.0, "epc": "C"},
    {"name": "Retail", "use": "RETAIL", "period": "1970–1990", "renovated": "No", "gfa": 1200.0, "zone": "Zürich, CH", "diversity": 15.0, "epc": "E"},
]
TECH_CATALOG = {
    "Heat supply": [("Gas boiler", "η 92% · gas import · CH grid tariff", "🔥"),
                    ("Air-source heat pump", "COP 3.0 · elec import", "💧"),
                    ("Ground-source HP", "COP 4.5 · borehole", "🌡️"),
                    ("Wood pellet boiler", "η 88% · pellet price CH", "🪵")],
    "Electricity & renewables": [("Solar PV", "Roof area from GIS", "☀️"),
                                 ("CHP unit", "Gas engine · heat-led", "⚙️")],
}
TECH_INDEX = {n: (c, s, i) for c, items in TECH_CATALOG.items() for n, s, i in items}
VARIANT_COLORS = [TEAL, "#1a6fc4", "#e0952b", "#9c1a6f", "#5a4fcf"]
DEFAULT_VARIANTS = [
    {"name": "Heat pump + Solar PV", "techs": ["Air-source heat pump", "Solar PV", "Gas boiler"]},
    {"name": "Status quo / Gas boiler", "techs": ["Gas boiler"]},
    {"name": "District heating + PV", "techs": ["Solar PV"]},
]
# Default site outline, given as [lat, lon]; stored and consumed as [lon, lat] (GeoJSON order).
_DEFAULT_LATLON = [[46.238324, 6.206312], [46.238034, 6.206817], [46.238348, 6.20709],
                   [46.238604, 6.20665], [46.238324, 6.206312]]
DEFAULT_POLYGON = [[lon, lat] for lat, lon in _DEFAULT_LATLON]
DEFAULT_MAP_CENTER = tuple(sum(p[i] for p in _DEFAULT_LATLON) / len(_DEFAULT_LATLON) for i in (0, 1))


# ----------------------------------------------------------------- UI pieces
def _btn(desc, *cls, w=None, h="34px", tip="", m=None):
    b = widgets.Button(description=desc, tooltip=tip, layout=widgets.Layout(width=w, height=h, margin=m))
    for c in cls:
        b.add_class(c)
    return b


def _vcolor(vi):
    return VARIANT_COLORS[vi % len(VARIANT_COLORS)]


def _closed(ring):
    """GeoJSON polygons must be closed."""
    ring = list(ring)
    return ring if ring[0] == ring[-1] else ring + [ring[0]]


def _w(width):
    return f"width:{width}px;" if width else "width:100%;"


def _loader(label, height, width=None):
    return HTML(f"<div class='wz-loader' style='{_w(width)}height:{height}px'>"
                f"<div class='ring'></div><span>{label}</span></div>")


def _error_box(msg, height, width=None):
    return HTML(f"<div class='wz-err' style='{_w(width)}min-height:{height}px;display:flex;align-items:center'>⚠ {msg}</div>")


def _loading_html(label="Loading…", big=False):
    box = "width:420px;height:88px;gap:16px" if big else "width:260px;height:64px"
    ring = " style='width:32px;height:32px;border-width:3.5px;flex:0 0 32px'" if big else ""
    txt = f" style='font-size:15px;font-weight:700;letter-spacing:.04em;--c:{INK}'" if big else ""
    return HTML(f"<div style='min-height:{CONTENT_MIN_PX}px;display:flex;align-items:center;justify-content:center'>"
                f"<div class='wz-loader' style='border:none;background:transparent;{box}'>"
                f"<div class='ring'{ring}></div><span{txt}>{label}</span></div></div>")


def _kpi(label, value, sub, color):
    return (f"<div class='wz-kpi'><div class='lab' style='--c:{color}'>{label}</div>"
            f"<div class='val'>{value}</div><div class='sub'>{sub}</div></div>")


def _render_nav_html(active):
    parts = []
    for i, (num, label) in enumerate(STEP_DEFS):
        cls = "active" if i == active else ("done" if i < active else "")
        parts.append(f"<div class='crumb {cls}'><div class='dot'>{'✓' if i < active else num}</div><span>{label}</span></div>")
    sep = "<div class='sep'>▸</div>"
    return f"<div class='wz-nav'>{sep.join(parts)}</div>"


def _profile_fig(curves, title, height, width=None):
    """`curves` maps a carrier to its 24 hourly values in kW (daily average)."""
    fig = go.Figure()
    for name, color in CARRIERS:
        y = curves.get(name) or []
        if y and max(y) > 0:
            fig.add_trace(go.Bar(x=list(range(24)), y=[round(v, 2) for v in y], name=name, marker_color=color,
                                 hovertemplate=f"{name} · %{{x}}h · %{{y}} kW<extra></extra>"))
    fig.update_layout(
        title=dict(text=title, font=dict(size=11), x=0, y=0.97) if title else None,
        barmode="group", height=height, width=width, margin=dict(l=40, r=8, t=26 if title else 8, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0.34, font=dict(size=10)),
        xaxis=dict(showticklabels=False, title="", showgrid=False),
        yaxis=dict(title="", showgrid=False, ticksuffix=" kW", tickfont=dict(size=9)),
        plot_bgcolor="white", paper_bgcolor="white", bargap=0.15, bargroupgap=0.05)
    return fig


def _solar_fig(avg24, height):
    """`avg24` is the site-total solar profile collapsed to 24 hourly values."""
    fig = go.Figure(go.Bar(x=list(range(24)), y=[round(v, 3) for v in avg24], name="Solar",
                           marker=dict(color=SOLAR_COLOR, line=dict(color=SOLAR_COLOR_LINE, width=0.6)),
                           hovertemplate="%{x}:00 · %{y}<extra></extra>"))
    # Plotly sizes the title box from font.size, so spans LARGER than it get clipped: the sun
    # rides the base size and the text is shrunk. "☀" (U+2600), not the emoji, so the span colour applies.
    fig.update_layout(
        title=dict(text=(f"<span style='color:{SOLAR_COLOR}'>☀</span>"
                         f"<span style='font-size:17px;color:{INK}'>  Solar profile — site total</span>"
                         f"<span style='color:{MUTED};font-weight:400;font-size:13px'>  daily avg of 8760 h</span>"),
                   font=dict(size=30, color=INK), x=0, xanchor="left", y=0.97),
        height=height, showlegend=False, margin=dict(l=42, r=10, t=52, b=32),
        xaxis=dict(tickmode="array", tickvals=[0, 4, 8, 12, 16, 20], ticktext=["0h", "4h", "8h", "12h", "16h", "20h"],
                   showgrid=False, tickfont=dict(size=10, color=MUTED),
                   title=dict(text="Hour of day", font=dict(size=10, color=MUTED))),
        yaxis=dict(title="", showgrid=True, gridcolor=LINE, gridwidth=1, zeroline=False, tickfont=dict(size=9, color=MUTED)),
        plot_bgcolor="white", paper_bgcolor="white", bargap=0.25)
    return fig


# ------------------------------------------------------- step 1: site location
def _build_step_location(site, vbox, spinner_html, on_gis_loaded=None):
    """Draw-a-polygon map. Mutates site["polygon"] ([lon, lat] pairs) as the user draws, and
    site["gis"] / ["gis_scenario_guid"] / ["solar_series"] / ["solar_area"] once "Load GIS data"
    runs — step 4 reuses all four. `vbox`/`spinner_html` are the shell's shared Spinned() area;
    `on_gis_loaded` lets the shell rebuild step 2 from the new addresses."""
    layers = {"site": None, "gis": None}
    m = Map(center=DEFAULT_MAP_CENTER, zoom=18, basemap=basemaps.OpenStreetMap.Mapnik, scroll_wheel_zoom=True,
            layout=widgets.Layout(width="100%", height="480px", border=f"1px solid {LINE}"))
    solar_box = widgets.VBox()

    def _set_layer(key, layer):
        # The draw control's finished shape lives on the frontend and can't be re-driven from
        # Python, so the outline is a plain layer too — exactly one of each is ever visible.
        if layers[key] is not None:
            try:
                m.remove_layer(layers[key])
            except Exception:
                pass
        layers[key] = layer
        if layer is not None:
            m.add_layer(layer)

    def _show_polygon(coords):
        if not coords:
            return _set_layer("site", None)
        _set_layer("site", GeoJSON(
            data={"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [_closed(coords)]}},
            style={"color": TEAL, "weight": 2, "fillColor": TEAL, "fillOpacity": .25}))

    def _clear_gis():
        """Outline changed: buildings and solar from the old polygon are stale."""
        _set_layer("gis", None)
        site.update(gis=None, gis_scenario_guid=None, solar_series=None, solar_area=None)
        solar_box.children = []

    draw = DrawControl(polygon={"shapeOptions": {"color": TEAL, "fillColor": TEAL, "fillOpacity": 0.25}},
                       polyline={}, circlemarker={}, rectangle={}, circle={}, marker={}, edit=True, remove=True)
    m.add_control(draw)

    def _on_draw(_target, action, geo_json):
        if action == "created":
            site["polygon"] = geo_json["geometry"]["coordinates"][0]
        elif action == "edited" and draw.data:
            site["polygon"] = list(draw.data)[-1]["geometry"]["coordinates"][0]
        elif action == "deleted" and not draw.data:
            site["polygon"] = None
        if action in ("created", "edited"):
            draw.clear()                     # drop the control's own shape
        _show_polygon(site.get("polygon"))
        _clear_gis()

    draw.on_draw(_on_draw)
    if site.get("polygon") is None:
        site["polygon"] = [list(p) for p in DEFAULT_POLYGON]
    _show_polygon(site["polygon"])

    def _center(_b=None):
        # fit_bounds needs the container's pixel size, which Voila often doesn't know yet; traitlets always work.
        poly = site.get("polygon")
        if poly:
            lons, lats = [p[0] for p in poly], [p[1] for p in poly]
            m.center = ((min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2)
            m.zoom = 18

    def _work_load_gis(out):
        poly = site.get("polygon")
        if not poly or len(poly) < 3:
            return out.print("✗ draw a polygon on the map before loading GIS data.")
        try:
            data, scenario_guid = _load_site_gis(out, poly)
        except Exception as exc:
            return out.print(f"✗ {type(exc).__name__}: {exc}")
        site["gis"], site["gis_scenario_guid"] = data, scenario_guid
        features = (data.get("building_layer") or {}).get("features", [])
        _set_layer("gis", GeoJSON(data={"type": "FeatureCollection", "features": features},
                                  style={"color": "#1a6fc4", "weight": 1, "fillColor": "#1a6fc4", "fillOpacity": 0.35},
                                  hover_style={"fillOpacity": 0.65}) if features else None)

        solar_box.children = [_loader("Fetching solar profile…", CHART_SOLAR_PX)]
        lonlat, area = _gis_first_building_lonlat(data), _gis_total_area(data)
        site["solar_series"] = site["solar_area"] = None
        if not lonlat or area <= 0:
            solar_box.children = [_error_box("no building footprint/area available for a solar lookup.", CHART_SOLAR_PX)]
        else:
            try:  # kept on `site` so a Solar-PV variant reuses this exact profile in step 4
                series = _fetch_solar_profile(*lonlat, area)
                site["solar_series"], site["solar_area"] = series, area
                out.print(f"  · solar: lon {lonlat[0]:.5f}, lat {lonlat[1]:.5f}, area {area:,.0f} m² · peak {max(series):,.3f}")
                solar_box.children = [plotly_fig_to_html(_solar_fig(_avg24_series(series), CHART_SOLAR_PX))]
            except Exception as exc:
                solar_box.children = [_error_box(f"{type(exc).__name__}: {exc}", CHART_SOLAR_PX)]
        if on_gis_loaded:
            on_gis_loaded()

    btn_gis = _btn("Load GIS data", "wz-primary", "wz-pill", w="160px",
                   tip="Fetch real building footprints for the drawn polygon from Sympheny GIS")
    btn_center = _btn("Center", "wz-ghost", "wz-pill", w="100px", tip="Recenter the map on the drawn polygon")
    Spinned(vbox, spinner_html).bind(_work_load_gis, btn_gis)
    btn_center.on_click(_center)
    panel = widgets.VBox([m, solar_box, widgets.HBox([btn_gis, btn_center], layout=widgets.Layout(margin="8px 0 0 0", gap="10px"))])
    return panel, lambda: None               # step 1 has no readout to refresh


# ------------------------------------------------------- step 2: site & bldgs
def _buildings_from_gis_addresses(addresses):
    """One building type per GIS address. Only use/gfa reach the demand API; the rest get editable defaults."""
    out = [{"name": a.get("address") or "Unnamed building",
            "use": a.get("building_type") if a.get("building_type") in USE_TYPES else USE_TYPES[0],
            "period": "2000–2010", "renovated": "No", "gfa": float(a.get("building_ground_area") or 0.0),
            "zone": CLIMATE_ZONES[0], "diversity": 10.0, "epc": "C"} for a in addresses]
    return out or [dict(b) for b in DEFAULT_BUILDINGS]


def _build_step_site(buildings):
    sel, loading = [0], [False]
    side_header, totals_box, status, kpi_row, agg_kpis, right_title = (HTML() for _ in range(6))
    type_list, agg_chart = widgets.VBox(), widgets.VBox()
    preview_box = widgets.VBox(layout=widgets.Layout(margin="0 0 0 14px"))
    btn_add = _btn("+ Add", "wz-ghost", w="80px", h="30px", tip="Add a building type", m="0 8px 8px 0")
    btn_del = _btn("Remove", "wz-ghost", w="90px", h="30px", tip="Remove selected type", m="0 0 8px 0")

    fw = widgets.Layout(width="97%", height="32px")
    F = {"name": widgets.Text(layout=fw), "use": widgets.Dropdown(options=USE_TYPES, layout=fw),
         "renovated": widgets.Dropdown(options=["No", "Yes"], layout=fw), "gfa": widgets.FloatText(layout=fw),
         "zone": widgets.Dropdown(options=CLIMATE_ZONES, layout=fw), "diversity": widgets.FloatText(layout=fw),
         "period": widgets.Dropdown(options=PERIODS, layout=widgets.Layout(width="200px", height="32px"))}
    epc_btns = [_btn(e, "wz-chipbtn", w="38px", h="30px", m="0 5px 0 0") for e in EPC_COLOR]

    def _col(label, key, caption):
        return widgets.VBox([HTML(f"<div class='wz-label'>{label}</div>"), F[key], HTML(f"<div class='wz-caption'>{caption}</div>")],
                            layout=widgets.Layout(width="32%"))

    form = widgets.VBox([
        widgets.HBox([_col("Name", "name", "Label used in the report"), _col("Use type", "use", "Sympheny building_type"),
                      _col("Renovated", "renovated", "Envelope refurbishment done")]),
        widgets.HBox([_col("Gross floor area", "gfa", "m² · sent as building_ground_area"),
                      _col("Climate zone", "zone", "Climate zone · solar irradiation"),
                      _col("Diversity factor", "diversity", "% reduction in aggregated peak")]),
        widgets.HBox([HTML("<div class='wz-label' style='margin:8px 10px 0 2px'>Energy class "
                           "<span style='--c:#8a94a0'>(EU EPC / SIA 380/1)</span></div>"),
                      widgets.HBox(epc_btns, layout=widgets.Layout(margin="4px 24px 0 0")),
                      HTML("<div class='wz-label' style='margin:8px 10px 0 0'>Construction period</div>"), F["period"]],
                     layout=widgets.Layout(align_items="center", margin="0 0 10px"))])
    side = widgets.VBox([side_header, widgets.HBox([btn_add, btn_del]), type_list, totals_box],
                        layout=widgets.Layout(width="250px", margin="0 20px 0 0"))
    right = widgets.VBox([right_title, form, widgets.HBox([kpi_row, preview_box], layout=widgets.Layout(align_items="center"))],
                         layout=widgets.Layout(width="calc(100% - 270px)"))
    panel = widgets.VBox([HTML("<div class='wz-title'>Site & buildings</div>"), status,
                          widgets.HBox([side, right], layout=widgets.Layout(align_items="flex-start")), agg_kpis, agg_chart])

    def _compute():
        pending = sum(1 for b in buildings if _demand_key(b) != b.get("_key"))
        if pending:
            status.value = (f"<div class='wz-caption'>⏳ Fetching {pending * len(CARRIERS)} demand profile(s) "
                            f"from Sympheny in parallel…</div>")
            preview_box.children = [_loader("Loading profile…", CHART_PREVIEW_PX, CHART_PREVIEW_W)]
            agg_chart.children = [_loader("Aggregating all building types…", CHART_COMBINED_PX)]
        _load_demands(buildings)
        status.value = "".join(f"<div class='wz-err'>⚠ {b['name']} — {b['_error']}</div>" for b in buildings if b.get("_error"))

    def _refresh_list():
        side_header.value = f"<div class='wz-title'>Building types ({len(buildings)})</div>"
        rows = []
        for i, b in enumerate(buildings):
            btn = _btn(f"{'⚠' if b.get('_error') else '🏢'}  {b['name']}", "wz-listitem", w="100%", h="32px",
                       tip=f"{b['gfa']:,.0f} m² · {b['use']} · Class {b['epc']}", m="0 0 1px 0")
            btn.style.button_color = "#e6f6f3" if i == sel[0] else "#ffffff"
            btn.style.font_weight = "bold" if i == sel[0] else "normal"
            btn.on_click(partial(_pick, i))
            rows.append(widgets.VBox([btn, HTML(f"<div class='wz-caption' style='margin:-3px 0 5px 30px'>"
                                                f"{b['gfa']:,.0f} m² · {b['use']}</div>")]))
        type_list.children = rows
        surface, peaks, *_ = _site_totals(buildings)
        totals_box.value = ("<div class='wz-side wz-tot' style='margin-top:8px'>"
                            "<div style='font-size:10px;letter-spacing:.1em;--c:#8a94a0'>AGGREGATE TOTALS</div>"
                            f"Surface <span>{surface:,.0f} m²</span><br>" +
                            "<br>".join(f"{c} peak <span style='--c:{col}'>{peaks[c]:,.0f} kW</span>" for c, col in CARRIERS)
                            + "</div>")

    def _refresh_right():
        if not buildings:
            right_title.value = "<i style='color:#8a94a0'>No building type defined.</i>"
            kpi_row.value, preview_box.children = "", []
            return
        cur = buildings[sel[0]]
        tag = " <span class='wz-tag err'>FAILED</span>" if cur.get("_error") else ""
        right_title.value = (f"<div style='font-family:sans-serif;font-size:15px;font-weight:600;margin:0 0 8px'>🏢 {cur['name']}{tag}"
                             f"<span style='font-size:11px;color:#8a94a0;font-weight:400'>  type {sel[0] + 1} of {len(buildings)} · "
                             f"{cur['use']}</span></div>")
        for b in epc_btns:
            on = b.description == cur["epc"]
            b.style.button_color = EPC_COLOR[b.description] if on else "#f2f4f7"
            b.style.font_weight = "bold" if on else "normal"
            b.style.text_color = "#ffffff" if on else "#6b7280"
        if cur.get("_error"):
            kpi_row.value = "<div class='wz-caption'>No demand data — the Sympheny request failed.</div>"
            preview_box.children = [_error_box(cur["_error"], CHART_PREVIEW_PX, CHART_PREVIEW_W)]
            return
        pk, an = _dv(cur, "peak"), _dv(cur, "annual")
        kpi_row.value = "<div class='wz-row'>" + "".join(
            _kpi(f"{c} peak", f"{pk[c]:,.0f}", f"kW · {an[c]:,.0f} MWh/y", col) for c, col in CARRIERS) + "</div>"
        preview_box.children = [plotly_fig_to_html(_profile_fig(
            _dv(cur, "avg24", [0.0] * 24), "Hourly profile preview (daily avg of 8760 h)", CHART_PREVIEW_PX, CHART_PREVIEW_W))]

    def _refresh_band():
        surface, peaks, annuals, curves, *_ = _site_totals(buildings)
        cards = [_kpi("Surface", f"{surface:,.0f}", "m²", "#4a5568")]
        for c, col in CARRIERS:
            cards += [_kpi(f"{c} peak", f"{peaks[c]:,.0f}", "kW · coincident", col),
                      _kpi(f"{c} annual", f"{annuals[c]:,.0f}", "MWh/y", col)]
        missing = sum(1 for b in buildings if b.get("_error"))
        note = (f" <span style='text-transform:none;letter-spacing:0;--c:#b3312c'>"
                f"· {missing} type(s) missing</span>") if missing else ""
        agg_kpis.value = (f"<div class='wz-band'><h4>Σ Aggregated totals — all {len(buildings)} building types{note}</h4>"
                          f"<div class='wz-row'>{''.join(cards[:6])}</div></div>")   # the band stops at the DHW peak
        agg_chart.children = [plotly_fig_to_html(_profile_fig(curves, "Combined hourly profile – all zones & carriers",
                                                              CHART_COMBINED_PX))]

    def refresh_all(recompute=True):
        if recompute:
            _compute()
        _refresh_list()
        _refresh_right()
        _refresh_band()

    def _load_form():
        if not buildings:
            return
        loading[0] = True
        cur = buildings[sel[0]]
        for k, w in F.items():
            v = cur[k]
            if k == "use" and v not in USE_TYPES:
                v = USE_TYPES[0]
            w.value = float(v) if isinstance(w, widgets.FloatText) else v
        loading[0] = False

    def _on_field(_change=None):
        if loading[0] or not buildings:
            return
        cur = buildings[sel[0]]
        cur.update({k: w.value for k, w in F.items()})
        cur["name"], cur["gfa"] = cur["name"] or "Unnamed", max(0.0, cur["gfa"])
        refresh_all()

    def _pick(index, _btn=None):
        if 0 <= index < len(buildings):
            sel[0] = index
            _load_form()
            refresh_all(recompute=False)

    def _on_epc(b):
        if buildings:
            buildings[sel[0]]["epc"] = b.description      # metadata only, no refetch
            refresh_all(recompute=False)

    def _on_add(_b):
        buildings.append({"name": f"Building type {len(buildings) + 1}", "use": "OFFICES", "period": "2000–2010",
                          "renovated": "No", "gfa": 1000.0, "zone": CLIMATE_ZONES[0], "diversity": 10.0, "epc": "C"})
        sel[0] = len(buildings) - 1
        _load_form()
        refresh_all()

    def _on_del(_b):
        if len(buildings) > 1:
            buildings.pop(sel[0])
            sel[0] = max(0, sel[0] - 1)
            _load_form()
            refresh_all(recompute=False)

    for w in F.values():
        w.observe(_on_field, names="value")
    for b in epc_btns:
        b.on_click(_on_epc)
    btn_add.on_click(_on_add)
    btn_del.on_click(_on_del)
    _load_form()
    refresh_all()
    return panel, refresh_all


# --------------------------------------------------- step 3: system variants
def _build_step_variants(variants):
    """Variant columns; technologies are added through a modal picker."""
    row = widgets.HBox(layout=widgets.Layout(align_items="flex-start", overflow="auto"))
    modal_title, modal_body = HTML(), widgets.VBox()
    btn_close = _btn("Cancel", "wz-ghost", "wz-pill", w="100px")
    modal_card = widgets.VBox([modal_title, modal_body, widgets.HBox(
        [btn_close], layout=widgets.Layout(justify_content="flex-end", margin="12px 0 0 0"))])
    modal_card.add_class("wz-modal-card")
    modal = widgets.Box([modal_card])
    modal.add_class("wz-modal")
    modal.layout.display = "none"

    def _open_modal(vi, _b=None):
        var, color = variants[vi], _vcolor(vi)
        modal_title.value = (f"<div class='wz-modal-title'>Add technology</div><div class='wz-caption'>to "
                             f"<b style='color:{color}'>V{vi + 1}</b> · {var['name']}</div>")
        blocks = []
        for cat, techs in TECH_CATALOG.items():
            available = [t for t in techs if t[0] not in var["techs"]]
            if not available:
                continue
            blocks.append(HTML(f"<div class='wz-cat'>{cat}</div>"))
            for tech, sub, icon in available:
                b = _btn(f"{icon}   {tech}", "wz-pick", w="99%", tip=sub, m="0 0 2px 0")
                b.on_click(partial(_add_tech, vi, tech))
                blocks += [b, HTML(f"<div class='wz-sub' style='margin:-4px 0 6px 30px'>{sub}</div>")]
        modal_body.children = blocks or [HTML("<div class='wz-caption'>Every technology is already part of this variant.</div>")]
        modal.layout.display = "flex"

    def _close_modal(_b=None):
        modal.layout.display = "none"

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
        _cat, sub, icon = TECH_INDEX.get(tech, ("", "", "•"))
        text = HTML(f"<div style='display:flex;align-items:center;gap:9px'><span style='font-size:16px'>{icon}</span><span>"
                    f"<div class='wz-tech-name'>{tech}</div><div class='wz-tech-sub'>{sub}</div></span></div>",
                    layout=widgets.Layout(width="205px"))
        badge = HTML(f"<div style='width:20px;height:20px;border-radius:50%;background:{color};color:#fff !important;"
                     f"font-size:11px;display:flex;align-items:center;justify-content:center'>✓</div>")
        rm = _btn("✕", "wz-x", w="26px", h="26px", tip=f"Remove {tech}")
        rm.on_click(partial(_remove_tech, vi, tech))
        return widgets.HBox([text, badge, rm], layout=widgets.Layout(
            width="272px", margin="0 0 6px 0", padding="8px 10px", align_items="center",
            justify_content="space-between", border=f"1px solid {color}66", border_radius="10px"))

    def _render():
        cols = []
        for vi, var in enumerate(variants):
            color = _vcolor(vi)
            name = widgets.Text(value=var["name"], layout=widgets.Layout(width="200px", height="32px"))
            name.observe(partial(_on_name, vi), names="value")
            head = [HTML(f"<div style='background:{color};color:#fff !important;border-radius:50%;width:24px;height:24px;"
                         f"line-height:24px;text-align:center;font-size:11px;font-weight:700;font-family:sans-serif'>"
                         f"V{vi + 1}</div>"), name]
            if len(variants) > 1:
                close = _btn("✕", "wz-x", w="28px", h="28px", tip="Remove variant")
                close.on_click(partial(_on_remove_variant, vi))
                head.append(close)
            items = [widgets.HBox(head, layout=widgets.Layout(align_items="center", margin="0 0 8px 0"))]
            for cat in TECH_CATALOG:
                chosen = [t for t, _s, _i in TECH_CATALOG[cat] if t in var["techs"]]
                if chosen:
                    items.append(HTML(f"<div class='wz-cat'>{cat}</div>"))
                    items += [_tech_card(vi, t, color) for t in chosen]
            if not var["techs"]:
                items.append(HTML("<div class='wz-caption'>No technology yet.</div>"))
            add = _btn("+ Add technology", "wz-addtech", w="272px", m="6px 0 0 0")
            add.on_click(partial(_open_modal, vi))
            items.append(add)
            cols.append(widgets.VBox(items, layout=widgets.Layout(
                width="310px", padding="12px 14px", margin="0 12px 0 0", border=f"1px solid {color}55", border_radius="12px")))
        add_var = _btn("+  Add variant", "wz-addtech", w="150px", h="38px")
        add_var.on_click(_on_add_variant)
        cols.append(widgets.VBox([HTML("<div class='wz-caption' style='margin:40px 0 8px'> </div>"), add_var],
                                 layout=widgets.Layout(width="180px", padding="12px", align_items="center",
                                                       border="1px dashed #d5dbe2", border_radius="12px")))
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

    btn_close.on_click(_close_modal)
    panel = widgets.VBox([HTML("<div class='wz-title'>Define your energy system variants</div><div class='wz-caption'>"
                               "Add technologies to each variant with the + button. Each variant is optimised separately.</div>"), row])
    _render()
    return panel, _render, modal


# ----------------------------------------------------------- step 4: summary
def _summary_html(buildings, variants):
    surface, peaks, annuals, _curves, div, coinc = _site_totals(buildings)
    rows = []
    for i, b in enumerate(buildings):
        pk, err = _dv(b, "peak"), b.get("_error")
        demand = (f"<span style='--c:#b3312c'>no demand data — {err}</span>" if err else
                  " · ".join(f"{c if c == 'DHW' else c.lower()} {pk[c]:,.0f} kW" for c, _ in CARRIERS))
        tag = " <span class='wz-tag err'>FAILED</span>" if err else ""
        rows.append(f"<tr><td class='k'>#{i + 1}  {b['name']}</td><td class='v'>{b['use']} · {b['period']} · "
                    f"renovated: {b['renovated']}{tag}<br><span style='font-weight:400;--c:#6b7280'>{b['gfa']:,.0f} m² · "
                    f"{b['zone']} · diversity {b['diversity']:.0f}% · class "
                    f"<b style='color:{EPC_COLOR[b['epc']]}'>{b['epc']}</b><br>{demand}</span></td></tr>")
    missing = [b["name"] for b in buildings if b.get("_error")]
    warn = (f"<tr><td class='k'>Incomplete</td><td class='v' style='--c:#b3312c'>"
            f"{', '.join(missing)} excluded — demand fetch failed</td></tr>") if missing else ""
    vrows = []
    for vi, var in enumerate(variants):
        color = _vcolor(vi)
        chips = "".join(f"<span class='wz-chip' style='background:{color}1a;--c:{color}'>{t}</span>"
                        for t in var["techs"]) or "<i style='color:#8a94a0'>no technology selected</i>"
        vrows.append(f"<tr><td class='k'><b style='color:{color}'>V{vi + 1}</b> {var['name']}</td><td class='v'>{chips}</td></tr>")
    return ("<div class='wz-title'>Summary</div>"
            f"<div class='wz-sum'><h3>Site & buildings ({len(buildings)} types)</h3><table>{''.join(rows)}</table></div>"
            "<div class='wz-sum'><h3>Aggregated totals</h3><table>"
            f"<tr><td class='k'>Surface</td><td class='v'>{surface:,.0f} m²</td></tr>" +
            "".join(f"<tr><td class='k'>{c} peak / annual</td><td class='v'>{peaks[c]:,.0f} kW · {annuals[c]:,.0f} MWh/y</td></tr>"
                    for c, _ in CARRIERS) +
            f"<tr><td class='k'>Coincidence applied</td><td class='v'>{coinc:.2f} (mean diversity {div:.0f}%)</td></tr>{warn}"
            f"</table></div><div class='wz-sum'><h3>System variants ({len(variants)})</h3><table>{''.join(vrows)}</table></div>")


def _build_step_summary(buildings, variants):
    body = HTML()
    btn_submit = _btn("Submit", "wz-primary", "wz-pill", w="150px", h="36px")

    def refresh():
        body.value = _summary_html(buildings, variants)

    refresh()
    return widgets.VBox([body]), btn_submit, refresh


# ------------------------------------------------------------- wizard shell
def run():
    # Phase 1: bare shell, displayed immediately.
    nav_widget = HTML()
    content_area = widgets.VBox([_loading_html()], layout=widgets.Layout(min_height=f"{CONTENT_MIN_PX}px", overflow="visible"))
    footer = widgets.HBox(layout=widgets.Layout(width="100%", justify_content="space-between", align_items="center",
                                                margin="10px 0 0 0", padding="10px 0 0 0", border_top=f"1px solid {LINE}"))
    spinner_html, vbox, modal_container = get_spinner_html(), widgets.VBox(), widgets.VBox()
    display(HTML(WZ_CSS), nav_widget, content_area, footer, HTML("<br/>"), spinner_html, vbox, modal_container)

    def _init_app():
        # Phase 2, once the browser is ready. Step 1 is built eagerly; the rest lazily, on first visit.
        _authenticate()
        site = {"polygon": None}
        buildings = [dict(b) for b in DEFAULT_BUILDINGS]
        variants = [{"name": v["name"], "techs": list(v["techs"])} for v in DEFAULT_VARIANTS]
        panels, refreshers, extras, current = {}, {}, {}, [0]

        panels[0], refreshers[0] = _build_step_location(
            site, vbox, spinner_html, on_gis_loaded=lambda: (panels.pop(1, None), refreshers.pop(1, None)))
        panels[0].layout.margin = "4px 0 0 0"
        btn_prev = _btn("←  Back", "wz-ghost", "wz-pill", w="120px", h="36px")
        btn_next = _btn("Continue  →", "wz-primary", "wz-pill", w="150px", h="36px")
        right_actions = widgets.HBox([btn_next], layout=widgets.Layout(align_items="center", gap="10px"))
        footer.children = [btn_prev, right_actions]

        def _ensure_step(index):
            if index in panels:
                return
            if index == 1:   # GIS fetched in step 1 replaces the defaults with one type per address
                addresses = (site.get("gis") or {}).get("addresses") or []
                if addresses:
                    buildings[:] = _buildings_from_gis_addresses(addresses)
                panels[1], refreshers[1] = _build_step_site(buildings)
            elif index == 2:
                panels[2], refreshers[2], modal = _build_step_variants(variants)
                modal_container.children = [modal]
            elif index == 3:
                panels[3], btn_submit, refreshers[3] = _build_step_summary(buildings, variants)
                extras["btn_submit"] = btn_submit
                Spinned(vbox, spinner_html).bind(lambda out: _work_submit(out, buildings, variants, site), btn_submit)
            panels[index].layout.margin = "4px 0 0 0"

        def go_to(index):
            index = max(0, min(len(STEP_DEFS) - 1, index))
            nav_widget.value = _render_nav_html(index)
            btn_prev.layout.visibility = "hidden" if index == 0 else "visible"
            content_area.children = [_loading_html("LOADING DEMANDS FROM SYMPHENY BACKEND …", big=True) if index == 1
                                     else _loading_html()]
            _ensure_step(index)
            refreshers[index]()
            current[0] = index
            content_area.children = [panels[index]]
            right_actions.children = (extras["btn_submit"],) if index == len(STEP_DEFS) - 1 else (btn_next,)

        btn_prev.on_click(lambda _: go_to(current[0] - 1))
        btn_next.on_click(lambda _: go_to(current[0] + 1))
        go_to(0)

    on_browser_ready(_init_app)


# ===========================================================================
## BACKEND API CALLS
# Everything below talks to Sympheny or derives numbers from what it returned.
# Nothing here touches ipywidgets: the UI above renders whatever comes back.
# ===========================================================================

CONSTRUCTION_END = 2000       # fixed – not driven by the form
NBR_FLOOR = 1                 # fixed – so building_ground_area == GFA
HTTP_TIMEOUT = 90
MAX_WORKERS = 12              # ceiling for one batch of building x carrier calls
PROJECT_NAME = "light-app"    # reused across submits; only its variants analysis is deleted & recreated
HUB_NAME, STAGE_NAME = "Hub 1", "Stage 1"
# Dedicated analysis inside PROJECT_NAME used only to preview GIS footprints (step 1). The analysis
# is reused; its scenario is deleted and recreated on every "Load GIS data" so the hub made right
# after is its only hub. That scenario is copied onto every variant scenario at submit time.
GIS_ANALYSIS_NAME = GIS_SCENARIO_NAME = "site-gis"
GIS_JOB_MAX_ATTEMPTS, GIS_JOB_POLL_SECONDS = 300, 1.0

CARRIER_DEMAND_TYPE = {"Heat": "SPACE_HEATING", "Elec": "ELECTRICITY", "DHW": "HOT_WATER"}
# EnergyCarrierRequestDtoV2.subType per app carrier — also the key used to reuse a carrier the
# technology package created: imported technologies emit HEAT_8 (space heating) and HEAT_4 (DHW),
# so these must match or every scenario ends up with duplicate heat carriers.
CARRIER_SUBTYPE = {"Heat": "HEAT_8", "Elec": "ELECTRICITY", "DHW": "HEAT_4"}
CARRIER_FULL_NAME = {"Heat": "Space heating", "Elec": "Electricity", "DHW": "Domestic hot water"}
# Subtype that importing "Solar PV - Roof" creates for its incoming solar resource; reused, not recreated.
SOLAR_RESOURCE_SUBTYPE = "SOLAR_ROOF"
# Import price is deliberately huge so the optimiser treats grid draw as a last resort.
IMPEX_ELEC_PRICE = {"IMPORT": 10000.0, "EXPORT": 1.0}
SOLVER = {"objective2": None, "name": "j", "clientType": "APP", "temporalResolution": "LOW",
          "points": 1, "timeLimit": 30, "mipGap": 10}
SOLVER_OBJECTIVE = "MIN_LIFE_CYCLE_COST"
SOLVER_WAIT_SECONDS, SOLVER_POLL_SECONDS = 300, 5
APP_TO_DB = {                 # app label -> Sympheny database technology name
    "Gas boiler": "Gas Boiler (Linearized cost)",
    "Air-source heat pump": "Air-to-water HP (Linearized cost)",
    "Ground-source HP": "Brine-Water HP- < 100 kW (Linearized cost)",
    "Wood pellet boiler": "Pellet Boiler- < 100 kW (Linearized cost)",
    "Solar PV": "Solar PV - Roof",
    "CHP unit": "Gas CHP (Linearized cost)",
}

_HEADERS, SYMPHENY_BASE_URL, BE_URL = {}, None, None
_DEMAND_CACHE, _SOLAR_CACHE = {}, {}


def _authenticate():
    """Read the kernel token once and build the auth header for every call."""
    global _HEADERS, SYMPHENY_BASE_URL, BE_URL
    creds = get_creds_from_token(get_token())
    _HEADERS, SYMPHENY_BASE_URL, BE_URL = creds["h"], creds["base_url"], creds["be"]
    utils_log.log(SYMPHENY_BASE_URL)

    # get logged username
    h = creds["h"]
    jwt = (h.get("authorization") or h.get("Authorization")).split(" ", 1)[-1]
    username = token_to_user(jwt)
    utils_log.log(username)


def _req(method, url, **kw):
    """Bare call — used where a non-200 is inspected rather than raised."""
    return getattr(r, method)(url, headers=_HEADERS, timeout=HTTP_TIMEOUT, **kw)


def _raw(method, url, **kw):
    resp = _req(method, url, **kw)
    resp.raise_for_status()
    return resp


def _d(method, url, **kw):
    """The common shape: raise on error, return the "data" envelope."""
    return _raw(method, url, **kw).json()["data"]


def _get_or_create(url, name_key, guid_key, name, body, pick=None):
    """Reuse the item called `name` from GET url, or POST it to the same url. `body` may be a
    callable taking the existing items (the stage endpoint needs their count)."""
    items = _d("get", url)
    items = pick(items) if pick else (items or [])
    for it in items:
        if it.get(name_key) == name:
            return it[guid_key]
    return _d("post", url, json=body(items) if callable(body) else body)[guid_key]


def _project(name=PROJECT_NAME):
    return _get_or_create(f"{BE_URL}projects", "projectName", "projectGuid", name,
                          {"projectName": name, "version": "V2"}, pick=lambda d: d["projects"])


def _analysis(project_guid, name):
    return _get_or_create(f"{BE_URL}projects/{project_guid}/analyses", "analysisName", "analysisGuid", name,
                          {"analysisName": name})


def _hub(scenario_guid, name=HUB_NAME):
    return _get_or_create(f"{BE_URL}scenarios/{scenario_guid}/hubs", "hubName", "hubGuid", name, {"hubName": name})


def _stage(scenario_guid, name=STAGE_NAME):
    return _get_or_create(f"{BE_URL}scenarios/{scenario_guid}/stages", "name", "guid", name,
                          lambda items: {"name": name, "index": len(items) + 1, "length": 1})


def _reset_analysis(project_guid, name):
    """Delete any analysis of this name, then create a fresh one (the project, and its GIS analysis, survive)."""
    for a in _d("get", f"{BE_URL}projects/{project_guid}/analyses") or []:
        if a.get("analysisName") == name:
            _raw("delete", f"{BE_URL}analysis/{a['analysisGuid']}")
    return _d("post", f"{BE_URL}projects/{project_guid}/analyses", json={"analysisName": name})["analysisGuid"]


def _reset_scenario(analysis_guid, name):
    """Delete any scenario of this name, then create a fresh one — it has no hubs yet."""
    for s in _d("get", f"{BE_URL}analysis/{analysis_guid}")["scenarios"]:
        if s.get("scenarioName") == name:
            _raw("delete", f"{BE_URL}scenario/{s['scenarioGuid']}")
    return _create_scenario(analysis_guid, name)


def _create_scenario(analysis_guid, name):
    return _d("post", f"{BE_URL}analysis/{analysis_guid}/scenario", json={"scenarioName": name})["scenarioGuid"]


# ------------------------------------------------- step 2: demand retrieval
def _fetch_carrier(building_type, area, carrier):
    """One hub_demand + profile round-trip. Returns peak [kW], annual [MWh/y], the 24 h
    daily-average curve [kW] and the full 8760 h series [kW]. Raises on any problem."""
    if area <= 0:
        return {"peak": 0.0, "annual": 0.0, "avg24": [0.0] * 24, "series": [0.0] * 8760}
    key = (building_type, round(float(area), 3), carrier)
    if key in _DEMAND_CACHE:
        return _DEMAND_CACHE[key]
    demand_type = CARRIER_DEMAND_TYPE[carrier]
    meta = _raw("post", f"{SYMPHENY_BASE_URL}api-services/demand/hub_demand?demand_type={demand_type}&building_type={building_type}",
                json=[{"construction_end": CONSTRUCTION_END, "building_ground_area": float(area), "nbr_floor": NBR_FLOOR}]).json()[0]
    guid, total = meta["energyDemandMetadataGuid"], meta["totalAnnualDemand"]
    data = _d("get", f"{BE_URL}database-energy-demands/{guid}/profile")
    if len(data) != 8760:
        raise ValueError(f"{demand_type}: expected 8760 periods, got {len(data)}")
    # Each entry is a normalised share of the annual total; period order isn't guaranteed.
    series = [item["demandValue"] * total for item in sorted(data, key=lambda x: x["period"])]
    _DEMAND_CACHE[key] = {"peak": max(series), "annual": total / 1000.0, "avg24": _avg24_series(series), "series": series}
    return _DEMAND_CACHE[key]


def _demand_key(b):
    """The only two form fields that drive the API call."""
    return (b["use"], round(float(b["gfa"] or 0), 3))


def _load_demands(buildings):
    """Fetch every stale building's carriers in ONE parallel batch. Failures are recorded per
    building in `_error` and never replaced by invented numbers."""
    stale = [b for b in buildings if not (b.get("_key") == _demand_key(b) and (b.get("_demand") or b.get("_error")))]
    if not stale:
        return
    names = [c for c, _ in CARRIERS]
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(stale) * len(names))) as pool:
        jobs = {(id(b), c): pool.submit(_fetch_carrier, *_demand_key(b), c) for b in stale for c in names}
    for b in stale:
        demand, error = {}, ""
        for c in names:
            try:
                demand[c] = jobs[(id(b), c)].result()
            except Exception as exc:
                error = error or f"{type(exc).__name__}: {exc}"
        b["_demand"], b["_error"] = None if error else demand, error
        b["_key"] = _demand_key(b)          # set even on failure: no retry storm


def _dv(b, field, default=0.0):
    """One demand field per carrier, zero-filled where the fetch failed."""
    d = b.get("_demand") or {}
    return {c: d.get(c, {}).get(field, default) for c, _ in CARRIERS}


def _avg24_series(series):
    """Collapse an 8760 h series to its 24 h daily average."""
    return [sum(series[h::24]) / 365.0 for h in range(24)]


def _site_totals(buildings):
    """(surface, coincident peaks, annual energy, coincident 24 h curves, mean diversity %, coincidence)."""
    surface = sum(float(b["gfa"] or 0) for b in buildings)
    peaks = {c: sum(_dv(b, "peak")[c] for b in buildings) for c, _ in CARRIERS}
    annuals = {c: sum(_dv(b, "annual")[c] for b in buildings) for c, _ in CARRIERS}
    curves = {c: [sum(_dv(b, "avg24", [0.0] * 24)[c][h] for b in buildings) for h in range(24)] for c, _ in CARRIERS}
    div = sum(float(b["diversity"] or 0) for b in buildings) / len(buildings) if buildings else 0.0
    coinc = max(0.0, 1.0 - div / 100.0)
    return (surface, {c: v * coinc for c, v in peaks.items()}, annuals,     # energy: no coincidence
            {c: [v * coinc for v in s] for c, s in curves.items()}, div, coinc)


def _aggregate_series(buildings):
    """Site-wide 8760 h demand per carrier [kW]. Buildings whose fetch failed contribute nothing."""
    total = {c: [0.0] * 8760 for c, _ in CARRIERS}
    for b in buildings:
        for c, _ in CARRIERS:
            s = (b.get("_demand") or {}).get(c, {}).get("series")
            if s:
                total[c] = [x + y for x, y in zip(total[c], s)]
    return total


# ------------------------------------------------------- step 1: GIS retrieval
def _load_site_gis(out, polygon_lonlat):
    """Ensure the GIS scenario/hub exist, populate them from the drawn polygon, wait for the
    background job, then return (GIS payload, scenario guid)."""
    out.print("Creating GIS hub from the drawn polygon…")
    project_guid = _project()
    out.print(f"  · project '{PROJECT_NAME}': {project_guid}")
    scenario_guid = _reset_scenario(_analysis(project_guid, GIS_ANALYSIS_NAME), GIS_SCENARIO_NAME)
    hub_guid = _hub(scenario_guid)
    out.print(f"  · scenario: {scenario_guid}  ·  hub: {hub_guid}")

    job_id = _raw("post", f"{SYMPHENY_BASE_URL}api-services/gis/background/scenarios/{scenario_guid}/hubs/{hub_guid}?geoadmin=true",
                  json={"hub_name": HUB_NAME, "feature": {"type": "Feature", "geometry": {
                      "type": "Polygon", "coordinates": [_closed(polygon_lonlat)]}}}).json()["job_id"]
    out.print(f"  · background job {job_id} started")
    for i in range(1, GIS_JOB_MAX_ATTEMPTS + 1):
        try:
            jobs = _raw("get", f"{SYMPHENY_BASE_URL}api-services/gis/background").json()
            if any(x.get("job_id") == job_id and x.get("is_done") for x in jobs):
                break
        except Exception:
            pass                             # transient poll failure — keep trying
        if i == 1 or i % 5 == 0:
            out.print(f"    – waiting for GIS job… {i}s elapsed")
        time.sleep(GIS_JOB_POLL_SECONDS)
    else:
        raise TimeoutError(f"GIS job {job_id} did not complete within {GIS_JOB_MAX_ATTEMPTS} seconds")

    out.print("  · job complete — fetching GIS data…")
    data = _raw("get", f"{SYMPHENY_BASE_URL}api-services/gis/scenarios/{scenario_guid}/hubs/{hub_guid}").json()
    out.print(f"✓ {len((data.get('building_layer') or {}).get('features', []))} building(s), "
              f"{len(data.get('addresses') or [])} address(es) loaded.")
    return data, scenario_guid


def _gis_first_building_lonlat(data):
    """(lon, lat) of the first building — from the address entry if it carries coordinates,
    else the vertex-average centroid of the first footprint."""
    for a in (data.get("addresses") or [])[:1]:
        lon, lat = a.get("lon", a.get("longitude")), a.get("lat", a.get("latitude"))
        if lon is not None and lat is not None:
            return float(lon), float(lat)
    for f in ((data.get("building_layer") or {}).get("features") or [])[:1]:
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") or []
        ring = (coords[0] if coords else []) if geom.get("type") == "Polygon" else (
            coords[0][0] if geom.get("type") == "MultiPolygon" and coords and coords[0] else [])
        pts = [p for p in ring if p and p[0] is not None and p[1] is not None]
        if pts:
            return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    return None


def _gis_total_area(data):
    """Sum of building_ground_area over the addresses (the field the demand calls use for GFA),
    falling back to the features' properties."""
    total = sum(float(a.get("building_ground_area") or 0.0) for a in (data.get("addresses") or []))
    if total > 0:
        return total
    return sum(float((f.get("properties") or {}).get("building_ground_area") or (f.get("properties") or {}).get("area") or 0.0)
               for f in ((data.get("building_layer") or {}).get("features") or []))


def _fetch_solar_profile(lon, lat, area):
    """8760 h solar profile [kW] for one point + surface area."""
    key = (round(lon, 5), round(lat, 5), round(area, 1))
    if key not in _SOLAR_CACHE:
        series = _raw("post", f"{SYMPHENY_BASE_URL}api-services/jrc/solar/profile", json=[{"lon": lon, "lat": lat, "area": area}]).json()
        if len(series) != 8760:
            raise ValueError(f"solar profile: expected 8760 periods, got {len(series)}")
        _SOLAR_CACHE[key] = series
    return _SOLAR_CACHE[key]


# --------------------------------------------- step 4: scenario construction
def _carriers_by_subtype(scenario_guid):
    """subtypeKey -> energyCarrierGuid for everything already in the scenario. Imported
    technologies name theirs "HEAT_4@tp=25447" — the subtype is the part before "@". First wins."""
    found = {}
    for c in (_d("get", f"{BE_URL}scenarios/{scenario_guid}/carriers") or {}).get("energyCarriers", []) or []:
        key = (c.get("subtypeKey") or "").upper().split("@")[0].strip()
        if key:
            found.setdefault(key, c["energyCarrierGuid"])
    return found


def _upload_profile(scenario_guid, name, series):
    """The endpoint wants exactly 8760 entries, periods 1..8760, positive."""
    return _d("post", f"{BE_URL}scenarios/{scenario_guid}/profiles-json",
              json={"name": name, "values": [{"period": i + 1, "demandValue": round(max(0.0, v), 6)}
                                             for i, v in enumerate(series)]})["id"]


def _populate_scenario(out, scenario_guid, agg, var, guid_of, solar_series, solar_area):
    """Hub + stage + technologies first (so the carriers they bring in can be reused), then the
    solar on-site resource, then the demands."""
    hub_guid, stage_guid = _hub(scenario_guid), _stage(scenario_guid)
    guids, unmapped = [], []
    for t in var["techs"]:
        guid = guid_of.get(APP_TO_DB.get(t, ""))
        guids.append(guid) if guid else unmapped.append(t)
    status = _req("post", f"{BE_URL}scenarios/{scenario_guid}/hubs/{hub_guid}/import-database-technology-package?technologiesOptional=true",
                  json={"conversionTechGuids": guids}).status_code if guids else None
    out.print(f"    – technologies: {len(guids)} imported" + (f" (HTTP {status})" if status is not None else " — nothing to import"))
    if unmapped:
        out.print(f"    ⚠ no database match for: {', '.join(unmapped)}")
    existing = _carriers_by_subtype(scenario_guid)
    out.print(f"    – carriers in scenario after import: {', '.join(sorted(existing)) or 'none'}")

    if "Solar PV" in var["techs"]:
        resource_guid = existing.get(SOLAR_RESOURCE_SUBTYPE)
        if not solar_series or max(solar_series) <= 0:
            out.print("    ⚠ Solar PV selected but no site solar profile is available — load GIS data in step 1 first. "
                      "Skipping on-site resource.")
        elif not resource_guid:
            out.print(f"    ⚠ Solar PV selected but no {SOLAR_RESOURCE_SUBTYPE} carrier was created by the import — "
                      f"skipping on-site resource.")
        else:
            # `area` is an "Area"-type available resource: the same m² the JRC profile was fetched for.
            pid = _upload_profile(scenario_guid, "Solar irradiance – site total", solar_series)
            guid = _d("post", f"{BE_URL}v2_1/scenarios/{scenario_guid}/solar-on-site-resource",
                      json={"name": "Solar irradiance – site total", "energyCarrierGuid": resource_guid,
                            "hubs": [{"hubGuid": hub_guid, "availableSolarCollectorArea": solar_area or 0.0,
                                      "availableResourceType": "Area"}],
                            "profileId": pid, "stages": [stage_guid]})["solarResourceGuid"]
            out.print(f"    – solar on-site resource (reused {SOLAR_RESOURCE_SUBTYPE} carrier): "
                      f"{solar_area or 0.0:,.0f} m² · profile #{pid} · {guid}")

    for carrier, _color in CARRIERS:
        series = agg.get(carrier) or []
        if not series or max(series) <= 0:
            out.print(f"    – {carrier}: no demand, skipped")
            continue
        subtype = CARRIER_SUBTYPE[carrier]
        carrier_guid, origin = existing.get(subtype), f"reused {subtype}"
        if not carrier_guid:
            carrier_guid = _d("post", f"{BE_URL}v2/scenarios/{scenario_guid}/carriers",
                              json={"energyCarrierName": CARRIER_FULL_NAME[carrier], "subType": subtype,
                                    "colorHexCode": CARRIER_COLOR[carrier]})["energyCarrierGuid"]
            existing[subtype], origin = carrier_guid, f"created {subtype}"
        pid = _upload_profile(scenario_guid, f"{CARRIER_FULL_NAME[carrier]} – site total", series)
        _d("post", f"{BE_URL}v2_1/scenarios/{scenario_guid}/energy-demands",
           json={"name": f"{CARRIER_FULL_NAME[carrier]} demand", "hubGuids": [hub_guid], "energyCarrierGuid": carrier_guid,
                 "demandProfileId": pid, "demandScalingFactor": 1, "stages": [stage_guid]})
        out.print(f"    – {carrier} ({origin}): {sum(series) / 1000:,.0f} MWh/y · peak {max(series):,.0f} kW · profile #{pid}")


def _create_variant_scenario(out, analysis_guid, var, agg, guid_of, gis_scenario_guid=None, solar_series=None, solar_area=None):
    """One scenario per variant. Returns (guid, frontend URL)."""
    scenario_guid = _create_scenario(analysis_guid, var["name"])
    # Populate first: the GIS copy below needs this scenario's own hub.
    _populate_scenario(out, scenario_guid, agg, var, guid_of, solar_series, solar_area)
    if gis_scenario_guid:
        try:
            _raw("put", f"{BE_URL}scenarios/copy/{gis_scenario_guid}/gis", params={"scenarioGuidTo": scenario_guid})
            out.print(f"    – GIS data copied from site scenario {gis_scenario_guid}")
        except Exception as exc:
            out.print(f"    ⚠ GIS copy failed: {type(exc).__name__}: {exc}")
    else:
        out.print("    – no GIS data loaded in step 1, skipping GIS copy")

    # Electricity import/export, if the scenario ended up with an ELECTRICITY carrier at all — it may
    # come from the import (a heat pump's input) or from the demands, so it's re-read rather than assumed.
    subtype = CARRIER_SUBTYPE["Elec"]
    elec_guid = _carriers_by_subtype(scenario_guid).get(subtype)
    if elec_guid:
        hub_guid, stage_guid = _hub(scenario_guid), _stage(scenario_guid)
        for kind, price in IMPEX_ELEC_PRICE.items():
            _d("post", f"{BE_URL}v2_1/scenario/{scenario_guid}/impex",
               json={"name": f"Electricity {kind.lower()}", "energyCarrierGuid": elec_guid, "type": kind,
                     "hubs": [{"hubGuid": hub_guid}], "energyPriceCHFkWh": price, "stages": [stage_guid]})
        out.print(f"    – electricity import @ {IMPEX_ELEC_PRICE['IMPORT']:,.0f} · export @ {IMPEX_ELEC_PRICE['EXPORT']:,.0f} CHF/kWh")
    else:
        out.print(f"    – no {subtype} carrier, skipping import/export")

    # Everything is in place — close the diagram last. This endpoint lives under SYMPHENY_BASE_URL, not BE_URL.
    resp = _req("put", f"{SYMPHENY_BASE_URL}sympheny-app/scenarios/{scenario_guid}/close-diagram", data=None)
    if resp.status_code != 200:
        raise RuntimeError(f"close-diagram returned HTTP {resp.status_code}")
    out.print("    – diagram closed")
    return scenario_guid, _d("get", f"{BE_URL}scenario/{scenario_guid}/frontend-url")["frontendUrl"]


def _solve(out, analysis_guid, scenario_guid, scenario_name):
    """Queue an optimisation, wait for it, and return the dashboard URL."""
    resp = _req("post", f"{SYMPHENY_BASE_URL}sense-api/ext/solver/jobs",
                json=[dict(SOLVER, objective1=SOLVER_OBJECTIVE, scenarioGuid=scenario_guid, scenarioName=scenario_name)])
    if resp.status_code != 200:
        raise RuntimeError(f"solver job returned HTTP {resp.status_code}")
    job_id = None
    for i in range(max(1, SOLVER_WAIT_SECONDS // SOLVER_POLL_SECONDS)):
        jobs = [j for j in _raw("post", f"{SYMPHENY_BASE_URL}sense-api/ext/solver/jobs/get-scenarios",
                                json={"scenarioGuids": [scenario_guid], "limit": SOLVER_WAIT_SECONDS}).json()
                if j["scenarioGuid"] == scenario_guid]
        if jobs and all(j["terminated"] for j in jobs):
            job_id = jobs[0]["id"]
            break
        out.print(f"    – waiting for solver… {i * SOLVER_POLL_SECONDS}s elapsed")
        time.sleep(SOLVER_POLL_SECONDS)
    if job_id is None:
        raise TimeoutError(f"solver job did not finish within {SOLVER_WAIT_SECONDS}s")
    domain = "app.dev.sympheny.com" if "dev" in BE_URL else "app.sympheny.com"
    project_guid = _d("get", f"{BE_URL}analysis/{analysis_guid}")["projectGuid"]
    return f"https://{domain}/projects/{project_guid}/analysis/{analysis_guid}/execution/{job_id}/solution/1"


def _work_submit(out, buildings, variants, site):
    """Create one Sympheny scenario per variant, then solve the first one."""
    out.print(f"Creating {len(variants)} scenario(s) from {len(buildings)} building type(s)…")
    agg = _aggregate_series(buildings)
    skipped = [b["name"] for b in buildings if b.get("_error")]
    if skipped:
        out.print(f"  ⚠ excluded from the aggregate (no demand data): {', '.join(skipped)}")
    if all(max(s) <= 0 for s in agg.values()):
        return out.print("✗ no demand data at all — go back to step 2 and fix the errors.")
    try:
        guid_of = {it["technologyName"]: it["conversionTechGuid"]
                   for it in _d("get", f"{BE_URL}conversion-technologies/profile-types/database")}
        out.print(f"  · database technologies: {len(guid_of)}")
        # Reuse the project (the step-1 GIS scenario lives in it); only the variants' own analysis is reset.
        project_guid = _project()
        out.print(f"  · project '{PROJECT_NAME}': {project_guid}")
        analysis_guid = _reset_analysis(project_guid, PROJECT_NAME)
        out.print(f"  · analysis: {analysis_guid}")
    except Exception as exc:
        return out.print(f"✗ setup failed — {type(exc).__name__}: {exc}")

    created = []
    for var in tqdm_out(variants, out):
        out.print(f"  • {var['name']}")
        try:
            created.append((var["name"],) + _create_variant_scenario(
                out, analysis_guid, var, agg, guid_of, site.get("gis_scenario_guid"),
                site.get("solar_series"), site.get("solar_area")))
        except Exception as exc:
            out.print(f"    ✗ {type(exc).__name__}: {exc}")
    if not created:
        return out.print("✗ no scenario was created.")
    name, scenario_guid, url = created[0]
    out.print("")
    out.print(f"✓ {len(created)} scenario(s) created. First scenario:")
    out.print(url)
    out.print("")
    out.print(f"Running the optimisation for '{name}'…")
    try:
        dashboard = _solve(out, analysis_guid, scenario_guid, name)
        out.print("✓ optimisation finished. Dashboard:")
        out.print(dashboard)
    except Exception as exc:
        out.print(f"✗ optimisation failed — {type(exc).__name__}: {exc}")