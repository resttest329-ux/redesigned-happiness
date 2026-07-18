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


TIN_PATTERN = re.compile(r"^\d{8}-\d{4}$")
HSN_PATTERN = re.compile(r"^\d{4}\.\d{2}$")
ISIC_PATTERN = re.compile(r"^\d{4}$")
SKU_PATTERN = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")


def validate_tin(value: Optional[str]) -> Optional[str]:
    if value is None or value == "":
        return value
    if not TIN_PATTERN.match(value):
        raise ValueError(
            "TIN must be in the FIRS format NNNNNNNN-NNNN (e.g. 12345678-0001)."
        )
    return value


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
    lga: str = ""


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
    price_unit: str


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
    irn: str
    business_id: str
    issue_date: str
    issue_time: Optional[str] = None
    due_date: Optional[str] = None
    invoice_type_code: str
    document_currency_code: str
    tax_currency_code: Optional[str] = None
    billing_reference: Optional[list[BillingReference]] = None
    payment_means: Optional[list[PaymentMeansItem]] = None

    accounting_customer_party: AccountingParty
    accounting_supplier_party: AccountingParty

    tax_total: list[TaxTotal]
    legal_monetary_total: LegalMonetaryTotal
    invoice_line: list[InvoiceLine]


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
    is_active: bool = True
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


class UserCreate(UserBase):
    password: str = Field(min_length=8)


class UserOut(UserBase):
    id: int

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
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CustomerPage(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[CustomerOut]


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


class ItemBase(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    hsn_code: Optional[str] = None
    hsn_category: Optional[str] = Field(default=None, max_length=200)
    isic_code: Optional[str] = None
    isic_category: Optional[str] = Field(default=None, max_length=200)
    unit_price: Optional[float] = Field(default=None, ge=0)
    price_unit: Optional[str] = Field(default=None, max_length=64)

    @field_validator("sku")
    @classmethod
    def _validate_sku(cls, v: str) -> str:
        v = (v or "").strip()
        if not SKU_PATTERN.match(v):
            raise ValueError(
                "SKU may only contain letters, digits, '.', '_' or '-' "
                "and must be 1-64 characters."
            )
        return v

    @field_validator(
        "name", "description", "hsn_category", "isic_category", "price_unit"
    )
    @classmethod
    def _strip_str(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        return v or None

    @field_validator("hsn_code")
    @classmethod
    def _validate_hsn(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v = v.strip()
        if not HSN_PATTERN.match(v):
            raise ValueError(
                "HS code must use the FIRS format XXXX.XX (e.g. 1006.10)."
            )
        return v

    @field_validator("isic_code")
    @classmethod
    def _validate_isic(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v = v.strip()
        if not ISIC_PATTERN.match(v):
            raise ValueError(
                "ISIC service code must be exactly 4 digits (e.g. 0112)."
            )
        return v

    @model_validator(mode="after")
    def _validate_exactly_one_code(self):
        has_hsn = bool(self.hsn_code)
        has_isic = bool(self.isic_code)
        if has_hsn and has_isic:
            raise ValueError(
                "An item must carry either an HS code (product) or an ISIC "
                "code (service), not both."
            )
        if not has_hsn and not has_isic:
            raise ValueError(
                "An item must carry exactly one classification: either an HS "
                "code (product) or an ISIC code (service)."
            )
        # Enforce paired category is only present for the code that is set.
        if has_hsn and self.isic_category:
            self.isic_category = None
        if has_isic and self.hsn_category:
            self.hsn_category = None
        return self


class ItemCreate(ItemBase):
    pass


class ItemUpdate(ItemBase):
    pass


class ItemOut(ItemBase):
    id: int
    business_id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ItemPage(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[ItemOut]


class ItemBulkDelete(BaseModel):
    ids: list[int] = Field(default_factory=list, max_length=500)


class ItemImportRowError(BaseModel):
    row: int
    sku: Optional[str] = None
    error: str


class ItemImportResult(BaseModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[ItemImportRowError] = Field(default_factory=list)
    total_rows: int = 0


class SessionCreate(BaseModel):
    jwt_token: str
    user_secret: str = ""
    username: str
    business_id: str
    user_id: Optional[int] = None


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
