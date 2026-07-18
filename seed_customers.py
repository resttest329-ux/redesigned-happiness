"""
Seed 30 customers into the e-invoicing backend.

Usage:
    python seed_customers.py                 # uses envars or prompts
    python seed_customers.py --username=admin --password=secret

Environment variables (optional):
    ZEBE_API_BASE_URL    default http://127.0.0.1:8000
"""

import argparse
import logging
import os
import sys
import time

import httpx

logger = logging.getLogger("seed_customers")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s"
)

API_BASE = os.environ.get("ZEBE_API_BASE_URL", "http://127.0.0.1:8000")

# ---------------------------------------------------------------------------
# 30 realistic Nigerian businesses
# ---------------------------------------------------------------------------
SEED_CUSTOMERS = [
    {
        "tin": "12345678-0001",
        "party_name": "De Grande Integrated Services Ltd",
        "email": "info@de-grande.com",
        "telephone": "+2348031000001",
        "street_name": "42a Adeola Odeku Street",
        "city_name": "Lagos",
        "postal_zone": "100001",
        "country": "NG",
        "state": "Lagos",
        "lga": "Eti-Osa",
    },
    {
        "tin": "23456789-0002",
        "party_name": "Renascent Technology Hub",
        "email": "hello@renascent.ng",
        "telephone": "+2348092000002",
        "street_name": "15 Bisi Ogunleye Close",
        "city_name": "Ikeja",
        "postal_zone": "100271",
        "country": "NG",
        "state": "Lagos",
        "lga": "Ikeja",
    },
    {
        "tin": "34567890-0003",
        "party_name": "Bamboo & Vine Furniture Co.",
        "email": "orders@bambovine.com",
        "telephone": "+2348053000003",
        "street_name": "7 Awolowo Road",
        "city_name": "Ikoyi",
        "postal_zone": "101233",
        "country": "NG",
        "state": "Lagos",
        "lga": "Eti-Osa",
    },
    {
        "tin": "45678901-0004",
        "party_name": "SwiftPay Financial Services",
        "email": "support@swiftpay.ng",
        "telephone": "+2348164000004",
        "street_name": "23 Marina Boulevard",
        "city_name": "Lagos Island",
        "postal_zone": "101241",
        "country": "NG",
        "state": "Lagos",
        "lga": "Lagos Island",
    },
    {
        "tin": "56789012-0005",
        "party_name": "GreenSprout Agric Ventures",
        "email": "farm@greensprout.ng",
        "telephone": "+2347065000005",
        "street_name": "Km 12 Abuja-Lokoja Road",
        "city_name": "Abuja",
        "postal_zone": "900001",
        "country": "NG",
        "state": "FCT",
        "lga": "Abuja Municipal",
    },
    {
        "tin": "67890123-0006",
        "party_name": "Pinnacle Engineering Ltd",
        "email": "eng@pinnacleltd.ng",
        "telephone": "+2348096000006",
        "street_name": "9 Tafawa Balewa Way",
        "city_name": "Kano",
        "postal_zone": "700001",
        "country": "NG",
        "state": "Kano",
        "lga": "Kano Municipal",
    },
    {
        "tin": "78901234-0007",
        "party_name": "CrestWave Consulting",
        "email": "info@crestwave.ng",
        "telephone": "+2348037000007",
        "street_name": "55 Isaac John Street",
        "city_name": "Ikeja",
        "postal_zone": "100271",
        "country": "NG",
        "state": "Lagos",
        "lga": "Ikeja",
    },
    {
        "tin": "89012345-0008",
        "party_name": "Oakleaf Pharmaceutical Ltd",
        "email": "pharma@oakleaf.ng",
        "telephone": "+2348088000008",
        "street_name": "17 Idowu Martins Street",
        "city_name": "Victoria Island",
        "postal_zone": "101241",
        "country": "NG",
        "state": "Lagos",
        "lga": "Eti-Osa",
    },
    {
        "tin": "90123456-0009",
        "party_name": "Blue Horizon Logistics",
        "email": "dispatch@bluehorizon.ng",
        "telephone": "+2348159000009",
        "street_name": "3 Wharf Road",
        "city_name": "Port Harcourt",
        "postal_zone": "500001",
        "country": "NG",
        "state": "Rivers",
        "lga": "Port Harcourt",
    },
    {
        "tin": "01234567-0010",
        "party_name": "TerraBuild Construction Co.",
        "email": "projects@terrabuild.ng",
        "telephone": "+2348020100010",
        "street_name": "22 Constitution Avenue",
        "city_name": "Abuja",
        "postal_zone": "900001",
        "country": "NG",
        "state": "FCT",
        "lga": "Abuja Municipal",
    },
    {
        "tin": "11223344-0011",
        "party_name": "Verdant Agro-Allied Ltd",
        "email": "sales@verdantagro.ng",
        "telephone": "+2347031100011",
        "street_name": "Old Oyo Road, Opposite Stadium",
        "city_name": "Ibadan",
        "postal_zone": "200001",
        "country": "NG",
        "state": "Oyo",
        "lga": "Ibadan North",
    },
    {
        "tin": "22334455-0012",
        "party_name": "Sahara Digital Solutions",
        "email": "dev@saharadigital.ng",
        "telephone": "+2348091200012",
        "street_name": "10 Bishop Aboyade Cole Street",
        "city_name": "Victoria Island",
        "postal_zone": "101241",
        "country": "NG",
        "state": "Lagos",
        "lga": "Eti-Osa",
    },
    {
        "tin": "33445566-0013",
        "party_name": "PrimeGate Security Services",
        "email": "info@primegate.ng",
        "telephone": "+2348051300013",
        "street_name": "25 Murtala Mohammed Way",
        "city_name": "Kaduna",
        "postal_zone": "800001",
        "country": "NG",
        "state": "Kaduna",
        "lga": "Kaduna North",
    },
    {
        "tin": "44556677-0014",
        "party_name": "Imperial Hospitality Ltd",
        "email": "reservations@imperial.ng",
        "telephone": "+2348141400014",
        "street_name": "1 Ahmadu Bello Way",
        "city_name": "Abuja",
        "postal_zone": "900211",
        "country": "NG",
        "state": "FCT",
        "lga": "Abuja Municipal",
    },
    {
        "tin": "55667788-0015",
        "party_name": "Crystal Clear Water Co.",
        "email": "hello@crystalwater.ng",
        "telephone": "+2347061500015",
        "street_name": "48 Nnamdi Azikiwe Road",
        "city_name": "Enugu",
        "postal_zone": "400001",
        "country": "NG",
        "state": "Enugu",
        "lga": "Enugu North",
    },
    {
        "tin": "66778899-0016",
        "party_name": "Apex Auto Spares Ltd",
        "email": "parts@apexauto.ng",
        "telephone": "+2348031600016",
        "street_name": "12 Obafemi Awolowo Way",
        "city_name": "Ikeja",
        "postal_zone": "100271",
        "country": "NG",
        "state": "Lagos",
        "lga": "Ikeja",
    },
    {
        "tin": "77889900-0017",
        "party_name": "Stratos Energy Services",
        "email": "info@stratosenergy.ng",
        "telephone": "+2348091700017",
        "street_name": "5 Trans-Amadi Industrial Layout",
        "city_name": "Port Harcourt",
        "postal_zone": "500102",
        "country": "NG",
        "state": "Rivers",
        "lga": "Obio-Akpor",
    },
    {
        "tin": "88990011-0018",
        "party_name": "Zuri Beauty & Cosmetics Ltd",
        "email": "care@zuribeauty.ng",
        "telephone": "+2348151800018",
        "street_name": "31 Raymond Njoku Street",
        "city_name": "Lagos",
        "postal_zone": "101233",
        "country": "NG",
        "state": "Lagos",
        "lga": "Eti-Osa",
    },
    {
        "tin": "99001122-0019",
        "party_name": "Meridian Healthcare Systems",
        "email": "info@meridianhealth.ng",
        "telephone": "+2347061900019",
        "street_name": "8 Golf Course Road",
        "city_name": "Abuja",
        "postal_zone": "900231",
        "country": "NG",
        "state": "FCT",
        "lga": "Abuja Municipal",
    },
    {
        "tin": "00112233-0020",
        "party_name": "BrightPath Educational Services",
        "email": "admin@brightpath.ng",
        "telephone": "+2348032000020",
        "street_name": "22 University Road",
        "city_name": "Ile-Ife",
        "postal_zone": "220001",
        "country": "NG",
        "state": "Osun",
        "lga": "Ife East",
    },
    {
        "tin": "99887766-0021",
        "party_name": "Ironclad Manufacturing Ltd",
        "email": "factory@ironclad.ng",
        "telephone": "+2348092100021",
        "street_name": "Km 14 Lagos-Ibadan Expressway",
        "city_name": "Abeokuta",
        "postal_zone": "110001",
        "country": "NG",
        "state": "Ogun",
        "lga": "Abeokuta South",
    },
    {
        "tin": "88776655-0022",
        "party_name": "Pulse Retail Concepts",
        "email": "shop@pulseretail.ng",
        "telephone": "+2348152200022",
        "street_name": "5 Allen Avenue",
        "city_name": "Ikeja",
        "postal_zone": "100271",
        "country": "NG",
        "state": "Lagos",
        "lga": "Ikeja",
    },
    {
        "tin": "77665544-0023",
        "party_name": "Aether Networks ISP",
        "email": "support@aether.ng",
        "telephone": "+2348032300023",
        "street_name": "16 Association Road",
        "city_name": "Uyo",
        "postal_zone": "520001",
        "country": "NG",
        "state": "Akwa Ibom",
        "lga": "Uyo",
    },
    {
        "tin": "66554433-0024",
        "party_name": "Golden Grain Mills Ltd",
        "email": "sales@goldengrain.ng",
        "telephone": "+2347062400024",
        "street_name": "3 Industrial Crescent",
        "city_name": "Kano",
        "postal_zone": "700222",
        "country": "NG",
        "state": "Kano",
        "lga": "Nasarawa",
    },
    {
        "tin": "55443322-0025",
        "party_name": "CrossRiver Eco-Tours",
        "email": "book@crossrivertours.ng",
        "telephone": "+2348092500025",
        "street_name": "6 Waterfall Drive",
        "city_name": "Calabar",
        "postal_zone": "540001",
        "country": "NG",
        "state": "Cross River",
        "lga": "Calabar Municipal",
    },
    {
        "tin": "44332211-0026",
        "party_name": "NovaTech IT Solutions",
        "email": "info@novatech.ng",
        "telephone": "+2348152600026",
        "street_name": "29 Ogunlana Drive",
        "city_name": "Lagos",
        "postal_zone": "100001",
        "country": "NG",
        "state": "Lagos",
        "lga": "Surulere",
    },
    {
        "tin": "33221100-0027",
        "party_name": "Ace Media & Advertising Ltd",
        "email": "hello@acemedia.ng",
        "telephone": "+2348032700027",
        "street_name": "11 Toyin Street",
        "city_name": "Ikeja",
        "postal_zone": "100271",
        "country": "NG",
        "state": "Lagos",
        "lga": "Ikeja",
    },
    {
        "tin": "22110099-0028",
        "party_name": "Tranquil Paints & Coatings",
        "email": "orders@tranquilpaints.ng",
        "telephone": "+2347062800028",
        "street_name": "18 Benin-Auchi Road",
        "city_name": "Benin City",
        "postal_zone": "300001",
        "country": "NG",
        "state": "Edo",
        "lga": "Egor",
    },
    {
        "tin": "11009988-0029",
        "party_name": "CloverLeaf Microfinance Bank",
        "email": "banking@cloverleaf.ng",
        "telephone": "+2348092900029",
        "street_name": "2 Bank Road",
        "city_name": "Ilorin",
        "postal_zone": "240001",
        "country": "NG",
        "state": "Kwara",
        "lga": "Ilorin West",
    },
    {
        "tin": "00998877-0030",
        "party_name": "Vanguard Renewable Energy",
        "email": "solar@vanguardre.ng",
        "telephone": "+2348153000030",
        "street_name": "Km 5 Ikorodu Road",
        "city_name": "Lagos",
        "postal_zone": "100001",
        "country": "NG",
        "state": "Lagos",
        "lga": "Kosofe",
    },
]


