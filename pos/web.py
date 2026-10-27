"""Web gateway for the till UI.

A thin layer in front of PosService: it serves the static UI in `web/` and exposes the JSON the
screens need (catalog with per-lens Rx validation, price quote with offer breakdown, till, orders,
partial refunds, audit). It holds NO business rules: every decision is made by PosService / the
domain. Existing modules (pos/server.py, services, domain, adapters) are untouched.

Money leaves this file as integer paise; the browser formats it.
Optional HTTP Basic auth: set ELUNO_UI_PASSWORD (any user name) before exposing it beyond localhost.
"""

import base64
import hmac
import json
import mimetypes
import os
import threading
import urllib.parse
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pos.bootstrap import build_service
from pos.config import BASE_DIR, TILL_VARIANCE_ALERT_PAISE
from pos.domain.errors import AmbiguousWriteError
from pos.domain.models import CHANNELS, PAYMENT_METHODS, Cart
from pos.domain.money import Money
from pos.domain.rx_validator import PrescriptionValidator, RxValidationError
from pos.services.pos_service import MANAGER_MAX_BPS, REASON_CODES, REFUND_REASONS

WEB_DIR = BASE_DIR / "web"
_LOCK = threading.RLock()  # PosService and its JSON state files are used by one request at a time
_SERVICE = None


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Optional[List[str]] = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or []


def service():
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = build_service()
    return _SERVICE


