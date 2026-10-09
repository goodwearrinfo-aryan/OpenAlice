// Test for structure breaker functionality
import { StructureBreaker } from './structure-breaker';

console.log('Testing StructureBreaker...');

// Create a breaker with default settings
const breaker = new StructureBreaker();

// Simulate price data that creates an uptrend with clear BOS and CHOCH
// We'll create: higher highs and higher lows (uptrend), then a BOS, then a CHOCH
const priceData = [
  // Initial accumulation
  { high: 100, low: 95, timestamp: Date.now() - 1200000 }, // 20 min ago
  { high: 105, low: 100, timestamp: Date.now() - 1140000 }, // 19 min ago
  { high: 103, low: 102, timestamp: Date.now() - 1080000 }, // 18 min ago
  
  // Uptrend begins - higher low
  { high: 110, low: 104, timestamp: Date.now() - 1020000 }, // 17 min ago
  { high: 115, low: 108, timestamp: Date.now() - 960000 },  // 16 min ago
  { high: 112, low: 110, timestamp: Date.now() - 900000 },  // 15 min ago
  
  // Continuing uptrend - higher high and higher low
  { high: 120, low: 115, timestamp: Date.now() - 840000 },  // 14 min ago
  { high: 125, low: 120, timestamp: Date.now() - 780000 },  // 13 min ago
  { high: 122, low: 123, timestamp: Date.now() - 720000 },  // 12 min ago
  
  // BOS - price breaks above previous high with strong momentum
  { high: 135, low: 128, timestamp: Date.now() - 660000 },  // 11 min ago - BOS!
  { high: 132, low: 130, timestamp: Date.now() - 600000 },  // 10 min ago
  
  // CHOCH - price breaks below previous low, indicating trend change
  { high: 128, low: 125, timestamp: Date.now() - 540000 },  // 9 min ago
  { high: 124, low: 122, timestamp: Date.now() - 480000 },  // 8 min ago
  { high: 120, low: 118, timestamp: Date.now() - 420000 },  // 7 min ago
  { high: 115, low: 115, timestamp: Date.now() - 360000 },  // 6 min ago - CHOCH! (broke below low of 118)
  { high: 110, low: 110, timestamp: Date.now() - 300000 },  // 5 min ago
  { high: 105, low: 105, timestamp: Date.now() - 240000 },  // 4 min ago
  { high: 100, low: 100, timestamp: Date.now() - 180000 },  // 3 min ago
  { high: 95, low: 95, timestamp: Date.now() - 120000 },   // 2 min ago
  { high: 90, low: 90, timestamp: Date.now() - 60000 },    // 1 min ago
  { high: 85, low: 85, timestamp: Date.now() },            // now
];

priceData.forEach((bar, i) => {
  const result = breaker.addBar(bar.high, bar.low, bar.timestamp);
  if (result) {
    console.log(`Bar ${i}: ${result.type} ${result.direction} at price ${result.breakPrice}`);
  }
});

const breaks = breaker.getBreaks();
console.log(`\nTotal breaks detected: ${breaks.length}`);
breaks.forEach((brk, i) => {
  console.log(`  ${i+1}. ${brk.type} ${brk.direction} at index ${brk.breakIndex}, price ${brk.breakPrice}`);
});

// Test reset
breaker.reset();
const breaksAfterReset = breaker.getBreaks();
console.log(`\nAfter reset, breaks length: ${breaksAfterReset.length}`);

console.log('\nStructureBreaker test completed.');