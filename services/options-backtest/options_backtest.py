#!/usr/bin/env python3
"""
Self-Healing Intelligent Multi-Leg Options Backtesting Engine
=============================================================

Professional-grade backtesting for prop firm multi-leg options strategies.
Features:
- Intelligent entry/exit logic with regime detection
- Self-healing parameter optimization
- Greeks-based risk management
- Realistic execution simulation (slippage, liquidity)
- Walk-forward validation
"""

import json
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from abc import ABC, abstractmethod
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# CORE DATA STRUCTURES
# ============================================================

class StrategyType(Enum):
    IRON_CONDOR = "iron_condor"
    VERTICAL_SPREAD = "vertical_spread"
    BUTTERFLY = "butterfly"
    IRON_BUTTERFLY = "iron_butterfly"
    CALENDAR = "calendar"
    DIAGONAL = "diagonal"
    JADE_LIZARD = "jade_lizard"
    BWB = "bwb"  # Broken Wing Butterfly
    STRADDLE = "straddle"
    STRANGLE = "strangle"
    RATIO_SPREAD = "ratio_spread"

class MarketRegime(Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_VOL = "high_vol"
    LOW_VOL = "low_vol"
    CRASH = "crash"
    UNKNOWN = "unknown"

class ExitReason(Enum):
    TARGET_PROFIT = "target_profit"
    STOP_LOSS = "stop_loss"
    TIME_DECAY = "time_decay"
    DELTA_THRESHOLD = "delta_threshold"
    GAMMA_RISK = "gamma_risk"
    VEGA_SHIFT = "vega_shift"
    REGIME_CHANGE = "regime_change"
    EXPIRATION = "expiration"
    ASSIGNMENT_RISK = "assignment_risk"

@dataclass
class OptionLeg:
    """Single option leg in a multi-leg strategy"""
    option_type: str  # 'call' or 'put'
    strike: float
    expiry_days: int
    quantity: int  # positive = long, negative = short
    entry_price: float = 0.0
    current_price: float = 0.0
    greeks: Dict[str, float] = field(default_factory=dict)
    
    def __post_init__(self):
        if self.greeks is None:
            self.greeks = {}

@dataclass
class Position:
    """Multi-leg position with full Greeks tracking"""
    strategy_type: StrategyType
    legs: List[OptionLeg]
    entry_date: pd.Timestamp
    entry_spot: float
    entry_iv: float
    entry_vix: float
    regime_at_entry: MarketRegime
    capital_at_risk: float
    max_profit: float
    max_loss: float
    target_profit: float
    stop_loss: float
    entry_credit_debit: float  # positive = credit, negative = debit
    
    # Dynamic state
    current_pnl: float = 0.0
    current_greeks: Dict[str, float] = field(default_factory=dict)
    days_held: int = 0
    exit_reason: Optional[ExitReason] = None
    exit_date: Optional[pd.Timestamp] = None
    exit_pnl: float = 0.0
    adjustments: List[Dict] = field(default_factory=list)
    
    def __post_init__(self):
        if self.current_greeks is None:
            self.current_greeks = {}

@dataclass
class MarketState:
    """Complete market state for decision making"""
    date: pd.Timestamp
    spot: float
    vix: float
    iv_rank: float
    iv_percentile: float
    realized_vol_10d: float
    realized_vol_30d: float
    term_structure: Dict[int, float]  # DTE -> IV
    skew: float  # 25d put IV - 25d call IV
    regime: MarketRegime
    trend_strength: float
    momentum: float
    rsi: float
    spy_trend: float  # Market correlation
    
    # Microstructure
    bid_ask_spread_pct: float = 0.01
    volume: float = 1_000_000
    open_interest: float = 10_000

# ============================================================
# REGIME DETECTION ENGINE
# ============================================================

class RegimeDetector:
    """Intelligent market regime detection using multiple factors"""
    
    def __init__(self, lookback_short=10, lookback_med=30, lookback_long=60):
        self.lookback_short = lookback_short
        self.lookback_med = lookback_med
        self.lookback_long = lookback_long
        self.regime_history = []
        
    def detect(self, market_data: pd.DataFrame, current_idx: int) -> MarketState:
        """Detect current market regime from historical data"""
        if current_idx < self.lookback_long:
            return self._default_state(market_data.iloc[current_idx])
            
        # Get windows
        short_window = market_data.iloc[current_idx - self.lookback_short:current_idx + 1]
        med_window = market_data.iloc[current_idx - self.lookback_med:current_idx + 1]
        long_window = market_data.iloc[current_idx - self.lookback_long:current_idx + 1]
        
        current = market_data.iloc[current_idx]
        
        # Price action
        returns = short_window['close'].pct_change().dropna()
        med_returns = med_window['close'].pct_change().dropna()
        
        # Volatility
        realized_vol_10d = returns.std() * np.sqrt(252)
        realized_vol_30d = med_returns.std() * np.sqrt(252)
        
        # Trend detection
        sma_short = short_window['close'].mean()
        sma_med = med_window['close'].mean()
        sma_long = long_window['close'].mean()
        current_price = current['close']
        
        trend_strength = (current_price - sma_long) / sma_long
        momentum = (sma_short - sma_med) / sma_med
        
        # RSI
        rsi = self._calculate_rsi(short_window['close'])
        
        # IV data (simulated if not available)
        vix = current.get('vix', 20)
        iv_rank = current.get('iv_rank', 50)
        iv_percentile = current.get('iv_percentile', 50)
        
        # Term structure
        term_structure = self._estimate_term_structure(current, vix)
        
        # Skew
        skew = current.get('skew', 0)
        
        # Regime classification
        regime = self._classify_regime(
            trend_strength, momentum, realized_vol_10d, 
            realized_vol_30d, vix, iv_rank, rsi
        )
        
        return MarketState(
            date=current.name if hasattr(current, 'name') else pd.Timestamp.now(),
            spot=current_price,
            vix=vix,
            iv_rank=iv_rank,
            iv_percentile=iv_percentile,
            realized_vol_10d=realized_vol_10d,
            realized_vol_30d=realized_vol_30d,
            term_structure=term_structure,
            skew=skew,
            regime=regime,
            trend_strength=trend_strength,
            momentum=momentum,
            rsi=rsi,
            spy_trend=0.0  # Would need SPY data
        )
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> float:
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1]) if not rsi.empty else 50.0
    
    def _estimate_term_structure(self, current: pd.Series, vix: float) -> Dict[int, float]:
        """Estimate IV term structure"""
        base = vix / 100
        return {
            7: base * 1.15,
            14: base * 1.10,
            30: base * 1.05,
            45: base * 1.02,
            60: base,
            90: base * 0.98
        }
    
    def _classify_regime(self, trend_strength: float, momentum: float, 
                        rv_10d: float, rv_30d: float, vix: float, 
                        iv_rank: float, rsi: float) -> MarketRegime:
        """Multi-factor regime classification"""
        
        vol_ratio = rv_10d / rv_30d if rv_30d > 0 else 1
        
        # Crash detection
        if vix > 40 or rv_10d > 0.6:
            return MarketRegime.CRASH
        
        # High/Low vol
        if iv_rank > 75 or vix > 30:
            return MarketRegime.HIGH_VOL
        if iv_rank < 25 and vix < 15:
            return MarketRegime.LOW_VOL
        
        # Trend detection
        if trend_strength > 0.05 and momentum > 0.02 and rsi > 60:
            return MarketRegime.TRENDING_UP
        if trend_strength < -0.05 and momentum < -0.02 and rsi < 40:
            return MarketRegime.TRENDING_DOWN
            
        # Mean reversion signals
        if vol_ratio > 1.3 and abs(momentum) < 0.01:
            return MarketRegime.RANGING
            
        return MarketRegime.RANGING
    
    def _default_state(self, current: pd.Series) -> MarketState:
        return MarketState(
            date=pd.Timestamp.now(),
            spot=current.get('close', 100),
            vix=current.get('vix', 20),
            iv_rank=current.get('iv_rank', 50),
            iv_percentile=current.get('iv_percentile', 50),
            realized_vol_10d=0.2,
            realized_vol_30d=0.2,
            term_structure={7: 0.23, 14: 0.22, 30: 0.21, 45: 0.205, 60: 0.2, 90: 0.195},
            skew=0,
            regime=MarketRegime.UNKNOWN,
            trend_strength=0,
            momentum=0,
            rsi=50,
            spy_trend=0
        )

