# NH-16 — n8n Licensing & Tenant-Isolation Decision

**Status:** Written recommendation, NOT a final decision — this needs a human
(and ideally n8n's own licensing team) to sign off before anyone builds
against it. Per the Execution Plan: NH-16's "done when" is *"written go/no-go
decision,"* not *"code that assumes an answer."*

**Recommendation: NO-GO on self-hosted n8n (Community Edition) for
Staykaro's automation use case. Build the automation directly in
`services/integration-service` instead.** Details and reasoning below.

## The question

NH-13 (Integration service), NH-14 (Email/WhatsApp automation), and NH-15
(CRM adapter framework) all need something that, after a call ends, reads
`integration_events` and dispatches to email/WhatsApp/CRM providers per
tenant. n8n was the assumed tool for this. Two separate questions determine
whether that assumption holds:

1. **Licensing** — does Staykaro's use of n8n fall under the free
   Sustainable Use License, or does it need a paid plan?
2. **Tenant isolation** — even if licensing is fine, can one n8n instance
   safely run workflows for multiple tenants without cross-tenant leakage?

## 1. Licensing

n8n ships under a "fair-code" model: the Sustainable Use License (SUL) is
free but restricted; the n8n Enterprise License is paid and unrestricted.
The SUL explicitly permits internal use — a team automating its own
operations — and explicitly does **not** permit reselling n8n, white-labeling
it, or hosting it for paying customers.

Staykaro's case sits in the grey area the SUL's own community has been
asked about directly: workflows that live entirely behind Staykaro's API,
never shown to any tenant, triggered only by Staykaro's own backend. On the
surface that looks like "internal use." A near-identical case was raised on
n8n's own community forum — a SaaS company asking whether using self-hosted
n8n as an internal automation backend for their own product (customers never
see n8n) is covered by the SUL. The clarified answer from n8n community
moderators:

> The deciding factor isn't whether customers see n8n's UI — it's whose
> credentials/data n8n processes, and whether customers derive value from
> n8n's automation logic, even indirectly. If they do, that's very likely
> **not** covered by the free Sustainable Use License and needs a paid
> Business/Enterprise plan.

That is exactly Staykaro's shape: a hotel client's post-call
email/WhatsApp/CRM follow-up is real value the *client* receives, powered by
n8n, even though the client never opens n8n's editor. Reading the SUL's own
restriction list (no reselling, no hosting-for-customers, no
white-labeling) generously enough to cover this is the kind of judgment call
the same thread explicitly warned against making unilaterally: *"you want
that answer in writing before it's load-bearing for your pricing."*

**Conclusion:** self-hosting n8n Community Edition for this feature is very
likely a licensing violation, not a supported free use case. Treating it as
free without written confirmation from n8n (`license@n8n.io`, with an actual
architecture diagram, per that same thread's advice) is a real legal/business
risk, not a technicality — not something to build a production feature on
speculatively.

## 2. Tenant isolation (the part that would still matter even with a paid plan)

Independent of licensing, n8n Community Edition has no native
multi-tenant RBAC — no concept of "this workflow belongs to tenant A and must
never see tenant B's credentials or trigger data." A single shared instance
running workflows for every tenant relies entirely on whoever authors each
workflow remembering to scope it correctly, by convention, with nothing in
n8n itself enforcing that.

That's a meaningfully worse isolation story than everywhere else in this
codebase. NK-07's PostgreSQL RLS — the actual precedent here — was built
specifically so tenant isolation does **not** depend on someone remembering
to filter correctly: it fails closed (zero rows) when a request forgets to
set tenant context, rather than failing open. A shared n8n instance is the
opposite shape: it fails open — a workflow that forgets to scope by tenant
doesn't error, it silently touches the wrong tenant's data. For a platform
whose Checkpoint 4 gate is "ANY unauthorized cross-tenant success = HARD
STOP," introducing one component that structurally can't offer that
guarantee is a bad trade, independent of whether it's legally licensed.

The credential-handling pattern the same community thread suggested — n8n
never holds tenant credentials directly, only calls back into a trusted
internal service that holds them (exactly what NH-13's `integration-service`
already is, per its own design: it "decouples the live call from automation
entirely," polling `integration_events` rather than n8n reaching into
tenant data directly) — closes part of this gap. But it also means n8n
would be doing very little in that architecture beyond being a workflow
*trigger* for logic that already has to live in `integration-service` anyway
to hold the credentials safely. At that point n8n adds licensing risk and an
extra moving part without buying much isolation or functionality that
`integration-service` doesn't already need to have.

## Recommendation

**Don't adopt n8n for NH-13/14/15.** Build the dispatch logic directly in
`services/integration-service` (already scaffolded, already Python/FastAPI
matching the rest of the stack):

- **NH-13** (integration service, async event path): a worker loop polling
  `integration_events` (`status: pending → processed/failed`, per Database
  Design §5) — this needs to exist regardless of what dispatches the actual
  automation, n8n or not.
- **NH-14** (email/WhatsApp automation) and **NH-15** (CRM adapter
  framework): a small per-provider adapter interface (mirroring the
  telephony provider pattern SH-01/SH-02 already established) — each
  adapter is maybe 50-100 lines against one provider's API, not a workflow
  engine's worth of complexity.

This gets tenant isolation via the *same* mechanism already proven
throughout this codebase (RLS + `get_tenant_scoped_db`, per NK-07/NK-08),
not a second, weaker isolation story to reason about. It also sidesteps the
licensing question entirely — no fair-code license to interpret, no
`license@n8n.io` email to wait on.

**If the team still wants n8n's visual editor specifically** (e.g., as an
internal ops tool for Staykaro's own team to build ad hoc automations, not
customer-facing per-tenant workflows): that's a much cleaner Sustainable Use
License fit — internal team tooling is squarely what the SUL is for — but
still get it in writing from n8n before relying on it, and never route
tenant-specific credentials or data through it directly; only ever through
`integration-service` acting as the credential-holding intermediary.

## What would change this recommendation

- Written confirmation from n8n (`license@n8n.io`) that Staykaro's specific
  architecture is SUL-covered, in which case only the isolation question
  (§2) remains, and per-tenant workflow scoping discipline (with review)
  becomes the mitigation.
- A budget decision to pay for n8n Enterprise, in which case its RBAC/
  environments features may address §2 too — Enterprise-tier isolation
  features weren't evaluated here since the licensing question alone was
  already reason enough to stop and write this up rather than build further.

## Sources

- [n8n Sustainable Use License — official docs](https://docs.n8n.io/sustainable-use-license/)
- [n8n community forum — "Sustainable Use License clarification regarding use as an integration backend"](https://community.n8n.io/t/sustainable-use-license-clarification-regarding-use-as-an-integration-backend/305902)
- [n8n Sustainable Use License Explained Simply — Nordflux](https://nordflux.de/en/guides/the-n8n-sustainable-use-license-explained)
- [n8n Licensing 101 — FatCamel](https://www.fatcamel.ai/blog/n8n-licensing-101-understanding-commercial-embed-and-sustainable-use-licenses)

Researched 2026-08-29. License terms can change — re-verify against
n8n's current docs before this decision is acted on if significant time has
passed.
