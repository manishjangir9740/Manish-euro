"""Acceptance tests: the brief's Must and Should requirements, checked end to end.

Boots the bundled mock (Shopify + store tool + terminal) and the till API on free ports with a fresh
state dir, then drives it over HTTP exactly as the UI does. The Shopify side is verified by reading the
orders back from the mock, not from our own responses.

    python -m unittest tests.test_acceptance -v
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
KARTHIK = "+919000000005"   # priority + progressive campaign, Rx with ADD
PLAIN = "+919000000004"    # no priority/campaign tags, valid Rx
RAHUL = "+919000000001"     # Rx without ADD
FRAME_HSR = 91000003        # stocked at HSR
LENS_PGX_160_BLUECUT = 91000083
LENS_PGX_160_STD = 91000081
LENS_SV = 91000041          # single vision


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(base, method, path, body=None):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


class Stack:
    """mock + API subprocesses"""

    def __init__(self, flaky=False):
        self.api_port, self.mock_port = free_port(), free_port()
        self.state = tempfile.mkdtemp(prefix="eluno-acc-")
        env = dict(os.environ, ELUNO_STATE_DIR=self.state, ELUNO_MOCK_SERVER_URL=f"http://127.0.0.1:{self.mock_port}",
                   PYTHONIOENCODING="utf-8")
        for k in ("SHOPIFY_SHOP", "SHOPIFY_ACCESS_TOKEN", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET", "PORT", "HOST", "ELUNO_API_TOKEN"):
            env.pop(k, None)
        cmd = [sys.executable, str(BACKEND / "app.py"), "--port", str(self.api_port), "--mock-port", str(self.mock_port)]
        if flaky:
            cmd.append("--flaky")
        self.proc = subprocess.Popen(cmd, cwd=str(BACKEND), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.api = f"http://127.0.0.1:{self.api_port}"
        self.mock = f"http://127.0.0.1:{self.mock_port}/admin/api/2026-10"
        for _ in range(100):
            try:
                urllib.request.urlopen(self.api + "/health", timeout=1).read()
                return
            except Exception:
                time.sleep(0.2)
        self.stop()
        raise RuntimeError("API did not start")

    def stop(self):
        # app.py starts the mock as a child: take the whole tree down (terminate() alone skips its atexit on Windows)
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            self.proc.terminate()
        try:
            self.proc.wait(10)
        except Exception:
            self.proc.kill()

    def get(self, path):
        return call(self.api, "GET", path)

    def post(self, path, body):
        return call(self.api, "POST", path, body)

    def shopify_order(self, order_id):
        with urllib.request.urlopen(f"{self.mock}/orders/{order_id}.json", timeout=20) as r:
            return json.loads(r.read())["order"]

    def bill(self, phone=KARTHIK, store="HSR", frame=FRAME_HSR, lens=LENS_PGX_160_BLUECUT, method="upi", channel="walk_in", **extra):
        pairs = extra.pop("pairs", [{"frame_id": frame, "lens_id": lens}])
        return self.post("/api/checkout", {"phone": phone, "store": store, "staff_id": "S105", "channel": channel,
                                            "payment_method": method, "pairs": pairs, **extra})

    def quote(self, phone=KARTHIK, store="HSR", **extra):
        pairs = extra.pop("pairs", [{"frame_id": FRAME_HSR, "lens_id": LENS_PGX_160_BLUECUT}])
        return self.post("/api/quote", {"phone": phone, "store": store, "staff_id": "S105", "channel": "walk_in", "pairs": pairs, **extra})


class AcceptanceBase(unittest.TestCase):
    stack = None
    flaky = False

    @classmethod
    def setUpClass(cls):
        cls.stack = Stack(flaky=cls.flaky)

    @classmethod
    def tearDownClass(cls):
        cls.stack.stop()


class TestMust(AcceptanceBase):
    # 1 ------------------------------------------------------------------
    def test_1_customer_lookup_with_valid_rx_and_flags(self):
        code, d = self.stack.get("/api/customer?phone=%2B919000000005")
        self.assertEqual(code, 200)
        self.assertEqual(d["customer"]["name"], "Karthik Reddy")
        self.assertIn("PRIORITY", d["customer"]["flags"])
        self.assertTrue(any(f.startswith("CAMPAIGN:") for f in d["customer"]["flags"]))
        rx = d["prescription"]
        self.assertIsNotNone(rx)
        self.assertGreaterEqual(rx["valid_until"], time.strftime("%Y-%m-%d"))   # only a currently valid Rx is returned
        self.assertEqual(rx["od"]["add"], 2.5)

    def test_1_unknown_customer_is_404_with_message(self):
        code, d = self.stack.get("/api/customer?phone=%2B910000000000")
        self.assertEqual(code, 404)
        self.assertIn("No customer", d["message"])

    # 2 ------------------------------------------------------------------
    def test_2_progressive_without_add_is_blocked_with_actionable_reason(self):
        code, d = self.stack.quote(phone=RAHUL, pairs=[{"frame_id": FRAME_HSR, "lens_id": LENS_PGX_160_STD}])
        self.assertEqual(code, 422)
        self.assertEqual(d["error"], "RxValidationFailed")
        self.assertIn("needs an ADD", d["message"])
        self.assertIn("single-vision", d["message"].lower())   # tells staff what to do instead

    def test_2_same_block_applies_at_checkout_and_charges_nothing(self):
        before = self.stack.get("/api/day-end?store=HSR")[1]["bill_count"]
        code, d = self.stack.bill(phone=RAHUL, lens=LENS_PGX_160_STD)
        self.assertEqual(code, 422)
        self.assertEqual(self.stack.get("/api/day-end?store=HSR")[1]["bill_count"], before)

    def test_2_catalog_marks_each_lens_with_verdict_and_single_vision_passes(self):
        code, d = self.stack.get("/api/catalog?store=HSR&phone=%2B919000000001")
        self.assertEqual(code, 200)
        by_id = {l["id"]: l for l in d["lenses"]}
        self.assertFalse(by_id[LENS_PGX_160_STD]["verdict"]["valid"])
        self.assertTrue(by_id[LENS_SV]["verdict"]["valid"])
        self.assertTrue(all("verdict" in l for l in d["lenses"]))

    def test_2_some_customer_without_valid_rx_cannot_buy_a_lens(self):
        for n in range(30):
            phone = f"+9190000000{n:02d}"
            code, d = self.stack.get("/api/customer?phone=" + phone.replace("+", "%2B"))
            if code == 200 and d["prescription"] is None:
                c, r = self.stack.quote(phone=phone, pairs=[{"lens_id": LENS_SV}])
                self.assertEqual(c, 422)
                self.assertIn("eye test", r["message"])
                return
        self.skipTest("no seed customer without a valid Rx")

    # 3 ------------------------------------------------------------------
    def test_3_offers_apply_with_reasons_for_every_offer(self):
        code, q = self.stack.quote()
        self.assertEqual(code, 200)
        applied = {o["offer_id"] for o in q["applied_offers"]}
        self.assertTrue({"PRIORITY500", "BUNDLE300", "FREE_BLUECUT_PGX"} <= applied, applied)   # stackable ones combine
        self.assertNotIn("FESTIVE10", applied)    # non-stackable never combines with them when the stack is better
        ids = {e["offer_id"] for e in q["offer_evaluations"]}
        self.assertIn("MONSOON20", ids)           # expired offer is listed ...
        monsoon = next(e for e in q["offer_evaluations"] if e["offer_id"] == "MONSOON20")
        self.assertFalse(monsoon["applied"])      # ... and explained, not silently dropped
        self.assertTrue(monsoon["why"])
        self.assertEqual(q["totals"]["discount"], sum(o["amount"] for o in q["applied_offers"]))

    def test_3_non_priority_customer_does_not_get_priority_offer(self):
        code, q = self.stack.quote(phone="+919000000004", pairs=[{"frame_id": FRAME_HSR, "lens_id": LENS_SV}])
        self.assertEqual(code, 200)
        self.assertNotIn("PRIORITY500", {o["offer_id"] for o in q["applied_offers"]})

    def test_3_manager_discount_needs_manager_reason_and_is_capped(self):
        mgr = lambda pct, who="S108", reason="WALKOUT_RISK": {"manager_discount": {"percent": pct, "approver_id": who, "reason_code": reason}}
        self.assertEqual(self.stack.quote(**mgr("8", who=""))[0], 422)          # no approver
        self.assertEqual(self.stack.quote(**mgr("8", reason=""))[0], 422)       # no reason
        self.assertEqual(self.stack.quote(**mgr("11"))[0], 422)                 # over 10%
        self.assertEqual(self.stack.quote(**mgr("8", who="S105"))[0], 422)      # S105 is sales, not a manager
        code, q = self.stack.quote(**mgr("8"))
        self.assertEqual(code, 200)

    # 4 ------------------------------------------------------------------
    def test_4_gst_per_line_reconciles_to_the_paisa(self):
        code, q = self.stack.quote(pairs=[{"frame_id": FRAME_HSR, "lens_id": LENS_PGX_160_BLUECUT},
                                          {"frame_id": 91000004, "lens_id": LENS_SV}])
        self.assertEqual(code, 200)
        for l in q["lines"]:
            cg = next(t for t in l["tax_lines"] if t["title"] == "CGST")["amount"]
            sg = next(t for t in l["tax_lines"] if t["title"] == "SGST")["amount"]
            self.assertEqual(l["taxable"] + cg + sg, l["gross"], l["name"])     # taxable + CGST + SGST = line total
            self.assertEqual(l["mrp"] - l["discount"], l["gross"])
            self.assertLessEqual(abs(cg - sg), 1)                                # halves differ by at most a paisa
        t = q["totals"]
        self.assertEqual(sum(l["gross"] for l in q["lines"]), t["total"])
        self.assertEqual(t["taxable"] + t["tax"], t["total"])
        rates = {l["hsn"]: l["tax_lines"][0]["rate_bps"] for l in q["lines"]}
        self.assertGreaterEqual(len(set(rates.values())), 2)                     # frame and lens HSNs carry different rates
        self.assertEqual(rates["90031900"], 900)                                 # frames 18% (9% + 9%)
        self.assertEqual(rates["90015000"], 250)                                 # lenses 5% (2.5% + 2.5%)

    # 5 ------------------------------------------------------------------
    def test_5_checkout_creates_a_complete_shopify_order(self):
        s = self.stack
        code, r = s.bill()
        self.assertEqual(code, 200)
        self.assertEqual(r["status"], "synced")
        self.assertRegex(r["invoice_no"], r"^ELU/HSR/FY26/\d{5}$")
        o = s.shopify_order(r["order_id"])
        attrs = {a["name"]: a["value"] for a in o["note_attributes"]}
        self.assertEqual(attrs["invoice_no"], r["invoice_no"])                     # per-store invoice number
        self.assertNotEqual(attrs["invoice_no"], o["name"])                         # not Shopify's order number
        self.assertEqual(attrs["store_code"], "HSR")
        self.assertEqual(attrs["channel"], "walk_in")
        self.assertTrue(o["taxes_included"])
        self.assertEqual(len(o["line_items"]), 2)
        for li in o["line_items"]:
            self.assertEqual({t["title"] for t in li["tax_lines"]}, {"CGST", "SGST"})    # tax lines per line
        lens = next(li for li in o["line_items"] if any(p["name"] == "rx_id" for p in li["properties"]))
        props = {p["name"]: p["value"] for p in lens["properties"]}
        self.assertEqual(props["rx_id"], "RX5007")                                  # Rx carried on the lens line
        self.assertIn("sph", props["rx"])
        frame = next(li for li in o["line_items"] if li is not lens)
        self.assertFalse(any(p["name"] == "rx_id" for p in frame["properties"]))
        self.assertTrue(o["discount_applications"])                                 # discounts present
        self.assertTrue(all(li["discount_allocations"] is not None for li in o["line_items"]))
        sale = [t for t in o["transactions"] if t["kind"] == "sale"]
        self.assertEqual(len(sale), 1)                                              # sale transaction
        self.assertEqual(sale[0]["status"], "success")
        self.assertEqual(round(float(sale[0]["amount"]) * 100), r["totals"]["total"])
        self.assertEqual(round(float(o["total_price"]) * 100), r["totals"]["total"])
        self.assertIn("ELUNO", r["invoice_text"])
        self.assertIn(r["invoice_no"], r["invoice_text"])

    def test_5_invoice_numbers_are_sequential_per_store(self):
        a = self.stack.bill(frame=None, lens=LENS_SV, phone="+919000000004")[1]["invoice_no"]
        b = self.stack.bill(frame=None, lens=LENS_SV, phone="+919000000004")[1]["invoice_no"]
        self.assertEqual(int(b.rsplit("/", 1)[1]), int(a.rsplit("/", 1)[1]) + 1)

    def test_5_out_of_stock_frame_is_refused_before_payment(self):
        code, cat = self.stack.get("/api/catalog?store=HSR&phone=%2B919000000005")
        out = next((f for f in cat["frames"] if f["stock"] == 0), None)
        if not out:
            self.skipTest("every frame has stock at HSR")
        code, d = self.stack.bill(frame=out["id"], lens=None)
        self.assertEqual(code, 409)
        self.assertIn("out of stock", d["message"].lower())

    # 6 ------------------------------------------------------------------
    def _stock(self, frame_id, store="HSR"):
        cat = self.stack.get(f"/api/catalog?store={store}&phone=%2B919000000005")[1]
        return next(f for f in cat["frames"] if f["id"] == frame_id)["stock"]

    def test_6_full_refund_reverses_tax_restocks_frame_not_lens(self):
        s = self.stack
        frame = 91000011
        before = self._stock(frame)
        code, r = s.bill(frame=frame, lens=LENS_SV)
        self.assertEqual(code, 200)
        self.assertEqual(self._stock(frame), before - 1)
        code, f = s.post("/api/refund", {"order_id": r["order_id"], "staff_id": "S105", "reason": "CHANGED_MIND"})
        self.assertEqual(code, 200, f)
        self.assertTrue(f["is_full"])
        self.assertEqual(f["refund_amount"], r["totals"]["total"])
        self.assertEqual(f["taxable_reversed"] + f["tax_reversed"], f["refund_amount"])
        self.assertEqual(f["tax_reversed"], r["totals"]["tax"])                      # tax reversed per line, in full
        self.assertEqual(self._stock(frame), before)                                 # frame back at the billing store
        by_line = {l["line_id"]: l["restock"] for l in f["lines"]}
        self.assertEqual(sorted(by_line.values()), [False, True])                    # frame restocked, lens not
        self.assertRegex(f["credit_note_no"], r"^ELU/HSR/FY26/CN/\d{5}$")
        self.assertEqual(f["original_invoice_no"], r["invoice_no"])                  # credit note references the invoice
        o = s.shopify_order(r["order_id"])
        sale = next(t for t in o["transactions"] if t["kind"] == "sale")
        self.assertEqual(len(o["refunds"]), 1)
        rf = o["refunds"][0]
        rtx = [t for t in rf["transactions"] if t["kind"] == "refund"]
        self.assertEqual(len(rtx), 1)                                                # refund transaction ...
        self.assertEqual(rtx[0]["parent_id"], sale["id"])                            # ... recorded against the sale
        self.assertEqual(round(float(rtx[0]["amount"]) * 100), r["totals"]["total"])
        self.assertEqual(sorted(li["restock_type"] for li in rf["refund_line_items"]), ["no_restock", "return"])
        restocked = next(li for li in rf["refund_line_items"] if li["restock_type"] == "return")
        self.assertEqual(restocked["location_id"], 70000002)                         # at HSR, the billing store
        notes = {a["name"]: a["value"] for a in rf["note_attributes"]}
        self.assertEqual(notes["credit_note_no"], f["credit_note_no"])
        self.assertEqual(notes["original_invoice_no"], r["invoice_no"])
        self.assertEqual(round(sum(float(li["total_tax"]) for li in rf["refund_line_items"]) * 100), f["tax_reversed"])

    def test_6_second_refund_of_same_bill_is_rejected(self):
        s = self.stack
        r = s.bill(frame=None, lens=LENS_SV, phone="+919000000004")[1]
        self.assertEqual(s.post("/api/refund", {"order_id": r["order_id"], "staff_id": "S105", "reason": "DEFECT"})[0], 200)
        code, d = s.post("/api/refund", {"order_id": r["order_id"], "staff_id": "S105", "reason": "DEFECT"})
        self.assertEqual(code, 422)

    def test_6_partial_refund_lens_only_keeps_frame_stock(self):
        s = self.stack
        frame = 91000012
        before = self._stock(frame)
        r = s.bill(frame=frame, lens=LENS_SV)[1]
        lens_line = next(l for l in s.get("/api/orders?store=HSR")[1]["orders"] if l["order_id"] == r["order_id"])["lines"]
        lens_id = next(l["line_id"] for l in lens_line if l["line_type"] == "lens")
        code, f = s.post("/api/refund", {"order_id": r["order_id"], "staff_id": "S105", "reason": "WRONG_RX", "line_ids": [lens_id]})
        self.assertEqual(code, 200, f)
        self.assertFalse(f["is_full"])
        self.assertFalse(any(l["restock"] for l in f["lines"]))
        self.assertEqual(self._stock(frame), before - 1)                             # frame still sold

    def test_6_bad_reason_rejected(self):
        r = self.stack.bill(frame=None, lens=LENS_SV, phone="+919000000004")[1]
        code, _ = self.stack.post("/api/refund", {"order_id": r["order_id"], "staff_id": "S105", "reason": "BECAUSE"})
        self.assertEqual(code, 422)

    # 7 ------------------------------------------------------------------
    def test_7_day_end_matches_shopify_orders_exactly(self):
        s = self.stack
        store = "KMG"      # a store nothing else in this class bills at: totals are fully ours
        a = s.bill(store=store, frame=None, lens=LENS_SV, phone="+919000000004", method="upi")[1]
        b = s.bill(store=store, frame=None, lens=LENS_SV, phone="+919000000005", method="card", channel="whatsapp_booked")[1]
        s.post("/api/refund", {"order_id": b["order_id"], "staff_id": "S105", "reason": "CHANGED_MIND"})
        code, d = s.get(f"/api/day-end?store={store}")
        self.assertEqual(code, 200)
        self.assertEqual(d["bill_count"], 2)
        self.assertEqual(d["gross_sales"], a["totals"]["mrp"] + b["totals"]["mrp"])
        self.assertEqual(d["total_discounts"], a["totals"]["discount"] + b["totals"]["discount"])
        self.assertEqual(d["total_tax"], a["totals"]["tax"] + b["totals"]["tax"])
        self.assertEqual(d["total_taxable"], a["totals"]["taxable"] + b["totals"]["taxable"])
        self.assertEqual(d["net_billed"], a["totals"]["total"] + b["totals"]["total"])
        self.assertEqual(d["total_refunds"], b["totals"]["total"])
        self.assertEqual(d["payment_splits"], {"upi": a["totals"]["total"], "card": b["totals"]["total"]})
        self.assertEqual(d["payment_net"]["card"], 0)
        self.assertEqual(d["channel_splits"], {"walk_in": 1, "whatsapp_booked": 1})
        self.assertEqual(d["mismatches"], [])
        self.assertIn("ELUNO DAY-END REPORT", d["report_text"])
        # independent check against Shopify itself
        orders = json.loads(urllib.request.urlopen(f"{s.mock}/orders.json?status=any&limit=250&location_id=70000004").read())["orders"]
        mine = {a["invoice_no"], b["invoice_no"]}
        todays = [o for o in orders if any(x["value"] in mine for x in o["note_attributes"] if x["name"] == "invoice_no")]
        self.assertEqual(len(todays), 2)
        self.assertEqual(sum(round(float(o["total_price"]) * 100) for o in todays), d["net_billed"])

    def test_7_seed_day_report_works_for_a_store_with_history(self):
        code, d = self.stack.get("/api/day-end?store=JN&date=2026-10-06")
        self.assertEqual(code, 200)
        self.assertGreater(d["bill_count"], 0)
        self.assertEqual(d["gross_sales"] - d["total_discounts"], d["net_billed"])

    def test_7_unknown_store_is_404(self):
        self.assertEqual(self.stack.get("/api/day-end?store=NOPE")[0], 404)


class TestShould(AcceptanceBase):
    def test_cash_till_lifecycle_and_variance_alert(self):
        s = self.stack
        # cash needs an open till
        code, d = s.bill(method="cash", store="BR", frame=None, lens=LENS_SV, phone="+919000000004")
        self.assertEqual(code, 409)
        self.assertEqual(d["error"], "TillClosed")
        # open, sell for cash, paid out, refund in cash, close with a counted amount
        code, t = s.post("/api/till/open", {"store": "BR", "staff_id": "S112", "float": "3000"})
        self.assertEqual(code, 200)
        sid = t["session"]["session_id"]
        code, r = s.bill(method="cash", store="BR", frame=None, lens=LENS_SV, phone="+919000000004")
        self.assertEqual(code, 200, r)
        self.assertEqual(s.post("/api/till/move", {"session_id": sid, "type": "paid_out", "amount": "120", "reason": "courier", "staff_id": "S112"})[0], 200)
        code, bad = s.post("/api/till/move", {"session_id": sid, "type": "paid_out", "amount": "50", "reason": "", "staff_id": "S112"})
        self.assertIn(code, (400, 422))                                              # paid-out needs a reason
        sess = s.get("/api/till?store=BR")[1]["session"]
        expected = 300000 + r["totals"]["total"] - 12000
        self.assertEqual(sess["expected_cash_paise"], expected)
        # short by Rs 250: above the Rs 200 limit -> flagged
        counted = f"{(expected - 25000) / 100:.2f}"
        code, closed = s.post("/api/till/close", {"session_id": sid, "staff_id": "S112", "counted": counted, "note": ""})
        self.assertEqual(code, 200)
        c = closed["session"]
        self.assertEqual(c["variance_paise"], -25000)
        self.assertTrue(c["variance_alert"])
        self.assertFalse(c["is_open"])
        # day-end reconciles till cash vs Shopify cash
        self.assertEqual(s.get("/api/day-end?store=BR")[1]["payment_splits"]["cash"], r["totals"]["total"])
        # closed till takes no more cash
        self.assertEqual(s.bill(method="cash", store="BR", frame=None, lens=LENS_SV, phone="+919000000004")[0], 409)

    def test_till_variance_within_limit_is_not_flagged(self):
        s = self.stack
        sid = s.post("/api/till/open", {"store": "MM", "staff_id": "S104", "float": "1000"})[1]["session"]["session_id"]
        c = s.post("/api/till/close", {"session_id": sid, "staff_id": "S104", "counted": "1100", "note": "tips"})[1]["session"]
        self.assertEqual(c["variance_paise"], 10000)
        self.assertFalse(c["variance_alert"])

    def test_cash_refund_is_recorded_in_till(self):
        s = self.stack
        s.post("/api/till/open", {"store": "JN", "staff_id": "S116", "float": "2000"})
        r = s.bill(method="cash", store="JN", frame=None, lens=LENS_SV, phone="+919000000004")[1]
        code, f = s.post("/api/refund", {"order_id": r["order_id"], "staff_id": "S116", "reason": "CHANGED_MIND"})
        self.assertEqual(code, 200)
        self.assertTrue(f["till_recorded"])
        sess = s.get("/api/till?store=JN")[1]["session"]
        self.assertEqual(sess["expected_cash_paise"], 200000)                         # sale and refund net to the float
        self.assertEqual([m["type"] for m in sess["movements"]], ["cash_sale", "cash_refund"])

    def test_sales_channel_recorded_on_order_and_split_in_report(self):
        s = self.stack
        r = s.bill(store="BR", frame=None, lens=LENS_SV, phone="+919000000004", channel="online_pickup")[1]
        attrs = {a["name"]: a["value"] for a in s.shopify_order(r["order_id"])["note_attributes"]}
        self.assertEqual(attrs["channel"], "online_pickup")
        self.assertIn("online_pickup", s.get("/api/day-end?store=BR")[1]["channel_splits"])

    def test_audit_trail_records_who_what_reason(self):
        s = self.stack
        r = s.bill(frame=None, lens=LENS_SV, phone="+919000000004",
                   manager_discount={"percent": "5", "approver_id": "S108", "reason_code": "PRICE_MATCH"})[1]
        ev = s.get("/api/audit")[1]["events"]
        done = next(e for e in ev if e["what"] == "ORDER_COMPLETED" and e["ref"] == r["invoice_no"])
        self.assertEqual(done["who"], "S105")
        self.assertEqual(done["reason_code"], "PRICE_MATCH")
        self.assertEqual(done["details"]["discount_approver_id"], "S108")
        o = s.shopify_order(r["order_id"])
        self.assertTrue(any("S108" in json.dumps(x) for x in o["note_attributes"]) or "S108" in json.dumps(o))   # approver on the Shopify order
        self.assertIn("MANAGER", json.dumps(o["discount_applications"]).upper())

    def test_printable_invoice_has_gst_breakup(self):
        r = self.stack.bill(frame=FRAME_HSR, lens=None, phone="+919000000004", store="MM")
        code, d = r
        if code != 200:                       # frame may not be stocked at MM
            d = self.stack.bill(frame=None, lens=LENS_SV, phone="+919000000004", store="MM")[1]
        txt = d["invoice_text"]
        for word in ("CGST", "SGST", "HSN", "TOTAL"):
            self.assertIn(word, txt.upper())


class TestResilience(AcceptanceBase):
    flaky = True     # the mock returns 429s and terminal 503s

    def test_flaky_mock_never_double_charges_or_double_creates(self):
        s = self.stack
        N = 8
        results = []
        for i in range(N):
            code, r = s.bill(frame=None, lens=LENS_SV, phone="+919000000004", store="HSR")
            self.assertEqual(code, 200, r)
            results.append(r)
        invoices = [r["invoice_no"] for r in results]
        self.assertEqual(len(set(invoices)), N)                                       # unique numbers
        nums = sorted(int(i.rsplit("/", 1)[1]) for i in invoices)
        self.assertEqual(nums, list(range(nums[0], nums[0] + N)))                    # gapless despite retries
        orders = json.loads(urllib.request.urlopen(f"{s.mock}/orders.json?status=any&limit=250&location_id=70000002").read())["orders"]
        ours = [o for o in orders if any(a["name"] == "invoice_no" and a["value"] in invoices for a in o["note_attributes"])]
        self.assertEqual(len(ours), N)                                                # exactly one Shopify order per bill
        for o in ours:
            self.assertEqual(len([t for t in o["transactions"] if t["kind"] == "sale"]), 1)   # exactly one sale transaction


if __name__ == "__main__":
    unittest.main()
