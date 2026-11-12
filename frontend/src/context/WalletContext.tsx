import React, { createContext, useContext, useEffect, useState } from 'react'
import { useToast } from './toast'

export interface Web3WalletState {
  address: string | null
  chainId: number | null
  chainName: string
  isConnected: boolean
  isConnecting: boolean
  walletType: 'injected' | 'coinbase' | null
  error: string | null
  dexBuilderSynced: boolean
  connect: (type?: 'injected' | 'coinbase') => Promise<boolean>
  disconnect: () => void
  signMessage: (message: string) => Promise<string | null>
}

const WalletContext = createContext<Web3WalletState | undefined>(undefined)

const STORAGE_KEY_ADDR = 'dolymarket_wallet_addr'
const STORAGE_KEY_TYPE = 'dolymarket_wallet_type'

function resolveChainName(chainId: number | null): string {
  if (!chainId) return 'Unknown'
  switch (chainId) {
    case 1:
      return 'Ethereum'
    case 8453:
      return 'Base'
    case 42161:
      return 'Arbitrum One'
    case 10:
      return 'Optimism'
    case 137:
      return 'Polygon'
    case 31337:
    case 1337:
      return 'Localhost'
    default:
      return `EVM (${chainId})`
  }
}

/** Safely inspect window.ethereum without tripping strict proxy invariants from conflicting wallet extensions. */
function getSafeEthereumProvider(): any {
  if (typeof window === 'undefined') return null
  try {
    const win = window as any
    if (Array.isArray(win.ethereum?.providers) && win.ethereum.providers.length > 0) {
      for (const p of win.ethereum.providers) {
        try {
          if (p && typeof p.request === 'function') return p
        } catch {
          /* ignore proxy trap error */
        }
      }
    }
    return win.ethereum || null
  } catch (err) {
    console.warn('Could not access window.ethereum safely:', err)
    return null
  }
}

function safeHasMethod(obj: any, method: string): boolean {
  if (!obj) return false
  try {
    return typeof obj[method] === 'function'
  } catch {
    return false
  }
}

export function WalletProvider({ children }: { children: React.ReactNode }) {
  const { push: toast } = useToast()

  const [address, setAddress] = useState<string | null>(() => {
    return localStorage.getItem(STORAGE_KEY_ADDR)
  })
  const [walletType, setWalletType] = useState<'injected' | 'coinbase' | null>(() => {
    return (localStorage.getItem(STORAGE_KEY_TYPE) as any) || null
  })
  const [chainId, setChainId] = useState<number | null>(8453) // Default to Base
  const [isConnecting, setIsConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Listen for Ethereum window events (MetaMask, Rabby, etc.)
  useEffect(() => {
    try {
      const eth = getSafeEthereumProvider()
      if (!eth || !safeHasMethod(eth, 'on')) return

      const handleAccountsChanged = (accounts: string[]) => {
        try {
          if (!accounts || accounts.length === 0) {
            disconnect()
          } else {
            const next = accounts[0].toLowerCase()
            setAddress(next)
            localStorage.setItem(STORAGE_KEY_ADDR, next)
          }
        } catch (e) {
          console.warn('Error in accountsChanged:', e)
        }
      }

      const handleChainChanged = (hexChainId: string) => {
        try {
          const id = parseInt(hexChainId, 16)
          setChainId(id)
        } catch {
          /* ignore invalid chain id */
        }
      }

      try {
        eth.on('accountsChanged', handleAccountsChanged)
        eth.on('chainChanged', handleChainChanged)
      } catch (e) {
        console.warn('Failed to attach provider listeners:', e)
      }

      return () => {
        try {
          if (safeHasMethod(eth, 'removeListener')) {
            eth.removeListener('accountsChanged', handleAccountsChanged)
            eth.removeListener('chainChanged', handleChainChanged)
          }
        } catch {
          /* ignore cleanup errors */
        }
      }
    } catch (e) {
      console.warn('Ethereum provider initialization error:', e)
    }
  }, [])

  async function connect(
    type: 'injected' | 'coinbase' = 'injected'
  ): Promise<boolean> {
    setIsConnecting(true)
    setError(null)

    try {
      const eth = getSafeEthereumProvider()
      if (!eth || !safeHasMethod(eth, 'request')) {
        throw new Error('No browser wallet detected. Install MetaMask, Rabby, or Coinbase Wallet.')
      }

      const accounts: string[] = await eth.request({ method: 'eth_requestAccounts' })
      if (!accounts || accounts.length === 0) {
        throw new Error('Wallet connection was rejected.')
      }

      const connected = accounts[0].toLowerCase()
      setAddress(connected)
      setWalletType(type)
      localStorage.setItem(STORAGE_KEY_ADDR, connected)
      localStorage.setItem(STORAGE_KEY_TYPE, type)

      try {
        const hexId = await eth.request({ method: 'eth_chainId' })
        setChainId(parseInt(hexId, 16))
      } catch {
        setChainId(8453)
      }

      toast(`Connected: ${connected.slice(0, 6)}...${connected.slice(-4)}`, 'info')
      return true
    } catch (err: any) {
      const msg = err.message || 'Could not connect wallet'
      setError(msg)
      toast(msg, 'error')
      return false
    } finally {
      setIsConnecting(false)
    }
  }

  function disconnect() {
    setAddress(null)
    setWalletType(null)
    localStorage.removeItem(STORAGE_KEY_ADDR)
    localStorage.removeItem(STORAGE_KEY_TYPE)
    toast('Wallet disconnected', 'info')
  }

  async function signMessage(message: string): Promise<string | null> {
    const targetAddr = address || localStorage.getItem(STORAGE_KEY_ADDR)
    if (!targetAddr) {
      toast('Connect a wallet first', 'error')
      return null
    }

    try {
      const eth = getSafeEthereumProvider()
      if (!eth || !safeHasMethod(eth, 'request')) throw new Error('No wallet provider available')

      const signature = await eth.request({
        method: 'personal_sign',
        params: [message, targetAddr],
      })
      return signature
    } catch (err: any) {
      toast(err.message || 'Signature rejected', 'error')
      return null
    }
  }

  return (
    <WalletContext.Provider
      value={{
        address,
        chainId,
        chainName: resolveChainName(chainId),
        isConnected: Boolean(address),
        isConnecting,
        walletType,
        error,
        dexBuilderSynced: Boolean(address),
        connect,
        disconnect,
        signMessage,
      }}
    >
      {children}
    </WalletContext.Provider>
  )
}

export function useWallet(): Web3WalletState {
  const ctx = useContext(WalletContext)
  if (!ctx) {
    throw new Error('useWallet must be used inside a WalletProvider')
  }
  return ctx
}
