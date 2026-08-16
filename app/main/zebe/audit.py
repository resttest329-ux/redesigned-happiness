### R1 — No IRN generation/reservation anywhere. The #1 gap.

The IRN is user-typed on every invoice. The server only knows the format regex (`invoice_service.py:14,224-237`); nothing computes `INV{n}-{ServiceID}-{YYYYMMDD}`, nothing sequences or reserves it. Local collisions on `(business_id, irn)` are silently absorbed by the idempotent log insert (`invoice_log_routes.py:125-134`), but FIRS collisions fail only at validate/sign — and an unlearned user cannot construct the string at all (it embeds ServiceID). Bonus bug: nothing checks the IRN date segment equals `issue_date`.  
**Add:** `GET /api/invoice/next-irn` deriving max-sequence+1 from `invoice_log` for today, cross-checked against `/invoice/validate-irn` (already exists as a probe, `invoice_routes.py:25-45`), with a regenerate flow on collision.

### R2 — No onboarding readiness; first invoice is a blind wall.

Sign/transmit need user\_secret + certificate + public\_key + supplier profile. The only signal today is `GET /auth/me/secret → {has_secret}` (`auth_routes.py:155-161`); everything else 403s at sign time (`invoice_routes.py:160-170`). Also `GET /auth/me` returns the **full certificate and public\_key strings** (`schema.py:301-305`) — a UI needs booleans, not PKI material on every page load.  
**Add:** readiness endpoint (or booleans on `/me`): `has_secret, has_cert, has_key, profile_complete, missing: [...]` → frontend renders a 4-step checklist and disables sign/transmit until green.

### R3 — Drafts are invisible, unlistable, 8h-only — and there's a security wart.

No list endpoint at all (`session_routes.py:52-155`); resume only by persisted `session_id`. Expiry is a hard 8h from creation, **not extended by activity** (`auth_routes.py:199-240` refreshes the JWT, not the session) — an actively-worked invoice dies mid-entry. **Security:** `GET /sessions/{id}` is unauthenticated and returns the stored `jwt_token` (`session_routes.py:76-83`) — a leaked URL = bearer token; `user_secret` is stored plaintext on the session (`session_routes.py:108`) while `/auth/me/secret` hashes it (`auth_routes.py:149`).  
**Add:** `GET /sessions` (list + expiry), extend expiry on wizard save, drop the token from GET responses, hash the session secret. Fix security in the same ticket as the resume feature.

### R4 — Invoice log is decoupled from transmit; no history, no repeat billing.

Transmit *requires* the log row to pre-exist (`invoice_routes.py:225`) but never creates/updates it (`invoice_routes.py:216-282`) — the frontend must POST log → GET transmit → PATCH transmitted as three separate steps, and any step dying between FIRS success and log write leaves a transmitted-but-unlisted invoice with no recovery path. The log stores no lines, no invoice type, no due date, no customer TIN, no `transmitted_at` (`models.py:84-103`).  
**Add:** transmit creates/updates the log atomically (or returns the payload to upsert), store a lines/wizard snapshot + `invoice_type_code` + `transmitted_at`. This is the shared foundation for history, templates, repeat billing, and credit-note prefill.

### R5 — Supplier profile is dead weight; every wizard re-types it.

`User.tin/party_name/address` exist (`models.py:32-58`) and are editable (`auth_routes.py:185-196`), but `assemble` builds the supplier party purely from wizard keys (`invoice_service.py:66-79`) and validation demands all of them (`invoice_service.py:240-265,401`).  
**Add:** prefill `supplier_*` from the profile when absent. Removes \~10 fields from every invoice.

### R6 — Invoice log view is too narrow; stats bug.

List has search + order only (`invoice_log_routes.py:84-112`). Missing: payment\_status, transmitted, date range, invoice type. **Stats bug:** `revenue` sums `payable_amount` across ALL currencies into one number (`invoice_log_routes.py:24-27`) — the dashboard shows ₦+$+£ as one total.  
**Add:** status/date/transmitted filters; fix the currency-aware revenue calc.

