FIRS/PASCA e-invoicing is built on the Peppol BIS Billing 3.0 standard using UBL 2.1 XML structure.
Nigeria's PASCA/FIRS staging platform uses 4 main document types: 380 (Credit Note), 381 (Commercial Invoice), 384 (Debit Note), and 385 (Self Billed Invoice).
PASCA's staging API reversed standard labels for 380 (Commercial Invoice in global standard, Credit Note in Nigeria MBS) and 381 (Credit Note in global standard, Commercial Invoice in Nigeria MBS).
Always query GET /api/v1/invoice/resources/invoice-types from the lookup routes to stay aligned with the environment's semantic mappings.
The standard IRN pattern validated successfully by PASCA is INV-{service_id}-{yyyymmdd}. Random suffixes or different segment formats lead to validation/signing rejections.
UUID business_id must remain lowercase during invoice assembly and signing; uppercasing it causes upstream IRN verification failures.
HSN codes for products must strictly use the XXXX.XX format (e.g., 1006.10), and service codes must strictly be 4 digits (e.g., 0112); validating this in the wizard prevents external validation 400 errors.
Recipient enablement checks are performed at transmission; if a recipient is not currently accepting e-invoices, PASCA returns 400 with NOT_ENABLED.
Frontend cookie session-restore endpoint (/sessions/{session_id}) must not require a bearer token to allow authentication state restoration on reload.
Reflex state properties representing dynamic API payloads (assembled/firs_invoice) must accept None/nested types in their annotations (e.g., dict[str, str | int | float | bool | list | dict]) to avoid compile-time exceptions.