# ----------------------------------------------------------------------
# Serialisation helpers (domain -> JSON)
# ----------------------------------------------------------------------
def jsonable(o: Any) -> Any:
    if isinstance(o, Money):
        return o.paise
    if isinstance(o, dict):
        return {k: jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    return o


def _rx_json(rx) -> Optional[Dict[str, Any]]:
    if not rx:
        return None
    eye = lambda e: {"sph": e.sph, "cyl": e.cyl, "axis": e.axis, "add": e.add}
    return {"rx_id": rx.rx_id, "date": rx.date, "valid_until": rx.valid_until, "source": rx.source,
            "optometrist_id": rx.optometrist_id, "od": eye(rx.od), "os": eye(rx.os), "pd": rx.pd, "notes": rx.notes}


def _customer_json(c) -> Dict[str, Any]:
    return {"id": c.id, "name": c.full_name, "phone": c.phone, "tags": c.tags, "is_priority": c.is_priority,
            "flags": c.billing_flags, "total_spent": c.total_spent.paise}


def _variant_json(v) -> Dict[str, Any]:
    out = {"id": v.id, "sku": v.sku, "name": v.display_name, "title": v.title, "product": v.product_title,
           "price": v.price.paise, "line_type": v.line_type, "hsn": v.hsn, "category": v.category}
    if v.line_type == "lens":
        lim = v.rx_limits
        out.update({
            "lens_type": v.lens_type, "index": v.index, "coating": v.coating, "lab_tat_days": v.lab_tat_days,
            "limits": None if not lim else {
                "sph_min": lim.sph_min, "sph_max": lim.sph_max, "cyl_abs_max": lim.cyl_abs_max,
                "add_required": lim.add_required, "add_min": lim.add_min, "add_max": lim.add_max},
        })
    return out


def _session_json(s: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not s:
        return None
    return dict(s, is_open=not s.get("closed_at"))


def _need(body: Dict[str, Any], *keys: str) -> None:
    missing = [k for k in keys if body.get(k) in (None, "")]
    if missing:
        raise ApiError(400, "BadRequest", "Missing: " + ", ".join(missing))


def _today() -> str:
    return date.today().isoformat()


def _location(store: str):
    try:
        return service().shopify.get_location_by_code(store)
    except ValueError as exc:
        raise ApiError(404, "UnknownStore", str(exc))


def _customer_and_rx(phone: str):
    cust, rx = service().lookup_customer_and_rx(phone)
    if not cust:
        raise ApiError(404, "CustomerNotFound", f"No customer with phone {phone}.")
    return cust, rx


def _money(value: Any, field: str) -> Money:
    try:
        m = Money.from_decimal(str(value))
    except Exception:
        raise ApiError(400, "BadRequest", f"{field} must be an amount in rupees, e.g. 3000 or 120.50")
    return m


# ----------------------------------------------------------------------
# Cart building and pricing (delegates to PosService)
# ----------------------------------------------------------------------
def _build_cart(body: Dict[str, Any]) -> Tuple[Cart, Any, Any]:
    _need(body, "phone", "store")
    svc = service()
    cust, rx = _customer_and_rx(body["phone"])
    channel = body.get("channel", "walk_in")
    try:
        cart = svc.create_cart(cust, channel, body.get("staff_id"))
    except ValueError as exc:
        raise ApiError(400, "BadRequest", str(exc))
    pairs = body.get("pairs") or []
    if not pairs:
        raise ApiError(400, "EmptyCart", "Add a frame or a lens first.")
    for i, p in enumerate(pairs, start=1):
        try:
            svc.add_pair_to_cart(cart, p.get("frame_id"), p.get("lens_id"), body["store"],
                                 pair_ref=str(p.get("pair_ref") or i), rx=rx)
        except RxValidationError as exc:
            raise ApiError(422, "RxValidationFailed", str(exc), list(getattr(exc, "errors", []) or []))
        except ValueError as exc:
            raise ApiError(409, "CartRejected", str(exc))
    return cart, cust, rx


def _manual_args(body: Dict[str, Any]) -> Dict[str, Any]:
    m = body.get("manager_discount") or {}
    pct = m.get("percent")
    if pct in (None, "", 0, "0"):
        return {}
    try:
        bps = int(round(float(pct) * 100))
    except (TypeError, ValueError):
        raise ApiError(400, "BadRequest", "Manager discount must be a percentage.")
    return {"manager_discount_bps": bps, "approver_id": m.get("approver_id") or None,
            "reason_code": m.get("reason_code") or None}


def _cart_json(cart: Cart, evaluations: List[Dict[str, Any]]) -> Dict[str, Any]:
    lines = []
    for idx, it in enumerate(cart.items):
        lines.append({
            "index": idx, "pair_ref": it.pair_ref, "variant_id": it.variant.id, "sku": it.variant.sku,
            "name": it.variant.display_name, "line_type": it.variant.line_type, "hsn": it.variant.hsn,
            "mrp": it.line_subtotal.paise, "discount": it.discount.paise, "gross": it.gross_amount.paise,
            "taxable": it.taxable_amount.paise, "tax": it.total_tax.paise,
            "tax_lines": [{"title": t.title, "rate_bps": t.rate_bps, "amount": t.price.paise} for t in it.tax_lines],
            "offers": [{"offer_id": a.offer_id, "name": _offer_name(a.offer_id), "amount": a.amount.paise}
                       for a in it.discount_allocations],
            "rx_id": it.rx.rx_id if it.rx else None, "lens_config": it.lens_config,
            "warnings": list(getattr(it, "warnings", [])),
        })
    return {
        "lines": lines,
        "totals": {"mrp": cart.subtotal_price.paise, "discount": cart.total_discounts.paise,
                   "taxable": cart.total_taxable.paise, "tax": cart.total_tax.paise,
                   "total": cart.total_price.paise},
        "applied_offers": [{"offer_id": e["offer_id"], "name": _offer_name(e["offer_id"]), "amount": e["amount"].paise}
                           for e in evaluations if e["applied"]],
        "offer_evaluations": [dict(e, name=_offer_name(e["offer_id"]), amount=e["amount"].paise) for e in evaluations],
    }


def _offer_name(offer_id: str) -> str:
    for o in service().offers.offers:
        if o.offer_id == offer_id:
            return o.name
    return offer_id


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------
def api_bootstrap(_q, _b):
    svc = service()
    stores = [{"code": l.store_code, "name": l.name, "id": l.id} for l in svc.shopify.get_locations()
              if l.kind == "store"]
    staff = [{"id": s.staff_id, "name": s.name, "role": s.role, "store": s.store_code,
              "can_approve_discount": s.role == "store_manager" and s.can_override_discount}
             for s in svc.smt.get_staff_members()]
    return {
        "today": _today(), "stores": stores, "staff": staff, "channels": list(CHANNELS),
        "payment_methods": list(PAYMENT_METHODS), "discount_reason_codes": list(REASON_CODES),
        "refund_reasons": list(REFUND_REASONS), "manager_max_percent": MANAGER_MAX_BPS / 100,
        "till_variance_alert": TILL_VARIANCE_ALERT_PAISE,
    }


def api_customer(q, _b):
    _need(q, "phone")
    cust, rx = _customer_and_rx(q["phone"])
    return {"customer": _customer_json(cust), "prescription": _rx_json(rx)}


def api_catalog(q, _b):
    """Frames with stock at the store; every lens with a pass/blocked verdict for this customer's Rx."""
    _need(q, "store")
    svc = service()
    loc = _location(q["store"])
    frames = []
    for f in svc.shopify.list_frame_variants():
        j = _variant_json(f)
        j["stock"] = svc.shopify.check_stock(f.inventory_item_id, loc.id) if f.inventory_item_id else None
        frames.append(j)
    lenses = []
    rx = cust = None
    if q.get("phone"):
        cust, rx = _customer_and_rx(q["phone"])
    for l in svc.shopify.list_lens_variants():
        j = _variant_json(l)
        if cust is not None:
            r = PrescriptionValidator.validate_lens_choice(l, rx, _today(), cust.id)
            j["verdict"] = {"valid": r.is_valid, "errors": r.errors, "warnings": r.warnings}
        lenses.append(j)
    frames.sort(key=lambda f: (f["name"] or ""))
    lenses.sort(key=lambda l: (l["lens_type"] or "", l["index"] or 0, l["price"]))
    return {"frames": frames, "lenses": lenses}


def api_quote(_q, body):
    cart, _c, _rx = _build_cart(body)
    svc = service()
    args = _manual_args(body)
    manual = approver = None
    if args:
        try:
            manual, approver = svc._resolve_manual_discount(
                body["store"], args["manager_discount_bps"], args["approver_id"], args["reason_code"])
        except ValueError as exc:
            raise ApiError(422, "ManagerDiscountRejected", str(exc))
    res = svc.prepare_cart_pricing(cart, _today(), manual, approver)
    return _cart_json(cart, res.evaluations)


def _open_session(store: str) -> Optional[Dict[str, Any]]:
    s = service().till.find_session(store, _today())
    return s if s and not s.get("closed_at") else None


def api_checkout(_q, body):
    _need(body, "staff_id", "payment_method")
    store = body["store"] = body.get("store") or ""
    cart, _c, _rx = _build_cart(body)
    method = str(body["payment_method"]).lower()
    session = _open_session(store)
    if method == "cash" and not session:
        raise ApiError(409, "TillClosed", "Open today's cash till (Till tab) before taking a cash payment.")
    try:
        res = service().checkout(
            cart, store, body["staff_id"], method, channel=body.get("channel", "walk_in"),
            till_session_id=session["session_id"] if session else None, **_manual_args(body))
    except RxValidationError as exc:
        raise ApiError(422, "RxValidationFailed", str(exc), list(getattr(exc, "errors", []) or []))
    except ValueError as exc:
        raise ApiError(422, "CheckoutRejected", str(exc))
    except AmbiguousWriteError as exc:
        raise ApiError(502, "ShopifyUnsure", str(exc))
    except Exception as exc:
        raise ApiError(502, "PaymentOrSyncFailed", str(exc))
    out = _cart_json(cart, res["offer_evaluations"])
    out.update({
        "invoice_no": res["invoice_no"], "status": res["status"], "order_id": res["order_id"],
        "order_number": res["order_number"], "charge_id": res["charge_id"], "invoice_text": res["invoice_text"],
        "warnings": res["warnings"], "payment_method": method,
    })
    return out


def _serialise_order(o, names: Dict[str, str]) -> Dict[str, Any]:
    refunded = set(o.refunded_line_ids)
    return {
        "order_id": o.order_id, "name": o.name, "invoice_no": o.invoice_no, "created_at": o.created_at,
        "channel": o.channel, "staff_id": o.staff_id, "payment_method": o.payment_method,
        "subtotal": o.subtotal.paise, "discounts": o.discounts.paise, "tax": o.tax.paise, "total": o.total.paise,
        "refunded": o.refunded.paise, "cancelled": o.cancelled,
        "refunds": [{"credit_note_no": r.credit_note_no, "amount": r.amount.paise, "created_at": r.created_at}
                    for r in o.refunds],
        "lines": [{"line_id": l.line_id, "sku": l.sku, "name": names.get(l.sku, l.sku), "line_type": l.line_type,
                   "gross": l.gross.paise, "tax": l.tax.paise, "taxable": l.taxable.paise,
                   "refunded": l.line_id in refunded, "rx_id": l.rx_id} for l in o.lines],
    }


def api_orders(q, _b):
    _need(q, "store")
    svc = service()
    loc = _location(q["store"])
    day = q.get("date") or _today()
    orders = svc.shopify.orders_for_location(loc.id, f"{day}T00:00:00+05:30", f"{day}T23:59:59+05:30")
    names = {v.sku: v.display_name for v in svc.shopify.list_frame_variants() + svc.shopify.list_lens_variants()}
    rows = [_serialise_order(o, names) for o in orders if o.invoice_no]
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return {"orders": rows}


def api_refund(_q, body):
    _need(body, "order_id", "staff_id", "reason")
    svc = service()
    order_id = int(body["order_id"])
    try:
        order = svc.shopify.get_order(order_id)
        session = _open_session(order.store_code) if order.store_code else None
        res = svc.process_refund(
            order_id, body["staff_id"], body["reason"],
            line_item_ids_to_refund=[int(x) for x in body.get("line_ids") or []] or None,
            till_session_id=session["session_id"] if session else None)
    except ValueError as exc:
        raise ApiError(422, "RefundRejected", str(exc))
    except Exception as exc:
        raise ApiError(502, "RefundFailed", str(exc))
    plan = res["plan"]
    return {
        "credit_note_no": res["credit_note_no"], "original_invoice_no": res["original_invoice_no"],
        "refund_amount": res["refund_amount"].paise, "taxable_reversed": res["taxable_reversed"].paise,
        "tax_reversed": res["tax_reversed"].paise, "is_full": res["is_full"],
        "lines": [{"line_id": l.line_id, "restock": l.restock} for l in plan.lines],
        "till_recorded": bool(session) and order.payment_method == "cash",
    }


def api_day_end(q, _b):
    _need(q, "store")
    _location(q["store"])
    try:
        rep = service().generate_day_end_report(q["store"], q.get("date") or _today())
    except ValueError as exc:
        raise ApiError(404, "ReportRejected", str(exc))
    return jsonable(rep)


def api_till(q, _b):
    _need(q, "store")
    return {"session": _session_json(service().till.find_session(q["store"], q.get("date") or _today()))}


def api_till_open(_q, b):
    _need(b, "store", "staff_id", "float")
    loc = _location(b["store"])
    try:
        s = service().till.open_session(b["store"], loc.id, b["staff_id"], _money(b["float"], "float"),
                                        f"TILL-{b['store']}-{_today()}")
    except ValueError as exc:
        raise ApiError(409, "TillRejected", str(exc))
    service().audit.log(who=b["staff_id"], what="TILL_OPENED", ref=s["session_id"],
                        details={"float_paise": s["opening_float_paise"]})
    return {"session": _session_json(s)}


def api_till_move(_q, b):
    _need(b, "session_id", "type", "amount", "staff_id")
    if b["type"] not in ("paid_in", "paid_out"):
        raise ApiError(400, "BadRequest", "Only paid_in and paid_out can be entered by hand.")
    amount = _money(b["amount"], "amount")
    if amount.paise <= 0:
        raise ApiError(400, "BadRequest", "Amount must be more than zero.")
    svc = service()
    try:
        svc.till.record_cash_movement(b["session_id"], b["type"], amount, f"{b['type'].upper()}-{_today()}",
                                      reason=(b.get("reason") or "").strip() or None, staff_id=b["staff_id"])
    except ValueError as exc:
        raise ApiError(422, "TillRejected", str(exc))
    svc.audit.log(who=b["staff_id"], what=b["type"].upper(), ref=b["session_id"], reason_code=b.get("reason"),
                  details={"amount_paise": amount.paise})
    return {"session": _session_json(svc.till.get_session(b["session_id"]))}


def api_till_close(_q, b):
    _need(b, "session_id", "staff_id", "counted")
    svc = service()
    try:
        s = svc.till.close_session(b["session_id"], b["staff_id"], _money(b["counted"], "counted"),
                                   (b.get("note") or "").strip() or None)
    except ValueError as exc:
        raise ApiError(422, "TillRejected", str(exc))
    svc.audit.log(who=b["staff_id"], what="TILL_CLOSED", ref=b["session_id"],
                  details={"variance_paise": s["variance_paise"], "alert": s["variance_alert"]})
    return {"session": _session_json(s)}


def api_audit(q, _b):
    svc = service()
    svc.audit._ensure_loaded()
    events = list(reversed(svc.audit.events))[: int(q.get("limit", 200))]
    return {"events": events}


def api_pending(_q, _b):
    return {"pending": [{"invoice_no": e["invoice_no"], "amount": e.get("amount_paise"),
                         "store": e.get("store_code")} for e in service().outbox.pending()]}


def api_sync_pending(_q, _b):
    return {"results": service().sync_pending()}


GET_ROUTES = {
    "/api/bootstrap": api_bootstrap, "/api/customer": api_customer, "/api/catalog": api_catalog,
    "/api/orders": api_orders, "/api/day-end": api_day_end, "/api/till": api_till, "/api/audit": api_audit,
    "/api/pending": api_pending,
}
POST_ROUTES = {
    "/api/quote": api_quote, "/api/checkout": api_checkout, "/api/refund": api_refund,
    "/api/till/open": api_till_open, "/api/till/move": api_till_move, "/api/till/close": api_till_close,
    "/api/sync-pending": api_sync_pending,
}


# ----------------------------------------------------------------------
# HTTP plumbing
# ----------------------------------------------------------------------
class WebHandler(BaseHTTPRequestHandler):
    server_version = "ElunoTill/1.0"

    def log_message(self, fmt, *args):
        pass

    def _authorised(self) -> bool:
        pw = os.environ.get("ELUNO_UI_PASSWORD")
        if not pw or self.path == "/health":
            return True
        header = self.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                _user, _, given = base64.b64decode(header[6:]).decode("utf-8").partition(":")
                return hmac.compare_digest(given, pw)
            except Exception:
                return False
        return False

    def _json(self, status: int, data: Any) -> None:
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: str) -> None:
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (WEB_DIR / rel).resolve()
        if WEB_DIR.resolve() not in target.parents and target != WEB_DIR.resolve():
            return self._json(404, {"error": "NotFound"})
        if not target.is_file():
            target = WEB_DIR / "index.html"  # single-page app fallback
        data = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") or "javascript" in ctype else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, routes, query, body) -> None:
        path = urllib.parse.urlparse(self.path).path
        fn = routes.get(path)
        if not fn:
            return self._json(404, {"error": "NotFound", "message": "Unknown endpoint"})
        try:
            with _LOCK:
                self._json(200, fn(query, body))
        except ApiError as e:
            self._json(e.status, {"error": e.code, "message": e.message, "details": e.details})
        except Exception as e:  # keep the till alive; the screen shows the message
            self._json(500, {"error": "ServerError", "message": str(e)})

    def do_GET(self):
        if not self._authorised():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Eluno till"')
            self.end_headers()
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/health":
            return self._json(200, {"status": "ok"})
        if parsed.path.startswith("/api/"):
            q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            return self._dispatch(GET_ROUTES, q, {})
        self._static(parsed.path)

    def do_POST(self):
        if not self._authorised():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Eluno till"')
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "BadRequest", "message": "Invalid JSON body"})
        self._dispatch(POST_ROUTES, {}, body)


def run_web(port: int = 8080, host: str = "127.0.0.1") -> None:
    httpd = ThreadingHTTPServer((host, port), WebHandler)
    print(f"[ui] Eluno till UI on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()
