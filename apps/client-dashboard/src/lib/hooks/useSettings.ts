import { useQuery } from "@tanstack/react-query";
import { getClientProfile } from "../api/settings";

export function useClientProfileQuery(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ["client-profile"],
    queryFn: getClientProfile,
    enabled: options.enabled,
    staleTime: 5 * 60 * 1000, // 5 min — profile rarely changes mid-session
  });
}
