// Break of Structure (BOS) and Change of Character (CHOCH) detection
import { SwingDetector, SwingPoint } from './swing';
import { TrendAnalyzer } from './trend';

export interface StructureBreak {
  type: 'BOS' | 'CHOCH';
  direction: 'bullish' | 'bearish';
  breakPrice: number;
  breakIndex: number;
  breakTimestamp: number;
  swingPoint: SwingPoint; // the swing point that was broken
}

export class StructureBreaker {
  private swingDetector: SwingDetector;
  private trendAnalyzer: TrendAnalyzer;
  private breaks: StructureBreak[] = [];

  constructor(swingDetectorOptions: Partial<import('./swing').SwingDetectorOptions> = {}) {
    this.swingDetector = new SwingDetector(swingDetectorOptions);
    this.trendAnalyzer = new TrendAnalyzer(swingDetectorOptions);
  }

  addBar(high: number, low: number, timestamp: number): StructureBreak | null {
    this.swingDetector.addBar(high, low, timestamp);
    this.trendAnalyzer.addBar(high, low, timestamp);

    const trend = this.trendAnalyzer.getTrend();
    const swings = this.swingDetector.getSwings();
    if (swings.length < 2) return null;

    // Get the last swing point
    const lastSwing = swings[swings.length - 1];
    const currentIndex = this.swingDetector.highs.length - 1;
    const currentPriceHigh = this.swingDetector.highs[currentIndex];
    const currentPriceLow = this.swingDetector.lows[currentIndex];

    // Check for BOS: price breaks beyond the last swing in the direction of the trend
    if (trend.direction === 'up') {
      // Bullish BOS: price breaks above the last swing high
      if (lastSwing.type === 'high' && currentPriceHigh > lastSwing.price) {
        const bos: StructureBreak = {
          type: 'BOS',
          direction: 'bullish',
          breakPrice: currentPriceHigh,
          breakIndex: currentIndex,
          breakTimestamp: timestamp,
          swingPoint: lastSwing
        };
        this.breaks.push(bos);
        return bos;
      }
    } else if (trend.direction === 'down') {
      // Bearish BOS: price breaks below the last swing low
      if (lastSwing.type === 'low' && currentPriceLow < lastSwing.price) {
        const bos: StructureBreak = {
          type: 'BOS',
          direction: 'bearish',
          breakPrice: currentPriceLow,
          breakIndex: currentIndex,
          breakTimestamp: timestamp,
          swingPoint: lastSwing
        };
        this.breaks.push(bos);
        return bos;
      }
    }

    // Check for CHOCH: price breaks the last swing in the opposite direction of the trend
    // This indicates a potential change in character
    if (trend.direction === 'up') {
      // In an uptrend, if we break below the last swing low, it could be a CHOCH
      if (lastSwing.type === 'low' && currentPriceLow < lastSwing.price) {
        // But we need to confirm it's not just a retracement - check if we have a lower low
        const lastTwo = this.swingDetector.getLastTwoSwings();
        const prevHigh = lastTwo[0]; // last high
        const prevLow = lastTwo[1]; // last low
        if (prevHigh && prevLow && currentPriceLow < prevLow.price) {
          // We have a lower low, which could indicate CHOCH
          const choch: StructureBreak = {
            type: 'CHOCH',
            direction: 'bearish', // because we broke the low in an uptrend
            breakPrice: currentPriceLow,
            breakIndex: currentIndex,
            breakTimestamp: timestamp,
            swingPoint: lastSwing
          };
          this.breaks.push(choch);
          return choch;
        }
      }
    } else if (trend.direction === 'down') {
      // In a downtrend, if we break above the last swing high, it could be a CHOCH
      if (lastSwing.type === 'high' && currentPriceHigh > lastSwing.price) {
        const lastTwo = this.swingDetector.getLastTwoSwings();
        const prevHigh = lastTwo[0];
        const prevLow = lastTwo[1];
        if (prevHigh && prevLow && currentPriceHigh > prevHigh.price) {
          const choch: StructureBreak = {
            type: 'CHOCH',
            direction: 'bullish',
            breakPrice: currentPriceHigh,
            breakIndex: currentIndex,
            breakTimestamp: timestamp,
            swingPoint: lastSwing
          };
          this.breaks.push(choch);
          return choch;
        }
      }
    }

    return null;
  }

  getBreaks(): StructureBreak[] {
    return [...this.breaks];
  }

  reset(): void {
    this.swingDetector.reset();
    this.trendAnalyzer.reset();
    this.breaks = [];
  }
}