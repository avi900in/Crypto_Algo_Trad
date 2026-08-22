#!/usr/bin/env python3
"""
Manual Trade Entry CLI Tool for Antigravity Crypto Algo Trader
Allows manual insertion of BUY or SELL trades into the SQLite database.
"""

import sys
import os
import argparse
from datetime import datetime

# Ensure project root is in sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import database
import telegram_notifier

def insert_manual_trade(symbol, side, price, amount, cost=None, fee=0.0, pnl=None, trade_type="LIVE", status="COMPLETED", timestamp=None, notes=""):
    symbol = symbol.upper().strip()
    side = side.upper().strip()
    trade_type = trade_type.upper().strip()
    
    if side not in ["BUY", "SELL"]:
        raise ValueError(f"Invalid side '{side}'. Must be 'BUY' or 'SELL'.")
    
    if trade_type not in ["LIVE", "PAPER"]:
        raise ValueError(f"Invalid type '{trade_type}'. Must be 'LIVE' or 'PAPER'.")

    price = float(price)
    amount = float(amount)
    
    if cost is None:
        cost = price * amount
    else:
        cost = float(cost)
        
    fee = float(fee) if fee is not None else 0.0
    pnl = float(pnl) if pnl is not None and pnl != "" else None
    
    if timestamp is None:
        timestamp = datetime.now().isoformat()

    database.add_trade(
        timestamp=timestamp,
        symbol=symbol,
        side=side,
        price=price,
        amount=amount,
        cost=cost,
        fee=fee,
        pnl=pnl,
        status=status,
        type=trade_type,
        notes=notes or "Manual trade entry"
    )
    
    # If paper trading, also update balances accordingly
    if trade_type == "PAPER":
        currency = symbol.split('/')[0]
        stable_currency = "USDT"
        current_stable = database.get_paper_balance(stable_currency)
        current_asset = database.get_paper_balance(currency)
        
        if side == "BUY":
            database.update_paper_balance(stable_currency, max(0.0, current_stable - cost))
            database.update_paper_balance(currency, current_asset + amount)
        elif side == "SELL":
            database.update_paper_balance(stable_currency, current_stable + (cost - fee))
            database.update_paper_balance(currency, max(0.0, current_asset - amount))

    # Send Telegram notification
    telegram_notifier.notify_trade(
        side=side,
        symbol=symbol,
        price=price,
        amount=amount,
        cost=cost,
        fee=fee,
        pnl=pnl,
        reason=f"Manual trade entry ({notes})",
        trade_type=trade_type
    )

    print(f"✅ Successfully recorded {trade_type} {side} order for {amount} {symbol} @ ${price:.4f} (Total: ${cost:.2f})")

def interactive_entry():
    print("\n" + "="*50)
    print(" ⚡ Manual Trade Entry for Antigravity Bot ⚡")
    print("="*50)
    
    trade_type = input("Trade Type [LIVE / PAPER] (default: LIVE): ").strip().upper() or "LIVE"
    side = input("Side [BUY / SELL] (default: BUY): ").strip().upper() or "BUY"
    symbol = input("Symbol (e.g. XRP/USDT, ADA/USDT, BTC/USDT): ").strip().upper()
    if not symbol:
        print("❌ Symbol is required.")
        return
        
    try:
        price = float(input("Price ($): ").strip())
        amount = float(input("Amount / Quantity: ").strip())
    except ValueError:
        print("❌ Invalid price or amount.")
        return
        
    default_cost = price * amount
    cost_in = input(f"Total Cost ($) (default: {default_cost:.4f}): ").strip()
    cost = float(cost_in) if cost_in else default_cost
    
    fee_in = input("Fee ($) (default: 0.0): ").strip()
    fee = float(fee_in) if fee_in else 0.0
    
    pnl = None
    if side == "SELL":
        pnl_in = input("PnL ($) (optional, press Enter to skip): ").strip()
        if pnl_in:
            pnl = float(pnl_in)
            
    notes = input("Notes (optional, e.g. Order ID / reason): ").strip() or "Manual CLI entry"
    
    insert_manual_trade(
        symbol=symbol,
        side=side,
        price=price,
        amount=amount,
        cost=cost,
        fee=fee,
        pnl=pnl,
        trade_type=trade_type,
        notes=notes
    )

def main():
    parser = argparse.ArgumentParser(description="Insert a manual trade into the SQLite database.")
    parser.add_argument("--symbol", help="Trading pair symbol (e.g., XRP/USDT)")
    parser.add_argument("--side", choices=["BUY", "SELL", "buy", "sell"], help="Order side: BUY or SELL")
    parser.add_argument("--price", type=float, help="Execution price per unit")
    parser.add_argument("--amount", type=float, help="Order amount/units")
    parser.add_argument("--cost", type=float, default=None, help="Total cost in USD/USDT (default: price * amount)")
    parser.add_argument("--fee", type=float, default=0.0, help="Trading fee in USD/USDT")
    parser.add_argument("--pnl", type=float, default=None, help="Profit or Loss in USD/USDT (for SELL orders)")
    parser.add_argument("--type", choices=["LIVE", "PAPER", "live", "paper"], default="LIVE", help="Trade mode (LIVE or PAPER)")
    parser.add_argument("--timestamp", help="ISO Timestamp (default: current time)")
    parser.add_argument("--notes", default="Manual entry", help="Custom notes or Exchange Order ID")
    parser.add_argument("-i", "--interactive", action="store_true", help="Launch interactive prompt")
    
    args = parser.parse_args()
    
    if args.interactive or (not args.symbol and not args.price and not args.amount):
        interactive_entry()
    else:
        if not args.symbol or not args.side or args.price is None or args.amount is None:
            print("❌ Error: --symbol, --side, --price, and --amount are required when not running interactively.")
            sys.exit(1)
            
        insert_manual_trade(
            symbol=args.symbol,
            side=args.side,
            price=args.price,
            amount=args.amount,
            cost=args.cost,
            fee=args.fee,
            pnl=args.pnl,
            trade_type=args.type,
            timestamp=args.timestamp,
            notes=args.notes
        )

if __name__ == "__main__":
    main()
