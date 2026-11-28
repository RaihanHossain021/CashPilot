export interface UserOut {
  id: string;
  email: string;
  name: string;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: 'bearer';
  user: UserOut;
}

export interface BusinessOut {
  id: string;
  owner_id: string;
  name: string;
  vertical: 'grocery' | 'service' | 'other';
  currency: string;
  min_cash_reserve: string;
  slow_stock_days_threshold: number;
  created_at: string;
}

export interface BusinessCreatePayload {
  name: string;
  vertical: 'grocery' | 'service' | 'other';
  currency: string;
  min_cash_reserve: string;
  slow_stock_days_threshold: number;
}

export interface BusinessUpdatePayload {
  name?: string;
  vertical?: 'grocery' | 'service' | 'other';
  currency?: string;
  min_cash_reserve?: string;
  slow_stock_days_threshold?: number;
}

export interface CustomerOut {
  id: string;
  business_id: string;
  name: string;
  phone: string | null;
}

export interface SupplierOut {
  id: string;
  business_id: string;
  name: string;
  phone: string | null;
}

export interface ProductOut {
  id: string;
  business_id: string;
  name: string;
  sku: string;
  kind: 'goods' | 'service';
  unit: string;
  track_inventory: boolean;
  reorder_level: string;
  sale_price: string;
  avg_cost: string;
  expiry_date: string | null;
}

export interface ProductCreatePayload {
  name: string;
  sku: string;
  kind: 'goods' | 'service';
  unit: string;
  track_inventory: boolean;
  reorder_level: string;
  sale_price: string;
  avg_cost: string;
}

export interface TransactionItemOut {
  id: string;
  product_id: string | null;
  qty: string;
  unit_price: string;
  unit_cost_snapshot: string;
}

export interface TransactionOut {
  id: string;
  business_id: string;
  type: 'sale' | 'purchase' | 'expense' | 'sale_return' | 'purchase_return';
  original_transaction_id: string | null;
  customer_id: string | null;
  supplier_id: string | null;
  date: string;
  due_date: string | null;
  total: string;
  discount: string;
  status: 'posted' | 'void';
  idempotency_key: string | null;
  notes: string | null;
  created_at: string;
  amount_paid: string;
  returns_total: string;
  balance_due: string;
  items: TransactionItemOut[];
}

export interface TransactionCreatePayload {
  type: 'sale' | 'purchase' | 'expense' | 'sale_return' | 'purchase_return';
  original_transaction_id?: string | null;
  customer_id?: string | null;
  supplier_id?: string | null;
  date: string;
  due_date?: string | null;
  discount?: string;
  paid_amount?: string;
  expense_amount?: string | null;
  idempotency_key?: string | null;
  notes?: string | null;
  items?: Array<{
    product_id?: string | null;
    qty: string;
    unit_price?: string | null;
  }>;
}

export interface ForecastDayOut {
  date: string;
  opening_cash: string;
  confirmed_inflows: string;
  expected_inflows: string;
  estimated_inflows: string;
  confirmed_outflows: string;
  expected_outflows: string;
  estimated_outflows: string;
  closing_cash: string;
  below_reserve: boolean;
}

export interface CashGapCauseOut {
  kind: 'outflow' | 'overdue_receivable';
  label: string;
  amount: string;
  due_on: string | null;
  record_id: string | null;
}

export interface ForecastResponse {
  currency: string;
  as_of: string;
  horizon_days: 7 | 14 | 30;
  limited_data: boolean;
  history_days: number;
  min_cash_reserve: string;
  lowest_cash_amount: string;
  lowest_cash_date: string;
  estimated_cash_gap_vs_reserve: string;
  estimated_cash_gap_vs_zero: string;
  gap_start_date: string | null;
  unlockable_slow_stock_value: string;
  assumptions_note: string;
  causes: CashGapCauseOut[];
  daily: ForecastDayOut[];
}

export interface ReadinessDimensionOut {
  key: string;
  label: string;
  status: 'green' | 'amber' | 'red';
  summary: string;
  evidence: Record<string, string>;
  improvement_action: string;
}

export interface ReadinessResponse {
  currency: string;
  overall_status: 'green' | 'amber' | 'red';
  disclaimer: string;
  dimensions: ReadinessDimensionOut[];
}

export interface RecommendationOut {
  code: string;
  title: string;
  issue: string;
  evidence: string;
  suggested_action: string;
  estimated_impact: string;
  limitations: string;
}

export interface DashboardResponse {
  currency: string;
  period_days: number;
  cash_on_hand: string;
  min_cash_reserve: string;
  customers_owe: string;
  overdue_receivables: string;
  we_owe_suppliers: string;
  total_stock_value: string;
  slow_stock_value_flagged: string;
  slow_stock_pct_of_inventory: string;
  estimated_cash_gap_vs_reserve: string;
  estimated_cash_gap_vs_zero: string;
  gap_date: string | null;
  incomplete_data: boolean;
  readiness_summary: ReadinessResponse;
  recommendations: RecommendationOut[];
}

export interface InventoryItemOut {
  product_id: string;
  name: string;
  sku: string;
  unit: string;
  track_inventory: boolean;
  on_hand_qty: string;
  avg_cost: string;
  stock_value: string;
  sale_price: string;
  reorder_level: string;
  units_sold_window: string;
  daily_velocity: string;
  days_of_stock: string | null;
  slow_stock: boolean;
  low_stock: boolean;
  first_received_date: string | null;
}

export interface InventoryResponse {
  currency: string;
  as_of: string;
  velocity_window_days: number;
  slow_stock_days_threshold: number;
  total_stock_value: string;
  slow_stock_value_flagged: string;
  slow_stock_pct_of_inventory: string;
  items: InventoryItemOut[];
}

export interface PartyBalanceOut {
  id: string;
  kind: 'customer' | 'supplier';
  name: string;
  phone: string | null;
  balance_due: string;
  overdue_amount: string;
  earliest_due_date: string | null;
}

export interface PartiesBalanceResponse {
  currency: string;
  as_of: string;
  customers: PartyBalanceOut[];
  suppliers: PartyBalanceOut[];
}

export interface SeedDemoResponse {
  business_id: string;
  business_name: string;
  demo_email: string;
  demo_password: string;
  reference_date: string;
}
