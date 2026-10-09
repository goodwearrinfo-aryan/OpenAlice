#!/usr/bin/env python3
"""
Adaptive Polymarket Trading Bot
===============================
Connects the regime-aware strategy manager to Polymarket API.
"""

import os
import json
import time
import random
from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum

# ============================================================
# STRATEGY MANAGEMENT (from above)
# ============================================================

class StrategyState(Enum):
    ACTIVE = "active"
    COOLDOWN = "cooldown"
    DISABLED = "disabled"

@dataclass
class StrategyConfig:
    name: str
    polymarket_template: str  # Market slug pattern
    side: str  # "YES" or "NO"
    min_prob: float = 0.52
    max_position: float = 100.0  # Max shares per trade
    max_consecutive_losses: int = 3
    cooldown_bars: int = 10
    allowed_regimes: Optional[List[str]] = None
    blocked_regimes: Optional[List[str]] = None
    
    def __post_init__(self):
        if self.allowed_regimes is None:
            self.allowed_regimes = []
        if self.blocked_regimes is None:
            self.blocked_regimes = []

@dataclass
class LiveStrategy:
    config: StrategyConfig
    state: StrategyState = StrategyState.ACTIVE
    consecutive_losses: int = 0
    trades_today: int = 0
    total_pnl: float = 0.0
    peak_equity: float = 0.0
    cooldown_remaining: int = 0
    last_market: str = ""
    
    def record_trade(self, pnl: float, equity: float):
        self.trades_today += 1
        self.total_pnl += pnl
        self.peak_equity = max(self.peak_equity, equity)
        
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
            
        if self.consecutive_losses >= self.config.max_consecutive_losses:
            self.state = StrategyState.COOLDOWN
            self.cooldown_remaining = self.config.cooldown_bars
            
    def step_cooldown(self):
        if self.state == StrategyState.COOLDOWN:
            self.cooldown_remaining -= 1
            if self.cooldown_remaining <= 0:
                self.state = StrategyState.ACTIVE
                self.consecutive_losses = 0
    
    def is_active(self, current_regime: str) -> bool:
        if self.state != StrategyState.ACTIVE:
            return False
        if self.config.allowed_regimes and current_regime not in self.config.allowed_regimes:
            return False
        if current_regime in self.config.blocked_regimes:
            return False
        return True

