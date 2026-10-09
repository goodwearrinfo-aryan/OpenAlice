// Institutional concepts: Order Blocks, Fair Value Gaps (FVG), etc.
import { SwingPoint, SwingDetector } from './swing';

export type OrderBlockType = 'bullish' | 'bearish';
export type FVGType = 'bullish' | 'bearish';
export type BlockType = 'order' | 'breaker' | 'mitigation' | 'rejection' | 'propulsion' | 'fvg' | 'ifvg';

export interface InstitutionalZone {
  high: number;
  low: number;
  midpoint: number;
  type: OrderBlockType | FVGType;
  blockType: BlockType;
  timeframe: string;
  direction: 'up' | 'down';
  creationTimestamp: number;
  creationIndex: number;
  age: number; // in bars
  mitigationStatus: 'unmitigated' | 'partially_mitigated' | 'fully_mitigated';
  invalidationStatus: boolean;
  retests: number;
  strength: number;
  volume?: number; // volume at creation if available
}

export interface OrderBlock extends InstitutionalZone {
  blockType: 'order';
  candleIndex: number;
  candleOpen: number;
  candleClose: number;
  candleHigh: number;
  candleLow: number;
}

export interface BreakerBlock extends InstitutionalZone {
  blockType: 'breaker';
  brokenLevel: number;
  brokenTimestamp: number;
}

export interface MitigationBlock extends InstitutionalZone {
  blockType: 'mitigation';
  mitigatedZone: InstitutionalZone;
  mitigationTimestamp: number;
}

export interface RejectionBlock extends InstitutionalZone {
  blockType: 'rejection';
  rejectionPrice: number;
  rejectionTimestamp: number;
}

export interface PropulsionBlock extends InstitutionalZone {
  blockType: 'propulsion';
  displacementStartIndex: number;
  displacementEndIndex: number;
}

export interface FairValueGap extends InstitutionalZone {
  blockType: 'fvg';
  gapType: FVGType;
  gapHigh: number;
  gapLow: number;
  gapSize: number;
  leftCandleHigh: number;
  leftCandleLow: number;
  rightCandleHigh: number;
  rightCandleLow: number;
}

export interface InverseFairValueGap extends InstitutionalZone {
  blockType: 'ifvg';
  originalFVG: FairValueGap;
  inversionTimestamp: number;
}

export interface BalancedPriceRange {
  top: number;
  bottom: number;
  midpoint: number;
  timeframe: string;
  creationTimestamp: number;
  strength: number;
}

export interface VolumeImbalance {
  price: number;
  volume: number;
  averageVolume: number;
  ratio: number; // volume / averageVolume
  timestamp: number;
  direction: 'buy' | 'sell';
}

export interface ConsequentEncroachment {
  zone: InstitutionalZone;
  encroachmentPrice: number;
  encroachmentPercentage: number; // 0-100% of zone
  timestamp: number;
}

export interface DisplacementCandle {
  index: number;
  high: number;
  low: number;
  open: number;
  close: number;
  volume: number;
  bodySize: number;
  wickSize: number;
  direction: 'bullish' | 'bearish';
  timestamp: number;
}

export class InstitutionalAnalyzer {
  private swingDetector: SwingDetector;
  private orderBlocks: OrderBlock[] = [];
  private breakerBlocks: BreakerBlock[] = [];
  private mitigationBlocks: MitigationBlock[] = [];
  private rejectionBlocks: RejectionBlock[] = [];
  private propulsionBlocks: PropulsionBlock[] = [];
  private fairValueGaps: FairValueGap[] = [];
  private inverseFVGs: InverseFairValueGap[] = [];
  private balancedPriceRanges: BalancedPriceRange[] = [];
  private volumeImbalances: VolumeImbalance[] = [];
  private consequentEncroachments: ConsequentEncroachment[] = [];
  private displacementCandles: DisplacementCandle[] = [];
  private readonly lookbackPeriod: number;
  private currentIndex: number = 0;

  constructor(options: { 
    lookbackPeriod?: number;
    swingDetectorOptions?: Partial<import('./swing').SwingDetectorOptions> 
  } = {}) {
    this.swingDetector = new SwingDetector(options.swingDetectorOptions);
    this.lookbackPeriod = options.lookbackPeriod ?? 200;
  }

