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
import requests
# === CONFIG ===
# Multiple chat IDs for notifications
from config import CHAT_ID, BOT_TOKEN, BARANOV_CHAT_ID, TWELVEDATD_API_KEY

CHAT_IDS = [
    CHAT_ID,        # Your original chat ID
    BARANOV_CHAT_ID,      # Add second user's chat ID here
    # "CHAT_ID_3",      # Add third user's chat ID here
]

# Enhanced ETF list with more variety
SYMBOLS = {
    # Broad Market
    'S&P 500 (SPY)': 'SPY',
    'NASDAQ 100 (QQQ)': 'QQQ',
    'Russell 2000 (IWM)': 'IWM',
    'Total Market (VTI)': 'VTI',

    # Israel 
    'Tel Aviv 125': '^TA125.TA',
    'Tel Aviv 35': 'TA35.TA',
    'TA Banks-5': 'TA-BANKS.TA',


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
        today = datetime.now().strftime("%Y-%m-%d")
        if "price_history" not in self.state:
            self.state["price_history"] = {}

        if symbol not in self.state["price_history"]:
            self.state["price_history"][symbol] = {}

        self.state["price_history"][symbol][today] = price
        self.state["last_prices"][symbol] = price  # still keep quick access
        self.save_state()
    
    def get_price_history(self, symbol: str) -> Dict[str, float]:
        return self.state.get("price_history", {}).get(symbol, {})

    def get_last_price(self, symbol: str) -> Optional[float]:
        return self.state["last_prices"].get(symbol)
    
    def should_send_notification(self) -> bool:
        last_notif = self.state.get("last_notification", "")
        today = datetime.now().strftime("%Y-%m-%d")
        return last_notif != today
    
    def mark_notification_sent(self):
        self.state["last_notification"] = datetime.now().strftime("%Y-%m-%d")
        self.save_state()
    
    def add_user(self, chat_id: str, username: str = "Unknown"):
        """Add a new user to receive notifications"""
        if "users" not in self.state:
            self.state["users"] = {}
        self.state["users"][chat_id] = {
            "username": username,
            "added_date": datetime.now().isoformat(),
            "active": True
        }
        self.save_state()
    
    def get_active_users(self) -> List[str]:
        """Get list of active user chat IDs"""
        users = self.state.get("users", {})
        active_users = [chat_id for chat_id, info in users.items() if info.get("active", True)]
        # Include original CHAT_IDS for backward compatibility
        return list(set(CHAT_IDS + active_users))
    
    def remove_user(self, chat_id: str):
        """Deactivate a user from receiving notifications"""
        if "users" in self.state and chat_id in self.state["users"]:
            self.state["users"][chat_id]["active"] = False
            self.save_state()

async def send_to_all_users(bot: Bot, message: str, parse_mode: str = 'Markdown'):
    """Send message to all active users"""
    active_users = state_manager.get_active_users()
    sent_count = 0
    failed_count = 0
    
    for chat_id in active_users:
        try:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode=parse_mode)
            sent_count += 1
            logger.info(f"Message sent successfully to {chat_id}")
        except Exception as e:
            failed_count += 1
            logger.error(f"Failed to send message to {chat_id}: {e}")
    
    logger.info(f"Message delivery: {sent_count} successful, {failed_count} failed")
    return sent_count, failed_count

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Please provide a symbol. Example: `/history SPY`", parse_mode='Markdown')
        return

    symbol = context.args[0].upper()
    history = state_manager.get_price_history(symbol)

    if not history:
        await update.message.reply_text(f"No history found for {symbol}.", parse_mode='Markdown')
        return

    # Sort by date
    sorted_history = sorted(history.items())
    message = f"*Price history for {symbol}:*\n"
    for date, price in sorted_history[-10:]:  # Show last 10
        message += f"{date}: ${price:.2f}\n"

    await update.message.reply_text(message, parse_mode='Markdown')


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

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Subscribe user to notifications"""
    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username or update.effective_user.first_name or "Unknown"
    
    state_manager.add_user(chat_id, username)
    
    await update.message.reply_text(
        f"✅ *Subscribed Successfully!*\n\n"
        f"👤 User: @{username}\n"
        f"🆔 Chat ID: {chat_id}\n\n"
        f"You will now receive:\n"
        f"• 📅 Daily market reports at 9:00 AM\n"
        f"• 🚨 Real-time alerts for significant changes\n"
        f"• 📊 Historical low notifications\n\n"
        f"Use /unsubscribe to stop notifications",
        parse_mode='Markdown'
    )

async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unsubscribe user from notifications"""
    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username or update.effective_user.first_name or "Unknown"
    
    state_manager.remove_user(chat_id)
    
    await update.message.reply_text(
        f"❌ *Unsubscribed*\n\n"
        f"👤 User: @{username}\n"
        f"You will no longer receive automatic notifications.\n\n"
        f"Use /subscribe to re-enable notifications",
        parse_mode='Markdown'
    )

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all subscribed users (admin only)"""
    chat_id = str(update.effective_chat.id)
    
    # Only allow original admin to see user list
    if chat_id not in CHAT_IDS:
        await update.message.reply_text("❌ Admin access required")
        return
    
    active_users = state_manager.get_active_users()
    users_info = state_manager.state.get("users", {})
    
    user_list = f"👥 *Subscribed Users* ({len(active_users)} total)\n\n"
    
    for i, user_chat_id in enumerate(active_users, 1):
        user_info = users_info.get(user_chat_id, {})
        username = user_info.get("username", "Unknown")
        added_date = user_info.get("added_date", "Unknown")
        
        if added_date != "Unknown":
            try:
                date_obj = datetime.fromisoformat(added_date.replace('Z', '+00:00'))
                added_date = date_obj.strftime("%Y-%m-%d")
            except:
                pass
        
        user_list += f"{i}. @{username}\n"
        user_list += f"   🆔 {user_chat_id}\n"
        user_list += f"   📅 Added: {added_date}\n\n"
    
    await update.message.reply_text(user_list, parse_mode='Markdown')

async def test_alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test sending alerts to all users"""
    chat_id = str(update.effective_chat.id)
    
    # Only allow original admin to test
    if chat_id not in CHAT_IDS:
        await update.message.reply_text("❌ Admin access required")
        return
    
    await update.message.reply_text("🧪 Sending test alert to all subscribed users...")
    
    test_message = f"""
🧪 *TEST ALERT - ETF Market Bot*

📅 Test Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

This is a test message to verify that notifications are working correctly.

✅ If you received this message, you're successfully subscribed to:
• Daily market reports (9:00 AM)
• Real-time price alerts
• Historical low notifications

🤖 Bot Status: Operational
📊 Monitoring: {len(SYMBOLS)} ETFs
    """
    
    bot = context.bot
    sent_count, failed_count = await send_to_all_users(bot, test_message)
    
    result_msg = f"📊 *Test Results*\n\n"
    result_msg += f"✅ Successfully sent: {sent_count}\n"
    result_msg += f"❌ Failed to send: {failed_count}\n"
    result_msg += f"👥 Total subscribers: {len(state_manager.get_active_users())}"
    
    await update.message.reply_text(result_msg, parse_mode='Markdown')

