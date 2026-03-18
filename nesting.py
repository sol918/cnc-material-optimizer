"""
Nesting algorithms for CNC plate optimization.
Maximal-Rectangles Best-Area-Fit packing + DP cutoff optimizer.
"""
import math
from collections import defaultdict


# ── Material Configuration ──────────────────────────────────────────────────

MATERIAL_CONFIG = {
    "LVLQ":  {"fixed_width": 1830, "kerf": 16, "margin": 1, "price_m3": 760.0,  "nestable": True,  "variable_length": True},
    "LVLS":  {"fixed_width": 1830, "kerf": 16, "margin": 1, "price_m3": 700.0,  "nestable": True,  "variable_length": True},
    "LVLB":  {"fixed_width": 1830, "kerf": 16, "margin": 1, "price_m3": 700.0,  "nestable": True,  "variable_length": True},
    "SPANO": {"fixed_width": 1250, "kerf": 16, "margin": 1, "price_m3": 270.0,  "nestable": True,  "variable_length": True},
    "FERM":  {"plate_l": 2600, "plate_w": 1250, "kerf": 16, "margin": 1, "price_m3": 650.0,  "nestable": True,  "variable_length": False},
    "GIPF":  {"plate_l": 2600, "plate_w": 1200, "kerf": 3,  "margin": 0, "price_m3": 250.0,  "nestable": True,  "variable_length": False},
    "GIPA":  {"plate_l": 2600, "plate_w": 1200, "kerf": 3,  "margin": 0, "price_m3": 250.0,  "nestable": True,  "variable_length": False},
    "CEM":   {"plate_l": 2500, "plate_w": 1200, "kerf": 3,  "margin": 0, "price_m3": 1990.0, "nestable": True,  "variable_length": False},
    "PRO":   {"kerf": 3, "margin": 0, "price_m3": 1250.0, "nestable": False, "variable_length": False},
    "BAUB":  {"kerf": 3, "margin": 0, "price_m3": 1400.0, "nestable": False, "variable_length": False},
}

def get_config(mat):
    return MATERIAL_CONFIG.get(mat, MATERIAL_CONFIG["PRO"])


def make_element(row):
    mat = str(row.get("materialId", "")).strip()
    if mat not in MATERIAL_CONFIG:
        return None
    try:
        def _s(v):
            s = str(v) if v is not None else ""
            return "" if s == "nan" else s
        return {
            "product_code": _s(row.get("productCode", "")),
            "composite_code": _s(row.get("compositeCode", "")),
            "composite_name": _s(row.get("compositeName", "")),
            "element_name": _s(row.get("elementName", "")),
            "material": mat,
            "length": int(float(str(row.get("length", 0)))),
            "width": int(float(str(row.get("width", 0)))),
            "thickness": int(float(str(row.get("thickness", 0)))),
            "volume": float(str(row.get("volume", "0")).replace(",", ".")),
            "weight": float(str(row.get("weight", "0")).replace(",", ".")),
            "building": _s(row.get("buildingNumber", "")),
            "module": _s(row.get("moduleNumber", "")),
            "work_station": _s(row.get("workStation", "")),
            "building_step": _s(row.get("buildingStep", "")),
            "sub_assembly": _s(row.get("subAssembly", "")),
            "client": _s(row.get("client", "")),
        }
    except (ValueError, TypeError):
        return None


# ── Filtering ──────────────────────────────────────────────────────────────

def filter_out_of_bounds(elements):
    valid, oob = [], []
    for e in elements:
        cfg = get_config(e["material"])
        is_oob = False
        if cfg["nestable"] and not cfg["variable_length"]:
            pl, pw = cfg["plate_l"], cfg["plate_w"]
            if not ((e["length"] <= pl and e["width"] <= pw) or
                    (e["length"] <= pw and e["width"] <= pl)):
                is_oob = True
        elif cfg["variable_length"]:
            if e["width"] > cfg["fixed_width"] - 2 * cfg["margin"]:
                is_oob = True
        (oob if is_oob else valid).append(e)
    return valid, oob


