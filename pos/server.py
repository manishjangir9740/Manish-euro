"""Lightweight HTTP REST API server for Eluno POS.

Runs with zero dependencies using Python's standard http.server.
Allows external testing via curl, Postman, or browser.

Endpoints:
  GET  /health
  GET  /api/customer?phone=%2B919000000005
  POST /api/checkout
  POST /api/refund
  GET  /api/day-end?store=JN&date=2026-10-06
"""

import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional
from pos.services.pos_service import PosService
from pos.domain.rx_validator import RxValidationError


class PosApiHandler(BaseHTTPRequestHandler):
    service = PosService()

    def _send_json(self, status_code: int, data: Dict[str, Any]) -> None:
        body = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Optional[Dict[str, Any]]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        try:
            raw = self.rfile.read(length).decode("utf-8")
            return json.loads(raw)
        except Exception:
            return None

    def do_OPTIONS(self):
        self._send_json(200, {"ok": True})

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. Health check
        if path == "/health":
            return self._send_json(200, {"status": "ok", "service": "Eluno POS API"})

        # 2. Customer & Rx lookup
        if path == "/api/customer":
            phones = query.get("phone", [])
            if not phones:
                return self._send_json(400, {"error": "Query param 'phone' is required"})
            phone = phones[0]
            cust, rx = self.service.lookup_customer_and_rx(phone)
            if not cust:
                return self._send_json(404, {"error": f"Customer with phone {phone} not found"})

            rx_data = None
            if rx:
                rx_data = {
                    "rx_id": rx.rx_id,
                    "date": rx.date,
                    "valid_until": rx.valid_until,
                    "is_valid": rx.is_valid_for_date(),
                    "od": {"sph": rx.od.sph, "cyl": rx.od.cyl, "axis": rx.od.axis, "add": rx.od.add},
                    "os": {"sph": rx.os.sph, "cyl": rx.os.cyl, "axis": rx.os.axis, "add": rx.os.add},
                    "pd": rx.pd,
                }

            return self._send_json(200, {
                "customer": {
                    "id": cust.id,
                    "name": cust.full_name,
                    "phone": cust.phone,
                    "tags": cust.tags,
                    "is_priority": cust.is_priority,
                    "total_spent": cust.total_spent.format_inr(),
                },
                "prescription": rx_data,
            })

        # 3. Day-end report
        if path == "/api/day-end":
            store = query.get("store", ["HSR"])[0]
            date_str = query.get("date", ["2026-10-06"])[0]
            try:
                report = self.service.generate_day_end_report(store_code=store, date_str=date_str)
                return self._send_json(200, report)
            except Exception as exc:
                return self._send_json(500, {"error": str(exc)})

        self._send_json(404, {"error": "Endpoint not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self._read_body()
        if body is None:
            return self._send_json(400, {"error": "Invalid JSON body"})

        # 1. Retail Checkout
        if path == "/api/checkout":
            phone = body.get("phone")
            store_code = body.get("store", "HSR")
            staff_id = body.get("staff_id", "S105")
            frame_id = body.get("frame_variant_id")
            lens_id = body.get("lens_variant_id")
            payment_method = body.get("payment_method", "upi")
            channel = body.get("channel", "walk_in")
            order_date = body.get("order_date")

            if not phone:
                return self._send_json(400, {"error": "phone is required"})

            cust, rx = self.service.lookup_customer_and_rx(phone, target_date=order_date)
            if not cust:
                return self._send_json(404, {"error": f"Customer {phone} not found"})

            cart = self.service.create_cart(customer=cust, channel=channel, staff_id=staff_id)
            try:
                self.service.add_pair_to_cart(
                    cart=cart,
                    frame_variant_id=frame_id,
                    lens_variant_id=lens_id,
                    store_code=store_code,
                    rx=rx,
                    order_date=order_date,
                )
            except RxValidationError as exc:
                return self._send_json(422, {"error": "RxValidationFailed", "message": str(exc)})
            except Exception as exc:
                return self._send_json(400, {"error": str(exc)})

            try:
                result = self.service.checkout(
                    cart=cart,
                    store_code=store_code,
                    staff_id=staff_id,
                    payment_method=payment_method,
                    channel=channel,
                    order_date=order_date,
                )
                return self._send_json(201, {
                    "success": True,
                    "invoice_no": result["invoice_no"],
                    "order_id": result["order_id"],
                    "order_number": result["order_number"],
                    "charge_id": result["charge_id"],
                    "total_price": result["total_price"].format_inr(),
                    "total_tax": result["total_tax"].format_inr(),
                    "invoice_text": result["invoice_text"],
                })
            except Exception as exc:
                return self._send_json(500, {"error": "CheckoutFailed", "message": str(exc)})

        # 2. Refund
        if path == "/api/refund":
            order_id = body.get("order_id")
            staff_id = body.get("staff_id", "S105")
            reason = body.get("reason", "CHANGED_MIND")

            if not order_id:
                return self._send_json(400, {"error": "order_id is required"})

            try:
                res = self.service.process_refund(order_id=int(order_id), staff_id=staff_id, reason=reason)
                return self._send_json(200, {
                    "success": True,
                    "credit_note_no": res["credit_note_no"],
                    "refund_amount": res["refund_amount"].format_inr(),
                    "refund_id": res["refund_id"],
                })
            except ValueError as exc:  # unknown order, already refunded, bad reason: the caller's mistake
                return self._send_json(422, {"error": "RefundRejected", "message": str(exc)})
            except Exception as exc:
                return self._send_json(500, {"error": "RefundFailed", "message": str(exc)})

        self._send_json(404, {"error": "Endpoint not found"})


def run_server(port: int = 8000, host: str = "127.0.0.1") -> None:
    """Serve the API. Binds to localhost by default: there is no authentication, so do not expose it
    on a store network (anyone who can reach it could issue refunds)."""
    server_address = (host, port)
    httpd = HTTPServer(server_address, PosApiHandler)
    print(f"\n[*] Eluno POS HTTP REST API running on http://localhost:{port}")
    print("    - GET  /health")
    print("    - GET  /api/customer?phone=+919000000005")
    print("    - POST /api/checkout")
    print("    - POST /api/refund")
    print("    - GET  /api/day-end?store=JN&date=2026-10-06\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down POS server.")
        httpd.server_close()
