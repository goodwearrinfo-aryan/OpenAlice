// Main index for confluence analysis - proper exports
export {
  SwingDetector,
  SwingPoint,
  SwingDetectorOptions
} from './swing';

export {
  TrendAnalyzer,
  TrendState
} from './trend';

export {
  StructureBreaker,
  StructureBreak
} from './structure-breaker';

export {
  MarketStructure,
  Level,
  Trendline,
  Channel
} from './market-structure';

export {
  LiquidityAnalyzer,
  LiquidityPool,
  LiquiditySweep,
  LiquidityVoid,
  Inducement
} from './liquidity';

export {
  InstitutionalAnalyzer,
  InstitutionalZone,
  OrderBlock,
  BreakerBlock,
  MitigationBlock,
  RejectionBlock,
  PropulsionBlock,
  FairValueGap,
  InverseFairValueGap,
  BalancedPriceRange,
  VolumeImbalance,
  ConsequentEncroachment,
  DisplacementCandle
} from './institutional';

export {
  FibonacciAnalyzer,
  FibonacciLevel,
  FibonacciDrawing,
  FibonacciConfluence,
  MeasuredMove,
  AB_CD_Pattern
} from './fibonacci';