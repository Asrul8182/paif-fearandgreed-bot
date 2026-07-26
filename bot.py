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

# Dummy Flask server supaya Render happy
app_flask = Flask(__name__)

@app_flask.route("/")
def home():
    return "PAIF Fear & Greed Bot is running!"

def run_flask():
    # Ditambah use_reloader=False supaya Flask tidak crash dalam thread
    app_flask.run(host="0.0.0.0", port=PORT, use_reloader=False, debug=False)

async def get_fng():
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
        
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code != 200:
            return f"❌ Server CNN balas kod: {resp.status_code}"
            
        data = resp.json()
        
        # Cuba beberapa kemungkinan struktur data CNN
        fng_data = data.get("fear_and_greed") or data.get("fearAndGreed")
        
        if fng_data:
            score = round(fng_data.get("score", 0))
            rating = fng_data.get("rating", "N/A").title()
            return f"🧭 *Fear & Greed*: {score} ({rating})"
        
        # Fallback: ambil dari historical (cara lama)
        historical = data.get("fear_and_greed_historical") or data.get("fearAndGreedHistorical")
        if historical and len(historical) > 0:
            latest = historical[-1]
            score = round(latest.get("score", 0))
            rating = latest.get("rating", "N/A").title()
            return f"🧭 *Fear & Greed*: {score} ({rating})"
        
        # Jika masih gagal, tunjuk sebahagian data untuk debug
        return f"❌ Struktur data tidak dikenali.\nKeys: {list(data.keys())[:5]}"
        
    except Exception as e:
        return f"❌ Gagal ambil data.\nError: {str(e)[:120]}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ *PAIF Fear & Greed Bot Aktif!*\n\n"
        "/fng - Lihat Fear & Greed Index\n"
        "/paif - Info PAIF",
        parse_mode="Markdown"
    )

async def fng_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await get_fng()
    await update.message.reply_text(msg, parse_mode="Markdown")

async def paif_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📊 *Public Asia Ittikal Fund (PAIF)*\n\n"
        "Fund Shariah-compliant Asia Equity.\n"
        "Gunakan /fng untuk timing sentiment.",
        parse_mode="Markdown"
    )

def main():
    if not TOKEN:
        print("ERROR: TELEGRAM_TOKEN tidak dijumpai!")
        return

    # Jalankan Flask di thread berasingan
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("fng", fng_cmd))
    app.add_handler(CommandHandler("paif", paif_cmd))

    print("Bot sedang berjalan...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
