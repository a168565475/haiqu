export type CustomerActivityStatus = 'INSUFFICIENT_DATA' | 'ACTIVE' | 'FOLLOW_UP' | 'HIGH_RISK' | 'DORMANT';

export type CustomerOrdering =
  | 'account_code'
  | '-account_code'
  | 'account_name'
  | '-account_name'
  | 'created_at'
  | '-created_at'
  | 'updated_at'
  | '-updated_at';

export interface CustomerCodeOption {
  item_code: string;
  display_name: string;
}

export interface CustomerDictionaryOption extends CustomerCodeOption {
  id: string;
  description: string;
  disabled?: boolean;
}

export interface CustomerListItem {
  id: string;
  account_code: string;
  account_name: string;
  english_name: string;
  primary_country_code: string;
  primary_region: { id: string; region_name: string } | null;
  secondary_region: { id: string; region_name: string } | null;
  customer_grade: { id: string; item_code: string; display_name: string } | null;
  activity: { activity_status: CustomerActivityStatus; display_name: string } | null;
  primary_owner: { id: string; employee_code: string; display_name: string } | null;
  last_12m_sales_amount: string | null;
  recent_order: {
    id: string;
    order_number: string;
    order_date: string;
    status: string;
    status_display: string;
    currency_code: string;
    total_amount: string;
  } | null;
  last_contact_at: string | null;
  next_follow_up_at: string | null;
}

export interface CustomerListQuery {
  page?: number;
  page_size?: number;
  ordering?: CustomerOrdering;
  q?: string;
  customer_grade?: string;
  country_code?: string;
  activity_status?: CustomerActivityStatus;
}

export interface CustomerOptions {
  country_options: CustomerDictionaryOption[];
  customer_grades: CustomerDictionaryOption[];
  activity_statuses: CustomerCodeOption[];
}

export interface CustomerPage {
  data: CustomerListItem[];
  meta: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  };
}

export interface ErpApiError extends Error {
  name: 'ErpApiError';
  status: number;
  code: 'HTTP_ERROR' | 'NETWORK_ERROR' | 'INVALID_RESPONSE' | 'INVALID_QUERY';
}
