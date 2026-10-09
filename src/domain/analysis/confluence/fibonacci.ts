// Fibonacci analysis: retracements, extensions, confluence
import { SwingPoint, SwingDetector } from './swing';

export type FibonacciLevelType = 'retracement' | 'extension' | 'expansion';

export interface FibonacciLevel {
  level: number; // e.g., 0.5, 0.618, 0.705, 0.786, 0.886
  price: number;
  type: FibonacciLevelType;
  anchorHigh: number;
  anchorLow: number;
  anchorHighTimestamp: number;
  anchorLowTimestamp: number;
  strength: number; // confluence score with other factors
}

export interface FibonacciDrawing {
  id: string;
  anchorHigh: SwingPoint;
  anchorLow: SwingPoint;
  direction: 'up' | 'down'; // up = retracement from low to high, down = retracement from high to low
  levels: FibonacciLevel[];
  creationTimestamp: number;
  timeframe: string;
  isActive: boolean;
}

export interface FibonacciConfluence {
  price: number;
  levels: FibonacciLevel[]; // multiple fib levels converging at this price
  totalStrength: number;
  nearbyLiquidity?: number;
  nearbyOrderBlock?: boolean;
  nearbyFVG?: boolean;
  nearbySupportResistance?: boolean;
  nearbyVWAP?: boolean;
  nearbyMarketProfile?: boolean;
  nearbySessionLevel?: boolean;
  nearbyPreviousHighLow?: boolean;
}

export interface MeasuredMove {
  startPrice: number;
  endPrice: number;
  projectionPrice: number;
  direction: 'up' | 'down';
  confidence: number;
  timestamp: number;
}

export interface AB_CD_Pattern {
  pointA: SwingPoint;
  pointB: SwingPoint;
  pointC: SwingPoint;
  pointD: number; // projected D point
  type: 'bullish' | 'bearish';
  completionRatio: number; // CD/AB ratio
  timestamp: number;
}

export class FibonacciAnalyzer {
  private swingDetector: SwingDetector;
  private drawings: FibonacciDrawing[] = [];
  private confluences: FibonacciConfluence[] = [];
  private measuredMoves: MeasuredMove[] = [];
  private abcdPatterns: AB_CD_Pattern[] = [];
  private readonly lookbackPeriod: number;
  private readonly priceTolerance: number;

