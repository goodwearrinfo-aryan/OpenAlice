// Liquidity analysis for Smart Money Concepts (SMC)
import { SwingPoint, SwingDetector } from './swing';

export interface LiquidityPool {
  price: number;
  type: 'BSL' | 'SSL'; // Buy-Side Liquidity or Sell-Side Liquidity
  strength: number; // number of swing points at this level
  swingIndices: number[]; // indices of swing points forming this pool
  firstTouch: number; // timestamp of first touch
  lastTouch: number; // timestamp of last touch
  isSwept: boolean;
  sweptTimestamp?: number;
  sweptPrice?: number;
}

export interface LiquiditySweep {
  pool: LiquidityPool;
  sweepPrice: number;
  sweepTimestamp: number;
  direction: 'up' | 'down'; // direction of the sweep
  isGenuine: boolean; // whether it's a genuine sweep vs liquidity grab
  retestPrice?: number;
  retestTimestamp?: number;
}

export interface LiquidityVoid {
  topPrice: number;
  bottomPrice: number;
  direction: 'up' | 'down';
  startIndex: number;
  endIndex: number;
  timestamp: number;
}

export interface Inducement {
  level: number;
  type: 'bullish' | 'bearish';
  targetLiquidity: LiquidityPool;
  timestamp: number;
}

export class LiquidityAnalyzer {
  private swingDetector: SwingDetector;
  private liquidityPools: LiquidityPool[] = [];
  private sweeps: LiquiditySweep[] = [];
  private voids: LiquidityVoid[] = [];
  private inducements: Inducement[] = [];
  private readonly lookbackPeriod: number;
  private readonly priceTolerance: number;

  constructor(options: { 
    lookbackPeriod?: number; 
    priceTolerance?: number;
    swingDetectorOptions?: Partial<import('./swing').SwingDetectorOptions> 
  } = {}) {
    this.swingDetector = new SwingDetector(options.swingDetectorOptions);
    this.lookbackPeriod = options.lookbackPeriod ?? 200;
    this.priceTolerance = options.priceTolerance ?? 0.002; // 0.2%
  }

  addBar(high: number, low: number, close: number, timestamp: number): void {
    this.swingDetector.addBar(high, low, timestamp);
    this.updateLiquidityPools(high, low, timestamp);
    this.detectSweeps(high, low, close, timestamp);
    this.detectVoids(high, low, close, timestamp);
    this.detectInducements(high, low, close, timestamp);
  }

  private updateLiquidityPools(high: number, low: number, timestamp: number): void {
    const swings = this.swingDetector.getSwings();
    if (swings.length === 0) return;

    // Group swing highs (SSL - Sell Side Liquidity) and swing lows (BSL - Buy Side Liquidity)
    const highs = swings.filter(s => s.type === 'high');
    const lows = swings.filter(s => s.type === 'low');

    // Process swing highs as SSL
    this.groupLiquidityPoints(highs, 'SSL', timestamp);
    
    // Process swing lows as BSL
    this.groupLiquidityPoints(lows, 'BSL', timestamp);
  }

  private groupLiquidityPoints(points: SwingPoint[], type: 'BSL' | 'SSL', timestamp: number): void {
    for (const point of points) {
      let found = false;
      for (const pool of this.liquidityPools) {
        if (pool.type === type && Math.abs(point.price - pool.price) / pool.price < this.priceTolerance) {
          // Add to existing pool
          pool.strength++;
          pool.swingIndices.push(point.index);
          pool.lastTouch = timestamp;
          found = true;
          break;
        }
      }
      if (!found) {
        // Create new pool
        this.liquidityPools.push({
          price: point.price,
          type,
          strength: 1,
          swingIndices: [point.index],
          firstTouch: timestamp,
          lastTouch: timestamp,
          isSwept: false
        });
      }
    }

    // Sort pools by strength
    this.liquidityPools.sort((a, b) => b.strength - a.strength);
  }

