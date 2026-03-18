"""
PDF Report Generator for CNC Material Optimizer.
Generates a comprehensive report with metrics, charts, tables, and logistics.
"""
import io
import tempfile
import os
from datetime import date, datetime
from collections import defaultdict

from fpdf import FPDF
import plotly.graph_objects as go
import plotly.express as px


class Report(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=15)

    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, "CNC Material Optimizer Report", align="R", new_x="LMARGIN", new_y="NEXT")
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def section_title(self, title):
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(40, 40, 40)
        self.cell(0, 10, self._safe(title), new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def sub_title(self, title):
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(60, 60, 60)
        self.cell(0, 8, self._safe(title), new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def body_text(self, text):
        self.set_font("Helvetica", "", 9)
        self.set_text_color(50, 50, 50)
        self.multi_cell(0, 5, self._safe(text))
        self.ln(1)

    def metric_row(self, metrics):
        """Render a row of key metrics: [(label, value), ...]"""
        col_w = 190 / len(metrics)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(100, 100, 100)
        for label, _ in metrics:
            self.cell(col_w, 4, self._safe(label), align="C")
        self.ln()
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(30, 30, 30)
        for _, value in metrics:
            self.cell(col_w, 7, self._safe(value), align="C")
        self.ln(10)

    @staticmethod
    def _safe(text):
        """Replace chars not in latin-1."""
        s = str(text)
        for old, new in [("\u20ac", "EUR"), ("\u00d7", "x"), ("\u2192", "->"),
                         ("\u2014", " - "), ("\u2013", "-"), ("\u2019", "'"),
                         ("\u201c", '"'), ("\u201d", '"')]:
            s = s.replace(old, new)
        # Strip any remaining non-latin-1
        return s.encode("latin-1", "replace").decode("latin-1")

    def add_table(self, headers, rows, col_widths=None):
        """Add a formatted table."""
        if not rows:
            return
        n = len(headers)
        if col_widths is None:
            col_widths = [190 / n] * n

        # Header
        self.set_font("Helvetica", "B", 8)
        self.set_fill_color(45, 45, 60)
        self.set_text_color(255, 255, 255)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 6, self._safe(h), border=1, fill=True, align="C")
        self.ln()

        # Rows
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(40, 40, 40)
        for ri, row in enumerate(rows):
            if self.get_y() > 270:
                self.add_page()
            bg = ri % 2 == 0
            if bg:
                self.set_fill_color(245, 245, 250)
            for i, val in enumerate(row):
                self.cell(col_widths[i], 5, self._safe(val)[:40], border=0, fill=bg,
                         align="R" if i > 0 and any(c in str(val) for c in "0123456789EUR%") else "L")
            self.ln()
        self.ln(3)

    def add_chart(self, fig, width=180, height=100):
        """Add a Plotly chart as image."""
        try:
            img_bytes = fig.to_image(format="png", width=int(width * 4), height=int(height * 4),
                                     scale=2)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(img_bytes)
                tmp_path = tmp.name

            if self.get_y() + height > 270:
                self.add_page()
            self.image(tmp_path, x=15, w=width)
            self.ln(3)
            os.unlink(tmp_path)
        except Exception as e:
            self.body_text(f"[Chart could not be rendered: {e}]")


def generate_report(all_elements, valid, oob, mat_groups, mat_order,
                    thickness_stats_fn, mat_colors, mat_labels, get_config_fn,
                    logistics_result=None):
    """Generate full PDF report. Returns bytes."""

    pdf = Report()
    pdf.alias_nb_pages()
    pdf.add_page()

    # ── Title Page ──
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 15, "CNC Material Optimizer", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
             new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Total elements: {len(all_elements):,}  |  Materials: {len(mat_order)}",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # ── Overview Metrics ──
    total_vol = sum(e["volume"] for e in valid)
    total_cost = 0
    total_waste = 0
    total_plates = 0
    mat_summaries = []

    for mat in mat_order:
        cfg = get_config_fn(mat)
        stats = thickness_stats_fn(mat, mat_groups[mat])
        count = sum(d["count"] for d in stats.values())
        vol = sum(d["volume"] for d in stats.values())
        pvol = sum(d["plate_vol"] for d in stats.values())
        bvol = sum(d["box_vol"] for d in stats.values())
        cost = sum(d["material_cost"] for d in stats.values())
        waste = sum(d["waste_cost"] for d in stats.values())
        nplates = sum(d["num_plates"] for d in stats.values())
        gl = ((pvol - bvol) / pvol * 100) if pvol > 0 else 0
        nl = ((pvol - sum(d["actual_vol"] for d in stats.values())) / pvol * 100) if pvol > 0 else 0
        total_cost += cost
        total_waste += waste
        total_plates += nplates
        mat_summaries.append({
            "mat": mat, "count": count, "vol": vol, "cost": cost,
            "waste": waste, "plates": nplates, "gross_loss": gl, "nett_loss": nl,
        })

    mat_summaries.sort(key=lambda r: -r["cost"])

    pdf.section_title("Overview")
    pdf.metric_row([
        ("Total Elements", f"{len(valid):,}"),
        ("Total Volume", f"{total_vol:,.1f} m³"),
        ("Gross Material Cost", f"EUR{total_cost:,.0f}"),
        ("Total Waste Cost", f"EUR{total_waste:,.0f}"),
        ("Total Plates", f"{total_plates:,}"),
    ])

    # ── Cost Distribution Pie ──
    colors = [mat_colors.get(r["mat"], "#888") for r in mat_summaries]
    fig = go.Figure(go.Pie(
        labels=[mat_labels.get(r["mat"], r["mat"]) for r in mat_summaries],
        values=[round(r["cost"]) for r in mat_summaries],
        marker=dict(colors=colors), hole=0.4,
        textinfo="label+percent", textposition="outside", sort=False))
    fig.update_layout(title="Cost Distribution", width=700, height=400,
                      margin=dict(t=50, b=20, l=20, r=20), showlegend=False,
                      paper_bgcolor="white", plot_bgcolor="white",
                      font=dict(color="black"))
    pdf.add_chart(fig, width=170, height=95)

    # ── Material Summary Table ──
    pdf.sub_title("Material Summary")
    headers = ["Material", "Elements", "Vol (m³)", "Plates", "Gross (EUR)", "Waste (EUR)", "Gross %", "Nett %"]
    rows = [[
        mat_labels.get(r["mat"], r["mat"]),
        f"{r['count']:,}", f"{r['vol']:.1f}", str(r["plates"]),
        f"EUR{r['cost']:,.0f}", f"EUR{r['waste']:,.0f}",
        f"{r['gross_loss']:.1f}%", f"{r['nett_loss']:.1f}%",
    ] for r in mat_summaries]
    pdf.add_table(headers, rows, [28, 20, 20, 18, 26, 26, 20, 20])

    # ── Plate Order (BOM) ──
    pdf.add_page()
    pdf.section_title("Bill of Materials — Plate Order")
    bom_rows = []
    for mat in mat_order:
        stats = thickness_stats_fn(mat, mat_groups[mat])
        cfg = get_config_fn(mat)
        for t in sorted(stats):
            d = stats[t]
            if not d["plates"]:
                if not cfg["nestable"]:
                    bom_rows.append([mat_labels.get(mat, mat), str(t), "To size",
                                    str(d["count"]), f"{d['volume']:.2f}",
                                    f"EUR{d['material_cost']:,.0f}"])
                continue
            size_groups = defaultdict(int)
            size_vols = defaultdict(float)
            for p in d["plates"]:
                key = f"{p['plate_length']}×{p['plate_width']}"
                size_groups[key] += 1
                size_vols[key] += p["plate_vol_m3"]
            for sz in sorted(size_groups):
                bom_rows.append([mat_labels.get(mat, mat), str(t), sz,
                                str(size_groups[sz]), f"{size_vols[sz]:.2f}",
                                f"EUR{size_vols[sz] * cfg['price_m3']:,.0f}"])

    pdf.add_table(["Material", "T (mm)", "Plate Size", "Qty", "Vol (m³)", "Cost (EUR)"],
                  bom_rows, [30, 18, 38, 18, 25, 30])

    # ── Per-Material Detail ──
    for mat in mat_order:
        cfg = get_config_fn(mat)
        stats = thickness_stats_fn(mat, mat_groups[mat])
        label = mat_labels.get(mat, mat)

        pdf.add_page()
        pdf.section_title(f"{label}")

        info = f"EUR{cfg['price_m3']:,.0f}/m³"
        if cfg.get("variable_length"):
            info += f"  |  Fixed width: {cfg['fixed_width']}mm"
        elif cfg.get("nestable"):
            info += f"  |  Plate: {cfg['plate_l']}×{cfg['plate_w']}mm"
        else:
            info += "  |  Ordered to size"
        pdf.body_text(info)

        total_vol_mat = sum(d["volume"] for d in stats.values())
        total_cost_mat = sum(d["material_cost"] for d in stats.values())
        total_waste_mat = sum(d["waste_cost"] for d in stats.values())
        total_plates_mat = sum(d["num_plates"] for d in stats.values())

        pdf.metric_row([
            ("Elements", f"{len(mat_groups[mat]):,}"),
            ("Volume", f"{total_vol_mat:.2f} m³"),
            ("Gross Cost", f"EUR{total_cost_mat:,.0f}"),
            ("Waste Cost", f"EUR{total_waste_mat:,.0f}"),
            ("Plates", f"{total_plates_mat:,}"),
        ])

        # Thickness breakdown table
        t_headers = ["Thickness", "Elements", "Vol (m³)", "Plates", "Cost (EUR)", "Waste (EUR)", "Gross %", "Nett %"]
        t_rows = []
        for t in sorted(stats):
            d = stats[t]
            t_rows.append([
                f"{t}mm", str(d["count"]), f"{d['volume']:.2f}",
                str(d["num_plates"]), f"EUR{d['material_cost']:,.0f}",
                f"EUR{d['waste_cost']:,.0f}",
                f"{d['gross_loss']:.1f}%", f"{d['nett_loss']:.1f}%",
            ])
        pdf.add_table(t_headers, t_rows, [22, 20, 22, 18, 26, 26, 20, 22])

        # Length bar chart per thickness
        for t in sorted(stats):
            elems = [e for e in mat_groups[mat] if e["thickness"] == t]
            if len(elems) < 5:
                continue
            se = sorted(elems, key=lambda e: -e["length"])
            cutoffs = list(set(p["plate_length"] for p in stats[t]["plates"])) if stats[t]["plates"] else []

            fig = go.Figure(go.Bar(
                x=list(range(len(se))), y=[e["length"] for e in se],
                marker_color=mat_colors.get(mat, "#4fc3f7"), opacity=0.85,
            ))
            for i, c in enumerate(sorted(cutoffs, reverse=True)):
                palette = ["#ff5252", "#ff9800", "#ffeb3b", "#66bb6a"]
                fig.add_hline(y=c, line_dash="dash", line_color=palette[i % len(palette)],
                              annotation_text=f"Plate {c}mm")
            fig.update_layout(title=f"{mat} T={t}mm — Elements by Length",
                              xaxis_title="Elements (sorted)", yaxis_title="Length (mm)",
                              width=700, height=300,
                              margin=dict(t=40, b=30, l=50, r=20),
                              paper_bgcolor="white", plot_bgcolor="white",
                              font=dict(color="black"))
            pdf.add_chart(fig, width=175, height=75)

    # ── Building Step Breakdown ──
    pdf.add_page()
    pdf.section_title("Building Step Breakdown")

    step_vol = defaultdict(float)
    step_cost = defaultdict(float)
    step_count = defaultdict(int)
    for e in valid:
        step = e.get("building_step", "").strip() or "Unknown"
        cfg = get_config_fn(e["material"])
        step_vol[step] += e["volume"]
        step_cost[step] += e["volume"] * cfg["price_m3"]
        step_count[step] += 1

    # Waste per step
    total_waste_by_mat = {}
    mat_vol_totals = defaultdict(float)
    for mat in mat_order:
        stats = thickness_stats_fn(mat, mat_groups[mat])
        total_waste_by_mat[mat] = sum(d["waste_cost"] for d in stats.values())
    for e in valid:
        mat_vol_totals[e["material"]] += e["volume"]

    step_waste = defaultdict(float)
    for e in valid:
        step = e.get("building_step", "").strip() or "Unknown"
        mat = e["material"]
        mt = mat_vol_totals[mat]
        if mt > 0 and mat in total_waste_by_mat:
            step_waste[step] += total_waste_by_mat[mat] * (e["volume"] / mt)

    sorted_steps = sorted(step_vol.items(), key=lambda x: -x[1])
    s_headers = ["Building Step", "Elements", "Vol (m³)", "Material (EUR)", "Waste (EUR)", "Waste %"]
    s_rows = []
    for step, vol in sorted_steps:
        tc = step_cost[step] + step_waste[step]
        wp = (step_waste[step] / tc * 100) if tc > 0 else 0
        s_rows.append([step[:45], str(step_count[step]), f"{vol:.2f}",
                       f"EUR{step_cost[step]:,.0f}", f"EUR{step_waste[step]:,.0f}", f"{wp:.1f}%"])
    pdf.add_table(s_headers, s_rows, [55, 20, 22, 25, 25, 18])

    # ── Errors & Warnings ──
    if oob:
        pdf.add_page()
        pdf.section_title(f"Out of Bounds — {len(oob)} elements")
        e_headers = ["PP-Code", "Element", "Material", "L", "W", "T"]
        e_rows = [[e["product_code"], e["element_name"][:30], e["material"],
                   str(e["length"]), str(e["width"]), str(e["thickness"])]
                  for e in oob[:100]]
        pdf.add_table(e_headers, e_rows, [32, 52, 22, 22, 22, 18])
        if len(oob) > 100:
            pdf.body_text(f"... and {len(oob) - 100} more")

    # ── Logistics ──
    if logistics_result:
        pdf.add_page()
        pdf.section_title("Logistics & Trucks")
        pdf.metric_row([
            ("Trucks", str(logistics_result["total_trucks"])),
            ("Packages", str(logistics_result["total_packages"])),
            ("Total Weight", f"{logistics_result['total_weight']:,.0f} kg"),
        ])

        t_headers = ["Truck", "Delivery", "Weight (kg)", "Util %", "Modules", "Packages"]
        t_rows = []
        for truck in logistics_result["trucks"]:
            util = truck["weight"] / 24000 * 100
            pkgs = [p for p in logistics_result["packages"] if p["truck_id"] == truck["truck_id"]]
            mods = sorted(truck["modules"], key=lambda x: int(x) if x.isdigit() else 0)
            t_rows.append([
                f"Truck {truck['truck_id']}", str(truck["delivery_date"]),
                f"{truck['weight']:,.0f}", f"{util:.0f}%",
                f"{mods[0]}-{mods[-1]}" if mods else "", str(len(pkgs)),
            ])
        pdf.add_table(t_headers, t_rows, [22, 28, 28, 18, 30, 22])

    # Output
    return pdf.output()
