/**
 * Type-Safe API Client & Domain Models for the Prediction Market Platform.
 * Backend contract: FastAPI app (app/main.py) — auth, collateral, markets,
 * CLOB orders, positions, CTF settlement, oracle resolution.
 */

const API_BASE = import.meta.env.VITE_API_URL || '';

export class ApiError extends Error {
  constructor(public status: number, message: string, public data?: any) {
    super(message);
    this.name = 'ApiError';
  }
}

// ---------------------------------------------------------------------------
// Domain models (mirroring SQLAlchemy schemas)
// ---------------------------------------------------------------------------

export type EventStatus = 'ACTIVE' | 'CLOSED' | 'RESOLVED';
export type MarketStatus =
  | 'ACTIVE'
  | 'SUSPENDED'
  | 'CLOSED'
  | 'IN_RESOLUTION'
  | 'DISPUTED'
  | 'RESOLVED';
export type Category = 'Politics' | 'Crypto' | 'Sports' | 'Macro' | 'Pop Culture' | 'Tech';

export interface OutcomeToken {
  token_id: string;
  outcome_index: number;
  symbol: string;
}

export interface Market {
  id: string;
  event_id: string;
  condition_id: string;
  question: string;
  outcomes: string[];
  tick_size: number;
  min_order_size: number;
  status: MarketStatus;
  neg_risk: boolean;
  winning_outcome_index: number | null;
  created_at: string;
  tokens: OutcomeToken[];
}

export interface Event {
  id: string;
  slug: string;
  title: string;
  description: string | null;
  category: string;
  tags: string[];
  status: EventStatus;
  end_date: string | null;
  total_volume: number;
  markets?: Market[];
}

export interface OrderBookLevel {
  price: number;
  size: number;
}

export interface OrderBookSnapshot {
  token_id: string;
  bids: [string, number][];
  asks: [string, number][];
  timestamp: number;
}

export interface Ticker {
  token_id: string;
  last_price: number | null;
  bbo: { best_bid: number | null; best_ask: number | null };
  volume_24h: number;
}

export interface Candle {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Order {
  id: string | null;
  market_id: string;
  token_id: string;
  side: 'BUY' | 'SELL';
  type: 'LIMIT' | 'MARKET';
  price: number;
  amount: number;
  filled_amount: number;
  status: string;
  time_in_force: string;
  created_at: string;
}

export interface OrderFill {
  id: string;
  price: number;
  shares: number;
  maker_fee: number;
  taker_fee: number;
  timestamp: string;
}

export interface Position {
  position_id: string;
  market_id: string;
  token_id: string;
  outcome_symbol: string | null;
  market_question: string | null;
  event_title: string | null;
  event_slug: string | null;
  market_status: MarketStatus | null;
  shares: number;
  locked_shares: number;
  avg_entry_price: number;
  current_price: number | null;
  unrealized_pnl: number | null;
  realized_pnl: number;
  is_settled: boolean;
  claimed: boolean;
}

export interface Balance {
  user_id: string;
  balance: number;
  locked_balance: number;
  available: number;
  currency: string;
}

export interface LedgerEntry {
  id: string;
  kind: string;
  amount: number;
  reference: string | null;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: { id: string; email: string };
}

export interface TradeTicketInput {
  market_id: string;
  token_id: string;
  side: 'BUY' | 'SELL';
  type: 'LIMIT' | 'MARKET';
  price: number | null;
  amount: number;
  time_in_force: 'GTC' | 'IOC' | 'FOK';
  post_only: boolean;
}

// ---------------------------------------------------------------------------
// Token storage
// ---------------------------------------------------------------------------

const TOKEN_KEY = 'pm_auth_token';

export function getStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setStoredToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* ignore */
  }
}

export function clearStoredToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

type ToastHandler = (message: string, kind: 'error' | 'info') => void;
let toastHandler: ToastHandler | null = null;
export function setToastHandler(handler: ToastHandler): void {
  toastHandler = handler;
}

function extractDetail(data: any): string {
  if (typeof data === 'string') return data;
  if (data?.detail) return typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
  if (data?.message) return data.message;
  return '';
}