async def test_9am_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test the 9 AM daily report"""
    chat_id = str(update.effective_chat.id)
    
    # Only allow original admin to test
    if chat_id not in CHAT_IDS:
        await update.message.reply_text("❌ Admin access required")
        return
    
    await update.message.reply_text("🧪 Generating and sending test 9 AM report to all users...")
    
    try:
        # Generate the daily report
        report = await build_report(detailed=False)
        test_report = f"🧪 *TEST - Daily Market Report*\n\n{report}\n\n_This was a test of the 9 AM daily alert system_"
        
        # Send to all users
        bot = context.bot
        sent_count, failed_count = await send_to_all_users(bot, test_report)
        
        result_msg = f"📊 *9 AM Test Results*\n\n"
        result_msg += f"✅ Report sent to: {sent_count} users\n"
        result_msg += f"❌ Failed deliveries: {failed_count}\n"
        result_msg += f"👥 Total subscribers: {len(state_manager.get_active_users())}"
        
        await update.message.reply_text(result_msg, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in 9 AM test: {e}")
        await update.message.reply_text(f"❌ Test failed: {str(e)}")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    active_users = state_manager.get_active_users()
    status_msg = f"""
📊 *Bot Status*

🕐 Current Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📈 Tracking: {len(SYMBOLS)} ETFs
👥 Active Users: {len(active_users)}
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
                    logger.info("Sending daily report to all users...")
                    report = await build_report(detailed=False)
                    await send_to_all_users(bot, report, parse_mode='Markdown')
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
                    
                    await send_to_all_users(bot, alert_msg, parse_mode='Markdown')
            
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
        app.add_handler(CommandHandler("test", test_alert_command))
        app.add_handler(CommandHandler("test9am", test_9am_command))
        app.add_handler(CommandHandler("subscribe", subscribe_command))
        app.add_handler(CommandHandler("unsubscribe", unsubscribe_command))
        app.add_handler(CommandHandler("users", users_command))
        app.add_handler(CommandHandler("history", history_command))

        
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