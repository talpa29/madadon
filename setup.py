import asyncio
import logging
from datetime import datetime, time
import yfinance as yf
import pandas as pd
from telegram import Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import pytz

# הגדרת לוגים
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ייבוא הגדרות
try:
    from config import BOT_TOKEN, CHAT_ID, SYMBOLS, DAILY_REPORT_HOUR, DAILY_REPORT_MINUTE, TIMEZONE
except ImportError:
    # הגדרות ברירת מחדל אם אין קובץ config
    BOT_TOKEN = "7879596687:AAF_0ckeFXnX5Wgs0j93oGp0suXwgr5BTZQ"
    CHAT_ID = "932734805" 
    TIMEZONE = 'Asia/Jerusalem'
    DAILY_REPORT_HOUR = 9
    DAILY_REPORT_MINUTE = 0
    SYMBOLS = {
        'S&P 500': '^GSPC',
        'NASDAQ 100': '^NDX',
        'MSCI ACWI': 'ACWI',
        'MSCI Europe': 'IEUR',
        'MSCI Emerging Markets': 'EEM',
        'China A': 'ASHR',
        'TA 125': 'TA125.TA',
        'TA 35': 'TA35.TA',
        'iShares Global Tech': 'IXN'
    }

class MarketAnalyzer:
    def __init__(self):
        self.symbols = SYMBOLS
    
    def get_market_data(self, symbol, period="1y"):
        """משיכת נתוני שוק עבור סימבול"""
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period=period)
            return data
        except Exception as e:
            logger.error(f"שגיאה בקבלת נתונים עבור {symbol}: {e}")
            return None
    
    def calculate_lows(self, data, periods=[20, 52]):
        """חישוב כמה LOW המחיר הנוכחי בתקופות שונות"""
        if data is None or data.empty:
            return {}
        
        current_price = data['Close'].iloc[-1]
        results = {'current_price': current_price}
        
        for period in periods:
            if len(data) >= period:
                # חישוב כמה ימים המחיר הנוכחי נמוך מהמחירים האחרונים
                recent_data = data['Close'].tail(period)
                lows_count = (current_price <= recent_data).sum()
                results[f'{period}_week_lows'] = lows_count
            else:
                results[f'{period}_week_lows'] = f"לא מספיק נתונים ({len(data)} ימים)"
        
        return results
    
    def analyze_all_symbols(self):
        """ניתוח כל המדדים"""
        results = {}
        
        for name, symbol in self.symbols.items():
            logger.info(f"מנתח {name} ({symbol})")
            data = self.get_market_data(symbol)
            
            if data is not None:
                analysis = self.calculate_lows(data)
                results[name] = analysis
            else:
                results[name] = {"error": "לא ניתן לקבל נתונים"}
        
        return results
    
    def format_report(self, results):
        """יצירת דוח מעוצב"""
        report = "📊 *דוח מדדים יומי*\n"
        report += f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
        
        for name, data in results.items():
            if "error" in data:
                report += f"❌ *{name}*: {data['error']}\n\n"
                continue
            
            current_price = data.get('current_price', 'N/A')
            report += f"📈 *{name}*\n"
            report += f"💰 מחיר נוכחי: {current_price:.2f}\n"
            
            if '20_week_lows' in data:
                report += f"📉 20 שבועות LOW: {data['20_week_lows']}\n"
            
            if '52_week_lows' in data:
                report += f"📉 52 שבועות LOW: {data['52_week_lows']}\n"
            
            report += "\n"
        
        return report

