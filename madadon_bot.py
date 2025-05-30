import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
import json
from typing import Dict, Optional, List, Tuple
import pandas as pd
import yfinance as yf
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes, ApplicationBuilder

# === CONFIG ===
BOT_TOKEN = '7879596687:AAF_0ckeFXnX5Wgs0j93oGp0suXwgr5BTZQ'
CHAT_ID = "932734805"

# Enhanced ETF list with more variety
SYMBOLS = {
    # Broad Market
    'S&P 500 (SPY)': 'SPY',
    'NASDAQ 100 (QQQ)': 'QQQ',
    'Russell 2000 (IWM)': 'IWM',
    'Total Market (VTI)': 'VTI',
    
    # International
    'ACWI': 'ACWI',
    'Europe (IEUR)': 'IEUR',
    'Emerging Markets (EEM)': 'EEM',
    'China A Shares (ASHR)': 'ASHR',
    'Japan (EWJ)': 'EWJ',
    
    # Sectors
    'Technology (VGT)': 'VGT',
    'Healthcare (VHT)': 'VHT',
    'Financials (VFH)': 'VFH',
    'Energy (VDE)': 'VDE',
    'Real Estate (VNQ)': 'VNQ',
    
    # Themes
    'Clean Energy (ICLN)': 'ICLN',
    'Cybersecurity (HACK)': 'HACK',
    'AI & Robotics (BOTZ)': 'BOTZ'
}

PERIODS = [30, 60, 180, 360]
CHANGE_THRESHOLD = 0.02  # 2% change threshold for notifications
STATE_FILE = Path("bot_state.json")

# === Enhanced Logging ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('market_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# === State Management ===
class StateManager:
    def __init__(self):
        self.state_file = STATE_FILE
        self.state = self.load_state()
    
    def load_state(self) -> Dict:
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load state: {e}")
        return {"last_prices": {}, "last_notification": "", "alerts": {}}
    
    def save_state(self):
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
    
    def update_price(self, symbol: str, price: float):
        self.state["last_prices"][symbol] = price
        self.save_state()
    
    def get_last_price(self, symbol: str) -> Optional[float]:
        return self.state["last_prices"].get(symbol)
    
    def should_send_notification(self) -> bool:
        last_notif = self.state.get("last_notification", "")
        today = datetime.now().strftime("%Y-%m-%d")
        return last_notif != today
    
    def mark_notification_sent(self):
        self.state["last_notification"] = datetime.now().strftime("%Y-%m-%d")
        self.save_state()

state_manager = StateManager()

# === Enhanced Price Fetching & Analysis ===
async def fetch_low_analysis(symbol: str) -> Optional[Dict]:
    """Fetch price data and analyze lows for different periods"""
    try:
        ticker = yf.Ticker(symbol)
        
        # Try different periods to get data
        full_hist = None
        for period in ["2y", "1y", "6mo", "3mo"]:
            try:
                full_hist = ticker.history(period=period)
                if not full_hist.empty and 'Low' in full_hist.columns and len(full_hist) > 50:
                    logger.info(f"✅ Fetched {period} history for {symbol} ({len(full_hist)} rows)")
                    break
            except Exception as e:
                logger.warning(f"Failed to fetch {period} data for {symbol}: {e}")
        
        if full_hist is None or full_hist.empty:
            logger.error(f"❌ No data available for {symbol}")
            return None
        
        current_price = full_hist['Close'].iloc[-1]
        volume = full_hist['Volume'].iloc[-1] if 'Volume' in full_hist.columns else 0
        
        result = {
            'current': round(current_price, 2),
            'volume': int(volume),
            'change_1d': 0,
            'symbol': symbol
        }
        
        # Calculate 1-day change
        if len(full_hist) >= 2:
            prev_close = full_hist['Close'].iloc[-2]
            result['change_1d'] = round(((current_price - prev_close) / prev_close) * 100, 2)
        
        # Timezone handling
        now = pd.Timestamp.now()
        if full_hist.index.tz is not None:
            now = now.tz_localize(full_hist.index.tz)
        
        # Analyze lows for different periods
        for days in PERIODS:
            try:
                start_date = now - pd.Timedelta(days=days)
                filtered = full_hist.loc[full_hist.index >= start_date]
                
                min_required_days = max(10, int(0.5 * days))  # More flexible requirement
                if len(filtered) < min_required_days:
                    logger.warning(f"Insufficient data for {symbol} {days}D: {len(filtered)} rows")
                    result[f'low_{days}'] = None
                    result[f'is_low_{days}'] = None
                    result[f'low_date_{days}'] = None
                    result[f'days_since_low_{days}'] = None
                    continue
                
                low_price = filtered['Low'].min()
                low_date = filtered['Low'].idxmin()
                days_since_low = (now.date() - low_date.date()).days
                
                # More nuanced "at low" detection (within 1.5%)
                is_at_low = current_price <= low_price * 1.015
                
                result[f'low_{days}'] = round(low_price, 2)
                result[f'is_low_{days}'] = is_at_low
                result[f'low_date_{days}'] = low_date.strftime('%Y-%m-%d')
                result[f'days_since_low_{days}'] = days_since_low
                
            except Exception as e:
                logger.error(f"Error analyzing {days}D low for {symbol}: {e}")
                result[f'low_{days}'] = None
                result[f'is_low_{days}'] = None
                result[f'low_date_{days}'] = None
                result[f'days_since_low_{days}'] = None
        
        return result
        
    except Exception as e:
        logger.error(f"Error fetching data for {symbol}: {e}")
        return None