def login(username: str, password: str) -> str | None:
    """Authenticate and return a bearer token."""
    url = f"{API_BASE}/auth/token"
    logger.info("Logging in as %s …", username)
    resp = httpx.post(url, data={"username": username, "password": password})
    if resp.status_code != 200:
        logger.error("Login failed: %s %s", resp.status_code, resp.text)
        return None
    data = resp.json()
    token = data.get("access_token") or data.get("token")
    if not token:
        logger.error("No access_token in response: %s", data)
        return None
    logger.info("Login successful (token received)")
    return token


def create_customer(token: str, payload: dict) -> bool:
    """POST a single customer.  Returns True on 200/201."""
    url = f"{API_BASE}/customers"
    headers = {"Authorization": f"Bearer {token}"}
    resp = httpx.post(url, json=payload, headers=headers)
    if resp.status_code in (200, 201):
        return True
    logger.warning(
        "  FAIL [%s] %s — %s",
        resp.status_code,
        payload["party_name"],
        resp.text[:200],
    )
    return False


def main():
    parser = argparse.ArgumentParser(description="Seed 30 customers")
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    args = parser.parse_args()

    username = (
        args.username or os.environ.get("ZEBE_USERNAME") or input("Username: ")
    )
    password = (
        args.password or os.environ.get("ZEBE_PASSWORD") or input("Password: ")
    )

    token = login(username, password)
    if token is None:
        sys.exit(1)

    logger.info("Seeding %d customers …", len(SEED_CUSTOMERS))
    ok = 0
    fail = 0
    for i, cust in enumerate(SEED_CUSTOMERS, 1):
        cust["tin"] = f"{cust['tin'].split('-')[0]}-{i:04d}"
        success = create_customer(token, cust)
        if success:
            ok += 1
            logger.info(
                "  %2d/%2d  ✓  %s", i, len(SEED_CUSTOMERS), cust["party_name"]
            )
        else:
            fail += 1
        # Be gentle with the backend
        time.sleep(0.1)

    logger.info("Done — %d created, %d failed", ok, fail)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()