class TelegramBot:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.analyzer = MarketAnalyzer()
        self.application = None
        self.israel_tz = pytz.timezone(TIMEZONE)
    
    async def send_daily_report(self):
        """שליחת דוח יומי"""
        try:
            logger.info("מתחיל ניתוח יומי...")
            results = self.analyzer.analyze_all_symbols()
            report = self.analyzer.format_report(results)
            
            bot = Bot(token=self.token)
            await bot.send_message(
                chat_id=self.chat_id,
                text=report,
                parse_mode='Markdown'
            )
            logger.info("דוח יומי נשלח בהצלחה")
            
        except Exception as e:
            logger.error(f"שגיאה בשליחת דוח יומי: {e}")
    
    async def handle_report_command(self, update, context):
        """טיפול בפקודת /report"""
        try:
            await update.message.reply_text("⏳ מכין דוח מדדים...")
            
            results = self.analyzer.analyze_all_symbols()
            report = self.analyzer.format_report(results)
            
            await update.message.reply_text(report, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"שגיאה בטיפול בפקודת דוח: {e}")
            await update.message.reply_text("❌ שגיאה ביצירת הדוח")
    
    async def handle_start_command(self, update, context):
        """טיפול בפקודת /start"""
        welcome_message = """
🤖 *ברוך הבא לבוט מדדי השוק!*

הבוט ישלח דוח יומי בכל בוקר בשעה 09:00 (שעון ישראל)

*פקודות זמינות:*
📊 /report - קבלת דוח מיידי
🔄 /test - בדיקת חיבור הבוט

*המדדים שנבדקים:*
• S&P 500
• NASDAQ 100  
• MSCI ACWI
• MSCI Europe
• MSCI Emerging Markets
• China A
• TA 125
• TA 35
• iShares Global Tech

הבוט בודק כמה LOW כל מדד ב-20 ו-52 השבועות האחרונים.
        """
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
    
    async def handle_test_command(self, update, context):
        """בדיקת חיבור הבוט"""
        await update.message.reply_text("✅ הבוט פעיל ומחובר!")
    
    async def handle_message(self, update, context):
        """טיפול בהודעות טקסט רגילות"""
        message_text = update.message.text.lower()
        
        # מילות מפתח שיפעילו דוח
        trigger_words = ['דוח', 'מדדים', 'שוק', 'מחירים', 'נתונים', 'report', 'market']
        
        if any(word in message_text for word in trigger_words):
            await self.handle_report_command(update, context)
        else:
            await update.message.reply_text(
                "💡 שלח /report לקבלת דוח מיידי או /start למידע נוסף"
            )
    
    async def schedule_daily_reports(self):
        """מתזמן דוחות יומיים"""
        while True:
            try:
                now = datetime.now(self.israel_tz)
                target_time = time(9, 0)  # 09:00 בבוקר
                
                if now.time() >= target_time:
                    # אם עבר הזמן היום, קבע למחר
                    next_run = now.replace(hour=9, minute=0, second=0, microsecond=0)
                    next_run = next_run.replace(day=next_run.day + 1)
                else:
                    # אם עוד לא הגיע הזמן היום
                    next_run = now.replace(hour=9, minute=0, second=0, microsecond=0)
                
                sleep_seconds = (next_run - now).total_seconds()
                logger.info(f"הדוח הבא יישלח ב: {next_run}")
                
                await asyncio.sleep(sleep_seconds)
                await self.send_daily_report()
                
            except Exception as e:
                logger.error(f"שגיאה במתזמן: {e}")
                await asyncio.sleep(3600)  # המתן שעה במקרה של שגיאה
    
    def run(self):
        """הפעלת הבוט"""
        try:
            # יצירת Application
            self.application = Application.builder().token(self.token).build()
            
            # הוספת handlers
            self.application.add_handler(CommandHandler("start", self.handle_start_command))
            self.application.add_handler(CommandHandler("report", self.handle_report_command))
            self.application.add_handler(CommandHandler("test", self.handle_test_command))
            self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
            
            # הפעלת הבוט עם המתזמן
            async def run_bot():
                # התחלת הבוט
                await self.application.initialize()
                await self.application.start()
                
                # התחלת המתזמן
                scheduler_task = asyncio.create_task(self.schedule_daily_reports())
                
                # התחלת polling
                await self.application.updater.start_polling()
                
                # המתנה לשני המשימות
                await asyncio.gather(scheduler_task)
            
            # הפעלת הלולאה האסינכרונית
            asyncio.run(run_bot())
            
        except Exception as e:
            logger.error(f"שגיאה בהפעלת הבוט: {e}")

def main():
    """פונקציה ראשית"""
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or CHAT_ID == "YOUR_CHAT_ID_HERE":
        print("❌ אנא הגדר את BOT_TOKEN ו-CHAT_ID בתחילת הסקריפט")
        return
    
    bot = TelegramBot(BOT_TOKEN, CHAT_ID)
    logger.info("מפעיל בוט מדדי שוק...")
    bot.run()

if __name__ == "__main__":
    main()