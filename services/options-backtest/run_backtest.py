#!/usr/bin/env python3
"""
Runner for Options Backtest Engine
"""

import sys
sys.path.insert(0, '/Users/aryanagarwal/.hermes/universal-workspace/repos/OpenAlice/services/options-backtest')

from options_backtest import run_backtest

if __name__ == '__main__':
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
    
    # Save report
    import json
    import pandas as pd
    
    def convert(obj):
        if hasattr(obj, 'value'):  # Enum
            return obj.value
        if isinstance(obj, pd.Timestamp):
            return str(obj)
        if isinstance(obj, dict):
            return {k: convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [convert(v) for v in obj]
        return obj
    
    with open('/Users/aryanagarwal/.hermes/universal-workspace/repos/OpenAlice/services/options-backtest/backtest_report.json', 'w') as f:
        serializable = convert(report)
        json.dump(serializable, f, indent=2)
    
    print("Report saved to backtest_report.json")
