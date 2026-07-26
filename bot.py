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

# ==================== Flask ====================
app_flask = Flask(__name__)

@app_flask.route("/")
def home():
    return "PAIF Bot (Institutional Asia Macro Edition) is running!"

def run_flask():
    app_flask.run(host="0.0.0.0", port=PORT, use_reloader=False, debug=False)

# ==================== Helper Functions ====================
def get_yahoo_data(symbol):
    """Fungsi fleksibel untuk ambil nilai dan % perubahan dari Yahoo"""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None] # Buang data kosong
        
        if len(closes) >= 2:
            current = closes[-1]
            prev = closes[-2]
            change_pct = ((current - prev) / prev) * 100
            return current, round(change_pct, 2)
        elif len(closes) == 1:
            return closes[0], 0.0
    except:
        pass
    return None, None

def calculate_asia_fng():
    """Enjin Makro Khas PAIF: Kira skor 0-100 berdasarkan indikator Asia"""
    score = 50 # Markah asas (Neutral)
    details = []

    # 1. Asia Volatility (VHSI)
    vhsi_val, _ = get_yahoo_data("^VHSI")
    if vhsi_val is not None:
        details.append(f"• VIX Asia (VHSI): {vhsi_val:.2f}")
        if vhsi_val >= 25: score -= 25      # Extreme Fear
        elif vhsi_val >= 20: score -= 15    # Fear
        elif vhsi_val <= 14: score += 20    # Extreme Greed
        elif vhsi_val <= 18: score += 10    # Greed
    else:
        details.append("• VIX Asia (VHSI): N/A")

    # 2. Yen as Safe Haven (USD/JPY)
    jpy_val, jpy_pct = get_yahoo_data("JPY=X")
    if jpy_pct is not None:
        details.append(f"• USD/JPY: {jpy_val:.2f} ({jpy_pct:+.2f}%)")
        if jpy_pct <= -0.5: score -= 15     # Yen menguat = Pelabur panik
        elif jpy_pct <= -0.2: score -= 5
        elif jpy_pct >= 0.5: score += 15    # Yen melemah = Pelabur berani
        elif jpy_pct >= 0.2: score += 5
    else:
        details.append("• USD/JPY: N/A")

    # 3. China Capital Flow (USD/CNY)
    cny_val, cny_pct = get_yahoo_data("CNY=X")
    if cny_pct is not None:
        details.append(f"• USD/CNY: {cny_val:.4f} ({cny_pct:+.2f}%)")
        if cny_pct >= 0.3: score -= 15      # Yuan melemah = Modal keluar
        elif cny_pct >= 0.1: score -= 5
        elif cny_pct <= -0.3: score += 15   # Yuan menguat = Modal masuk
        elif cny_pct <= -0.1: score += 5
    else:
        details.append("• USD/CNY: N/A")
        
    # 4. Asian Equities Trend (Hang Seng & KLCI)
    _, hsi_pct = get_yahoo_data("^HSI")
    _, klci_pct = get_yahoo_data("^KLSE")
    
    if hsi_pct is not None:
        details.append(f"• Hang Seng: {hsi_pct:+.2f}%")
        if hsi_pct <= -1.5: score -= 10
        elif hsi_pct >= 1.5: score += 10
    
    if klci_pct is not None:
        details.append(f"• KLCI: {klci_pct:+.2f}%")
        
    # Tetapkan had markah 0 hingga 100
    score = max(0, min(100, score))
    
    # Penentuan Label
    if score <= 25: rating = "Extreme Fear"
    elif score <= 45: rating = "Fear"
    elif score <= 55: rating = "Neutral"
    elif score <= 75: rating = "Greed"
    else: rating = "Extreme Greed"
    
    return score, rating, "\n".join(details)

def calculate_rsi(prices):
    if len(prices) < 2: 
        return 50.0
    gains, losses = [], []
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
    if avg_loss == 0: return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)

