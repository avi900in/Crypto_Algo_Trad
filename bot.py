import os
import sys
import time
import signal
import traceback
from datetime import datetime
import pandas as pd
import ccxt
import dotenv
import database
import telegram_notifier
from strategy import BreakoutStrategy

# Load environment variables
dotenv.load_dotenv(os.path.join(database.DB_DIR, ".env"), override=True)

# Constants
FEE_RATE = 0.005  # 0.5% exchange fee (50 bps)
PID_FILE = os.path.join(database.DB_DIR, "data", "bot.pid")
LOG_FILE = os.path.join(database.DB_DIR, "data", "bot.log")

running = True

def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"
    print(formatted_msg)
    sys.stdout.flush()
    try:
        with open(LOG_FILE, "a") as f:
            f.write(formatted_msg + "\n")
    except Exception:
        pass

def handle_signals(signum, frame):
    global running
    log(f"Received signal {signum}. Shutting down...")
    running = False


def get_exchange(api_key=None, api_secret=None):
    params = {'enableRateLimit': True}
    if api_key and api_secret:
        params['apiKey'] = api_key
        params['secret'] = api_secret
    # Initialize Crypto.com Exchange client
    exchange = ccxt.cryptocom(params)
    return exchange

def get_exchange_public(api_key=None,api_secret_public=None):
    params_public = {'enableRateLimit': True}
    if api_key:
        params_public['apiKey'] = api_key
        params_public['secret'] = api_secret_public
    # Initialize Crypto.com Exchange client
    exchange_public = ccxt.cryptocom(params_public)
    return exchange_public

def fetch_ohlcv_safely(exchange_public, symbol, timeframe='5m', limit=50):
    try:
        # Load markets if not loaded
        if not exchange_public.markets:
            exchange_public.load_markets()
        
        # CCXT fetches OHLCV: [[timestamp, open, high, low, close, volume], ...]
        ohlcv = exchange_public.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        log(f"Error fetching OHLCV for {symbol}: {e}")
        return None

def execute_paper_buy(symbol, current_price, trade_size_usd, reason=""):
    # Treat USD and USDT quote currencies as interchangeable paper balances mapped to "USDT"
    stable_currency = "USDT"
    stable_balance = database.get_paper_balance(stable_currency)
    if stable_balance < trade_size_usd:
        log(f"Paper Buy FAILED: Insufficient stable balance ({stable_balance:.2f} < {trade_size_usd:.2f})")
        return False
    
    currency = symbol.split('/')[0]
    
    # Calculate amount after fee
    cost = trade_size_usd
    fee = cost * FEE_RATE
    net_cost = cost - fee
    amount = net_cost / current_price
    
    # Update SQLite balances
    database.update_paper_balance(stable_currency, stable_balance - cost)
    current_asset_bal = database.get_paper_balance(currency)
    database.update_paper_balance(currency, current_asset_bal + amount)
    
    # Log trade
    database.add_trade(
        timestamp=datetime.now().isoformat(),
        symbol=symbol,
        side="BUY",
        price=current_price,
        amount=amount,
        cost=cost,
        fee=fee,
        pnl=None,
        status="COMPLETED",
        type="PAPER",
        notes=f"Simulated breakout buy order: {reason}"
    )
    log(f"Paper BUY COMPLETED: Bought {amount:.6f} {currency} at ${current_price:.2f} for ${trade_size_usd:.2f} (Fee: ${fee:.4f})")
    
    # Send Telegram notification
    telegram_notifier.notify_trade(
        side="BUY",
        symbol=symbol,
        price=current_price,
        amount=amount,
        cost=cost,
        fee=fee,
        reason=reason,
        trade_type="PAPER"
    )
    return True

def execute_paper_sell(symbol, current_price, amount, entry_price, reason=""):
    currency = symbol.split('/')[0]
    
    # Calculate total value and fee
    gross_value = amount * current_price
    fee = gross_value * FEE_RATE
    net_value = gross_value - fee
    
    # Calculate PnL relative to entry
    buy_cost = amount * entry_price
    pnl = net_value - buy_cost
    
    # Update SQLite balances
    stable_currency = "USDT"
    stable_balance = database.get_paper_balance(stable_currency)
    current_asset_bal = database.get_paper_balance(currency)
    
    # Ensure we don't end up with negative balance due to precision issues
    new_asset_bal = max(0.0, current_asset_bal - amount)
    database.update_paper_balance(stable_currency, stable_balance + net_value)
    database.update_paper_balance(currency, new_asset_bal)
    
    # Log trade
    database.add_trade(
        timestamp=datetime.now().isoformat(),
        symbol=symbol,
        side="SELL",
        price=current_price,
        amount=amount,
        cost=gross_value,
        fee=fee,
        pnl=pnl,
        status="COMPLETED",
        type="PAPER",
        notes=f"Simulated exit from entry ${entry_price:.2f}: {reason}"
    )
    log(f"Paper SELL COMPLETED: Sold {amount:.6f} {currency} at ${current_price:.2f} for ${net_value:.2f} (Fee: ${fee:.4f}, PnL: ${pnl:+.4f})")
    
    # Send Telegram notification
    telegram_notifier.notify_trade(
        side="SELL",
        symbol=symbol,
        price=current_price,
        amount=amount,
        cost=gross_value,
        fee=fee,
        pnl=pnl,
        entry_price=entry_price,
        reason=reason,
        trade_type="PAPER"
    )
    return True