# ══════════════════════════════════════════════════════════════════════════
#  MAXIMAL RECTANGLES BIN PACKING
# ══════════════════════════════════════════════════════════════════════════

class MaxRectsPacker:
    """
    Maximal Rectangles packing with Best-Area-Fit + Best-Short-Side-Fit.
    Significantly better than guillotine for mixed-size rectangles.
    """

    def __init__(self, width, height, kerf, margin, allow_rotation=True):
        self.W = width
        self.H = height
        self.kerf = kerf
        self.margin = margin
        self.allow_rotation = allow_rotation
        uw = width - 2 * margin
        uh = height - 2 * margin
        self.free_rects = [(margin, margin, uw, uh)]  # (x, y, w, h)
        self.placed = []

    def _find_best(self, ew, eh):
        """Find best free rect using Best-Area-Fit with Short-Side tiebreak."""
        best_idx = -1
        best_area_waste = float("inf")
        best_short = float("inf")
        best_orient = None

        orientations = [(ew, eh, False)]
        if self.allow_rotation and ew != eh:
            orientations.append((eh, ew, True))

        for i, (fx, fy, fw, fh) in enumerate(self.free_rects):
            for pw, ph, rot in orientations:
                if pw <= fw and ph <= fh:
                    area_waste = fw * fh - pw * ph
                    short_side = min(fw - pw, fh - ph)
                    if (area_waste < best_area_waste or
                        (area_waste == best_area_waste and short_side < best_short)):
                        best_area_waste = area_waste
                        best_short = short_side
                        best_idx = i
                        best_orient = (pw, ph, rot)

        return best_idx, best_orient

    def place(self, elem):
        """Try to place an element. Returns True if placed."""
        ew, eh = elem["length"], elem["width"]
        best_idx, best_orient = self._find_best(ew, eh)

        if best_idx < 0:
            return False

        pw, ph, rotated = best_orient
        fx, fy, fw, fh = self.free_rects[best_idx]

        self.placed.append({
            **elem,
            "px": fx, "py": fy, "pw": pw, "ph": ph, "rotated": rotated,
        })

        # Generate new free rects from the placement
        k = self.kerf
        new_rects = []

        # Right of placed element
        rw = fw - pw - k
        if rw > 0:
            new_rects.append((fx + pw + k, fy, rw, fh))

        # Above placed element
        ah = fh - ph - k
        if ah > 0:
            new_rects.append((fx, fy + ph + k, fw, ah))

        # Remove the used rect
        self.free_rects.pop(best_idx)

        # Add new rects
        self.free_rects.extend(new_rects)

        # Split ALL existing free rects that overlap with the placed element
        placed_rect = (fx, fy, pw, ph)
        self._split_overlapping(placed_rect)

        # Remove contained rects
        self._prune_contained()

        return True

    def _split_overlapping(self, placed):
        """Split free rects that overlap with the placed rectangle."""
        px, py, pw, ph = placed
        k = self.kerf
        pr = px + pw  # right edge of placed
        pt = py + ph  # top edge of placed

        new_free = []
        to_remove = []

        for i, (fx, fy, fw, fh) in enumerate(self.free_rects):
            fr = fx + fw
            ft = fy + fh

            # Check overlap
            if fx >= pr + k or fr <= px - k or fy >= pt + k or ft <= py - k:
                continue  # No overlap

            to_remove.append(i)

            # Left portion
            if fx < px - k:
                new_free.append((fx, fy, px - k - fx, fh))
            # Right portion
            if fr > pr + k:
                new_free.append((pr + k, fy, fr - pr - k, fh))
            # Bottom portion
            if fy < py - k:
                new_free.append((fx, fy, fw, py - k - fy))
            # Top portion
            if ft > pt + k:
                new_free.append((fx, pt + k, fw, ft - pt - k))

        for i in sorted(to_remove, reverse=True):
            self.free_rects.pop(i)
        self.free_rects.extend(new_free)

    def _prune_contained(self):
        """Remove free rects that are fully contained in another."""
        if len(self.free_rects) <= 1:
            return

        # Remove zero/negative size rects
        self.free_rects = [(x, y, w, h) for x, y, w, h in self.free_rects if w > 0 and h > 0]

        pruned = []
        n = len(self.free_rects)
        contained = [False] * n

        for i in range(n):
            if contained[i]:
                continue
            ix, iy, iw, ih = self.free_rects[i]
            ir, it = ix + iw, iy + ih
            for j in range(n):
                if i == j or contained[j]:
                    continue
                jx, jy, jw, jh = self.free_rects[j]
                jr, jt = jx + jw, jy + jh
                # Is j contained in i?
                if jx >= ix and jy >= iy and jr <= ir and jt <= it:
                    contained[j] = True

        self.free_rects = [r for i, r in enumerate(self.free_rects) if not contained[i]]


