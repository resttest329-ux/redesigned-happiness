# Zetamind e-Invoicing Math Guide

This guide documents every calculation used to produce an invoice's monetary totals across the Zetamind stack — the FastAPI backend (`zebe`), the FastHTML wizard frontend (`app/zefe`), and the FIRS/PASCA-authoritative payload assembled at submission time.

The single source of truth for all monetary math lives in `zebe/services/invoice_service.py`. Every other component (wizard previews, dashboards, PDFs) reproduces the **same** formulas using the **same** precedence rules so the user never sees one number on screen and a different number on their FIRS receipt.

---

## 1. Inputs collected per line item

Each line item the user adds in step 3 of the wizard contributes the following numeric fields:

| Field               | Meaning                                                        | Required |
|---------------------|----------------------------------------------------------------|----------|
| `invoiced_quantity` | Quantity of the item being invoiced (must be > 0)              | Yes      |
| `price_amount`      | Unit price in the document currency (≥ 0)                      | Yes      |
| `base_quantity`     | Reference quantity that the unit price applies to              | Yes (default 1) |
| `discount_rate`     | Percentage discount (0–100), applied to the line base          | Optional |
| `discount_amount`   | Flat-currency discount applied to the line base                | Optional |
| `fee_rate`          | Percentage fee (0–100) applied on top of the line base         | Optional |
| `fee_amount`        | Flat-currency fee added on top of the line base                | Optional |

`base_quantity` and `price_unit` are descriptive fields used to format the invoice; they do **not** alter the per-line math below.

---

## 2. Per-line formula

For a single line, the adjusted line extension amount is computed as:


base            = invoiced_quantity * price_amount

discount        = discount_amount                if discount_amount is set and ≠ 0
                  else base * (discount_rate / 100)

fee             = fee_amount                     if fee_amount is set and ≠ 0
                  else base * (fee_rate / 100)

line_extension  = base − discount + fee


### Precedence rules

- **Flat overrides percentage.** If both `discount_amount` and `discount_rate` are provided, the flat amount wins. The same applies to fees.
- **Empty / zero is treated as "not set".** Blank inputs and `0` are equivalent — they cause the percentage rate to be used (or, if the rate is also zero, the adjustment is `0`).
- **Discounts and fees are independent.** A line may have a discount only, a fee only, both, or neither. Each line carries its own `discount_*` and `fee_*` fields, so customisations on one line never bleed into another.
- **Order of operations is fixed.** `discount` is always subtracted from `base` before `fee` is added. The user does not need to compute this — the system does.

### Worked examples

| Qty | Price | Discount        | Fee            | base   | discount | fee    | line_extension |
|-----|-------|-----------------|----------------|--------|----------|--------|----------------|
| 2   | 100   | —               | —              | 200.00 | 0.00     | 0.00   | **200.00**     |
| 3   | 250   | 10 %            | —              | 750.00 | 75.00    | 0.00   | **675.00**     |
| 4   | 120   | flat 30 (rate 20% ignored) | —    | 480.00 | 30.00    | 0.00   | **450.00**     |
| 5   | 80    | —               | 12.5 %         | 400.00 | 0.00     | 50.00  | **450.00**     |
| 7   | 50    | —               | flat 22.75 (rate 10% ignored) | 350.00 | 0.00 | 22.75 | **372.75** |
| 1.5 | 1000  | flat 125.50     | flat 19.99     | 1500.00| 125.50   | 19.99  | **1394.49**    |
| 2.25| 333.33| 5.5 %           | 2.25 %         | 749.9425 | 41.246838 | 16.873706 | **725.617... ** |

---

## 3. Invoice-level aggregation

Once every line has its `line_extension`, the invoice totals are:


subtotal                = Σ line_extension                  (a.k.a. tax_exclusive_amount)
VAT (tax_amount)        = subtotal * 0.075                   (7.5 % FIRS standard rate)
tax_inclusive_amount    = subtotal + tax_amount
payable_amount          = subtotal + tax_amount              (= tax_inclusive_amount)


VAT is computed on the **adjusted** subtotal — i.e. *after* per-line discounts and fees, not on the raw `quantity * price` total. This matches the FIRS/PASCA Peppol BIS Billing 3.0 rules and the formula in `zebe/services/invoice_service.py::compute_totals`.

### Multi-line example

Using the seven rows from the table above:


