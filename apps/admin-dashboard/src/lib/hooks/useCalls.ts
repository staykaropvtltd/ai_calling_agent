import { useQuery } from "@tanstack/react-query";
import { getCall, listCalls, type CallListParams } from "../api/calls";

const KEY = "calls";

export function useCallsQuery(params: CallListParams) {
  return useQuery({
    queryKey: [KEY, params],
    queryFn: () => listCalls(params),
  });
}

export function useCallQuery(callId: number | undefined) {
  return useQuery({
    queryKey: [KEY, callId],
    queryFn: () => getCall(callId as number),
    enabled: callId !== undefined,
  });
}
