import client from "./client";
import type { PaginatedResponse } from "../types/common";
import type { PhoneNumber } from "../types/phoneNumber";

export interface PhoneNumberListParams {
  page?: number;
  per_page?: number;
}

export async function listPhoneNumbers(
  params: PhoneNumberListParams = {},
): Promise<PaginatedResponse<PhoneNumber>> {
  const { data } = await client.get<PaginatedResponse<PhoneNumber>>("/client/phone-numbers", {
    params,
  });
  return data;
}