class PolymarketAdaptiveBot:
    def __init__(self, client, initial_capital: float = 10000):
        self.client = client
        self.capital = initial_capital
        self.equity = initial_capital
        self.strategies: Dict[str, LiveStrategy] = {}
        self.current_regime = "unknown"
        self.open_positions = []
        self.trade_log = []
        
    def add_strategy(self, config: StrategyConfig):
        self.strategies[config.name] = LiveStrategy(config)
        
    def update_regime(self, regime: str):
        """Call this when regime detection signals a change"""
        self.current_regime = regime
        print(f"[REGIME] Switched to: {regime}")
        
    def scan_opportunities(self) -> List[Dict]:
        """Scan Polymarket for markets matching active strategies"""
        opportunities = []
        
        for name, strategy in self.strategies.items():
            if not strategy.is_active(self.current_regime):
                continue
                
            # In production: query Polymarket API for markets matching template
            # For demo, simulate finding a market
            market = self._find_market(strategy.config.polymarket_template)
            if market:
                prob = self._estimate_probability(market)
                if prob >= strategy.config.min_prob:
                    opportunities.append({
                        "strategy": name,
                        "market": market,
                        "probability": prob,
                        "side": strategy.config.side,
                        "max_size": strategy.config.max_position
                    })
                    
        return opportunities
    
    def _find_market(self, template: str) -> Optional[Dict]:
        """Simulate market lookup - replace with actual API call"""
        # Example: client.markets.list(conditions...)
        return {
            "slug": "chiefs-super-bowl-lx",
            "question": "Will the Chiefs win Super Bowl LX?",
            "yes_price": 0.52,
            "no_price": 0.48,
            "volume": 50000,
            "liquidity": 25000
        }
    
    def _estimate_probability(self, market: Dict) -> float:
        """Estimate true probability from market prices"""
        yes = market.get("yes_price", 0.5)
        no = market.get("no_price", 0.5)
        # Simple: midpoint adjusted for spread
        return (yes + (1 - no)) / 2
    
    def execute_trade(self, opportunity: Dict) -> bool:
        """Execute trade via Polymarket client"""
        strategy_name = opportunity["strategy"]
        strategy = self.strategies[strategy_name]
        market = opportunity["market"]
        side = opportunity["side"]
        size = min(opportunity["max_size"], self.capital * 0.02 / market[f"{side.lower()}_price"])
        
        try:
            order = self.client.orders.create({
                "marketSlug": market["slug"],
                "intent": f"ORDER_INTENT_BUY_{side.upper()}",
                "type": "ORDER_TYPE_LIMIT",
                "price": {"value": str(market[f"{side.lower()}_price"]), "currency": "USD"},
                "quantity": int(size),
                "tif": "TIME_IN_FORCE_GOOD_TILL_CANCEL",
            })
            
            print(f"[EXECUTE] {strategy_name} | {market['slug']} | {side} | {size} shares @ {market[f'{side.lower()}_price']}")
            
            # Track position
            self.open_positions.append({
                "order_id": order.get("id"),
                "strategy": strategy_name,
                "market_slug": market["slug"],
                "side": side,
                "quantity": size,
                "entry_price": market[f"{side.lower()}_price"],
                "entry_time": time.time()
            })
            strategy.last_market = market["slug"]
            return True
            
        except Exception as e:
            print(f"[ERROR] Trade failed: {e}")
            return False
    
    def manage_positions(self):
        """Check open positions for exits"""
        for pos in self.open_positions[:]:
            # In production: check current price via API
            current_price = self._get_current_price(pos["market_slug"], pos["side"])
            pnl = (current_price - pos["entry_price"]) * pos["quantity"]
            
            # Exit rules
            should_exit = False
            exit_reason = ""
            
            # Target: 50% profit
            if current_price >= pos["entry_price"] * 1.5:
                should_exit = True
                exit_reason = "target"
            # Stop: 30% loss
            elif current_price <= pos["entry_price"] * 0.7:
                should_exit = True
                exit_reason = "stop"
            # Time: 7 days
            elif time.time() - pos["entry_time"] > 7 * 24 * 3600:
                should_exit = True
                exit_reason = "time"
                
            if should_exit:
                self._close_position(pos, current_price, exit_reason)
    
    def _get_current_price(self, slug: str, side: str) -> float:
        """Get current market price - replace with API call"""
        # Simulate
        return random.uniform(0.3, 0.7)
    
    def _close_position(self, pos: Dict, exit_price: float, reason: str):
        pnl = (exit_price - pos["entry_price"]) * pos["quantity"]
        strategy = self.strategies[pos["strategy"]]
        strategy.record_trade(pnl, self.equity)
        self.equity += pnl
        self.capital += pnl
        
        print(f"[EXIT] {pos['strategy']} | {pos['market_slug']} | P&L: ${pnl:.2f} | Reason: {reason}")
        
        self.trade_log.append({
            "strategy": pos["strategy"],
            "market": pos["market_slug"],
            "side": pos["side"],
            "entry": pos["entry_price"],
            "exit": exit_price,
            "qty": pos["quantity"],
            "pnl": pnl,
            "reason": reason
        })
        self.open_positions.remove(pos)
    
    def step(self):
        """Call each iteration (e.g., every minute/hour)"""
        for s in self.strategies.values():
            s.step_cooldown()
            
        # Daily reset
        if hasattr(self, '_last_day'):
            if time.time() // 86400 != self._last_day:
                for s in self.strategies.values():
                    s.trades_today = 0
        self._last_day = time.time() // 86400
    
    def run_cycle(self):
        """Main trading loop iteration"""
        # 1. Scan for opportunities
        opportunities = self.scan_opportunities()
        
        # 2. Execute best opportunity per strategy
        for opp in opportunities:
            if self.capital > 1000:  # Min capital check
                self.execute_trade(opp)
        
        # 3. Manage existing positions
        self.manage_positions()
        
        # 4. Step cooldowns
        self.step()

