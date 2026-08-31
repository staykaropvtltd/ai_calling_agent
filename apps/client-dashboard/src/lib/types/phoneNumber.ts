// Matches GET /admin/phone-numbers (PhoneNumberResponse in services/api/src/routers/admin.py).
// Source: phone_number_routes table (PhoneNumberRoute model).
export interface PhoneNumber {
  number: string;
  tenant_id: string;
  agent_id: string;
  provider: string;
  created_at: string | null;
}
