import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createCustomer,
  getCustomer,
  listCustomers,
  type CustomerListParams,
} from "../api/customers";
import type { CustomerCreate } from "../types/customer";

const KEY = "customers";

export function useCustomersQuery(params: CustomerListParams, options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: [KEY, params],
    queryFn: () => listCustomers(params),
    enabled: options.enabled !== false,
  });
}

export function useCustomerQuery(customerId: string | undefined) {
  return useQuery({
    queryKey: [KEY, customerId],
    queryFn: () => getCustomer(customerId as string),
    enabled: !!customerId,
  });
}

export function useCreateCustomer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CustomerCreate) => createCustomer(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}
