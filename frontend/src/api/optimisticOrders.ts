/**
 * Tiny optimistic-order store.
 *
 * Orders appear in the portfolio immediately with a "pending" pulse. They are
 * either confirmed with the server response or rolled back when the API returns
 * 4xx/network errors (the API client also raises a toast).
 */
import type { Order } from './client'

type Listener = (orders: Order[]) => void

let pending: Order[] = []
const listeners = new Set<Listener>()

function emit(): void {
  const snapshot = [...pending]
  listeners.forEach((listener) => listener(snapshot))
}

export function subscribePendingOrders(listener: Listener): () => void {
  listeners.add(listener)
  listener([...pending])
  return () => listeners.delete(listener)
}

export function getPendingOrders(): Order[] {
  return [...pending]
}

export function addPendingOrder(order: Order): string {
  const tempId = `pending-${Math.random().toString(36).slice(2)}`
  pending = [{ ...order, id: tempId, pending: true, status: 'PENDING' }, ...pending]
  emit()
  return tempId
}

export function confirmPendingOrder(tempId: string, serverOrder?: Order): void {
  pending = pending.filter((order) => order.id !== tempId)
  if (
    serverOrder &&
    (serverOrder.status === 'OPEN' || serverOrder.status === 'PARTIALLY_FILLED')
  ) {
    pending = [{ ...serverOrder, pending: false }, ...pending]
  }
  emit()
}

export function rejectPendingOrder(tempId: string): void {
  pending = pending.filter((order) => order.id !== tempId)
  emit()
}
