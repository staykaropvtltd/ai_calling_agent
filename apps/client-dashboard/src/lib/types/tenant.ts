// Matches GET /client/me (ClientProfile in services/api/src/routers/client.py).
export interface ClientProfile {
  // User fields
  user_id: string;
  email: string;
  full_name: string;
  role: string;
  permissions: string[];

  // Tenant / client fields
  tenant_id: string;
  tenant_name: string;
  tenant_slug: string | null;
  plan: string | null;
  tenant_status: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  max_concurrent_calls: number | null;
  api_limit: number | null;

  // Internationalisation
  country: string | null;           // ISO 3166-1 α-2 e.g. "AE", "IN"
  timezone: string | null;          // IANA e.g. "Asia/Dubai", "Asia/Kolkata"
  currency: string | null;          // ISO 4217 e.g. "AED", "INR"
  default_language: string | null;  // BCP 47 e.g. "en", "ar"
  phone_country_code: string | null; // e.g. "+971", "+91"
}