# ============================================================
# REGIME DETECTION (simplified for Polymarket)
# ============================================================

def detect_regime_from_market_data() -> str:
    """
    Detect regime from market microstructure.
    Replace with actual implementation using:
    - Volatility of top 10 markets
    - Correlation of market moves
    - Volume/liquidity trends
    - External signals (VIX, crypto vol, etc.)
    """
    # Simplified: random for demo
    regimes = ["ranging", "trending_up", "trending_down", "high_vol", "low_vol"]
    return random.choice(regimes)

# ============================================================
# STRATEGY CONFIGS FOR POLYMARKET
# ============================================================

POLYMARKET_STRATEGIES = [
    StrategyConfig(
        name="sports_reversion",
        polymarket_template="*super-bowl*",
        side="YES",
        min_prob=0.55,
        max_position=50,
        allowed_regimes=["ranging", "low_vol"],
        blocked_regimes=["high_vol", "crash"],
        max_consecutive_losses=3,
        cooldown_bars=5
    ),
    StrategyConfig(
        name="election_trend",
        polymarket_template="*presidential-election*",
        side="YES",
        min_prob=0.52,
        max_position=100,
        allowed_regimes=["trending_up", "trending_down"],
        blocked_regimes=["high_vol"],
        max_consecutive_losses=4,
        cooldown_bars=10
    ),
    StrategyConfig(
        name="crypto_vol_crush",
        polymarket_template="*bitcoin*",
        side="NO",  # Sell volatility
        min_prob=0.60,
        max_position=75,
        allowed_regimes=["high_vol"],
        blocked_regimes=["low_vol", "crash"],
        max_consecutive_losses=3,
        cooldown_bars=7
    ),
    StrategyConfig(
        name="event_straddle",
        polymarket_template="*fed-rate*",
        side="YES",
        min_prob=0.45,  # Lower prob, higher R
        max_position=30,
        allowed_regimes=["high_vol"],
        blocked_regimes=["low_vol"],
        max_consecutive_losses=2,
        cooldown_bars=3
    ),
]

# ============================================================
# MAIN
# ============================================================

def main():
    # Initialize Polymarket client (your credentials)
    try:
        from polymarket_us import PolymarketUS
        client = PolymarketUS(
            key_id=os.environ["POLYMARKET_KEY_ID"],
            secret_key=os.environ["POLYMARKET_SECRET_KEY"],
        )
    except ImportError:
        print("[WARN] polymarket_us not installed, using mock client")
        client = MockClient()
    except KeyError:
        print("[WARN] POLYMARKET credentials not set, using mock client")
        client = MockClient()
    
    # Initialize bot
    bot = PolymarketAdaptiveBot(client, initial_capital=10000)
    
    for config in POLYMARKET_STRATEGIES:
        bot.add_strategy(config)
    
    print("=== ADAPTIVE POLYMARKET BOT STARTED ===")
    print(f"Capital: ${bot.capital:,.2f}")
    print(f"Strategies: {list(bot.strategies.keys())}")
    print()
    
    # Main loop
    cycle = 0
    while True:
        try:
            cycle += 1
            print(f"\n{'='*50}")
            print(f"CYCLE {cycle} | Equity: ${bot.equity:,.2f} | Regime: {bot.current_regime}")
            
            # Update regime (in production: use real detection)
            new_regime = detect_regime_from_market_data()
            bot.update_regime(new_regime)
            
            # Run trading cycle
            bot.run_cycle()
            
            # Status
            active = [n for n, s in bot.strategies.items() if s.is_active(bot.current_regime)]
            print(f"Active strategies: {active}")
            print(f"Open positions: {len(bot.open_positions)}")
            
            # Sleep
            time.sleep(60)  # 1 minute cycles
            
        except KeyboardInterrupt:
            print("\n[SHUTDOWN] Saving state...")
            break
        except Exception as e:
            print(f"[ERROR] Cycle failed: {e}")
            time.sleep(30)

class MockClient:
    """Mock client for testing without API keys"""
    class Orders:
        def create(self, order):
            return {"id": f"mock_{random.randint(1000,9999)}", **order}
    orders = Orders()

if __name__ == "__main__":
    main()