import client from "./client";
import type { PaginatedResponse } from "../types/common";
import type { Customer, CustomerCreate } from "../types/customer";

export interface CustomerListParams {
  page?: number;
  per_page?: number;
  search?: string;
}

export async function listCustomers(
  params: CustomerListParams = {},
): Promise<PaginatedResponse<Customer>> {
  const { data } = await client.get<PaginatedResponse<Customer>>("/client/customers", { params });
  return data;
}

export async function getCustomer(customerId: string): Promise<Customer> {
  const { data } = await client.get<Customer>(`/client/customers/${customerId}`);
  return data;
}

export async function createCustomer(payload: CustomerCreate): Promise<Customer> {
  const { data } = await client.post<Customer>("/client/customers", payload);
  return data;
}