def execute_live_buy(exchange, symbol, current_price, trade_size_usd, reason=""):
    try:
        # Load markets to check limits
        exchange.load_markets()
        market = exchange.market(symbol)
        
        # Calculate amount based on trade size and price
        amount = trade_size_usd / current_price
        
        # Adjust amount to exchange precision & limits
        amount = float(exchange.amount_to_precision(symbol, amount))
        
        # Check against minimum order limits
        min_amount = market['limits']['amount']['min']
        if min_amount and amount < min_amount:
            log(f"Live Buy FAILED: Calculated order size {amount} is below exchange minimum {min_amount} for {symbol}")
            return False
            
        log(f"Placing Live Market BUY Order for {symbol}: {amount} units...")
        
        # Place market order
        order = exchange.create_market_buy_order(symbol, amount)
        
        # Parse result safely with fallbacks if exchange returns None values
        order_price = order.get('price') or current_price
        order_amount = order.get('filled') or order.get('amount') or amount
        order_cost = order.get('cost') or (float(order_price) * float(order_amount))

        order_fee = 0.0
        if order.get('fee') and order['fee'].get('cost') is not None:
            order_fee = float(order['fee']['cost'])

        database.add_trade(
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            side="BUY",
            price=order_price,
            amount=order_amount,
            cost=order_cost,
            fee=order_fee,
            pnl=None,
            status="COMPLETED",
            type="LIVE",
            notes=f"Live Exchange Order ID: {order.get('id')} | Reason: {reason}"
        )
        log(f"Live BUY COMPLETED: Bought {order_amount:.6f} at ${order_price:.2f} (Total: ${order_cost:.2f})")
        
        # Send Telegram notification
        tg_ok = telegram_notifier.notify_trade(
            side="BUY",
            symbol=symbol,
            price=float(order_price),
            amount=float(order_amount),
            cost=float(order_cost),
            fee=float(order_fee),
            reason=reason,
            trade_type="LIVE",
            order_id=str(order.get('id', ''))
        )
        if tg_ok:
            log(f"Telegram alert sent successfully for LIVE BUY {symbol}")
        else:
            log(f"Telegram alert not sent (check credentials or connection) for LIVE BUY {symbol}")
        return True
    except Exception as e:
        log(f"Live Buy FAILED: {e}")
        traceback.print_exc()
        return False

