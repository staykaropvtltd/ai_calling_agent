import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createCampaign,
  getCampaign,
  importSheet,
  listCampaigns,
  previewUpload,
  updateCampaign,
  type CampaignListParams,
} from "../api/campaigns";
import type { CampaignCreate } from "../types/campaign";

const KEY = "campaigns";

export function useCampaignsQuery(
  params: CampaignListParams,
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: [KEY, params],
    queryFn: () => listCampaigns(params),
    enabled: options.enabled !== false,
  });
}

export function useCampaignQuery(id: string | undefined) {
  return useQuery({
    queryKey: [KEY, id],
    queryFn: () => getCampaign(id as string),
    enabled: !!id,
  });
}

export function useCreateCampaign() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CampaignCreate) => createCampaign(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}

export function useUpdateCampaign() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...payload }: { id: string } & Partial<CampaignCreate & { status: string }>) =>
      updateCampaign(id, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}

export function usePreviewUpload() {
  return useMutation({
    mutationFn: (file: File) => previewUpload(file),
  });
}

export function useImportSheet() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      file,
      campaignId,
      phoneColumn,
      nameColumn,
      emailColumn,
    }: {
      file: File;
      campaignId: string;
      phoneColumn: string;
      nameColumn?: string;
      emailColumn?: string;
    }) => importSheet(file, campaignId, phoneColumn, nameColumn, emailColumn),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [KEY] });
      queryClient.invalidateQueries({ queryKey: ["customers"] });
    },
  });
}
