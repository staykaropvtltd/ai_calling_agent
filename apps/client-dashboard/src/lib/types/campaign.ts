export interface Campaign {
  id: string;
  client_id: number;
  name: string;
  description: string | null;
  purpose: string | null;
  status: string; // draft|scheduled|running|paused|completed|cancelled
  scheduled_at: string | null;
  max_retries: number;
  retry_delay_minutes: number;
  total_contacts: number;
  queued_count: number;
  completed_count: number;
  failed_count: number;
  no_answer_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface CampaignCreate {
  name: string;
  description?: string;
  purpose?: string;
  scheduled_at?: string;
  max_retries?: number;
  retry_delay_minutes?: number;
}
