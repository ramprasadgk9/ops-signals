from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

from backend.app.integrations.ticketing.models import (
    RemoteEventDraft,
    RemoteTicketSnapshot,
    TicketCreationResult,
    TicketDraft,
)


class TicketingError(Exception):
    """Base exception for ticketing integration errors."""
    pass


class AmbiguousOutcomeError(TicketingError):
    """Raised when the outcome of a remote mutation cannot be verified (timeouts, gateway 5xx)."""
    pass


class TicketNotFoundError(TicketingError):
    """Raised when a referenced ticket, event, or case cannot be found."""
    pass


class ProviderNotConfiguredError(TicketingError):
    """Raised when an operation is attempted against a disabled or incompletely configured provider."""
    pass


class LeaseLostError(TicketingError):
    """Raised when a worker's lease token is no longer valid upon conditional commit."""
    pass


@runtime_checkable
class TicketCreator(Protocol):
    """Role protocol for outbound ticket creation and pre-reconciliation."""
    def reconcile_or_create(self, draft: TicketDraft, operation_id: str) -> TicketCreationResult:
        ...

    def reconcile_only(self, operation_id: str, case_id: int | None = None) -> TicketCreationResult | None:
        ...


@runtime_checkable
class TicketSynchronizer(Protocol):
    """Role protocol for polling remote ticket updates."""
    def pull_remote_ticket(self, remote_id: str, display_key: str, cursor: str | None) -> RemoteTicketSnapshot:
        ...


@runtime_checkable
class WebhookVerifier(Protocol):
    """Role protocol for cryptographic webhook signature verification."""
    def verify_signature(self, raw_body: bytes, headers: Mapping[str, str], secret: str) -> bool:
        ...


@runtime_checkable
class WebhookParser(Protocol):
    """Role protocol for extracting delivery identifiers and parsing remote events."""
    def extract_delivery_id(self, headers: Mapping[str, str]) -> str | None:
        ...

    def parse_webhook_event(self, raw_body: bytes, headers: Mapping[str, str]) -> RemoteEventDraft | None:
        ...
