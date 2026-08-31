import { useQuery } from "@tanstack/react-query";
import { getAnalytics } from "../api/analytics";

export function useAnalyticsQuery(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ["analytics"],
    queryFn: getAnalytics,
    enabled: options.enabled,
  });
}
