# Zetamind e-Invoicing Support & Onboarding Manual

Welcome to your onboarding manual for the Zetamind e-invoicing platform. This guide will walk you through setting up your business account, managing your customer database, and building, validating, signing, and transmitting legally compliant e-invoices.

---

## 1. Getting Started & Setup Checklist

When logging into your workspace for the first time, complete the setup checklist displayed on your dashboard to unlock all invoicing capabilities:

1. **Complete Your Profile**: Fill in your legal business name, registered Tax Identification Number (TIN), telephone, and street address. These details appear as the Supplier on all generated invoices.
2. **Configure FIRS PKI Credentials**: Paste the cryptographic certificate and public key issued to your business by FIRS. These credentials are used to sign and lock your documents.
3. **Set a Signing Secret**: Configure a secure passcode. You will be prompted to enter this passcode every time you sign an invoice or update a payment status.

---

## 2. Setting Up Your Profile, Credentials, & Secret

Navigate to the **Settings** section from the sidebar navigation to configure these parameters:

- **Profile Tab**: Provide your company details. Your TIN must strictly adhere to the FIRS format `NNNNNNNN-NNNN` (e.g., `12345678-0001`). For Nigerian addresses, select your state from the dropdown. For international suppliers, choose your country to activate free-form text region inputs.
- **FIRS Credentials Tab**: Paste your PEM-encoded Certificate and Public Key. Ensure you include the full headers and footers (e.g. `-----BEGIN CERTIFICATE-----` and `-----END CERTIFICATE-----`). Click "Reveal Certificate/Key" to inspect configured values.
- **Signing Secret Tab**: Type a memorable passcode and confirm it. This secret acts as a digital authorization key and remains completely private to your device.

---

## 3. Customer Directory Management

Manage your customer list in the **Customers** section before initiating an invoice:

- **Adding Customers**: Click "Add Customer" to open the registration form. Fill in their TIN (using the FIRS format `NNNNNNNN-NNNN`), registered email, phone, and complete physical address. Saving customers here saves time during the invoice wizard process.
- **Clickable Row Editing**: Select any customer row in the directory to modify their details directly.
- **Bulk Operations**: Select the checkboxes on the left side of multiple rows to activate the bulk action bar, allowing you to delete multiple records safely.

---

## 4. Creating Invoices with the Guided Wizard

Click **New Invoice** in the sidebar navigation to start the guided, four-step invoice builder:

### Step 1: Header Details
- The invoice reference number (IRN) is generated automatically. To edit it, click "Edit" and ensure it matches the FIRS standard `INV{seq}-{your_service_id}-{date}`.
- Choose your invoice type (e.g., Commercial Invoice, Credit Note). Note that Credit Notes, Debit Notes, and Self-Billed invoices require an original invoice's IRN and date as a reference in the Billing Reference field.

### Step 2: Selecting Parties
- Your supplier details are loaded automatically.
- To select a customer, type their name in the customer search bar. Selecting a customer populates their details automatically and displays a clean summary card. To enter customer details manually for a one-off invoice, click "Choose different" to clear the search bar.

### Step 3: Line Items & Live Product Lookup
- Click "Add Line Item" to open the item drawer.
- Use the **Item Lookup** search bar to find matching classifications (e.g., searching for "computer" or "consulting"). Selecting a result automatically attaches the correct HSN code (for products) or ISIC code (for services) and defaults the unit descriptors and tax categories.
- Enter the quantity and rate, then click "Add line". Subtotals, VAT (7.5%), and final payable amounts are calculated automatically.

### Step 4: Validate, Sign, and Transmit
- **Validate**: Click "Validate now" to verify your draft matches the FIRS schema rules.
- **Sign**: Once validated, enter your Signing Secret to authorize and sign the document. This step generates a compliant audit trail entry locally.
- **Transmit**: Click "Transmit to FIRS" to submit your document. The system handles duplicate errors and recipient-readiness issues gracefully.
- **Finish**: Click "Finish & view invoice" to access your final document.

---

## 5. Post-Transmission Actions

- **Download PDF**: Click "Download PDF" to save or print a beautifully structured, print-ready document containing your business branding, line details, and payment summaries.
- **Scan and Verify QR Code**: Every signed invoice features a generated QR code representing the IRN, payable sum, and issue date. Scan this code with any mobile device to verify document authenticity.
- **Update Payment Status**: If a client pays a balance partially or in full, navigate to the invoice, select the updated status (e.g., `PAID` or `PARTIAL`), enter your signing secret, and submit. This updates the FIRS registry and your local audit trail in real time.

---

## 6. Common Errors & Support Escalation

- **Error: "Recipient is not currently accepting e-invoices"**:
  The customer's workspace has not activated receiving capabilities with FIRS. Ask your client to enable receiving, then click "Transmit" again.
- **Error: "TIN must be in the FIRS format"**:
  Ensure the Tax Identification Number is exactly 12 digits divided by a hyphen after the eighth digit (`NNNNNNNN-NNNN`).
- **Error: "Invalid user secret"**:
  Your updated status or signature passcode does not match your configured secret. Verify your passcode or reset it under Settings → Signing Secret.
- **Support Escalation**:
  If you encounter issues during validation or transmission, take a screenshot of the error, note down the Invoice Reference Number (IRN), and email our technical support desk at `support@zetamind.com` for assistance.
