import logging
import os
import subprocess
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import text

from utils.database import SessionLocal
from utils.models import User, Customer
from auth import hash_password

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("seed")

load_dotenv(override=True)

USER_NAME = os.getenv("USER_NAME", "admin")
USER_EMAIL = os.getenv("USER_EMAIL", "admin@zetamind.com")
USER_PASSWORD = os.getenv("USER_PASSWORD", "admin123")
BUSINESS_ID = os.getenv("BUSINESS_ID", "")
SERVICE_ID = os.getenv("SERVICE_ID", "")
PUBLIC_KEY = os.getenv("PUBLIC_KEY", "")
CERTIFICATE = os.getenv("CERTIFICATE", "")
TIN = os.getenv("TIN", "12345678-0001")
PARTY_NAME = os.getenv("PARTY_NAME", "Zetamind Technologies Ltd")
TELEPHONE = os.getenv("TELEPHONE", "+234-800-000-0000")
STREET_NAME = os.getenv("STREET_NAME", "42 Awolowo Road")
CITY_NAME = os.getenv("CITY_NAME", "Ikeja")
POSTAL_ZONE = os.getenv("POSTAL_ZONE", "100001")
COUNTRY = os.getenv("COUNTRY", "NG")
STATE = os.getenv("STATE", "LA")
LGA = os.getenv("LGA", "Ikeja")

SAMPLE_CUSTOMERS = [
    {
        "tin": "20867371-0001",
        "party_name": "Adatum Corporation",
        "email": "robert.townes@contoso.com",
        "telephone": "+234801234876",
        "street_name": "Station Road, 21",
        "city_name": "London",
        "postal_zone": "100001",
        "country": "GB",
        "state": "London",
        "lga": "UK",
    },
]


def seed_default_user() -> bool:
    db = SessionLocal()
    try:
        logger.info("Verifying database connection…")
        db.execute(text("SELECT 1"))
        logger.info("Database connection OK.")

        logger.info("Checking for existing user with email '%s'…", USER_EMAIL)
        existing = db.query(User).filter(User.email == USER_EMAIL).first()

        if existing is not None:
            logger.info(
                "Default user '%s' (%s) already exists — skipping insert.",
                existing.username,
                existing.email,
            )
            return False

        logger.info("No existing default user found. Creating one…")
        hashed_pw = hash_password(USER_PASSWORD)

        new_user = User(
            username=USER_NAME,
            email=USER_EMAIL,
            hashed_password=hashed_pw,
            business_id=BUSINESS_ID,
            service_id=SERVICE_ID,
            public_key=PUBLIC_KEY,
            certificate=CERTIFICATE,
            tin=TIN,
            party_name=PARTY_NAME,
            telephone=TELEPHONE,
            street_name=STREET_NAME,
            city_name=CITY_NAME,
            postal_zone=POSTAL_ZONE,
            country=COUNTRY,
            state=STATE,
            lga=LGA,
            is_active=True,
        )

        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        logger.info(
            "Default user created successfully — id=%s, username='%s', email='%s'",
            new_user.id,
            new_user.username,
            new_user.email,
        )
        return True

    except Exception:
        logger.exception("Failed to seed default user.")
        db.rollback()
        raise
    finally:
        db.close()


def seed_customers() -> bool:
    if not BUSINESS_ID:
        logger.error(
            "BUSINESS_ID environment variable is not set — skipping customer seed."
        )
        return False

    db = SessionLocal()
    try:
        logger.info("Verifying database connection…")
        db.execute(text("SELECT 1"))
        logger.info("Database connection OK.")

        logger.info(
            "Seeding %d sample customers for business_id='%s'…",
            len(SAMPLE_CUSTOMERS),
            BUSINESS_ID,
        )

        created_count = 0
        skipped_count = 0

        for customer_data in SAMPLE_CUSTOMERS:
            existing = (
                db.query(Customer)
                .filter(
                    Customer.business_id == BUSINESS_ID,
                    Customer.tin == customer_data["tin"],
                )
                .first()
            )

            if existing:
                logger.info(
                    "Customer '%s' (%s) already exists — skipping.",
                    customer_data["party_name"],
                    customer_data["tin"],
                )
                skipped_count += 1
                continue

            new_customer = Customer(
                business_id=BUSINESS_ID,
                tin=customer_data["tin"],
                party_name=customer_data["party_name"],
                email=customer_data["email"],
                telephone=customer_data["telephone"],
                street_name=customer_data["street_name"],
                city_name=customer_data["city_name"],
                postal_zone=customer_data["postal_zone"],
                country=customer_data["country"],
                state=customer_data["state"],
                lga=customer_data.get("lga"),
                created_at=datetime.now(timezone.utc),
            )

            db.add(new_customer)
            db.commit()
            db.refresh(new_customer)

            logger.info(
                "✓ Created customer '%s' (id=%s, tin=%s)",
                new_customer.party_name,
                new_customer.id,
                new_customer.tin,
            )
            created_count += 1

        logger.info(
            "Customer seeding complete — created=%d, skipped=%d",
            created_count,
            skipped_count,
        )
        return True

    except Exception:
        logger.exception("Failed to seed customers.")
        db.rollback()
        raise
    finally:
        db.close()


def run_migrations():
    logger.info("Running Alembic migrations…")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=base_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("Alembic migration failed:\n%s", result.stderr)
        sys.exit(1)
    logger.info("Alembic migrations applied successfully.")


def main():
    logger.info("=" * 56)
    logger.info("Zetamind e-Invoicing — Database Seeder")
    logger.info("=" * 56)

    run_migrations()

    try:
        created = seed_default_user()
    except Exception:
        logging.exception("Unexpected error")
        logger.error("Seeding aborted due to errors above. Exiting.")
        sys.exit(1)

    try:
        seed_customers()
    except Exception:
        logging.exception("Unexpected error")
        logger.error("Customer seeding failed, but continuing.")

    if created:
        logger.info("Seeding completed successfully — new user inserted.")
    else:
        logger.info("Seeding completed successfully — no action needed.")

    logger.info("Starting FastAPI dev server…")

    try:
        subprocess.run(
            [sys.executable, "-m", "fastapi", "dev", "main.py"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
    except KeyboardInterrupt:
        logging.exception("Unexpected error")
        logger.info("Server stopped by user (Ctrl+C).")
    except Exception:
        logger.exception("Failed to start FastAPI dev server.")
        sys.exit(1)


if __name__ == "__main__":
    main()