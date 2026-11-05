/**
 * Resilient public WebSocket client.
 *
 * - exponential backoff reconnect (1s min, 30s max, 0-20% jitter)
 * - L2 order-book resync on every reconnect (and on detected stream gaps)
 * - 30s heartbeat with a 10s pong deadline before forcibly recycling socket
 */
import type { OrderBookSnapshot } from './client'

export type SocketState = 'connecting' | 'open' | 'reconnecting' | 'closed'

export interface SocketSubscription {
  action: 'subscribe'
  channel: string
  token_id?: string
}

export interface PredictionSocketOptions {
  url: string
  subscriptions: SocketSubscription[] | (() => SocketSubscription[])
  getSnapshot?: () => Promise<OrderBookSnapshot>
  onMessage: (message: any) => void
  onState?: (state: SocketState) => void
  pingIntervalMs?: number
  pongTimeoutMs?: number
}

const MIN_RECONNECT_MS = 1_000
const MAX_RECONNECT_MS = 30_000
const DEFAULT_PING_MS = 30_000
const DEFAULT_PONG_TIMEOUT_MS = 10_000

export class PredictionSocket {
  private ws: WebSocket | null = null
  private attempt = 0
  private closedByUser = false
  private reconnectTimer: number | null = null
  private heartbeatTimer: number | null = null
  private pongTimer: number | null = null
  private lastStreamSequence = 0
  private resyncing = false
  private readonly pingIntervalMs: number
  private readonly pongTimeoutMs: number

  constructor(private readonly options: PredictionSocketOptions) {
    this.pingIntervalMs = options.pingIntervalMs ?? DEFAULT_PING_MS
    this.pongTimeoutMs = options.pongTimeoutMs ?? DEFAULT_PONG_TIMEOUT_MS
  }

  connect(): void {
    this.closedByUser = false
    this.open()
  }

  close(): void {
    this.closedByUser = true
    this.clearTimers()
    if (this.reconnectTimer != null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.ws?.close()
    this.ws = null
    this.emitState('closed')
  }

  private open(): void {
    this.emitState(this.attempt === 0 ? 'connecting' : 'reconnecting')
    const ws = new WebSocket(this.options.url)
    this.ws = ws

    ws.onopen = () => {
      this.attempt = 0
      this.emitState('open')
      const subscriptions =
        typeof this.options.subscriptions === 'function'
          ? this.options.subscriptions()
          : this.options.subscriptions
      subscriptions.forEach((sub) => ws.send(JSON.stringify(sub)))
      void this.requestSnapshot()
      this.startHeartbeat()
    }

    ws.onmessage = (event) => {
      let message: any
      try {
        message = JSON.parse(event.data)
      } catch {
        return
      }
      if (message?.action === 'pong') {
        this.clearPongTimer()
        return
      }
      this.trackSequence(message)
      this.options.onMessage(message)
    }

    ws.onerror = () => {
      // onclose always follows; reconnection is handled there.
    }

    ws.onclose = () => {
      this.clearTimers()
      if (this.closedByUser) {
        this.emitState('closed')
        return
      }
      this.scheduleReconnect()
    }
  }

  private trackSequence(message: any): void {
    const seq = Number(message?.stream_sequence)
    if (!Number.isFinite(seq) || seq <= 0) return
    if (this.lastStreamSequence > 0 && seq > this.lastStreamSequence + 1) {
      void this.requestSnapshot()
    }
    if (seq > this.lastStreamSequence) this.lastStreamSequence = seq
  }

  /** Fetch a fresh L2 snapshot before incremental deltas are reapplied. */
  private async requestSnapshot(): Promise<void> {
    if (!this.options.getSnapshot || this.resyncing) return
    this.resyncing = true
    try {
      const snapshot = await this.options.getSnapshot()
      const seq = Number((snapshot as any)?.stream_sequence)
      if (Number.isFinite(seq) && seq >= 0) {
        // The snapshot is authoritative: adopt its cursor even after a server
        // restart that reset the sequence counter.
        this.lastStreamSequence = seq
      }
      this.options.onMessage({ channel: 'pred.depth', ...snapshot })
    } catch {
      // The live socket keeps streaming; the caller's REST fallback also has
      // a chance to refresh state on the next reconnect.
    } finally {
      this.resyncing = false
    }
  }

  private startHeartbeat(): void {
    this.clearHeartbeat()
    this.heartbeatTimer = window.setInterval(() => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return
      this.ws.send(JSON.stringify({ action: 'ping' }))
      this.clearPongTimer()
      this.pongTimer = window.setTimeout(() => {
        // No pong within the deadline: force close so onclose reconnects.
        this.ws?.close()
      }, this.pongTimeoutMs)
    }, this.pingIntervalMs)
  }

  private scheduleReconnect(): void {
    if (this.closedByUser) return
    const exponential = Math.min(
      MAX_RECONNECT_MS,
      MIN_RECONNECT_MS * 2 ** this.attempt
    )
    const jitter = exponential * Math.random() * 0.2
    const delay = Math.min(MAX_RECONNECT_MS, exponential + jitter)
    this.attempt += 1
    this.emitState('reconnecting')
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.open()
    }, delay)
  }

  private clearTimers(): void {
    this.clearHeartbeat()
    this.clearPongTimer()
  }

  private clearHeartbeat(): void {
    if (this.heartbeatTimer != null) {
      window.clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  private clearPongTimer(): void {
    if (this.pongTimer != null) {
      window.clearTimeout(this.pongTimer)
      this.pongTimer = null
    }
  }

  private emitState(state: SocketState): void {
    this.options.onState?.(state)
  }
}

export function publicSocketUrl(path = '/api/v4/prediction/ws/public'): string {
  const explicit = import.meta.env.VITE_WS_URL
  if (explicit) return `${String(explicit).replace(/\/+$/, '')}${path}`
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}${path}`
}
