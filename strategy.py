import pandas as pd
import numpy as np

class BreakoutStrategy:
    def __init__(self, rsi_period=14, ema_period=20, volume_period=20, atr_period=14):
        self.rsi_period = rsi_period
        self.ema_period = ema_period
        self.volume_period = volume_period
        self.atr_period = atr_period

    def calculate_indicators(self, df):
        """
        Expects a pandas DataFrame with columns: ['open', 'high', 'low', 'close', 'volume']
        """
        if len(df) < max(self.rsi_period, self.ema_period, self.volume_period, self.atr_period) + 5:
            # Not enough data yet
            df['rsi'] = 50.0
            df['ema_20'] = df['close']
            df['volume_sma'] = df['volume']
            df['atr'] = df['close'] * 0.01
            return df

        # Calculate EMA
        df['ema_20'] = df['close'].ewm(span=self.ema_period, adjust=False).mean()

        # Calculate Volume SMA
        df['volume_sma'] = df['volume'].rolling(window=self.volume_period).mean().bfill().ffill()

        # Calculate Wilder's RSI
        delta = df['close'].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        
        avg_gain = gain.ewm(com=self.rsi_period - 1, adjust=False).mean()
        avg_loss = loss.ewm(com=self.rsi_period - 1, adjust=False).mean()
        
        # Avoid division by zero
        rs = np.where(avg_loss == 0, 0, avg_gain / avg_loss)
        df['rsi'] = 100 - (100 / (1 + rs))
        df['rsi'] = df['rsi'].fillna(50)

        # Calculate Wilder's ATR (Average True Range)
        high_low = df['high'] - df['low']
        high_close_prev = (df['high'] - df['close'].shift(1)).abs()
        low_close_prev = (df['low'] - df['close'].shift(1)).abs()
        tr = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
        df['atr'] = tr.ewm(com=self.atr_period - 1, adjust=False).mean().bfill().ffill()

        return df

    def analyze(self, df, open_position=False, entry_price=None, peak_price=None, stop_loss_pct=1.5, take_profit_pct=3.0, fee_rate=0.005):
        """
        Analyzes the latest bar and decides on BUY, SELL, or HOLD.
        Incorporates round-trip fees into the exit targets.
        """
        if len(df) < 5:
            return {"signal": "HOLD", "reason": "Insufficient candles"}

        df = self.calculate_indicators(df)
        
        # Latest completed candle values
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        current_price = latest['close']
        current_rsi = latest['rsi']
        current_vol = latest['volume']
        avg_vol = latest['volume_sma']
        ema_val = latest['ema_20']
        atr_val = latest.get('atr', current_price * 0.01)

        # Avoid zero division
        volume_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0

        # Calculate round-trip fee percentage (Buy fee + Sell fee)
        # e.g., 2 * 0.5% = 1.0%
        round_trip_fee_pct = 2 * fee_rate * 100

        # Fine-Tuning: Dynamic Exit targets based on ATR (market volatility)
        # Default multipliers: Stop Loss = 1.5x ATR, Take Profit = 3.0x ATR
        if atr_val > 0 and current_price > 0:
            dynamic_sl = (atr_val / current_price) * 1.5 * 100
            dynamic_tp = (atr_val / current_price) * 3.0 * 100
            
            # Guardrails to keep stop-loss and take-profit targets within realistic bounds
            stop_loss_pct = max(0.5, min(4.0, dynamic_sl))
            take_profit_pct = max(1.0, min(8.0, dynamic_tp))

        # Case 1: Already holding a position - Check Exit Conditions
        if open_position and entry_price is not None:
            # Trailing Stop-Loss uses the peak price reached since entry.
            # If peak_price is not provided/tracked, we fallback to entry_price.
            reference_price = peak_price if peak_price is not None else entry_price
            
            # Trailing stop loss: check drop relative to peak price
            price_change_from_peak = ((current_price - reference_price) / reference_price) * 100
            
            # Take profit: check gain relative to core entry price
            price_change_from_entry = ((current_price - entry_price) / entry_price) * 100

            # Adjust Take Profit to be net of round-trip transaction fees
            required_tp_gain = take_profit_pct + round_trip_fee_pct

            # Trailing Stop Loss trigger (stop loss remains relative to volatility)
            if price_change_from_peak <= -stop_loss_pct:
                return {
                    "signal": "SELL",
                    "reason": f"Trailing Stop Loss hit: dropped {price_change_from_peak:.2f}% from peak ${reference_price:.2f} (Limit: -{stop_loss_pct:.2f}%)",
                    "rsi": current_rsi,
                    "volume_ratio": volume_ratio,
                    "stop_loss_pct": stop_loss_pct,
                    "take_profit_pct": take_profit_pct
                }

            # Take Profit trigger (must cover entry price + net profit + round-trip fee)
            if price_change_from_entry >= required_tp_gain:
                return {
                    "signal": "SELL",
                    "reason": f"Take Profit hit: up {price_change_from_entry:.2f}% from entry ${entry_price:.2f} (Required Net: +{take_profit_pct:.2f}%, incl. fees: {required_tp_gain:.2f}%)",
                    "rsi": current_rsi,
                    "volume_ratio": volume_ratio,
                    "stop_loss_pct": stop_loss_pct,
                    "take_profit_pct": take_profit_pct
                }

            # Technical Exit: Overbought RSI weakening or price falling below EMA
            # Note: We only execute technical exits if we are either locking in a profit that covers fees,
            # or if the trend is severely broken to cut losses.
            if current_rsi > 75 and current_rsi < prev['rsi']:
                # If in profit, verify it covers the fees, otherwise let trailing stop handle it unless necessary
                if price_change_from_entry > round_trip_fee_pct:
                    return {
                        "signal": "SELL",
                        "reason": f"Technical Exit: RSI overbought and reversing down ({current_rsi:.1f}). Locked net profit.",
                        "rsi": current_rsi,
                        "volume_ratio": volume_ratio,
                        "stop_loss_pct": stop_loss_pct,
                        "take_profit_pct": take_profit_pct
                    }
            
            if current_price < ema_val and prev['close'] >= prev['ema_20']:
                return {
                    "signal": "SELL",
                    "reason": "Technical Exit: Price crossed below 20-period EMA (Trend reversal)",
                    "rsi": current_rsi,
                    "volume_ratio": volume_ratio,
                    "stop_loss_pct": stop_loss_pct,
                    "take_profit_pct": take_profit_pct
                }

            return {
                "signal": "HOLD",
                "reason": f"Holding position. PnL: {price_change_from_entry:.2f}% (Peak: ${reference_price:.2f})",
                "rsi": current_rsi,
                "volume_ratio": volume_ratio,
                "stop_loss_pct": stop_loss_pct,
                "take_profit_pct": take_profit_pct
            }

        # Case 2: No active position - Check Entry Conditions (Volume Breakout & Momentum)
        else:
            # 1. Volume Breakout (volume > 1.5x average)
            volume_breakout = volume_ratio >= 1.5

            # 2. Bullish candle (close > open) and price above EMA (upward trend)
            bullish_trend = current_price > ema_val and current_price > latest['open']

            # 3. RSI in bullish momentum zone (e.g. between 50 and 70)
            rsi_bullish = 50.0 <= current_rsi <= 70.0

            # 4. Immediate positive price change
            price_increasing = current_price > prev['close']

            # Tuned Fee Guard: If current volatility (ATR) is so low that the expected Take-Profit
            # is less than 1.5x the round-trip fee (e.g. < 1.5%), we skip the trade to avoid fee drag.
            expected_gain_pct = take_profit_pct
            is_volatility_sufficient = expected_gain_pct >= (round_trip_fee_pct * 1.5)

            if volume_breakout and bullish_trend and rsi_bullish and price_increasing and is_volatility_sufficient:
                return {
                    "signal": "BUY",
                    "reason": f"Volume Breakout ({volume_ratio:.1f}x) & Bullish Momentum (RSI: {current_rsi:.1f})",
                    "rsi": current_rsi,
                    "volume_ratio": volume_ratio,
                    "stop_loss_pct": stop_loss_pct,
                    "take_profit_pct": take_profit_pct
                }

            return {
                "signal": "HOLD",
                "reason": "No entry criteria met" if is_volatility_sufficient else "Skipping entry: volatility too low relative to fees (fee drag guard)",
                "rsi": current_rsi,
                "volume_ratio": volume_ratio,
                "stop_loss_pct": stop_loss_pct,
                "take_profit_pct": take_profit_pct
            }
