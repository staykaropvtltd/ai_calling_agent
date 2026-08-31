import client from "./client";
import type { PaginatedResponse } from "../types/common";
import type { Campaign, CampaignCreate } from "../types/campaign";

export interface CampaignListParams {
  page?: number;
  per_page?: number;
  status?: string;
}

export async function listCampaigns(
  params: CampaignListParams = {},
): Promise<PaginatedResponse<Campaign>> {
  const { data } = await client.get<PaginatedResponse<Campaign>>("/client/campaigns", { params });
  return data;
}

export async function getCampaign(id: string): Promise<Campaign> {
  const { data } = await client.get<Campaign>(`/client/campaigns/${id}`);
  return data;
}

export async function createCampaign(payload: CampaignCreate): Promise<Campaign> {
  const { data } = await client.post<Campaign>("/client/campaigns", payload);
  return data;
}

export async function updateCampaign(
  id: string,
  payload: Partial<CampaignCreate & { status: string }>,
): Promise<Campaign> {
  const { data } = await client.put<Campaign>(`/client/campaigns/${id}`, payload);
  return data;
}

export interface UploadPreviewResponse {
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  columns: string[];
  preview: Array<{ row_number: number; data: Record<string, string>; error: string | null }>;
}

export async function previewUpload(file: File): Promise<UploadPreviewResponse> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await client.post<UploadPreviewResponse>("/client/upload/preview", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export interface ImportResult {
  imported: number;
  skipped: number;
  campaign_id: string;
}

export async function importSheet(
  file: File,
  campaignId: string,
  phoneColumn: string,
  nameColumn?: string,
  emailColumn?: string,
): Promise<ImportResult> {
  const form = new FormData();
  form.append("file", file);
  const params: Record<string, string> = {
    campaign_id: campaignId,
    phone_column: phoneColumn,
  };
  if (nameColumn) params.name_column = nameColumn;
  if (emailColumn) params.email_column = emailColumn;
  const { data } = await client.post<ImportResult>("/client/upload/import", form, {
    params,
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}
