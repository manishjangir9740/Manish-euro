const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const inr0 = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 0, maximumFractionDigits: 0 });

/** Paise (integer) to ₹ with two decimals. The backend only ever sends integer paise. */
export const money = (paise: number | null | undefined) => inr.format((paise || 0) / 100);
/** Whole rupees when there are no paise (catalog prices), exact otherwise. */
export const moneyShort = (paise: number) => (paise % 100 === 0 ? inr0 : inr).format(paise / 100);

export const fmtTime = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true }) : "";
export const fmtDate = (iso?: string | null) =>
  iso ? new Date(iso.length === 10 ? iso + "T00:00:00" : iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "";
export const titleCase = (s: unknown) => String(s ?? "").toLowerCase().replace(/[_:]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
export const signed = (n: number | null | undefined) => (n == null ? "–" : (n > 0 ? "+" : "") + Number(n).toFixed(2));

/** Normalise typed input to the E.164 number Shopify stores: +91XXXXXXXXXX. */
export function normalisePhone(raw: string): string {
  const digits = raw.replace(/\D/g, "");
  if (!digits) return "";
  if (digits.length === 10) return "+91" + digits;
  return "+" + digits;
}

/** Rupees typed by staff (e.g. "3,000.50") to paise, or null if it is not an amount. */
export function rupeesToPaise(raw: string): number | null {
  const t = raw.trim().replace(/,/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(t)) return null;
  const [r, p = ""] = t.split(".");
  return Number(r) * 100 + Number((p + "00").slice(0, 2));
}

export function printText(title: string, text: string) {
  const frame = document.createElement("iframe");
  frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0";
  document.body.appendChild(frame);
  const doc = frame.contentDocument!;
  doc.open();
  doc.write(`<title>${title}</title><pre style="font:11px/1.45 Consolas,monospace;white-space:pre-wrap"></pre>`);
  doc.close();
  doc.querySelector("pre")!.textContent = text;
  frame.contentWindow!.focus();
  frame.contentWindow!.print();
  setTimeout(() => frame.remove(), 1500);
}
