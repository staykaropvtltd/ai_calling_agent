import client from "./client";
import type { PaginatedResponse } from "../types/common";
import type { CallLogEntry, CreateCallRequest, CreateCallResponse } from "../types/call";

export interface CallListParams {
  page?: number;
  per_page?: number;
  search?: string;
}

// /client/calls is scoped to the authenticated user's tenant by the backend
// (_require_client + RLS). This app never needs to pass a tenant_id param.
export async function listCalls(params: CallListParams = {}): Promise<PaginatedResponse<CallLogEntry>> {
  const { data } = await client.get<PaginatedResponse<CallLogEntry>>("/client/calls", { params });
  return data;
}

export async function getCall(callId: number): Promise<CallLogEntry> {
  const { data } = await client.get<CallLogEntry>(`/client/calls/${callId}`);
  return data;
}

// POST /call — places an outbound AI call. Open to any authenticated role
// (tenant_admin and agent alike).
export async function createCall(payload: CreateCallRequest): Promise<CreateCallResponse> {
  const { data } = await client.post<CreateCallResponse>("/call", payload);
  return data;
}
