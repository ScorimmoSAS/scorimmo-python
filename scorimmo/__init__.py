"""SDK Python officiel Scorimmo — client API v2 & récepteur webhook."""
from .client import (
    AdditionalFieldsResource,
    AppointmentsResource,
    CommentsResource,
    CustomersResource,
    FormResource,
    LeadsResource,
    OriginsResource,
    RemindersResource,
    RequestFieldsResource,
    RequestsResource,
    ScorimmoApiError,
    ScorimmoAuthError,
    ScorimmoClient,
    StatusResource,
    StoresResource,
    UsersResource,
    WebCallbacksResource,
)
from .webhook import ScorimmoWebhook, WebhookAuthError, WebhookValidationError

__version__ = "0.2.0"
__all__ = [
    "ScorimmoClient",
    "ScorimmoApiError",
    "ScorimmoAuthError",
    "ScorimmoWebhook",
    "WebhookAuthError",
    "WebhookValidationError",
    # Resources
    "LeadsResource",
    "AppointmentsResource",
    "CommentsResource",
    "RemindersResource",
    "RequestsResource",
    "StoresResource",
    "UsersResource",
    "CustomersResource",
    "StatusResource",
    "OriginsResource",
    "AdditionalFieldsResource",
    "RequestFieldsResource",
    "FormResource",
    "WebCallbacksResource",
]
