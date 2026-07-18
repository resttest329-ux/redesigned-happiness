# Zetamind e-Invoicing (Zefe + Zebe) Architecture Guide

Welcome to the developer and engineering architecture guide for the Zetamind e-invoicing system. This document outlines the distinct responsibilities of the FastHTML frontend (`zefe`) and the FastAPI backend (`zebe`), their runtime flow, data model, session management, configuration, run order, and troubleshooting protocols.

## 1. System Topology & Responsibilities

The Zetamind e-Invoicing suite is structured as a decoupled architecture consisting of a lightweight standalone frontend and a robust stateless API backend.

### stand-alone Frontend: `zefe` (FastHTML)
- **Core Stack**: FastHTML (FastAPI + ASGI + Starlette), HTMX, TailwindCSS, ReportLab.
- **Presentation**: Renders print-ready, pixel-perfect document visuals and native dynamic components via HTMX without SPA framework dependencies.
- **PDF Assembly**: Generates client-facing, print-friendly PDFs on the fly using `ReportLab` based strictly on the structured, authoritative JSON received from the backend API.
- **Session State Cache**: Manages secure HTTP-only session cookies and caches essential JWT tokens locally inside an memory cache (using Thread/Request scoped ContextVars) to prevent redundant upstream lookups.

### API Backend: `zebe` (FastAPI)
- **Core Stack**: FastAPI, SQLAlchemy ORM, SQLite/PostgreSQL, JWT.
- **UBL 2.1 Assembly**: Implements the complex Peppol BIS Billing 3.0 / Nigerian MBS specifications. Translates basic flat wizard variables into compliant nested XML/JSON schemas.
- **Cryptographic Operations**: Signs the finalized document payload using the user's business certificate and public key.
- **Upstream FIRS Gateway Integrator**: Acts as the single conduit communicating directly with the Federal Inland Revenue Service (FIRS) / PASCA staging and production gateways for IRN verification, validation, and real-time transmission.
- **Stateless Persistence**: Maintains the local customer registry and the localized audit log of signed/transmitted invoices.

---

## 2. Runtime Flow & Lifecycle

### Authentication & Session Model
1. The user logs in via `zefe` `/login` by submitting credentials.
2. `zefe` requests an access token from `zebe` `/auth/token` via OAuth2 password grant.
3. Upon verification, `zebe` returns a JWT bearer token.
4. `zefe` initiates a server-managed browser session by posting to `zebe` `/sessions` with the JWT. `zebe` generates a secure `session_id` and persists the session details with an 8-hour expiry.
5. `zefe` sets the `zefe_session_id` cookie on the client's browser (HTTP-only, Secure, SameSite=Lax).
6. On subsequent requests, `zefe` intercepts the cookie, loads the session details, and uses the corresponding JWT to authenticate downstream requests.

### Invoice Document Lifecycle
1. **Step 1 (Header)**: The user initiates a new invoice draft. The system generates a compliant FIRS IRN matching the pattern `INV{sequence}-{service_id}-{yyyymmdd}`.
2. **Step 2 (Parties)**: The user selects or inputs supplier and customer information. Both parties must contain valid TIN formats (`NNNNNNNN-NNNN`) and complete physical/postal addresses.
3. **Step 3 (Line items)**: The user selects products or services. Every line item is strictly validated for mutual exclusivity (each line is either a product containing an HSN code or a service containing an ISIC code).
4. **Step 4 (Assembly & Validation)**: `zefe` invokes `/invoice/assemble` on the backend, which computes subtotals, VAT (7.5%), and total payable amounts. The resulting UBL 2.1 JSON schema is passed to `/invoice/validate-invoice` to verify FIRS conformity.
5. **Signing**: The user submits their signing secret. The backend validates the secret, loads the business's PKI credentials (certificate + public key), signs the invoice hash, and registers the local log entry as `PENDING`.
6. **Transmission**: The signed invoice is sent to `/invoice/transmit-invoice/{irn}`. On success, the local status is marked as transmitted. If the recipient is not enabled, the system handles the 400 error gracefully, returning actionable warnings.

---

## 3. Configuration & Local Run Order

### Backend (`zebe`) Environment Variables (.env)
bash
JWT_SECRET_KEY="your-jwt-secret-key"
ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_IN_MINUTES=480
API_KEY="your-pasca-api-key"
CLIENT_SECRET="your-pasca-client-secret"
PASCA_BASE_URL="https://test-api.pasca.co"
BASE_URL="https://eivc-k6z6d.ondigitalocean.app"


### Standalone Frontend (`zefe`) Environment Variables (.env)
bash
BACKEND_URL="http://127.0.0.1:8000"
SESSION_SECRET="your-browser-session-secret"
PORT=5000
HOST="0.0.0.0"


### Local Start Order
1. **Step 1: Install Dependencies**
   Ensure you have installed packages for both systems using `pip install -r requirements.txt`.
2. **Step 2: Database Setup & Seed (Zebe)**
   Run the backend seeder to apply migrations and inject default users and customers:
   bash
   cd zebe
   python seed.py
   
   The FastAPI development server will start automatically on `http://127.0.0.1:8000`.
3. **Step 3: Launch Standalone Frontend (Zefe)**
   Open a new terminal session and run the FastHTML application:
   bash
   cd app/zefe
   python main.py
   
   Access the user interface at `http://127.0.0.1:5000`.

---

## 4. Troubleshooting & Self-Healing

- **Duplicate IRN Error (400 Bad Request)**:
  Occurs if the generated IRN has already been used on the FIRS gateway. The system auto-heals by scanning the local database for the highest sequence number and advancing the `INV{seq}` prefix to the next increment.
- **Recipient Not Enabled (NOT_ENABLED)**:
  Occurs during transmission if the customer has not enabled receiving capabilities. The frontend captures this error code and presents an actionable message instead of crashing with a 500 error.
- **PKI Signature Failures**:
  Ensure your certificate and public keys are pasted fully including headers (`-----BEGIN CERTIFICATE-----` / `-----END CERTIFICATE-----`). Double check that your `business_id` is passed as a strictly **lowercase** UUID.
