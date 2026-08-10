# Admin Dashboard — API Contracts
# NH-06 Pre-Implementation Reference

These contracts must be agreed with Nishkala (NK-05 JWT, NK-06 RBAC) before
any frontend implementation. This file is the source of truth until the
backend is live — at which point OpenAPI spec takes over.

---

## Authentication (NK-05 dependency)

### POST /api/auth/login
Request:
```json
{ "email": "admin@staykaro.com", "password": "string" }
```
Response 200:
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 1800
}
```
Response 401: `{ "detail": "Invalid credentials" }`

### POST /api/auth/refresh
Request:
```json
{ "refresh_token": "eyJ..." }
```
Response 200: same shape as login response

### POST /api/auth/logout
Header: `Authorization: Bearer <access_token>`
Response 204 (no body)

### GET /api/auth/me
Header: `Authorization: Bearer <access_token>`
Response 200:
```json
{
  "user_id": "uuid",
  "email": "string",
  "full_name": "string",
  "role": "super_admin | tenant_admin | agent",
  "tenant_id": "uuid | null",
  "permissions": ["tenant:read", "tenant:write", "user:read", ...]
}
```

---

## Tenant Management (NH-06 — super_admin only)

### POST /api/admin/tenants
Request:
```json
{
  "name": "Acme Hotels",
  "slug": "acme-hotels",
  "plan": "starter | pro | enterprise",
  "contact_email": "ops@acme.com",
  "max_concurrent_calls": 10
}
```
Response 201:
```json
{
  "tenant_id": "uuid",
  "name": "string",
  "slug": "string",
  "plan": "string",
  "status": "active | suspended | inactive",
  "contact_email": "string",
  "max_concurrent_calls": 10,
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```
Error 409: `{ "detail": "Slug already exists" }`

### GET /api/admin/tenants
Query params: `?page=1&per_page=20&status=active&search=acme`
Response 200:
```json
{
  "data": [Tenant],
  "total": 45,
  "page": 1,
  "per_page": 20,
  "total_pages": 3
}
```

### GET /api/admin/tenants/:tenant_id
Response 200: Tenant (full object)
Error 404: `{ "detail": "Tenant not found" }`

### PUT /api/admin/tenants/:tenant_id
Request (all fields optional):
```json
{
  "name": "string",
  "plan": "string",
  "status": "active | suspended | inactive",
  "contact_email": "string",
  "max_concurrent_calls": 20
}
```
Response 200: Tenant (updated)

### DELETE /api/admin/tenants/:tenant_id
Soft delete — sets status to "inactive". Does NOT delete data.
Response 204

### GET /api/admin/tenants/:tenant_id/stats
Response 200:
```json
{
  "tenant_id": "uuid",
  "total_calls": 1204,
  "calls_this_month": 88,
  "active_users": 5,
  "plan_call_limit": 500,
  "plan_usage_pct": 17.6
}
```

---

## User Management (NH-06)

### POST /api/admin/users
Request:
```json
{
  "email": "string",
  "full_name": "string",
  "role": "tenant_admin | agent",
  "tenant_id": "uuid"
}
```
Response 201:
```json
{
  "user_id": "uuid",
  "email": "string",
  "full_name": "string",
  "role": "string",
  "tenant_id": "uuid",
  "status": "active | suspended",
  "created_at": "ISO8601"
}
```

### GET /api/admin/users
Query: `?page=1&per_page=20&tenant_id=uuid&role=agent&status=active`
Response 200: `{ "data": [User], "total", "page", "per_page", "total_pages" }`

### GET /api/admin/users/:user_id
Response 200: User

### PUT /api/admin/users/:user_id
Request:
```json
{ "full_name": "string", "role": "string", "status": "active | suspended" }
```
Response 200: User (updated)

### DELETE /api/admin/users/:user_id
Soft delete — sets status to "suspended".
Response 204

---

## Call Log (read-only admin view)

### GET /api/admin/calls
Query: `?page=1&per_page=20&tenant_id=uuid&status=completed&from=2024-01-01&to=2024-01-31`
Response 200:
```json
{
  "data": [{
    "call_id": "uuid",
    "tenant_id": "uuid",
    "customer_name": "string",
    "phone": "+91XXXXXXXXXX",
    "status": "initiated | in_progress | completed | failed",
    "duration_s": 142,
    "created_at": "ISO8601"
  }],
  "total": 1204,
  "page": 1,
  "per_page": 20,
  "total_pages": 61
}
```

### GET /api/admin/calls/:call_id
Response 200: Call (full object with recording_url if available)

---

## Multi-Tenant Safety Rules (backend must enforce)

1. super_admin  → can see ALL tenants and users
2. tenant_admin → can only see resources where tenant_id == their own tenant_id
3. agent        → no access to /api/admin/* routes at all

The backend MUST filter by tenant_id from the JWT payload, NOT from query params.
Never trust tenant_id sent by the client in the request body for scoping queries.

---

## Error Response Standard

All errors follow this shape:
```json
{
  "detail": "Human-readable message",
  "code": "MACHINE_READABLE_CODE",
  "field": "optional — for validation errors"
}
```

HTTP codes:
- 400  Validation error
- 401  No valid token
- 403  Valid token, insufficient role
- 404  Resource not found
- 409  Conflict (duplicate slug, email, etc.)
- 422  Request body schema mismatch
- 500  Internal server error