export class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
  }

  private async request<T>(path: string, options: RequestInit = {}, auth = true): Promise<T> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...((options.headers as Record<string, string>) || {}),
    };
    if (auth) {
      const token = getStoredToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;
    }

    let res: Response;
    try {
      res = await fetch(`${this.baseUrl}${path}`, { ...options, headers });
    } catch (err: any) {
      const msg = `Network error: ${err?.message ?? 'backend unreachable'}`;
      toastHandler?.(msg, 'error');
      throw new ApiError(0, msg);
    }

    if (!res.ok) {
      let data: any;
      try {
        data = await res.json();
      } catch {
        data = await res.text();
      }
      const msg = extractDetail(data) || `Request failed (${res.status})`;
      toastHandler?.(msg, res.status === 401 || res.status === 403 ? 'error' : 'error');
      if (res.status === 401) clearStoredToken();
      throw new ApiError(res.status, msg, data);
    }

    if (res.status === 204) return null as T;
    return res.json() as Promise<T>;
  }

  private fmt(v: number | string): string {
    return String(v);
  }

  // ---- Auth ---------------------------------------------------------------

  async register(email: string, password: string): Promise<AuthResponse> {
    const data = await this.request<AuthResponse>(
      '/api/v1/auth/register',
      { method: 'POST', body: JSON.stringify({ email, password }) },
      false
    );
    setStoredToken(data.access_token);
    return data;
  }

  async login(email: string, password: string): Promise<AuthResponse> {
    const data = await this.request<AuthResponse>(
      '/api/v1/auth/login',
      { method: 'POST', body: JSON.stringify({ email, password }) },
      false
    );
    setStoredToken(data.access_token);
    return data;
  }

  logout(): void {
    clearStoredToken();
  }

  // ---- Collateral ---------------------------------------------------------

  getBalance(): Promise<Balance> {
    return this.request('/api/v1/collateral/balance');
  }

  deposit(amount: number): Promise<Balance> {
    return this.request('/api/v1/collateral/deposit', {
      method: 'POST',
      body: JSON.stringify({ amount }),
    });
  }

  withdraw(amount: number): Promise<Balance> {
    return this.request('/api/v1/collateral/withdraw', {
      method: 'POST',
      body: JSON.stringify({ amount }),
    });
  }

  getLedger(): Promise<{ entries: LedgerEntry[] }> {
    return this.request('/api/v1/collateral/ledger');
  }

  // ---- Public discovery ----------------------------------------------------

  listEvents(params: { status?: string; category?: string; sort_by?: string; search?: string; cursor?: string; limit?: number } = {}): Promise<{
    events: Event[];
    next_cursor: string | null;
    total_count: number;
  }> {
    const qs = new URLSearchParams();
    if (params.status) qs.set('status', params.status);
    if (params.category) qs.set('category', params.category);
    if (params.sort_by) qs.set('sort_by', params.sort_by);
    if (params.search) qs.set('search', params.search);
    if (params.cursor) qs.set('cursor', params.cursor);
    if (params.limit) qs.set('limit', String(params.limit));
    const q = qs.toString();
    return this.request(`/api/v4/prediction/events${q ? `?${q}` : ''}`);
  }

  getEventBySlug(slug: string): Promise<Event> {
    return this.request(`/api/v4/prediction/events/slug/${encodeURIComponent(slug)}`);
  }

  listMarkets(params: { event_id?: string; category?: string; status?: string } = {}): Promise<{ markets: Market[] }> {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v && qs.set(k, v));
    const q = qs.toString();
    return this.request(`/api/v4/prediction/markets${q ? `?${q}` : ''}`);
  }

  getMarket(marketId: string): Promise<Market> {
    return this.request(`/api/v4/prediction/markets/${marketId}`);
  }

  getOrderBook(tokenId: string, depth = 50): Promise<OrderBookSnapshot> {
    return this.request(`/api/v4/prediction/tokens/${tokenId}/order_book?depth=${depth}`);
  }

  getTicker(tokenId: string): Promise<Ticker> {
    return this.request(`/api/v4/prediction/tokens/${tokenId}/ticker`);
  }

  getPriceHistory(tokenId: string, resolution = '1m'): Promise<{ candles: Candle[] }> {
    return this.request(
      `/api/v4/prediction/tokens/${tokenId}/price_history?resolution=${resolution}`
    );
  }

  // ---- Orders --------------------------------------------------------------

  submitOrder(input: TradeTicketInput): Promise<{ order: Order; fills: OrderFill[] }> {
    return this.request('/api/v4/prediction/orders', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  }

  listOrders(params: { market_id?: string; status?: string; limit?: number } = {}): Promise<{ orders: Order[] }> {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v && qs.set(k, String(v)));
    const q = qs.toString();
    return this.request(`/api/v4/prediction/orders${q ? `?${q}` : ''}`);
  }

  cancelOrder(orderId: string): Promise<{ order_id: string; status: string; unfilled_amount: number }> {
    return this.request(`/api/v4/prediction/orders/${orderId}`, { method: 'DELETE' });
  }

  cancelAllOrders(params: { market_id?: string; condition_id?: string }): Promise<{ cancelled_count: number; cancelled_order_ids: string[] }> {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v && qs.set(k, v));
    return this.request(`/api/v4/prediction/orders?${qs.toString()}`, { method: 'DELETE' });
  }

  // ---- Positions -----------------------------------------------------------

  listPositions(settlementStatus?: 'OPEN' | 'SETTLED'): Promise<{ positions: Position[] }> {
    const q = settlementStatus ? `?settlement_status=${settlementStatus}` : '';
    return this.request(`/api/v4/prediction/positions${q}`);
  }

  redeemPosition(positionId: string): Promise<{
    position_id: string;
    payout_amount: number;
    status: string;
    payout_per_share: number;
  }> {
    return this.request(`/api/v4/prediction/positions/${positionId}/redeem`, {
      method: 'POST',
    });
  }

  splitPosition(marketId: string, shares: number): Promise<any> {
    return this.request('/api/v4/prediction/positions/split', {
      method: 'POST',
      body: JSON.stringify({ market_id: marketId, shares }),
    });
  }

  mergePositions(marketId: string, shares: number): Promise<any> {
    return this.request('/api/v4/prediction/positions/merge', {
      method: 'POST',
      body: JSON.stringify({ market_id: marketId, shares }),
    });
  }

  // ---- Resolution ----------------------------------------------------------

  proposeResolution(marketId: string, proposedOutcomeIndex: number): Promise<any> {
    return this.request('/api/v4/prediction/resolution/propose', {
      method: 'POST',
      body: JSON.stringify({ market_id: marketId, proposed_outcome_index: proposedOutcomeIndex }),
    });
  }

  disputeProposal(marketId: string, counterBond = 50.0): Promise<any> {
    return this.request('/api/v4/prediction/resolution/dispute', {
      method: 'POST',
      body: JSON.stringify({ market_id: marketId, counter_bond: counterBond }),
    });
  }

  finalizeResolution(marketId: string, winningOutcomeIndex: number): Promise<any> {
    return this.request('/api/v4/prediction/resolution/finalize', {
      method: 'POST',
      body: JSON.stringify({ market_id: marketId, winning_outcome_index: winningOutcomeIndex }),
    });
  }

  closeMarket(marketId: string): Promise<any> {
    return this.request(`/api/v4/prediction/admin/markets/${marketId}/close`, {
      method: 'POST',
    });
  }

  listResolutionMarkets(): Promise<{ markets: any[] }> {
    return this.request('/api/v4/prediction/resolution/markets');
  }

  createEvent(body: {
    slug: string;
    title: string;
    description?: string;
    category: string;
    tags?: string[];
    end_date?: string;
  }): Promise<any> {
    return this.request('/api/v4/prediction/admin/events', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  createMarket(body: {
    event_slug: string;
    question: string;
    outcomes: string[];
    neg_risk?: boolean;
  }): Promise<any> {
    return this.request('/api/v4/prediction/admin/markets', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }
}

export const api = new ApiClient();
