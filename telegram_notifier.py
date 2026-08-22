import os
import json
import urllib.request
import urllib.error
from datetime import datetime
import dotenv

DOTENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

# Helper to retrieve token & chat_id from environment or database
def get_telegram_credentials():
    dotenv.load_dotenv(DOTENV_PATH, override=True)
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    
    # Also check database config if available
    try:
        import database
        if not token:
            token = database.get_config("telegram_bot_token", "") or ""
        if not chat_id:
            chat_id = database.get_config("telegram_chat_id", "") or ""
    except Exception:
        pass
        
    return token.strip(), chat_id.strip()

def send_telegram_message(text: str, token: str = None, chat_id: str = None) -> bool:
    """
    Send an HTML formatted message to Telegram Bot using standard urllib.
    Non-blocking / safe: returns False on error without raising exceptions.
    """
    if not token or not chat_id:
        env_token, env_chat_id = get_telegram_credentials()
        token = token or env_token
        chat_id = chat_id or env_chat_id

    if not token or not chat_id:
        # Not configured
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            res_body = response.read().decode("utf-8")
            res_json = json.loads(res_body)
            return res_json.get("ok", False)
    except Exception as e:
        print(f"[Telegram Notifier] Error sending message: {e}")
        return False

def notify_trade(side: str, symbol: str, price: float, amount: float, cost: float, 
                 fee: float = 0.0, pnl: float = None, entry_price: float = None, 
                 reason: str = "", trade_type: str = "LIVE", order_id: str = "") -> bool:
    """
    Format and send a structured trade alert to Telegram for BUY or SELL orders.
    """
    side = side.upper()
    trade_type = trade_type.upper()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    currency = symbol.split('/')[0]

    if side == "BUY":
        icon = "🚀" if trade_type == "LIVE" else "🧪"
        title = f"{icon} <b>CRYPTO ALGO TRADER: {trade_type} BUY</b>"
        
        msg = (
            f"{title}\n\n"
            f"🪙 <b>Pair:</b> <code>{symbol}</code>\n"
            f"📈 <b>Action:</b> BUY\n"
            f"💵 <b>Price:</b> ${price:,.4f}\n"
            f"🔢 <b>Quantity:</b> {amount:.6f} {currency}\n"
            f"💰 <b>Total Cost:</b> ${cost:,.2f}\n"
            f"🧾 <b>Fee:</b> ${fee:,.4f}\n"
            f"💡 <b>Signal Reason:</b> {reason or 'Volume Breakout / Momentum Signal'}\n"
        )
        if order_id:
            msg += f"🆔 <b>Order ID:</b> <code>{order_id}</code>\n"
        msg += f"⏱ <b>Timestamp:</b> <code>{now_str}</code>"

    else: # SELL
        icon = "🔔" if trade_type == "LIVE" else "🧪"
        pnl_pct = 0.0
        if entry_price and entry_price > 0:
            pnl_pct = ((price - entry_price) / entry_price) * 100

        pnl_badge = "⚪"
        if pnl is not None:
            pnl_badge = "🟢" if pnl >= 0 else "🔴"

        title = f"{icon} <b>CRYPTO ALGO TRADER: {trade_type} SELL</b>"
        
        msg = (
            f"{title}\n\n"
            f"🪙 <b>Pair:</b> <code>{symbol}</code>\n"
            f"📉 <b>Action:</b> SELL\n"
            f"💵 <b>Exit Price:</b> ${price:,.4f}\n"
        )
        if entry_price:
            msg += f"🏷 <b>Entry Price:</b> ${entry_price:,.4f}\n"
            
        msg += (
            f"🔢 <b>Quantity:</b> {amount:.6f} {currency}\n"
            f"💰 <b>Total Value:</b> ${cost:,.2f}\n"
            f"🧾 <b>Fee:</b> ${fee:,.4f}\n"
        )
        
        if pnl is not None:
            msg += f"📊 <b>PnL:</b> {pnl_badge} <b>{pnl:+.4f} USD ({pnl_pct:+.2f}%)</b>\n"
            
        msg += f"💡 <b>Exit Reason:</b> {reason or 'Stop Loss / Take Profit Target'}\n"
        
        if order_id:
            msg += f"🆔 <b>Order ID:</b> <code>{order_id}</code>\n"
        msg += f"⏱ <b>Timestamp:</b> <code>{now_str}</code>"

    return send_telegram_message(msg)