_NO_ROTATE_MATS = {"LVLQ", "LVLS", "LVLB"}

def maxrects_pack(elements, plate_w, plate_h, kerf, margin, sort_key=None, allow_rotation=True):
    """Pack elements into a single plate using MaxRects. Returns (placed, remaining)."""
    if sort_key is None:
        sort_key = lambda e: (-(e["length"] * e["width"]), -max(e["length"], e["width"]))

    packer = MaxRectsPacker(plate_w, plate_h, kerf, margin, allow_rotation)
    sorted_elems = sorted(elements, key=sort_key)
    remaining = []
    for elem in sorted_elems:
        if not packer.place(elem):
            remaining.append(elem)
    return packer.placed, remaining


# Sort strategies for multi-pass packing
_SORT_KEYS = [
    lambda e: (-(e["length"] * e["width"]), -max(e["length"], e["width"])),  # area desc
    lambda e: (-max(e["length"], e["width"]), -(e["length"] * e["width"])),  # max dim desc
    lambda e: (-min(e["length"], e["width"]), -(e["length"] * e["width"])),  # min dim desc
    lambda e: (-(e["length"] + e["width"]), -(e["length"] * e["width"])),    # perimeter desc
    lambda e: (-e["width"], -e["length"]),                                    # width desc
    lambda e: (-e["length"], -e["width"]),                                    # length desc
    lambda e: (min(e["length"], e["width"]), -max(e["length"], e["width"])), # min dim ASC (strips of thin elements)
    lambda e: (-max(e["length"], e["width"]), min(e["length"], e["width"])), # tallest first, thinnest second
]


def _pack_plate_multipass(elements, plate_w, plate_h, kerf, margin, allow_rotation=True):
    """Try multiple sort orders for a single plate, return best packing."""
    best_placed = None
    best_remaining = None
    best_fill = -1

    # For large element sets, limit to top 3 sort keys for speed
    keys = _SORT_KEYS if len(elements) < 2000 else _SORT_KEYS[:3]

    for sk in keys:
        placed, remaining = maxrects_pack(elements, plate_w, plate_h, kerf, margin, sk, allow_rotation)
        if not placed:
            continue
        fill = sum(p["pw"] * p["ph"] for p in placed)
        if fill > best_fill:
            best_fill = fill
            best_placed = placed
            best_remaining = remaining

    if best_placed is None:
        return [], elements
    return best_placed, best_remaining


def nest_into_plates(elements, plate_w, plate_h, thickness, mat, kerf, margin):
    """Pack elements into multiple plates using multi-pass MaxRects."""
    allow_rot = mat not in _NO_ROTATE_MATS
    remaining = list(elements)
    plates = []
    for _ in range(len(remaining) + 10):
        if not remaining:
            break
        placed, remaining = _pack_plate_multipass(remaining, plate_w, plate_h, kerf, margin, allow_rot)
        if not placed:
            break
        plates.append({
            "plate_length": plate_w, "plate_width": plate_h,
            "thickness": thickness, "material": mat,
            "placements": placed,
            "plate_vol_m3": plate_w * plate_h * thickness / 1e9,
            "box_vol_m3": sum(p["pw"] * p["ph"] * thickness / 1e9 for p in placed),
            "actual_vol_m3": sum(p["volume"] for p in placed),
        })
    return plates