  addBar(
    high: number, 
    low: number, 
    open: number, 
    close: number, 
    volume: number, 
    timestamp: number,
    timeframe: string = '1h'
  ): void {
    this.swingDetector.addBar(high, low, timestamp);
    this.currentIndex++;
    
    // Detect institutional zones
    this.detectOrderBlocks(high, low, open, close, volume, timestamp, timeframe);
    this.detectFairValueGaps(high, low, open, close, timestamp, timeframe);
    this.detectDisplacementCandles(high, low, open, close, volume, timestamp);
    this.detectVolumeImbalances(volume, timestamp);
    this.updateZoneStatus(high, low, close, timestamp);
    this.cleanupOldZones();
  }

  private detectOrderBlocks(
    high: number, 
    low: number, 
    open: number, 
    close: number, 
    volume: number, 
    timestamp: number,
    timeframe: string
  ): void {
    // Bullish Order Block: last down candle before a strong up move (displacement)
    // Bearish Order Block: last up candle before a strong down move (displacement)
    
    // We need to look at recent candles to find displacement
    // For simplicity, we'll check the last 3 candles for a displacement pattern
    if (this.currentIndex < 3) return;
    
    // This is a simplified detection - in practice you'd maintain a candle history
    // A bullish OB is a down candle followed by a strong up move
    // A bearish OB is an up candle followed by a strong down move
    
    // For now, we'll create a basic detection based on candle structure
    const bodySize = Math.abs(close - open);
    const range = high - low;
    const bodyToRangeRatio = bodySize / range;
    
    // Only consider candles with significant bodies (not dojis)
    if (bodyToRangeRatio < 0.3) return;
    
    const isBullishCandle = close > open;
    const isBearishCandle = close < open;
    
    // Check for displacement in the next candle (simplified - would need history)
    // This is a placeholder for the actual implementation
  }

  private detectFairValueGaps(
    high: number, 
    low: number, 
    open: number, 
    close: number, 
    timestamp: number,
    timeframe: string
  ): void {
    // FVG detection requires 3 candles:
    // Bullish FVG: candle 1 high < candle 3 low (gap between 1 and 3)
    // Bearish FVG: candle 1 low > candle 3 high (gap between 1 and 3)
    // This requires maintaining candle history - simplified for now
    
    if (this.currentIndex < 3) return;
    
    // In a full implementation, we'd maintain a rolling window of candles
    // and check for the 3-candle FVG pattern
  }

  private detectDisplacementCandles(
    high: number, 
    low: number, 
    open: number, 
    close: number, 
    volume: number, 
    timestamp: number
  ): void {
    const bodySize = Math.abs(close - open);
    const range = high - low;
    const upperWick = high - Math.max(open, close);
    const lowerWick = Math.min(open, close) - low;
    const wickSize = upperWick + lowerWick;
    const direction = close > open ? 'bullish' : 'bearish';
    
    // Displacement candle: large body, small wicks, high volume
    const bodyToRangeRatio = bodySize / range;
    const wickToRangeRatio = wickSize / range;
    
    if (bodyToRangeRatio > 0.7 && wickToRangeRatio < 0.2) {
      this.displacementCandles.push({
        index: this.currentIndex,
        high,
        low,
        open,
        close,
        volume,
        bodySize,
        wickSize,
        direction,
        timestamp
      });
      
      // Keep only recent displacement candles
      if (this.displacementCandles.length > 50) {
        this.displacementCandles.shift();
      }
    }
  }

  private detectVolumeImbalances(volume: number, timestamp: number): void {
    // This would need historical volume data to calculate average
    // For now, just a placeholder structure
  }