def execute_live_sell(exchange, symbol, current_price, amount, entry_price, reason=""):
    try:
        exchange.load_markets()
        market = exchange.market(symbol)
        currency = symbol.split('/')[0]
        
        # 1. Fetch real-time available wallet balance on the exchange
        balance = exchange.fetch_balance()
        free_balance = float(balance.get('free', {}).get(currency, 0.0) or 0.0)
        
        if free_balance <= 0.0:
            log(f"Live Sell FAILED: No available {currency} balance found in wallet (Free: {free_balance:.8f})")
            return False
            
        # 2. Cap sell amount to actual available wallet balance (accounts for fees deducted on buy)
        sell_amount = min(float(amount), free_balance)
        
        # 3. Floor down to exchange precision step size so we NEVER round up above available balance
        prec = market.get('precision', {}).get('amount')
        if prec is not None:
            import math
            if isinstance(prec, float) and prec < 1:
                decimals = abs(int(round(math.log10(prec))))
                sell_amount = round(math.floor(sell_amount / prec) * prec, decimals)
            elif isinstance(prec, int):
                sell_amount = round(math.floor(sell_amount * (10 ** prec)) / (10 ** prec), prec)
                
        amount_str = exchange.amount_to_precision(symbol, sell_amount)
        final_amount = float(amount_str)
        
        # Safety guarantee: never exceed free wallet balance
        if final_amount > free_balance:
            final_amount = sell_amount
            
        # Check against minimum order limits
        min_amount = market.get('limits', {}).get('amount', {}).get('min')
        if min_amount and final_amount < min_amount:
            log(f"Live Sell FAILED: Order size {final_amount} is below exchange minimum {min_amount} for {symbol}")
            return False
        
        log(f"Placing Live Market SELL Order for {symbol}: {final_amount} units (Wallet free: {free_balance:.6f} {currency})...")
        
        order = exchange.create_market_sell_order(symbol, final_amount)
        
        # Parse result safely with fallbacks if exchange returns None values
        order_price = order.get('price') or current_price
        order_amount = order.get('filled') or order.get('amount') or amount
        order_cost = order.get('cost') or (float(order_price) * float(order_amount))
        
        order_fee = 0.0
        if order.get('fee') and order['fee'].get('cost') is not None:
            order_fee = float(order['fee']['cost'])
            
        # PnL calculation
        buy_cost = float(order_amount) * float(entry_price)
        pnl = (float(order_cost) - float(order_fee)) - buy_cost
        
        database.add_trade(
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            side="SELL",
            price=order_price,
            amount=order_amount,
            cost=order_cost,
            fee=order_fee,
            pnl=pnl,
            status="COMPLETED",
            type="LIVE",
            notes=f"Live Exchange Order ID: {order.get('id')} | Reason: {reason}"
        )
        log(f"Live SELL COMPLETED: Sold {order_amount:.6f} at ${order_price:.2f} (PnL: ${pnl:+.4f})")
        
        # Send Telegram notification
        tg_ok = telegram_notifier.notify_trade(
            side="SELL",
            symbol=symbol,
            price=float(order_price),
            amount=float(order_amount),
            cost=float(order_cost),
            fee=float(order_fee),
            pnl=float(pnl),
            entry_price=float(entry_price),
            reason=reason,
            trade_type="LIVE",
            order_id=str(order.get('id', ''))
        )
        if tg_ok:
            log(f"Telegram alert sent successfully for LIVE SELL {symbol}")
        else:
            log(f"Telegram alert not sent (check credentials or connection) for LIVE SELL {symbol}")
        return True
    except Exception as e:
        log(f"Live Sell FAILED: {e}")
        traceback.print_exc()
        return False

def update_performance_snapshot(exchange,exchange_public,dry_run, target_symbols):
    try:
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:00:00") # Hourly snapshot
        
        if dry_run:
            # Paper trading equity calculation
            balances = database.get_all_paper_balances()
            usdt_bal = balances.get("USDT", 0.0)
            asset_value = 0.0
            
            for currency, amount in balances.items():
                if currency != "USDT" and amount > 0.0:
                    # Find which symbol in target_symbols matches currency
                    symbol = next((s for s in target_symbols if s.startswith(f"{currency}/")), f"{currency}/USDT")
                    # Fetch current price
                    try:
                        ticker = exchange.fetch_ticker(symbol)
                        current_price = ticker['last']
                        asset_value += amount * current_price
                    except Exception:
                        pass
            
            total_equity = usdt_bal + asset_value
            pnl = total_equity - 100.0 # Profit from $100 starting capital
            
            database.log_performance(timestamp_str, total_equity, pnl, "PAPER")
            
        else:
            # Live trading equity calculation

            balance = exchange.fetch_balance()
            total_equity = balance.get('total', {}).get('USD', 0.0)
            
            # Fetch prices of holding coins and sum up
            for currency, amount in balance.get('total', {}).items():
                if currency != 'USDT' and amount > 0.0:
                    symbol = next((s for s in target_symbols if s.startswith(f"{currency}/")), f"{currency}/USDT")
                    try:
                        ticker = exchange_public.fetch_ticker(symbol)
                        total_equity += amount * ticker['last']
                    except Exception:
                        pass
            
            # Retrieve initial live equity or default to $100
            initial_equity = float(database.get_config("live_initial_equity", 100.0))
            pnl = total_equity - initial_equity
            
            database.log_performance(timestamp_str, total_equity, pnl, "LIVE")
            
    except Exception as e:
        log(f"Error logging performance snapshot: {e}")

