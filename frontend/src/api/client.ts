/**
 * Type-Safe API Client & Domain Models for Dolymarket.
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

export type EventStatus = 'ACTIVE' | 'CLOSED' | 'RESOLVED' | 'UNFUNDED' | 'EXPIRED';
export type MarketStatus =
  | 'ACTIVE'
  | 'UNFUNDED'
  | 'EXPIRED'
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
  tier?: 'OFFICIAL' | 'COMMUNITY';
  creator_user_id?: string | null;
  resolution_criteria?: string | null;
  oracle_feed?: string | null;
  oracle_threshold?: number | null;
  oracle_comparator?: string | null;
  clarity?: { score: number; grade: 'HIGH' | 'MEDIUM' | 'LOW'; flags: string[] };
  liquidity_funded_usdc?: number;
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
  tier?: 'OFFICIAL' | 'COMMUNITY';
  creator_user_id?: string | null;
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
  sequence?: number;
  stream_sequence?: number;
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

/** Live DexBuilder market (read-only upstream data). */
export interface LiveMarket {
  id: string;
  event_id: string;
  condition_id: string | null;
  question: string;
  question_i18n?: Record<string, string> | null;
  event_title: string | null;
  slug: string | null;
  outcomes: string[];
  tokens: (OutcomeToken & { price: number | null })[];
  prices: Record<string, number>;
  tick_size: number;
  min_order_size: number;
  status: string;
  start_time: number | null;
  end_time: number | null;
  category: string;
  tags: string[];
  accepting_orders: boolean;
  closed: boolean;
  resolved: boolean;
  winning_outcome_index: number | null;
  winning_outcome: string | null;
  best_bid: number | null;
  best_ask: number | null;
  mid_price: number | null;
  last_trade_price: number | null;
  volume: number;
  liquidity: number;
  source: string;
  read_only: boolean;
}

/** Live DexBuilder event. */
export interface LiveEvent {
  id: string;
  slug: string | null;
  title: string;
  category: string;
  tags: string[];
  status: string;
  start_date: string | null;
  end_date: string | null;
  total_volume: number;
  source: string;
  read_only: boolean;
}

/** Live DexBuilder trade print. */
export interface LiveTrade {
  id: string;
  market_id: string;
  token_id: string;
  outcome: string | null;
  side: string;
  price: number | null;
  size: number | null;
  timestamp: string | null;
  source: string;
}

/** Runtime status of the live upstream integration. */
export interface LiveStatus {
  upstream: string;
  public_reads: boolean;
  credentialed: boolean;
  cache_entries: number;
  circuit_open: boolean;
  consecutive_failures: number;
}

/** Credential diagnostic for the upstream DexBuilder integration. */
export interface LiveAuthStatus {
  configured: boolean;
  key_present: boolean;
  secret_present: boolean;
  scheme: string;
  headers: string[];
  authenticated: boolean;
  upstream: {
    status: number | null;
    label: string;
    message: string;
  } | null;
}

/** Desk entry in the admin review queue. */
export interface AdminDesk {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  status: string;
  review_note: string | null;
  owner_email: string | null;
  follower_count: number;
  created_at: string;
  activated_at: string | null;
  suspended_at: string | null;
}

/** Copy job in the admin history listing. */
export interface AdminCopyJob {
  id: string;
  desk_id: string;
  desk_name: string | null;
  follower_email: string | null;
  source_fill_id: string;
  status: string;
  copy_ratio: number;
  requested_shares: number;
  filled_shares: number;
  limit_breached: boolean;
  error_code: string | null;
  created_at: string;
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
  pending?: boolean;
}

export interface OrderFill {
  id: string;
  price: number;
  shares: number;
  maker_fee: number;
  taker_fee: number;
  sequence_id?: number;
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
  user: { id: string; email: string; is_admin?: boolean };
}

export interface OAuthProviderInfo {
  name: string;
  label: string;
  configured: boolean;
  scopes: string;
}

export interface OAuthStartResponse {
  provider: string;
  label: string;
  configured: boolean;
  auth_url: string;
  state: string;
  redirect_uri: string;
}

export interface PasskeyOptions {
  publicKey: any;
  challenge: string;
  rp: { id: string; name: string };
}

