/**
 * Paper-trade demo script for OpenAlice
 *
 * Feeds back-test signals into the UTA mock broker.
 * Usage: pnpm -F @traderalice/desktop run-script paper-trade
 * or: node scripts/paper-trade.ts
 */

import { UTAManagerSDK } from '@traderalice/uta-client'
import { runBacktest, runAllLegs } from '../services/backtest/index.js'

async function paperTrade () {
  const uta = new UTAManagerSDK()
  await uta.connect()

  // Run backtest for BTC-PERP with default parameters
  const result = await runBacktest('BTC-PERP', {
    fee: 0.001,
    slippage: 0.0005
  })

  console.log('Backtest result:', JSON.stringify(result, null, 2))

  // Also run all 4 strategies and compare
  const allResults = await runAllLegs('BTC-PERP', {
    fee: 0.001,
    slippage: 0.0005
  })
  console.log('\nAll strategies:')
  for (const leg of allResults.legs) {
    console.log(`  ${leg.leg}: ${leg.trades} trades, ${leg.win_rate}% win rate, ` +
      `${leg.avg_ret_pct}% avg ret, ${leg.total_ret_pct}% total ret`)
  }

  uta.disconnect()

  return { result, allResults }
}

export { paperTrade }

if (require.main === module) {
  paperTrade().then(({ result, allResults }) => {
    console.log('Paper trade complete')
    process.exit(0)
  }).catch(err => {
    console.error('Paper trade failed:', err)
    process.exit(1)
  })
}