  // Key Fibonacci levels
  private static readonly RETRACEMENT_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.705, 0.786, 0.886];
  private static readonly EXTENSION_LEVELS = [1.0, 1.272, 1.414, 1.618, 2.0, 2.618];
  private static readonly EXPANSION_LEVELS = [0.618, 1.0, 1.618, 2.0, 2.618];

  constructor(options: { 
    lookbackPeriod?: number;
    priceTolerance?: number;
    swingDetectorOptions?: Partial<import('./swing').SwingDetectorOptions> 
  } = {}) {
    this.swingDetector = new SwingDetector(options.swingDetectorOptions);
    this.lookbackPeriod = options.lookbackPeriod ?? 200;
    this.priceTolerance = options.priceTolerance ?? 0.001; // 0.1%
  }

  addBar(high: number, low: number, timestamp: number): void {
    this.swingDetector.addBar(high, low, timestamp);
    this.updateFibonacciDrawings(high, low, timestamp);
    this.detectConfluences(high, low, timestamp);
    this.detectMeasuredMoves(high, low, timestamp);
    this.detectABCDPatterns(timestamp);
    this.cleanupOldDrawings();
  }

  private updateFibonacciDrawings(high: number, low: number, timestamp: number): void {
    const swings = this.swingDetector.getSwings();
    if (swings.length < 2) return;

    // Find significant swing points to anchor Fibonacci
    // We look for swings that are separated by enough distance and time
    const recentSwings = swings.slice(-10); // last 10 swings
    
    for (let i = 0; i < recentSwings.length - 1; i++) {
      for (let j = i + 1; j < recentSwings.length; j++) {
        const swing1 = recentSwings[i];
        const swing2 = recentSwings[j];
        
        // Only create Fibonacci between opposite swing types
        if (swing1.type === swing2.type) continue;
        
        // Check if the move is significant enough
        const priceDiff = Math.abs(swing2.price - swing1.price);
        const avgPrice = (swing1.price + swing2.price) / 2;
        const movePercent = priceDiff / avgPrice;
        
        // Require at least 1% move
        if (movePercent < 0.01) continue;
        
        // Check if we already have a drawing for this pair
        const existingDrawing = this.drawings.find(d => 
          d.anchorHigh.index === (swing1.type === 'high' ? swing1.index : swing2.index) &&
          d.anchorLow.index === (swing1.type === 'low' ? swing1.index : swing2.index)
        );
        
        if (existingDrawing) continue;
        
        // Create new Fibonacci drawing
        const anchorHigh = swing1.type === 'high' ? swing1 : swing2;
        const anchorLow = swing1.type === 'low' ? swing1 : swing2;
        const direction = anchorLow.index < anchorHigh.index ? 'up' : 'down';
        
        const levels = this.calculateFibonacciLevels(anchorHigh, anchorLow, direction);
        
        const drawing: FibonacciDrawing = {
          id: `fib_${anchorHigh.index}_${anchorLow.index}_${Date.now()}`,
          anchorHigh,
          anchorLow,
          direction,
          levels,
          creationTimestamp: timestamp,
          timeframe: '1h', // would come from context
          isActive: true
        };
        
        this.drawings.push(drawing);
      }
    }
  }

  private calculateFibonacciLevels(
    anchorHigh: SwingPoint, 
    anchorLow: SwingPoint, 
    direction: 'up' | 'down'
  ): FibonacciLevel[] {
    const levels: FibonacciLevel[] = [];
    const highPrice = anchorHigh.price;
    const lowPrice = anchorLow.price;
    const range = highPrice - lowPrice;
    
    // Retracement levels (0.236, 0.382, 0.5, 0.618, 0.705, 0.786, 0.886)
    if (direction === 'up') {
      // Retracement from low to high: levels below the high
      for (const level of FibonacciAnalyzer.RETRACEMENT_LEVELS) {
        const price = highPrice - (range * level);
        levels.push({
          level,
          price,
          type: 'retracement',
          anchorHigh: highPrice,
          anchorLow: lowPrice,
          anchorHighTimestamp: anchorHigh.timestamp,
          anchorLowTimestamp: anchorLow.timestamp,
          strength: this.getLevelStrength(level, 'retracement')
        });
      }
      
      // Extension levels (above the high)
      for (const level of FibonacciAnalyzer.EXTENSION_LEVELS) {
        const price = highPrice + (range * (level - 1));
        levels.push({
          level,
          price,
          type: 'extension',
          anchorHigh: highPrice,
          anchorLow: lowPrice,
          anchorHighTimestamp: anchorHigh.timestamp,
          anchorLowTimestamp: anchorLow.timestamp,
          strength: this.getLevelStrength(level, 'extension')
        });
      }
    } else {
      // Retracement from high to low: levels above the low
      for (const level of FibonacciAnalyzer.RETRACEMENT_LEVELS) {
        const price = lowPrice + (range * level);
        levels.push({
          level,
          price,
          type: 'retracement',
          anchorHigh: highPrice,
          anchorLow: lowPrice,
          anchorHighTimestamp: anchorHigh.timestamp,
          anchorLowTimestamp: anchorLow.timestamp,
          strength: this.getLevelStrength(level, 'retracement')
        });
      }
      
      // Extension levels (below the low)
      for (const level of FibonacciAnalyzer.EXTENSION_LEVELS) {
        const price = lowPrice - (range * (level - 1));
        levels.push({
          level,
          price,
          type: 'extension',
          anchorHigh: highPrice,
          anchorLow: lowPrice,
          anchorHighTimestamp: anchorHigh.timestamp,
          anchorLowTimestamp: anchorLow.timestamp,
          strength: this.getLevelStrength(level, 'extension')
        });
      }
    }
    
    return levels;
  }

  private getLevelStrength(level: number, type: 'retracement' | 'extension'): number {
    // Key levels get higher base strength
    if (type === 'retracement') {
      if (level === 0.5) return 10;
      if (level === 0.618) return 10;
      if (level === 0.382 || level === 0.786) return 8;
      if (level === 0.236 || level === 0.705 || level === 0.886) return 6;
    } else {
      if (level === 1.618) return 10;
      if (level === 1.272 || level === 1.0) return 8;
      if (level === 1.414 || level === 2.0) return 6;
      if (level === 2.618) return 5;
    }
    return 5;
  }

  private detectConfluences(high: number, low: number, timestamp: number): void {
    this.confluences = [];
    
    // Collect all Fibonacci levels from active drawings
    const allLevels: FibonacciLevel[] = [];
    for (const drawing of this.drawings) {
      if (drawing.isActive) {
        allLevels.push(...drawing.levels);
      }
    }
    
    // Group levels by price (within tolerance)
    const groupedLevels = new Map<number, FibonacciLevel[]>();
    
    for (const level of allLevels) {
      let found = false;
      for (const [priceKey, levels] of groupedLevels.entries()) {
        if (Math.abs(level.price - priceKey) / priceKey < this.priceTolerance) {
          levels.push(level);
          found = true;
          break;
        }
      }
      if (!found) {
        groupedLevels.set(level.price, [level]);
      }
    }
    
    // Create confluence objects for groups with multiple levels
    for (const [price, levels] of groupedLevels.entries()) {
      if (levels.length >= 2) {
        const totalStrength = levels.reduce((sum, l) => sum + l.strength, 0);
        
        this.confluences.push({
          price,
          levels,
          totalStrength,
          // These would be populated by cross-referencing with other analyzers
          nearbyLiquidity: undefined,
          nearbyOrderBlock: false,
          nearbyFVG: false,
          nearbySupportResistance: false,
          nearbyVWAP: false,
          nearbyMarketProfile: false,
          nearbySessionLevel: false,
          nearbyPreviousHighLow: false
        });
      }
    }
    
    // Sort by strength
    this.confluences.sort((a, b) => b.totalStrength - a.totalStrength);
  }

  private detectMeasuredMoves(high: number, low: number, timestamp: number): void {
    // Measured moves: project the size of a previous move
    // This would use swing points to find AB moves and project CD
  }

  private detectABCDPatterns(timestamp: number): void {
    // AB=CD pattern detection
    // Requires 4 swing points: A, B, C, D where AB ≈ CD
    const swings = this.swingDetector.getSwings();
    if (swings.length < 4) return;
    
    // Look for AB=CD in recent swings
    const recentSwings = swings.slice(-8);
    
    for (let i = 0; i < recentSwings.length - 3; i++) {
      const a = recentSwings[i];
      const b = recentSwings[i + 1];
      const c = recentSwings[i + 2];
      // D would be projected
      
      if (a.type === b.type || b.type === c.type) continue; // Need alternating
      
      const abSize = Math.abs(b.price - a.price);
      const bcSize = Math.abs(c.price - b.price);
      
      // Check if BC is a retracement of AB (typically 0.382-0.786)
      const retraceRatio = bcSize / abSize;
      if (retraceRatio < 0.382 || retraceRatio > 0.786) continue;
      
      // Project D
      let projectedD: number;
      if (a.type === 'low' && b.type === 'high' && c.type === 'low') {
        // Bullish AB=CD
        projectedD = c.price + abSize;
      } else if (a.type === 'high' && b.type === 'low' && c.type === 'high') {
        // Bearish AB=CD
        projectedD = c.price - abSize;
      } else {
        continue;
      }
      
      const pattern: AB_CD_Pattern = {
        pointA: a,
        pointB: b,
        pointC: c,
        pointD: projectedD,
        type: a.type === 'low' ? 'bullish' : 'bearish',
        completionRatio: 1.0, // CD/AB = 1 for perfect AB=CD
        timestamp
      };
      
      this.abcdPatterns.push(pattern);
    }
  }

  private cleanupOldDrawings(): void {
    // Remove old inactive drawings
    const cutoff = Date.now() - this.lookbackPeriod * 60 * 60 * 1000;
    this.drawings = this.drawings.filter(d => 
      d.isActive || d.creationTimestamp > cutoff
    );
  }

  // Getters
  getDrawings(): FibonacciDrawing[] { return [...this.drawings]; }
  getConfluences(): FibonacciConfluence[] { return [...this.confluences]; }
  getMeasuredMoves(): MeasuredMove[] { return [...this.measuredMoves]; }
  getABCDPatterns(): AB_CD_Pattern[] { return [...this.abcdPatterns]; }

  // Get Fibonacci levels near a price
  getLevelsNearPrice(price: number, tolerance: number = 0.005): FibonacciLevel[] {
    const allLevels: FibonacciLevel[] = [];
    for (const drawing of this.drawings) {
      if (drawing.isActive) {
        allLevels.push(...drawing.levels);
      }
    }
    return allLevels.filter(l => Math.abs(l.price - price) / price < tolerance);
  }

  // Get confluence at or near a price
  getConfluenceAtPrice(price: number, tolerance: number = 0.005): FibonacciConfluence | null {
    for (const confluence of this.confluences) {
      if (Math.abs(confluence.price - price) / price < tolerance) {
        return confluence;
      }
    }
    return null;
  }

  reset(): void {
    this.swingDetector.reset();
    this.drawings = [];
    this.confluences = [];
    this.measuredMoves = [];
    this.abcdPatterns = [];
  }
}