# scorimmo

Official Python SDK for the [Scorimmo](https://www.scorimmo.com) real-estate CRM platform.

## Requirements

- Python ≥ 3.9

## Installation

```bash
pip install scorimmo

# With Flask support
pip install scorimmo[flask]
```

## API Client

```python
from scorimmo import ScorimmoClient, ScorimmoApiError

client = ScorimmoClient(
    base_url="https://app.scorimmo.com",
    username="your-api-username",
    password="your-api-password",
)

# Fetch leads created in the last 24h (handles pagination automatically)
from datetime import datetime, timedelta, timezone
since = datetime.now(timezone.utc) - timedelta(hours=24)
leads = client.leads.since(since)

# Get a single lead
lead = client.leads.get(42)

# Search leads
result = client.leads.list(search={"external_lead_id": "CRM-001"}, limit=20)

# Create a lead
created = client.leads.create({
    "store_id": 1,
    "interest": "TRANSACTION",
    "customer": {"first_name": "Marie", "last_name": "Dupont", "phone": "0600000001"},
    "properties": [{"type": "Appartement", "price": 250000}],
})

# Update a lead (e.g. store your CRM id)
client.leads.update(created["id"], {"external_lead_id": "CRM-456"})
```

## Webhook Handler

```python
from scorimmo import ScorimmoWebhook

webhook = ScorimmoWebhook(
    header_value="your-webhook-secret",
    header_key="X-Scorimmo-Key",
)

# Framework-agnostic
event = webhook.parse(request.headers, request.body)
webhook.dispatch(event, {
    "new_lead":     lambda lead: your_crm.create_contact(lead),
    "update_lead":  lambda e:    your_crm.update_contact(e["id"], e),
    "new_rdv":      lambda e:    your_crm.create_appointment(e),
    "closure_lead": lambda e:    your_crm.archive_contact(e["lead_id"]),
})

# Flask shortcut
app.add_url_rule("/webhook", view_func=webhook.flask_view({
    "new_lead": lambda lead: your_crm.create_contact(lead),
}), methods=["POST"])
```

### Webhook events

| Event | Trigger | Key fields |
|-------|---------|------------|
| `new_lead` | Lead created | Full lead object |
| `update_lead` | Lead updated | `id`, changed fields |
| `new_comment` | Comment added | `lead_id`, `comment` |
| `new_rdv` | Appointment created | `lead_id`, `start_time`, `location` |
| `new_reminder` | Reminder created | `lead_id`, `start_time` |
| `closure_lead` | Lead closed | `lead_id`, `status`, `close_reason` |

## Error handling

```python
from scorimmo import ScorimmoApiError, ScorimmoAuthError

try:
    lead = client.leads.get(999)
except ScorimmoApiError as e:
    print(e.status_code)  # 404
    print(str(e))         # "Lead not found"
except ScorimmoAuthError:
    print("Check your API credentials")
```

## License

MIT
