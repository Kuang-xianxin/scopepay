/**
 * @typedef {{id:string,title:string,quantity:number,unit_cents:number,line_cents:number}} QuoteLine
 * @typedef {{id:string,currency:'USD'|'EUR'|'GBP',total_cents:number,fingerprint:string,items:QuoteLine[]}} Quote
 * @typedef {{project:'ScopePay',schema_version:2,quote:Quote,status:string,order:object|null,receipt:object|null,audit:object[]}} Snapshot
 * The server's Pydantic/OpenAPI schema is authoritative. This runtime guard
 * rejects malformed/old endpoint responses before they drive payment controls.
 */
export function validateResponse(path, data) {
  if (!data || typeof data !== "object")
    throw new Error("invalid_server_response");
  if (/\/snapshot$/.test(path) || /\/export$/.test(path)) {
    const q = data.quote;
    if (
      data.project !== "ScopePay" ||
      data.schema_version !== 2 ||
      !q ||
      !Number.isSafeInteger(q.total_cents) ||
      q.total_cents <= 0 ||
      !["USD", "EUR", "GBP"].includes(q.currency) ||
      !Array.isArray(q.items) ||
      typeof q.fingerprint !== "string" ||
      !Array.isArray(data.audit) ||
      ![
        "review",
        "approved",
        "awaiting_buyer",
        "capture_ready",
        "paid",
        "unknown",
        "creating",
        "revoked",
        "expired",
        "declined",
        "payment_declined",
      ].includes(data.status)
    ) {
      throw new Error("invalid_server_response");
    }
  }
  if (
    path.startsWith("/api/purchases") &&
    (!Array.isArray(data.items) || !Number.isSafeInteger(data.total))
  ) {
    throw new Error("invalid_server_response");
  }
}
