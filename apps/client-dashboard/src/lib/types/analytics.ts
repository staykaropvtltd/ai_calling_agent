// Matches GET /admin/analytics (AnalyticsResponse in services/api/src/routers/admin.py).
// Data source: call_requests table (Caller model) — each row is one POST /call request.
export interface CallVolumeDay {
  date: string; // YYYY-MM-DD
  count: number;
}

export interface AnalyticsData {
  total_calls: number;
  calls_this_month: number;
  calls_this_week: number;
  daily_volume: CallVolumeDay[];
}
