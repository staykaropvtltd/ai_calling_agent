# Twilio sandbox verification (SH-02)

Set the following environment variables in `.env`; **never commit values**.

```
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_PHONE_NUMBER
TWILIO_WEBHOOK_SECRET
TWILIO_TIMEOUT_SECONDS
INTERNAL_API_BASE_URL
TWILIO_ROUTING_STUB_ENABLED
ENVIRONMENT
```

## Required Twilio Console setup

1. In the [Twilio Console](https://console.twilio.com), go to **Phone Numbers → Manage → Active Numbers** and select your number.
2. Under **Voice & Fax → A Call Comes In**, set the webhook URL to:
   ```
   https://<your-public-tunnel>/telephony/twilio/callback
   ```
   and set **HTTP Method** to `POST`.
3. Under **Call Status Changes**, set the status callback URL to the same endpoint.
4. Set the `TWILIO_WEBHOOK_SECRET` env var to a strong random string and configure your Twilio number's webhook auth in the console to send `X-Twilio-Signature: <secret>` (or use an ngrok basic-auth middleware to inject the header for local testing, since Twilio's built-in signature is HMAC-SHA1 — see note below).

> **Security note:** The project uses a shared-secret model (`X-Twilio-Signature: <TWILIO_WEBHOOK_SECRET>`) consistent with the Exotel adapter. If you later switch to Twilio's standard HMAC-SHA1 request-signing algorithm, only `twilio_routes.py` needs to change — the rest of the contract is unaffected.

## Local verification steps

1. Start Redis: `docker compose up redis -d`
2. Start the voice gateway locally with all Twilio env vars set.
3. Expose port 9000 via an HTTPS tunnel (e.g., `ngrok http 9000`).
4. Configure the tunnel URL in Twilio Console (see above).
5. Trigger a test call from the Twilio sandbox.

### Expected events

| Twilio fires | Expected response body |
|---|---|
| `CallStatus=in-progress` | `{"status": "session_started", "call_id": "<uuid>"}` |
| `CallStatus=completed` | `{"status": "session_cleaned", "call_id": "<uuid>"}` |
| `CallStatus=failed` | `{"status": "session_cleaned", "call_id": "<uuid>"}` (`end_reason: provider_failure`) |

Verify the Redis `call_session:<call_id>` record is created on `session_started` and removed on `session_cleaned`.

## Local integration stub

For local tests only, set `TWILIO_ROUTING_STUB_ENABLED=true`. The stub maps `+917314623519`
to `test-tenant` / `test-agent` and rejects every other number. The default is `false`;
disable it when the real phone-number routing API is available. It is not a production fallback.

## Troubleshooting

- **401 on callback** — check `TWILIO_WEBHOOK_SECRET` matches the value sent in `X-Twilio-Signature`.
- **503 on `session_started`** — routing dependency unavailable; set `TWILIO_ROUTING_STUB_ENABLED=true` for local tests.
- **404 on `session_started`** — phone number not configured in the routing stub or NK API.
- **Tunnel reachability** — confirm the public HTTPS URL is reachable before configuring Twilio Console.
- **Region** — Twilio API requests go to `api.twilio.com`; no region subdomain needed (unlike Exotel).
