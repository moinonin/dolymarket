import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { decodeFunctionResult, encodeFunctionData, formatUnits, parseAbi } from 'viem'
import { useToast } from './toast'

export interface DiscoveredWallet {
  id: string
  name: string
  icon?: string
  rdns?: string
  provider: any
}

export interface Web3WalletState {
  address: string | null
  chainId: number | null
  chainName: string
  isConnected: boolean
  isConnecting: boolean
  walletType: 'injected' | 'coinbase' | 'gate' | null
  error: string | null
  dexBuilderSynced: boolean
  discoveredWallets: DiscoveredWallet[]
  usdcBalance: string | null
  usdcBalanceLoading: boolean
  refreshUsdcBalance: () => Promise<string | null>
  connect: (type?: 'injected' | 'coinbase' | 'gate', providerOverride?: any) => Promise<boolean>
  disconnect: () => void
  signMessage: (message: string) => Promise<string | null>
  signTypedData: (typedData: Record<string, any>) => Promise<string | null>
  sendTransaction: (tx: { to: string; data?: string; value?: string }) => Promise<string | null>
}

const ERC20_BALANCE_ABI = parseAbi(['function balanceOf(address owner) view returns (uint256)'])

const USDC_CONTRACTS: Record<number, `0x${string}`> = {
  1: '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48',
  10: '0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85',
  137: '0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359',
  8453: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
  42161: '0xaf88d065e77c8cC2239327C5EDb3A432268e5831',
  84532: '0x036CbD53842c5426634e7929541eC2318f3dCF7e',
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

/** Safely inspect window.ethereum / window.gatewallet without tripping strict proxy invariants. */
function getSafeEthereumProvider(preferredType?: 'injected' | 'coinbase' | 'gate'): any {
  if (typeof window === 'undefined') return null
  try {
    const win = window as any
    if (preferredType === 'gate') {
      if (win.gatewallet && typeof win.gatewallet.request === 'function') return win.gatewallet
      if (Array.isArray(win.ethereum?.providers)) {
        const g = win.ethereum.providers.find((p: any) => p?.isGateWallet || p?.isGate)
        if (g) return g
      }
      if (win.ethereum?.isGateWallet || win.ethereum?.isGate) return win.ethereum
    }
    if (Array.isArray(win.ethereum?.providers) && win.ethereum.providers.length > 0) {
      for (const p of win.ethereum.providers) {
        try {
          if (p && typeof p.request === 'function') return p
        } catch {
          /* ignore proxy trap error */
        }
      }
    }
    return win.ethereum || win.gatewallet || null
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
  const [walletType, setWalletType] = useState<'injected' | 'coinbase' | 'gate' | null>(() => {
    return (localStorage.getItem(STORAGE_KEY_TYPE) as any) || null
  })
  const [chainId, setChainId] = useState<number | null>(8453) // Default to Base
  const [isConnecting, setIsConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [discoveredWallets, setDiscoveredWallets] = useState<DiscoveredWallet[]>([])
  const [usdcBalance, setUsdcBalance] = useState<string | null>(null)
  const [usdcBalanceLoading, setUsdcBalanceLoading] = useState(false)
  const activeProviderRef = useRef<any>(null)

  const refreshUsdcBalance = useCallback(async (): Promise<string | null> => {
    const targetAddr = address || localStorage.getItem(STORAGE_KEY_ADDR)
    if (!targetAddr || !chainId) {
      setUsdcBalance(null)
      return null
    }
    const contract = USDC_CONTRACTS[chainId]
    if (!contract) {
      setUsdcBalance(null)
      return null
    }
    const eth = activeProviderRef.current || getSafeEthereumProvider(walletType || undefined)
    if (!eth || !safeHasMethod(eth, 'request')) {
      return null
    }

    setUsdcBalanceLoading(true)
    try {
      const data = encodeFunctionData({
        abi: ERC20_BALANCE_ABI,
        functionName: 'balanceOf',
        args: [targetAddr as `0x${string}`],
      })
      const rawHex: string = await eth.request({
        method: 'eth_call',
        params: [{ to: contract, data }, 'latest'],
      })
      const raw = decodeFunctionResult({
        abi: ERC20_BALANCE_ABI,
        functionName: 'balanceOf',
        data: rawHex as `0x${string}`,
      })
      const formatted = Number(formatUnits(raw, 6)).toFixed(2)
      setUsdcBalance(formatted)
      return formatted
    } catch {
      setUsdcBalance(null)
      return null
    } finally {
      setUsdcBalanceLoading(false)
    }
  }, [address, chainId, walletType])

  useEffect(() => {
    if (address && chainId) {
      void refreshUsdcBalance()
    } else {
      setUsdcBalance(null)
    }
  }, [address, chainId, refreshUsdcBalance])

  // EIP-6963 multi-wallet discovery (Gate Wallet, MetaMask, Rabby, Coinbase, etc.)
  useEffect(() => {
    if (typeof window === 'undefined') return
    const onAnnounce = (event: any) => {
      const detail = event?.detail
      if (!detail?.provider || !detail?.info) return
      const id = detail.info.uuid || detail.info.rdns || detail.info.name
      setDiscoveredWallets((prev) => {
        if (prev.some((w) => w.id === id)) return prev
        return [
          ...prev,
          {
            id,
            name: detail.info.name || 'Browser Wallet',
            icon: detail.info.icon,
            rdns: detail.info.rdns,
            provider: detail.provider,
          },
        ]
      })
    }
    window.addEventListener('eip6963:announceProvider', onAnnounce)
    window.dispatchEvent(new Event('eip6963:requestProvider'))

    // Fallback: register window.gatewallet if present and not yet announced
    const win = window as any
    if (win.gatewallet && safeHasMethod(win.gatewallet, 'request')) {
      setDiscoveredWallets((prev) =>
        prev.some((w) => w.id === 'gate-injected' || w.name.toLowerCase().includes('gate'))
          ? prev
          : [...prev, { id: 'gate-injected', name: 'Gate Wallet', rdns: 'io.gate.wallet', provider: win.gatewallet }]
      )
    }

    return () => {
      window.removeEventListener('eip6963:announceProvider', onAnnounce)
    }
  }, [])

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
          localStorage.setItem('dolymarket_wallet_chain_id', String(id))
        } catch {
          /* ignore invalid chain id */
        }
      }

      if (safeHasMethod(eth, 'request')) {
        eth
          .request({ method: 'eth_chainId' })
          .then((hexId: string) => {
            const id = parseInt(hexId, 16)
            if (Number.isFinite(id) && id > 0) {
              setChainId(id)
              localStorage.setItem('dolymarket_wallet_chain_id', String(id))
            }
          })
          .catch(() => {
            /* ignore */
          })
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
    type: 'injected' | 'coinbase' | 'gate' = 'injected',
    providerOverride?: any
  ): Promise<boolean> {
    setIsConnecting(true)
    setError(null)

    try {
      const eip6963Fallback =
        discoveredWallets.find((w) =>
          type === 'gate'
            ? w.name.toLowerCase().includes('gate') || w.rdns?.includes('gate')
            : type === 'coinbase'
              ? w.name.toLowerCase().includes('coinbase') || w.rdns?.includes('coinbase')
              : !w.id.includes('shim')
        )?.provider || null
      const eth = providerOverride || eip6963Fallback || getSafeEthereumProvider(type)
      if (!eth || !safeHasMethod(eth, 'request')) {
        throw new Error('No browser wallet detected. Install Gate Wallet, MetaMask, Rabby, or Coinbase Wallet.')
      }
      activeProviderRef.current = eth

      const accounts: string[] = await Promise.race([
        eth.request({ method: 'eth_requestAccounts' }),
        new Promise<never>((_, reject) =>
          window.setTimeout(
            () =>
              reject(
                new Error(
                  'Wallet extension did not respond. If multiple wallets are installed (e.g. Gate Wallet + a Cardano extension), disable the conflicting extension or pick a specific EIP-6963 wallet.'
                )
              ),
            20000
          )
        ),
      ])
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
        const parsed = parseInt(hexId, 16)
        setChainId(parsed)
        localStorage.setItem('dolymarket_wallet_chain_id', String(parsed))
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
    activeProviderRef.current = null
    setAddress(null)
    setWalletType(null)
    setUsdcBalance(null)
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
      const eth = activeProviderRef.current || getSafeEthereumProvider(walletType || undefined)
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

  async function signTypedData(typedData: Record<string, any>): Promise<string | null> {
    const targetAddr = address || localStorage.getItem(STORAGE_KEY_ADDR)
    if (!targetAddr) {
      toast('Connect a wallet first', 'error')
      return null
    }

    try {
      const eth = activeProviderRef.current || getSafeEthereumProvider(walletType || undefined)
      if (!eth || !safeHasMethod(eth, 'request')) throw new Error('No wallet provider available')

      const domain = typedData.domain ?? {}
      const rawTypes = { ...(typedData.types ?? {}) }
      if (!rawTypes.EIP712Domain) {
        const domainFields: Array<{ name: string; type: string }> = []
        if (domain.name !== undefined) domainFields.push({ name: 'name', type: 'string' })
        if (domain.version !== undefined) domainFields.push({ name: 'version', type: 'string' })
        if (domain.chainId !== undefined) domainFields.push({ name: 'chainId', type: 'uint256' })
        if (domain.verifyingContract !== undefined) {
          domainFields.push({ name: 'verifyingContract', type: 'address' })
        }
        if (domain.salt !== undefined) domainFields.push({ name: 'salt', type: 'bytes32' })
        rawTypes.EIP712Domain = domainFields
      }

      const payload = {
        domain,
        types: rawTypes,
        primaryType: typedData.primaryType,
        message: typedData.message ?? {},
      }

      const signature = await eth.request({
        method: 'eth_signTypedData_v4',
        params: [targetAddr, JSON.stringify(payload)],
      })
      return signature
    } catch (err: any) {
      toast(err.message || 'Typed data signature rejected', 'error')
      return null
    }
  }

  async function sendTransaction(tx: { to: string; data?: string; value?: string }): Promise<string | null> {
    const targetAddr = address || localStorage.getItem(STORAGE_KEY_ADDR)
    if (!targetAddr) {
      toast('Connect a wallet first', 'error')
      return null
    }

    try {
      const eth = activeProviderRef.current || getSafeEthereumProvider(walletType || undefined)
      if (!eth || !safeHasMethod(eth, 'request')) throw new Error('No wallet provider available')

      const txHash = await eth.request({
        method: 'eth_sendTransaction',
        params: [
          {
            from: targetAddr,
            to: tx.to,
            ...(tx.data ? { data: tx.data } : {}),
            ...(tx.value ? { value: tx.value } : {}),
          },
        ],
      })
      return txHash
    } catch (err: any) {
      toast(err.message || 'Transaction rejected', 'error')
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
        discoveredWallets,
        usdcBalance,
        usdcBalanceLoading,
        refreshUsdcBalance,
        connect,
        disconnect,
        signMessage,
        signTypedData,
        sendTransaction,
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
