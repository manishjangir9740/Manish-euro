"""Configuration and path resolutions for Eluno POS."""

import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
STARTER_KIT_DIR = BASE_DIR / "starter-kit"
DATA_DIR = STARTER_KIT_DIR / "data"

# Mock server endpoints
MOCK_SERVER_URL = os.environ.get("ELUNO_MOCK_SERVER_URL", "http://127.0.0.1:8787")
# Real Shopify (optional): set SHOPIFY_SHOP=your-store.myshopify.com and SHOPIFY_ACCESS_TOKEN=shpat_...
# Without them everything talks to the bundled mock.
SHOPIFY_API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2026-10")
SHOPIFY_SHOP = os.environ.get("SHOPIFY_SHOP", "")
SHOPIFY_ACCESS_TOKEN = os.environ.get("SHOPIFY_ACCESS_TOKEN", "")
SHOPIFY_API_BASE = (
    f"https://{SHOPIFY_SHOP}/admin/api/{SHOPIFY_API_VERSION}" if SHOPIFY_SHOP
    else f"{MOCK_SERVER_URL}/admin/api/{SHOPIFY_API_VERSION}"
)
SMT_API_BASE = f"{MOCK_SERVER_URL}/smt"
TERMINAL_API_BASE = f"{MOCK_SERVER_URL}/terminal"

# File data sources
TAX_RATES_FILE = DATA_DIR / "tax_rates.json"
OFFERS_FILE = DATA_DIR / "offers.json"
LOCATIONS_FILE = DATA_DIR / "locations.json"
CUSTOMERS_FILE = DATA_DIR / "customers.json"
PRODUCTS_FILE = DATA_DIR / "products.json"
PRESCRIPTIONS_FILE = DATA_DIR / "prescriptions.json"
STAFF_FILE = DATA_DIR / "staff.json"

# State persistence directory
STATE_DIR = Path(os.environ.get("ELUNO_STATE_DIR", BASE_DIR / "state"))
INVOICE_SEQUENCE_FILE = STATE_DIR / "invoice_sequences.json"
TILL_SESSIONS_FILE = STATE_DIR / "till_sessions.json"
AUDIT_LOG_FILE = STATE_DIR / "audit_log.json"
OUTBOX_FILE = STATE_DIR / "pending_bills.json"
TILL_SAMPLE_FILE = DATA_DIR / "till_sessions_sample.json"

# Finance: cash variance above this is flagged the same night
TILL_VARIANCE_ALERT_PAISE = 20000

# Network retry configuration
MAX_RETRIES = 5
DEFAULT_RETRY_AFTER_SECS = 1.0
HTTP_TIMEOUT_SECS = 10.0