def run_bot_cycle(exchange,exchange_public,strategy):
    # 1. Fetch live configs from DB
    configs = database.get_all_configs()
    
    # Check if bot has been stopped
    if configs.get("bot_status") == "stopped":
        log("Bot status is set to STOPPED. Exiting cycle...")
        global running
        running = False
        return

    dry_run = configs.get("dry_run") == "1"
    symbols_str = configs.get("symbols", "BTC/USDT")
    symbols = [s.strip() for s in symbols_str.split(",") if s.strip()]
    trade_size_usd = float(configs.get("trade_size_usd", 20.0))
    stop_loss_pct = float(configs.get("stop_loss_pct", 1.5))
    take_profit_pct = float(configs.get("take_profit_pct", 3.0))
    timeframe = configs.get("interval", "5m")

    log(f"Starting cycle. Mode: {'PAPER' if dry_run else 'LIVE'} | Symbols: {symbols}")

    # Track open positions
    if dry_run:
        open_positions = database.get_open_paper_positions()
    else:
        # For live trading, we query the latest trade for each specific symbol
        open_positions = {}
        for s in symbols:
            currency = s.split('/')[0]
            conn = database.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
            SELECT side, amount, price FROM trades 
            WHERE symbol = ? AND status = 'COMPLETED' AND type = 'LIVE' 
            ORDER BY timestamp DESC LIMIT 1
            """, (s,))
            row = cursor.fetchone()
            conn.close()
            if row and row['side'] == 'BUY':
                open_positions[currency] = {
                    "amount": float(row['amount']),
                    "entry_price": float(row['price'])
                }

    # Analyze each symbol
    for symbol in symbols:
        currency = symbol.split('/')[0]
        
        # Fetch historical prices
        df = fetch_ohlcv_safely(exchange_public, symbol, timeframe, limit=50)
        if df is None or len(df) < 25:
            log(f"Skipping {symbol} due to insufficient candle data.")
            continue
            
        current_price = df.iloc[-1]['close']
        
        # Check if we are holding this coin
        is_holding = currency in open_positions
        entry_price = open_positions[currency]['entry_price'] if is_holding else None
        amount_held = open_positions[currency]['amount'] if is_holding else 0.0

        # Retrieve and update peak price for trailing stop loss
        mode_type = "PAPER" if dry_run else "LIVE"
        peak_key = f"peak_{mode_type}_{symbol}"
        if is_holding:
            prev_peak = database.get_config(peak_key)
            peak_price = max(float(prev_peak), current_price) if prev_peak else max(entry_price, current_price)
            database.set_config(peak_key, peak_price)
        else:
            peak_price = None
            database.set_config(peak_key, "")  # Clear if not holding

        # Run analysis (indicators computed on completed candles)
        analysis = strategy.analyze(
            df=df,
            open_position=is_holding,
            entry_price=entry_price,
            peak_price=peak_price,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            fee_rate=FEE_RATE
        )

        signal_type = analysis['signal']
        reason = analysis['reason']

        if signal_type != "HOLD":
            log(f"Signal for {symbol}: {signal_type} | Reason: {reason} | Price: ${current_price:.4f}")

        # Execute signals
        if signal_type == "BUY" and not is_holding:
            if dry_run:
                execute_paper_buy(symbol, current_price, trade_size_usd, reason=reason)
            else:
                execute_live_buy(exchange, symbol, current_price, trade_size_usd, reason=reason)
                
        elif signal_type == "SELL" and is_holding:
            if dry_run:
                execute_paper_sell(symbol, current_price, amount_held, entry_price, reason=reason)
            else:
                execute_live_sell(exchange, symbol, current_price, amount_held, entry_price, reason=reason)

    # 4. Log portfolio snapshot
    update_performance_snapshot(exchange, exchange_public, dry_run, symbols)

def main():
    global running
    
    # Ensure directory structure and double check if already running
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            print(f"Bot is already running with PID {pid}. Exiting.")
            sys.exit(0)
        except OSError:
            # Process doesn't exist, clean up PID file
            os.remove(PID_FILE)

    # Write current PID
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    # Register signal handlers
    try:
        signal.signal(signal.SIGINT, handle_signals)
        signal.signal(signal.SIGTERM, handle_signals)
    except ValueError as e:
        log(f"Could not register signal handlers: {e}")

    log("Crypto Algo Trading Bot starting up...")
    
    # Initialize exchange and strategy
    configs = database.get_all_configs()
    
    # Load keys
    api_key = os.getenv("CRYPTOCOM_API_KEY")
    api_secret = os.getenv("CRYPTOCOM_API_SECRET")
    api_secret_public=''
    
    exchange = get_exchange(api_key, api_secret)
    exchange_public = get_exchange_public(api_key,api_secret_public)
    strategy = BreakoutStrategy()

    # Loop
    try:
        while running:
            # Run one cycle
            run_bot_cycle(exchange,exchange_public,strategy)
            
            # Reload keys/configs dynamically
            configs = database.get_all_configs()
            if configs.get("bot_status") == "stopped":
                log("Received stop request via DB. Shutting down...")
                break
                
            # Sleep for 1 minute before checking again
            # Running frequently allows the bot to react quickly to SL/TP conditions
            time.sleep(60)
    except Exception as e:
        log(f"Fatal error in bot loop: {e}")
        traceback.print_exc()
    finally:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        log("Bot process terminated.")

if __name__ == "__main__":
    main()
