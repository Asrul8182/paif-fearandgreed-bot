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

# Ambil NAV dari Supabase (Versi Log Sejarah)
def get_paif_nav_from_db():
    if supabase:
        try:
            # Ambil rekod paling terbaharu berdasarkan 'created_at'
            res = supabase.table("paif_nav").select("*").order("created_at", desc=True).limit(1).execute()
            
            if res.data:
                nav = res.data[0].get("nav")
                tarikh = res.data[0].get("tarikh")
                masa = res.data[0].get("masa")
                nota = res.data[0].get("nota")
                
                # Cantumkan info untuk dipaparkan
                info_str = f"{tarikh} {masa}"
                if nota:
                    info_str += f"\n  (Nota: {nota})"
                    
                return f"{nav:.4f}", info_str
        except Exception as e:
            logging.error(f"Error baca NAV dari DB: {e}")
    return None, None

# Backup: Ambil dari Web (Jika DB tiada data)
def get_paif_nav_web():
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
        print(f"PAIF Web error: {e}")
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

        # 3. PAIF NAV (Sistem Hibrid - DB diutamakan)
        nav_db, info_db = get_paif_nav_from_db()
        if nav_db:
             paif_text = f"• PAIF NAV   : RM {nav_db}\n  (Dikemas kini: {info_db})"
        else:
            # Guna Web Scraper sebagai sandaran jika DB kosong
            date_web, nav_web, change_web = get_paif_nav_web()
            if nav_web:
                paif_text = f"• PAIF NAV   : RM {nav_web}  {change_web}\n  (Sumber Auto: {date_web})"
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
    
    if supabase:
        try:
            user_data = {
                "telegram_id": user.id,
                "first_name": user.first_name or "",
                "username": user.username or ""
            }
            # Jika table 'users' tiada, kod ini diabaikan dengan selamat
            supabase.table("users").upsert(user_data).execute()
        except Exception:
            pass

    await update.message.reply_text(
        "✅ *PAIF Fear & Greed Bot Aktif!*\n\n"
        "/fng  - Lihat bacaan semasa F&G\n"
        "/setnav [harga] [nota opsional] - Update NAV manual\n"
        "/paif - Info ringkas PAIF",
        parse_mode="Markdown"
    )

# Fungsi kemas kini selari dengan schema 'paif_nav' anda
async def setnav_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Sila masukkan harga NAV.\n*Contoh:* `/setnav 0.3541` atau `/setnav 0.3541 HSI jatuh hari ini`", 
            parse_mode="Markdown"
        )
        return

    try:
        new_nav = float(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Sila pastikan NAV adalah dalam format nombor/perpuluhan.")
        return
        
    # Ambil teks selepas harga sebagai nota (jika ada)
    nota_str = " ".join(context.args[1:]) if len(context.args) > 1 else ""
    
    # Kira Waktu Malaysia (UTC + 8 jam)
    my_time = datetime.utcnow() + timedelta(hours=8)
    tarikh_str = my_time.strftime("%d-%m-%Y")
    masa_str = my_time.strftime("%I:%M %p")

    if supabase:
        try:
            # Insert data baharu sebagai log (id dan created_at diuruskan oleh Supabase)
            data = {
                "tarikh": tarikh_str,
                "masa": masa_str,
                "nav": new_nav,
                "nota": nota_str
            }
            supabase.table("paif_nav").insert(data).execute()
            
            # Balasan berserta nota (jika ada)
            reply_msg = (
                f"✅ *NAV PAIF Berjaya Disimpan!*\n\n"
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
        "• Gunakan /fng untuk timing sentiment\n"
        "• Gunakan /setnav untuk kemas kini harga",
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
