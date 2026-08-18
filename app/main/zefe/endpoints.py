from __future__ import annotations


AUTH_TOKEN = "/api/auth/token"
AUTH_REGISTER = "/api/auth/register"
AUTH_ME = "/api/auth/me"
AUTH_ME_SECRET = "/api/auth/me/secret"
AUTH_ME_PROFILE = "/api/auth/me/profile"
AUTH_ME_CERT_KEY = "/api/auth/me/cert-key"
AUTH_REFRESH = "/api/auth/refresh"


SESSIONS = "/api/sessions"
SESSIONS_BY_ID = "/api/sessions/{session_id}"
SESSIONS_TOKEN = "/api/sessions/{session_id}/token"
SESSIONS_SECRET = "/api/sessions/{session_id}/secret"
SESSIONS_WIZARD = "/api/sessions/{session_id}/wizard"


CUSTOMERS = "/api/customers"
CUSTOMERS_BY_ID = "/api/customers/{cid}"
CUSTOMERS_RESTORE = "/api/customers/{cid}/restore"
CUSTOMERS_BULK_DELETE = "/api/customers/bulk-delete"
CUSTOMERS_BULK_ACTIVATE = "/api/customers/bulk-activate"
CUSTOMERS_IMPORT = "/api/customers/import"
CUSTOMERS_EXPORT = "/api/customers/export"


INVOICE_LOG = "/api/invoice-log"
INVOICE_LOG_STATS = "/api/invoice-log/stats"
INVOICE_LOG_BY_IRN = "/api/invoice-log/{irn}"
INVOICE_LOG_TRANSMITTED = "/api/invoice-log/{irn}/transmitted"
INVOICE_LOG_STATUS = "/api/invoice-log/{irn}/status"


INVOICE_GET = "/api/invoice/get-invoice/{irn}"
INVOICE_QR = "/api/invoice/{irn}/qr"
INVOICE_TRANSMIT = "/api/invoice/transmit-invoice/{irn}"
INVOICE_UPDATE = "/api/invoice/update-invoice/{irn}"
INVOICE_ASSEMBLE = "/api/invoice/assemble"
INVOICE_VALIDATE = "/api/invoice/validate-invoice"
INVOICE_SIGN = "/api/invoice/sign-invoice"


LOOKUP_INVOICE_TYPES = "/api/lookup/types-of-invoice"
LOOKUP_PAYMENT_MEANS = "/api/lookup/payment-means"
LOOKUP_CURRENCIES = "/api/lookup/get-currency"
LOOKUP_TAX_CATEGORIES = "/api/lookup/tax-categories"
LOOKUP_STATE_CODES = "/api/lookup/state-codes"
LOOKUP_LGA_CODES = "/api/lookup/lga-codes"
LOOKUP_COUNTRIES = "/api/lookup/countries"
LOOKUP_UNITS = "/api/lookup/units-of-measurement"
LOOKUP_UNIT_CODES = "/api/lookup/unit-codes"
LOOKUP_PRODUCTS = "/api/lookup/products"
LOOKUP_SERVICES = "/api/lookup/services"


ITEMS = "/api/items"
ITEMS_BY_ID = "/api/items/{item_id}"
ITEMS_BULK_DELETE = "/api/items/bulk-delete"
ITEMS_BULK_ACTIVATE = "/api/items/bulk-activate"
ITEMS_IMPORT = "/api/items/import"
