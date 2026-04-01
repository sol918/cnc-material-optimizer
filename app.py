"""
CNC Material Optimizer Dashboard — v6
Streamlit segmented_control for thickness nav. Per-thickness caching.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from collections import defaultdict
import os, math, io

from nesting import (
    MATERIAL_CONFIG, get_config, make_element,
    filter_out_of_bounds, nest_fixed, optimize_variable, auto_optimize,
    plate_layout_key,
)
from logistics import process_logistics
from report import generate_report

st.set_page_config(page_title="CNC Material-Optimizer", layout="wide", page_icon="🪵")

MAT_COLORS = {
    "LVLQ": "#5C6BC0", "LVLS": "#42A5F5", "LVLB": "#29B6F6",
    "SPANO": "#26A69A", "FERM": "#66BB6A", "GIPF": "#9CCC65",
    "GIPA": "#AED581", "CEM": "#FFA726", "PRO": "#EF5350", "BAUB": "#EC407A",
}
MAT_LABELS = {
    "LVLQ": "LVLQ", "LVLS": "LVLS", "LVLB": "LVLB",
    "SPANO": "SPANO", "FERM": "Fermacell", "GIPF": "Gips F",
    "GIPA": "Gips A", "CEM": "Cempanel", "PRO": "Promatect", "BAUB": "Baubuche",
}

# ── CSS ────────────────────────────────────────────────────────────────────

def inject_nav_css(mat_order, active_mat):
    mat_css = ""
    for i, mat in enumerate(mat_order):
        col_idx = i + 2
        color = MAT_COLORS.get(mat, "#888")
        is_active = (mat == active_mat)
        if is_active:
            mat_css += f"""
            #mat-nav > div:nth-child({col_idx}) button {{
                background-color: {color} !important; color: white !important;
                border-color: {color} !important; box-shadow: 0 0 10px {color}55 !important;
            }}"""
        else:
            mat_css += f"""
            #mat-nav > div:nth-child({col_idx}) button {{
                border: 2px solid {color} !important; color: {color} !important;
                background-color: transparent !important;
            }}
            #mat-nav > div:nth-child({col_idx}) button:hover {{
                background-color: {color}30 !important;
            }}"""

    ov_active = active_mat is None
    if ov_active:
        mat_css += """
        #mat-nav > div:nth-child(1) button {
            background-color: #78909C !important; color: white !important;
            border-color: #78909C !important;
        }"""
    else:
        mat_css += """
        #mat-nav > div:nth-child(1) button {
            border: 2px solid #78909C !important; color: #B0BEC5 !important;
            background-color: transparent !important;
        }"""

    # Logistics button
    log_idx = len(mat_order) + 2
    log_active = active_mat == "__logistics__"
    if log_active:
        mat_css += f"""
        #mat-nav > div:nth-child({log_idx}) button {{
            background-color: #7E57C2 !important; color: white !important;
            border-color: #7E57C2 !important;
        }}"""
    else:
        mat_css += f"""
        #mat-nav > div:nth-child({log_idx}) button {{
            border: 2px solid #7E57C288 !important; color: #7E57C2 !important;
            background-color: transparent !important;
        }}"""

    # Batch button
    batch_idx = len(mat_order) + 3
    batch_active = active_mat == "__batch__"
    if batch_active:
        mat_css += f"""
        #mat-nav > div:nth-child({batch_idx}) button {{
            background-color: #FF7043 !important; color: white !important;
            border-color: #FF7043 !important;
        }}"""
    else:
        mat_css += f"""
        #mat-nav > div:nth-child({batch_idx}) button {{
            border: 2px solid #FF704388 !important; color: #FF7043 !important;
            background-color: transparent !important;
        }}"""

    err_idx = len(mat_order) + 4
    err_active = active_mat == "__errors__"

    # Search button
    search_idx = len(mat_order) + 5
    search_active = active_mat == "__search__"
    if search_active:
        mat_css += f"""
        #mat-nav > div:nth-child({search_idx}) button {{
            background-color: #29B6F6 !important; color: white !important;
            border-color: #29B6F6 !important;
        }}"""
    else:
        mat_css += f"""
        #mat-nav > div:nth-child({search_idx}) button {{
            border: 2px solid #29B6F688 !important; color: #29B6F6 !important;
            background-color: transparent !important;
        }}"""
    if err_active:
        mat_css += f"""
        #mat-nav > div:nth-child({err_idx}) button {{
            background-color: #ef5350 !important; color: white !important;
            border-color: #ef5350 !important;
        }}"""
    else:
        mat_css += f"""
        #mat-nav > div:nth-child({err_idx}) button {{
            border: 2px solid #ef535088 !important; color: #ef5350 !important;
            background-color: transparent !important;
        }}"""

    st.markdown(f"""<style>
    div[data-testid="stMetricValue"] {{ font-size: 1.4rem; }}
    .block-container {{ padding-top: 2.5rem !important; }}
    hr {{ margin: 4px 0 !important; }}
    .warn-inline {{
        background: #4a1c1c; border: 1px solid #ef5350; border-radius: 8px;
        padding: 6px 12px; margin: 4px 0; font-size: 0.85rem;
    }}
    .warn-inline b {{ color: #ef5350; }}
    .info-inline {{
        background: #1a237e22; border: 1px solid #5c6bc044; border-radius: 8px;
        padding: 6px 12px; margin: 4px 0; font-size: 0.85rem;
    }}
    .plate-label {{ font-size: 0.82rem; font-weight: 600; margin: 1px 0; }}
    {mat_css}
    </style>""", unsafe_allow_html=True)


# ── Parsing ────────────────────────────────────────────────────────────────

@st.cache_data(show_spinner="Parsing CSV...")
def parse_csv(file_bytes_list=None, filepath=None):
    """Parse one or more CSVs and concatenate into a single dataset."""
    dfs = []
    if filepath:
        dfs.append(pd.read_csv(filepath, on_bad_lines="skip", sep=None, engine="python"))
    elif file_bytes_list:
        for fb in file_bytes_list:
            dfs.append(pd.read_csv(io.BytesIO(fb), on_bad_lines="skip", sep=None, engine="python"))
    df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    elements = [e for e in (make_element(row) for _, row in df.iterrows()) if e]
    return elements, df

# ── Cached per-thickness computations ─────────────────────────────────────

def _ekey(elements):
    """Fast cache key: count + hash of first/last/middle elements."""
    n = len(elements)
    if n == 0:
        return (0,)
    samples = [elements[0], elements[n//2], elements[-1]]
    return (n, tuple((e["product_code"], e["length"], e["width"]) for e in samples))

@st.cache_data(show_spinner="Optimizing...")
def cached_optimize(ekey, elements_json, mat, thickness, num_sizes):
    return optimize_variable(elements_json, mat, thickness, num_sizes)

@st.cache_data(show_spinner="Running plate optimization (may take up to 30s)...")
def cached_auto(ekey, elements_json, mat, thickness):
    results = auto_optimize(elements_json, mat, thickness)
    if results:
        last_n = results[-1]["num_sizes"]
        extra = optimize_variable(elements_json, mat, thickness, last_n + 1)
        plates = extra["plates"]
        cfg = get_config(mat)
        pv = sum(p["plate_vol_m3"] for p in plates)
        bv = sum(p["box_vol_m3"] for p in plates)
        av = sum(p["actual_vol_m3"] for p in plates)
        wc = (pv - av) * cfg["price_m3"] if pv > 0 else 0
        results.append({
            "num_sizes": last_n + 1, "cutoffs": extra["cutoffs"], "plates": plates,
            "plate_vol": pv, "box_vol": bv, "actual_vol": av,
            "gross_loss": ((pv - bv) / pv * 100) if pv > 0 else 0,
            "nett_loss": ((pv - av) / pv * 100) if pv > 0 else 0,
            "waste_cost": wc, "savings": results[-1]["waste_cost"] - wc,
            "num_plates": len(plates), "below_threshold": True,
        })
    return results

@st.cache_data(show_spinner="Optimizing nesting (this may take a moment)...")
def compute_thickness_stats(ekey, mat, thickness, elements_json):
    """Compute stats for ONE material+thickness. Fast and independently cached."""
    cfg = get_config(mat)
    elems = elements_json
    if cfg["nestable"] and cfg["variable_length"]:
        auto_res = auto_optimize(elems, mat, thickness)
        plates = auto_res[-1]["plates"] if auto_res else []
    elif cfg["nestable"]:
        plates = nest_fixed(elems, mat).get(thickness, [])
    else:
        plates = []
    pv = sum(p["plate_vol_m3"] for p in plates) if plates else 0
    bv = sum(p["box_vol_m3"] for p in plates) if plates else 0
    av = sum(p["actual_vol_m3"] for p in plates) if plates else sum(e["volume"] for e in elems)
    el_vol = sum(e["volume"] for e in elems)
    return {
        "count": len(elems), "volume": el_vol,
        "plate_vol": pv, "box_vol": bv, "actual_vol": av,
        "gross_loss": ((pv - bv) / pv * 100) if pv > 0 else 0,
        "nett_loss": ((pv - av) / pv * 100) if pv > 0 else 0,
        "waste_cost": (pv - av) * cfg["price_m3"] if pv > 0 else 0,
        "material_cost": pv * cfg["price_m3"] if pv > 0 else el_vol * cfg["price_m3"],
        "num_plates": len(plates) if plates else (len(elems) if not cfg["nestable"] else 0),
        "plates": plates,
    }


def get_all_thickness_stats(mat, elements):
    """Get stats for all thicknesses of a material. Each cached independently."""
    by_t = defaultdict(list)
    for e in elements:
        by_t[e["thickness"]].append(e)
    results = {}
    for t, elems in by_t.items():
        ekey = _ekey(elems)
        results[t] = compute_thickness_stats(ekey, mat, t, elems)
    return results


def get_all_thickness_stats_batched(mat, elements, batch_mode, trucks):
    """Get stats with batch-based nesting. Each batch nested independently."""
    if batch_mode == "All Together":
        return get_all_thickness_stats(mat, elements)

    # Split elements (already filtered to this material) into batches
    batches = defaultdict(list)
    if batch_mode == "Per Module":
        for e in elements:
            batches[e.get("module", "0")].append(e)
    else:  # Per Truck or Per 2 Trucks
        mod_to_truck = {}
        for t in trucks:
            for m in t["modules"]:
                mod_to_truck[m] = t["truck_id"]
        group_size = 2 if batch_mode == "Per 2 Trucks" else 1
        for e in elements:
            truck_id = mod_to_truck.get(e.get("module", "0"), 0)
            batch_id = (truck_id - 1) // group_size if group_size > 1 else truck_id
            batches[batch_id].append(e)

    # Nest each batch independently, aggregate results
    agg = {}
    for batch_elems in batches.values():
        stats = get_all_thickness_stats(mat, batch_elems)
        for t, d in stats.items():
            if t not in agg:
                agg[t] = {"count": 0, "volume": 0, "plate_vol": 0, "box_vol": 0,
                          "actual_vol": 0, "waste_cost": 0, "material_cost": 0,
                          "num_plates": 0, "plates": []}
            a = agg[t]
            for k in ["count", "volume", "plate_vol", "box_vol", "actual_vol",
                       "waste_cost", "material_cost", "num_plates"]:
                a[k] += d[k]
            a["plates"].extend(d["plates"])

    for a in agg.values():
        pv = a["plate_vol"]
        a["gross_loss"] = ((pv - a["box_vol"]) / pv * 100) if pv > 0 else 0
        a["nett_loss"] = ((pv - a["actual_vol"]) / pv * 100) if pv > 0 else 0

    return agg


# ── Charts ────────────────────────────────────────────────────────────────

ELEM_COLORS = px.colors.qualitative.Set3 + px.colors.qualitative.Pastel1

def plot_length_bars(elements, cutoffs, title, color="#4fc3f7"):
    se = sorted(elements, key=lambda e: e["length"], reverse=True)
    fig = go.Figure(go.Bar(
        x=list(range(len(se))), y=[e["length"] for e in se],
        marker_color=color, opacity=0.85,
        hovertext=[f"{e['product_code']}\n{e['element_name']}\n{e['length']}×{e['width']}mm" for e in se],
        hovertemplate="%{hovertext}<extra></extra>",
    ))
    palette = ["#ff5252", "#ff9800", "#ffeb3b", "#66bb6a", "#42a5f5", "#ab47bc", "#26c6da"]
    for i, c in enumerate(sorted(cutoffs, reverse=True)):
        fig.add_hline(y=c, line_dash="dash", line_color=palette[i % len(palette)],
                      annotation_text=f"Plate {c}mm", annotation_position="top left",
                      annotation_font_color=palette[i % len(palette)])
    fig.update_layout(title=title, xaxis_title="Elements (sorted by length)",
                      yaxis_title="Length (mm)", template="plotly_dark", height=380,
                      showlegend=False, margin=dict(t=40, b=30, l=50, r=20))
    return fig


def draw_plate(plate):
    fig = go.Figure()
    pl, pw = plate["plate_length"], plate["plate_width"]
    fig.add_shape(type="rect", x0=0, y0=0, x1=pl, y1=pw,
                  line=dict(color="#555", width=2), fillcolor="rgba(30,30,46,0.9)")
    hx, hy, ht = [], [], []
    for i, p in enumerate(plate["placements"]):
        fig.add_shape(type="rect", x0=p["px"], y0=p["py"],
                      x1=p["px"] + p["pw"], y1=p["py"] + p["ph"],
                      line=dict(color="white", width=0.5),
                      fillcolor=ELEM_COLORS[i % len(ELEM_COLORS)], opacity=0.75)
        hx.append(p["px"] + p["pw"] / 2)
        hy.append(p["py"] + p["ph"] / 2)
        ht.append(f"<b>{p['product_code']}</b><br>{p['element_name']}<br>{p['pw']}×{p['ph']}mm")
    fig.add_trace(go.Scatter(
        x=hx, y=hy, mode="markers",
        marker=dict(size=max(3, min(14, 600 // max(len(hx), 1))), opacity=0),
        hovertext=ht, hoverinfo="text", showlegend=False))
    ar = pw / pl if pl > 0 else 0.5
    fig.update_layout(height=max(80, int(280 * ar)),
                      xaxis=dict(range=[-5, pl + 5], visible=False, scaleanchor="y"),
                      yaxis=dict(range=[-5, pw + 5], visible=False),
                      template="plotly_dark", margin=dict(l=1, r=1, t=1, b=1),
                      hoverlabel=dict(bgcolor="black", font_size=11))
    return fig


def render_plates(plates, key_prefix, per_page=120):
    if not plates:
        st.info("No plates.")
        return
    lmap = defaultdict(list)
    for p in plates:
        lmap[plate_layout_key(p)].append(p)
    unique = list(lmap.values())
    st.markdown(f"**{len(plates)} plates — {len(unique)} unique layouts**")
    total_pages = max(1, math.ceil(len(unique) / per_page))
    if total_pages > 1:
        page = st.number_input("Page", 1, total_pages, 1, key=f"{key_prefix}_pg") - 1
    else:
        page = 0
    start, end = page * per_page, min((page + 1) * per_page, len(unique))
    showing = unique[start:end]
    for rs in range(0, len(showing), 5):
        cols = st.columns(min(5, len(showing) - rs))
        for ci, col in enumerate(cols):
            gi = rs + ci
            if gi >= len(showing): break
            grp = showing[gi]
            pl = grp[0]
            with col:
                st.markdown(f"<div class='plate-label'>{len(grp)}× — "
                            f"{pl['plate_length']}×{pl['plate_width']} "
                            f"({len(pl['placements'])} el)</div>", unsafe_allow_html=True)
                st.plotly_chart(draw_plate(pl), use_container_width=True,
                               key=f"{key_prefix}_{start + gi}")


# ══════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════

def main():
    st.title("CNC Material-Optimizer")

    uploaded = st.file_uploader("Drop your CSV file(s) here", type=["csv"],
                                accept_multiple_files=True)
    if not uploaded:
        st.info("Upload one or more CSV files to start.")
        return

    file_bytes = tuple(f.getvalue() for f in uploaded)
    all_elements, raw_df = parse_csv(file_bytes_list=file_bytes)
    if len(uploaded) > 1:
        st.caption(f"Loaded {len(uploaded)} files — {len(all_elements):,} elements combined")
    else:
        st.caption(f"Loaded {uploaded[0].name} — {len(all_elements):,} elements")
    if not all_elements:
        st.error("No valid elements found.")
        return

    valid, oob = filter_out_of_bounds(all_elements)
    oob_by_mat = defaultdict(list)
    for e in oob: oob_by_mat[e["material"]].append(e)
    mat_groups = defaultdict(list)
    for e in valid: mat_groups[e["material"]].append(e)
    mat_order = [m for m in ["LVLQ","LVLS","LVLB","SPANO","FERM","GIPF","GIPA","CEM","PRO","BAUB"]
                 if m in mat_groups]

    # ── Batch size selector ──
    from logistics import pack_trucks
    trucks = pack_trucks(all_elements)
    n_mods = len(set(e.get("module", "0") for e in all_elements))
    n_trucks = len(trucks)

    batch_mode = st.radio(
        "Nesting batch size",
        ["Per Module", "Per Truck", "Per 2 Trucks", "All Together"],
        index=3,
        horizontal=True,
        help=(f"**Per Module** — nest each module independently ({n_mods} modules). "
              f"**Per Truck** — nest each truck-load together ({n_trucks} trucks). "
              f"**Per 2 Trucks** — nest every 2 trucks together ({math.ceil(n_trucks/2)} batches). "
              f"**All Together** — nest all elements in one batch (best yield)."),
        key="batch_mode",
    )

    if "page" not in st.session_state:
        st.session_state["page"] = None

    active_mat = st.session_state["page"]
    inject_nav_css(mat_order, active_mat)

    # ── Material nav bar ──
    nav = st.container()
    with nav:
        st.markdown('<div id="mat-nav">', unsafe_allow_html=True)
        nav_cols = st.columns([1.1] + [1] * len(mat_order) + [1.2, 1.2, 1, 1])
        with nav_cols[0]:
            if st.button("Overview", use_container_width=True, key="nav_ov"):
                st.session_state["page"] = None
                st.rerun()
        for i, mat in enumerate(mat_order):
            with nav_cols[i + 1]:
                if st.button(mat, use_container_width=True, key=f"nav_{mat}"):
                    st.session_state["page"] = mat
                    st.rerun()

        # Logistics
        with nav_cols[-4]:
            if st.button("Logistics", use_container_width=True, key="nav_log"):
                st.session_state["page"] = "__logistics__"
                st.rerun()

        # Batch Analysis
        with nav_cols[-3]:
            if st.button("Batch", use_container_width=True, key="nav_batch"):
                st.session_state["page"] = "__batch__"
                st.rerun()

        # Errors
        err_count = len(oob)
        all_low_vol = []
        for mat in mat_order:
            cfg = get_config(mat)
            stats = get_all_thickness_stats_batched(mat, mat_groups[mat], batch_mode, trucks)
            for t, d in stats.items():
                cost = d.get("material_cost", d["volume"] * cfg["price_m3"])
                if cost < 1000 and cfg.get("nestable", False):
                    t_elems = [e for e in mat_groups[mat] if e["thickness"] == t]
                    pp_codes = list(set(e["product_code"] for e in t_elems))[:20]
                    all_low_vol.append({"material": mat, "thickness": t,
                                       "volume": d["volume"], "count": d["count"],
                                       "cost": cost, "pp_codes": pp_codes})
        total_issues = err_count + len(all_low_vol)
        with nav_cols[-2]:
            lbl = f"⚠ {total_issues}" if total_issues else "Errors"
            if st.button(lbl, use_container_width=True, key="nav_err"):
                st.session_state["page"] = "__errors__"
                st.rerun()

        with nav_cols[-1]:
            if st.button("🔍 Search", use_container_width=True, key="nav_search"):
                st.session_state["page"] = "__search__"
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("---")

    if active_mat is None:
        _page_overview(valid, oob, mat_groups, oob_by_mat, mat_order, all_elements,
                       batch_mode, trucks)
    elif active_mat == "__logistics__":
        _page_logistics(all_elements, raw_df)
    elif active_mat == "__batch__":
        _page_batch(all_elements)
    elif active_mat == "__search__":
        _page_search(all_elements)
    elif active_mat == "__errors__":
        _page_errors(oob, oob_by_mat, all_low_vol, all_elements)
    elif active_mat in mat_groups:
        _page_material(active_mat, mat_groups[active_mat], oob_by_mat.get(active_mat, []),
                       batch_mode, trucks)


# ── Errors Page ──────────────────────────────────────────────────────────

def _page_errors(oob, oob_by_mat, all_low_vol, all_elements):
    st.markdown("## Errors & Warnings")

    # Count all issues for summary
    issues = []

    # ── 1. Out of Bounds ──
    if oob:
        issues.append(f"{len(oob)} out-of-bounds")
        st.markdown(f"### Out of Bounds — {len(oob)} elements")
        st.caption("Exceed plate dimensions, need manual intervention.")
        rows = []
        for e in oob:
            cfg = get_config(e["material"])
            if cfg.get("nestable") and not cfg.get("variable_length"):
                constraint = f"Plate {cfg['plate_l']}×{cfg['plate_w']}mm"
            elif cfg.get("variable_length"):
                constraint = f"Max width {cfg['fixed_width']}mm"
            else:
                constraint = ""
            rows.append({"PP-Code": e["product_code"], "Element": e["element_name"],
                         "Material": e["material"], "L": e["length"], "W": e["width"],
                         "T": e["thickness"], "Constraint": constraint, "Building": e["building"]})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.success("No out-of-bounds elements.")

    # ── 2. Low Cost Thicknesses ──
    if all_low_vol:
        issues.append(f"{len(all_low_vol)} low-cost thicknesses")
        st.markdown("### Low Cost Material+Thickness (< €1,000)")
        st.caption("Consider combining with another order.")
        lv_rows = []
        for lv in all_low_vol:
            lv_rows.append({
                "Material": lv["material"],
                "Thickness": f"{lv['thickness']}mm",
                "Elements": lv["count"],
                "Volume (m³)": f"{lv['volume']:.3f}",
                "Cost (€)": f"€{lv['cost']:,.0f}",
                "PP-Codes": ", ".join(lv.get("pp_codes", [])[:10]),
            })
        st.dataframe(pd.DataFrame(lv_rows), use_container_width=True, hide_index=True)

    # ── 3. Orphan Elements (missing building or module) ──
    orphans = [e for e in all_elements if not e.get("building", "").strip() or not e.get("module", "").strip()]
    if orphans:
        issues.append(f"{len(orphans)} orphan elements")
        st.markdown(f"### Orphan Elements — {len(orphans)}")
        st.caption("Missing buildingNumber or moduleNumber — will break logistics.")
        st.dataframe(pd.DataFrame([{
            "PP-Code": e["product_code"], "Element": e["element_name"],
            "Material": e["material"], "Building": e.get("building", ""),
            "Module": e.get("module", ""),
        } for e in orphans[:200]]), use_container_width=True, hide_index=True)
        if len(orphans) > 200:
            st.caption(f"Showing 200 of {len(orphans)}")

    # ── 4. Zero/Negative Volume Check ──
    vol_issues = []
    for e in all_elements:
        if e["volume"] <= 0:
            vol_issues.append({**e, "issue": "Zero/negative volume"})
        else:
            box_vol = e["length"] * e["width"] * e["thickness"] / 1e9
            if box_vol > 0:
                ratio = e["volume"] / box_vol
                if ratio > 1.05:
                    vol_issues.append({**e, "issue": f"Volume > bounding box ({ratio:.2f}x)"})
                elif ratio < 0.3:
                    vol_issues.append({**e, "issue": f"Volume very low vs box ({ratio:.0%})"})

    if vol_issues:
        issues.append(f"{len(vol_issues)} volume anomalies")
        st.markdown(f"### Volume Anomalies — {len(vol_issues)}")
        st.caption("Elements with zero volume or unusual volume vs bounding box (may be data errors or highly profiled).")
        st.dataframe(pd.DataFrame([{
            "PP-Code": e["product_code"], "Element": e["element_name"],
            "Material": e["material"], "L": e["length"], "W": e["width"], "T": e["thickness"],
            "CSV Vol": f"{e['volume']:.5f}",
            "Box Vol": f"{e['length']*e['width']*e['thickness']/1e9:.5f}",
            "Issue": e["issue"],
        } for e in vol_issues[:200]]), use_container_width=True, hide_index=True)
        if len(vol_issues) > 200:
            st.caption(f"Showing 200 of {len(vol_issues)}")

    # ── Summary ──
    if not issues:
        st.success("No data quality issues found.")
    else:
        st.markdown("---")
        st.caption(f"Total: {', '.join(issues)}")


# ── Overview ──────────────────────────────────────────────────────────────

def _page_overview(valid, oob, mat_groups, oob_by_mat, mat_order, all_elements=None,
                   batch_mode="All Together", trucks=None):
    rows = []
    total_cost = total_waste = total_vol = total_count = total_plates = 0
    for mat in mat_order:
        stats = get_all_thickness_stats_batched(mat, mat_groups[mat], batch_mode, trucks)
        count = sum(d["count"] for d in stats.values())
        vol = sum(d["volume"] for d in stats.values())
        pvol = sum(d["plate_vol"] for d in stats.values())
        bvol = sum(d["box_vol"] for d in stats.values())
        cost = sum(d["material_cost"] for d in stats.values())
        waste = sum(d["waste_cost"] for d in stats.values())
        nplates = sum(d["num_plates"] for d in stats.values())
        gl = ((pvol - bvol) / pvol * 100) if pvol > 0 else 0
        nl = ((pvol - sum(d["actual_vol"] for d in stats.values())) / pvol * 100) if pvol > 0 else 0
        total_cost += cost; total_waste += waste; total_vol += vol
        total_count += count; total_plates += nplates
        rows.append({"mat": mat, "count": count, "vol": vol, "cost": cost,
                     "waste": waste, "plates": nplates, "gross_loss": gl, "nett_loss": nl})
    rows.sort(key=lambda r: r["cost"], reverse=True)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Elements", f"{total_count:,}")
    c2.metric("Total Volume", f"{total_vol:,.1f} m³")
    c3.metric("Gross Material Cost", f"€{total_cost:,.0f}")
    c4.metric("Total Waste Cost", f"€{total_waste:,.0f}")
    c5.metric("Total Plates", f"{total_plates:,}")

    col_pie, col_table = st.columns([1, 1.5])
    with col_pie:
        colors = [MAT_COLORS.get(r["mat"], "#888") for r in rows]
        fig = go.Figure(go.Pie(
            labels=[MAT_LABELS.get(r["mat"], r["mat"]) for r in rows],
            values=[round(r["cost"]) for r in rows],
            marker=dict(colors=colors), hole=0.4,
            textinfo="label+percent", textposition="outside",
            hovertemplate="%{label}: €%{value:,.0f}<extra></extra>", sort=False))
        fig.update_layout(title="Cost Distribution", template="plotly_dark",
                          height=440, margin=dict(t=50, b=20, l=20, r=20), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    with col_table:
        st.markdown("#### Material Summary (sorted by cost)")
        st.dataframe(pd.DataFrame([{
            "Material": MAT_LABELS.get(r["mat"], r["mat"]),
            "Elements": f"{r['count']:,}", "Volume (m³)": f"{r['vol']:.1f}",
            "Plates": r["plates"], "Gross Cost (€)": f"€{r['cost']:,.0f}",
            "Waste (€)": f"€{r['waste']:,.0f}",
            "Gross Loss": f"{r['gross_loss']:.1f}%", "Nett Loss": f"{r['nett_loss']:.1f}%",
        } for r in rows]), use_container_width=True, hide_index=True, height=420)

    # ── Plate Order Overview ──
    st.markdown("---")
    st.markdown("#### Plate Order Overview")
    st.caption("All plates to be ordered, grouped by material, thickness, and plate size.")

    order_rows = []
    for mat in mat_order:
        stats = get_all_thickness_stats_batched(mat, mat_groups[mat], batch_mode, trucks)
        cfg = get_config(mat)
        for t in sorted(stats):
            d = stats[t]
            if not d["plates"]:
                # Direct order materials
                if not cfg["nestable"]:
                    order_rows.append({
                        "Material": MAT_LABELS.get(mat, mat),
                        "Thickness (mm)": t,
                        "Plate Size": "To size",
                        "Qty": d["count"],
                        "Plate Vol (m³)": f"{d['volume']:.2f}",
                        "Cost (€)": f"€{d['material_cost']:,.0f}",
                    })
                continue
            # Group plates by size
            size_groups = defaultdict(int)
            size_vols = defaultdict(float)
            for p in d["plates"]:
                key = f"{p['plate_length']} × {p['plate_width']}"
                size_groups[key] += 1
                size_vols[key] += p["plate_vol_m3"]
            for size_str in sorted(size_groups):
                qty = size_groups[size_str]
                vol = size_vols[size_str]
                order_rows.append({
                    "Material": MAT_LABELS.get(mat, mat),
                    "Thickness (mm)": t,
                    "Plate Size": size_str,
                    "Qty": qty,
                    "Plate Vol (m³)": f"{vol:.2f}",
                    "Cost (€)": f"€{vol * cfg['price_m3']:,.0f}",
                })

    if order_rows:
        bom_df = pd.DataFrame(order_rows)
        st.dataframe(bom_df, use_container_width=True,
                     hide_index=True, height=min(600, 35 + 35 * len(order_rows)))

        # BOM Export
        st.download_button("Download BOM (CSV)", bom_df.to_csv(index=False).encode("utf-8"),
                           "bill_of_materials.csv", "text/csv", use_container_width=True)

    # ── Sankey Diagram ──
    st.markdown("---")
    st.markdown("#### Material Flow")
    _render_sankey(valid)

    # ── Building Step Breakdown ──
    st.markdown("---")
    _render_building_step_breakdown(valid, mat_groups, mat_order, batch_mode, trucks)

    with st.expander("Pricing reference"):
        st.dataframe(pd.DataFrame([
            {"Material": MAT_LABELS.get(m, m), "€/m³": f"€{c['price_m3']:,.0f}"}
            for m, c in MATERIAL_CONFIG.items()
        ]), use_container_width=True, hide_index=True, height=200)

    # ── PDF Report ──
    st.markdown("---")
    if all_elements is not None:
        if st.button("Generate PDF Report", type="primary", use_container_width=True,
                     key="gen_pdf"):
            with st.spinner("Generating PDF report..."):
                # Try to include logistics if dates are set
                log_result = None
                try:
                    from datetime import date as dt
                    first = st.session_state.get("log_first", dt(2026, 4, 1))
                    last = st.session_state.get("log_last", dt(2026, 6, 30))
                    log_result = process_logistics(all_elements, first, last)
                except Exception:
                    pass

                pdf_bytes = generate_report(
                    all_elements=all_elements, valid=valid, oob=oob,
                    mat_groups=mat_groups, mat_order=mat_order,
                    thickness_stats_fn=lambda m, e: get_all_thickness_stats_batched(m, e, batch_mode, trucks),
                    mat_colors=MAT_COLORS, mat_labels=MAT_LABELS,
                    get_config_fn=get_config,
                    logistics_result=log_result,
                )
            st.download_button("Download PDF Report", pdf_bytes,
                               "cnc_optimizer_report.pdf", "application/pdf",
                               use_container_width=True)


def _render_building_step_breakdown(elements, mat_groups, mat_order,
                                    batch_mode="All Together", trucks=None):
    """Building step pie chart + table with waste allocation."""
    st.markdown("#### Volume by Building Step")

    # Gather volume per building step
    step_vol = defaultdict(float)
    step_cost = defaultdict(float)
    step_count = defaultdict(int)
    for e in elements:
        step = e.get("building_step", "").strip() or "Unknown"
        cfg = get_config(e["material"])
        step_vol[step] += e["volume"]
        step_cost[step] += e["volume"] * cfg["price_m3"]
        step_count[step] += 1

    # Compute waste share per step (proportional to volume share per material)
    total_waste_by_mat = {}
    for mat in mat_order:
        stats = get_all_thickness_stats_batched(mat, mat_groups[mat], batch_mode, trucks)
        total_waste_by_mat[mat] = sum(d["waste_cost"] for d in stats.values())

    step_waste = defaultdict(float)
    mat_vol_totals = defaultdict(float)
    for e in elements:
        mat_vol_totals[e["material"]] += e["volume"]

    for e in elements:
        step = e.get("building_step", "").strip() or "Unknown"
        mat = e["material"]
        mat_total = mat_vol_totals[mat]
        if mat_total > 0 and mat in total_waste_by_mat:
            step_waste[step] += total_waste_by_mat[mat] * (e["volume"] / mat_total)

    sorted_steps = sorted(step_vol.items(), key=lambda x: -x[1])

    # Pie (top 12)
    if len(sorted_steps) > 12:
        top = sorted_steps[:12]
        top.append(("Other", sum(v for _, v in sorted_steps[12:])))
    else:
        top = sorted_steps

    col1, col2 = st.columns([1, 1.5])
    with col1:
        fig = go.Figure(go.Pie(
            labels=[s[0] for s in top], values=[round(s[1], 2) for s in top],
            hole=0.4, textinfo="label+percent", textposition="outside",
            hovertemplate="%{label}<br>%{value:.2f} m³<extra></extra>",
        ))
        fig.update_layout(template="plotly_dark", height=420,
                          margin=dict(t=20, b=20, l=10, r=10), showlegend=False,
                          font=dict(size=10))
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        step_rows = []
        for step, vol in sorted_steps:
            total_step_cost = step_cost[step] + step_waste[step]
            waste_pct = (step_waste[step] / total_step_cost * 100) if total_step_cost > 0 else 0
            step_rows.append({
                "Building Step": step,
                "Elements": step_count[step],
                "Volume (m³)": f"{vol:.2f}",
                "Material (€)": f"€{step_cost[step]:,.0f}",
                "Waste (€)": f"€{step_waste[step]:,.0f}",
                "Waste %": f"{waste_pct:.1f}%",
            })
        st.dataframe(pd.DataFrame(step_rows), use_container_width=True, hide_index=True,
                     height=min(420, 35 + 35 * len(step_rows)))



def _hex_to_rgba(hex_color, alpha):
    """Convert '#RRGGBB' to 'rgba(r,g,b,alpha)'."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _render_sankey(elements):
    """Sankey: Material → Thickness → Building."""
    labels = []
    label_idx = {}

    def get_idx(name):
        if name not in label_idx:
            label_idx[name] = len(labels)
            labels.append(name)
        return label_idx[name]

    sources, targets, values, link_colors = [], [], [], []
    flow_mat_thick = defaultdict(float)
    flow_thick_bldg = defaultdict(float)

    for e in elements:
        mat = e["material"]
        thick = f"{mat} {e['thickness']}mm"  # prefix to avoid label collision
        bldg = e.get("building", "?")
        vol = e["volume"]
        flow_mat_thick[(mat, thick)] += vol
        flow_thick_bldg[(thick, bldg)] += vol

    for (src, tgt), val in flow_mat_thick.items():
        if val < 0.005:
            continue
        sources.append(get_idx(src))
        targets.append(get_idx(tgt))
        values.append(round(val, 3))
        c = MAT_COLORS.get(src, "#888")
        link_colors.append(_hex_to_rgba(c, 0.25))

    for (src, tgt), val in flow_thick_bldg.items():
        if val < 0.005:
            continue
        sources.append(get_idx(src))
        targets.append(get_idx(tgt))
        values.append(round(val, 3))
        mat_name = src.split(" ")[0]
        c = MAT_COLORS.get(mat_name, "#888")
        link_colors.append(_hex_to_rgba(c, 0.18))

    node_colors = []
    for lbl in labels:
        if lbl in MAT_COLORS:
            node_colors.append(MAT_COLORS[lbl])
        elif "mm" in lbl:
            mat_name = lbl.split(" ")[0]
            node_colors.append(MAT_COLORS.get(mat_name, "#78909C"))
        elif lbl.startswith("BN"):
            node_colors.append("#FFA726")
        else:
            node_colors.append("#999")

    # Clean labels: remove material prefix from thickness labels for display
    display_labels = []
    for lbl in labels:
        if "mm" in lbl and " " in lbl:
            display_labels.append(lbl.split(" ", 1)[1])  # "LVLQ 33mm" → "33mm"
        else:
            display_labels.append(lbl)

    fig = go.Figure(go.Sankey(
        node=dict(pad=20, thickness=18, label=display_labels, color=node_colors),
        link=dict(source=sources, target=targets, value=values, color=link_colors),
    ))
    fig.update_layout(title="Material → Thickness → Building",
                      template="plotly_dark", height=450,
                      margin=dict(t=40, b=20, l=20, r=20),
                      font=dict(size=11))
    st.plotly_chart(fig, use_container_width=True)


# ── Material Detail ──────────────────────────────────────────────────────

def _page_material(mat, elements, oob_elems, batch_mode="All Together", trucks=None):
    cfg = get_config(mat)
    color = MAT_COLORS.get(mat, "#888")
    label = MAT_LABELS.get(mat, mat)

    # Use pre-computed per-thickness stats (each independently cached)
    stats = get_all_thickness_stats_batched(mat, elements, batch_mode, trucks or [])

    info_parts = [f"€{cfg['price_m3']:,.0f}/m³"]
    if cfg.get("variable_length"):
        info_parts.append(f"Fixed width: {cfg['fixed_width']}mm")
    elif cfg.get("nestable"):
        info_parts.append(f"Plate: {cfg['plate_l']}×{cfg['plate_w']}mm")
    else:
        info_parts.append("Ordered to size")

    st.markdown(
        f"<div style='border-left:5px solid {color}; padding:6px 14px; "
        f"background:{color}12; border-radius:5px; margin-bottom:6px'>"
        f"<span style='font-size:1.4rem; font-weight:700; color:{color}'>{label}</span>"
        f"<span style='opacity:0.6; margin-left:10px; font-size:0.85rem'>"
        f"{' | '.join(info_parts)}</span></div>", unsafe_allow_html=True)

    total_vol = sum(d["volume"] for d in stats.values())
    total_cost = sum(d["material_cost"] for d in stats.values())
    total_waste = sum(d["waste_cost"] for d in stats.values())
    total_plates = sum(d["num_plates"] for d in stats.values())

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Elements", f"{len(elements):,}")
    c2.metric("Volume", f"{total_vol:.2f} m³")
    c3.metric("Gross Cost", f"€{total_cost:,.0f}")
    c4.metric("Waste Cost", f"€{total_waste:,.0f}")
    c5.metric("Plates", f"{total_plates:,}")

    # ── Thickness nav using segmented_control ──
    thicknesses = sorted(stats.keys())
    options = ["Overview"] + [f"{t}mm" for t in thicknesses]

    sel = st.segmented_control("Thickness", options, default="Overview",
                                key=f"tseg_{mat}",
                                selection_mode="single")

    if sel is None or sel == "Overview":
        _thickness_overview(mat, stats, thicknesses, color)
    else:
        sel_t = int(sel.replace("mm", ""))
        t_elems = [e for e in elements if e["thickness"] == sel_t]
        td = stats[sel_t]
        if not cfg["nestable"]:
            _render_direct(mat, t_elems, sel_t, color)
        elif not cfg["variable_length"]:
            _render_fixed(mat, t_elems, sel_t, color, cfg, td)
        else:
            _render_variable(mat, t_elems, sel_t, color, cfg, td)


def _thickness_overview(mat, stats, thicknesses, color):
    if len(thicknesses) <= 1:
        st.caption(f"Single thickness: {thicknesses[0]}mm — select it above.")
        return
    pc, tc = st.columns([1, 1.5])
    with pc:
        fig = go.Figure(go.Pie(
            labels=[f"{t}mm" for t in thicknesses],
            values=[stats[t]["material_cost"] for t in thicknesses],
            hole=0.4, textinfo="label+percent", textposition="outside",
            hovertemplate="%{label}: €%{value:,.0f}<extra></extra>",
            marker=dict(colors=px.colors.sequential.Blues_r[:len(thicknesses)])))
        fig.update_layout(title=f"{mat} — Cost by Thickness", template="plotly_dark",
                          height=350, margin=dict(t=50, b=20, l=20, r=20), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    with tc:
        st.markdown("#### Thickness Breakdown")
        st.dataframe(pd.DataFrame([{
            "Thickness": f"{t}mm" + (" ⚠" if stats[t]["material_cost"] < 1000 else ""),
            "Elements": stats[t]["count"],
            "Volume (m³)": f"{stats[t]['volume']:.2f}",
            "Plates": stats[t]["num_plates"],
            "Gross Cost (€)": f"€{stats[t]['material_cost']:,.0f}",
            "Waste (€)": f"€{stats[t]['waste_cost']:,.0f}",
            "Gross Loss": f"{stats[t]['gross_loss']:.1f}%",
            "Nett Loss": f"{stats[t]['nett_loss']:.1f}%",
        } for t in thicknesses]), use_container_width=True, hide_index=True)


def _render_direct(mat, elements, thickness, color):
    if not elements: return
    max_l = max(e["length"] for e in elements)
    st.markdown("<div class='info-inline'>Ordered to exact size — no nesting.</div>",
                unsafe_allow_html=True)
    st.plotly_chart(plot_length_bars(elements, [max_l],
                                     f"{mat} T={thickness}mm — Elements by Length", color),
                    use_container_width=True)
    c1, c2, c3 = st.columns(3)
    c1.metric("Longest", f"{max_l} mm")
    c2.metric("Shortest", f"{min(e['length'] for e in elements)} mm")
    c3.metric("Average", f"{sum(e['length'] for e in elements) / len(elements):.0f} mm")


def _render_fixed(mat, elements, thickness, color, cfg, td):
    pl, pw = cfg["plate_l"], cfg["plate_w"]
    st.markdown(f"<div class='info-inline'>Fixed plate: <b>{pl}×{pw}mm</b></div>",
                unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Plates", td["num_plates"])
    c2.metric("Gross Cost", f"€{td['material_cost']:,.0f}")
    c3.metric("Gross Loss", f"{td['gross_loss']:.1f}%")
    c4.metric("Waste Cost", f"€{td['waste_cost']:,.0f}")
    st.plotly_chart(plot_length_bars(elements, [pl],
                                     f"{mat} T={thickness}mm — Elements by Length", color),
                    use_container_width=True)
    with st.expander(f"Plate Layouts ({td['num_plates']} plates)"):
        render_plates(td["plates"], f"fx_{mat}_{thickness}")


def _render_variable(mat, elements, thickness, color, cfg, td):
    st.markdown(f"<div class='info-inline'>Fixed width: <b>{cfg['fixed_width']}mm</b> | "
                f"Kerf: {cfg['kerf']}mm | Margin: {cfg['margin']}mm</div>",
                unsafe_allow_html=True)

    # Use pre-computed stats from td — no recalculation needed
    plates = td["plates"]
    cutoffs = list(set(p["plate_length"] for p in plates)) if plates else []

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Plates", td["num_plates"])
    c2.metric("Gross Cost", f"€{td['material_cost']:,.0f}")
    c3.metric("Gross Loss", f"{td['gross_loss']:.1f}%")
    c4.metric("Nett Loss", f"{td['nett_loss']:.1f}%")
    c5.metric("Waste Cost", f"€{td['waste_cost']:,.0f}")

    if cutoffs:
        for c in sorted(cutoffs):
            gp = [p for p in plates if p["plate_length"] == c]
            if gp:
                st.markdown(f"**Plate {c}mm:** {len(gp)} plates "
                            f"({sum(p['plate_vol_m3'] for p in gp):.2f} m³)")

    with st.expander("Optimization details"):
        ekey = _ekey(elements)
        results = cached_auto(ekey, elements, mat, thickness)
        optimal = results[-2] if len(results) > 1 else results[0]
        opt_n = optimal["num_sizes"]
        _show_auto_table(results, color, opt_n)
        num_sizes = st.number_input("Override plate count", 1, 8, opt_n,
                                    key=f"ns_{mat}_{thickness}")
        if num_sizes != opt_n:
            res = cached_optimize(ekey, elements, mat, thickness, num_sizes)
            override_plates = res["plates"]
            cutoffs = res["cutoffs"]
            plates = override_plates
            pv2 = sum(p["plate_vol_m3"] for p in plates)
            bv2 = sum(p["box_vol_m3"] for p in plates)
            mc2 = pv2 * cfg["price_m3"]
            wc2 = (pv2 - sum(p["actual_vol_m3"] for p in plates)) * cfg["price_m3"]
            gl2 = ((pv2 - bv2) / pv2 * 100) if pv2 > 0 else 0
            st.markdown(f"**Override:** {len(plates)} plates, "
                        f"€{mc2:,.0f} gross, {gl2:.1f}% loss, €{wc2:,.0f} waste")

    if cutoffs:
        st.plotly_chart(plot_length_bars(elements, cutoffs,
                                         f"{mat} T={thickness}mm — Elements by Length", color),
                        use_container_width=True)

    with st.expander(f"Plate Layouts ({len(plates)} plates)"):
        render_plates(plates, f"var_{mat}_{thickness}")


def _show_auto_table(results, color, opt_n):
    st.dataframe(pd.DataFrame([{
        "": "✓" if r["num_sizes"] == opt_n else ("..." if r.get("below_threshold") else ""),
        "# Sizes": r["num_sizes"],
        "Cutoffs (mm)": ", ".join(map(str, r["cutoffs"])),
        "Plates": r["num_plates"],
        "Plate Vol (m³)": f"{r['plate_vol']:.2f}",
        "Gross Loss": f"{r['gross_loss']:.1f}%",
        "Nett Loss": f"{r['nett_loss']:.1f}%",
        "Waste (€)": f"€{r['waste_cost']:,.0f}",
        "Savings (€)": f"€{r['savings']:,.0f}",
    } for r in results]), use_container_width=True, hide_index=True)


# ── Logistics & Packaging ────────────────────────────────────────────────

from datetime import date, timedelta

def _page_logistics(all_elements, raw_df):
    st.markdown(
        "<div style='border-left:5px solid #7E57C2; padding:6px 14px; "
        "background:#7E57C212; border-radius:5px; margin-bottom:8px'>"
        "<span style='font-size:1.4rem; font-weight:700; color:#7E57C2'>"
        "Logistics & Packaging</span>"
        "<span style='opacity:0.6; margin-left:10px; font-size:0.85rem'>"
        "Truck packing, delivery scheduling, package codes</span></div>",
        unsafe_allow_html=True)

    # Date inputs
    dc1, dc2 = st.columns(2)
    with dc1:
        first_date = st.date_input("First Truck Delivery Date",
                                   value=date(2026, 4, 1), key="log_first")
    with dc2:
        last_date = st.date_input("Last Truck Delivery Date",
                                  value=date(2026, 6, 30), key="log_last")

    if last_date < first_date:
        st.error("Last date must be after first date.")
        return

    # Run logistics computation
    result = process_logistics(all_elements, first_date, last_date)
    trucks = result["trucks"]
    packages = result["packages"]
    assignments = result["assignments"]

    # Top metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Trucks", result["total_trucks"])
    c2.metric("Packages", result["total_packages"])
    c3.metric("Total Weight", f"{result['total_weight']:,.0f} kg")
    c4.metric("Elements", f"{len(all_elements):,}")

    # Build export CSV
    export_df = _build_export_df(raw_df, all_elements, assignments)

    st.download_button(
        label="Download Processed CSV",
        data=export_df.to_csv(index=False).encode("utf-8"),
        file_name="processed_logistics.csv",
        mime="text/csv",
        type="primary",
        use_container_width=True,
    )

    st.markdown("---")

    # ── Gantt Chart ──
    st.markdown("#### Delivery Timeline")
    gantt_data = []
    for truck in trucks:
        util = truck["weight"] / 24000 * 100
        gantt_data.append({
            "Truck": f"Truck {truck['truck_id']}",
            "Date": truck["delivery_date"],
            "Weight": truck["weight"],
            "Utilization": util,
            "Modules": len(truck["modules"]),
        })
    gdf = pd.DataFrame(gantt_data)
    fig_gantt = go.Figure()
    for _, row in gdf.iterrows():
        util = row["Utilization"]
        color = "#66BB6A" if util > 90 else "#FFA726" if util > 75 else "#EF5350"
        fig_gantt.add_trace(go.Bar(
            x=[row["Weight"]], y=[row["Truck"]], orientation="h",
            marker_color=color, opacity=0.85,
            hovertemplate=f"{row['Truck']}<br>{row['Date']}<br>"
                          f"{row['Weight']:,.0f} kg ({util:.0f}%)<br>"
                          f"{row['Modules']} modules<extra></extra>",
            showlegend=False,
        ))
    fig_gantt.add_vline(x=24000, line_dash="dash", line_color="#ff5252",
                        annotation_text="24t")
    fig_gantt.update_layout(
        xaxis=dict(title="Weight (kg)", range=[0, 25500]),
        yaxis=dict(autorange="reversed"),
        template="plotly_dark", height=max(200, len(trucks) * 28 + 60),
        margin=dict(l=80, r=20, t=20, b=40),
        barmode="stack",
    )
    # Add date annotations on the right
    for _, row in gdf.iterrows():
        fig_gantt.add_annotation(
            x=row["Weight"] + 200, y=row["Truck"],
            text=str(row["Date"]), showarrow=False,
            font=dict(size=10, color="#aaa"), xanchor="left")
    st.plotly_chart(fig_gantt, use_container_width=True)

    st.markdown("---")

    # Truck detail expanders
    for truck in trucks:
        tid = truck["truck_id"]
        dd = truck["delivery_date"]
        tw = truck["weight"]
        mods = truck["modules"]
        truck_pkgs = [p for p in packages if p["truck_id"] == tid]
        utilization = tw / 24000 * 100

        with st.expander(
            f"Truck {tid}  —  {dd.strftime('%Y-%m-%d')}  |  "
            f"{tw:,.0f} kg ({utilization:.0f}%)  |  "
            f"{len(mods)} modules  |  {len(truck_pkgs)} packages",
            expanded=False,
        ):
            # Truck summary bar
            fig = go.Figure(go.Bar(
                x=[tw], y=[""], orientation="h",
                marker_color="#7E57C2", opacity=0.8,
                text=[f"{tw:,.0f} kg"], textposition="inside",
                hovertemplate=f"Truck {tid}: {tw:,.0f} / 24,000 kg<extra></extra>",
            ))
            fig.add_vline(x=24000, line_dash="dash", line_color="#ff5252",
                          annotation_text="24t limit")
            fig.update_layout(xaxis=dict(range=[0, 25000], title="Weight (kg)"),
                              yaxis=dict(visible=False),
                              template="plotly_dark", height=70,
                              margin=dict(l=5, r=5, t=5, b=25))
            st.plotly_chart(fig, use_container_width=True,
                           key=f"truck_bar_{tid}")

            st.caption(f"Modules: {', '.join(str(m) for m in sorted(mods, key=lambda x: int(x) if x.isdigit() else 0))}")

            # Packages table
            pkg_rows = [{
                "Package": p["package_code"],
                "Building Step": p["building_step"],
                "Elements": p["element_count"],
                "Weight (kg)": f"{p['weight']:,.1f}",
            } for p in truck_pkgs]
            st.dataframe(pd.DataFrame(pkg_rows), use_container_width=True,
                         hide_index=True, key=f"pkg_table_{tid}")

            # Expandable element detail per package
            for p in truck_pkgs:
                with st.expander(
                    f"{p['package_code']}  —  {p['building_step']}  "
                    f"({p['element_count']} elements)",
                    expanded=False,
                ):
                    elem_rows = [{
                        "Product Code": e["product_code"],
                        "Composite": e.get("composite_code", ""),
                        "Element": e["element_name"],
                        "Module": e["module"],
                        "Material": e["material"],
                        "Weight": f"{e['weight']:.1f}",
                    } for e in p["elements"]]
                    st.dataframe(pd.DataFrame(elem_rows),
                                 use_container_width=True, hide_index=True,
                                 key=f"elem_{p['package_code']}")


def _build_export_df(raw_df, all_elements, assignments):
    """Build export DataFrame with deliveryDate and packageCode columns."""
    # Map element index to assignment
    delivery_dates = []
    package_codes = []

    for e in all_elements:
        key = id(e)
        if key in assignments:
            a = assignments[key]
            delivery_dates.append(a["delivery_date"].strftime("%Y-%m-%d"))
            package_codes.append(a["package_code"])
        else:
            delivery_dates.append("")
            package_codes.append("")

    # The raw_df may have more rows than all_elements (elements with unknown materials
    # were filtered out). We need to align by matching rows.
    # Since make_element filters by MATERIAL_CONFIG, we track which raw rows matched.
    export = raw_df.copy()
    export["deliveryDate"] = ""
    export["packageCode"] = ""

    # Walk through raw_df and all_elements in parallel
    elem_idx = 0
    for i, row in raw_df.iterrows():
        mat = str(row.get("materialId", "")).strip()
        if mat in MATERIAL_CONFIG and elem_idx < len(all_elements):
            if elem_idx < len(delivery_dates):
                export.at[i, "deliveryDate"] = delivery_dates[elem_idx]
                export.at[i, "packageCode"] = package_codes[elem_idx]
            elem_idx += 1

    return export


# ── Batch Size Analysis ──────────────────────────────────────────────────

def _page_batch(all_elements):
    st.markdown(
        "<div style='border-left:5px solid #FF7043; padding:6px 14px; "
        "background:#FF704312; border-radius:5px; margin-bottom:8px'>"
        "<span style='font-size:1.4rem; font-weight:700; color:#FF7043'>"
        "Batch Size Analysis</span>"
        "<span style='opacity:0.6; margin-left:10px; font-size:0.85rem'>"
        "How does yield change with batch size?</span></div>",
        unsafe_allow_html=True)

    st.caption("This analysis nests elements for different batch sizes (modules and trucks) "
               "to show how yield improves with larger batches. This is compute-intensive.")

    # Group elements by module (sorted numerically)
    mod_elems = defaultdict(list)
    for e in all_elements:
        mod_elems[e.get("module", "0")].append(e)

    def _msort(m):
        try: return int(m)
        except: return 99999

    sorted_modules = sorted(mod_elems.keys(), key=_msort)
    total_modules = len(sorted_modules)

    # Build truck groupings using sequential packing
    from logistics import compute_module_weights, pack_trucks
    trucks = pack_trucks(all_elements)
    total_trucks = len(trucks)

    # Define batch points
    module_points = [n for n in [1, 2, 3, 4, 5, 6, 8, 10, 15, 20] if n <= total_modules]
    if total_modules not in module_points:
        module_points.append(total_modules)

    truck_points = [n for n in [1, 2, 3, 5, 10, 15, 20] if n <= total_trucks]
    if total_trucks not in truck_points:
        truck_points.append(total_trucks)

    st.markdown(f"**{total_modules} modules** across **{total_trucks} trucks** — "
                f"{len(all_elements):,} elements total")

    # Check for cached results
    if "batch_results" not in st.session_state:
        st.session_state["batch_results"] = None

    if st.button("Run Batch Analysis", type="primary", use_container_width=True, key="run_batch"):
        st.session_state["batch_results"] = None  # reset

        results = []
        progress = st.progress(0, text="Starting batch analysis...")
        total_steps = len(module_points) + len(truck_points)
        step = 0

        # Module batches
        for n_mods in module_points:
            step += 1
            progress.progress(step / total_steps,
                              text=f"Nesting {n_mods} module{'s' if n_mods>1 else ''} "
                                   f"({step}/{total_steps})...")
            batch_mods = sorted_modules[:n_mods]
            batch_elems = []
            for m in batch_mods:
                batch_elems.extend(mod_elems[m])

            valid_b, _ = filter_out_of_bounds(batch_elems)
            stats = _compute_batch_yield(valid_b)
            results.append({
                "batch": f"{n_mods} module{'s' if n_mods>1 else ''}",
                "batch_type": "modules",
                "n": n_mods,
                "elements": len(valid_b),
                **stats,
            })

        # Truck batches
        for n_trucks in truck_points:
            step += 1
            progress.progress(step / total_steps,
                              text=f"Nesting {n_trucks} truck{'s' if n_trucks>1 else ''} "
                                   f"({step}/{total_steps})...")
            batch_mods = set()
            for t in trucks[:n_trucks]:
                batch_mods.update(t["modules"])
            batch_elems = []
            for m in batch_mods:
                batch_elems.extend(mod_elems.get(m, []))

            valid_b, _ = filter_out_of_bounds(batch_elems)
            stats = _compute_batch_yield(valid_b)
            results.append({
                "batch": f"{n_trucks} truck{'s' if n_trucks>1 else ''}",
                "batch_type": "trucks",
                "n": n_trucks,
                "elements": len(valid_b),
                **stats,
            })

        progress.empty()
        st.session_state["batch_results"] = results

    results = st.session_state.get("batch_results")
    if results is None:
        st.info("Click the button above to start the analysis.")
        return

    # ── Results table ──
    st.markdown("### Results")
    table_rows = [{
        "Batch": r["batch"],
        "Elements": f"{r['elements']:,}",
        "Volume (m³)": f"{r['element_vol']:.1f}",
        "Plate Vol (m³)": f"{r['plate_vol']:.1f}",
        "Yield %": f"{r['yield_pct']:.1f}%",
        "Gross Yield %": f"{r['gross_yield_pct']:.1f}%",
        "Waste (€)": f"EUR{r['waste_cost']:,.0f}",
        "Plates": r["num_plates"],
    } for r in results]
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    # ── Chart ──
    mod_results = [r for r in results if r["batch_type"] == "modules"]
    truck_results = [r for r in results if r["batch_type"] == "trucks"]

    fig = go.Figure()

    if mod_results:
        fig.add_trace(go.Scatter(
            x=[r["elements"] for r in mod_results],
            y=[r["yield_pct"] for r in mod_results],
            mode="lines+markers+text",
            name="By Modules",
            marker=dict(color="#FF7043", size=10),
            text=[r["batch"] for r in mod_results],
            textposition="top center",
            textfont=dict(size=9),
            hovertemplate="%{text}<br>%{x:,} elements<br>Yield: %{y:.1f}%<extra></extra>",
        ))

    if truck_results:
        fig.add_trace(go.Scatter(
            x=[r["elements"] for r in truck_results],
            y=[r["yield_pct"] for r in truck_results],
            mode="lines+markers+text",
            name="By Trucks",
            marker=dict(color="#7E57C2", size=10),
            text=[r["batch"] for r in truck_results],
            textposition="bottom center",
            textfont=dict(size=9),
            hovertemplate="%{text}<br>%{x:,} elements<br>Yield: %{y:.1f}%<extra></extra>",
        ))

    fig.update_layout(
        title="Yield % vs Batch Size",
        xaxis_title="Number of Elements in Batch",
        yaxis_title="Nett Yield %",
        template="plotly_dark", height=450,
        margin=dict(t=50, b=40, l=50, r=20),
        legend=dict(yanchor="bottom", y=0.05, xanchor="right", x=0.95),
        yaxis=dict(range=[
            min(r["yield_pct"] for r in results) - 3,
            max(r["yield_pct"] for r in results) + 3,
        ]),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Insight ──
    if len(results) >= 2:
        worst = min(results, key=lambda r: r["yield_pct"])
        best = max(results, key=lambda r: r["yield_pct"])
        st.markdown(f"**Lowest yield:** {worst['batch']} at {worst['yield_pct']:.1f}% — "
                    f"**Highest yield:** {best['batch']} at {best['yield_pct']:.1f}% — "
                    f"**Improvement:** {best['yield_pct'] - worst['yield_pct']:.1f} percentage points")


def _compute_batch_yield(elements):
    """Compute total yield for a batch — uses fast single-pass nesting."""
    from nesting import get_config, optimize_variable_fast, nest_fixed_fast

    by_mat = defaultdict(lambda: defaultdict(list))
    for e in elements:
        by_mat[e["material"]][e["thickness"]].append(e)

    total_pv = 0
    total_bv = 0
    total_av = 0
    total_plates = 0
    total_cost = 0

    for mat, by_t in by_mat.items():
        cfg = get_config(mat)
        for t, elems in by_t.items():
            if cfg["nestable"] and cfg["variable_length"]:
                plates = optimize_variable_fast(elems, mat, t)
            elif cfg["nestable"]:
                plates = nest_fixed_fast(elems, mat).get(t, [])
            else:
                plates = []

            pv = sum(p["plate_vol_m3"] for p in plates) if plates else 0
            bv = sum(p["box_vol_m3"] for p in plates) if plates else 0
            av = sum(p["actual_vol_m3"] for p in plates) if plates else sum(e["volume"] for e in elems)

            if not cfg["nestable"]:
                pv = sum(e["volume"] for e in elems)
                bv = pv
                av = pv

            total_pv += pv
            total_bv += bv
            total_av += av
            total_plates += len(plates) if plates else len(elems)
            total_cost += (pv - av) * cfg["price_m3"] if pv > 0 else 0

    yield_pct = (total_av / total_pv * 100) if total_pv > 0 else 0
    gross_yield_pct = (total_bv / total_pv * 100) if total_pv > 0 else 0

    return {
        "element_vol": sum(e["volume"] for e in elements),
        "plate_vol": total_pv,
        "box_vol": total_bv,
        "actual_vol": total_av,
        "yield_pct": yield_pct,
        "gross_yield_pct": gross_yield_pct,
        "waste_cost": total_cost,
        "num_plates": total_plates,
    }


# ── Element Search ────────────────────────────────────────────────────────

def _page_search(all_elements):
    st.markdown(
        "<div style='border-left:5px solid #29B6F6; padding:6px 14px; "
        "background:#29B6F612; border-radius:5px; margin-bottom:8px'>"
        "<span style='font-size:1.4rem; font-weight:700; color:#29B6F6'>"
        "Element Search</span></div>", unsafe_allow_html=True)

    query = st.text_input("Search by PP-code, element name, or composite code",
                          placeholder="e.g. PP-000273510", key="search_q")

    if not query or len(query) < 2:
        st.caption("Type at least 2 characters to search.")
        return

    q = query.lower().strip()
    matches = [e for e in all_elements
               if q in e["product_code"].lower()
               or q in e["element_name"].lower()
               or q in e.get("composite_code", "").lower()]

    if not matches:
        st.warning(f"No elements found for '{query}'.")
        return

    st.markdown(f"**{len(matches)} elements found**")

    # Build results with logistics info
    # Quick logistics computation for context
    from logistics import process_logistics
    from datetime import date
    first = st.session_state.get("log_first", date(2026, 4, 1))
    last = st.session_state.get("log_last", date(2026, 6, 30))
    log_result = process_logistics(all_elements, first, last)
    assignments = log_result["assignments"]

    result_rows = []
    for e in matches[:200]:  # limit display
        a = assignments.get(id(e), {})
        result_rows.append({
            "PP-Code": e["product_code"],
            "Element": e["element_name"],
            "Material": e["material"],
            "L×W×T": f"{e['length']}×{e['width']}×{e['thickness']}",
            "Volume (m³)": f"{e['volume']:.4f}",
            "Weight (kg)": f"{e['weight']:.1f}",
            "Building": e.get("building", ""),
            "Module": e.get("module", ""),
            "Truck": a.get("truck_id", ""),
            "Package": a.get("package_code", ""),
            "Delivery": str(a.get("delivery_date", "")),
        })

    st.dataframe(pd.DataFrame(result_rows), use_container_width=True,
                 hide_index=True, height=min(600, 35 + 35 * len(result_rows)))

    if len(matches) > 200:
        st.caption(f"Showing first 200 of {len(matches)} matches.")


if __name__ == "__main__":
    main()
