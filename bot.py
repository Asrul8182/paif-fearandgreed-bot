import os
import requests
import logging
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TOKEN = os.getenv("TELEGRAM_TOKEN")
PORT = int(os.environ.get("PORT", 10000))

# Dummy Flask server
app_flask = Flask(__name__)

@app_flask.route("/")
def home():
    return "PAIF Fear & Greed Bot is running!"

def run_flask():
    app_flask.run(host="0.0.0.0", port=PORT, use_reloader=False, debug=False)

def get_yahoo_change(symbol):
    """Ambil % change hari ini dari Yahoo Finance"""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        
        result = data["chart"]["result"][0]
        closes = result["indicators"]["quote"][0]["close"]
        
        if len(closes) >= 2 and closes[-1] and closes[-2]:
            change = ((closes[-1] - closes[-2]) / closes[-2]) * 100
            return round(change, 2)
        return None
    except:
        return None

async def get_fng():
    try:
        # 1. Fear & Greed
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
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
        hsi = get_yahoo_change("^HSI")      # Hang Seng
        klci = get_yahoo_change("^KLSE")    # KLCI
        
        hsi_text = f"{hsi:+.2f}%" if hsi is not None else "N/A"
        klci_text = f"{klci:+.2f}%" if klci is not None else "N/A"
        
        # 3. Cadangan ringkas
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
            f"*Cadangan PAIF:*\n{advice}"
        )
        return msg
        
    except Exception as e:
        return f"❌ Gagal ambil data.\nError: {str(e)[:120]}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ *PAIF Fear & Greed Bot Aktif!*\n\n"
        "/fng - Fear & Greed + Asia Snapshot\n"
        "/paif - Info PAIF",
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
