// Matches GET /admin/calls' CallResponse (services/api/src/routers/admin.py).
// This is the legacy call_requests log (the Caller model) — NOT the real
// call lifecycle (Call/CallTurn/CallEvent), which no /admin/* endpoint
// exposes yet.
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

// Matches POST /call's CallerRequest (services/api/src/main.py). Any
// authenticated role may place a call — there is no admin-role gate on
// this endpoint.
export interface CreateCallRequest {
  customer_name: string;
  phone_number: string; // E.164, e.g. +919876543210
  hotel_name: string;
  check_in_date: string; // YYYY-MM-DD
  check_out_date: string; // YYYY-MM-DD
}

export interface CreateCallResponse {
  status: string;
  database: string;
  redis_session: string | null;
}
