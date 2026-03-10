"""
Example: Fetch leads from the Scorimmo API

Install: pip install scorimmo
Run:     python examples/fetch_leads.py
"""
import os
from datetime import datetime, timedelta, timezone
from scorimmo import ScorimmoClient, ScorimmoApiError

client = ScorimmoClient(
    base_url=os.environ.get("SCORIMMO_URL", "https://app.scorimmo.com"),
    username=os.environ.get("SCORIMMO_USER", ""),
    password=os.environ.get("SCORIMMO_PASSWORD", ""),
)

# ── Fetch leads created in the last 24h ──────────────────────────────────────
since = datetime.now(timezone.utc) - timedelta(hours=24)
leads = client.leads.since(since)

print(f"Found {len(leads)} new leads")
for lead in leads:
    customer = lead.get("customer", {})
    name = f"{customer.get('first_name', '')} {customer.get('last_name', '?')}".strip()
    print(f"  → #{lead['id']} {name} — {lead['interest']} — {lead.get('status', '?')}")

# ── Get a specific lead ───────────────────────────────────────────────────────
try:
    lead = client.leads.get(42)
    print(f"\nLead #42: {lead}")
except ScorimmoApiError as e:
    if e.status_code == 404:
        print("Lead #42 not found")
    else:
        raise

# ── Create a lead ─────────────────────────────────────────────────────────────
created = client.leads.create({
    "store_id": 1,
    "interest": "TRANSACTION",
    "origin": "Mon Site",
    "customer": {
        "first_name": "Marie",
        "last_name": "Dupont",
        "email": "marie.dupont@example.com",
        "phone": "0600000001",
    },
    "properties": [{"type": "Appartement", "price": 250000, "area": 65}],
})
print(f"\nCreated lead #{created['id']}")

# ── Update with your CRM id ───────────────────────────────────────────────────
client.leads.update(created["id"], {"external_lead_id": "CRM-456"})
print(f"Updated lead #{created['id']} with external_lead_id CRM-456")
