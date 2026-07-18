# Zetamind e-Invoicing Backend API Reference (`zebe`)

This reference document catalogs the backend endpoints exposed by the `zebe` API, their purpose, integration patterns, expected inputs, and standard outputs.

---

## 1. Authentication (`/auth`)

### `POST /auth/register`
- **Purpose**: Registers a new business workspace.
- **How Zefe Uses It**: Invoked when a new user signs up.
- **Input**: JSON payload containing `username` (display name), `email` (login identifier), `password` (minimum 8 characters), `business_id` (lowercase UUID), `service_id` (8-character template identifier), and optionally `certificate` and `public_key`.
- **Output**: JSON representation of the created user (excluding password) containing the assigned database `id`.

### `POST /auth/token`
- **Purpose**: Authenticates credentials and issues access tokens.
- **How Zefe Uses It**: Processes the login form.
- **Input**: Form-encoded `username` (email) and `password`.
- **Output**: JWT bearer token string and token type (`{"access_token": "...", "token_type": "bearer"}`).

### `GET /auth/me`
- **Purpose**: Returns the authenticated user's workspace parameters.
- **How Zefe Uses It**: Restores user context and profile settings.
- **Input**: Bearer token in the `Authorization` header.
- **Output**: Profile details including current workspace ID, Service ID, business address details, and PKI configuration.

### `PATCH /auth/me/secret`
- **Purpose**: Updates the user's secure signing secret.
- **How Zefe Uses It**: Invoked when a user sets or updates their local key verification phrase.
- **Input**: JSON `{"user_secret": "..."}`.
- **Output**: Success status `{"ok": true}`.

### `GET /auth/me/secret`
- **Purpose**: Checks if a signing secret has been set.
- **How Zefe Uses It**: Conditionally shows configuration checklists on the dashboard.
- **Input**: Bearer token.
- **Output**: Boolean state wrapper `{"has_secret": true/false}`.

### `PATCH /auth/me/cert-key`
- **Purpose**: Saves cryptographic public keys and certificates.
- **How Zefe Uses It**: Configures the PKI tab in settings.
- **Input**: JSON body containing PEM-formatted `certificate` and/or `public_key` strings.
- **Output**: Success status `{"ok": true}`.

### `PATCH /auth/me/profile`
- **Purpose**: Updates business address details.
- **How Zefe Uses It**: Saves Supplier Profile fields in Settings.
- **Input**: JSON containing address properties (`street_name`, `city_name`, `state`, `country`, `postal_zone`, `lga`).
- **Output**: Success status `{"ok": true}`.

### `POST /auth/refresh`
- **Purpose**: Refreshes expired JWT tokens anonymously via session ID.
- **How Zefe Uses It**: Automatic token renewal behind the scenes.
- **Input**: JSON containing `session_id`.
- **Output**: Fresh access token `{"access_token": "...", "token_type": "bearer"}`.

---

## 2. Sessions (`/sessions`)

### `POST /sessions`
- **Purpose**: Creates an active browser session mapping a JWT token.
- **How Zefe Uses It**: Sets up the browser context upon login.
- **Input**: JSON containing `jwt_token`, `business_id`, `username`, and `user_id`.
- **Output**: Secure alphanumeric token `{"session_id": "..."}`.

### `GET /sessions/{session_id}`
- **Purpose**: Restores active session parameters.
- **How Zefe Uses It**: Validates the session on browser refresh.
- **Input**: Session identifier path parameter.
- **Output**: Complete session state containing `jwt_token`, expiry timestamps, and saved wizard progress JSON.

### `DELETE /sessions/{session_id}`
- **Purpose**: Destroys the browser session.
- **How Zefe Uses It**: Triggered on Logout.
- **Input**: Session identifier path parameter.
- **Output**: Success status `{"ok": true}`.

---

## 3. Customers (`/customers`)

### `GET /customers`
- **Purpose**: Queries the workspace customer directory.
- **How Zefe Uses It**: Populates customer listings, lookup bars, and wizard dropdowns.
- **Input**: Optional query parameters `search` (keyword filter), `offset`, and `limit`.
- **Output**: Paginated wrapper containing total matches and an item array.