  private updateZoneStatus(high: number, low: number, close: number, timestamp: number): void {
    // Update mitigation status of all zones
    const allZones = this.getAllZones();

    for (const zone of allZones) {
      if (zone.invalidationStatus) continue;
      
      // Check if price has entered the zone (mitigation)
      const priceInZone = close >= zone.low && close <= zone.high;
      const priceBelowZone = close < zone.low;
      const priceAboveZone = close > zone.high;
      
      // Check invalidation - price closes beyond the zone in the opposite direction
      if (zone.direction === 'up' && priceBelowZone) {
        // Bullish zone invalidated by close below
        zone.invalidationStatus = true;
      } else if (zone.direction === 'down' && priceAboveZone) {
        // Bearish zone invalidated by close above
        zone.invalidationStatus = true;
      }
      
      // Check mitigation - price enters the zone
      if (priceInZone && zone.mitigationStatus === 'unmitigated') {
        zone.mitigationStatus = 'partially_mitigated';
        zone.retests++;
      } else if (priceInZone && zone.mitigationStatus === 'partially_mitigated') {
        zone.mitigationStatus = 'fully_mitigated';
        zone.retests++;
      }
      
      // Update age
      zone.age = this.currentIndex - zone.creationIndex;
    }
  }

  private getAllZones(): InstitutionalZone[] {
    return [
      ...this.orderBlocks,
      ...this.breakerBlocks,
      ...this.mitigationBlocks,
      ...this.rejectionBlocks,
      ...this.propulsionBlocks,
      ...this.fairValueGaps,
      ...this.inverseFVGs
    ];
  }

  private cleanupOldZones(): void {
    // Remove zones that are too old and fully mitigated/invalidated
    const maxAge = this.lookbackPeriod;
    
    const cleanArray = <T extends InstitutionalZone>(arr: T[]) => {
      return arr.filter(z => z.age < maxAge || z.mitigationStatus === 'unmitigated' || !z.invalidationStatus);
    };
    
    this.orderBlocks = cleanArray(this.orderBlocks);
    this.breakerBlocks = cleanArray(this.breakerBlocks);
    this.mitigationBlocks = cleanArray(this.mitigationBlocks);
    this.rejectionBlocks = cleanArray(this.rejectionBlocks);
    this.propulsionBlocks = cleanArray(this.propulsionBlocks);
    this.fairValueGaps = cleanArray(this.fairValueGaps);
    this.inverseFVGs = cleanArray(this.inverseFVGs);
  }

  // Getters
  getOrderBlocks(): OrderBlock[] { return [...this.orderBlocks]; }
  getBreakerBlocks(): BreakerBlock[] { return [...this.breakerBlocks]; }
  getMitigationBlocks(): MitigationBlock[] { return [...this.mitigationBlocks]; }
  getRejectionBlocks(): RejectionBlock[] { return [...this.rejectionBlocks]; }
  getPropulsionBlocks(): PropulsionBlock[] { return [...this.propulsionBlocks]; }
  getFairValueGaps(): FairValueGap[] { return [...this.fairValueGaps]; }
  getInverseFVGs(): InverseFairValueGap[] { return [...this.inverseFVGs]; }
  getBalancedPriceRanges(): BalancedPriceRange[] { return [...this.balancedPriceRanges]; }
  getVolumeImbalances(): VolumeImbalance[] { return [...this.volumeImbalances]; }
  getConsequentEncroachments(): ConsequentEncroachment[] { return [...this.consequentEncroachments]; }
  getDisplacementCandles(): DisplacementCandle[] { return [...this.displacementCandles]; }

  // Get unmitigated zones
  getUnmitigatedZones(): InstitutionalZone[] {
    const allZones = this.getAllZones();
    return allZones.filter(z => z.mitigationStatus === 'unmitigated' && !z.invalidationStatus);
  }

  // Get nearest zone to price
  getNearestZone(price: number, direction?: 'up' | 'down'): InstitutionalZone | null {
    const zones = this.getUnmitigatedZones()
      .filter(z => !direction || z.direction === direction);
    
    if (zones.length === 0) return null;
    
    return zones.reduce((prev, curr) => 
      Math.abs(prev.midpoint - price) < Math.abs(curr.midpoint - price) ? prev : curr
    );
  }

  reset(): void {
    this.swingDetector.reset();
    this.orderBlocks = [];
    this.breakerBlocks = [];
    this.mitigationBlocks = [];
    this.rejectionBlocks = [];
    this.propulsionBlocks = [];
    this.fairValueGaps = [];
    this.inverseFVGs = [];
    this.balancedPriceRanges = [];
    this.volumeImbalances = [];
    this.consequentEncroachments = [];
    this.displacementCandles = [];
    this.currentIndex = 0;
  }
}