Identified and diagnosed 7 backend/external API data-flow mismatches during live staging testing.
Corrected session-restore endpoint to allow anonymous lookup by session ID.
Preserved lowercase business_id uuid format to satisfy external signing template rules.
Mapped generated IRN to exact FIRS/PASCA business templates (INV-{service_id}-{yyyymmdd}).
Added proactive regex validation for HSN and ISIC service categories inside wizard line-save event.
Enhanced error reporting for recipient-readiness failures during invoice transmission.
Widen Reflex type definitions for assembled invoice payloads to support None and list values safely.
Integrated lookups with user-friendly descriptions instead of displaying raw codes first.
Restructured item-selection dropdowns to collapse and clear immediately upon selection.
Refactored supplier section into a read-only profile link card and made customer selection scalable.