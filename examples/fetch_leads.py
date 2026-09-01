"""
Example: fetch leads from the Scorimmo API v2.

Install:   pip install scorimmo
Run:       python examples/fetch_leads.py

Env vars:
    SCORIMMO_EMAIL      Adresse email du compte API v2
    SCORIMMO_PASSWORD   Mot de passe du compte API v2
    SCORIMMO_URL        URL de base (défaut: https://pro.scorimmo.com)
"""
import os
from datetime import datetime, timedelta, timezone

from scorimmo import ScorimmoApiError, ScorimmoClient

client = ScorimmoClient(
    email=os.environ.get("SCORIMMO_EMAIL", ""),
    password=os.environ.get("SCORIMMO_PASSWORD", ""),
    base_url=os.environ.get("SCORIMMO_URL", "https://pro.scorimmo.com"),
)

# ── Récupérer les leads créés dans les dernières 24h ─────────────────────────
since = datetime.now(timezone.utc) - timedelta(hours=24)
leads = client.leads.since(since, include=["customer", "seller"])

print(f"Found {len(leads)} new leads")
for lead in leads:
    customer = lead.get("customer") or {}
    name = f"{customer.get('first_name', '')} {customer.get('last_name', '?')}".strip()
    print(f"  → #{lead['id']} {name} — {lead['interest']} — {lead.get('status', '?')}")

# ── Récupérer un lead avec ses relations ─────────────────────────────────────
try:
    lead = client.leads.get(42, include=["customer", "seller", "appointments", "comments"])
    print(f"\nLead #42: {lead}")
except ScorimmoApiError as e:
    if e.status_code == 404:
        print("Lead #42 not found")
    else:
        raise

# ── Mise à jour partielle d'un lead ──────────────────────────────────────────
client.leads.update(42, {"external_lead_id": "CRM-456"})
print("Updated lead #42 with external_lead_id CRM-456")

# ── Recherche filtrée ────────────────────────────────────────────────────────
filtered = client.leads.list(**{
    "interest": "Transaction",
    "store_id": 1,
    "created_at[gte]": "2026-01-01T00:00:00+00:00",
    "sort": "created_at:desc",
    "limit": 20,
    "include": "customer",
})
print(f"\nFiltered: {len(filtered['data'])} leads (total: {filtered['meta']['total_items']})")

# ── Formulaire public ───────────────────────────────────────────────────────
response = client.form.submit({
    "store_id": 1,
    "libelle_id": 12,
    "to_email": "contact@agence.fr",
    "origin": "Site web",
    "message": "Je souhaite visiter le bien X.",
    "subject": "Demande de visite",
    "customer": {
        "civility": "M.",
        "first_name": "Jean",
        "last_name": "Dupont",
        "email": "jean@example.com",
        "phone": "0612345678",
    },
    "external_lead_id": "CRM-12345",
})
print(f"\nForm submitted → lead id {response['id']}")

# ── Appel sortant WebCallback (auth par clé WCB, pas de Bearer) ─────────────
# client.web_callbacks.launch(os.environ["SCORIMMO_WCB_KEY"], "+33612345678")

# ── Gestion des tokens (optionnel) ──────────────────────────────────────────
client.get_token()  # force la première auth
refresh_token = client.get_refresh_token()
print(f"\nRefresh token: {(refresh_token or '')[:8]}…")
