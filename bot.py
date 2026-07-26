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
    return "PAIF Fear & Greed Bot (Pro Technical) is running!"

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

def calculate_rsi(prices):
    if len(prices) < 2: 
        return 50.0
    
    gains = []
    losses = []
    
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
            
    avg_gain = sum(gains) / len(gains)
    avg_loss = sum(losses) / len(losses)
    
    if avg_loss == 0:
        return 100.0
        
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 1)

# Ambil NAV & Kira Enjin Teknikal Penuh
def get_paif_nav_from_db():
    if supabase:
        try:
            # Ambil sejarah lengkap (untuk mendapatkan ATH, ATL, dan trend)
            res = supabase.table("paif_nav").select("*").order("id", desc=True).execute()
            
            if res.data:
                records = res.data
                all_navs = [float(r.get("nav")) for r in records if r.get("nav") is not None]
                
                if not all_navs:
                    return None
                    
                latest_nav = all_navs[0]
                tarikh = records[0].get("tarikh")
                masa = records[0].get("masa")
                nota = records[0].get("nota")
                
                # 1. ATH, ATL & Zon Struktur Pasaran (Premium/Discount)
                ath = max(all_navs)
                atl = min(all_navs)
                midpoint = atl + ((ath - atl) / 2)
                
                if latest_nav < midpoint:
                    zone_str = "🟢 DISCOUNT (Bawah 50%)"
                else:
                    zone_str = "🔴 PREMIUM (Atas 50%)"
                
                # 2. RSI 14-Hari (Ambil 15 harga terakhir, susun lama ke baharu)
                prices_for_rsi = all_navs[:15][::-1] if len(all_navs) >= 15 else all_navs[::-1]
                rsi_val = calculate_rsi(prices_for_rsi)
                
                if rsi_val <= 30:
                    rsi_status = "Oversold"
                elif rsi_val >= 70:
                    rsi_status = "Overbought"
                else:
                    rsi_status = "Neutral"
                    
                # 3. Perubahan Sejarah (1W = 5 hari bekerja, 1M = 22 hari bekerja)
                chg_1w = ((latest_nav - all_navs[5]) / all_navs[5]) * 100 if len(all_navs) > 5 else 0
                chg_1m = ((latest_nav - all_navs[21]) / all_navs[21]) * 100 if len(all_navs) > 21 else 0
                
                # Cantumkan info masa
                info_str = f"{tarikh} {masa}"
                if nota:
                    info_str += f" ({nota})"
                    
                return latest_nav, info_str, rsi_val, rsi_status, zone_str, ath, chg_1w, chg_1m
                
        except Exception as e:
            logging.error(f"Error baca NAV dari DB: {e}")
    return None

def get_paif_nav_web():
    try:
        url = "https://www.investing.com/funds/public-asia-ittikal-fund"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            price_tag = soup.select_one('[data-test="instrument-price-last"]')
            if price_tag:
                return "Investing.com", price_tag.get_text(strip=True)
    except:
        pass
    return None, None

# ==================== Main F&G Function ====================
async def get_fng():
    try:
        # 1. CNN Fear & Greed (Bakal digantikan dengan Indeks Asia kelak)
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            fng_data = data.get("fear_and_greed", {})
            if not fng_data: fng_data = data.get("fear_and_greed_historical", [{}])[-1]
            score = round(fng_data.get("score", 0))
            rating = fng_data.get("rating", "N/A").title()
        else:
            score, rating = 50, "Sistem Dalam Penyelenggaraan"

        # 2. Asia Indices Snapshot
        hsi = get_yahoo_change("^HSI")
        klci = get_yahoo_change("^KLSE")
        hsi_text = f"{hsi:+.2f}%" if hsi is not None else "N/A"
        klci_text = f"{klci:+.2f}%" if klci is not None else "N/A"

        # 3. Pengiraan Teknikal Pro
        db_result = get_paif_nav_from_db()
        
        if db_result:
            nav_db, info_db, rsi_val, rsi_status, zone_str, ath, chg_1w, chg_1m = db_result
            drawdown = ((nav_db - ath) / ath) * 100 if ath else 0
            
            paif_text = (
                f"• Semasa     : *RM {nav_db:.4f}*\n"
                f"• Momentum   : {rsi_val} (RSI - {rsi_status})\n"
                f"• Zon Pasaran: {zone_str}\n"
                f"• Perubahan  : {chg_1w:+.2f}% (1W) / {chg_1m:+.2f}% (1M)\n"
                f"• ATH (High) : RM {ath:.4f} ({drawdown:+.2f}%)\n"
                f"  🗓 *{info_db}*"
            )
        else:
            _, nav_web = get_paif_nav_web()
            paif_text = f"• PAIF NAV: RM {nav_web}" if nav_web else "• PAIF NAV: Tidak tersedia"
            rsi_val, nav_db, zone_str = 50, None, ""

        # 4. Enjin Cadangan 
        if score <= 30 and "DISCOUNT" in zone_str and rsi_val <= 40:
            advice = "🔥 **PERFECT BUY / STRONG DCA**\nFear ekstrem, harga di zon Discount & Momentum mula Oversold. Peluang keemasan."
        elif score <= 45 and "DISCOUNT" in zone_str:
            advice = "🛒 **BUY (Accumulate)**\nHarga sangat cantik di zon diskaun. Boleh mula kumpul lot."
        elif "PREMIUM" in zone_str and rsi_val >= 70:
            advice = "⚠️ **CAUTION / TAKE PROFIT**\nHarga di zon Premium dan Momentum terlalu panas (Overbought). Tunggu harga reda."
        else:
            advice = "⚖️ **NEUTRAL / HOLD**\nPasaran sedang mencari arah (sideway). Teruskan memantau pergerakan harga dan sentimen."

        msg = (
            f"🧭 *Fear & Greed (Global)*: {score} ({rating})\n\n"
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
        "✅ *PAIF Pro Bot Aktif!*\n\n"
        "/fng  - Analisis Teknikal (RSI, Zon Pasaran, Prestasi)\n"
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
            
            await update.message.reply_text(f"✅ NAV RM {new_nav:.4f} berjaya disimpan!", parse_mode="Markdown")
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
        "• Enjin Teknikal: RSI 14-Hari, Premium/Discount Zones, ATH Drawdown.\n"
        "• Data memori pasaran memuatkan lebih 600 rekod dagangan.",
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
