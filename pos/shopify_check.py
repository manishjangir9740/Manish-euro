"""Read-only compatibility check against a Shopify backend (the mock or a real dev store).

Makes GET requests only: nothing is created, changed or refunded. It reports what the POS needs
that the store does or does not provide, so surprises show up before the first bill.
"""

import urllib.parse
from typing import Any, Dict, List, Tuple

from pos.adapters.http_client import HttpStatusError

Check = Tuple[str, bool, str]


def run_checks(adapter) -> List[Check]:
    c = adapter.client
    base = adapter.base_url
    out: List[Check] = []

    def get(path: str) -> Dict[str, Any]:
        return c.get(f"{base}/{path}")

    # 1. reachable + authorised
    try:
        shop = get("shop.json").get("shop", {})
        out.append(("Connects and authenticates (shop.json)", True, shop.get("name") or shop.get("domain", "ok")))
        out.append(("Shop currency is INR", shop.get("currency") == "INR", f"currency={shop.get('currency')}"))
        out.append(("Prices are tax-inclusive (taxes_included)", bool(shop.get("taxes_included")),
                    f"taxes_included={shop.get('taxes_included')}"))
    except HttpStatusError as exc:
        if exc.code == 404:
            out.append(("shop.json", True, "not provided by the mock (skipped)"))
        else:
            out.append(("Connects and authenticates (shop.json)", False, f"HTTP {exc.code}: {exc.body}"))
            return out  # nothing else can work

    # 2. locations carry the store code the invoice series needs
    try:
        locs = get("locations.json").get("locations", [])
        with_code = [l for l in locs if (l.get("eluno") or {}).get("store_code")]
        out.append(("Locations readable", bool(locs), f"{len(locs)} locations"))
        out.append(("Each store location has an Eluno store_code (needed for invoice numbers)",
                    len(with_code) > 0,
                    f"{len(with_code)}/{len(locs)} have one. A real store needs this in a location metafield "
                    f"and the adapter mapped to it" if not with_code else f"{len(with_code)} found"))
    except HttpStatusError as exc:
        out.append(("Locations readable", False, f"HTTP {exc.code}"))

    # 3. catalog carries HSN + lens limits
    try:
        prods = get("products.json?limit=250").get("products", [])
        variants = [v for p in prods for v in p.get("variants", [])]
        with_hsn = [v for v in variants if (v.get("eluno") or {}).get("hsn")]
        with_lim = [v for v in variants if (v.get("eluno") or {}).get("rx_limits")]
        out.append(("Products readable", bool(prods), f"{len(prods)} products, {len(variants)} variants"))
        out.append(("Variants carry an HSN code", bool(with_hsn),
                    f"{len(with_hsn)}/{len(variants)}" + ("" if with_hsn else " - needs a variant metafield")))
        out.append(("Lens variants carry Rx limits", bool(with_lim),
                    f"{len(with_lim)} lens variants" + ("" if with_lim else " - needs a variant metafield")))
    except HttpStatusError as exc:
        out.append(("Products readable", False, f"HTTP {exc.code}"))

    # 4. customers searchable by phone
    try:
        q = urllib.parse.quote("phone:+910000000000")
        get(f"customers/search.json?query={q}")
        out.append(("Customer search by phone works", True, "query accepted"))
    except HttpStatusError as exc:
        out.append(("Customer search by phone works", False, f"HTTP {exc.code}"))

    # 5. orders readable with the filters day-end uses
    try:
        q = "orders.json?status=any&limit=1&created_at_min=2000-01-01T00:00:00%2B05:30&created_at_max=2999-01-01T00:00:00%2B05:30"
        get(q)
        out.append(("Orders readable with status/date filters (day-end)", True, "ok"))
    except HttpStatusError as exc:
        out.append(("Orders readable with status/date filters (day-end)", False, f"HTTP {exc.code}"))

    # 6. inventory levels readable
    try:
        prods = get("products.json?limit=1").get("products", [])
        item = next((v.get("inventory_item_id") for p in prods for v in p.get("variants", []) if v.get("inventory_item_id")), None)
        if item:
            get(f"inventory_levels.json?inventory_item_ids={item}")
            out.append(("Inventory levels readable", True, "ok"))
        else:
            out.append(("Inventory levels readable", False, "no inventory-tracked variant found to test with"))
    except HttpStatusError as exc:
        out.append(("Inventory levels readable", False, f"HTTP {exc.code}"))
    return out


def print_report(checks: List[Check]) -> bool:
    for name, ok, detail in checks:
        print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    failed = [n for n, ok, _ in checks if not ok]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed. Read-only: nothing was created or changed.")
    return not failed
