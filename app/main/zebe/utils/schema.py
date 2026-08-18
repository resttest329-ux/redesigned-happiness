import re
from enum import Enum
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)
from typing import Optional
from datetime import datetime

from services.invoice_service import (
    DEFAULT_UNIT_CODE,
    TAX_CURRENCY_CODE,
    validate_unit_code,
)


TIN_PATTERN = re.compile(r"^\d{8}-\d{4}$")
HSN_PATTERN = re.compile(r"^\d{4}\.\d{2}$")
ISIC_PATTERN = re.compile(r"^\d{4}$")


def validate_tin(value: Optional[str]) -> Optional[str]:
    if value is None or value == "":
        return value
    if not TIN_PATTERN.match(value):
        raise ValueError(
            "TIN must be in the FIRS format NNNNNNNN-NNNN (e.g. 12345678-0001)."
        )
    return value


#: NRS `invoice_kind` values. Derived server-side, never a user input.
VALID_INVOICE_KINDS = {"B2B", "B2C", "B2G"}


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REJECTED = "REJECTED"
    PARTIAL = "PARTIAL"


class InvoiceUpdatePaymentStatus(str, Enum):
    PAID = "PAID"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"


class InvoiceTypes(BaseModel):
    code: str
    value: str


class PaymentMeans(BaseModel):
    code: str
    value: str


class TaxCategoryLookUp(BaseModel):
    code: str
    value: str


class Currency(BaseModel):
    symbol: str
    name: str
    symbol_native: str
    decimal_digits: int
    rounding: float
    code: str
    name_plural: str


class ProductCodes(BaseModel):
    hscode: str
    description: str


class ServiceCode(BaseModel):
    description: str
    code: str


class ProductSearchItem(BaseModel):
    hscode: str
    description: str
    product_category: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class ServiceSearchItem(BaseModel):
    code: str
    description: str

    model_config = ConfigDict(extra="ignore")


class UnitOfMeasurement(BaseModel):
    name: str
    code: str

    model_config = ConfigDict(extra="ignore")


class LocalGovernment(BaseModel):
    name: str
    code: str
    state_code: str


class StateCode(BaseModel):
    name: str
    code: str


class Country(BaseModel):
    name: str
    alpha_2: str
    alpha_3: str
    country_code: str
    iso_3166_2: str
    region: str
    sub_region: str
    intermediate_region: str
    region_code: str
    sub_region_code: str
    intermediate_region_code: str


class ValidateIRNSchema(BaseModel):
    irn: str
    business_id: str

    _uppercase_irn = field_validator("irn")(lambda v: v.upper() if v else v)
    _uppercase_business_id = field_validator("business_id")(
        lambda v: v.upper() if v else v
    )


