import os
import requests
import logging
import threading
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
    logging.warning("⚠️ SUPABASE_URL atau SUPABASE_KEY tidak dijumpai di Environment Variables.")

# ==================== Flask (untuk Render) ====================
app_flask = Flask(__name__)

@app_flask.route("/")
def home():
    return "PAIF Fear & Greed Bot is running!"

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

def get_paif_nav():
    try:
        url = "https://www.investing.com/funds/public-asia-ittikal-fund"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
        
    except Exception as e:
        print(f"PAIF Investing.com error: {e}")
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
            if historical:
                fng_data = historical[-1]

        score = round(fng_data.get("score", 0))
        rating = fng_data.get("rating", "N/A").title()

        # 2. Asia Indices
        hsi = get_yahoo_change("^HSI")
        klci = get_yahoo_change("^KLSE")

        hsi_text = f"{hsi:+.2f}%" if hsi is not None else "N/A"
        klci_text = f"{klci:+.2f}%" if klci is not None else "N/A"

        # 3. PAIF NAV
        date, nav, change = get_paif_nav()
        if nav:
            paif_text = f"• PAIF NAV   : RM {nav}  {change}\n  (Tarikh: {date})"
        else:
            paif_text = "• PAIF NAV   : Tidak tersedia buat masa ini"

        # 4. Cadangan
        if score <= 25:
            advice = "Extreme Fear → Pertimbang **beli** PAIF"
        elif score <= 45:
            advice = "Fear → Boleh beli secara berperingkat"
        elif score <= 55:
            advice = "Neutral → Hold / pantau"
        elif score <= 75:
            advice = "Greed → Lebih berhati-hati"
        else:
            advice = "Extreme Greed → Pertimbang kurangkan / switch"

        msg = (
            f"🧭 *Fear & Greed*: {score} ({rating})\n\n"
            f"*Asia Market Snapshot:*\n"
            f"• Hang Seng : {hsi_text}\n"
            f"• KLCI      : {klci_text}\n\n"
            f"*PAIF:*\n{paif_text}\n\n"
            f"*Cadangan:*\n{advice}"
        )
        return msg

    except Exception as e:
        return f"❌ Gagal ambil data.\nError: {str(e)[:120]}"

# ==================== Telegram Commands ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Rekod pengguna ke pangkalan data Supabase
    if supabase:
        try:
            user_data = {
                "telegram_id": user.id,
                "first_name": user.first_name or "",
                "username": user.username or ""
            }
            # upsert bermaksud: jika ID sudah ada, update. Jika belum, tambah rekod baharu.
            supabase.table("users").upsert(user_data).execute()
        except Exception as e:
            logging.error(f"Gagal simpan data user ke Supabase: {e}")

    await update.message.reply_text(
        "✅ *PAIF Fear & Greed Bot Aktif!*\n\n"
        "/fng  - Fear & Greed + Asia + PAIF NAV\n"
        "/paif - Info ringkas PAIF",
        parse_mode="Markdown"
    )

async def fng_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await get_fng()
    await update.message.reply_text(msg, parse_mode="Markdown")

async def paif_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📊 *Public Asia Ittikal Fund (PAIF)*\n\n"
        "• Fund Shariah-compliant Asia Equity\n"
        "• Prestasi 1 tahun lepas sangat kukuh\n"
        "• Gunakan /fng untuk timing sentiment",
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

    print("Bot sedang berjalan...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
