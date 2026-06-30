---
name: mt5-trader-helper
description: Operations and connection routines for MetaTrader 5 (MT5) with Exness trading engine integration.
---

# MetaTrader 5 & Exness Trading Helper Skill

This skill provides python routines for managing MT5 connections, opening/closing positions with precise Risk Management, and handling execution errors.

## 1. Initialising MT5 & Checking Connection

Always verify terminal status and account details before attempting trades.

```python
import MetaTrader5 as mt5

def check_mt5_connection(login, password, server):
    if not mt5.initialize():
        print("initialize() failed, error code =", mt5.last_error())
        return False
        
    # Login to Exness Account
    authorized = mt5.login(login, password=password, server=server)
    if not authorized:
        print(f"Failed to authorize account {login}, error={mt5.last_error()}")
        mt5.shutdown()
        return False
        
    account_info = mt5.account_info()
    print(f"Connected! Account Balance: {account_info.balance} USD")
    return True
```

## 2. Order Execution (Market Order with SL/TP)

Place trades with exact risk settings. Ensure proper lot sizing based on currency or index properties (e.g. US30m).

```python
def send_market_order(symbol, action, lot, sl_points=300, tp_points=600):
    """
    action: mt5.ORDER_TYPE_BUY or mt5.ORDER_TYPE_SELL
    """
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(f"{symbol} not found")
        return None

    # Check if symbol is enabled, if not enable it
    if not symbol_info.visible:
        mt5.symbol_select(symbol, True)

    point = symbol_info.point
    price = mt5.symbol_info_tick(symbol).ask if action == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(symbol).bid
    
    sl_price = price - (sl_points * point) if action == mt5.ORDER_TYPE_BUY else price + (sl_points * point)
    tp_price = price + (tp_points * point) if action == mt5.ORDER_TYPE_BUY else price - (tp_points * point)
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(lot),
        "type": action,
        "price": price,
        "sl": sl_price,
        "tp": tp_price,
        "deviation": 20,
        "magic": 102030,
        "comment": "Oracle MAS Automated Trade",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Order failed, retcode={result.retcode} error_str={result.comment}")
    else:
        print(f"Order success! Ticket={result.order}")
    return result
```

## 3. Handling MT5 Trade Errors

Ensure you intercept common Exness broker errors:
- `TRADE_RETCODE_MARKET_CLOSED` (10018): Market is closed. Do not retry, log and skip.
- `TRADE_RETCODE_REQUOTE` (10004): Price changed. Fetch the new tick and retry once.
- `TRADE_RETCODE_NO_MONEY` (10019): Balance is insufficient for margin.
