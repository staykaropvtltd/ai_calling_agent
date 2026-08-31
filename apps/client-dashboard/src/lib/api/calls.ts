import client from "./client";
import type { PaginatedResponse } from "../types/common";
import type { CallLogEntry, CallTurn, CreateCallRequest, CreateCallResponse } from "../types/call";

export interface CallListParams {
  page?: number;
  per_page?: number;
  search?: string;
  status?: string;
}

export async function listCalls(params: CallListParams = {}): Promise<PaginatedResponse<CallLogEntry>> {
  const { data } = await client.get<PaginatedResponse<CallLogEntry>>("/client/calls", { params });
  return data;
}

export async function getCall(callId: number): Promise<CallLogEntry> {
  const { data } = await client.get<CallLogEntry>(`/client/calls/${callId}`);
  return data;
}

export async function getCallTranscript(callId: number): Promise<CallTurn[]> {
  const { data } = await client.get<CallTurn[]>(`/client/calls/${callId}/transcript`);
  return data;
}

export async function createCall(payload: CreateCallRequest): Promise<CreateCallResponse> {
  const { data } = await client.post<CreateCallResponse>("/call", payload);
  return data;
}
