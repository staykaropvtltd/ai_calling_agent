# Security Notice

## Compromised Credentials — Immediate Rotation Required

The following credentials were committed to Git history and must be treated as compromised.
Simply deleting them from `.env` is **not sufficient** — they remain readable in `git log`.

| Credential | Where exposed | Action required |
|---|---|---|
| `[REDACTED_API_PASSWORD]` (API password) | `scripts/keepalive.ps1`, `infrastructure/nginx/portal.html` — commit `8cf4fa5` | Rotate `API_SECRET_KEY` / `API_PASSWORD` in all environments |
| `[REDACTED_DB_PASSWORD]` (Supabase DB password) | `.env` — referenced in commit context | Rotate Supabase database password via Supabase dashboard |
| Bland AI API key (`[REDACTED_BLAND_AI_KEY]`) | `.env.production.example` — commit `8cf4fa5` | Revoke via Bland AI dashboard (integration removed, key still valid) |

To permanently remove credentials from Git history, use
[BFG Repo Cleaner](https://rtyley.github.io/bfg-repo-cleaner/) or
`git filter-repo` — coordinate with all contributors before a force-push.

---

## Known Dependency Vulnerabilities

The following CVEs are tracked and accepted pending a FastAPI/starlette bundle upgrade
(tracked separately). Any NEW vulnerability not on this list will fail CI.

### No fix available

| Package | Version | CVE ID | Notes |
|---|---|---|---|
| `ecdsa` | 0.19.2 | PYSEC-2026-1325 | Transitive dep of python-jose; no upstream fix published |
| `python-jose` | 3.4.0 | PYSEC-2025-185 | No upstream fix published in any python-jose release |
| `pyasn1` | 0.4.8 | PYSEC-2026-2263, PYSEC-2026-3455–3457 | `python-jose 3.4.0` pins `pyasn1<0.5.0`; upgrading pyasn1 conflicts with python-jose's own constraint. Unfixable without switching JWT library. |

### Fix requires FastAPI/starlette upgrade (out of scope for this PR)

FastAPI 0.115.0 pins `starlette <0.38.7`. Fixing the starlette CVEs below
requires upgrading `fastapi` to a version that accepts starlette ≥0.47.2.
This is tracked as a separate dependency-upgrade task.

| Package | CVE ID | Fix version |
|---|---|---|
| `starlette` | PYSEC-2026-161  | ≥1.0.1 |
| `starlette` | PYSEC-2026-248  | ≥1.3.0 |
| `starlette` | PYSEC-2026-249  | ≥1.3.1 |
| `starlette` | PYSEC-2026-1943 | ≥0.40.0 |
| `starlette` | PYSEC-2026-1941 | ≥0.47.2 |
| `starlette` | PYSEC-2026-2281 | ≥1.1.0 |
| `starlette` | PYSEC-2026-2280 | ≥1.1.0 |

### Fixed in this PR

| Package | Old version | New version | CVEs fixed |
|---|---|---|---|
| `python-jose` | 3.3.0 | 3.4.0 | PYSEC-2024-232, PYSEC-2024-233 |
| `python-multipart` | 0.0.12 | 0.0.31 | PYSEC-2026-1851, PYSEC-2026-1852, PYSEC-2026-3036–3040 |
| `python-dotenv` | 1.0.1 | 1.2.2 | PYSEC-2026-2270 |

---

## Branch Protection

CI job names that must be required checks in GitHub Settings → Branch protection:

- `Lint (ruff)`
- `Security (bandit · pip-audit)`
- `Unit Tests (pytest)`
- `Docker Build Validation`

**Branch protection status cannot be verified from the repository.**
Configure required status checks in:
> GitHub → Settings → Branches → Branch protection rules → `main` and `develop`