def plate_layout_key(plate):
    parts = tuple(sorted(
        ((round(p["px"]), round(p["py"]), round(p["pw"]), round(p["ph"])) for p in plate["placements"]),
        key=lambda x: (x[0], x[1])
    ))
    return (plate["plate_length"], plate["plate_width"], parts)


# ── Fixed Plate Nesting ───────────────────────────────────────────────────

def nest_fixed(elements, mat):
    cfg = get_config(mat)
    by_t = defaultdict(list)
    for e in elements:
        by_t[e["thickness"]].append(e)
    result = {}
    for t, elems in by_t.items():
        result[t] = nest_into_plates(elems, cfg["plate_l"], cfg["plate_w"],
                                     t, mat, cfg["kerf"], cfg["margin"])
    return result


# ══════════════════════════════════════════════════════════════════════════
#  OPTIMAL CUTOFF SELECTION
# ══════════════════════════════════════════════════════════════════════════

def _nest_with_cutoffs(elements, cutoffs, plate_width, thickness, mat, kerf, margin):
    """Assign elements to cutoffs and nest. Returns plates list."""
    groups = {c: [] for c in cutoffs}
    sc = sorted(cutoffs)
    for elem in elements:
        needed = elem["length"] + 2 * margin
        for c in sc:
            if c >= needed:
                groups[c].append(elem)
                break
        else:
            groups[max(cutoffs)].append(elem)

    all_plates = []
    for pl in sc:
        if groups[pl]:
            all_plates.extend(
                nest_into_plates(groups[pl], pl, plate_width, thickness, mat, kerf, margin)
            )
    return all_plates


def _fast_plate_area(elements, cutoffs, plate_width, kerf, margin, allow_rotation=True):
    """Fast strip-based plate area estimate for cutoff search."""
    groups = {c: [] for c in cutoffs}
    sc = sorted(cutoffs)
    for elem in elements:
        needed = elem["length"] + 2 * margin
        for c in sc:
            if c >= needed:
                groups[c].append(elem)
                break
        else:
            groups[max(cutoffs)].append(elem)

    total = 0
    for pl in sc:
        if not groups[pl]:
            continue
        # Strip packing estimate
        usable_w = plate_width - 2 * margin
        sorted_e = sorted(groups[pl], key=lambda e: -(e["length"] * e["width"]))
        n_plates = 1
        strip_y = 0
        strip_h = 0
        strip_x = margin
        for elem in sorted_e:
            ew, eh = elem["length"], elem["width"]
            # Best orientation: smaller dim as strip height
            opts = []
            if ew <= pl - 2*margin and eh <= usable_w:
                opts.append((ew, eh))
            if allow_rotation and eh <= pl - 2*margin and ew <= usable_w:
                opts.append((eh, ew))
            if not opts:
                continue
            pw, ph = min(opts, key=lambda o: o[1])
            if strip_x + pw + margin <= pl and strip_y + max(strip_h, ph) + margin <= plate_width:
                strip_x += pw + kerf
                strip_h = max(strip_h, ph)
            elif strip_y + strip_h + kerf + ph + margin <= plate_width:
                strip_y += strip_h + kerf
                strip_x = margin + pw + kerf
                strip_h = ph
            else:
                n_plates += 1
                strip_y = 0
                strip_x = margin + pw + kerf
                strip_h = ph
        total += n_plates * pl * plate_width
    return total


def optimize_variable(elements, mat, thickness, num_sizes=1):
    """Find optimal plate lengths using greedy cutoff search with actual packing."""
    cfg = get_config(mat)
    plate_width = cfg["fixed_width"]
    kerf, margin = cfg["kerf"], cfg["margin"]
    allow_rot = mat not in _NO_ROTATE_MATS

    if not elements:
        return {"cutoffs": [], "plates": []}

    sorted_elems = sorted(elements, key=lambda e: -e["length"])
    max_len = sorted_elems[0]["length"] + 2 * margin

    if num_sizes == 1:
        cutoffs = [max_len]
    else:
        cutoffs = _greedy_find_cutoffs(sorted_elems, num_sizes, plate_width, kerf, margin, allow_rot)

    plates = _nest_with_cutoffs(sorted_elems, cutoffs, plate_width, thickness, mat, kerf, margin)
    return {"cutoffs": sorted(cutoffs), "plates": plates}


