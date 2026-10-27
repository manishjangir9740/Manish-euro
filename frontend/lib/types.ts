export interface Store { code: string; name: string; id: number }
export interface Staff { id: string; name: string; role: string; store: string; can_approve_discount: boolean }
export interface Bootstrap {
  today: string; stores: Store[]; staff: Staff[]; channels: string[]; payment_methods: string[];
  discount_reason_codes: string[]; refund_reasons: string[]; manager_max_percent: number; till_variance_alert: number;
}
export interface Customer { id: number; name: string; phone: string; tags: string[]; is_priority: boolean; flags: string[]; total_spent: number }
export interface Eye { sph: number; cyl: number; axis: number | null; add: number | null }
export interface Rx {
  rx_id: string; date: string; valid_until: string; source: string; optometrist_id: string | null;
  od: Eye; os: Eye; pd: { binocular?: number | null }; notes: string | null;
}
export interface Frame { id: number; sku: string; name: string; price: number; stock: number | null; hsn: string }
export interface Verdict { valid: boolean; errors: string[]; warnings: string[] }
export interface Lens {
  id: number; sku: string; name: string; price: number; lens_type: string; index: number; coating: string;
  lab_tat_days: number; hsn: string; verdict?: Verdict;
  limits: { sph_min: number; sph_max: number; cyl_abs_max: number; add_required: boolean; add_min: number | null; add_max: number | null };
}
export interface TaxLine { title: string; rate_bps: number; amount: number }
export interface QuoteLine {
  index: number; pair_ref: string; variant_id: number; sku: string; name: string; line_type: "frame" | "lens"; hsn: string;
  mrp: number; discount: number; gross: number; taxable: number; tax: number; tax_lines: TaxLine[];
  offers: { offer_id: string; name: string; amount: number }[]; rx_id: string | null; warnings: string[];
}
export interface OfferEval { offer_id: string; name: string; applied: boolean; amount: number; why: string }
export interface Quote {
  lines: QuoteLine[];
  totals: { mrp: number; discount: number; taxable: number; tax: number; total: number };
  applied_offers: { offer_id: string; name: string; amount: number }[];
  offer_evaluations: OfferEval[];
}
export interface CheckoutResult extends Quote {
  invoice_no: string; status: "synced" | "pending_sync"; order_id: number | null; order_number: number | null;
  charge_id: string; invoice_text: string; warnings: string[]; payment_method: string;
}
export interface OrderLine { line_id: number; sku: string; name: string; line_type: string; gross: number; tax: number; taxable: number; refunded: boolean; rx_id: string | null }
export interface Order {
  order_id: number; name: string; invoice_no: string; created_at: string; channel: string; staff_id: string | null;
  payment_method: string; subtotal: number; discounts: number; tax: number; total: number; refunded: number; cancelled: boolean;
  refunds: { credit_note_no: string | null; amount: number; created_at: string }[]; lines: OrderLine[];
}
export interface RefundResult {
  credit_note_no: string; original_invoice_no: string; refund_amount: number; taxable_reversed: number; tax_reversed: number;
  is_full: boolean; lines: { line_id: number; restock: boolean }[]; till_recorded: boolean;
}
export interface Movement { type: string; amount_paise: number; ref: string; at: string; reason: string | null; staff_id: string | null }
export interface TillSession {
  session_id: string; opened_at: string; opened_by: string; opening_float_paise: number; movements: Movement[];
  closed_at: string | null; expected_cash_paise: number; counted_cash_paise: number | null; variance_paise: number | null;
  variance_note: string | null; variance_alert: boolean; is_open: boolean;
}
export interface DayEnd {
  store_code: string; date: string; bill_count: number; gross_sales: number; total_discounts: number; total_taxable: number;
  total_tax: number; net_billed: number; total_refunds: number; refund_tax: number; average_bill: number;
  payment_splits: Record<string, number>; payment_refunds: Record<string, number>; payment_net: Record<string, number>;
  channel_splits: Record<string, number>; channel_totals: Record<string, number>; mismatches: string[]; report_text: string;
}
export interface AuditEvent { timestamp: string; who: string; what: string; reason_code: string | null; ref: string | null; details: Record<string, unknown> }