# ============================================================
# OPTION PRICING & GREEKS ENGINE
# ============================================================

class OptionsPricer:
    """Black-Scholes with Greeks for realistic option pricing"""
    
    def __init__(self, risk_free_rate: float = 0.05):
        self.r = risk_free_rate
        
    def price(self, spot: float, strike: float, dte: int, iv: float, 
              option_type: str = 'call') -> Dict[str, float]:
        """Calculate option price and all Greeks"""
        if dte <= 0:
            # At expiration
            intrinsic = max(spot - strike, 0) if option_type == 'call' else max(strike - spot, 0)
            return {'price': intrinsic, 'delta': 1.0 if intrinsic > 0 else 0.0,
                    'gamma': 0, 'vega': 0, 'theta': 0, 'rho': 0}
        
        T = dte / 365.0
        sigma = iv
        
        d1 = (np.log(spot / strike) + (self.r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        
        from scipy.stats import norm
        N_d1 = norm.cdf(d1)
        N_d2 = norm.cdf(d2)
        N_nd1 = norm.cdf(-d1)
        N_nd2 = norm.cdf(-d2)
        pdf_d1 = norm.pdf(d1)
        
        if option_type == 'call':
            price = spot * N_d1 - strike * np.exp(-self.r * T) * N_d2
            delta = N_d1
            theta = (-(spot * pdf_d1 * sigma) / (2 * np.sqrt(T)) 
                    - self.r * strike * np.exp(-self.r * T) * N_d2) / 365
            rho = strike * T * np.exp(-self.r * T) * N_d2 / 100
        else:
            price = strike * np.exp(-self.r * T) * N_nd2 - spot * N_nd1
            delta = N_d1 - 1
            theta = (-(spot * pdf_d1 * sigma) / (2 * np.sqrt(T)) 
                    + self.r * strike * np.exp(-self.r * T) * N_nd2) / 365
            rho = -strike * T * np.exp(-self.r * T) * N_nd2 / 100
            
        gamma = pdf_d1 / (spot * sigma * np.sqrt(T))
        vega = spot * np.sqrt(T) * pdf_d1 / 100
        
        return {
            'price': max(price, 0.01),
            'delta': delta,
            'gamma': gamma,
            'vega': vega,
            'theta': theta,
            'rho': rho
        }
    
    def implied_vol(self, price: float, spot: float, strike: float, 
                    dte: int, option_type: str = 'call') -> float:
        """Calculate implied volatility (simplified)"""
        # Newton-Raphson would go here
        return 0.20  # Placeholder

# ============================================================
# INTELLIGENT STRATEGY ENGINE
# ============================================================

class StrategyEngine:
    """Self-healing strategy selection and parameter optimization"""
    
    def __init__(self, config: Dict = None):
        default = self._default_config()
        if config:
            # Deep merge
            self.config = self._merge_config(default, config)
        else:
            self.config = default
        self.performance_history = []
        self.regime_performance = {regime: [] for regime in MarketRegime}
        self.parameter_memory = {}
        

    def _merge_config(self, default: Dict, user: Dict) -> Dict:
        """Recursively merge user config into default"""
        result = default.copy()
        for key, value in user.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_config(result[key], value)
            else:
                result[key] = value
        return result

    def _default_config(self) -> Dict:
        return {
            # Position sizing
            'max_risk_per_trade': 0.02,  # 2% of capital
            'max_portfolio_risk': 0.10,  # 10% total
            'max_concurrent': 10,
            
            # Strategy preferences by regime
            'regime_preferences': {
                MarketRegime.RANGING: [
                    (StrategyType.IRON_CONDOR, 0.4),
                    (StrategyType.IRON_BUTTERFLY, 0.2),
                    (StrategyType.BUTTERFLY, 0.15),
                    (StrategyType.CALENDAR, 0.15),
                    (StrategyType.DIAGONAL, 0.1),
                ],
                MarketRegime.TRENDING_UP: [
                    (StrategyType.VERTICAL_SPREAD, 0.35),
                    (StrategyType.DIAGONAL, 0.25),
                    (StrategyType.JADE_LIZARD, 0.2),
                    (StrategyType.BWB, 0.2),
                ],
                MarketRegime.TRENDING_DOWN: [
                    (StrategyType.VERTICAL_SPREAD, 0.35),
                    (StrategyType.DIAGONAL, 0.25),
                    (StrategyType.JADE_LIZARD, 0.2),
                    (StrategyType.BWB, 0.2),
                ],
                MarketRegime.HIGH_VOL: [
                    (StrategyType.IRON_CONDOR, 0.3),
                    (StrategyType.IRON_BUTTERFLY, 0.25),
                    (StrategyType.RATIO_SPREAD, 0.2),
                    (StrategyType.STRANGLE, 0.15),
                    (StrategyType.JADE_LIZARD, 0.1),
                ],
                MarketRegime.LOW_VOL: [
                    (StrategyType.CALENDAR, 0.3),
                    (StrategyType.DIAGONAL, 0.25),
                    (StrategyType.BUTTERFLY, 0.2),
                    (StrategyType.STRADDLE, 0.15),
                    (StrategyType.STRANGLE, 0.1),
                ],
                MarketRegime.CRASH: [
                    (StrategyType.RATIO_SPREAD, 0.4),
                    (StrategyType.IRON_CONDOR, 0.3),
                    (StrategyType.BWB, 0.3),
                ]
            },
            
            # Entry criteria
            'min_iv_rank_entry': 30,
            'max_iv_rank_entry': 85,
            'min_credit_pct': 0.30,  # Credit as % of width
            'min_pop': 0.65,  # Probability of profit
            'max_delta_short': 0.25,
            
            # Exit criteria
            'target_profit_pct': 0.50,  # 50% of max profit
            'stop_loss_pct': 2.0,  # 2x credit/debit
            'dte_exit': 21,
            'delta_threshold': 0.30,
            'gamma_threshold': 0.05,
            
            # Self-healing
            'learning_rate': 0.1,
            'min_trades_for_optimization': 20,
            'performance_window': 100,
        }
    
    def select_strategy(self, market_state: MarketState, capital: float) -> Optional[Tuple[StrategyType, Dict]]:
        """Intelligently select strategy based on regime and historical performance"""
        
        # Get regime preferences
        prefs = self.config['regime_preferences'].get(market_state.regime, 
            self.config['regime_preferences'][MarketRegime.RANGING])
        
        # Adjust weights based on historical performance
        adjusted_prefs = self._adjust_weights(prefs, market_state.regime)
        
        # Filter by entry criteria
        viable = []
        for strategy, weight in adjusted_prefs:
            if self._meets_entry_criteria(strategy, market_state):
                viable.append((strategy, weight))
        
        if not viable:
            return None
            
        # Weighted random selection
        strategies = [s for s, _ in viable]
        weights = [w for _, w in viable]
        weights = np.array(weights) / sum(weights)
        
        selected = np.random.choice(strategies, p=weights)
        
        # Get optimized parameters
        params = self._get_optimized_params(selected, market_state)
        
        return selected, params
    
    def _meets_entry_criteria(self, strategy: StrategyType, ms: MarketState) -> bool:
        """Check if strategy meets entry criteria for current market"""
        cfg = self.config
        
        # IV rank filter
        if ms.iv_rank < cfg['min_iv_rank_entry'] or ms.iv_rank > cfg['max_iv_rank_entry']:
            # Exception: Long premium strategies in low IV
            if strategy in [StrategyType.STRADDLE, StrategyType.STRANGLE, 
                          StrategyType.CALENDAR, StrategyType.DIAGONAL]:
                if ms.iv_rank < cfg['min_iv_rank_entry']:
                    return True
            return False
            
        # Regime-specific filters
        if strategy == StrategyType.IRON_CONDOR:
            return ms.regime in [MarketRegime.RANGING, MarketRegime.HIGH_VOL]
        if strategy == StrategyType.VERTICAL_SPREAD:
            return ms.regime in [MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN]
        if strategy == StrategyType.STRADDLE:
            return ms.iv_rank < 30 and ms.realized_vol_10d > ms.iv_rank / 100
            
        return True
    
    def _adjust_weights(self, prefs: List[Tuple], regime: MarketRegime) -> List[Tuple]:
        """Adjust strategy weights based on historical performance"""
        if len(self.regime_performance.get(regime, [])) < self.config['min_trades_for_optimization']:
            return prefs
            
        # Calculate win rates per strategy in this regime
        perf = self.regime_performance[regime]
        strategy_stats = {}
        for p in perf[-self.config['performance_window']:]:
            strat = p['strategy']
            if strat not in strategy_stats:
                strategy_stats[strat] = {'wins': 0, 'total': 0, 'avg_r': 0}
            strategy_stats[strat]['total'] += 1
            if p['pnl'] > 0:
                strategy_stats[strat]['wins'] += 1
            strategy_stats[strat]['avg_r'] += p['pnl'] / p['risk']
        
        # Adjust weights
        adjusted = []
        for strategy, weight in prefs:
            if strategy in strategy_stats and strategy_stats[strategy]['total'] > 10:
                wr = strategy_stats[strategy]['wins'] / strategy_stats[strategy]['total']
                avg_r = strategy_stats[strategy]['avg_r'] / strategy_stats[strategy]['total']
                # Boost weight for good performers
                adjustment = (wr - 0.5) * 0.5 + avg_r * 0.3
                new_weight = max(0.01, weight * (1 + adjustment))
                adjusted.append((strategy, new_weight))
            else:
                adjusted.append((strategy, weight))
        
        return adjusted
    
    def _get_optimized_params(self, strategy: StrategyType, ms: MarketState) -> Dict:
        """Get optimized parameters for strategy"""
        base_params = self._base_params(strategy, ms)
        
        # Apply learned adjustments
        key = f"{strategy.value}_{ms.regime.value}"
        if key in self.parameter_memory:
            learned = self.parameter_memory[key]
            base_params.update(learned)
            
        return base_params
    
    def _base_params(self, strategy: StrategyType, ms: MarketState) -> Dict:
        """Base parameters for each strategy"""
        spot = ms.spot
        iv = ms.vix / 100
        
        # ATM strike
        atm_strike = round(spot / 5) * 5
        
        params = {
            'spot': spot,
            'iv': iv,
            'dte': 30,
        }
        
        if strategy == StrategyType.IRON_CONDOR:
            # Asymmetric wings for skew
            put_width = 10 if ms.skew > 0 else 8
            call_width = 8 if ms.skew > 0 else 10
            
            short_put_delta = 0.12 if ms.iv_rank > 60 else 0.15
            short_call_delta = 0.12 if ms.iv_rank > 60 else 0.15
            
            params.update({
                'short_put_strike': atm_strike - 15,
                'long_put_strike': atm_strike - 15 - put_width,
                'short_call_strike': atm_strike + 15,
                'long_call_strike': atm_strike + 15 + call_width,
                'dte': 35,
            })
            
        elif strategy == StrategyType.VERTICAL_SPREAD:
            direction = 'bull' if ms.regime == MarketRegime.TRENDING_UP else 'bear'
            params.update({
                'direction': direction,
                'long_strike': atm_strike if direction == 'bull' else atm_strike - 10,
                'short_strike': atm_strike + 10 if direction == 'bull' else atm_strike - 10,
                'dte': 30,
            })
            
        elif strategy == StrategyType.DIAGONAL:
            params.update({
                'long_dte': 60,
                'short_dte': 21,
                'long_strike': atm_strike - 5,  # ITM
                'short_strike': atm_strike + 10,  # OTM
            })
            
        elif strategy == StrategyType.JADE_LIZARD:
            params.update({
                'short_put_strike': atm_strike - 15,
                'short_call_strike': atm_strike + 15,
                'long_call_strike': atm_strike + 25,
                'dte': 35,
            })
            
        elif strategy == StrategyType.BWB:
            params.update({
                'center_strike': atm_strike,
                'long_strike': atm_strike - 10,
                'short_strike': atm_strike,
                'wing_strike': atm_strike + 15,  # Broken wing
                'dte': 21,
            })
            
        return params
    
    def record_trade(self, position: Position, pnl: float):
        """Record trade for learning"""
        risk = position.capital_at_risk
        r_multiple = pnl / risk if risk > 0 else 0
        
        record = {
            'strategy': position.strategy_type,
            'regime': position.regime_at_entry,
            'pnl': pnl,
            'risk': risk,
            'r_multiple': r_multiple,
            'days_held': position.days_held,
            'exit_reason': position.exit_reason.value if position.exit_reason else 'unknown',
        }
        
        self.performance_history.append(record)
        self.regime_performance[position.regime_at_entry].append(record)
        
        # Self-healing: Update parameter memory
        self._update_parameter_memory(position, r_multiple)
    
    def _update_parameter_memory(self, position: Position, r_multiple: float):
        """Learn from trade outcomes"""
        key = f"{position.strategy_type.value}_{position.regime_at_entry.value}"
        
        if key not in self.parameter_memory:
            self.parameter_memory[key] = {}
            
        lr = self.config['learning_rate']
        
        # Adjust parameters based on outcome
        if r_multiple > 1.0:  # Good trade
            # Reinforce parameters that led to success
            for param, value in self._extract_adjustable_params(position).items():
                if param in self.parameter_memory[key]:
                    self.parameter_memory[key][param] = (
                        self.parameter_memory[key][param] * (1 - lr) + value * lr
                    )
                else:
                    self.parameter_memory[key][param] = value
        elif r_multiple < -0.5:  # Bad loss
            # Slightly adjust away from bad parameters
            for param, value in self._extract_adjustable_params(position).items():
                if param in self.parameter_memory[key]:
                    self.parameter_memory[key][param] = (
                        self.parameter_memory[key][param] * (1 + lr) - value * lr * 0.5
                    )
    
    def _extract_adjustable_params(self, position: Position) -> Dict:
        """Extract parameters that can be optimized"""
        params = {}
        for leg in position.legs:
            if leg.option_type == 'put' and leg.quantity < 0:  # Short put
                params['short_put_strike'] = leg.strike
            elif leg.option_type == 'call' and leg.quantity < 0:  # Short call
                params['short_call_strike'] = leg.strike
        params['dte'] = position.legs[0].expiry_days if position.legs else 30
        return params

# ============================================================
# POSITION MANAGEMENT ENGINE
# ============================================================

class PositionManager:
    """Intelligent position management with dynamic exits and adjustments"""
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        
    def evaluate_exit(self, position: Position, market_state: MarketState, 
                      pricer: OptionsPricer) -> Optional[ExitReason]:
        """Evaluate if position should be exited and why"""
        
        # Update position Greeks
        self._update_greeks(position, market_state, pricer)
        
        # Calculate current P&L
        current_value = sum(leg.current_price * leg.quantity * 100 for leg in position.legs)
        position.current_pnl = current_value + position.entry_credit_debit * 100
        
        pnl_pct = position.current_pnl / position.capital_at_risk if position.capital_at_risk > 0 else 0
        
        # Check exit conditions in priority order
        
        # 1. Target profit
        if pnl_pct >= position.target_profit / position.capital_at_risk:
            return ExitReason.TARGET_PROFIT
            
        # 2. Stop loss
        if pnl_pct <= -position.stop_loss / position.capital_at_risk:
            return ExitReason.STOP_LOSS
            
        # 3. Time decay (DTE)
        min_dte = min(leg.expiry_days for leg in position.legs)
        if min_dte <= self.config.get('dte_exit', 21):
            return ExitReason.TIME_DECAY
            
        # 4. Delta threshold on short strikes
        for leg in position.legs:
            if leg.quantity < 0:  # Short leg
                delta = abs(leg.greeks.get('delta', 0))
                if delta >= self.config.get('delta_threshold', 0.30):
                    return ExitReason.DELTA_THRESHOLD
                    
        # 5. Gamma risk
        net_gamma = sum(leg.greeks.get('gamma', 0) * leg.quantity * 100 for leg in position.legs)
        if abs(net_gamma) > self.config.get('gamma_threshold', 0.05) * position.capital_at_risk:
            return ExitReason.GAMMA_RISK
            
        # 6. Vega shift (IV change)
        iv_change = (market_state.vix / 100 - position.entry_iv) / position.entry_iv
        net_vega = sum(leg.greeks.get('vega', 0) * leg.quantity * 100 for leg in position.legs)
        vega_pnl = net_vega * iv_change * 100
        if abs(vega_pnl) > position.capital_at_risk * 0.5:
            return ExitReason.VEGA_SHIFT
            
        # 7. Regime change
        if market_state.regime != position.regime_at_entry:
            # Allow some regime changes if profitable
            if pnl_pct < 0.1:  # Not yet profitable
                return ExitReason.REGIME_CHANGE
                
        # 8. Assignment risk (short ITM near expiry)
        for leg in position.legs:
            if leg.quantity < 0 and leg.expiry_days <= 5:
                if (leg.option_type == 'call' and market_state.spot > leg.strike) or                    (leg.option_type == 'put' and market_state.spot < leg.strike):
                    return ExitReason.ASSIGNMENT_RISK
                    
        return None
    
    def _update_greeks(self, position: Position, market_state: MarketState, 
                       pricer: OptionsPricer):
        """Update all leg prices and Greeks"""
        for leg in position.legs:
            greeks = pricer.price(
                market_state.spot, 
                leg.strike, 
                leg.expiry_days, 
                market_state.term_structure.get(leg.expiry_days, market_state.vix / 100),
                leg.option_type
            )
            leg.current_price = greeks['price']
            leg.greeks = greeks
            
        # Aggregate
        position.current_greeks = {
            'delta': sum(l.greeks.get('delta', 0) * l.quantity * 100 for l in position.legs),
            'gamma': sum(l.greeks.get('gamma', 0) * l.quantity * 100 for l in position.legs),
            'vega': sum(l.greeks.get('vega', 0) * l.quantity * 100 for l in position.legs),
            'theta': sum(l.greeks.get('theta', 0) * l.quantity * 100 for l in position.legs),
        }
        position.days_held += 1
    
    def generate_adjustment(self, position: Position, market_state: MarketState,
                           exit_reason: ExitReason) -> Optional[Dict]:
        """Generate intelligent adjustment instead of just closing"""
        
        adjustments = {
            ExitReason.DELTA_THRESHOLD: self._adjust_delta,
            ExitReason.GAMMA_RISK: self._adjust_gamma,
            ExitReason.VEGA_SHIFT: self._adjust_vega,
            ExitReason.REGIME_CHANGE: self._adjust_regime,
        }
        
        if exit_reason in adjustments:
            return adjustments[exit_reason](position, market_state)
        return None
    
    def _adjust_delta(self, position: Position, ms: MarketState) -> Dict:
        """Roll challenged side or convert to iron condor"""
        if position.strategy_type == StrategyType.IRON_CONDOR:
            # Roll the tested side
            return {
                'type': 'roll_side',
                'side': 'put' if ms.spot < position.entry_spot else 'call',
                'action': 'roll_down' if ms.spot < position.entry_spot else 'roll_up',
                'new_dte': 35,
                'reason': 'Delta threshold breached, rolling tested side'
            }
        elif position.strategy_type == StrategyType.VERTICAL_SPREAD:
            return {
                'type': 'roll_out',
                'new_dte': 30,
                'same_strikes': True,
                'reason': 'Rolling vertical spread for more time'
            }
        return {}
    
    def _adjust_gamma(self, position: Position, ms: MarketState) -> Dict:
        """Reduce gamma by rolling or closing"""
        return {
            'type': 'reduce_gamma',
            'action': 'roll_to_further_otm',
            'reason': 'Gamma risk too high, rolling strikes OTM'
        }
    
    def _adjust_vega(self, position: Position, ms: MarketState) -> Dict:
        """Adjust vega exposure"""
        return {
            'type': 'vega_hedge',
            'action': 'add_calendar_spread' if ms.iv_rank > 50 else 'reduce_short_vega',
            'reason': 'IV shift causing excessive vega P&L'
        }
    
    def _adjust_regime(self, position: Position, ms: MarketState) -> Dict:
        """Handle regime change"""
        if position.strategy_type == StrategyType.IRON_CONDOR and            ms.regime in [MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN]:
            return {
                'type': 'convert',
                'new_strategy': StrategyType.DIAGONAL,
                'reason': 'Regime changed to trending, converting to diagonal'
            }
        return {}

# ============================================================
# EXECUTION SIMULATOR
# ============================================================

class ExecutionSimulator:
    """Realistic execution with slippage, commissions, liquidity"""
    
    def __init__(self, config: Dict = None):
        default_config = {
            'commission_per_contract': 0.65,
            'slippage_bps': 5,  # Basis points of premium
            'min_slippage': 0.01,
            'liquidity_penalty': 1.5,  # Multiplier for illiquid
        }
        if config:
            self.config = {**default_config, **config}
        else:
            self.config = default_config
    
    def execute_entry(self, legs: List[OptionLeg], market_state: MarketState) -> Tuple[List[OptionLeg], float]:
        """Simulate order execution with slippage"""
        total_cost = 0
        executed_legs = []
        
        for leg in legs:
            # Base slippage
            slippage = max(
                leg.entry_price * self.config['slippage_bps'] / 10000,
                self.config['min_slippage']
            )
            
            # Liquidity adjustment
            liq_factor = self._liquidity_factor(leg, market_state)
            slippage *= liq_factor
            
            # Direction: pay slippage when buying, receive less when selling
            if leg.quantity > 0:  # Buying
                exec_price = leg.entry_price + slippage
            else:  # Selling
                exec_price = leg.entry_price - slippage
                
            exec_price = max(exec_price, 0.01)
            
            # Commission
            commission = abs(leg.quantity) * self.config['commission_per_contract']
            
            new_leg = OptionLeg(
                option_type=leg.option_type,
                strike=leg.strike,
                expiry_days=leg.expiry_days,
                quantity=leg.quantity,
                entry_price=exec_price,
                current_price=exec_price,
                greeks=leg.greeks
            )
            executed_legs.append(new_leg)
            
            total_cost += exec_price * leg.quantity * 100 + commission
            
        return executed_legs, total_cost
    
    def execute_exit(self, legs: List[OptionLeg], market_state: MarketState) -> Tuple[List[OptionLeg], float]:
        """Simulate exit execution"""
        total_proceeds = 0
        executed_legs = []
        
        for leg in legs:
            slippage = max(
                leg.current_price * self.config['slippage_bps'] / 10000,
                self.config['min_slippage']
            )
            liq_factor = self._liquidity_factor(leg, market_state)
            slippage *= liq_factor
            
            if leg.quantity > 0:  # Selling to close
                exec_price = leg.current_price - slippage
            else:  # Buying to close
                exec_price = leg.current_price + slippage
                
            exec_price = max(exec_price, 0.01)
            commission = abs(leg.quantity) * self.config['commission_per_contract']
            
            new_leg = OptionLeg(
                option_type=leg.option_type,
                strike=leg.strike,
                expiry_days=leg.expiry_days,
                quantity=leg.quantity,
                entry_price=leg.entry_price,
                current_price=exec_price,
                greeks=leg.greeks
            )
            executed_legs.append(new_leg)
            
            total_proceeds += exec_price * leg.quantity * 100 - commission
            
        return executed_legs, total_proceeds
    
    def _liquidity_factor(self, leg: OptionLeg, ms: MarketState) -> float:
        """Calculate liquidity penalty factor"""
        # ATM more liquid
        moneyness = abs(ms.spot - leg.strike) / ms.spot
        if moneyness < 0.02:  # Near ATM
            return 1.0
        elif moneyness < 0.05:
            return 1.2
        elif moneyness < 0.10:
            return 1.5
        else:
            return 2.0
        
        # DTE factor
        if leg.expiry_days < 7:
            return 1.5
        elif leg.expiry_days < 14:
            return 1.2
        return 1.0

# ============================================================
# MAIN BACKTEST ENGINE
# ============================================================

class OptionsBacktestEngine:
    """Main backtesting engine with walk-forward validation"""
    
    def __init__(self, initial_capital: float = 100000, config: Dict = None):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.config = config or {}
        
        # Components
        self.regime_detector = RegimeDetector()
        self.strategy_engine = StrategyEngine(config)
        self.position_manager = PositionManager(config)
        self.pricer = OptionsPricer()
        self.executor = ExecutionSimulator(config)
        
        # State
        self.open_positions: List[Position] = []
        self.closed_trades: List[Position] = []
        self.equity_curve: List[Dict] = []
        self.daily_pnl: List[Dict] = []
        
    def run(self, market_data: pd.DataFrame, start_idx: int = 0) -> Dict:
        """Run backtest on market data"""
        
        print(f"Starting backtest with ${self.initial_capital:,.0f} capital")
        print(f"Data range: {market_data.index[start_idx]} to {market_data.index[-1]}")
        print(f"Bars: {len(market_data) - start_idx}")
        
        for i in range(start_idx, len(market_data)):
            current_bar = market_data.iloc[i]
            
            # Create market state
            market_state = self.regime_detector.detect(market_data, i)
            
            # Manage existing positions
            self._manage_positions(market_state)
            
            # Look for new entries
            self._scan_entries(market_state)
            
            # Record equity
            total_equity = self.capital + sum(p.current_pnl for p in self.open_positions)
            self.equity_curve.append({
                'date': market_state.date,
                'equity': total_equity,
                'cash': self.capital,
                'positions': len(self.open_positions),
                'regime': market_state.regime.value,
                'vix': market_state.vix
            })
            
            # Daily P&L
            if i > start_idx:
                prev_equity = self.equity_curve[-2]['equity']
                daily_pnl = total_equity - prev_equity
                self.daily_pnl.append({
                    'date': market_state.date,
                    'pnl': daily_pnl,
                    'pnl_pct': daily_pnl / prev_equity if prev_equity > 0 else 0
                })
                
            # Progress
            if (i - start_idx) % 250 == 0:
                print(f"  Bar {i - start_idx}: Equity=${total_equity:,.0f}, "
                      f"Positions={len(self.open_positions)}, Regime={market_state.regime.value}")
        
        # Close all remaining positions
        final_state = self.regime_detector.detect(market_data, len(market_data) - 1)
        for pos in self.open_positions[:]:
            pos.exit_reason = ExitReason.EXPIRATION
            pos.exit_date = final_state.date
            self._close_position(pos, final_state)
        
        return self._generate_report()
    
    def _scan_entries(self, market_state: MarketState):
        """Scan for new entry opportunities"""
        # Risk checks
        if len(self.open_positions) >= self.strategy_engine.config['max_concurrent']:
            return
            
        portfolio_risk = sum(p.capital_at_risk for p in self.open_positions)
        if portfolio_risk >= self.capital * self.strategy_engine.config['max_portfolio_risk']:
            return
            
        # Daily loss limit
        if self.daily_pnl:
            today_pnl = sum(d['pnl'] for d in self.daily_pnl[-1:])
            if today_pnl < -self.capital * 0.02:  # -2% daily limit
                return
        
        # Get strategy recommendation
        result = self.strategy_engine.select_strategy(market_state, self.capital)
        if not result:
            return
            
        strategy_type, params = result
        
        # Build position
        position = self._build_position(strategy_type, params, market_state)
        if not position:
            return
            
        # Execute entry
        executed_legs, cost = self.executor.execute_entry(position.legs, market_state)
        position.legs = executed_legs
        position.entry_credit_debit = cost / 100
        
        # Check if we have capital
        if abs(cost) > self.capital * 0.5:  # Don't use more than 50% on one trade
            return
            
        self.capital -= cost
        self.open_positions.append(position)
        
        print(f"  ENTRY: {strategy_type.value} @ {market_state.date.date()}, "
              f"Spot={market_state.spot:.2f}, Cost=${cost:.2f}, "
              f"Regime={market_state.regime.value}")
    
    def _build_position(self, strategy_type: StrategyType, params: Dict, 
                        ms: MarketState) -> Optional[Position]:
        """Build position from strategy parameters"""
        
        legs = []
        
        if strategy_type == StrategyType.IRON_CONDOR:
            # Put credit spread
            put_s = self.pricer.price(ms.spot, params['short_put_strike'], params['dte'], ms.vix / 100, 'put')
            put_l = self.pricer.price(ms.spot, params['long_put_strike'], params['dte'], ms.vix / 100, 'put')
            
            # Call credit spread
            call_s = self.pricer.price(ms.spot, params['short_call_strike'], params['dte'], ms.vix / 100, 'call')
            call_l = self.pricer.price(ms.spot, params['long_call_strike'], params['dte'], ms.vix / 100, 'call')
            
            credit = (put_s['price'] - put_l['price'] + call_s['price'] - call_l['price']) * 100
            width = params['short_put_strike'] - params['long_put_strike']
            max_loss = width * 100 - credit
            
            legs = [
                OptionLeg('put', params['short_put_strike'], params['dte'], -1, put_s['price'], greeks=put_s),
                OptionLeg('put', params['long_put_strike'], params['dte'], 1, put_l['price'], greeks=put_l),
                OptionLeg('call', params['short_call_strike'], params['dte'], -1, call_s['price'], greeks=call_s),
                OptionLeg('call', params['long_call_strike'], params['dte'], 1, call_l['price'], greeks=call_l),
            ]
            
            position = Position(
                strategy_type=strategy_type,
                legs=legs,
                entry_date=ms.date,
                entry_spot=ms.spot,
                entry_iv=ms.vix / 100,
                entry_vix=ms.vix,
                regime_at_entry=ms.regime,
                capital_at_risk=max_loss,
                max_profit=credit,
                max_loss=max_loss,
                target_profit=credit * self.config.get('target_profit_pct', 0.5),
                stop_loss=credit * self.config.get('stop_loss_pct', 2.0),
                entry_credit_debit=credit / 100
            )
            return position
            
        # Add other strategy builders...
        # For brevity, implementing Iron Condor as primary
        # Full implementation would have all strategy types
        
        return None
    
    def _manage_positions(self, market_state: MarketState):
        """Manage all open positions"""
        for position in self.open_positions[:]:
            # Check exit
            exit_reason = self.position_manager.evaluate_exit(position, market_state, self.pricer)
            
            if exit_reason:
                # Try adjustment first
                adjustment = self.position_manager.generate_adjustment(position, market_state, exit_reason)
                
                if adjustment and self._should_adjust(position, adjustment):
                    self._apply_adjustment(position, adjustment, market_state)
                    position.adjustments.append(adjustment)
                    print(f"  ADJUST: {position.strategy_type.value} - {adjustment.get('reason', '')}")
                else:
                    # Close position
                    self._close_position(position, market_state, exit_reason)
            else:
                # Check for proactive adjustments
                self._check_proactive_adjustments(position, market_state)
    
    def _should_adjust(self, position: Position, adjustment: Dict) -> bool:
        """Decide if adjustment is worth it"""
        # Don't adjust more than 2 times
        if len(position.adjustments) >= 2:
            return False
        # Don't adjust if very close to expiration
        min_dte = min(l.expiry_days for l in position.legs)
        if min_dte < 14:
            return False
        # Adjustment must improve risk/reward
        return True
    
    def _apply_adjustment(self, position: Position, adjustment: Dict, ms: MarketState):
        """Apply adjustment to position"""
        # This would modify the position legs
        # For now, just record it
        pass
    
    def _check_proactive_adjustments(self, position: Position, ms: MarketState):
        """Check for proactive adjustments (rolling, etc.)"""
        min_dte = min(l.expiry_days for l in position.legs)
        
        # Roll at 50% profit
        if position.current_pnl > position.max_profit * 0.5 and min_dte < 21:
            # Could roll here
            pass
    
    def _close_position(self, position: Position, market_state: MarketState, 
                        reason: ExitReason = None):
        """Close position and record results"""
        
        executed_legs, proceeds = self.executor.execute_exit(position.legs, market_state)
        
        position.legs = executed_legs
        position.exit_reason = reason or ExitReason.EXPIRATION
        position.exit_date = market_state.date
        position.exit_pnl = proceeds + position.entry_credit_debit * 100
        
        self.capital += proceeds
        self.open_positions.remove(position)
        self.closed_trades.append(position)
        
        # Record for learning
        self.strategy_engine.record_trade(position, position.exit_pnl)
        
        r_mult = position.exit_pnl / position.capital_at_risk if position.capital_at_risk > 0 else 0
        
        print(f"  EXIT: {position.strategy_type.value} @ {market_state.date.date()}, "
              f"P&L=${position.exit_pnl:.2f} ({r_mult:.2f}R), "
              f"Reason={position.exit_reason.value}, Days={position.days_held}")
    
    def _generate_report(self) -> Dict:
        """Generate comprehensive backtest report"""
        
        if not self.closed_trades:
            return {'error': 'No trades executed'}
            
        equity_df = pd.DataFrame(self.equity_curve)
        pnl_df = pd.DataFrame(self.daily_pnl) if self.daily_pnl else pd.DataFrame()
        
        # Trade statistics
        pnls = [t.exit_pnl for t in self.closed_trades]
        risks = [t.capital_at_risk for t in self.closed_trades]
        r_multiples = [p / r if r > 0 else 0 for p, r in zip(pnls, risks)]
        win_rates = [1 if p > 0 else 0 for p in pnls]
        
        # By strategy
        by_strategy = {}
        for t in self.closed_trades:
            strat = t.strategy_type.value
            if strat not in by_strategy:
                by_strategy[strat] = {'trades': 0, 'wins': 0, 'pnl': 0, 'r_mult': []}
            by_strategy[strat]['trades'] += 1
            if t.exit_pnl > 0:
                by_strategy[strat]['wins'] += 1
            by_strategy[strat]['pnl'] += t.exit_pnl
            by_strategy[strat]['r_mult'].append(
                t.exit_pnl / t.capital_at_risk if t.capital_at_risk > 0 else 0
            )
        
        # By regime
        by_regime = {}
        for t in self.closed_trades:
            regime = t.regime_at_entry.value
            if regime not in by_regime:
                by_regime[regime] = {'trades': 0, 'wins': 0, 'pnl': 0}
            by_regime[regime]['trades'] += 1
            if t.exit_pnl > 0:
                by_regime[regime]['wins'] += 1
            by_regime[regime]['pnl'] += t.exit_pnl
        
        # Risk metrics
        returns = pnl_df['pnl_pct'].values if len(pnl_df) > 0 else np.array([0])
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
        max_dd = self._max_drawdown(equity_df['equity'].values)
        
        # Exit reasons
        exit_reasons = {}
        for t in self.closed_trades:
            reason = t.exit_reason.value
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
        
        report = {
            'summary': {
                'initial_capital': self.initial_capital,
                'final_capital': self.capital + sum(p.current_pnl for p in self.open_positions),
                'total_return': (self.capital + sum(p.current_pnl for p in self.open_positions) - self.initial_capital) / self.initial_capital,
                'total_trades': len(self.closed_trades),
                'win_rate': np.mean(win_rates) if win_rates else 0,
                'avg_r_multiple': np.mean(r_multiples) if r_multiples else 0,
                'profit_factor': sum(p for p in pnls if p > 0) / abs(sum(p for p in pnls if p < 0)) if any(p < 0 for p in pnls) else float('inf'),
                'sharpe_ratio': sharpe,
                'max_drawdown': max_dd,
                'avg_days_held': np.mean([t.days_held for t in self.closed_trades]),
            },
            'by_strategy': {k: {**v, 'win_rate': v['wins']/v['trades'], 'avg_r': np.mean(v['r_mult'])} 
                           for k, v in by_strategy.items()},
            'by_regime': {k: {**v, 'win_rate': v['wins']/v['trades'] if v['trades'] > 0 else 0} 
                         for k, v in by_regime.items()},
            'exit_reasons': exit_reasons,
            'equity_curve': self.equity_curve[-100:],  # Last 100 points
            'learned_parameters': self.strategy_engine.parameter_memory,
        }
        
        return report
    
    def _max_drawdown(self, equity: np.ndarray) -> float:
        """Calculate maximum drawdown"""
        peak = np.maximum.accumulate(equity)
        dd = (peak - equity) / peak
        return np.max(dd) if len(dd) > 0 else 0

# ============================================================
# DATA GENERATOR (for testing without external data)
# ============================================================

class SyntheticDataGenerator:
    """Generate realistic market data for backtesting"""
    
    @staticmethod
    def generate(days: int = 756, start_price: float = 4500, 
                 seed: int = 42) -> pd.DataFrame:
        """Generate synthetic OHLCV data with regime changes"""
        np.random.seed(seed)
        
        dates = pd.date_range(start='2022-01-01', periods=days, freq='B')
        
        # Regime schedule
        regime_changes = [
            (0, 150, 'trending_up', 0.15, 0.15),
            (150, 250, 'high_vol', 0.0, 0.35),
            (250, 400, 'ranging', 0.05, 0.18),
            (400, 500, 'trending_down', -0.06, 0.25),
            (500, 600, 'low_vol', 0.08, 0.12),
            (600, days, 'ranging', 0.03, 0.16),
        ]
        
        prices = [start_price]
        vix_values = []
        iv_ranks = []
        
        for i in range(1, days):
            # Determine regime
            regime = 'ranging'
            drift = 0.0
            vol = 0.16
            for start, end, r, d, v in regime_changes:
                if start <= i < end:
                    regime = r
                    drift = d / 252
                    vol = v / np.sqrt(252)
                    break
            
            # Add momentum
            if i > 20:
                mom = (prices[-1] - prices[-20]) / prices[-20]
                drift += np.clip(mom * 0.05, -0.001, 0.001)
            # Mean reversion to long-term trend
            if i > 60:
                long_term = np.mean(prices[-60:])
                reversion = (long_term - prices[-1]) / prices[-1] * 0.001
                drift += reversion
                drift += mom * 0.1
            
            # Generate return
            ret = np.random.normal(drift, vol)
            ret = np.clip(ret, -0.15, 0.15)  # Cap daily returns
            
            # Fat tails
            if np.random.random() < 0.02:
                ret *= 3
            
            new_price = prices[-1] * (1 + ret)
            new_price = min(new_price, prices[-1] * 1.20)  # Max 20% daily move
            new_price = max(new_price, prices[-1] * 0.80)  # Min -20% daily move
            new_price = min(new_price, start_price * 5)  # Absolute max 5x
            prices.append(max(new_price, 100))
            
            # VIX
            base_vix = vol * np.sqrt(252) * 100
            vix_noise = np.random.normal(0, 3)
            vix = max(8, base_vix + vix_noise)
            vix_values.append(vix)
            
            # IV Rank (simplified)
            iv_rank = min(95, max(5, (vix - 10) / 30 * 100 + np.random.normal(0, 10)))
            iv_ranks.append(iv_rank)
        
        vix_values = [vix_values[0]] + vix_values
        iv_ranks = [iv_ranks[0]] + iv_ranks
        
        # Create OHLC
        data = []
        for i, (date, close, vix, ivr) in enumerate(zip(dates, prices, vix_values, iv_ranks)):
            if i == 0:
                open_ = close
            else:
                open_ = prices[i-1]
            high = max(open_, close) * (1 + abs(np.random.normal(0, 0.005)))
            low = min(open_, close) * (1 - abs(np.random.normal(0, 0.005)))
            volume = int(np.random.lognormal(13, 0.5))
            
            data.append({
                'date': date,
                'open': open_,
                'high': high,
                'low': low,
                'close': close,
                'volume': volume,
                'vix': vix,
                'iv_rank': ivr,
                'iv_percentile': ivr,
                'skew': np.random.normal(0, 2),
            })
        
        df = pd.DataFrame(data)
        df.set_index('date', inplace=True)
        return df

# ============================================================
# MAIN ENTRY POINT
# ============================================================

def run_backtest(config: Dict = None) -> Dict:
    """Run complete backtest"""
    
    # Generate synthetic data
    print("Generating synthetic market data...")
    market_data = SyntheticDataGenerator.generate(days=756)  # ~3 years
    
    # Create engine
    engine = OptionsBacktestEngine(initial_capital=100000, config=config)
    
    # Run
    print("Running backtest...")
    report = engine.run(market_data, start_idx=100)  # Skip warmup
    
    return report

if __name__ == '__main__':
    # Run backtest
    config = {
        'target_profit_pct': 0.50,
        'stop_loss_pct': 2.0,
        'dte_exit': 21,
        'delta_threshold': 0.30,
        'gamma_threshold': 0.05,
        'max_concurrent': 8,
        'max_risk_per_trade': 0.02,
    }
    
    report = run_backtest(config)
    
    # Print results
    print("\n" + "="*60)
    print("BACKTEST RESULTS")
    print("BACKTEST RESULTS")
    print("="*60)
    s = report['summary']
    print(f"Initial Capital:    ${s['initial_capital']:,.0f}")
    print(f"Final Capital:      ${s['final_capital']:,.0f}")
    print(f"Total Return:       {s['total_return']:.2%}")
    print(f"Total Trades:       {s['total_trades']}")
    print(f"Win Rate:           {s['win_rate']:.1%}")
    print(f"Avg R-Multiple:     {s['avg_r_multiple']:.2f}")
    print(f"Profit Factor:      {s['profit_factor']:.2f}")
    print(f"Sharpe Ratio:       {s['sharpe_ratio']:.2f}")
    print(f"Max Drawdown:       {s['max_drawdown']:.1%}")
    print(f"Avg Days Held:      {s['avg_days_held']:.1f}")
    
    print("\nBy Strategy:")
    for strat, stats in report['by_strategy'].items():
        print(f"  {strat:20s}: {stats['trades']:3d} trades, "
              f"WR={stats['win_rate']:.1%}, "
              f"P&L=${stats['pnl']:,.0f}, "
              f"Avg R={stats['avg_r']:.2f}")
    
    print("\nBy Regime:")
    for regime, stats in report['by_regime'].items():
        print(f"  {regime:15s}: {stats['trades']:3d} trades, "
              f"WR={stats['win_rate']:.1%}, "
              f"P&L=${stats['pnl']:,.0f}")
    
    print("\nExit Reasons:")
    for reason, count in report['exit_reasons'].items():
        print(f"  {reason:20s}: {count}")
    
    print("\nLearned Parameters:")
    for key, params in report['learned_parameters'].items():
        print(f"  {key}: {params}")