subtotal              = 200.00 + 675.00 + 450.00 + 450.00 + 372.75 + 1394.49 + 725.617744
                      = 4267.857744

VAT (7.5 %)           = 4267.857744 * 0.075
                      = 320.0893308

payable_amount        = 4267.857744 + 320.0893308
                      = 4587.9470745


The wizard's step-3 totals card and the FIRS-authoritative payload assembled in step 4 both produce these same numbers.

---

## 4. Display vs. authoritative numbers

The Zetamind stack draws a clear line between **what is shown** and **what is sent to FIRS**:

| Where                                            | Source                                                                                       | Authority         |
|--------------------------------------------------|----------------------------------------------------------------------------------------------|-------------------|
| Wizard step 3 — per-line "Subtotal" column        | `_line_extension(line)` in `app/zefe/routes/wizard_routes.py`                                | Display-only      |
| Wizard step 3 — Subtotal / VAT / Total card       | `Σ _line_extension`, `* 7.5 %`, sum                                                          | Display-only      |
| Wizard step 4 — invoice summary card              | Backend-computed `wizard["computed"]` returned from `POST /invoice/assemble`                 | **Authoritative** |
| Signed UBL 2.1 invoice payload                    | `build_invoice_schema(...)` + `compute_totals(...)` in `zebe/services/invoice_service.py`    | **Authoritative** |
| Invoice detail page / PDF / dashboard             | `GET /invoice/get-invoice/{irn}` (returned by FIRS) or local `invoice_log` row               | **Authoritative** |

**Display formulas mirror authoritative formulas exactly.** The wizard does its own math purely so the user sees instant feedback as they edit a row. When the user clicks "Continue" on step 3, the wizard POSTs its full state to `/invoice/assemble`, and from that moment onward every total shown is the backend's value. If the two ever disagreed, the backend value wins.

---

## 5. Rounding behaviour

- Internal computation uses native Python `float` (IEEE-754 double precision). No intermediate rounding is performed.
- Currency amounts are formatted for display with `:.2f` (two decimal places). The unrounded value is what is sent to FIRS — the rounding only affects what the user sees.
- The 7.5 % VAT rate is treated as exact `0.075`, not a banker's-rounded approximation.
- Quantities accept fractional values (e.g. `1.5`, `2.25`) — useful for hours, kilograms, etc.

---

## 6. Validation guardrails

The wizard refuses to advance a line whose numeric inputs are out of range, so totals can never be polluted by impossible values:

- `invoiced_quantity` must be `> 0`
- `base_quantity` must be `> 0`
- `price_amount` must be `≥ 0`
- `discount_rate` and `fee_rate` must be in `[0, 100]`
- `discount_amount` and `fee_amount` must be `≥ 0`

Lines without an HS code (product) **or** ISIC code (service) are also blocked — without a classification code FIRS cannot validate the line, regardless of how clean the math is.

---

## 7. FIRS schema mapping

When `build_invoice_schema(...)` produces the UBL 2.1 payload, the per-line and invoice-level numbers map to:


invoice_line[i].line_extension_amount     ← line_extension(line i)
legal_monetary_total.line_extension_amount ← subtotal
legal_monetary_total.tax_exclusive_amount  ← subtotal
legal_monetary_total.tax_inclusive_amount  ← subtotal + VAT
legal_monetary_total.payable_amount        ← subtotal + VAT

tax_total[0].tax_amount                    ← VAT
tax_total[0].tax_subtotal[0].taxable_amount← subtotal
tax_total[0].tax_subtotal[0].tax_amount    ← VAT
tax_total[0].tax_subtotal[0].tax_category  ← { id: "STANDARD_VAT", percent: 7.5 }


The discount/fee values themselves are also persisted on each `invoice_line` (`discount_rate`, `discount_amount`, `fee_rate`, `fee_amount`) so the FIRS receipt records *how* each line extension was reached, not just the final number.

---

## 8. Quick reference


Per line:
    base           = quantity * price
    discount       = discount_amount  if nonzero else base * discount_rate / 100
    fee            = fee_amount       if nonzero else base * fee_rate    / 100
    line_extension = base - discount + fee

Per invoice:
    subtotal = Σ line_extension
    vat      = subtotal * 0.075
    payable  = subtotal + vat


If anything in the wizard, the PDF, or the dashboard ever disagrees with this guide, the bug is in the *display* — the backend computation in `zebe/services/invoice_service.py` is the canonical reference.