export interface PasskeyCredentialInfo {
  credential_id: string;
  label: string | null;
  aaguid: string | null;
  device_type: string | null;
  backed_up: boolean;
  sign_count: number;
  created_at: string;
  last_used_at: string | null;
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
// AGX (Algoxen) utility token
//
// Every amount crosses the wire as a decimal string; the UI only formats these
// strings for display and never does token arithmetic in binary floating point.
// ---------------------------------------------------------------------------

export interface AgxBalance {
  user_id: string;
  balance: string;
  staked_balance: string;
  locked_gating_balance: string;
  locked_dispute_balance: string;
  pending_rewards: string;
  last_reward_epoch: string | null;
  tier: string;
  tier_name: string;
  discount_rate: string;
  updated_at: string | null;
}

export interface AgxStake {
  id: string;
  amount: string;
  status: string;
  locked_until: string;
  created_at: string | null;
}

export interface AgxCooldown {
  id: string;
  stake_id: string;
  amount: string;
  status: string;
  cooldown_until: string;
  created_at: string | null;
}

export interface AgxDisputeStake {
  id: string;
  market_id: string;
  amount: string;
  status: string;
  created_at: string | null;
  resolved_at: string | null;
  treasury_address: string;
}

export interface AgxRewardEpoch {
  id: string;
  epoch_number: number;
  total_fees_collected: string;
  total_staked_supply: string;
  reward_per_token: string;
  creator_share: string;
  staker_pool: string;
  creator_accruals: Record<string, string>;
  started_at: string | null;
  ended_at: string | null;
  distributed: boolean;
}

export interface AgxRewardEntry {
  id: string;
  amount: string;
  balance_after: string;
  reference_id: string | null;
  created_at: string | null;
}

export interface AgxTier {
  tier: string;
  name: string;
  min_staked: string;
  discount_rate: string;
}

export interface AgxTiersResponse {
  tiers: AgxTier[];
  total_staked: string;
  staker_count: number;
}

export interface AgxStats {
  chain_id: number;
  token_symbol: string;
  token_decimals: number;
  treasury_address: string;
  total_staked: string;
  total_spendable: string;
  total_gating_locked: string;
  total_dispute_locked: string;
  staker_count: number;
  epoch_count: number;
  distributed_staker_pool: string;
}

// ---------------------------------------------------------------------------
// Token storage (in-memory access token; HttpOnly refresh cookie restores reloads)
// ---------------------------------------------------------------------------

const TOKEN_KEY = 'dolymarket_auth_token';
const SESSION_HINT_KEY = 'dolymarket_has_session';
let inMemoryToken: string | null = null;

export function getStoredToken(): string | null {
  return inMemoryToken;
}

export function hasSessionHint(): boolean {
  try {
    return localStorage.getItem(SESSION_HINT_KEY) === '1';
  } catch {
    return false;
  }
}

export function setStoredToken(token: string): void {
  inMemoryToken = token;
  try {
    localStorage.setItem(SESSION_HINT_KEY, '1');
  } catch {
    /* ignore */
  }
}

export function clearStoredToken(): void {
  inMemoryToken = null;
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem('pm_auth_token');
    localStorage.removeItem(SESSION_HINT_KEY);
  } catch {
    /* ignore */
  }
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

type ToastHandler = (message: string, kind: 'error' | 'info') => void;
let toastHandler: ToastHandler | null = null;
export function setToastHandler(handler: ToastHandler | null): void {
  toastHandler = handler;
}

type UnauthorizedHandler = (status: number, message: string) => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

function extractDetail(data: any): string {
  if (typeof data === 'string') return data;
  if (data?.detail) return typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
  if (data?.message) return data.message;
  return '';
}

export class ApiClient {
  private baseUrl: string;
  private refreshPromise: Promise<AuthResponse | null> | null = null;

  constructor(baseUrl: string = API_BASE) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
  }

  private async request<T>(
    path: string,
    options: RequestInit = {},
    auth = true,
    silent = false,
    retried = false
  ): Promise<T> {
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
      res = await fetch(`${this.baseUrl}${path}`, {
        credentials: 'include',
        ...options,
        headers,
      });
    } catch (err: any) {
      const msg = `Network error: ${err?.message ?? 'backend unreachable'}`;
      if (!silent) toastHandler?.(msg, 'error');
      throw new ApiError(0, msg);
    }

    if (res.status === 401 && auth && !retried) {
      const refreshed = await this.refreshSession().catch(() => null);
      if (refreshed?.access_token) {
        return this.request<T>(path, options, auth, silent, true);
      }
    }

