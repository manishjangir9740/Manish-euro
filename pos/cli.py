"""Command line front end for the Eluno POS."""

import argparse
import sys
from datetime import date
from typing import List, Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from pos.domain.money import Money
from pos.domain.rx_validator import RxValidationError
from pos.services.pos_service import PosService


def _print_checkout(res) -> None:
    print(res["invoice_text"])
    if res["status"] == "pending_sync":
        print(f"\n[!] Paid, but Shopify was unreachable. Invoice {res['invoice_no']} is saved locally.")
        print("    Run: python run_pos.py sync-pending   (safe to repeat; never creates a duplicate)")
    for w in res["warnings"]:
        print(f"[warn] {w}")


def run_demo(service: PosService) -> None:
    today = date.today().isoformat()
    phone, store, staff = "+919000000005", "HSR", "S105"
    banner = lambda t: print(f"\n{'=' * 78}\n  {t}\n{'=' * 78}")

    banner("1. Customer + prescription lookup")
    cust, rx = service.lookup_customer_and_rx(phone, today)
    if not cust:
        print(f"Customer {phone} not found. Is the mock server running?")
        return
    print(f"Customer : {cust.full_name} (id {cust.id})   flags: {cust.billing_flags or 'none'}")
    if rx:
        print(f"Latest valid Rx {rx.rx_id}: OD {rx.od.sph:+.2f}/{rx.od.cyl:+.2f} add {rx.od.add}, "
              f"OS {rx.os.sph:+.2f}/{rx.os.cyl:+.2f} add {rx.os.add}, valid until {rx.valid_until}")

    banner("2. Lens validation against the prescription")
    probe = service.create_cart(cust, "whatsapp_booked", staff)
    try:
        service.add_pair_to_cart(probe, None, 91000081, store, rx=rx, order_date=today)  # Progressive 1.60 standard
        print("Progressive 1.60 standard: accepted for this Rx")
    except RxValidationError as exc:
        print(f"Blocked: {exc}")
    try:
        service.add_pair_to_cart(probe, None, 91000041, store, rx=None, order_date=today)
    except RxValidationError as exc:
        print(f"Blocked without Rx: {exc}")

    banner("3. Bill: frame + progressive lens -> offers -> GST -> terminal -> Shopify")
    cart = service.create_cart(cust, "whatsapp_booked", staff)
    service.add_pair_to_cart(cart, 91000003, 91000083, store, "1", rx=rx, order_date=today)
    res = service.checkout(cart, store, staff, "upi", order_date=today)
    _print_checkout(res)
    print("\nOffer evaluation:")
    for e in res["offer_evaluations"]:
        print(f"  {'APPLIED ' if e['applied'] else 'skipped '} {e['offer_id']:<18} {e['amount'].format_inr():>12}  {e['why']}")

    banner("4. Full refund: tax reversed per line, frame restocked at HSR, lens scrapped")
    rf = service.process_refund(res["order_id"], staff, "CHANGED_MIND")
    print(f"Credit note {rf['credit_note_no']} against {rf['original_invoice_no']}")
    print(f"Refunded {rf['refund_amount'].format_inr()} = taxable {rf['taxable_reversed'].format_inr()} + "
          f"GST {rf['tax_reversed'].format_inr()}")
    for l in rf["plan"].lines:
        print(f"  line {l.line_id}: {'RESTOCK at location ' + str(l.location_id) if l.restock else 'no restock (lens scrapped)'}")

    banner("5. Cash till: open, cash sale, paid-out, close with count")
    loc = service.shopify.get_location_by_code(store)
    session = service.till.open_session(store, loc.id, "S108", Money.from_decimal("3000"), f"TILL-{store}-{today}")
    cart2 = service.create_cart(cust, "walk_in", staff)
    service.add_pair_to_cart(cart2, 91000014, 91000041, store, "1", rx=service.smt.get_latest_valid_prescription(phone, today), order_date=today)
    res2 = service.checkout(cart2, store, staff, "cash", order_date=today, till_session_id=session["session_id"])
    print(f"Cash bill {res2['invoice_no']} {res2['total_price'].format_inr()} ({res2['status']})")
    service.till.record_cash_movement(session["session_id"], "paid_out", Money.from_decimal("120"), "PO-HSR-1", "courier", "S108")
    closed = service.till.close_session(session["session_id"], "S108", Money.from_decimal("3000") + res2["total_price"] - Money.from_decimal("120") - Money.from_decimal("250"))
    print(f"Expected {Money(closed['expected_cash_paise']).format_inr()}, counted {Money(closed['counted_cash_paise']).format_inr()}, "
          f"variance {Money(closed['variance_paise']).format_inr()}\n{closed['variance_note']}")

    banner("6. Day-end reports (computed from Shopify orders)")
    print(service.generate_day_end_report(store, today)["report_text"])
    print(service.generate_day_end_report("JN", "2026-10-06")["report_text"])
    print("\n[DONE] Must flow completed.")


