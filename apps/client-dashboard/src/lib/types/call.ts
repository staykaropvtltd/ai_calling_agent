// Matches GET /client/calls and GET /client/calls/{id} (CallResponse in
// services/api/src/routers/client.py). Includes Phase 1 fields added in
// migration c3d4e5f6a7b8.
export interface CallLogEntry {
  id: number;
  customer_name: string | null;
  phone_number: string | null;
  hotel_name: string | null;
  check_in_date: string | null;
  check_out_date: string | null;
  created_at: string | null; // ISO8601
  // Phase 1 fields
  status: string | null; // pending|queued|dialing|ringing|connected|in_progress|completed|failed|cancelled|no_answer|voicemail
  call_type: string | null; // inbound|outbound
  is_simulation: boolean | null;
  customer_id: string | null;
  connection_status: string | null; // not_attempted|attempted|connected|failed_pre_connect
  failure_reason: string | null;
  duration_seconds: number | null;
  outcome: string | null;
}

// One turn in a call conversation (CallTurn model).
export interface CallTurn {
  turn_id: string;
  speaker: "caller" | "agent";
  text: string;
  started_at: string; // ISO8601
  language_code: string | null;
}

// Matches POST /call's CallerRequest (services/api/src/main.py).
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
