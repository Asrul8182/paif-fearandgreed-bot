import os
import requests
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TOKEN = os.getenv("TELEGRAM_TOKEN")

async def get_fng():
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/"
        resp = requests.get(url, timeout=15)
        data = resp.json()
        latest = data.get("fear_and_greed_historical", [{}])[-1]
        score = latest.get("score", "N/A")
        rating = latest.get("rating", "N/A")
        return f"🧭 *Fear & Greed*: {score} ({rating})"
    except Exception as e:
        return f"❌ Gagal ambil data.\nError: {str(e)[:80]}"

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

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("fng", fng_cmd))
    app.add_handler(CommandHandler("paif", paif_cmd))

    print("Bot sedang berjalan...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