def run_bench(service: PosService, args) -> None:
    """The 10-second target is measured from the moment the customer says yes: the checkout call
    (price, validate, charge, create in Shopify, invoice). Cart building is timed separately."""
    import time
    cust, rx = service.lookup_customer_and_rx(args.phone)
    loc = service.shopify.get_location_by_code(args.store)
    frames = [f for f in service.shopify.list_frame_variants()
              if f.inventory_item_id and service.shopify.check_stock(f.inventory_item_id, loc.id) > 0][: args.n]
    if len(frames) < args.n:
        sys.exit(f"Only {len(frames)} frames in stock at {args.store}; use --n {len(frames)}.")
    build, bill = [], []
    for f in frames:
        t0 = time.perf_counter()
        cart = service.create_cart(cust, "walk_in", args.staff)
        service.add_pair_to_cart(cart, f.id, 91000041, args.store, rx=rx)
        t1 = time.perf_counter()
        res = service.checkout(cart, args.store, args.staff, "upi")
        t2 = time.perf_counter()
        build.append(t1 - t0)
        bill.append(t2 - t1)
        print(f"  {res['invoice_no']}  build cart {t1 - t0:5.2f}s   checkout {t2 - t1:5.2f}s   ({res['status']})")
    bill_sorted = sorted(bill)
    print(f"checkout over {len(bill)} bills: avg {sum(bill) / len(bill):.2f}s, worst {bill_sorted[-1]:.2f}s "
          f"(target < 10s, measured against a local mock: network latency of real store Wi-Fi is not included)")


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Eluno POS CLI")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("demo", help="End-to-end demo against the mock APIs")

    lk = sub.add_parser("lookup", help="Customer + latest valid prescription")
    lk.add_argument("--phone", required=True)

    ln = sub.add_parser("lenses", help="List lenses that suit this customer's prescription")
    ln.add_argument("--phone", required=True)
    ln.add_argument("--type", choices=["single_vision", "bifocal", "progressive"])
    ln.add_argument("--coating")

    co = sub.add_parser("checkout", help="Bill a frame + lens pair")
    co.add_argument("--phone", required=True)
    co.add_argument("--store", default="HSR")
    co.add_argument("--frame", type=int, required=True, help="Frame variant id")
    co.add_argument("--lens", type=int, required=True, help="Lens variant id")
    co.add_argument("--staff", required=True)
    co.add_argument("--method", default="upi", choices=["upi", "card", "cash"])
    co.add_argument("--channel", default="walk_in", choices=["walk_in", "whatsapp_booked", "online_pickup"])
    co.add_argument("--till-session", help="Till session id (required for cash to hit the drawer)")
    co.add_argument("--manager-discount", type=float, help="Manager discount percent, max 10")
    co.add_argument("--approver", help="Store manager staff id approving the discount")
    co.add_argument("--reason-code", help="Reason code for the manager discount")

    rf = sub.add_parser("refund", help="Refund an order (full, or selected lines)")
    rf.add_argument("--order-id", type=int, required=True)
    rf.add_argument("--staff", required=True)
    rf.add_argument("--reason", default="CHANGED_MIND")
    rf.add_argument("--lines", type=int, nargs="*", help="Line item ids for a partial refund")
    rf.add_argument("--till-session")

    de = sub.add_parser("day-end", help="Day-end report for a store and date")
    de.add_argument("--store", required=True)
    de.add_argument("--date", default=date.today().isoformat())

    tl = sub.add_parser("till", help="Cash drawer")
    tsub = tl.add_subparsers(dest="till_cmd", required=True)
    t_open = tsub.add_parser("open"); t_open.add_argument("--store", required=True); t_open.add_argument("--staff", required=True); t_open.add_argument("--float", required=True, help="Opening float in rupees")
    t_mv = tsub.add_parser("move"); t_mv.add_argument("--session", required=True); t_mv.add_argument("--type", choices=["paid_in", "paid_out"], required=True); t_mv.add_argument("--amount", required=True); t_mv.add_argument("--reason", required=True); t_mv.add_argument("--staff", required=True)
    t_close = tsub.add_parser("close"); t_close.add_argument("--session", required=True); t_close.add_argument("--staff", required=True); t_close.add_argument("--counted", required=True); t_close.add_argument("--note")

    bn = sub.add_parser("bench", help="Time N bills against the mock (creates real orders in the mock)")
    bn.add_argument("--n", type=int, default=5)
    bn.add_argument("--store", default="HSR")
    bn.add_argument("--staff", default="S105")
    bn.add_argument("--phone", default="+919000000005")

    sv = sub.add_parser("serve", help="Optional HTTP API on localhost (no authentication)")
    sv.add_argument("--port", type=int, default=8000)

    sub.add_parser("sync-pending", help="Replay paid bills that are not yet in Shopify")

    args = parser.parse_args(argv)
    service = PosService()

    try:
        if args.command in (None, "demo"):
            run_demo(service)
        elif args.command == "lookup":
            cust, rx = service.lookup_customer_and_rx(args.phone)
            print(f"Customer: {cust.full_name if cust else 'NOT FOUND'}  flags: {cust.billing_flags if cust else ''}")
            print(f"Latest valid Rx: {rx.rx_id if rx else 'NONE - eye test needed'}")
        elif args.command == "lenses":
            _, rx = service.lookup_customer_and_rx(args.phone)
            if not rx:
                sys.exit("No valid prescription on file.")
            for v in service.suggest_lenses(rx, args.type, args.coating)[:30]:
                print(f"{v.id}  {v.sku}  {v.display_name:<28} {v.price.format_inr():>12}")
        elif args.command == "checkout":
            cust, rx = service.lookup_customer_and_rx(args.phone)
            if not cust:
                sys.exit(f"Customer {args.phone} not found.")
            print(f"Customer flags: {cust.billing_flags or 'none'}")
            cart = service.create_cart(cust, args.channel, args.staff)
            service.add_pair_to_cart(cart, args.frame, args.lens, args.store, rx=rx)
            bps = round(args.manager_discount * 100) if args.manager_discount else None
            _print_checkout(service.checkout(
                cart, args.store, args.staff, args.method, args.channel,
                till_session_id=args.till_session, manager_discount_bps=bps,
                approver_id=args.approver, reason_code=args.reason_code))
        elif args.command == "refund":
            r = service.process_refund(args.order_id, args.staff, args.reason, args.lines or None, args.till_session)
            print(f"Credit note {r['credit_note_no']} ({'full' if r['is_full'] else 'partial'}): "
                  f"{r['refund_amount'].format_inr()} incl. GST {r['tax_reversed'].format_inr()}")
        elif args.command == "day-end":
            print(service.generate_day_end_report(args.store, args.date)["report_text"])
        elif args.command == "till":
            if args.till_cmd == "open":
                loc = service.shopify.get_location_by_code(args.store)
                s = service.till.open_session(args.store, loc.id, args.staff, Money.from_decimal(args.float))
                print(f"Till session {s['session_id']} open, float {Money(s['opening_float_paise']).format_inr()}")
            elif args.till_cmd == "move":
                service.till.record_cash_movement(args.session, args.type, Money.from_decimal(args.amount),
                                                  f"{args.type.upper()}-{args.session}", args.reason, args.staff)
                print("Recorded.")
            else:
                s = service.till.close_session(args.session, args.staff, Money.from_decimal(args.counted), args.note)
                print(f"Expected {Money(s['expected_cash_paise']).format_inr()} counted {Money(s['counted_cash_paise']).format_inr()} "
                      f"variance {Money(s['variance_paise']).format_inr()}")
                if s["variance_alert"]:
                    print(s["variance_note"])
        elif args.command == "serve":
            from pos.server import run_server
            run_server(args.port)
        elif args.command == "bench":
            run_bench(service, args)
        elif args.command == "sync-pending":
            rows = service.sync_pending()
            for r in rows:
                print(r)
            print(f"{len(rows)} pending bill(s) processed.")
    except RxValidationError as exc:
        sys.exit(f"BLOCKED: {exc}")
    except (ValueError, RuntimeError) as exc:
        sys.exit(f"ERROR: {exc}")


if __name__ == "__main__":
    main()
