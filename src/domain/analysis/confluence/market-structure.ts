// Market structure analysis: support/resistance, trendlines, channels, etc.
import { SwingDetector, SwingPoint } from './swing';

export interface Level {
  price: number;
  strength: number; // number of touches
  lastTouch: number; // timestamp of last touch
  type: 'support' | 'resistance';
}

export interface Trendline {
  slope: number; // price change per bar
  intercept: number; // price at index 0
  strength: number; // number of points touching the line
  startIndex: number;
  endIndex: number;
  type: 'support' | 'resistance'; // whether it acts as support or resistance
}

export interface Channel {
  upper: Trendline;
  lower: Trendline;
  middle: Trendline; // midline
  width: number; // average distance between upper and lower
  type: 'ascending' | 'descending' | 'horizontal';
}

export class MarketStructure {
  private swingDetector: SwingDetector;
  private levels: Level[] = [];
  private trendlines: Trendline[] = [];
  private channels: Channel[] = [];
  private readonly lookbackPeriod: number; // how many bars back to look for structure

  constructor(options: { lookbackPeriod?: number; swingDetectorOptions?: Partial<import('./swing').SwingDetectorOptions> } = {}) {
    this.swingDetector = new SwingDetector(options.swingDetectorOptions);
    this.lookbackPeriod = options.lookbackPeriod ?? 100;
  }

  /**
   * Add a new bar to the market structure analyzer
   * @param high - bar high
   * @param low - bar low
   * @param close - bar close
   * @param timestamp - bar timestamp (Unix ms)
   */
  addBar(high: number, low: number, close: number, timestamp: number): void {
    this.swingDetector.addBar(high, low, timestamp);
    this.updateLevels(high, low, close, timestamp);
    this.updateTrendlines();
    this.updateChannels();
  }

  /**
   * Update support and resistance levels based on swing points
   */
  private updateLevels(high: number, low: number, close: number, timestamp: number): void {
    const swings = this.swingDetector.getSwings();
    if (swings.length === 0) return;

    // Consider only recent swings within lookback period
    const cutoff = timestamp - this.lookbackPeriod * 60 * 60 * 1000; // assuming 1h timeframe, adjust as needed
    const recentSwings = swings.filter(s => s.timestamp >= cutoff);

    // Group swings by price level (within a tolerance)
    const priceTolerance = 0.001; // 0.1% tolerance, adjust based on instrument
    const levelsMap = new Map<number, Level>();

    for (const swing of recentSwings) {
      let found = false;
      for (const [priceKey, level] of levelsMap.entries()) {
        if (Math.abs(swing.price - priceKey) / priceKey < priceTolerance) {
          // Update existing level
          level.strength++;
          level.lastTouch = timestamp;
          found = true;
          break;
        }
      }
      if (!found) {
        // Create new level
        const isResistance = swing.type === 'high';
        const level: Level = {
          price: swing.price,
          strength: 1,
          lastTouch: timestamp,
          type: isResistance ? 'resistance' : 'support'
        };
        levelsMap.set(swing.price, level);
      }
    }

    // Convert map back to array and sort by strength
    this.levels = Array.from(levelsMap.values()).sort((a, b) => b.strength - a.strength);
  }

  /**
   * Update trendlines using linear regression on swing points
   */
  private updateTrendlines(): void {
    const swings = this.swingDetector.getSwings();
    if (swings.length < 3) return; // need at least 3 points for a trendline

    // Separate highs and lows
    const highs = swings.filter(s => s.type === 'high');
    const lows = swings.filter(s => s.type === 'low');

    // Generate potential trendlines from highs (resistance) and lows (support)
    this.trendlines = [];

    // For resistance trendlines (connecting swing highs)
    if (highs.length >= 2) {
      const resistanceLines = this.generateTrendlines(highs, 'resistance');
      this.trendlines.push(...resistanceLines);
    }

    // For support trendlines (connecting swing lows)
    if (lows.length >= 2) {
      const supportLines = this.generateTrendlines(lows, 'support');
      this.trendlines.push(...supportLines);
    }

    // Sort by strength (number of points)
    this.trendlines.sort((a, b) => b.strength - a.strength);
  }

  /**
   * Generate trendlines from a set of points using linear regression
   */
  private generateTrendlines(points: SwingPoint[], type: 'support' | 'resistance'): Trendline[] {
    const lines: Trendline[] = [];
    const minPoints = 3; // minimum points to form a trendline

    // Try different combinations of points (for simplicity, we'll use consecutive points)
    // In a more sophisticated implementation, we'd try all combinations
    for (let i = 0; i <= points.length - minPoints; i++) {
      for (let j = i + minPoints - 1; j < points.length; j++) {
        const subset = points.slice(i, j + 1);
        const line = this.calculateTrendline(subset);
        if (line.strength >= minPoints) {
          lines.push(line);
        }
      }
    }

    // Remove duplicate or very similar lines (simplified)
    return lines.filter((line, index, self) => {
      return index === self.findIndex(l => 
        Math.abs(l.slope - line.slope) < 0.001 && 
        Math.abs(l.intercept - line.intercept) < 0.001
      );
    });
  }

  /**
   * Calculate a trendline using linear regression on points
   */
  private calculateTrendline(points: SwingPoint[]): Trendline {
    let sumX = 0, sumY = 0, sumXY = 0, sumXX = 0;
    const n = points.length;

    for (let i = 0; i < n; i++) {
      const x = i; // use index as x variable
      const y = points[i].price;
      sumX += x;
      sumY += y;
      sumXY += x * y;
      sumXX += x * x;
    }

    const slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX);
    const intercept = (sumY - slope * sumX) / n;

    // Calculate strength: how many points are close to the line
    const tolerance = 0.005; // 0.5% tolerance
    let strength = 0;
    for (let i = 0; i < n; i++) {
      const x = i;
      const y = points[i].price;
      const predicted = slope * x + intercept;
      if (Math.abs(y - predicted) / predicted < tolerance) {
        strength++;
      }
    }

    return {
      slope,
      intercept,
      strength,
      startIndex: points[0].index,
      endIndex: points[points.length - 1].index,
      type: points[0].type === 'high' ? 'resistance' : 'support' // simplified
    };
  }

  /**
   * Update channels based on parallel trendlines
   */
  private updateChannels(): void {
    this.channels = [];
    if (this.trendlines.length < 2) return;

    // Look for pairs of trendlines that are roughly parallel
    const parallelTolerance = 0.001; // slope difference tolerance
    for (let i = 0; i < this.trendlines.length; i++) {
      for (let j = i + 1; j < this.trendlines.length; j++) {
        const line1 = this.trendlines[i];
        const line2 = this.trendlines[j];

        // Check if lines are roughly parallel
        if (Math.abs(line1.slope - line2.slope) < parallelTolerance) {
          // Determine which is upper and lower based on average price
          const avgPrice1 = (line1.slope * 0 + line1.intercept + line1.slope * 100 + line1.intercept) / 2; // approximate
          const avgPrice2 = (line2.slope * 0 + line2.intercept + line2.slope * 100 + line2.intercept) / 2;

          const upper = avgPrice1 > avgPrice2 ? line1 : line2;
          const lower = avgPrice1 > avgPrice2 ? line2 : line1;

          // Calculate midline
          const midline: Trendline = {
            slope: (upper.slope + lower.slope) / 2,
            intercept: (upper.intercept + lower.intercept) / 2,
            strength: Math.min(upper.strength, lower.strength),
            startIndex: Math.max(upper.startIndex, lower.startIndex),
            endIndex: Math.min(upper.endIndex, lower.endIndex),
            type: 'support' // midline can act as both, but we'll label as support for simplicity
          };

          // Calculate average width (distance between lines)
          const width = Math.abs(upper.intercept - lower.intercept); // simplified, should be perpendicular distance

          // Determine channel type
          let type: 'ascending' | 'descending' | 'horizontal' = 'horizontal';
          if (upper.slope > 0.0001) {
            type = 'ascending';
          } else if (upper.slope < -0.0001) {
            type = 'descending';
          }

          this.channels.push({
            upper,
            lower,
            middle: midline,
            width,
            type
          });
        }
      }
    }
  }

  /**
   * Get all identified support and resistance levels
   */
  getLevels(): Level[] {
    return [...this.levels];
  }

  /**
   * Get all identified trendlines
   */
  getTrendlines(): Trendline[] {
    return [...this.trendlines];
  }

  /**
   * Get all identified channels
   */
  getChannels(): Channel[] {
    return [...this.channels];
  }

  /**
   * Get the nearest support level below a price
   */
  getNearestSupport(price: number): Level | null {
    const supports = this.levels.filter(l => l.type === 'support' && l.price < price);
    if (supports.length === 0) return null;
    return supports.reduce((prev, current) => 
      (price - prev.price) < (price - current.price) ? prev : current
    );
  }

  /**
   * Get the nearest resistance level above a price
   */
  getNearestResistance(price: number): Level | null {
    const resistances = this.levels.filter(l => l.type === 'resistance' && l.price > price);
    if (resistances.length === 0) return null;
    return resistances.reduce((prev, current) => 
      (prev.price - price) < (current.price - price) ? prev : current
    );
  }

  /**
   * Reset the market structure analyzer
   */
  reset(): void {
    this.swingDetector.reset();
    this.levels = [];
    this.trendlines = [];
    this.channels = [];
  }
}