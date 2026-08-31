import { useQuery } from "@tanstack/react-query";
import { listPhoneNumbers, type PhoneNumberListParams } from "../api/phoneNumbers";

export function usePhoneNumbersQuery(
  params: PhoneNumberListParams = {},
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: ["phone-numbers", params],
    queryFn: () => listPhoneNumbers(params),
    enabled: options.enabled,
  });
}