class PostalAddress(BaseModel):
    street_name: str
    city_name: str
    postal_zone: str
    country: str
    state: str
    #: Stored locally on the profile / customer record, but optional on the
    #: wire — blanks are normalized away rather than sent as empty strings.
    lga: Optional[str] = None

    @field_validator("lga", mode="before")
    @classmethod
    def _blank_lga_to_none(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        return s or None


class AccountingParty(BaseModel):
    tin: str
    email: EmailStr
    telephone: str
    party_name: str
    postal_address: PostalAddress

    _validate_tin = field_validator("tin")(validate_tin)


class BillingReference(BaseModel):
    irn: str
    issue_date: str


class TaxScheme(BaseModel):
    id: str


class TaxCategory(BaseModel):
    id: str
    percent: float
    tax_scheme: Optional[TaxScheme] = None


class TaxSubtotal(BaseModel):
    tax_category: TaxCategory
    tax_amount: float
    taxable_amount: float


class TaxTotal(BaseModel):
    tax_amount: float
    tax_subtotal: list[TaxSubtotal]


class LegalMonetaryTotal(BaseModel):
    line_extension_amount: float
    tax_exclusive_amount: float
    tax_inclusive_amount: float
    payable_amount: float


class Item(BaseModel):
    name: str
    description: Optional[str] = None
    sellers_item_identification: Optional[str] = None


class Price(BaseModel):
    price_amount: float
    base_quantity: float
    price_unit: str = DEFAULT_UNIT_CODE

    _validate_price_unit = field_validator("price_unit")(validate_unit_code)


class PaymentMeansItem(BaseModel):
    payment_means_code: str
    payment_due_date: Optional[str] = None


class InvoiceLine(BaseModel):
    item: Item
    price: Price
    hsn_code: Optional[str] = None
    product_category: Optional[str] = None
    invoiced_quantity: float
    line_extension_amount: float
    discount_rate: Optional[float] = None
    discount_amount: Optional[float] = None
    fee_rate: Optional[float] = None
    fee_amount: Optional[float] = None
    isic_code: Optional[str] = None
    service_category: Optional[str] = None


class InvoiceSchema(BaseModel):
    """Outbound FIRS/PASCA invoice payload.

    Serialization contract: routes send
    ``model_dump(exclude_none=True, by_alias=True)``. Every field's external
    name is its snake_case field name — including the tax currency, which the
    live PASCA sandbox only accepts as ``tax_currency_code`` (the camelCase
    ``taxCurrencyCode`` spelling was rejected with
    ``invoicerequest.invoice.taxcurrencycode is required`` even when present).
    No field on this model declares an alias, so ``by_alias=True`` is a no-op
    kept for consistency across the outbound serialization helpers.
    ``populate_by_name`` keeps the Python-side snake_case ergonomics when
    constructing the model.
    """

    model_config = ConfigDict(populate_by_name=True)

    irn: str
    business_id: str
    #: Derived from the customer identity (B2B when a customer TIN exists).
    invoice_kind: str = "B2B"
    issue_date: str
    issue_time: Optional[str] = None
    due_date: Optional[str] = None
    #: Derived from issue_date (Peppol BT-7 / NRS tax_point_date).
    tax_point_date: Optional[str] = None
    #: Always PENDING at creation; later transitions use the status endpoint.
    payment_status: Optional[str] = PaymentStatus.PENDING.value
    invoice_type_code: str
    document_currency_code: str
    #: Required by PASCA on every invoice (``invoice.taxcurrencycode``) and
    #: sent snake_case on the wire as ``tax_currency_code``. Derived — never a
    #: user input.
    tax_currency_code: str = TAX_CURRENCY_CODE
    billing_reference: Optional[list[BillingReference]] = None
    payment_means: Optional[list[PaymentMeansItem]] = None

    accounting_customer_party: AccountingParty
    accounting_supplier_party: AccountingParty

    tax_total: list[TaxTotal]
    legal_monetary_total: LegalMonetaryTotal
    invoice_line: list[InvoiceLine]

    @field_validator("tax_currency_code", mode="before")
    @classmethod
    def _validate_tax_currency_code(cls, v):
        raw = str(v or "").strip().upper()
        return raw or TAX_CURRENCY_CODE

    @field_validator("invoice_kind", mode="before")
    @classmethod
    def _validate_invoice_kind(cls, v):
        raw = str(v or "").strip().upper() or "B2B"
        if raw not in VALID_INVOICE_KINDS:
            raise ValueError(
                "invoice_kind must be one of: "
                f"{', '.join(sorted(VALID_INVOICE_KINDS))}."
            )
        return raw

    @field_validator("payment_status", mode="before")
    @classmethod
    def _validate_initial_payment_status(cls, v):
        if v is None or str(v).strip() == "":
            return PaymentStatus.PENDING.value
        raw = str(v).strip().upper()
        if raw not in {s.value for s in PaymentStatus}:
            raise ValueError(
                "payment_status must be one of: "
                f"{', '.join(s.value for s in PaymentStatus)}."
            )
        return raw

    @field_validator("business_id")
    @classmethod
    def _preserve_business_id(cls, v: str) -> str:
        # business_id must be passed through byte-exact (FIRS templates are
        # registered against the lowercase UUID) — only strip whitespace.
        return (v or "").strip()


class UpdateInvoiceSchema(BaseModel):
    payment_status: Optional[InvoiceUpdatePaymentStatus] = None
    reference: Optional[str] = None
    amount: Optional[float] = None
    payment_update_date: Optional[str] = None

    @model_validator(mode="after")
    def validate_update_contract(self):
        if self.payment_status is None:
            raise ValueError("Payment status is required.")

        if self.payment_status == InvoiceUpdatePaymentStatus.PARTIAL:
            if self.amount is None or self.amount <= 0:
                raise ValueError(
                    "A payment amount greater than zero is required for PARTIAL payments."
                )

        return self


class InvoiceHeader(BaseModel):
    user_secret: str


class UserBase(BaseModel):
    username: str
    email: str
    business_id: str
    service_id: str
    certificate: Optional[str] = None
    public_key: Optional[str] = None
    tin: Optional[str] = None
    party_name: Optional[str] = None
    telephone: Optional[str] = None
    street_name: Optional[str] = None
    city_name: Optional[str] = None
    postal_zone: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    lga: Optional[str] = None

    _validate_tin = field_validator("tin")(validate_tin)


PASSWORD_UPPER = re.compile(r"[A-Z]")
PASSWORD_LOWER = re.compile(r"[a-z]")
PASSWORD_DIGIT = re.compile(r"\d")


class UserCreate(UserBase):
    password: str = Field(min_length=8)

    @field_validator("password")
    @classmethod
    def _validate_password_strength(cls, v: str) -> str:
        if not PASSWORD_UPPER.search(v):
            raise ValueError(
                "Password must contain at least one uppercase letter"
            )
        if not PASSWORD_LOWER.search(v):
            raise ValueError(
                "Password must contain at least one lowercase letter"
            )
        if not PASSWORD_DIGIT.search(v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserOut(UserBase):
    id: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str


class RefreshRequest(BaseModel):
    session_id: str


class CustomerBase(BaseModel):
    tin: str
    party_name: str
    email: EmailStr
    telephone: str
    street_name: str
    city_name: str
    postal_zone: str
    country: str
    state: str
    lga: Optional[str] = None


class CustomerCreate(CustomerBase):
    _validate_tin = field_validator("tin")(validate_tin)


CustomerUpdate = CustomerCreate


class CustomerOut(CustomerBase):
    id: int
    business_id: str
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CustomerPage(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[CustomerOut]


class CustomerBulkAction(BaseModel):
    ids: list[int] = []
    hard: bool = False


class CustomerImportResult(BaseModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = []


class InvoiceLogCreate(BaseModel):
    irn: str
    issue_date: str
    customer_name: str
    currency: str
    payment_status: str = "PENDING"
    payable_amount: float
    transmitted: bool = False


class InvoiceLogOut(InvoiceLogCreate):
    id: int
    business_id: str
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class InvoiceLogStats(BaseModel):
    total: int
    revenue: float = 0.0
    pending: int
    paid: int
    rejected: int
    partial: int = 0
    revenue_by_currency: dict[str, float] = {}


class InvoiceLogPage(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[InvoiceLogOut]


class SessionOut(BaseModel):
    id: int
    session_id: str
    user_id: Optional[int] = None
    username: str
    business_id: str
    expires_at: str
    wizard_json: Optional[str] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SessionOutWithToken(SessionOut):
    jwt_token: str


class WizardAssembleRequest(BaseModel):
    wizard: dict


class InvoiceStatusUpdate(BaseModel):
    payment_status: PaymentStatus


class SessionSecretUpdate(BaseModel):
    user_secret: str


class SessionTokenUpdate(BaseModel):
    jwt_token: str


class SessionWizardUpdate(BaseModel):
    wizard_json: Optional[str] = None


class UserSecretUpdate(BaseModel):
    user_secret: str


class UserCertKeyUpdate(BaseModel):
    certificate: Optional[str] = None
    public_key: Optional[str] = None


class UserProfileUpdate(BaseModel):
    tin: Optional[str] = None
    party_name: Optional[str] = None
    telephone: Optional[str] = None
    street_name: Optional[str] = None
    city_name: Optional[str] = None
    postal_zone: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    lga: Optional[str] = None

    _validate_tin = field_validator("tin")(validate_tin)


class NextIRNRequest(BaseModel):
    issue_date: str
    regenerate: bool = False
    current_irn: Optional[str] = None


class NextIRNResponse(BaseModel):
    irn: str
    sequence: int
    service_id: str
    date_segment: str
    issue_date: str
    reserved: bool = True


class UnitCode(BaseModel):
    code: str
    name: str


class ItemBase(BaseModel):
    sku: Optional[str] = None
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    hsn_code: Optional[str] = None
    hsn_category: Optional[str] = None
    isic_code: Optional[str] = None
    isic_category: Optional[str] = None
    unit_price: float
    price_unit: str = DEFAULT_UNIT_CODE
    base_quantity: float = 1.0

    _validate_price_unit = field_validator("price_unit")(validate_unit_code)

    @field_validator(
        "sku",
        "description",
        "hsn_code",
        "hsn_category",
        "isic_code",
        "isic_category",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, v):
        return str(v).strip() if v is not None else v

    @field_validator("unit_price")
    @classmethod
    def _validate_unit_price(cls, v: float) -> float:
        if v is None or v <= 0:
            raise ValueError(
                "unit_price must be greater than zero — a priced-later item "
                "cannot be invoiced."
            )
        return float(v)

    @field_validator("base_quantity")
    @classmethod
    def _validate_base_quantity(cls, v: float) -> float:
        if v is None or v <= 0:
            raise ValueError("base_quantity must be greater than zero.")
        return float(v)

    @model_validator(mode="after")
    def _validate_classification(self):
        has_hsn = bool(self.hsn_code)
        has_isic = bool(self.isic_code)
        if has_hsn and has_isic:
            raise ValueError(
                "An item is either a product (HS code) or a service "
                "(ISIC code), not both."
            )
        if not has_hsn and not has_isic:
            raise ValueError(
                "Either an HS code (product) or an ISIC code (service) is "
                "required."
            )
        if has_hsn:
            if not HSN_PATTERN.match(self.hsn_code):
                raise ValueError(
                    "hsn_code must use the FIRS format XXXX.XX (e.g. 1006.10)."
                )
            if not self.hsn_category:
                raise ValueError(
                    "hsn_category is required for product items — select it "
                    "from the FIRS product lookup."
                )
        if has_isic:
            if not ISIC_PATTERN.match(self.isic_code):
                raise ValueError(
                    "isic_code must be exactly 4 digits (e.g. 0112)."
                )
            if not self.isic_category:
                raise ValueError(
                    "isic_category is required for service items — select it "
                    "from the FIRS service lookup."
                )
        return self


class ItemCreate(ItemBase):
    pass


class ItemUpdate(ItemBase):
    pass


class ItemOut(ItemBase):
    id: int
    business_id: str
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ItemPage(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[ItemOut]


class ItemBulkDelete(BaseModel):
    ids: list[int] = []
    hard: bool = False


class ItemImportResult(BaseModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = []
