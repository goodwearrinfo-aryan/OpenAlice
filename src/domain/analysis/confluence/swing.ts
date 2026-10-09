// Swing detection for market structure analysis
export interface SwingPoint {
  index: number; // index in the bar series
  price: number; // high for swing high, low for swing low
  type: 'high' | 'low';
  timestamp: number; // Unix timestamp in ms
  strength: number; // number of bars on left/right required to confirm
}

export interface SwingDetectorOptions {
  leftStrength: number; // bars to left for confirmation
  rightStrength: number; // bars to right for confirmation
}

export class SwingDetector {
  private highs: number[] = [];
  private lows: number[] = [];
  private timestamps: number[] = [];
  private swings: SwingPoint[] = [];
  private readonly leftStrength: number;
  private readonly rightStrength: number;

  constructor(options: Partial<SwingDetectorOptions> = {}) {
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
    this.highs.push(high);
    this.lows.push(low);
    this.timestamps.push(timestamp);
    this.detectSwings();
  }

  /**
   * Detect new swing points based on the latest bar
   * We can only confirm a swing when we have enough rightStrength bars after it
   */
  private detectSwings(): void {
    const len = this.highs.length;
    // We can only confirm a swing at index i if we have i + rightStrength < len
    const startIndex = Math.max(this.leftStrength, this.swings.length > 0 ? this.swings[this.swings.length - 1].index + 1 : 0);
    for (let i = startIndex; i <= len - this.rightStrength - 1; i++) {
      // Check if we already have a swing at this index
      if (this.swings.some(s => s.index === i)) continue;

      const isSwingHigh = this.isSwingHigh(i);
      const isSwingLow = this.isSwingLow(i);

      if (isSwingHigh) {
        this.swings.push({
          index: i,
          price: this.highs[i],
          type: 'high',
          timestamp: this.timestamps[i],
          strength: this.leftStrength // using leftStrength as the confirmation strength
        });
      } else if (isSwingLow) {
        this.swings.push({
          index: i,
          price: this.lows[i],
          type: 'low',
          timestamp: this.timestamps[i],
          strength: this.leftStrength
        });
      }
    }
  }

  private isSwingHigh(index: number): boolean {
    const leftStart = Math.max(0, index - this.leftStrength);
    const rightEnd = Math.min(this.highs.length, index + this.rightStrength + 1);

    // Check left side
    for (let i = leftStart; i < index; i++) {
      if (this.highs[i] >= this.highs[index]) {
        return false;
      }
    }
    // Check right side
    for (let i = index + 1; i < rightEnd; i++) {
      if (this.highs[i] >= this.highs[index]) {
        return false;
      }
    }
    return true;
  }

  private isSwingLow(index: number): boolean {
    const leftStart = Math.max(0, index - this.leftStrength);
    const rightEnd = Math.min(this.lows.length, index + this.rightStrength + 1);

    // Check left side
    for (let i = leftStart; i < index; i++) {
      if (this.lows[i] <= this.lows[index]) {
        return false;
      }
    }
    // Check right side
    for (let i = index + 1; i < rightEnd; i++) {
      if (this.lows[i] <= this.lows[index]) {
        return false;
      }
    }
    return true;
  }

  /**
   * Get all confirmed swing points
   */
  getSwings(): SwingPoint[] {
    return [...this.swings];
  }

  /**
   * Get the last swing point of a given type
   */
  getLastSwing(type: 'high' | 'low'): SwingPoint | null {
    for (let i = this.swings.length - 1; i >= 0; i--) {
      if (this.swings[i].type === type) {
        return this.swings[i];
      }
    }
    return null;
  }

  /**
   * Get the last two swing points (for trend analysis)
   */
  getLastTwoSwings(): [SwingPoint | null, SwingPoint | null] {
    const highs = this.swings.filter(s => s.type === 'high');
    const lows = this.swings.filter(s => s.type === 'low');
    const lastHigh = highs.length > 0 ? highs[highs.length - 1] : null;
    const lastLow = lows.length > 0 ? lows[lows.length - 1] : null;
    return [lastHigh, lastLow];
  }

  /**
   * Reset the detector
   */
  reset(): void {
    this.highs = [];
    this.lows = [];
    this.timestamps = [];
    this.swings = [];
  }
}