  private detectSweeps(high: number, low: number, close: number, timestamp: number): void {
    for (const pool of this.liquidityPools) {
      if (pool.isSwept) continue;

      if (pool.type === 'SSL' && high > pool.price) {
        // SSL swept - price broke above sell-side liquidity
        const isGenuine = this.isGenuineSweep(pool.price, high, 'up');
        const sweep: LiquiditySweep = {
          pool,
          sweepPrice: high,
          sweepTimestamp: timestamp,
          direction: 'up',
          isGenuine
        };
        pool.isSwept = true;
        pool.sweptTimestamp = timestamp;
        pool.sweptPrice = high;
        this.sweeps.push(sweep);
      } else if (pool.type === 'BSL' && low < pool.price) {
        // BSL swept - price broke below buy-side liquidity
        const isGenuine = this.isGenuineSweep(pool.price, low, 'down');
        const sweep: LiquiditySweep = {
          pool,
          sweepPrice: low,
          sweepTimestamp: timestamp,
          direction: 'down',
          isGenuine
        };
        pool.isSwept = true;
        pool.sweptTimestamp = timestamp;
        pool.sweptPrice = low;
        this.sweeps.push(sweep);
      }
    }
  }

  private isGenuineSweep(poolPrice: number, sweepPrice: number, direction: 'up' | 'down'): boolean {
    // A genuine sweep should have some momentum beyond the pool
    // Calculate the penetration depth
    const penetration = direction === 'up' 
      ? (sweepPrice - poolPrice) / poolPrice 
      : (poolPrice - sweepPrice) / poolPrice;
    
    // Require at least 0.1% penetration for genuine sweep
    return penetration > 0.001;
  }

  private detectVoids(high: number, low: number, close: number, timestamp: number): void {
    // Detect liquidity voids - rapid price movement with little volume/liquidity
    // This is a simplified detection based on large candle bodies relative to recent range
    // In a full implementation, this would use volume data
  }

  private detectInducements(high: number, low: number, close: number, timestamp: number): void {
    // Detect inducement - price targeting liquidity to trigger stops before reversing
    // This would look for price approaching a liquidity pool but not sweeping it yet
  }

  getLiquidityPools(): LiquidityPool[] {
    return [...this.liquidityPools];
  }

  getSweeps(): LiquiditySweep[] {
    return [...this.sweeps];
  }

  getVoids(): LiquidityVoid[] {
    return [...this.voids];
  }

  getInducements(): Inducement[] {
    return [...this.inducements];
  }

  getNearestLiquidity(price: number, type: 'BSL' | 'SSL'): LiquidityPool | null {
    const pools = this.liquidityPools.filter(p => p.type === type && !p.isSwept);
    if (pools.length === 0) return null;

    if (type === 'BSL') {
      // For BSL, find the highest pool below current price
      const below = pools.filter(p => p.price < price);
      if (below.length === 0) return null;
      return below.reduce((prev, curr) => (price - prev.price) < (price - curr.price) ? prev : curr);
    } else {
      // For SSL, find the lowest pool above current price
      const above = pools.filter(p => p.price > price);
      if (above.length === 0) return null;
      return above.reduce((prev, curr) => (prev.price - price) < (curr.price - price) ? prev : curr);
    }
  }

  getSweptLiquidity(type: 'BSL' | 'SSL'): LiquidityPool[] {
    return this.liquidityPools.filter(p => p.type === type && p.isSwept);
  }

  getRemainingLiquidity(type: 'BSL' | 'SSL'): LiquidityPool[] {
    return this.liquidityPools.filter(p => p.type === type && !p.isSwept);
  }

  getProbableDrawOnLiquidityTarget(price: number): number | null {
    // Calculate probable target based on remaining liquidity
    const bsl = this.getNearestLiquidity(price, 'BSL');
    const ssl = this.getNearestLiquidity(price, 'SSL');
    
    // If price is closer to BSL, target SSL, and vice versa
    if (bsl && ssl) {
      const distToBsl = price - bsl.price;
      const distToSsl = ssl.price - price;
      return distToBsl < distToSsl ? ssl.price : bsl.price;
    }
    return ssl?.price ?? bsl?.price ?? null;
  }

  reset(): void {
    this.swingDetector.reset();
    this.liquidityPools = [];
    this.sweeps = [];
    this.voids = [];
    this.inducements = [];
  }
}