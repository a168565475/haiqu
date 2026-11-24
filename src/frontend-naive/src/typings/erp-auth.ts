export type ErpAccessScope = 'OWN' | 'TEAM' | 'ALL' | 'MODULE' | 'WORKSHOP' | 'CRAFT';

export interface ErpEffectiveAccess {
  active: boolean;
  is_superuser: boolean;
  roles: { id: string; name: string; code: string }[];
  actions: Record<string, {
    scopes: ErpAccessScope[];
    sources: { type: string; role_id?: string; scope?: ErpAccessScope; resource_ids?: string[] }[];
  }>;
  legacy_sources: { type: string; permission: string; name?: string; role_id?: string; group_id?: number }[];
  business_scope_enforcement: 'ENABLED' | 'PARTIAL' | 'DISABLED';
  version: string;
}

export interface ErpUser {
  id: number;
  username: string;
  display_name: string;
  is_superuser: boolean;
  employee: {
    id: string;
    employee_code: string;
    display_name: string;
    status: string;
  } | null;
  permissions: string[];
  data_scope: 'ALL' | 'ASSIGNED_AND_GRANTED' | 'NONE';
  sales_access_enabled?: boolean;
  module_access_enabled?: boolean;
  effective_access?: ErpEffectiveAccess;
}

export type ErpSession = { authenticated: true; user: ErpUser } | { authenticated: false; user: null };

export interface ErpAuthError extends Error {
  name: 'ErpAuthError';
  status: number;
  code: 'HTTP_ERROR' | 'NETWORK_ERROR' | 'INVALID_RESPONSE' | 'INVALID_CREDENTIALS' | 'CSRF_ERROR';
}
