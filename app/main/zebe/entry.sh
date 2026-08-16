#!/bin/sh
set -e

echo ">>> [zebe] Running Alembic migrations..."
alembic upgrade head

echo ">>> [zebe] Seeding database..."
python -c "
from seed import seed_default_user, seed_customers
seed_default_user()
seed_customers()
print('[zebe] Seeding complete.')
"

echo ">>> [zebe] Starting uvicorn production server..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
