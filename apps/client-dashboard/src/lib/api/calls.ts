import client from "./client";
import type { PaginatedResponse } from "../types/common";
import type { CallLogEntry, CreateCallRequest, CreateCallResponse } from "../types/call";

export interface CallListParams {
  page?: number;
  per_page?: number;
}

// /admin/calls is tenant-scoped server-side for tenant_admin tokens
// (services/api/src/routers/admin.py's list_calls ignores any tenant_id
// query param for that role and binds to the JWT's client_id instead) —
// this app never needs to pass one.
export async function listCalls(params: CallListParams = {}): Promise<PaginatedResponse<CallLogEntry>> {
  const { data } = await client.get<PaginatedResponse<CallLogEntry>>("/admin/calls", { params });
  return data;
}

export async function getCall(callId: number): Promise<CallLogEntry> {
  const { data } = await client.get<CallLogEntry>(`/admin/calls/${callId}`);
  return data;
}

// POST /call — places an outbound AI call. Open to any authenticated role
// (tenant_admin and agent alike), unlike the /admin/* routes above.
export async function createCall(payload: CreateCallRequest): Promise<CreateCallResponse> {
  const { data } = await client.post<CreateCallResponse>("/call", payload);
  return data;
}