def detect_significant_changes() -> List[Tuple[str, str, float, float]]:
    """Detect significant price changes since last check"""
    changes = []
    
    for name, symbol in SYMBOLS.items():
        try:
            ticker = yf.Ticker(symbol)
            current_data = ticker.history(period="2d")
            
            if len(current_data) < 1:
                continue
                
            current_price = current_data['Close'].iloc[-1]
            last_known_price = state_manager.get_last_price(symbol)
            
            if last_known_price is not None:
                change_pct = abs((current_price - last_known_price) / last_known_price)
                if change_pct >= CHANGE_THRESHOLD:
                    changes.append((name, symbol, last_known_price, current_price))
            
            state_manager.update_price(symbol, current_price)
            
        except Exception as e:
            logger.error(f"Error checking changes for {symbol}: {e}")
    
    return changes

async def build_report(detailed: bool = True) -> str:
    """Build comprehensive market report"""
    report = f"📊 *Market Report - {datetime.now().strftime('%d/%m/%Y %H:%M')}*\n\n"
    
    at_lows = []
    notable_moves = []
    
    for name, symbol in SYMBOLS.items():
        data = await fetch_low_analysis(symbol)
        if not data:
            if detailed:
                report += f"❌ *{name}* ({symbol}): Data unavailable\n\n"
            continue
        
        # Check if at any significant lows
        low_periods = []
        for days in PERIODS:
            if data.get(f'is_low_{days}'):
                low_periods.append(f"{days}D")
        
        if low_periods:
            at_lows.append(f"🔻 *{name}*: At {', '.join(low_periods)} low(s)")
        
        # Notable daily moves
        change_1d = data.get('change_1d', 0)
        if abs(change_1d) >= 2:  # 2%+ move
            emoji = "🟢" if change_1d > 0 else "🔴"
            notable_moves.append(f"{emoji} *{name}*: {change_1d:+.1f}%")
        
        if detailed:
            report += f"📈 *{name}* ({symbol})\n"
            report += f"💰 Current: ${data['current']} ({change_1d:+.1f}%)\n"
            
            for days in PERIODS:
                low = data.get(f'low_{days}')
                is_low = data.get(f'is_low_{days}')
                days_since = data.get(f'days_since_low_{days}')
                
                if low is None:
                    report += f"❔ {days}D: No data\n"
                elif is_low:
                    report += f"🔻 *At {days}D Low*: ${low:.2f} (today)\n"
                else:
                    report += f"✅ Above {days}D low: ${low:.2f} ({days_since}d ago)\n"
            
            report += "\n"
    
    # Summary section
    if at_lows or notable_moves:
        report += "🚨 *KEY ALERTS*\n\n"
        
        if at_lows:
            report += "💡 *At Historical Lows:*\n"
            for alert in at_lows:
                report += f"{alert}\n"
            report += "\n"
        
        if notable_moves:
            report += "📈 *Notable Moves Today:*\n"
            for move in notable_moves:
                report += f"{move}\n"
            report += "\n"
    
    if not detailed:
        report += f"\nUse /detailed for full analysis"
    
    report += "\n📝 *Note:* Prices are for ETFs tracking the indices/sectors"
    return report

# === Enhanced Bot Commands ===
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = """
🤖 *ETF Market Tracker Bot*

Commands:
/report - Quick market summary
/detailed - Full detailed report  
/alerts - Check for significant changes
/status - Bot status and stats
/help - Show this help

I'll automatically notify you of:
• ETFs hitting historical lows
• Significant price movements (>2%)
• Daily market summaries
    """
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Generating market summary...")
    try:
        report = await build_report(detailed=False)
        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in report command: {e}")
        await update.message.reply_text("❌ Failed to generate report. Please try again.")