    if (!res.ok) {
      const rawText = await res.text();
      let data: any = rawText;
      try {
        data = rawText ? JSON.parse(rawText) : {};
      } catch {
        /* keep plain text body */
      }
      const msg = extractDetail(data) || `Request failed (${res.status})`;
      if (!silent) {
        toastHandler?.(msg, res.status === 401 || res.status === 403 ? 'error' : 'error');
      }
      if (res.status === 401) {
        clearStoredToken();
        unauthorizedHandler?.(res.status, msg);
      }
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

  /** Request a cryptographic SIWE challenge for Web3 wallet authentication. */
  getWalletChallenge(address: string, chainId?: number): Promise<{ challenge: string; nonce: string; expires_at: string }> {
    const domain = typeof window !== 'undefined' ? window.location.host : undefined;
    const uri = typeof window !== 'undefined' ? window.location.origin : undefined;
    return this.request(
      '/api/v1/auth/wallet/challenge',
      { method: 'POST', body: JSON.stringify({ address, chain_id: chainId ?? 8453, domain, uri }) },
      false
    );
  }

  /** Verify wallet signature and issue access token (SIWE). */
  async verifyWalletLogin(address: string, signature: string, nonce: string): Promise<AuthResponse> {
    const data = await this.request<AuthResponse>(
      '/api/v1/auth/wallet/verify',
      { method: 'POST', body: JSON.stringify({ address, signature, nonce }) },
      false
    );
    setStoredToken(data.access_token);
    return data;
  }

  async refreshSession(): Promise<AuthResponse | null> {
    if (this.refreshPromise) return this.refreshPromise;
    this.refreshPromise = (async () => {
      try {
        const data = await this.request<AuthResponse>(
          '/api/v1/auth/refresh',
          { method: 'POST' },
          false,
          true
        );
        if (data?.access_token) {
          setStoredToken(data.access_token);
          return data;
        }
        return null;
      } catch {
        return null;
      } finally {
        this.refreshPromise = null;
      }
    })();
    return this.refreshPromise;
  }

  logout(): void {
    const token = getStoredToken();
    const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
    void fetch(`${this.baseUrl}/api/v1/auth/logout`, {
      method: 'POST',
      credentials: 'include',
      headers,
    }).catch(() => {});
    clearStoredToken();
  }

  /** Profile of the authenticated account. */
  getMe(): Promise<{ id: string; email: string; created_at: string; is_admin: boolean; dexbuilder_wallet?: string | null }> {
    return this.request('/api/v1/auth/me');
  }

  /** Set the DexBuilder sub-user wallet address for the authenticated user. */
  setDexBuilderWallet(wallet_address: string): Promise<{ user_id: string; dexbuilder_wallet: string }> {
    return this.request('/api/v1/auth/dexbuilder-wallet', {
      method: 'POST',
      body: JSON.stringify({ wallet_address }),
    });
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

  previewMarketClarity(body: {
    question?: string;
    resolution_criteria?: string;
    end_date?: string;
    oracle_feed?: string;
  }): Promise<{
    score: number;
    grade: 'HIGH' | 'MEDIUM' | 'LOW';
    flags: string[];
    category?: string;
    engine?: string;
  }> {
    return this.request('/api/v4/prediction/community/clarity-preview', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  createCommunityMarket(body: {
    title: string;
    question: string;
    category?: string;
    resolution_criteria: string;
    outcomes?: string[];
    end_date?: string;
    initial_liquidity_usdc?: number;
    oracle_feed?: string;
    oracle_threshold?: number;
    oracle_comparator?: string;
  }): Promise<any> {
    return this.request('/api/v4/prediction/community/markets', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  fundCommunityMarket(marketId: string, amountUsdc: number): Promise<any> {
    return this.request(`/api/v4/prediction/community/markets/${encodeURIComponent(marketId)}/fund`, {
      method: 'POST',
      body: JSON.stringify({ amount_usdc: amountUsdc }),
    });
  }

  // ---- Hybrid LMSR AMM & LP ------------------------------------------------

  getAmmPool(marketId: string): Promise<{
    market_id: string;
    b: number;
    q_yes: number;
    q_no: number;
    pool_usdc: number;
    fees_collected_usdc: number;
    total_lp_shares: number;
    fee_bps: number;
    yes_price: number;
    no_price: number;
  }> {
    return this.request(`/api/v4/prediction/amm/${encodeURIComponent(marketId)}`);
  }

  quoteAmm(
    marketId: string,
    outcomeIndex: number,
    side: 'BUY' | 'SELL',
    shares: number,
  ): Promise<{
    market_id: string;
    outcome_index: number;
    side: string;
    shares: number;
    notional_usdc: number;
    fee_usdc: number;
    total_usdc: number;
    avg_price: number;
    post_yes_price: number;
    post_no_price: number;
  }> {
    const qs = new URLSearchParams({
      outcome_index: String(outcomeIndex),
      side,
      shares: String(shares),
    });
    return this.request(`/api/v4/prediction/amm/${encodeURIComponent(marketId)}/quote?${qs}`);
  }

  depositAmmLiquidity(marketId: string, amountUsdc: number): Promise<any> {
    return this.request(`/api/v4/prediction/amm/${encodeURIComponent(marketId)}/deposit`, {
      method: 'POST',
      body: JSON.stringify({ amount_usdc: amountUsdc }),
    });
  }

  tradeAmm(
    marketId: string,
    tokenId: string,
    side: 'BUY' | 'SELL',
    shares: number,
  ): Promise<any> {
    return this.request(`/api/v4/prediction/amm/${encodeURIComponent(marketId)}/trade`, {
      method: 'POST',
      body: JSON.stringify({ token_id: tokenId, side, shares }),
    });
  }

  redeemAmmLp(marketId: string): Promise<{
    market_id: string;
    redeemed_shares: number;
    payout_usdc: number;
  }> {
    return this.request(`/api/v4/prediction/amm/${encodeURIComponent(marketId)}/redeem`, {
      method: 'POST',
    });
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

  /**
   * Submit an order.
   *
   * `idempotencyKey` lets a caller reuse the same key when retrying the same
   * logical request: the server replays the first response instead of
   * matching the order twice. A fresh key is generated when omitted.
   */
  submitOrder(
    input: TradeTicketInput,
    idempotencyKey?: string
  ): Promise<{ order: Order; fills: OrderFill[] }> {
    const key =
      idempotencyKey ??
      (typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(36).slice(2)}`);
    return this.request('/api/v4/prediction/orders', {
      method: 'POST',
      headers: { 'X-Idempotency-Key': key },
      body: JSON.stringify(input),
    });
  }

  getFearGreedLatest(profile = 'microstructure'): Promise<{
    ewi: number;
    score_0_100: number;
    regime_state: string;
    early_warning?: boolean;
  }> {
    return this.request(
      `/api/v1/feargreed/latest?profile=${encodeURIComponent(profile)}`,
      {},
      false,
      true
    );
  }

  smartQuote(input: {
    market_id: string;
    token_id: string;
    side: 'BUY' | 'SELL';
    shares: number;
    max_slippage_price?: number;
  }): Promise<{
    market_id: string;
    token_id: string;
    side: 'BUY' | 'SELL';
    requested_shares: number;
    fillable_shares: number;
    has_amm: boolean;
    clob_exhausted: boolean;
    clob_shares: number;
    clob_avg_price: number;
    clob_notional_usdc: number;
    amm_shares: number;
    amm_avg_price: number;
    amm_notional_usdc: number;
    amm_fee_usdc: number;
    amm_total_usdc: number;
    blended_avg_price: number;
  }> {
    return this.request(
      '/api/v4/prediction/orders/smart-quote',
      { method: 'POST', body: JSON.stringify(input) },
      false,
      true
    );
  }

  placeSmartOrder(input: {
    market_id: string;
    token_id: string;
    side: 'BUY' | 'SELL';
    shares: number;
    max_slippage_price?: number;
  }): Promise<{
    status: string;
    total_filled_shares: number;
    clob_filled_shares: number;
    amm_filled_shares: number;
    blended_avg_price: number;
  }> {
    return this.request('/api/v4/prediction/orders/smart', {
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

  cancelAllOrders(params: { market_id: string; condition_id?: string }): Promise<{ cancelled_count: number; cancelled_order_ids: string[] }> {
    // The backend rejects a batch cancel without a market/condition scope.
    const qs = new URLSearchParams();
    qs.set('market_id', params.market_id);
    if (params.condition_id) qs.set('condition_id', params.condition_id);
    return this.request(`/api/v4/prediction/orders?${qs.toString()}`, { method: 'DELETE' });
  }

  // ---- Federated auth ------------------------------------------------------

  /** Providers this deployment supports (and whether they are configured). */
  listAuthProviders(): Promise<{ providers: OAuthProviderInfo[] }> {
    return this.request('/api/v1/auth/oauth/providers', {}, false);
  }

  /** Begin an OAuth handshake and return the provider authorize URL. */
  oauthStart(provider: string, redirect = true): Promise<OAuthStartResponse> {
    const query = redirect ? '?redirect=true' : '';
    return this.request(
      `/api/v1/auth/oauth/${encodeURIComponent(provider)}/start${query}`,
      {},
      false
    );
  }

  /** Redeem the one-time code for a JWT and persist it. */
  async oauthExchange(code: string): Promise<AuthResponse> {
    const data = await this.request<AuthResponse>(
      '/api/v1/auth/oauth/exchange',
      { method: 'POST', body: JSON.stringify({ code }) },
      false
    );
    setStoredToken(data.access_token);
    return data;
  }

  // ---- Passkeys ------------------------------------------------------------

  passkeyRegisterOptions(): Promise<PasskeyOptions> {
    return this.request('/api/v1/auth/passkey/register/options', { method: 'POST' });
  }

  passkeyRegisterVerify(
    credential: unknown,
    label?: string
  ): Promise<{ status: string; credential_id: string; user: { id: string; email: string } }> {
    return this.request('/api/v1/auth/passkey/register/verify', {
      method: 'POST',
      body: JSON.stringify({ credential, label }),
    });
  }

  passkeyLoginOptions(): Promise<PasskeyOptions> {
    return this.request('/api/v1/auth/passkey/login/options', { method: 'POST' }, false);
  }

  /** Verify a passkey assertion, persist the JWT and return the session. */
  async passkeyLoginVerify(credential: unknown): Promise<AuthResponse> {
    const data = await this.request<AuthResponse>(
      '/api/v1/auth/passkey/login/verify',
      { method: 'POST', body: JSON.stringify({ credential }) },
      false
    );
    setStoredToken(data.access_token);
    return data;
  }

  listPasskeys(): Promise<{ passkeys: PasskeyCredentialInfo[] }> {
    return this.request('/api/v1/auth/passkey/credentials');
  }

  deletePasskey(credentialId: string): Promise<{ status: string; credential_id: string }> {
    return this.request(
      `/api/v1/auth/passkey/credentials/${encodeURIComponent(credentialId)}`,
      { method: 'DELETE' }
    );
  }

  // ---- Pro Desks -----------------------------------------------------------
  listDesks(params: { sort?: string; limit?: number } = {}): Promise<{ desks: any[] }> {
    const q = new URLSearchParams();
    if (params.sort) q.set('sort', params.sort);
    if (params.limit) q.set('limit', String(params.limit));
    const qs = q.toString();
    return this.request(`/api/v1/desks${qs ? '?' + qs : ''}`, {}, false);
  }
  getDesk(id: string): Promise<{ desk: any }> {
    return this.request(`/api/v1/desks/${encodeURIComponent(id)}`, {}, false);
  }
  getDeskTrackRecord(id: string): Promise<{ track_record: any; curve: any[] }> {
    return this.request(`/api/v1/desks/${encodeURIComponent(id)}/track-record`, {}, false);
  }
  createDesk(body: { name: string; slug: string; description?: string }): Promise<{ status: string; desk: any }> {
    return this.request('/api/v1/desks', { method: 'POST', body: JSON.stringify(body) });
  }
  getMyDesk(silent = false): Promise<{ desk: any }> {
    return this.request('/api/v1/desks/mine', {}, true, silent);
  }
  updateDesk(id: string, body: { name?: string; description?: string }): Promise<{ desk: any }> {
    return this.request(`/api/v1/desks/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(body) });
  }
  submitDesk(id: string): Promise<{ status: string; desk: any }> {
    return this.request(`/api/v1/desks/${encodeURIComponent(id)}/submit`, { method: 'POST' });
  }
  suspendDesk(id: string): Promise<{ status: string; desk: any }> {
    return this.request(`/api/v1/desks/${encodeURIComponent(id)}/suspend`, { method: 'POST' });
  }
  archiveDesk(id: string): Promise<{ status: string; desk: any }> {
    return this.request(`/api/v1/desks/${encodeURIComponent(id)}/archive`, { method: 'POST' });
  }
  startDeskMarketMaker(
    id: string,
    body: {
      market_id: string
      token_id: string
      base_half_spread?: string | number
      quote_size?: string | number
      max_inventory?: string | number
      tick_size?: string | number
      crypto_skew?: boolean
      dry_run?: boolean
      interval_s?: number
    }
  ): Promise<any> {
    return this.request(`/api/v1/desks/${encodeURIComponent(id)}/mm/start`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }
  stopDeskMarketMaker(id: string): Promise<any> {
    return this.request(`/api/v1/desks/${encodeURIComponent(id)}/mm/stop`, { method: 'POST' });
  }
  getDeskMarketMakerStatus(id: string): Promise<any> {
    return this.request(`/api/v1/desks/${encodeURIComponent(id)}/mm/status`);
  }
  listDeskFollowers(id: string): Promise<{ followers: any[] }> {
    return this.request(`/api/v1/desks/${encodeURIComponent(id)}/followers`);
  }
  listDeskCopyJobs(id: string): Promise<{ counts: any; jobs: any[] }> {
    return this.request(`/api/v1/desks/${encodeURIComponent(id)}/copy-jobs`);
  }
  followDesk(id: string, body: any): Promise<{ status: string }> {
    return this.request(`/api/v1/desks/${encodeURIComponent(id)}/follow`, { method: 'POST', body: JSON.stringify(body) });
  }
  updateFollow(id: string, body: any): Promise<{ status: string }> {
    return this.request(`/api/v1/desks/${encodeURIComponent(id)}/follow`, { method: 'PUT', body: JSON.stringify(body) });
  }
  unfollowDesk(id: string): Promise<void> {
    return this.request(`/api/v1/desks/${encodeURIComponent(id)}/follow`, { method: 'DELETE' });
  }
  listCopyJobs(params: { status?: string; limit?: number } = {}): Promise<{ jobs: any[] }> {
    const q = new URLSearchParams();
    if (params.status) q.set('status', params.status);
    if (params.limit) q.set('limit', String(params.limit));
    const qs = q.toString();
    return this.request(`/api/v1/copy-jobs${qs ? '?' + qs : ''}`);
  }

  // ---- Operations console (admin only) -------------------------------------

  listAdminDesks(status = 'PENDING_REVIEW'): Promise<{ desks: AdminDesk[]; status: string | null }> {
    const q = new URLSearchParams();
    if (status) q.set('status', status);
    const qs = q.toString();
    return this.request(`/api/v4/prediction/admin/desks${qs ? '?' + qs : ''}`);
  }
  approveDesk(id: string): Promise<{ status: string; desk_id: string }> {
    return this.request(`/api/v4/prediction/admin/desks/${encodeURIComponent(id)}/approve`, { method: 'POST' });
  }
  rejectDesk(id: string, reason: string): Promise<{ status: string; desk_id: string }> {
    return this.request(`/api/v4/prediction/admin/desks/${encodeURIComponent(id)}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    });
  }
  adminSuspendDesk(id: string): Promise<{ status: string; desk_id: string }> {
    return this.request(`/api/v4/prediction/admin/desks/${encodeURIComponent(id)}/suspend`, { method: 'POST' });
  }
  listAdminCopyJobs(params: { status?: string; limit?: number } = {}): Promise<{ jobs: AdminCopyJob[] }> {
    const q = new URLSearchParams();
    if (params.status) q.set('status', params.status);
    if (params.limit) q.set('limit', String(params.limit));
    const qs = q.toString();
    return this.request(`/api/v4/prediction/admin/copy-jobs${qs ? '?' + qs : ''}`);
  }

  // ---- DexBuilder parity / extended prediction surfaces --------------------
  listTags(): Promise<{ tags: string[] }> {
    return this.request('/api/v4/prediction/tags', {}, false);
  }
  getMarketBySlug(slug: string): Promise<any> {
    return this.request(`/api/v4/prediction/markets/slug/${encodeURIComponent(slug)}`, {}, false);
  }
  getBulkPrices(ids: string[]): Promise<{ prices: Record<string, number | null> }> {
    return this.request(`/api/v4/prediction/tokens/prices?ids=${encodeURIComponent(ids.join(','))}`, {}, false);
  }
  getUserTrades(): Promise<{ trades: any[] }> {
    return this.request('/api/v4/prediction/usertrades');
  }
  getSettledPositions(): Promise<{ positions: any[] }> {
    return this.request('/api/v4/prediction/positions/settled');
  }
  getDexBuilderMarkets(params: { status?: string; category?: string; limit?: number } = {}): Promise<any> {
    const q = new URLSearchParams();
    if (params.status) q.set('status', params.status);
    if (params.category) q.set('category', params.category);
    if (params.limit) q.set('limit', String(params.limit));
    const qs = q.toString();
    return this.request(`/api/v4/dexbuilder/markets${qs ? '?' + qs : ''}`, {}, false);
  }
  getDexBuilderTags(): Promise<any> {
    return this.request('/api/v4/dexbuilder/tags', {}, false);
  }
  getDexBuilderOrderBook(tokenId: string): Promise<any> {
    return this.request(`/api/v4/dexbuilder/tokens/${encodeURIComponent(tokenId)}/order_book`, {}, false);
  }
  getDexBuilderPriceHistory(tokenId: string, interval = '1h', fromMs?: number, toMs?: number): Promise<any> {
    const q = new URLSearchParams({ interval });
    if (fromMs != null) q.set('from', String(fromMs));
    if (toMs != null) q.set('to', String(toMs));
    return this.request(`/api/v4/dexbuilder/tokens/${encodeURIComponent(tokenId)}/price_history?${q.toString()}`, {}, false);
  }
  getDexBuilderCandlesticks(tokenId: string): Promise<any> {
    return this.request(`/api/v4/dexbuilder/tokens/${encodeURIComponent(tokenId)}/candlesticks`, {}, false);
  }
  getDexBuilderTime(): Promise<{ server_time: number }> {
    return this.request('/api/v4/dexbuilder/time', {}, false);
  }
  placeDexBuilderOrder(payload: {
    token_id: string
    side: 'BUY' | 'SELL'
    price: string
    size: string
    total_cost?: string
    order_type?: string
    order_mode?: string
    client_order_id?: string
    post_only?: boolean
    sell_all?: boolean
    expire_time?: number
  }): Promise<{ order_id: string; client_order_id?: string; status: string; created_at?: number }> {
    return this.request('/api/v4/dexbuilder/orders', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }
  getDexBuilderOrders(params: { status?: string; condition_id?: string; limit?: number; cursor?: string } = {}): Promise<any> {
    const q = new URLSearchParams();
    if (params.status) q.set('status', params.status);
    if (params.condition_id) q.set('condition_id', params.condition_id);
    if (params.limit != null) q.set('limit', String(params.limit));
    if (params.cursor) q.set('cursor', params.cursor);
    const qs = q.toString();
    return this.request(`/api/v4/dexbuilder/orders${qs ? '?' + qs : ''}`);
  }
  cancelDexBuilderOrder(orderId: string): Promise<any> {
    return this.request(`/api/v4/dexbuilder/orders/${encodeURIComponent(orderId)}`, {
      method: 'DELETE',
    });
  }
  getDexBuilderAccountBook(params: { limit?: number; cursor?: string } = {}): Promise<any> {
    const q = new URLSearchParams();
    if (params.limit != null) q.set('limit', String(params.limit));
    if (params.cursor) q.set('cursor', params.cursor);
    const qs = q.toString();
    return this.request(`/api/v4/dexbuilder/account_book${qs ? '?' + qs : ''}`);
  }
  getDexBuilderClaimable(): Promise<{ total_claimable_amount: string; event_count: number }> {
    return this.request('/api/v4/dexbuilder/claims/available');
  }
  claimDexBuilderWinnings(payload: Record<string, any> = {}): Promise<any> {
    return this.request('/api/v4/dexbuilder/claims', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }
  getDexBuilderUserInfo(): Promise<any> {
    return this.request('/api/v4/dexbuilder/platform/user');
  }
  getDexBuilderDeposits(page = 1, pageSize = 20): Promise<any> {
    return this.request(`/api/v4/dexbuilder/platform/deposits?page=${page}&page_size=${pageSize}`);
  }
  getDexBuilderWithdrawals(page = 1, pageSize = 20): Promise<any> {
    return this.request(`/api/v4/dexbuilder/platform/withdrawals?page=${page}&page_size=${pageSize}`);
  }
  createDexBuilderDepositSignData(payload: Record<string, any>): Promise<any> {
    return this.request('/api/v4/dexbuilder/platform/deposit/sign_data', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }
  createDexBuilderWithdrawSignData(payload: Record<string, any>): Promise<any> {
    return this.request('/api/v4/dexbuilder/platform/withdraw/sign_data', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }
  submitDexBuilderWithdraw(payload: Record<string, any>): Promise<any> {
    return this.request('/api/v4/dexbuilder/platform/withdraw/submit', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  // ---- Live DexBuilder data (public upstream reads, read-only) -------------

  getLiveStatus(): Promise<LiveStatus> {
    return this.request('/api/v4/prediction/live/status', {}, false);
  }
  getLiveAuth(): Promise<LiveAuthStatus> {
    return this.request('/api/v4/prediction/live/auth', {}, false);
  }
  getLiveMarkets(
    params: { status?: string; category?: string; limit?: number; offset?: number } = {}
  ): Promise<{
    markets: LiveMarket[]
    total: number
    status: string
    offset: number
    limit: number
    has_more: boolean
    next_offset: number | null
    source: string
  }> {
    const q = new URLSearchParams();
    if (params.status) q.set('status', params.status);
    if (params.category) q.set('category', params.category);
    if (params.limit) q.set('limit', String(params.limit));
    if (params.offset) q.set('offset', String(params.offset));
    const qs = q.toString();
    return this.request(`/api/v4/prediction/live/markets${qs ? '?' + qs : ''}`, {}, false);
  }
  getLiveMarket(marketId: string): Promise<LiveMarket> {
    return this.request(
      `/api/v4/prediction/live/markets/${encodeURIComponent(marketId)}`,
      {},
      false
    );
  }
  getLiveEvents(params: { limit?: number } = {}): Promise<{ events: LiveEvent[] }> {
    const q = params.limit ? `?limit=${params.limit}` : '';
    return this.request(`/api/v4/prediction/live/events${q}`, {}, false);
  }
  getLiveTags(): Promise<{ tags: string[] }> {
    return this.request('/api/v4/prediction/live/tags', {}, false);
  }
  getLiveTime(): Promise<{ server_time: number }> {
    return this.request('/api/v4/prediction/live/time', {}, false);
  }
  getLiveOrderBook(tokenId: string, depth = 50): Promise<OrderBookSnapshot> {
    return this.request(
      `/api/v4/prediction/live/tokens/${encodeURIComponent(tokenId)}/order_book?depth=${depth}`,
      {},
      false
    );
  }
  getLivePriceHistory(
    tokenId: string,
    interval = '1h'
  ): Promise<{ candles: Candle[]; interval: string }> {
    return this.request(
      `/api/v4/prediction/live/tokens/${encodeURIComponent(tokenId)}/price_history?interval=${interval}`,
      {},
      false
    );
  }
  getLiveCandlesticks(
    tokenId: string,
    interval = '1m',
    limit = 200
  ): Promise<{ candlesticks: Candle[] }> {
    return this.request(
      `/api/v4/prediction/live/tokens/${encodeURIComponent(tokenId)}/candlesticks?interval=${interval}&limit=${limit}`,
      {},
      false
    );
  }
  getLiveMarketTrades(
    marketId: string,
    limit = 50
  ): Promise<{ trades: LiveTrade[] }> {
    return this.request(
      `/api/v4/prediction/live/markets/${encodeURIComponent(marketId)}/trades?limit=${limit}`,
      {},
      false
    );
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

  disputeProposal(marketId: string, counterBond = 100.0): Promise<any> {
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

  resolveWithFeed(
    marketId: string,
    feed: string,
    threshold: number,
    comparator = '>=',
    autoFinalize = false,
  ): Promise<any> {
    return this.request('/api/v4/prediction/resolution/resolve-feed', {
      method: 'POST',
      body: JSON.stringify({
        market_id: marketId,
        feed,
        threshold,
        comparator,
        auto_finalize: autoFinalize,
      }),
    });
  }

  runResolutionTick(): Promise<{ closed: number; expired: number; proposed: number; finalized: number }> {
    return this.request('/api/v4/prediction/resolution/run-tick', {
      method: 'POST',
    });
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
    oracle_feed?: string;
    oracle_threshold?: number;
    oracle_comparator?: string;
  }): Promise<any> {
    return this.request('/api/v4/prediction/admin/markets', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  // ---- AGX utility token ----------------------------------------------------

  getAgxBalance(): Promise<AgxBalance> {
    return this.request('/api/v1/agx/balance');
  }

  getAgxStakes(): Promise<{ stakes: AgxStake[]; cooldowns: AgxCooldown[] }> {
    return this.request('/api/v1/agx/stakes');
  }

  stakeAgx(amount: string): Promise<{ status: string; stake: AgxStake; balance: AgxBalance }> {
    return this.request('/api/v1/agx/stake', {
      method: 'POST',
      body: JSON.stringify({ amount }),
    });
  }

  unstakeAgx(stakeId: string): Promise<{
    status: string;
    cooldown: AgxCooldown;
    balance: AgxBalance;
  }> {
    return this.request('/api/v1/agx/unstake', {
      method: 'POST',
      body: JSON.stringify({ stake_id: stakeId }),
    });
  }

  withdrawAgx(cooldownId: string): Promise<{
    status: string;
    amount: string;
    balance: AgxBalance;
  }> {
    return this.request('/api/v1/agx/withdraw', {
      method: 'POST',
      body: JSON.stringify({ cooldown_id: cooldownId }),
    });
  }

  claimAgxRewards(): Promise<{ claimed: string; balance: AgxBalance }> {
    return this.request('/api/v1/agx/claim-rewards', { method: 'POST' });
  }

  getAgxRewardHistory(): Promise<{ rewards: AgxRewardEntry[]; total: string }> {
    return this.request('/api/v1/agx/rewards/history');
  }

  getAgxTiers(): Promise<AgxTiersResponse> {
    return this.request('/api/v1/agx/tiers', {}, false);
  }

  getAgxStats(): Promise<AgxStats> {
    return this.request('/api/v1/agx/stats', {}, false);
  }

  getAgxEpochs(limit = 50): Promise<{ epochs: AgxRewardEpoch[] }> {
    return this.request(`/api/v1/agx/epochs?limit=${limit}`, {}, false);
  }

  listAgxDisputeStakes(): Promise<{ disputes: AgxDisputeStake[] }> {
    return this.request('/api/v1/agx/dispute-stakes');
  }

  stakeAgxDispute(
    marketId: string,
    amount?: string
  ): Promise<{ dispute: AgxDisputeStake; balance: AgxBalance }> {
    return this.request('/api/v1/agx/dispute-stake', {
      method: 'POST',
      body: JSON.stringify({ market_id: marketId, amount: amount ?? null }),
    });
  }

  /** Admin-only: attest a verified on-chain AGX balance for the caller. */
  syncAgxBalance(verifiedBalance: string): Promise<{ credited: string; balance: AgxBalance }> {
    return this.request('/api/v1/agx/sync-balance', {
      method: 'POST',
      body: JSON.stringify({ verified_balance: verifiedBalance }),
    });
  }

  /** Admin-only: close and distribute a reward epoch. */
  distributeAgxEpoch(
    body: { epoch_number?: number; total_fees_collected?: string } = {}
  ): Promise<{ epoch: AgxRewardEpoch; rewarded_stakers: number }> {
    return this.request('/api/v1/agx/epochs/distribute', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  /** Cached multi-source news carousel (RSS + GDELT + Currents + Wikimedia) linked to active markets. */
  getNewsCarousel(
    limit = 12,
    filters?: { category?: string; tag?: string }
  ): Promise<{ items: NewsCarouselItem[]; sources: string[] }> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (filters?.category && filters.category !== 'Trending' && filters.category !== 'New') {
      params.set('category', filters.category);
    }
    if (filters?.tag && filters.tag !== 'ALL') {
      params.set('tag', filters.tag);
    }
    return this.request(`/api/v4/prediction/news/carousel?${params.toString()}`, {}, false);
  }
}

export interface NewsCarouselItem {
  id: string;
  news_title: string;
  caption: string;
  source: string;
  article_url: string | null;
  image_url: string | null;
  published_at: string | null;
  provider: string;
  event_id: string;
  market_id: string | null;
  market_slug: string;
  market_title: string;
  category: string;
  yes_pct: number | null;
  volume: number;
}

export const api = new ApiClient();