def get_paif_nav_from_db():
    if supabase:
        try:
            res = supabase.table("paif_nav").select("*").order("id", desc=True).execute()
            if res.data:
                records = res.data
                all_navs = [float(r.get("nav")) for r in records if r.get("nav") is not None]
                if not all_navs: return None
                    
                latest_nav = all_navs[0]
                tarikh = records[0].get("tarikh")
                masa = records[0].get("masa")
                nota = records[0].get("nota")
                
                # ATH, ATL & Zon Struktur
                ath = max(all_navs)
                atl = min(all_navs)
                midpoint = atl + ((ath - atl) / 2)
                zone_str = "🟢 DISCOUNT (Bawah 50%)" if latest_nav < midpoint else "🔴 PREMIUM (Atas 50%)"
                
                # RSI 14-Hari
                prices_for_rsi = all_navs[:15][::-1] if len(all_navs) >= 15 else all_navs[::-1]
                rsi_val = calculate_rsi(prices_for_rsi)
                
                if rsi_val <= 30: rsi_status = "Oversold"
                elif rsi_val >= 70: rsi_status = "Overbought"
                else: rsi_status = "Neutral"
                    
                # Perubahan Sejarah
                chg_1w = ((latest_nav - all_navs[5]) / all_navs[5]) * 100 if len(all_navs) > 5 else 0
                chg_1m = ((latest_nav - all_navs[21]) / all_navs[21]) * 100 if len(all_navs) > 21 else 0
                
                info_str = f"{tarikh} {masa}"
                if nota: info_str += f" ({nota})"
                    
                return latest_nav, info_str, rsi_val, rsi_status, zone_str, ath, chg_1w, chg_1m
        except Exception as e:
            logging.error(f"Error baca NAV: {e}")
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

# ==================== Main Function ====================
async def get_fng():
    try:
        # 1. Enjin Sentimen Makro Asia
        macro_score, macro_rating, macro_details = calculate_asia_fng()

        # 2. Pengiraan Teknikal PAIF
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

        # 3. Logik Keputusan Hibrid (Makro + Mikro)
        if macro_score <= 30 and "DISCOUNT" in zone_str and rsi_val <= 40:
            advice = "🔥 **PERFECT BUY / STRONG DCA**\nMakro Asia sedang ketakutan ekstrem, struktur harga diskaun & oversold. Optimum untuk kumpul aset."
        elif macro_score <= 45 and "DISCOUNT" in zone_str:
            advice = "🛒 **BUY (Accumulate)**\nSentimen Makro berpihak kepada Fear dan harga berada di zon diskaun. Boleh DCA berperingkat."
        elif macro_score >= 75 and "PREMIUM" in zone_str and rsi_val >= 70:
            advice = "⚠️ **CAUTION / TAKE PROFIT**\nPasaran Asia tamak (Greed) dan harga PAIF sedang overbought. Jangan kejar harga."
        else:
            advice = "⚖️ **NEUTRAL / HOLD**\nTiada sentimen ekstrem dikesan. Teruskan memantau pergerakan wang serantau."

        msg = (
            f"🧭 *Asia Sentiment (PAIF Radar)*: {macro_score} ({macro_rating})\n\n"
            f"*Indikator Pasaran (Proksi):*\n{macro_details}\n\n"
            f"*Data Teknikal PAIF:*\n{paif_text}\n\n"
            f"*Cadangan Sistem:*\n{advice}"
        )
        return msg

    except Exception as e:
        return f"❌ Gagal ambil data.\nError: {str(e)[:120]}"

# ==================== Telegram Commands ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ *PAIF Institutional Bot Aktif!*\n\n"
        "/fng  - Radar F&G Asia (VIX/FX) & Teknikal\n"
        "/setnav [harga] [nota] - Update NAV manual\n"
        "/paif - Info Dana", parse_mode="Markdown"
    )

async def setnav_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Masukkan harga. *Contoh:* `/setnav 0.8123`", parse_mode="Markdown")
        return
    try:
        new_nav = float(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Format nombor salah.")
        return
        
    nota_str = " ".join(context.args[1:])
    my_time = datetime.utcnow() + timedelta(hours=8)
    
    if supabase:
        try:
            supabase.table("paif_nav").insert({
                "tarikh": my_time.strftime("%d-%m-%Y"),
                "masa": my_time.strftime("%I:%M %p"),
                "nav": new_nav,
                "nota": nota_str
            }).execute()
            await update.message.reply_text(f"✅ NAV RM {new_nav:.4f} berjaya disimpan!", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Gagal: {e}")
    else:
        await update.message.reply_text("❌ Database error.")

async def fng_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await get_fng()
    await update.message.reply_text(msg, parse_mode="Markdown")

async def paif_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 *PAIF Radar*\nEnjin Makro: VIX Asia (VHSI), JPY, CNY, HSI.\nEnjin Mikro: RSI, Drawdown & Zon Struktur.", parse_mode="Markdown")

def main():
    if not TOKEN: return
    threading.Thread(target=run_flask, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("fng", fng_cmd))
    app.add_handler(CommandHandler("paif", paif_cmd))
    app.add_handler(CommandHandler("setnav", setnav_cmd))
    print("Bot berjalan...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
