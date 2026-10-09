// Test for swing detection functionality
import { SwingDetector } from './swing';

console.log('Testing SwingDetector...');

// Create a detector with default settings
const detector = new SwingDetector();

// Simulate some price data with clear swing points
// Index: 0  1  2  3  4  5  6  7  8  9 10 11 12 13 14
// Price: 10,12,11,13,12,15,14,16,15,18,17,19,18,20,19
// We expect swing highs at indices 1,3,5,7,9,11,13 (peaks)
// We expect swing lows at indices 0,2,4,6,8,10,12,14 (troughs)

const prices = [10,12,11,13,12,15,14,16,15,18,17,19,18,20,19];
const timestamps = prices.map((_, i) => Date.now() - (14 - i) * 60000); // 1 minute intervals

prices.forEach((price, i) => {
  // For simplicity, using same value for high and low in this test
  detector.addBar(price, price, timestamps[i]);
});

const swings = detector.getSwings();
console.log(`Detected ${swings.length} swing points:`);
swings.forEach((swing, i) => {
  console.log(`  ${i+1}. ${swing.type} at index ${swing.index}, price ${swing.price}, timestamp ${new Date(swing.timestamp).toISOString()}`);
});

// Test getting last swing
const lastHigh = detector.getLastSwing('high');
const lastLow = detector.getLastSwing('low');
console.log(`\nLast swing high:`, lastHigh);
console.log(`Last swing low:`, lastLow);

// Test getting last two swings
const [lastHigh2, lastLow2] = detector.getLastTwoSwings();
console.log(`\nLast two swings:`);
console.log(`  Last high:`, lastHigh2);
console.log(`  Last low:`, lastLow2);

// Reset and test again
detector.reset();
const swingsAfterReset = detector.getSwings();
console.log(`\nAfter reset, swings length: ${swingsAfterReset.length}`);

console.log('\nSwingDetector test completed.');