async def detailed_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Building detailed analysis...")
    try:
        report = await build_report(detailed=True)
        # Split long messages
        if len(report) > 4000:
            parts = [report[i:i+4000] for i in range(0, len(report), 4000)]
            for part in parts:
                await update.message.reply_text(part, parse_mode='Markdown')
        else:
            await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in detailed command: {e}")
        await update.message.reply_text("❌ Failed to generate detailed report.")

async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Checking for significant changes...")
    try:
        changes = detect_significant_changes()
        
        if not changes:
            await update.message.reply_text("✅ No significant changes detected since last check.")
            return
        
        alert_msg = "🚨 *Significant Changes Detected:*\n\n"
        for name, symbol, old_price, new_price in changes:
            change_pct = ((new_price - old_price) / old_price) * 100
            emoji = "🟢" if change_pct > 0 else "🔴"
            alert_msg += f"{emoji} *{name}*\n"
            alert_msg += f"${old_price:.2f} → ${new_price:.2f} ({change_pct:+.1f}%)\n\n"
        
        await update.message.reply_text(alert_msg, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in alerts command: {e}")
        await update.message.reply_text("❌ Failed to check alerts.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = f"""
📊 *Bot Status*

🕐 Current Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📈 Tracking: {len(SYMBOLS)} ETFs
⏰ Check Intervals: Every 30 minutes
📅 Last Daily Report: {state_manager.state.get('last_notification', 'Never')}
💾 State File: {'✅ OK' if STATE_FILE.exists() else '❌ Missing'}

*Tracked ETFs:* {len(SYMBOLS)}
*Periods Analyzed:* {', '.join(map(str, PERIODS))} days
    """
    await update.message.reply_text(status_msg, parse_mode='Markdown')

# === Background Tasks ===
async def automated_monitoring():
    """Background task for continuous monitoring"""
    bot = Bot(token=BOT_TOKEN)
    
    while True:
        try:
            current_time = datetime.now()
            
            # Daily report at 9:00 AM
            if current_time.hour == 9 and current_time.minute == 0:
                if state_manager.should_send_notification():
                    logger.info("Sending daily report...")
                    report = await build_report(detailed=False)
                    await bot.send_message(chat_id=CHAT_ID, text=report, parse_mode='Markdown')
                    state_manager.mark_notification_sent()
            
            # Check for significant changes every 30 minutes during market hours
            elif current_time.hour >= 9 and current_time.hour <= 16 and current_time.minute % 30 == 0:
                changes = detect_significant_changes()
                if changes:
                    alert_msg = "🚨 *Market Alert - Significant Changes:*\n\n"
                    for name, symbol, old_price, new_price in changes:
                        change_pct = ((new_price - old_price) / old_price) * 100
                        emoji = "🟢" if change_pct > 0 else "🔴"
                        alert_msg += f"{emoji} *{name}*: {change_pct:+.1f}%\n"
                    
                    await bot.send_message(chat_id=CHAT_ID, text=alert_msg, parse_mode='Markdown')
            
            await asyncio.sleep(60)  # Check every minute
            
        except Exception as e:
            logger.error(f"Error in automated monitoring: {e}")
            await asyncio.sleep(300)  # Wait 5 minutes on error

async def main():
    """Main function to run the bot"""
    try:
        # Build application
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        
        # Add command handlers
        app.add_handler(CommandHandler("start", start_command))
        app.add_handler(CommandHandler("help", start_command))
        app.add_handler(CommandHandler("report", report_command))
        app.add_handler(CommandHandler("detailed", detailed_command))
        app.add_handler(CommandHandler("alerts", alerts_command))
        app.add_handler(CommandHandler("status", status_command))
        
        logger.info("Starting ETF Market Tracker Bot...")
        logger.info(f"Monitoring {len(SYMBOLS)} ETFs")
        logger.info(f"Sending notifications to chat ID: {CHAT_ID}")
        
        # Start background monitoring task
        monitoring_task = asyncio.create_task(automated_monitoring())
        
        # Run the bot
        async with app:
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            
            try:
                # Keep the application running
                await asyncio.gather(monitoring_task)
            except KeyboardInterrupt:
                logger.info("Received interrupt signal, shutting down...")
            finally:
                await app.updater.stop()
                await app.stop()
        
    except Exception as e:
        logger.error(f"Fatal error starting bot: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())