### R7 — Error translation partial and asymmetric.

`NOT_ENABLED` is translated only in transmit (`invoice_routes.py:247-256`); the same failure on validate/sign comes back raw. Upstream 401/403 → generic "FIRS authentication/authorisation failed" with **wrong status 502** (`invoice_routes.py:128-132,199-203,268-272`) — the user reads "server problem" when their cert is dead. Line errors say "Line 2: …" without naming the item (`invoice_service.py:268`).  
**Add:** 401/403 → "your FIRS certificate/credentials are invalid or expired — update in settings"; mirror NOT\_ENABLED across validate/sign/update; name items in line errors.

### R8 — Repeat billing: nothing (and no data source for it).

Items cover "same items" but not "same customer + terms". R4's lines snapshot is the prerequisite. Bonus: with the snapshot, "create credit note from IRN" can prefill `billing_reference` — today users hand-type the original IRN + date (`invoice_service.py:367-394`), the exact fields people get wrong.

### R9 — One account per business; no password reset.

Second user refused with "contact your administrator" — an administrator that doesn't exist (`auth_routes.py:53-63`). Two clerks share one login and one secret. No reset/change-password endpoint; forgotten password + 15-attempt lockout (`rate_limiter.py:62-67`) = permanently locked out. Organizational, but real for growth.

### R10 — Two overlapping lookup surfaces; the UI can get it wrong.

`/lookup/product-codes` + `/service-codes` hit FIRS (`lookup_routes.py:196-221`), return code+description only, 502 on failure. `/lookup/products` + `/services` hit PASCA (`lookup_routes.py:266-381`), support search, return `product_category` — and **silently return \[\] on failure** (`lookup_routes.py:316-322`) with no result-count metadata. A UI that picks the similarly-named `/product-codes` ships every invoice with `category=item-name` via the fallback below.  
**Add:** document/standardize: line creation must use `/products` + `/services` (the only source of `product_category`); surface failures instead of `[]`.

### R11 — Minor but real.

Customer creation has no TIN dedupe (`customer_routes.py:49-62`); throttle message unactionable ("Invoice operation rate limit exceeded", `invoice_routes.py:86-94`; 50/h shared across assemble/sign/transmit); session secret plaintext (see R3).

## Items catalog page — final design (audit-verified)

**Cheap and safe:** a wizard line is a flat dict and `build_invoice_schema` copies line fields straight through (`invoice_service.py:95-147`) — an item is exactly a wizard line minus per-invoice fields, so the frontend merges the item into `step3.lines` with **zero changes to assemble/invoice\_service**. No `item_id` server-side — denormalize fields into the line at selection time.

**Fields (must match wizard line keys 1:1):**

- `name` (required — what the buyer sees on the FIRS invoice), `description`, `sellers_item_identification` (SKU)
- Exactly one of `hsn_code` + **`product_category` (REQUIRED)** or `isic_code` + **`service_category` (REQUIRED)** — without the category, `build_invoice_schema` falls back to `line.get("name")` (`invoice_service.py:99-109`), **silently mislabeling the invoice at FIRS**. Source the category from the `/lookup/products` result, not free text
- `price_amount` (default price, **required &gt; 0** — a priced-later item fails assemble with a line error the clerk can't connect to the catalog), `price_unit` (from units-of-measurement, default "NGN per 1"), `base_quantity` (default 1.0, clamped ≥1)

**Save-time vs invoice-time validation:** save = name required, hsn XOR isic, format regexes (`invoice_service.py:17-18`), category required, price &gt; 0, base\_quantity &gt; 0 — optionally cross-check codes against cached `/lookup/product-codes`/`/service-codes` so dead upstream codes fail in the catalog. Invoice time (unchanged): qty/price &gt; 0, totals consistency.

**Pitfalls:** soft-delete (`is_active`) so deletion never nukes a pending draft; per-business scoping like `Customer`; search name+SKU+description with a product/service kind filter; unique `(business_id, sku)` index; default price is an editable prefill, never a contract.
