/** Unit tests for OpenAlice backtesting engine. */
/* eslint-env node */

import { describe, it, expect, vi } from 'vitest'
// Mock fs/promises — no real disk I/O
vi.mock('fs/promises', () => ({
  readFile: vi.fn(),
  writeFile: vi.fn().mockResolvedValue(undefined),
  mkdir: vi.fn().mockResolvedValue(undefined),
  unlink: vi.fn().mockResolvedValue(undefined),
  rm: vi.fn().mockResolvedValue(undefined),
  rename: vi.fn().mockResolvedValue(undefined),
  chmod: vi.fn().mockResolvedValue(undefined),
}))

// Mock the UTA client SDK
vi.mock('@traderalice/uta-client', () => ({
  UTAManagerSDK: class UTAManagerSDK {
    async connect () { return this }
    async disconnect () { }
  },
}))

// Import the backtest module under test
import { runBacktest, runAllLegs } from '../services/backtest/index.js'

describe('runBacktest', () => {
  it('should return a result with expected shape', async () => {
    const result = await runBacktest('BTC-PERP', { fee: 0.001, slippage: 0.0005 })

    // Core metrics
    expect(result).toHaveProperty('symbol', 'BTC-PERP')
    expect(result).toHaveProperty('leg')
    expect(result).toHaveProperty('trades')
    expect(result).toHaveProperty('win_rate')
    expect(result).toHaveProperty('avg_ret_pct')
    expect(result).toHaveProperty('total_ret_pct')
    expect(result).toHaveProperty('net_total_ret_pct')
    expect(result).toHaveProperty('net_avg_ret_pct')
    expect(result).toHaveProperty('net_win_rate')

    // Type checks
    expect(typeof result.win_rate).toBe('number')
    expect(typeof result.avg_ret_pct).toBe('number')
    expect(typeof result.total_ret_pct).toBe('number')
    expect(typeof result.net_total_ret_pct).toBe('number')
    expect(typeof result.net_avg_ret_pct).toBe('number')
    expect(typeof result.net_win_rate).toBe('number')

    // Win rate should be 0-100 range
    expect(result.win_rate).toBeGreaterThanOrEqual(0)
    expect(result.win_rate).toBeLessThanOrEqual(100)
  })

  it('should use default fee and slippage when not provided', async () => {
    const result = await runBacktest('ETH-PERP')

    expect(result.symbol).toBe('ETH-PERP')
    expect(typeof result.win_rate).toBe('number')
    expect(typeof result.avg_ret_pct).toBe('number')
    expect(typeof result.total_ret_pct).toBe('number')
  })

  it('should accept custom fee and slippage parameters', async () => {
    const result = await runBacktest('SOL-PERP', { fee: 0.002, slippage: 0.001 })

    expect(result.symbol).toBe('SOL-PERP')
    // Function should accept them without error
    expect(result).toBeDefined()
    expect(result.trades).toBeDefined()
  })

  it('should return results for all 4 legs via runAllLegs', async () => {
    const result = await runAllLegs('BTC-PERP', { fee: 0.001, slippage: 0.0005 })

    expect(result).toHaveProperty('symbol', 'BTC-PERP')
    expect(result).toHaveProperty('legs')
    expect(result.legs).toContain('candlesig')
    expect(result.legs).toContain('macdsig')
    expect(result.legs).toContain('coinrev')
    expect(result.legs).toContain('diverg')
    expect(result).toHaveProperty('summary')
    expect(result.summary).toHaveProperty('total_trades')
    expect(result.summary).toHaveProperty('avg_win_rate')
    expect(result.summary).toHaveProperty('avg_net_ret_pct')
  })
})