### `POST /customers`
- **Purpose**: Registers a new customer workspace profile.
- **How Zefe Uses It**: Saves customers via the directory modal or the inline wizard checkbox.
- **Input**: JSON object containing company name, email, TIN, telephone, and postal address fields.
- **Output**: Created database record with unique customer `id`.

### `GET /customers/{id}`
- **Purpose**: Loads a single customer record.
- **How Zefe Uses It**: Prefills customer edit forms.
- **Input**: Customer database identifier path parameter.
- **Output**: Customer details containing TIN, company address, and contact numbers.

### `DELETE /customers/{id}`
- **Purpose**: Removes a customer from the directory.
- **How Zefe Uses It**: Removes customers individually or via bulk check selection.
- **Input**: Path identifier.
- **Output**: Success status `{"ok": true}`.

---

## 4. Invoice Log (`/invoice-log`)

### `GET /invoice-log/stats`
- **Purpose**: Computes business revenue statistics.
- **How Zefe Uses It**: Renders metric charts and key metric badges on the dashboard.
- **Input**: Bearer token.
- **Output**: Aggregated figures for total count, revenue sum, paid count, pending count, and rejected count.

### `GET /invoice-log`
- **Purpose**: Queries the audit trail of generated invoices.
- **How Zefe Uses It**: Feeds the paginated invoice search table.
- **Input**: Query parameters `search`, `limit`, `offset`, and sorting direction.
- **Output**: Paginated list of logged items containing payment statuses and transmission flags.

### `POST /invoice-log`
- **Purpose**: Inserts a new record into the invoice log.
- **How Zefe Uses It**: Called automatically after a successful signature step to create an audit record.
- **Input**: JSON with `irn`, `issue_date`, `customer_name`, `payable_amount`, and `payment_status`.
- **Output**: Created invoice log database record.

---

## 5. Invoices (`/invoice`)

### `POST /invoice/validate-irn`
- **Purpose**: Verifies that the IRN is legally linked to the business template.
- **How Zefe Uses It**: Intercepts IRN inputs during Step 1 of the wizard.
- **Input**: JSON with `irn` and `business_id`.
- **Output**: Validation confirmation message.

### `POST /invoice/assemble`
- **Purpose**: Compiles wizard drafts into structured schemas and calculates totals.
- **How Zefe Uses It**: Invoked automatically when continuing from Step 3 of the wizard.
- **Input**: Flat wizard dictionary representing steps 1, 2, and 3.
- **Output**: Fully compiled UBL 2.1 schema JSON alongside calculated monetary subtotals and standard VAT fields.

### `POST /invoice/validate-invoice`
- **Purpose**: Validates schema compliance against FIRS rules.
- **How Zefe Uses It**: Step 4 validation check.
- **Input**: Compiled UBL 2.1 schema JSON.
- **Output**: Success message or 400 Bad Request with validation errors.

### `POST /invoice/sign-invoice`
- **Purpose**: Signs the assembled payload.
- **How Zefe Uses It**: Generates the final legal digital signature.
- **Input**: Compiled UBL 2.1 schema JSON with user-secret passed in headers.
- **Output**: Confirmation message on successful signature generation.

### `GET /invoice/transmit-invoice/{irn}`
- **Purpose**: Transmits the signed XML payload to the FIRS platform.
- **How Zefe Uses It**: Triggers final submission.
- **Input**: Invoice reference number path parameter.
- **Output**: Confirmation message or 400 Bad Request with recipient enablement indicators.

---

## 6. Lookups (`/lookup`)

### `GET /lookup/types-of-invoice`
- **Purpose**: Returns valid document types.
- **How Zefe Uses It**: Step 1 document classification selection.
- **Output**: Core codes matching FIRS-compliant classifications (`380` - Credit, `381` - Commercial, `384` - Debit, `385` - Self-Billed).

### `GET /lookup/products` / `GET /lookup/services`
- **Purpose**: Performs a keyword search on FIRS classifications.
- **How Zefe Uses It**: Search and autocomplete inside the wizard.
- **Input**: Query parameters `search` (keyword term) and `length`.
- **Output**: Matching reference items containing HSN codes (for products) or ISIC codes (for services).
