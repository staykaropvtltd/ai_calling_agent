# Exotel sandbox verification (SH-01)

Set `TELEPHONY_PROVIDER`, `EXOTEL_API_KEY`, `EXOTEL_API_SECRET`, `EXOTEL_SID`,
`EXOTEL_SUBDOMAIN`, `EXOTEL_CALLER_ID`, `EXOTEL_WEBHOOK_TOKEN`,
and `INTERNAL_API_BASE_URL` in `.env`; never commit values. The NK API must resolve
the Exotel `Called` number through `phone_numbers` to a tenant and agent.

Start Redis and the voice gateway, then expose `POST /telephony/exotel/callback`
through an HTTPS public tunnel/reverse proxy. Configure the Exotel sandbox call-flow
to POST `CallSid` and `EventType` to that URL with the configured
`X-Exotel-Webhook-Token`. Trigger a sandbox call. A `connected` callback must return
`session_started`; verify the Redis `call_session:<CallSid>` record and gateway logs.
A `completed`, `failed`, or `disconnected` callback must return `session_cleaned` and
remove the record. Check public HTTPS reachability, exact token, and Exotel account
region/subdomain first when troubleshooting.

The repository does not yet provide the required phone-number routing API, so a real
callback will return 503 until NK supplies that dependency. The supplied project documentation does not specify Exotel's audio-stream/AgentStream
contract. Confirm that contract with Exotel and wire its media URL to `/ws/{call_id}`
before claiming live Pipecat audio is verified.

For local integration tests only, set `EXOTEL_ROUTING_STUB_ENABLED=true`. It maps
`07314623519` to `test-tenant` / `test-agent` for Exotel and rejects every other
number. The default is `false`; disable it again when NK provides `phone_numbers`
routing. It is not a production fallback.
