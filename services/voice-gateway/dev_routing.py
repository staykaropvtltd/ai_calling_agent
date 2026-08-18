"""Temporary development-only substitute for NK phone_numbers routing.

Remove/disable this once the real NK routing contract is available.
"""

from __future__ import annotations

from dataclasses import dataclass

from internal_calls import InternalApiError


@dataclass(frozen=True)
class TestPhoneRoute:
    tenant_id: str
    agent_id: str
    provider: str


class TestExotelRoutingStub:
    """Explicitly injected only; never selected by production defaults."""

    async def resolve(self, dialed_number: str) -> tuple[str, str]:
        if dialed_number != "+917314623519":
            raise InternalApiError("Test phone-number route not found")
        route = TestPhoneRoute("test-tenant", "test-agent", "exotel")
        return route.tenant_id, route.agent_id
