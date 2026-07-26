import os
import requests
import logging
import threading
from datetime import datetime, timedelta
from flask import Flask
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Import Supabase
from supabase import create_client, Client

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TOKEN = os.getenv("TELEGRAM_TOKEN")
PORT = int(os.environ.get("PORT", 10000))

# ==================== Supabase Setup ====================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = None

if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    logging.info("✅ Berjaya berhubung dengan Supabase!")
else:
    logging.warning("⚠️ SUPABASE_URL atau SUPABASE_KEY tidak dijumpai.")

# ==================== Flask (untuk Render) ====================
app_flask = Flask(__name__)

@app_flask.route("/")
def home():
    return "PAIF Fear & Greed Bot (Hybrid ATH) is running!"

def run_flask():
    app_flask.run(host="0.0.0.0", port=PORT, use_reloader=False, debug=False)

# ==================== Helper Functions ====================
def get_yahoo_change(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        if len(closes) >= 2 and closes[-1] and closes[-2]:
            change = ((closes[-1] - closes[-2]) / closes[-2]) * 100
            return round(change, 2)
        return None
    except:
        return None

# Ambil NAV dari Supabase + Kiraan Analisis Teknikal (MA, Support & All-Time High)
def get_paif_nav_from_db():
    if supabase:
        try:
            # 1. Ambil 30 rekod terbaharu untuk pengiraan Moving Average & Support Semasa
            res = supabase.table("paif_nav").select("*").order("id", desc=True).limit(30).execute()
            
            # 2. Carian khas: Ambil Harga Tertinggi dalam sejarah (All-Time High)
            res_ath = supabase.table("paif_nav").select("nav").order("nav", desc=True).limit(1).execute()
            
            ath = None
            if res_ath.data:
                ath = float(res_ath.data[0].get("nav"))
            
            if res.data:
                records = res.data
                latest_nav = float(records[0].get("nav"))
                tarikh = records[0].get("tarikh")
                masa = records[0].get("masa")
                nota = records[0].get("nota")
                
                # Ekstrak semua harga 30 hari untuk pengiraan teknikal
                navs = [float(r.get("nav")) for r in records if r.get("nav") is not None]
                
                # Kira Moving Average & Support 30-Hari
                ma_14 = sum(navs[:14]) / len(navs[:14]) if len(navs) >= 14 else sum(navs) / len(navs)
                ma_30 = sum(navs) / len(navs)
                support_30 = min(navs)
                
                # Cantumkan info untuk dipaparkan
                info_str = f"{tarikh} {masa}"
                if nota:
                    info_str += f"\n  (Nota: {nota})"
                    
                return latest_nav, info_str, ma_14, ma_30, support_30, ath
        except Exception as e:
            logging.error(f"Error baca NAV dari DB: {e}")
    return None, None, None, None, None, None

def get_paif_nav_web():
    try:
        url = "https://www.investing.com/funds/public-asia-ittikal-fund"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code != 200:
            return None, None, None

        soup = BeautifulSoup(resp.text, "html.parser")
        price_tag = soup.select_one('[data-test="instrument-price-last"]')
        change_tag = soup.select_one('[data-test="instrument-price-change"]')
        percent_tag = soup.select_one('[data-test="instrument-price-change-percent"]')
        
        nav = price_tag.get_text(strip=True) if price_tag else None
        change = change_tag.get_text(strip=True) if change_tag else ""
        percent = percent_tag.get_text(strip=True) if percent_tag else ""
        
        if nav:
            return "Investing.com", nav, f"{change} {percent}".strip()
        return None, None, None
    except Exception:
        return None, None, None

# ==================== Main F&G Function ====================
async def get_fng():
    try:
        # 1. CNN Fear & Greed
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=15)

        if resp.status_code != 200:
            return f"❌ Gagal ambil F&G (kod {resp.status_code})"

        data = resp.json()
        fng_data = data.get("fear_and_greed") or {}
        if not fng_data:
            historical = data.get("fear_and_greed_historical", [])
            if historical: fng_data = historical[-1]

        score = round(fng_data.get("score", 0))
        rating = fng_data.get("rating", "N/A").title()

        # 2. Asia Indices
        hsi = get_yahoo_change("^HSI")
        klci = get_yahoo_change("^KLSE")

        hsi_text = f"{hsi:+.2f}%" if hsi is not None else "N/A"
        klci_text = f"{klci:+.2f}%" if klci is not None else "N/A"

        # 3. PAIF NAV (Sistem Analisis Teknikal ATH)
        nav_db, info_db, ma_14, ma_30, support_30, ath = get_paif_nav_from_db()
        
        if nav_db is not None:
            # Kira Drawdown (Peratusan kejatuhan dari harga All-Time High)
            drawdown = ((nav_db - ath) / ath) * 100 if ath else 0
            
            paif_text = (
                f"• Semasa     : *RM {nav_db:.4f}*\n"
                f"• MA 14-Hari : RM {ma_14:.4f}\n"
                f"• MA 30-Hari : RM {ma_30:.4f}\n"
                f"• Support 30D: RM {support_30:.4f}\n"
                f"• ATH (High) : RM {ath:.4f}\n"
                f"• Drawdown   : {drawdown:+.2f}%\n"
                f"  (Kemas kini: {info_db})"
            )
        else:
            date_web, nav_web, change_web = get_paif_nav_web()
            if nav_web:
                paif_text = f"• PAIF NAV   : RM {nav_web}  {change_web}\n  (Sumber Auto: {date_web})"
            else:
                paif_text = "• PAIF NAV   : Tidak tersedia buat masa ini"

        # 4. Enjin Logik Cadangan Hibrid (F&G + Teknikal)
        if score <= 25:
            if nav_db and nav_db <= ma_30:
                advice = "🔥 **STRONG BUY**\nExtreme Fear + Harga di bawah MA30. Peluang kumpul aset (DCA) yang sangat baik di zon murah."
            else:
                advice = "Extreme Fear → Sentimen amat takut. Pertimbang beli berperingkat."
                
        elif score <= 45:
            if nav_db and nav_db <= (support_30 * 1.01): # Harga berhampiran zon support
                advice = "🛒 **BUY (Support Test)**\nSentimen Fear dan harga kini sedang menguji paras sokongan 30-hari!"
            elif nav_db and nav_db <= ma_14:
                advice = "🛒 **BUY**\nSentimen Fear + Harga di bawah MA14. Momen sesuai untuk mula kumpul."
            else:
                advice = "Fear → Sentimen sedang menurun, pantau pergerakan harga."
                
        elif score <= 55:
            advice = "Neutral → Hold / pantau pasaran. Tiada arah yang jelas."
            
        elif score <= 75:
            if nav_db and nav_db >= ma_30:
                advice = "⚠️ **BERJAGA-JAGA**\nGreed + Harga di atas purata 30-hari (Premium). Jangan kejar harga (FOMO)."
            else:
                advice = "Greed → Pasaran mula tamak. Lebih berhati-hati."
                
        else:
            advice = "🛑 **STRONG SELL / TAKE PROFIT**\nExtreme Greed! Pasaran terlalu panas, pertimbang untuk switch dana atau kurangkan pendedahan."

        msg = (
            f"🧭 *Fear & Greed*: {score} ({rating})\n\n"
            f"*Asia Market Snapshot:*\n"
            f"• Hang Seng : {hsi_text}\n"
            f"• KLCI      : {klci_text}\n\n"
            f"*Data Teknikal PAIF:*\n{paif_text}\n\n"
            f"*Cadangan Sistem:*\n{advice}"
        )
        return msg

    except Exception as e:
        return f"❌ Gagal ambil data.\nError: {str(e)[:120]}"

