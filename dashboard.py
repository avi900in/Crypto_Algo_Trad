import os
import sys
import subprocess
import signal
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from datetime import datetime
import dotenv

# Add current path to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import database
from strategy import BreakoutStrategy
from bot import get_exchange,get_exchange_public,fetch_ohlcv_safely

# Setup page
st.set_page_config(
    page_title="Antigravity Algo Trader",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load env file from bot directory
DOTENV_PATH = os.path.join(database.DB_DIR, ".env")
dotenv.load_dotenv(DOTENV_PATH)

# Colors matching dark tech/cyberpunk design system
BG_COLOR = "#0D0E12"
CARD_BG = "#151720"
PRIMARY_COLOR = "#00F2FE"    # Neon Cyan
SECONDARY_COLOR = "#7F00FF"  # Violet
SUCCESS_COLOR = "#00E676"    # Pulsing Green
ERROR_COLOR = "#FF1744"      # Soft Crimson
TEXT_MUTED = "#8E9AA8"

# Inject custom CSS for premium look
st.markdown(f"""
    <style>
    /* Dark Theme Core Adjustments */
    .stApp {{
        background-color: {BG_COLOR};
        color: #E2E8F0;
        font-family: 'Inter', sans-serif;
    }}
    
    /* Header Container styling */
    .header-container {{
        background: linear-gradient(135deg, {CARD_BG} 0%, #1c1f2e 100%);
        border: 1px solid rgba(0, 242, 254, 0.15);
        border-radius: 12px;
        padding: 20px 25px;
        margin-bottom: 25px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
    }}
    .header-title {{
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(90deg, {PRIMARY_COLOR} 0%, {SECONDARY_COLOR} 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 0;
    }}
    .header-subtitle {{
        color: {TEXT_MUTED};
        font-size: 0.95rem;
        margin-top: 5px;
        margin-bottom: 0;
    }}
    
    /* Custom metric card */
    .metric-card {{
        background-color: {CARD_BG};
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        box-shadow: 0 4px 10px rgba(0,0,0,0.2);
        transition: all 0.3s ease;
    }}
    .metric-card:hover {{
        border-color: rgba(0, 242, 254, 0.3);
        transform: translateY(-2px);
    }}
    .metric-label {{
        color: {TEXT_MUTED};
        font-size: 0.85rem;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 8px;
    }}
    .metric-value {{
        font-size: 1.8rem;
        font-weight: 700;
        margin-bottom: 5px;
    }}
    
    /* Pulsing status badges */
    .status-running {{
        color: {SUCCESS_COLOR};
        font-weight: 700;
        animation: pulse 1.8s infinite;
        display: inline-block;
    }}
    .status-stopped {{
        color: {ERROR_COLOR};
        font-weight: 700;
        display: inline-block;
    }}
    
    @keyframes pulse {{
        0% {{ opacity: 0.4; }}
        50% {{ opacity: 1; }}
        100% {{ opacity: 0.4; }}
    }}
    
    /* Style for trade lists */
    .trade-row {{
        background-color: {CARD_BG};
        border-left: 4px solid #64748B;
        padding: 10px 15px;
        margin-bottom: 8px;
        border-radius: 4px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }}
    .trade-row.buy {{
        border-left-color: {SUCCESS_COLOR};
    }}
    .trade-row.sell {{
        border-left-color: {ERROR_COLOR};
    }}
    .tag-buy {{
        background-color: rgba(0, 230, 118, 0.15);
        color: {SUCCESS_COLOR};
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 700;
    }}
    .tag-sell {{
        background-color: rgba(255, 23, 68, 0.15);
        color: {ERROR_COLOR};
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 700;
    }}
    </style>
""", unsafe_allow_html=True)

# Helper to retrieve dashboard master password from Streamlit secrets, .env, or database
def get_dashboard_password():
    try:
        if hasattr(st, "secrets") and "DASHBOARD_PASSWORD" in st.secrets:
            return str(st.secrets["DASHBOARD_PASSWORD"]).strip()
    except Exception:
        pass
    env_pass = os.getenv("DASHBOARD_PASSWORD", "").strip()
    if env_pass:
        return env_pass
    try:
        db_pass = database.get_config("dashboard_password", "")
        if db_pass:
            return str(db_pass).strip()
    except Exception:
        pass
    return ""

# Authentication Gate
configured_password = get_dashboard_password()
if configured_password:
    if not st.session_state.get("authenticated", False):
        _, login_col, _ = st.columns([1, 1.4, 1])
        with login_col:
            st.markdown(f"""
                <div style="background: linear-gradient(135deg, {CARD_BG} 0%, #1c1f2e 100%); 
                            border: 1px solid rgba(0, 242, 254, 0.3); border-radius: 16px; 
                            padding: 35px 25px 25px 25px; margin-top: 60px; text-align: center; 
                            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);">
                    <div style="font-size: 2.4rem; margin-bottom: 5px;">⚡</div>
                    <h2 style="background: linear-gradient(90deg, {PRIMARY_COLOR} 0%, {SECONDARY_COLOR} 100%); 
                               -webkit-background-clip: text; -webkit-text-fill-color: transparent; 
                               margin: 0; font-weight: 800; font-size: 1.6rem;">TERMINAL LOCKED</h2>
                    <p style="color: {TEXT_MUTED}; font-size: 0.88rem; margin-top: 8px; margin-bottom: 0;">Enter your master password to access the trading terminal.</p>
                </div>
            """, unsafe_allow_html=True)
            st.markdown("<div style='margin-bottom: 12px;'></div>", unsafe_allow_html=True)
            with st.form("login_form"):
                entered_password = st.text_input("Master Password", type="password", placeholder="Enter password...", label_visibility="collapsed")
                submit_login = st.form_submit_button("🔓 Unlock Terminal", use_container_width=True)
                if submit_login:
                    if entered_password == configured_password:
                        st.session_state["authenticated"] = True
                        st.toast("Access Granted!", icon="🔓")
                        st.rerun()
                    else:
                        st.error("❌ Invalid master password. Access denied.")
        st.stop()

# Process Management Helpers
def get_bot_pid():
    pid_path = os.path.join(database.DB_DIR, "data", "bot.pid")
    if os.path.exists(pid_path):
        try:
            with open(pid_path, "r") as f:
                return int(f.read().strip())
        except Exception:
            return None
    return None

def is_bot_running():
    pid = get_bot_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        # Cleanup invalid PID file
        pid_path = os.path.join(database.DB_DIR, "data", "bot.pid")
        if os.path.exists(pid_path):
            try:
                os.remove(pid_path)
            except Exception:
                pass
        return False

def start_bot():
    if is_bot_running():
        return True
    try:
        database.set_config("bot_status", "running")
        # Run bot.py as background process using current Python interpreter
        subprocess.Popen(
            [sys.executable, os.path.join(database.DB_DIR, "bot.py")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=database.DB_DIR
        )
        return True
    except Exception as e:
        st.error(f"Failed to start bot: {e}")
        return False

def stop_bot():
    database.set_config("bot_status", "stopped")
    pid = get_bot_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            # Short sleep to let process clean up
            time_slept = 0
            while is_bot_running() and time_slept < 3:
                import time
                time.sleep(0.5)
                time_slept += 0.5
            return True
        except OSError:
            pass
    return False

# Load current DB settings
configs = database.get_all_configs()
dry_run = configs.get("dry_run", "1") == "1"
symbols_list = [s.strip() for s in configs.get("symbols", "BTC/USDT,ETH/USDT").split(",")]
trade_size_usd = float(configs.get("trade_size_usd", 20.0))
stop_loss_pct = float(configs.get("stop_loss_pct", 1.5))
take_profit_pct = float(configs.get("take_profit_pct", 3.0))
candle_interval = configs.get("interval", "5m")

# UI - Sidebar Control Center
st.sidebar.markdown("### 🛠️ Control Center")

# Bot status indicator
bot_active = is_bot_running()
status_html = f'<span class="status-running">● RUNNING</span>' if bot_active else f'<span class="status-stopped">● STOPPED</span>'
st.sidebar.markdown(f"**Bot Status**: {status_html}", unsafe_allow_html=True)

# Start/Stop buttons
if not bot_active:
    if st.sidebar.button("▶️ Start Algorithmic Bot", use_container_width=True):
        if start_bot():
            st.toast("Bot started successfully!", icon="🚀")
            st.rerun()
else:
    if st.sidebar.button("🛑 Stop Algorithmic Bot", use_container_width=True):
        if stop_bot():
            st.toast("Bot stopped successfully.", icon="🛑")
            st.rerun()

if configured_password and st.session_state.get("authenticated", False):
    st.sidebar.markdown("<div style='margin-top: 8px;'></div>", unsafe_allow_html=True)
    if st.sidebar.button("🔒 Lock Dashboard", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("### ⚙️ Quick Configurations")

# Dry Run toggle
new_dry_run = st.sidebar.toggle("Dry Run (Paper Trading)", value=dry_run, help="Simulate trades with live market data using a virtual $100 balance. Keep enabled to test strategies safely.")
if new_dry_run != dry_run:
    database.set_config("dry_run", "1" if new_dry_run else "0")
    st.toast(f"Mode changed to {'Paper Trading' if new_dry_run else 'Live Trading'}", icon="🔄")
    st.rerun()

# Parameters inputs
new_trade_size = st.sidebar.number_input("Trade Size ($)", min_value=5.0, max_value=100.0, value=trade_size_usd, step=5.0, help="Amount of USD/USDT allocated to each buy order.")
new_stop_loss = st.sidebar.number_input("Stop Loss (%)", min_value=0.5, max_value=10.0, value=stop_loss_pct, step=0.1, help="Percentage drop below entry price to trigger a sell.")
new_take_profit = st.sidebar.number_input("Take Profit (%)", min_value=0.5, max_value=20.0, value=take_profit_pct, step=0.2, help="Percentage rise above entry price to trigger a sell.")
new_interval = st.sidebar.selectbox("Candle Timeframe", options=["1m", "5m", "15m", "30m", "1h", "4h"], index=["1m", "5m", "15m", "30m", "1h", "4h"].index(candle_interval))

if (new_trade_size != trade_size_usd or new_stop_loss != stop_loss_pct or 
    new_take_profit != take_profit_pct or new_interval != candle_interval):
    database.set_config("trade_size_usd", new_trade_size)
    database.set_config("stop_loss_pct", new_stop_loss)
    database.set_config("take_profit_pct", new_take_profit)
    database.set_config("interval", new_interval)
    st.toast("Parameters updated successfully!", icon="💾")
    st.rerun()

# Target Symbols input
new_symbols_str = st.sidebar.text_input("Trade Pairs (comma separated)", value=configs.get("symbols", "BTC/USDT,ETH/USDT,SOL/USDT"))
if new_symbols_str != configs.get("symbols"):
    database.set_config("symbols", new_symbols_str)
    st.toast("Trading pairs updated!", icon="💱")
    st.rerun()

# Main Interface Layout - Header & Top Refresh Toolbar (Equal 50/50 Width)
top_col1, top_col2 = st.columns(2)

with top_col1:
    st.markdown(f"""
        <div class="header-container" style="padding: 12px 18px; margin-bottom: 0px; min-height: 98px; display: flex; flex-direction: column; justify-content: center;">
            <h1 class="header-title" style="font-size: 1.35rem; margin: 0; line-height: 1.2;">⚡ ANTIGRAVITY ALGO TRADER</h1>
            <p class="header-subtitle" style="font-size: 0.8rem; margin-top: 4px; margin-bottom: 0; line-height: 1.3;">
                Volumetric Breakout Bot • Timeframe: <strong>{candle_interval}</strong> • Mode: <span style="color: {'#00E676' if dry_run else '#00F2FE'}; font-weight: 600;">{'Paper Trading' if dry_run else 'Live Account'}</span>
            </p>
        </div>
    """, unsafe_allow_html=True)

with top_col2:
    st.markdown(f"""
        <div style="background-color: {CARD_BG}; border: 1px solid rgba(0, 242, 254, 0.15); border-radius: 12px; padding: 12px 18px; margin-bottom: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.4);">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:0.85rem; color:{TEXT_MUTED}; text-transform:uppercase; letter-spacing:1px; font-weight:700;">🔄 Real-time Sync</span>
                <span style="font-size:0.8rem; color:{SUCCESS_COLOR}; background:rgba(0,230,118,0.12); padding:3px 8px; border-radius:4px; font-family:monospace;">Updated: {datetime.now().strftime('%H:%M:%S')}</span>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    rc1, rc2, rc3 = st.columns([1.2, 1.2, 1])
    with rc1:
        if st.button("↻ Refresh Now", use_container_width=True):
            st.rerun()
    with rc2:
        auto_refresh = st.toggle("Auto-Sync", value=st.session_state.get("auto_refresh", False), key="auto_refresh_toggle")
        st.session_state["auto_refresh"] = auto_refresh
    with rc3:
        refresh_interval_map = {"5s": 5, "10s": 10, "15s": 15, "30s": 30, "60s": 60, "2m": 120}
        selected_interval_label = st.selectbox(
            "Interval",
            options=list(refresh_interval_map.keys()),
            index=list(refresh_interval_map.keys()).index(st.session_state.get("refresh_interval_label", "15s")),
            key="refresh_interval_select",
            label_visibility="collapsed"
        )
        st.session_state["refresh_interval_label"] = selected_interval_label
        refresh_seconds = refresh_interval_map[selected_interval_label]

st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)

# Fetch stats and trade data
mode_type = "PAPER" if dry_run else "LIVE"
trades = database.get_trades(limit=100, trade_type=mode_type)

# Calculate Metric Values
if dry_run:
    balances = database.get_all_paper_balances()
    usdt_bal = balances.get("USDT", 0.0)
    
    # Calculate current asset values dynamically using CCXT
    api_key = os.getenv("CRYPTOCOM_API_KEY")
    api_secret = os.getenv("CRYPTOCOM_API_SECRET")
    api_secret_public=''
    exchange = get_exchange(api_key, api_secret)
    exchange_public=get_exchange_public(api_key,api_secret_public)
    
    asset_value = 0.0
    open_positions = database.get_open_paper_positions()
    for currency, details in open_positions.items():
        try:
            symbol = details.get('symbol', f"{currency}/USDT")
            ticker = exchange_public.fetch_ticker(symbol)
            asset_value += details['amount'] * ticker['last']
        except Exception:
            # Fallback to entry price if rate limited or network fails
            asset_value += details['amount'] * details['entry_price']
            
    total_equity = usdt_bal + asset_value
    net_profit = total_equity - 100.0
    profit_pct = (net_profit / 100.0) * 100
else:
    # Live balances
    try:
        api_key = os.getenv("CRYPTOCOM_API_KEY")
        api_secret = os.getenv("CRYPTOCOM_API_SECRET")
        exchange = get_exchange(api_key, api_secret)
        live_balance = exchange.fetch_balance()
        usdt_bal = live_balance.get('total', {}).get('USDT', 0.0)
        
        asset_value = 0.0
        # Calculate active live positions based on bought assets
        trades_live = database.get_trades(limit=100, trade_type="LIVE")
        # In a real environment we sum wallet balances of all cryptos
        for currency, total_val in live_balance.get('total', {}).items():
            if currency != 'USDT' and total_val > 0.0:
                try:
                    symbol = next((s for s in symbols_list if s.startswith(f"{currency}/")), f"{currency}/USDT")
                    ticker = exchange.fetch_ticker(symbol)
                    asset_value += total_val * ticker['last']
                except Exception:
                    pass
        total_equity = usdt_bal + asset_value
        initial_live = float(database.get_config("live_initial_equity", total_equity if total_equity > 0 else 100.0))
        # Save initial equity if not set
        if not database.get_config("live_initial_equity"):
            database.set_config("live_initial_equity", total_equity)
            initial_live = total_equity
        net_profit = total_equity - initial_live
        profit_pct = (net_profit / initial_live) * 100 if initial_live > 0 else 0.0
    except Exception:
        # Fallback if keys are missing/invalid
        total_equity = 0.0
        net_profit = 0.0
        profit_pct = 0.0
        usdt_bal = 0.0
        open_positions = {}

# Closed trades count & win rate
closed_trades = [t for t in trades if t['side'] == 'SELL' and t['status'] == 'COMPLETED']
winning_trades = [t for t in closed_trades if t['pnl'] is not None and t['pnl'] > 0]
win_rate = (len(winning_trades) / len(closed_trades)) * 100 if closed_trades else 0.0

# Render top stats row
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Total Equity (USD)</div>
            <div class="metric-value" style="color: {PRIMARY_COLOR};">${total_equity:.2f}</div>
            <div style="font-size:0.85rem; color:{TEXT_MUTED}">USDT Cash: ${usdt_bal:.2f}</div>
        </div>
    """, unsafe_allow_html=True)

with col2:
    pnl_color = SUCCESS_COLOR if net_profit >= 0 else ERROR_COLOR
    st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Net Profit / Loss</div>
            <div class="metric-value" style="color: {pnl_color};">{net_profit:+.2f} USD</div>
            <div style="font-size:0.85rem; color:{pnl_color}">{profit_pct:+.2f}% ROI</div>
        </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Win Rate (Closed Trades)</div>
            <div class="metric-value" style="color: {SUCCESS_COLOR if win_rate >= 50 else TEXT_MUTED};">{win_rate:.1f}%</div>
            <div style="font-size:0.85rem; color:{TEXT_MUTED}">Wins: {len(winning_trades)} / Total: {len(closed_trades)}</div>
        </div>
    """, unsafe_allow_html=True)

with col4:
    active_positions_count = len(database.get_open_paper_positions()) if dry_run else len([t for t in trades if t['side'] == 'BUY']) # simple proxy
    if not dry_run:
        # Count open positions for live
        active_positions_count = 0
        try:
            for currency, amt in live_balance.get('total', {}).items():
                if currency != 'USDT' and amt > 0.0001:
                    active_positions_count += 1
        except Exception:
            pass
            
    st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Active Positions</div>
            <div class="metric-value" style="color: {SECONDARY_COLOR};">{active_positions_count}</div>
            <div style="font-size:0.85rem; color:{TEXT_MUTED}">Target pairs: {len(symbols_list)}</div>
        </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# Body Section
mcol1, mcol2 = st.columns([2, 1])

with mcol1:
    st.markdown("### 📊 Market Technical Chart")
    selected_symbol = st.selectbox("Select Asset to Analyze", options=symbols_list)
    
    # Initialize exchange to fetch chart data
    api_key = os.getenv("CRYPTOCOM_API_KEY")
    api_secret = os.getenv("CRYPTOCOM_API_SECRET")
    api_secret_public=''
    exchange_public = get_exchange_public(api_key, api_secret_public)
    
    df = fetch_ohlcv_safely(exchange_public, selected_symbol, timeframe=candle_interval, limit=50)
    
    if df is not None and len(df) > 0:
        # Calculate strategy indicators
        strategy = BreakoutStrategy()
        df = strategy.calculate_indicators(df)
        
        # Check active position for this coin
        currency = selected_symbol.split('/')[0]
        pos_details = None
        if dry_run:
            opp = database.get_open_paper_positions()
            if currency in opp:
                pos_details = opp[currency]
        
        is_holding = pos_details is not None
        entry_price = pos_details['entry_price'] if is_holding else None
        
        # Run real-time check
        analysis = strategy.analyze(
            df=df,
            open_position=is_holding,
            entry_price=entry_price,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct
        )
        
        # Plotly chart
        fig = go.Figure()
        
        # Subplots: Row 1 = Candlestick & EMA, Row 2 = Volume, Row 3 = RSI
        from plotly.subplots import make_subplots
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, 
                            vertical_spacing=0.05, 
                            row_heights=[0.5, 0.2, 0.3])
        
        # Candlestick
        fig.add_trace(go.Candlestick(
            x=df['timestamp'],
            open=df['open'], high=df['high'],
            low=df['low'], close=df['close'],
            name='Candles'
        ), row=1, col=1)
        
        # EMA 20
        fig.add_trace(go.Scatter(
            x=df['timestamp'], y=df['ema_20'],
            line=dict(color='#FF8F00', width=1.5),
            name='EMA 20'
        ), row=1, col=1)
        
        # Entry price line if holding
        if is_holding and entry_price:
            fig.add_hline(y=entry_price, line_dash="dash", line_color=PRIMARY_COLOR, line_width=1.5, 
                          annotation_text=f"BUY Entry: ${entry_price:.2f}", annotation_position="top left", row=1, col=1)
            
        # Volume
        fig.add_trace(go.Bar(
            x=df['timestamp'], y=df['volume'],
            marker_color='#4FACFE',
            name='Volume'
        ), row=2, col=1)
        
        # Volume SMA
        fig.add_trace(go.Scatter(
            x=df['timestamp'], y=df['volume_sma'],
            line=dict(color='#E91E63', width=1.2),
            name='Vol SMA'
        ), row=2, col=1)
        
        # RSI
        fig.add_trace(go.Scatter(
            x=df['timestamp'], y=df['rsi'],
            line=dict(color=PRIMARY_COLOR, width=1.5),
            name='RSI (14)'
        ), row=3, col=1)
        
        fig.add_hline(y=70, line_dash="dash", line_color=ERROR_COLOR, line_width=1, row=3, col=1)
        fig.add_hline(y=50, line_dash="dash", line_color="gray", line_width=1, row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color=SUCCESS_COLOR, line_width=1, row=3, col=1)
        
        fig.update_layout(
            template='plotly_dark',
            xaxis_rangeslider_visible=False,
            height=500,
            margin=dict(l=10, r=10, t=10, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
        # Analysis results output
        st.markdown(f"""
            <div style="background-color: {CARD_BG}; border-radius: 8px; padding: 15px; border-left: 4px solid {PRIMARY_COLOR}">
                <strong>Agent Strategy Signal Analysis</strong>: 
                <span style="color: {SUCCESS_COLOR if analysis['signal']=='BUY' else (ERROR_COLOR if analysis['signal']=='SELL' else '#FFF')}; font-weight: bold;">{analysis['signal']}</span>
                <br><span style="color: {TEXT_MUTED}">Reason: {analysis['reason']} | RSI: {analysis['rsi']:.1f} | Volume Ratio: {analysis['volume_ratio']:.2f}x</span>
            </div>
        """, unsafe_allow_html=True)
    else:
        st.info(f"Connecting to Crypto.com Exchange API. Fetching live charts for {selected_symbol}...")
        st.spinner("Connecting...")

with mcol2:
    st.markdown("### 💼 Active Positions")
    
    if dry_run:
        opp = database.get_open_paper_positions()
        if opp:
            for cur, details in opp.items():
                symbol = details.get('symbol', f"{cur}/USDT")
                # Get current price
                try:
                    ticker = exchange.fetch_ticker(symbol)
                    cur_price = ticker['last']
                except Exception:
                    cur_price = details['entry_price']
                
                # Fetch trailing peak price
                peak_key = f"peak_PAPER_{symbol}"
                peak_val = database.get_config(peak_key)
                peak_price = float(peak_val) if peak_val else details['entry_price']
                
                # Use current stop loss configuration for visual display
                trailing_stop_price = peak_price * (1 - stop_loss_pct / 100)
                
                chg = ((cur_price - details['entry_price']) / details['entry_price']) * 100
                chg_color = SUCCESS_COLOR if chg >= 0 else ERROR_COLOR
                
                st.markdown(f"""
                    <div style="background-color:{CARD_BG}; padding:15px; border-radius:8px; margin-bottom:10px; border: 1px solid rgba(255,255,255,0.05)">
                        <div style="display:flex; justify-content:space-between; font-weight:bold; font-size:1.1rem">
                            <span>{symbol}</span>
                            <span style="color:{chg_color}">{chg:+.2f}%</span>
                        </div>
                        <div style="color:{TEXT_MUTED}; font-size:0.85rem; margin-top:5px">
                            Holding: {details['amount']:.6f} {cur}<br>
                            Buy Price: ${details['entry_price']:.2f} | Peak: ${peak_price:.2f}<br>
                            Current Stop: ${trailing_stop_price:.2f} | Current: ${cur_price:.2f}
                        </div>
                    </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown(f"<div style='color:{TEXT_MUTED}; font-style:italic;'>No active paper positions. Scanning for breakouts...</div>", unsafe_allow_html=True)
    else:
        # Live positions list
        st.markdown(f"<div style='color:{TEXT_MUTED}; font-style:italic;'>Connect live keys to display open wallet positions.</div>", unsafe_allow_html=True)
        try:
            if api_key and api_secret:
                st.write("Fetching wallet positions...")
                for currency, amt in live_balance.get('total', {}).items():
                    if currency != 'USDT' and amt > 0.0001:
                        st.write(f"🟢 **{currency}**: {amt:.4f} units")
        except Exception:
            pass

    st.markdown("<br>### 📈 Equity Performance Curve", unsafe_allow_html=True)
    perf_history = database.get_performance_history(type=mode_type, limit=100)
    if len(perf_history) > 1:
        perf_df = pd.DataFrame(perf_history)
        perf_df['timestamp'] = pd.to_datetime(perf_df['timestamp'])
        
        fig_equity = go.Figure()
        fig_equity.add_trace(go.Scatter(
            x=perf_df['timestamp'], y=perf_df['total_equity'],
            mode='lines+markers',
            line=dict(color=PRIMARY_COLOR, width=2),
            name='Total Equity'
        ))
        fig_equity.update_layout(
            template='plotly_dark',
            height=200,
            margin=dict(l=10, r=10, t=10, b=10),
            xaxis_title="Time",
            yaxis_title="Equity ($)"
        )
        st.plotly_chart(fig_equity, use_container_width=True)
    else:
        st.markdown(f"<div style='color:{TEXT_MUTED}; font-style:italic;'>Equity tracking will plot here as the bot updates hourly.</div>", unsafe_allow_html=True)

st.markdown("<br>---<br>", unsafe_allow_html=True)

# Tabs section
tab_trades, tab_manual, tab_settings, tab_logs = st.tabs(["📜 Execution Logs", "➕ Manual Trade Entry", "🔑 API Settings", "⚙️ Bot Terminal Output"])

with tab_trades:
    st.markdown("### Historical Orders")
    if trades:
        for t in trades:
            side_tag = f'<span class="tag-buy">BUY</span>' if t['side'] == 'BUY' else f'<span class="tag-sell">SELL</span>'
            pnl_info = ""
            if t['side'] == 'SELL' and t['pnl'] is not None:
                color = SUCCESS_COLOR if t['pnl'] >= 0 else ERROR_COLOR
                pnl_info = f" • <span style='color:{color}; font-weight:bold;'>PnL: {t['pnl']:+.4f} USD</span>"
                
            time_formatted = datetime.fromisoformat(t['timestamp']).strftime("%m-%d %H:%M:%S")
            trade_class = 'buy' if t['side'] == 'BUY' else 'sell'
            row_html = (
                f'<div class="trade-row {trade_class}">'
                f'<div>{side_tag} <strong>{t["symbol"]}</strong> • {t["amount"]:.5f} units @ ${t["price"]:.2f}</div>'
                f'<div style="font-size:0.9rem; text-align:right;"><span style="color:{TEXT_MUTED}">{time_formatted}</span>{pnl_info}</div>'
                f'</div>'
            )
            st.markdown(row_html, unsafe_allow_html=True)
    else:
        st.markdown(f"<div style='color:{TEXT_MUTED}; font-style:italic;'>No execution logs yet. Launch the bot to start trading.</div>", unsafe_allow_html=True)

with tab_manual:
    st.markdown("### ➕ Manual Trade Entry")
    st.caption("Manually insert missing or uncaptured BUY / SELL orders directly into the database.")
    
    with st.form("manual_trade_form", clear_on_submit=False):
        fcol1, fcol2, fcol3 = st.columns(3)
        with fcol1:
            form_type = st.selectbox("Trading Mode", options=["LIVE", "PAPER"], index=0 if not dry_run else 1)
            form_side = st.selectbox("Order Side", options=["BUY", "SELL"])
        with fcol2:
            form_symbol = st.text_input("Symbol Pair (e.g. XRP/USDT, ADA/USDT, BTC/USDT)", value="XRP/USDT")
            form_price = st.number_input("Execution Price ($)", min_value=0.000001, value=1.0, format="%.6f")
        with fcol3:
            form_amount = st.number_input("Quantity / Amount", min_value=0.000001, value=10.0, format="%.6f")
            form_fee = st.number_input("Trading Fee ($)", min_value=0.0, value=0.0, format="%.4f")
            
        fcol4, fcol5 = st.columns(2)
        with fcol4:
            form_pnl = None
            if form_side == "SELL":
                pnl_input = st.number_input("Realized PnL ($)", value=0.0, format="%.4f", help="Net profit/loss on this sale.")
                form_pnl = pnl_input
            else:
                st.info(f"💡 Total Cost: **${(form_price * form_amount):.4f} USD**")
        with fcol5:
            form_notes = st.text_input("Notes / Exchange Order ID", value="Manual order entry")
            
        submit_trade = st.form_submit_button("💾 Insert Trade Record", use_container_width=True)
        
        if submit_trade:
            if not form_symbol:
                st.error("Please enter a valid symbol pair.")
            else:
                total_cost = form_price * form_amount
                database.add_trade(
                    timestamp=datetime.now().isoformat(),
                    symbol=form_symbol.upper().strip(),
                    side=form_side,
                    price=form_price,
                    amount=form_amount,
                    cost=total_cost,
                    fee=form_fee,
                    pnl=form_pnl,
                    status="COMPLETED",
                    type=form_type,
                    notes=form_notes
                )
                if form_type == "PAPER":
                    currency = form_symbol.upper().strip().split('/')[0]
                    current_asset = database.get_paper_balance(currency)
                    current_usdt = database.get_paper_balance("USDT")
                    if form_side == "BUY":
                        database.update_paper_balance("USDT", max(0.0, current_usdt - total_cost))
                        database.update_paper_balance(currency, current_asset + form_amount)
                    elif form_side == "SELL":
                        database.update_paper_balance("USDT", current_usdt + (total_cost - form_fee))
                        database.update_paper_balance(currency, max(0.0, current_asset - form_amount))
                        
                import telegram_notifier
                telegram_notifier.notify_trade(
                    side=form_side,
                    symbol=form_symbol.upper().strip(),
                    price=float(form_price),
                    amount=float(form_amount),
                    cost=float(total_cost),
                    fee=float(form_fee),
                    pnl=float(form_pnl) if form_pnl is not None else None,
                    reason=f"Manual Dashboard Entry ({form_notes})",
                    trade_type=form_type
                )
                
                st.success(f"✅ Successfully added {form_type} {form_side} order for {form_amount} {form_symbol.upper()} @ ${form_price:.4f}!")
                st.toast("Trade recorded & Telegram alerted!", icon="✅")
                import time
                time.sleep(1)
                st.rerun()

with tab_settings:
    st.markdown("### Crypto.com API Credentials")
    st.info("💡 Your API keys and Telegram credentials are saved locally in the `.env` file in the workspace directory. They are never shared with any external third party.")
    
    current_key = os.getenv("CRYPTOCOM_API_KEY", "")
    current_secret = os.getenv("CRYPTOCOM_API_SECRET", "")
    current_tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    current_tg_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    
    col_k1, col_k2 = st.columns(2)
    with col_k1:
        api_key_input = st.text_input("Crypto.com API Key", value=current_key, type="password")
    with col_k2:
        api_secret_input = st.text_input("Crypto.com API Secret", value=current_secret, type="password")
        
    st.markdown("---")
    st.markdown("### 🤖 Telegram Bot Notifications (`ID_Crypto_Algo_Trader_bot`)")
    st.caption("Receive instant alerts with price, quantity, signal reason, and PnL on every live/paper order.")
    
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        tg_token_input = st.text_input("Telegram Bot Token (from @BotFather)", value=current_tg_token, type="password", help="Example: 7123456789:AAHfj1... from @BotFather")
    with col_t2:
        tg_chat_id_input = st.text_input("Telegram Chat ID", value=current_tg_chat_id, help="Your personal or group Telegram Chat ID (e.g. 123456789 or @userinfobot)")
        
    st.markdown("---")
    st.markdown("### 🛡️ Dashboard Access Password")
    st.caption("Protect your cloud dashboard with a master password so only you can access it.")
    
    current_pass = get_dashboard_password()
    dash_pass_input = st.text_input("Master Dashboard Password", value=current_pass, type="password", placeholder="Set a master password (leave empty to disable)...")
    
    st.markdown("<div style='margin-bottom: 12px;'></div>", unsafe_allow_html=True)
    
    btn_col1, btn_col2 = st.columns([1, 1])
    with btn_col1:
        if st.button("💾 Save All Credentials & Password", use_container_width=True):
            try:
                with open(DOTENV_PATH, "w") as f:
                    f.write(f"CRYPTOCOM_API_KEY={api_key_input}\n")
                    f.write(f"CRYPTOCOM_API_SECRET={api_secret_input}\n")
                    f.write(f"TELEGRAM_BOT_TOKEN={tg_token_input}\n")
                    f.write(f"TELEGRAM_CHAT_ID={tg_chat_id_input}\n")
                    f.write(f"DASHBOARD_PASSWORD={dash_pass_input}\n")
                # Also cache in DB configs
                database.set_config("telegram_bot_token", tg_token_input)
                database.set_config("telegram_chat_id", tg_chat_id_input)
                database.set_config("dashboard_password", dash_pass_input)
                st.success("Credentials and password saved successfully!")
                st.toast("Settings saved!", icon="🔒")
                import time
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Error saving keys: {e}")
                
    with btn_col2:
        if st.button("📲 Send Test Telegram Alert", use_container_width=True):
            import telegram_notifier
            test_success = telegram_notifier.send_telegram_message(
                "⚡ <b>Antigravity Crypto Algo Trader</b>\n\n"
                "✅ <i>Telegram bot connection successful!</i>\n"
                "You will now receive live BUY/SELL alerts with order price, quantity, signal reason, and PnL.",
                token=tg_token_input,
                chat_id=tg_chat_id_input
            )
            if test_success:
                st.success("✅ Test message delivered to your Telegram!")
                st.toast("Telegram test delivered!", icon="🚀")
            else:
                st.error("❌ Failed to send Telegram message. Please check your Bot Token and Chat ID.")

with tab_logs:
    st.markdown("### Engine Real-time Logs (`data/bot.log`)")
    log_path = os.path.join(database.DB_DIR, "data", "bot.log")
    
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                log_lines = f.readlines()
            
            # Show last 40 lines
            log_content = "".join(log_lines[-40:])
            st.text_area("Bot Terminal", value=log_content, height=300)
        except Exception as e:
            st.error(f"Failed to read logs: {e}")
    else:
        st.markdown(f"<div style='color:{TEXT_MUTED}; font-style:italic;'>No bot logs found. The log file will be generated once the bot process starts.</div>", unsafe_allow_html=True)

# Auto-refresh background loop
if st.session_state.get("auto_refresh", False):
    import time
    time.sleep(refresh_seconds)
    st.rerun()
