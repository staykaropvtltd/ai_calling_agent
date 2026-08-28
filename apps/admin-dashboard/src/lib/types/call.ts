// Matches GET /admin/calls' CallResponse (services/api/src/routers/admin.py).
// This is the legacy call_requests log (the Caller model) — NOT the real
// call lifecycle (Call/CallTurn/CallEvent), which no /admin/* endpoint
// exposes yet. See the Phase 7 plan's "explicitly out of scope" note.
export interface CallLogEntry {
  id: number;
  customer_name: string | null;
  phone_number: string | null;
  hotel_name: string | null;
  check_in_date: string | null;
  check_out_date: string | null;
  client_id: number | null;
  created_at: string | null; // ISO8601
}
