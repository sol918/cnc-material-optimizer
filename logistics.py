"""
Logistics & Packaging module.
Packs modules into trucks, assigns delivery dates, generates package codes.
"""
from collections import defaultdict
from datetime import date, timedelta


def compute_module_weights(elements):
    """Calculate total weight per moduleNumber."""
    mod_weights = defaultdict(float)
    for e in elements:
        mod_weights[e["module"]] += e["weight"]
    return dict(mod_weights)


def pack_trucks(elements, max_weight=24000):
    """
    Pack whole modules into trucks sequentially.
    Modules are loaded in order (1, 2, 3, ...) until the truck is full,
    then a new truck is started.
    Returns list of trucks, each is {"modules": [moduleNumber, ...], "weight": float}.
    """
    mod_weights = compute_module_weights(elements)

    # Sort modules numerically (sequential order)
    def _mod_sort_key(mod_id):
        try:
            return int(mod_id)
        except (ValueError, TypeError):
            return float("inf")

    sorted_mods = sorted(mod_weights.items(), key=lambda x: _mod_sort_key(x[0]))

    trucks = [{"modules": [], "weight": 0.0}]

    for mod_id, mod_w in sorted_mods:
        current = trucks[-1]
        if current["weight"] + mod_w <= max_weight or not current["modules"]:
            # Add to current truck (always add at least one module per truck)
            current["modules"].append(mod_id)
            current["weight"] += mod_w
        else:
            # Start new truck
            trucks.append({"modules": [mod_id], "weight": mod_w})

    for i, truck in enumerate(trucks):
        truck["truck_id"] = i + 1

    return trucks


def _next_weekday(d):
    """Move date to next Monday if it falls on a weekend."""
    while d.weekday() >= 5:  # 5=Saturday, 6=Sunday
        d += timedelta(days=1)
    return d


def assign_delivery_dates(trucks, first_date, last_date):
    """Evenly distribute delivery dates across trucks, skipping weekends."""
    n = len(trucks)
    first_date = _next_weekday(first_date)
    last_date = _next_weekday(last_date)

    if n <= 1:
        for t in trucks:
            t["delivery_date"] = first_date
        return

    # Build list of available weekdays in the range
    weekdays = []
    d = first_date
    while d <= last_date:
        if d.weekday() < 5:
            weekdays.append(d)
        d += timedelta(days=1)

    if not weekdays:
        weekdays = [first_date]

    # Distribute trucks evenly across available weekdays
    for i, truck in enumerate(trucks):
        idx = round(i * (len(weekdays) - 1) / max(n - 1, 1))
        truck["delivery_date"] = weekdays[min(idx, len(weekdays) - 1)]


def generate_packages(trucks, elements):
    """
    Within each truck, group elements by buildingStep to form packages.
    Assigns sequential packageCodes (PC-0000001, PC-0000002, ...).
    Returns:
        - packages: list of package dicts
        - element_assignments: dict mapping (productCode, moduleNumber, buildingStep) -> {deliveryDate, packageCode}
    """
    # Build module -> truck lookup
    mod_to_truck = {}
    for truck in trucks:
        for mod in truck["modules"]:
            mod_to_truck[mod] = truck

    # Group elements by truck, then by buildingStep
    truck_step_groups = defaultdict(lambda: defaultdict(list))
    for e in elements:
        truck = mod_to_truck.get(e["module"])
        if truck:
            truck_step_groups[truck["truck_id"]][e["building_step"]].append(e)

    packages = []
    element_assignments = {}
    pkg_counter = 0

    for truck in trucks:
        tid = truck["truck_id"]
        step_groups = truck_step_groups.get(tid, {})

        for step, step_elems in sorted(step_groups.items()):
            pkg_counter += 1
            pkg_code = f"PC-{pkg_counter:07d}"

            pkg = {
                "package_code": pkg_code,
                "truck_id": tid,
                "delivery_date": truck["delivery_date"],
                "building_step": step,
                "elements": step_elems,
                "element_count": len(step_elems),
                "weight": sum(e["weight"] for e in step_elems),
            }
            packages.append(pkg)

            # Map each element to its assignment
            for e in step_elems:
                key = id(e)  # Use object id since elements may have duplicate fields
                element_assignments[key] = {
                    "delivery_date": truck["delivery_date"],
                    "package_code": pkg_code,
                    "truck_id": tid,
                }

    return packages, element_assignments


def process_logistics(elements, first_date, last_date):
    """Full pipeline: pack trucks, assign dates, generate packages."""
    trucks = pack_trucks(elements)
    assign_delivery_dates(trucks, first_date, last_date)
    packages, assignments = generate_packages(trucks, elements)

    return {
        "trucks": trucks,
        "packages": packages,
        "assignments": assignments,
        "total_trucks": len(trucks),
        "total_packages": len(packages),
        "total_weight": sum(t["weight"] for t in trucks),
    }
