import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createCall, getCall, getCallTranscript, listCalls, type CallListParams } from "../api/calls";
import type { CreateCallRequest } from "../types/call";

const KEY = "calls";

export function useCallsQuery(params: CallListParams, options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: [KEY, params],
    queryFn: () => listCalls(params),
    enabled: options.enabled,
  });
}

export function useCallQuery(callId: number | undefined) {
  return useQuery({
    queryKey: [KEY, callId],
    queryFn: () => getCall(callId as number),
    enabled: callId !== undefined && !isNaN(callId),
  });
}

export function useCallTranscript(callId: number | undefined) {
  return useQuery({
    queryKey: [KEY, callId, "transcript"],
    queryFn: () => getCallTranscript(callId as number),
    enabled: callId !== undefined && !isNaN(callId),
    retry: false,
  });
}

export function useCreateCall() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateCallRequest) => createCall(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}
