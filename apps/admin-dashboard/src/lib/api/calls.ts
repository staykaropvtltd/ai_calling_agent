import client from "./client";
import type { PaginatedResponse } from "../types/tenant";
import type { CallLogEntry } from "../types/call";

export interface CallListParams {
  page?: number;
  per_page?: number;
  tenant_id?: string;
}

export async function listCalls(params: CallListParams = {}): Promise<PaginatedResponse<CallLogEntry>> {
  const { data } = await client.get<PaginatedResponse<CallLogEntry>>("/admin/calls", { params });
  return data;
}

export async function getCall(callId: number): Promise<CallLogEntry> {
  const { data } = await client.get<CallLogEntry>(`/admin/calls/${callId}`);
  return data;
}
