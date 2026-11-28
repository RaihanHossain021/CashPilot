import type {
  AdvisorAskResponse,
  AdvisorLogOut,
  BusinessCreatePayload,
  BusinessOut,
  BusinessUpdatePayload,
  CustomerOut,
  DashboardResponse,
  ForecastResponse,
  InventoryResponse,
  PartiesBalanceResponse,
  ProductCreatePayload,
  ProductOut,
  ReadinessResponse,
  SeedDemoResponse,
  SupplierOut,
  TokenResponse,
  TransactionCreatePayload,
  TransactionOut,
} from './types'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
const TOKEN_STORAGE_KEY = 'cashpilot_access_token'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY)
}

export function setStoredToken(token: string | null): void {
  if (token) {
    localStorage.setItem(TOKEN_STORAGE_KEY, token)
  } else {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
  }
}

export function formatMoney(decimalStr: string | number | null | undefined, currency: string): string {
  if (decimalStr === null || decimalStr === undefined) return `0.00 ${currency}`
  const num = typeof decimalStr === 'number' ? decimalStr : Number(decimalStr)
  if (!Number.isFinite(num)) return `${decimalStr} ${currency}`
  return `${num.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 })} ${currency}`
}

export function formatQty(decimalStr: string): string {
  const num = Number(decimalStr)
  if (!Number.isFinite(num)) return decimalStr
  return num.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 })
}

export function newIdempotencyKey(prefix: string): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}-${crypto.randomUUID()}`
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getStoredToken()
  const headers = new Headers(options.headers)
  if (!headers.has('Content-Type') && options.body) {
    headers.set('Content-Type', 'application/json')
  }
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  })

  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const errBody = (await res.json()) as { detail?: unknown }
      if (typeof errBody.detail === 'string') {
        detail = errBody.detail
      } else if (Array.isArray(errBody.detail) && errBody.detail.length > 0) {
        detail = errBody.detail
          .map((e) => (typeof e === 'object' && e && 'msg' in e ? String(e.msg) : String(e)))
          .join('; ')
      }
    } catch {
      // ignore non-JSON errors
    }
    throw new ApiError(res.status, detail)
  }

  return (await res.json()) as T
}

export const api = {
  register(payload: { email: string; password: string; name: string }): Promise<TokenResponse> {
    return request<TokenResponse>('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  login(payload: { email: string; password: string }): Promise<TokenResponse> {
    return request<TokenResponse>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  seedDemo(): Promise<SeedDemoResponse> {
    return request<SeedDemoResponse>('/api/v1/dev/seed', { method: 'POST' })
  },
  getBusiness(): Promise<BusinessOut> {
    return request<BusinessOut>('/api/v1/business')
  },
  createBusiness(payload: BusinessCreatePayload): Promise<BusinessOut> {
    return request<BusinessOut>('/api/v1/business', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  updateBusiness(payload: BusinessUpdatePayload): Promise<BusinessOut> {
    return request<BusinessOut>('/api/v1/business', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },
  getDashboard(days: 14 | 30 = 14): Promise<DashboardResponse> {
    return request<DashboardResponse>(`/api/v1/dashboard?days=${days}`)
  },
  getReadiness(days: 14 | 30 = 14): Promise<ReadinessResponse> {
    return request<ReadinessResponse>(`/api/v1/readiness?days=${days}`)
  },
  getForecast(days: 7 | 14 | 30 = 14): Promise<ForecastResponse> {
    return request<ForecastResponse>(`/api/v1/cashflow/forecast?days=${days}`)
  },
  getInventory(): Promise<InventoryResponse> {
    return request<InventoryResponse>('/api/v1/inventory')
  },
  getPartiesBalances(): Promise<PartiesBalanceResponse> {
    return request<PartiesBalanceResponse>('/api/v1/parties/balances')
  },
  listCustomers(): Promise<CustomerOut[]> {
    return request<CustomerOut[]>('/api/v1/customers')
  },
  createCustomer(payload: { name: string; phone?: string | null }): Promise<CustomerOut> {
    return request<CustomerOut>('/api/v1/customers', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  listSuppliers(): Promise<SupplierOut[]> {
    return request<SupplierOut[]>('/api/v1/suppliers')
  },
  createSupplier(payload: { name: string; phone?: string | null }): Promise<SupplierOut> {
    return request<SupplierOut>('/api/v1/suppliers', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  listProducts(): Promise<ProductOut[]> {
    return request<ProductOut[]>('/api/v1/products')
  },
  createProduct(payload: ProductCreatePayload): Promise<ProductOut> {
    return request<ProductOut>('/api/v1/products', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  listTransactions(params?: { type?: string; unpaidOnly?: boolean }): Promise<TransactionOut[]> {
    const query = new URLSearchParams()
    if (params?.type) query.set('type', params.type)
    if (params?.unpaidOnly) query.set('unpaid_only', 'true')
    const qs = query.toString()
    return request<TransactionOut[]>(`/api/v1/transactions${qs ? `?${qs}` : ''}`)
  },
  createTransaction(payload: TransactionCreatePayload): Promise<TransactionOut> {
    return request<TransactionOut>('/api/v1/transactions', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  recordPayment(
    transactionId: string,
    payload: { amount: string; date: string; idempotency_key: string; note?: string },
  ): Promise<unknown> {
    return request(`/api/v1/transactions/${transactionId}/payments`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  setOpeningCash(payload: { amount: string; date: string; note?: string }): Promise<unknown> {
    return request('/api/v1/cash/opening', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  setOpeningStock(payload: {
    product_id: string
    qty: string
    unit_cost: string
    date?: string
  }): Promise<unknown> {
    return request('/api/v1/inventory/opening', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  askAdvisor(question: string): Promise<AdvisorAskResponse> {
    return request<AdvisorAskResponse>('/api/v1/advisor/ask', {
      method: 'POST',
      body: JSON.stringify({ question }),
    })
  },
  getAdvisorHistory(): Promise<AdvisorLogOut[]> {
    return request<AdvisorLogOut[]>('/api/v1/advisor/history')
  },
}
