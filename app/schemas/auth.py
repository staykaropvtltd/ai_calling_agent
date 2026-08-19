from datetime import datetime

from pydantic import BaseModel


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class AuthenticatedUser(BaseModel):
    """
    Identity extracted from a verified JWT — never from client-supplied
    body/query parameters. This is the object protected endpoints receive
    via the `get_current_user` dependency.
    """

    user_id: str
    tenant_id: str
    role: str