def _greedy_find_cutoffs(elements, num_sizes, plate_width, kerf, margin, allow_rotation=True):
    """
    Greedy cutoff search: start with 1 size, add the split that reduces
    plate area the most.
    """
    lengths = sorted(set(e["length"] for e in elements), reverse=True)
    if len(lengths) <= num_sizes:
        return [l + 2 * margin for l in lengths]

    max_len = lengths[0] + 2 * margin

    all_candidates = sorted(set(l + 2 * margin for l in lengths), reverse=True)

    if len(all_candidates) > 40:
        step = max(1, len(all_candidates) // 30)
        sampled = set(all_candidates[:5])
        sampled.update(all_candidates[-5:])
        for i in range(0, len(all_candidates), step):
            sampled.add(all_candidates[i])
        candidates = sorted(sampled, reverse=True)
    else:
        candidates = all_candidates

    current_cutoffs = [max_len]
    current_area = _fast_plate_area(elements, current_cutoffs, plate_width, kerf, margin, allow_rotation)

    for _ in range(num_sizes - 1):
        best_cand = None
        best_area = current_area

        for cand in candidates:
            if cand in current_cutoffs:
                continue
            trial = current_cutoffs + [cand]
            area = _fast_plate_area(elements, trial, plate_width, kerf, margin, allow_rotation)
            if area < best_area:
                best_area = area
                best_cand = cand

        if best_cand is not None and best_area < current_area:
            current_cutoffs.append(best_cand)
            current_area = best_area
        else:
            break

    return sorted(current_cutoffs)


def auto_optimize(elements, mat, thickness, max_sizes=10, threshold=1000.0):
    """
    Incrementally add plate sizes until marginal savings < threshold.
    Guarantees monotonically decreasing waste by keeping best-so-far.
    """
    cfg = get_config(mat)
    price = cfg["price_m3"]
    plate_width = cfg["fixed_width"]
    kerf, margin = cfg["kerf"], cfg["margin"]
    results = []
    prev_wc = None
    best_plates = None
    best_cutoffs = None
    best_pv = float("inf")

    for n in range(1, max_sizes + 1):
        r = optimize_variable(elements, mat, thickness, n)
        plates = r["plates"]
        pv = sum(p["plate_vol_m3"] for p in plates)
        bv = sum(p["box_vol_m3"] for p in plates)
        av = sum(p["actual_vol_m3"] for p in plates)

        # Monotonicity guarantee: if this result is worse, keep previous best
        if pv > best_pv and best_plates is not None:
            plates = best_plates
            cutoffs_used = best_cutoffs
            pv = sum(p["plate_vol_m3"] for p in plates)
            bv = sum(p["box_vol_m3"] for p in plates)
            av = sum(p["actual_vol_m3"] for p in plates)
        else:
            best_pv = pv
            best_plates = plates
            best_cutoffs = r["cutoffs"]
            cutoffs_used = r["cutoffs"]

        gl = ((pv - bv) / pv * 100) if pv > 0 else 0
        nl = ((pv - av) / pv * 100) if pv > 0 else 0
        wc = (pv - av) * price
        savings = (prev_wc - wc) if prev_wc is not None else wc
        if savings < 0:
            savings = 0  # monotonicity
        prev_wc = wc

        results.append({
            "num_sizes": n, "cutoffs": cutoffs_used, "plates": plates,
            "plate_vol": pv, "box_vol": bv, "actual_vol": av,
            "gross_loss": gl, "nett_loss": nl,
            "waste_cost": wc, "savings": savings, "num_plates": len(plates),
        })
        if n > 1 and savings < threshold:
            break

    return results
