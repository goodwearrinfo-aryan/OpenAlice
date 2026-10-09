// Trend structure analysis
export interface SwingPoint {
  index: number; // index in the bar series
  price: number; // high for swing high, low for swing low
  type: 'high' | 'low';
  timestamp: number; // Unix timestamp in ms
  strength: number; // number of bars on left/right required to confirm
}

export interface TrendState {
  direction: 'up' | 'down' | 'sideways';
  lastHigherHigh: SwingPoint | null;
  lastHigherLow: SwingPoint | null;
  lastLowerHigh: SwingPoint | null;
  lastLowerLow: SwingPoint | null;
}

export class TrendAnalyzer {
  private swingPoints: SwingPoint[] = [];
  private trend: TrendState = {
    direction: 'sideways',
    lastHigherHigh: null,
    lastHigherLow: null,
    lastLowerHigh: null,
    lastLowerLow: null
  };
  private readonly leftStrength: number;
  private readonly rightStrength: number;

  constructor(options: { leftStrength?: number; rightStrength?: number } = {}) {
    this.leftStrength = options.leftStrength ?? 2;
    this.rightStrength = options.rightStrength ?? 2;
  }

  /**
   * Add a new bar to the detector
   * @param high - bar high
   * @param low - bar low
   * @param timestamp - bar timestamp (Unix ms)
   */
  addBar(high: number, low: number, timestamp: number): void {
    // First detect swing points from the new bar
    this.detectSwingPoints(high, low, timestamp);
    // Then update trend based on all swing points
    this.updateTrend();
  }

  private detectSwingPoints(high: number, low: number, timestamp: number): void {
    const index = this.swingPoints.length;
    
    // Add the new bar's high and low to our internal arrays for swing detection
    // We'll store them temporarily for swing detection calculation
    const tempHighs = this.swingPoints.map(p => p.type === 'high' ? p.price : -Infinity);
    const tempLows = this.swingPoints.map(p => p.type === 'low' ? p.price : Infinity);
    
    // Add current bar's values
    tempHighs.push(high);
    tempLows.push(low);
    
    // Check if we can confirm a swing at index - rightStrength
    const checkIndex = index - this.rightStrength;
    if (checkIndex >= this.leftStrength) {
      // Check if this is a swing high
      let isSwingHigh = true;
      for (let i = Math.max(0, checkIndex - this.leftStrength); i < checkIndex; i++) {
        if (tempHighs[i] >= high) {
          isSwingHigh = false;
          break;
        }
      }
      if (isSwingHigh) {
        for (let i = checkIndex + 1; i <= checkIndex + this.rightStrength; i++) {
          if (i < tempHighs.length && tempHighs[i] >= high) {
            isSwingHigh = false;
            break;
          }
        }
      }
      
      // Check if this is a swing low
      let isSwingLow = true;
      for (let i = Math.max(0, checkIndex - this.leftStrength); i < checkIndex; i++) {
        if (tempLows[i] <= low) {
          isSwingLow = false;
          break;
        }
      }
      if (isSwingLow) {
        for (let i = checkIndex + 1; i <= checkIndex + this.rightStrength; i++) {
          if (i < tempLows.length && tempLows[i] <= low) {
            isSwingLow = false;
            break;
          }
        }
      }
      
      if (isSwingHigh) {
        this.swingPoints.push({
          index: checkIndex,
          price: high,
          type: 'high',
          timestamp: timestamp - (this.rightStrength * 60000), // approximate timestamp
          strength: this.leftStrength
        });
      } else if (isSwingLow) {
        this.swingPoints.push({
          index: checkIndex,
          price: low,
          type: 'low',
          timestamp: timestamp - (this.rightStrength * 60000), // approximate timestamp
          strength: this.leftStrength
        });
      }
    }
  }

  private updateTrend(): void {
    if (this.swingPoints.length < 2) {
      this.trend.direction = 'sideways';
      return;
    }

    // Get the last two swing highs and lows
    const highs = this.swingPoints.filter(s => s.type === 'high');
    const lows = this.swingPoints.filter(s => s.type === 'low');

    // Update higher highs and higher lows (for uptrend)
    if (highs.length >= 2) {
      const last = highs[highs.length - 1];
      const prev = highs[highs.length - 2];
      if (last.price > prev.price) {
        this.trend.lastHigherHigh = last;
      } else {
        this.trend.lastHigherHigh = null;
      }
    }

    if (lows.length >= 2) {
      const last = lows[lows.length - 1];
      const prev = lows[lows.length - 2];
      if (last.price > prev.price) {
        this.trend.lastHigherLow = last;
      } else {
        this.trend.lastHigherLow = null;
      }
    }

    // Update lower highs and lower lows (for downtrend)
    if (highs.length >= 2) {
      const last = highs[highs.length - 1];
      const prev = highs[highs.length - 2];
      if (last.price < prev.price) {
        this.trend.lastLowerHigh = last;
      } else {
        this.trend.lastLowerHigh = null;
      }
    }

    if (lows.length >= 2) {
      const last = lows[lows.length - 1];
      const prev = lows[lows.length - 2];
      if (last.price < prev.price) {
        this.trend.lastLowerLow = last;
      } else {
        this.trend.lastLowerLow = null;
      }
    }

    // Determine trend direction
    const hh = this.trend.lastHigherHigh !== null;
    const hl = this.trend.lastHigherLow !== null;
    const lh = this.trend.lastLowerHigh !== null;
    const ll = this.trend.lastLowerLow !== null;

    if (hh && hl) {
      this.trend.direction = 'up';
    } else if (lh && ll) {
      this.trend.direction = 'down';
    } else {
      this.trend.direction = 'sideways';
    }
  }

  getTrend(): TrendState {
    return { ...this.trend };
  }

  reset(): void {
    this.swingPoints = [];
    this.trend = {
      direction: 'sideways',
      lastHigherHigh: null,
      lastHigherLow: null,
      lastLowerHigh: null,
      lastLowerLow: null
    };
  }
}