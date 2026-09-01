// Matches GET /client/customers (CustomerResponse in services/api/src/routers/client.py)
export interface Customer {
  id: string;
  client_id: number;
  name: string | null;
  phone: string;
  email: string | null;
  language_code: string | null;
  timezone: string | null;
  country_code: string | null;
  notes: string | null;
  external_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface CustomerCreate {
  name?: string;
  phone: string;
  email?: string;
  language_code?: string;
  timezone?: string;
  country_code?: string;
  notes?: string;
  external_id?: string;
}
