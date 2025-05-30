import asyncio
import logging
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes, ApplicationBuilder

# === CONFIG ===
BOT_TOKEN = '7879596687:AAF_0ckeFXnX5Wgs0j93oGp0suXwgr5BTZQ'
CHAT_ID = "932734805"
SYMBOLS = {
    'S&P 500 (SPY)': 'SPY',
    'NASDAQ 100 (QQQ)': 'QQQ',
    'ACWI': 'ACWI',
    'Tech (VGT)': 'VGT',
    'China A Shares': 'ASHR',
    'Europe (IEUR)': 'IEUR',
    'Emerging Markets': 'EEM',
    'Clean Energy': 'ICLN'
}
PERIODS = [30, 60, 180, 360]

# === Logging ===
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


# === Price Fetching & Analysis ===
def fetch_low_analysis(symbol: str):
    try:
        ticker = yf.Ticker(symbol)

        full_hist = None
        for p in ["2y", "1y", "6mo"]:
            try:
                full_hist = ticker.history(period=p)
                if not full_hist.empty and 'Low' in full_hist.columns:
                    logger.info(f"✅ Successfully fetched {p} history for {symbol}")
                    break
            except Exception as e:
                logger.warning(f"⛔ Failed to fetch history with period={p} for {symbol}: {e}")

        if full_hist is None or full_hist.empty:
            logger.error(f"❌ No comprehensive history data for {symbol}")
            return None

        current_price = full_hist['Close'].iloc[-1]
        result = {'current': round(current_price, 2)}

        now = pd.Timestamp.now()
        if full_hist.index.tz is not None:
            now = now.tz_localize(full_hist.index.tz)
        else:
            now = now.tz_localize(None)

        for days in PERIODS:
            try:
                start_date = now - pd.Timedelta(days=days)
                filtered = full_hist.loc[full_hist.index >= start_date]

                if len(filtered) < int(0.65 * days):
                    logger.warning(f"⚠️ Not enough data for {symbol} - {days} days (got {len(filtered)} rows)")
                    result[f'low_{days}'] = None
                    result[f'is_low_{days}'] = None
                    result[f'low_date_{days}'] = None
                    continue

                low = filtered['Low'].min()
                low_date = filtered['Low'].idxmin().date()
                result[f'low_{days}'] = round(low, 2)
                result[f'is_low_{days}'] = current_price <= low * 1.01
                result[f'low_date_{days}'] = str(low_date)

            except Exception as e:
                logger.error(f"❌ Error in {days}-day low check for {symbol}: {e}")
                result[f'low_{days}'] = None
                result[f'is_low_{days}'] = None
                result[f'low_date_{days}'] = None

        return result
    except Exception as e:
        logger.error(f"Error fetching data for {symbol}: {e}")
        return None

def build_report():
    report = f"\U0001F4CA *Market Report - {datetime.now().strftime('%d/%m/%Y')}*\n\n"
    for name, symbol in SYMBOLS.items():
        data = fetch_low_analysis(symbol)
        if not data:
            report += f"❌ *{name}* ({symbol}): Failed to fetch data\n\n"
            continue

        report += f"\U0001F4C8 *{name}*\n"
        report += f"\U0001F4B0 Current: ${data['current']}\n"

        for days in PERIODS:
            low = data.get(f'low_{days}')
            is_low = data.get(f'is_low_{days}')
            low_date = data.get(f'low_date_{days}')
            label = f"{days}D Low"

            if low is None:
                report += f"❔ {label}: Data unavailable\n"
            elif is_low:
                report += f"🔻 *At {label}*: ${low:.2f} (on {low_date})\n"
            else:
                report += f"✅ Above {label} (${low:.2f}, low on {low_date})\n"

        report += "\n"

    report += "\U0001F4CC Note: Prices refer to ETFs tracking the indices, not the indices themselves."
    return report

# === Bot Logic ===
async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Building report...")
    report = build_report()
    await update.message.reply_text(report, parse_mode='Markdown')

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Welcome! Use /report to get the latest market low status.")

async def daily_report(bot: Bot):
    while True:
        now = datetime.now()
        if now.hour == 9 and now.minute == 0:
            report = build_report()
            await bot.send_message(chat_id=CHAT_ID, text=report, parse_mode='Markdown')
            await asyncio.sleep(60)
        await asyncio.sleep(30)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("report", report_command))
    logger.info("📡 Running bot...")
    app.run_polling()

if __name__ == "__main__":
    main()