# ==================== Telegram Commands ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if supabase:
        try:
            user_data = {
                "telegram_id": user.id,
                "first_name": user.first_name or "",
                "username": user.username or ""
            }
            supabase.table("users").upsert(user_data).execute()
        except Exception:
            pass

    await update.message.reply_text(
        "✅ *PAIF Hybrid Bot Aktif!*\n\n"
        "/fng  - Analisis Hibrid F&G + Sentimen MA\n"
        "/setnav [harga] [nota opsional] - Update NAV manual\n"
        "/paif - Info ringkas PAIF",
        parse_mode="Markdown"
    )

async def setnav_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Sila masukkan harga NAV.\n*Contoh:* `/setnav 0.8123`", 
            parse_mode="Markdown"
        )
        return

    try:
        new_nav = float(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Sila pastikan NAV adalah dalam format nombor/perpuluhan.")
        return
        
    nota_str = " ".join(context.args[1:]) if len(context.args) > 1 else ""
    
    my_time = datetime.utcnow() + timedelta(hours=8)
    tarikh_str = my_time.strftime("%d-%m-%Y")
    masa_str = my_time.strftime("%I:%M %p")

    if supabase:
        try:
            data = {
                "tarikh": tarikh_str,
                "masa": masa_str,
                "nav": new_nav,
                "nota": nota_str
            }
            supabase.table("paif_nav").insert(data).execute()
            
            reply_msg = (
                f"✅ *NAV Berjaya Disimpan!*\n\n"
                f"• Harga: RM {new_nav:.4f}\n"
                f"• Tarikh: {tarikh_str} ({masa_str})"
            )
            if nota_str:
                reply_msg += f"\n• Nota: {nota_str}"
                
            await update.message.reply_text(reply_msg, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Gagal simpan ke database: {e}")
    else:
        await update.message.reply_text("❌ Database belum disambungkan.")

async def fng_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await get_fng()
    await update.message.reply_text(msg, parse_mode="Markdown")

async def paif_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📊 *Public Asia Ittikal Fund (PAIF)*\n\n"
        "• Fund Shariah-compliant Asia Equity\n"
        "• Bot ini menggunakan analisis purata (MA) untuk mengukur struktur harga.",
        parse_mode="Markdown"
    )

# ==================== Main ====================
def main():
    if not TOKEN:
        print("ERROR: TELEGRAM_TOKEN tidak dijumpai!")
        return

    threading.Thread(target=run_flask, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("fng", fng_cmd))
    app.add_handler(CommandHandler("paif", paif_cmd))
    app.add_handler(CommandHandler("setnav", setnav_cmd))

    print("Bot sedang berjalan...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
