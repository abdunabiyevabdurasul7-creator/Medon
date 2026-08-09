import logging
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)

# --- SOZLAMALAR ---
BOT_TOKEN = "8611684086:AAHiEjf0ZqhbiaM-SlTnhNBgNprDgQJGwPU"
ADMIN_ID = 5692925792  # Admin Telegram ID

# Database Sozlash
conn = sqlite3.connect('bot_database.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance REAL DEFAULT 0
)''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    item_name TEXT,
    price REAL,
    status TEXT DEFAULT 'Kutilmoqda'
)''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS promocodes (
    code TEXT PRIMARY KEY,
    amount REAL,
    limit_count INTEGER,
    used_count INTEGER DEFAULT 0
)''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS promo_uses (
    user_id INTEGER,
    code TEXT,
    PRIMARY KEY (user_id, code)
)''')

# --- TO'LOVLAR JADVALI ---
cursor.execute('''
CREATE TABLE IF NOT EXISTS payments (
    payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL DEFAULT 0,
    status TEXT DEFAULT 'Kutilmoqda',
    created_at TEXT
)''')
conn.commit()

# --- STEP CONSTANTS ---
(
    PROMO_CODE, PROMO_AMOUNT, PROMO_LIMIT, 
    USE_PROMO, CHECK_ORDER, 
    TRANSFER_USER, TRANSFER_AMOUNT, 
    MANUAL_ADD_USER, MANUAL_ADD_AMOUNT,
    MANUAL_SUB_USER, MANUAL_SUB_AMOUNT,
    POST_MESSAGE, TOP_UP_AMOUNT
) = range(13)

# --- ASOSIY MENYU ---
def main_keyboard():
    return ReplyKeyboardMarkup([
        ["🛍️ Buyurtma berish", "💳 Balans to'ldirish"],
        ["💸 Pul o'tkazish", "🔍 Buyurtmani tekshirish"],
        ["🎁 Promokod", "👤 Balans va Profil"],
        ["📊 Statistika"]
    ], resize_keyboard=True)

# --- BEKOR QILISH TUGMASI UCHUN KLAVIATURA ---
def cancel_keyboard():
    return ReplyKeyboardMarkup([
        ["❌ Bekor qilish"]
    ], resize_keyboard=True)

# --- START COMMAND ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    await update.message.reply_text("Xush kelibsiz! Kerakli bo'limni tanlang:", reply_markup=main_keyboard())

# --- BALANS TO'LDIRISH (1-QADAM: Summani so'rash) ---
async def fill_balance_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💳 Balansni to'ldirish uchun qancha summa kiritmoqchisiz?\n\n"
        "*(Faqat raqamlarda kiriting, masalan: 15000)*",
        reply_markup=cancel_keyboard()
    )
    return TOP_UP_AMOUNT

# --- BALANS TO'LDIRISH (2-QADAM: Karta va chekni so'rash) ---
async def fill_balance_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text)
        if amount <= 0:
            await update.message.reply_text("❌ Noto'g'ri summa kiritildi. Qaytadan kiriting:", reply_markup=cancel_keyboard())
            return TOP_UP_AMOUNT

        context.user_data['top_up_amount'] = amount
        user_id = update.effective_user.id

        text = (
            f"💳 Kiritilgan summa: **{amount:,.0f} so'm**\n\n"
            "1. Quyidagi karta raqamiga to'lov qiling:\n"
            "<code>9860 6067 6078 9275</code> (A.Abdurasul)\n\n"
            "2. To'lov qilgach, to'lov cheki (skrinshot) rasmini shu botning o'ziga yuboring!\n\n"
            f"🆔 Sizning ID: <code>{user_id}</code>"
        )
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_keyboard())
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("❌ Faqat raqam ko'rinishida kiriting:", reply_markup=cancel_keyboard())
        return TOP_UP_AMOUNT

# --- CHEK RASMINI TUTIB OLISH VA ADMINGA YUBORISH ---
async def handle_receipt_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    photo_id = update.message.photo[-1].file_id
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    amount = context.user_data.get('top_up_amount', 0)

    cursor.execute("INSERT INTO payments (user_id, amount, status, created_at) VALUES (?, ?, 'Kutilmoqda', ?)", (user_id, amount, current_time))
    conn.commit()
    payment_id = cursor.lastrowid

    context.user_data.pop('top_up_amount', None)

    await update.message.reply_text("✅ Chek qabul qilindi! Admin ko'rib chiqqach, balansingiz to'ldiriladi.", reply_markup=main_keyboard())

    admin_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Balans qo'shish", callback_data=f"pay_approve_{user_id}_{payment_id}"),
            InlineKeyboardButton("❌ Rad etish", callback_data=f"pay_reject_{payment_id}")
        ],
        [InlineKeyboardButton("💳 To'lovlar tarixi", callback_data="admin_payments_history")]
    ])

    username = update.effective_user.username
    user_mention = f"@{username}" if username else "Yo'q"
    amount_str = f"{amount:,.0f} so'm" if amount > 0 else "Kiritilmagan"
    caption_text = f"📥 Yangi to'lov cheki!\n🆔 To'lov ID: #{payment_id}\n👤 Foydalanuvchi ID: {user_id}\n👤 Username: {user_mention}\n💰 Summa: {amount_str}"

    await context.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo_id,
        caption=caption_text,
        reply_markup=admin_keyboard
    )

# --- ADMIN CHEK ORQALI BALANS QO'SHISH ---
async def approve_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split("_")
    target_user_id = data[2]
    payment_id = data[3] if len(data) > 3 else None

    context.user_data['waiting_for_balance_user'] = target_user_id
    context.user_data['waiting_for_payment_id'] = payment_id
    
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
        
    await query.message.reply_text(f"💳 ID: {target_user_id} foydalanuvchisining balansiga qancha pul qo'shmoqchisiz (so'mda)?\n\n*(Faqat raqam yuboring)*")

# --- ADMIN CHEKNI BEKOR QILISH ---
async def reject_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split("_")
    payment_id = data[2]

    cursor.execute("UPDATE payments SET status = 'Rad etildi' WHERE payment_id = ?", (payment_id,))
    conn.commit()
    
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
        
    if query.message.caption:
        await query.message.edit_caption(caption=query.message.caption + "\n\n❌ **Holat:** To'lov rad etildi!")
    else:
        await query.message.reply_text("❌ To'lov rad etildi.")

# --- ADMIN TO'LOVLAR TARIXINI KO'RISH (/payments) ---
async def admin_payments_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    cursor.execute("SELECT payment_id, user_id, amount, status, created_at FROM payments ORDER BY payment_id DESC LIMIT 15")
    payments = cursor.fetchall()

    if not payments:
        await update.message.reply_text("📭 Hozircha to'lovlar tarixi bo'sh.")
        return

    msg = "📜 **Oxirgi to'lovlar tarixi:**\n\n"
    for p in payments:
        p_id, u_id, amt, status, date = p
        amt_str = f"{amt:,.0f} so'm" if amt else "Aniqlanmagan"
        msg += f"🆔 #{p_id} | User: <code>{u_id}</code>\n💰 Summa: {amt_str}\n📌 Holati: {status} | 🕒 {date}\n-------------------\n"

    await update.message.reply_text(msg, parse_mode="HTML")

# --- ADMIN QO'LDA BALANS QO'SHISH (/addbalance) ---
async def manual_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    await update.message.reply_text("➕ Balansiga pul qo'shmoqchi bo'lgan foydalanuvchining ID raqamini kiriting:", reply_markup=cancel_keyboard())
    return MANUAL_ADD_USER

async def manual_add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = int(update.message.text)
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if not cursor.fetchone():
            await update.message.reply_text("❌ Bunday foydalanuvchi topilmadi.", reply_markup=main_keyboard())
            return ConversationHandler.END
        
        context.user_data['manual_add_user_id'] = user_id
        await update.message.reply_text(f"💰 ID: {user_id} balansiga qancha so'm QO'SHMOQCHISIZ?", reply_markup=cancel_keyboard())
        return MANUAL_ADD_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ ID faqat raqamlardan iborat bo'lishi kerak.", reply_markup=main_keyboard())
        return ConversationHandler.END

async def manual_add_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text)
        user_id = context.user_data['manual_add_user_id']
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        cursor.execute("INSERT INTO payments (user_id, amount, status, created_at) VALUES (?, ?, 'Qo''lda qo''shildi', ?)", (user_id, amount, current_time))
        conn.commit()
        
        await update.message.reply_text(f"✅ ID: {user_id} balansiga {amount:,.0f} so'm qo'shildi!", reply_markup=main_keyboard())
        await context.bot.send_message(user_id, f"🎉 Hisobingizga admin tomonidan {amount:,.0f} so'm qo'shildi!")
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri summa kiritildi.", reply_markup=main_keyboard())
    return ConversationHandler.END

# --- ADMIN QO'LDA BALANS AYRISH (/subbalance) ---
async def manual_sub_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    await update.message.reply_text("➖ Balansidan pul AYRIMOQCHI bo'lgan foydalanuvchining ID raqamini kiriting:", reply_markup=cancel_keyboard())
    return MANUAL_SUB_USER

async def manual_sub_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = int(update.message.text)
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if not cursor.fetchone():
            await update.message.reply_text("❌ Bunday foydalanuvchi topilmadi.", reply_markup=main_keyboard())
            return ConversationHandler.END
        
        context.user_data['manual_sub_user_id'] = user_id
        await update.message.reply_text(f"📉 ID: {user_id} balansidan qancha so'm AYRIMOQCHISIZ?", reply_markup=cancel_keyboard())
        return MANUAL_SUB_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ ID faqat raqamlardan iborat bo'lishi kerak.", reply_markup=main_keyboard())
        return ConversationHandler.END

async def manual_sub_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text)
        user_id = context.user_data.get('manual_sub_user_id')
        
        if not user_id:
            await update.message.reply_text("❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.", reply_markup=main_keyboard())
            return ConversationHandler.END

        if amount <= 0:
            await update.message.reply_text("❌ Summa 0 dan katta bo'lishi kerak.", reply_markup=cancel_keyboard())
            return MANUAL_SUB_AMOUNT

        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        res = cursor.fetchone()
        current_balance = res[0] if res else 0

        if current_balance < amount:
            await update.message.reply_text(f"⚠️ Foydalanuvchining balansi yetarli emas! (Joriy balans: {current_balance:,.0f} so'm)", reply_markup=main_keyboard())
            return ConversationHandler.END

        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        
        await update.message.reply_text(f"✅ ID: {user_id} balansidan {amount:,.0f} so'm ayirib tashlandi!", reply_markup=main_keyboard())
        await context.bot.send_message(user_id, f"⚠️ Balansingizdan admin tomonidan {amount:,.0f} so'm olib tashlandi.")
        
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri summa kiritildi. Faqat raqam kiriting:", reply_markup=cancel_keyboard())
        return MANUAL_SUB_AMOUNT
        
    return ConversationHandler.END

# --- ADMIN POST YUBORISH (/post) ---
async def post_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Bu buyruq faqat Admin uchun!")
        return ConversationHandler.END

    await update.message.reply_text(
        "📢 Barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni yuboring (Matn, rasm, video yoki istalgan fayl):",
        reply_markup=cancel_keyboard()
    )
    return POST_MESSAGE

async def post_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()

    success_count = 0
    fail_count = 0

    await update.message.reply_text("⏳ Xabar foydalanuvchilarga tarqatilmoqda, iltimos kuting...", reply_markup=main_keyboard())

    for user in users:
        user_id = user[0]
        try:
            await update.message.copy(chat_id=user_id)
            success_count += 1
        except Exception:
            fail_count += 1

    await update.message.reply_text(
        f"✅ Post muvaffaqiyatli tarqatildi!\n\n"
        f"📤 Yuborildi: {success_count} ta\n"
        f"❌ Xatolik (botni bloklaganlar): {fail_count} ta",
        reply_markup=main_keyboard()
    )
    return ConversationHandler.END

# --- PUL O'TKAZISH TIZIMI ---
async def transfer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💸 Pul o'tkazmoqchi bo'lgan foydalanuvchining Telegram ID raqamini kiriting:", reply_markup=cancel_keyboard())
    return TRANSFER_USER

async def transfer_get_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target_id = int(update.message.text)
        if target_id == update.effective_user.id:
            await update.message.reply_text("❌ O'zingizga pul o'tkaza olmaysiz!", reply_markup=main_keyboard())
            return ConversationHandler.END

        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (target_id,))
        if not cursor.fetchone():
            await update.message.reply_text("❌ Bunday foydalanuvchi botda topilmadi.", reply_markup=main_keyboard())
            return ConversationHandler.END

        context.user_data['transfer_target'] = target_id
        await update.message.reply_text("Qancha summa o'tkazmoqchisiz (masalan: 10000)?", reply_markup=cancel_keyboard())
        return TRANSFER_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri ID kiritildi.", reply_markup=main_keyboard())
        return ConversationHandler.END

async def transfer_get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text)
        sender_id = update.effective_user.id
        target_id = context.user_data['transfer_target']

        if amount <= 0:
            await update.message.reply_text("❌ Noto'g'ri summa kiritildi.", reply_markup=main_keyboard())
            return ConversationHandler.END

        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (sender_id,))
        res = cursor.fetchone()
        sender_balance = res[0] if res else 0

        if sender_balance < amount:
            await update.message.reply_text("❌ Balansda yetarli mablag' mavjud emas!", reply_markup=main_keyboard())
            return ConversationHandler.END

        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, sender_id))
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
        conn.commit()

        await update.message.reply_text(f"✅ {target_id} ID egasiga {amount:,.0f} so'm muvaffaqiyatli o'tkazildi!", reply_markup=main_keyboard())
        await context.bot.send_message(target_id, f"🎉 Hisobingizga {sender_id} ID egasi tomonidan {amount:,.0f} so'm o'tkazildi!")

    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri summa kiritildi.", reply_markup=main_keyboard())

    return ConversationHandler.END

# --- BUYURTMANI TEKSHIRISH ---
async def check_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Tekshirmoqchi bo'lgan Buyurtma ID raqamini kiriting:", reply_markup=cancel_keyboard())
    return CHECK_ORDER

async def check_order_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        order_id = int(update.message.text)
        user_id = update.effective_user.id

        cursor.execute("SELECT item_name, price, status FROM orders WHERE order_id = ? AND user_id = ?", (order_id, user_id))
        order = cursor.fetchone()

        if order:
            item_name, price, status = order
            status_icon = "⏳" if status == "Kutilmoqda" else ("✅" if status == "Bajarildi" else "❌")
            msg = (
                f"📦 Buyurtma #{order_id} ma'lumotlari:\n\n"
                f"🔹 Mahsulot: {item_name}\n"
                f"💵 Narxi: {price:,.0f} so'm\n"
                f"📌 Holati: {status_icon} {status}"
            )
            await update.message.reply_text(msg, reply_markup=main_keyboard())
        else:
            await update.message.reply_text("❌ Sizga tegishli bunday buyurtma ID topilmadi.", reply_markup=main_keyboard())

    except ValueError:
        await update.message.reply_text("❌ Buyurtma ID faqat raqamlardan iborat bo'ladi.", reply_markup=main_keyboard())

    return ConversationHandler.END

# --- PROMOKOD ISHLATISH ---
async def use_promo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎁 Promokodizni kiriting:", reply_markup=cancel_keyboard())
    return USE_PROMO

async def use_promo_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    user_id = update.effective_user.id

    cursor.execute("SELECT amount, limit_count, used_count FROM promocodes WHERE code = ?", (code,))
    promo = cursor.fetchone()

    if not promo:
        await update.message.reply_text("❌ Bunday promokod mavjud emas!", reply_markup=main_keyboard())
        return ConversationHandler.END

    amount, limit_count, used_count = promo

    if used_count >= limit_count:
        await update.message.reply_text("❌ Ushbu promokod ishlatilish limiti tugagan!", reply_markup=main_keyboard())
        return ConversationHandler.END

    cursor.execute("SELECT 1 FROM promo_uses WHERE user_id = ? AND code = ?", (user_id, code))
    if cursor.fetchone():
        await update.message.reply_text("❌ Siz ushbu promokodni avval ishlatgansiz!", reply_markup=main_keyboard())
        return ConversationHandler.END

    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    cursor.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE code = ?", (code,))
    cursor.execute("INSERT INTO promo_uses (user_id, code) VALUES (?, ?)", (user_id, code))
    conn.commit()

    await update.message.reply_text(f"🎉 Tabriklaymiz! Promokod muvaffaqiyatli faollashtirildi.\n💰 Balansingizga {amount:,.0f} so'm qo'shildi!", reply_markup=main_keyboard())
    return ConversationHandler.END

# --- ADMIN PROMOKOD YARATISH (/addpromo) ---
async def add_promo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Bu buyruq faqat Admin uchun!")
        return ConversationHandler.END

    await update.message.reply_text("🔑 Yangi promokod nomini kiriting (Masalan: BONUS5000):", reply_markup=cancel_keyboard())
    return PROMO_CODE

async def add_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_promo_code'] = update.message.text.strip()
    await update.message.reply_text("💰 Promokod summasini kiriting (so'mda):", reply_markup=cancel_keyboard())
    return PROMO_AMOUNT

async def add_promo_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['new_promo_amount'] = float(update.message.text)
        await update.message.reply_text("👥 Nechta foydalanuvchi ishlata olishini (limit sonini) kiriting:", reply_markup=cancel_keyboard())
        return PROMO_LIMIT
    except ValueError:
        await update.message.reply_text("❌ Summani raqamda kiriting.", reply_markup=main_keyboard())
        return ConversationHandler.END

async def add_promo_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        limit = int(update.message.text)
        code = context.user_data['new_promo_code']
        amount = context.user_data['new_promo_amount']

        cursor.execute("INSERT OR REPLACE INTO promocodes (code, amount, limit_count) VALUES (?, ?, ?)", (code, amount, limit))
        conn.commit()

        await update.message.reply_text(f"✅ Promokod muvaffaqiyatli yaratildi!\n\n🔑 Kodu: {code}\n💰 Summasi: {amount:,.0f} so'm\n👥 Limiti: {limit} ta", reply_markup=main_keyboard())
    except ValueError:
        await update.message.reply_text("❌ Limit sonini raqamda kiriting.", reply_markup=main_keyboard())

    return ConversationHandler.END

# --- STATISTIKA ---
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT COUNT(*) FROM users")
    users_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM orders")
    orders_count = cursor.fetchone()[0]
    await update.message.reply_text(
        f"📊 Bot Statistikasi:\n\n👥 Foydalanuvchilar: {users_count} ta\n📦 Buyurtmalar: {orders_count} ta"
    )

# --- PROFIL ---
async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    balance = res[0] if res else 0
    await update.message.reply_text(
        f"👤 Sizning Profilingiz:\n\n🆔 ID: {user_id}\n💰 Balans: {balance:,.0f} so'm"
    )

# --- KATEGORIYALAR TIZIMI ---
async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Telegram xizmatlari", callback_data="cat_telegram")],
        [InlineKeyboardButton("🎮 PUBG Mobile UC", callback_data="cat_pubg")],
        [InlineKeyboardButton("🔥 Free Fire Diamond", callback_data="cat_ff")],
        [InlineKeyboardButton("🕹️ Grand Mobile ID", callback_data="cat_grand")]
    ])
    await update.message.reply_text("🛒 Kerakli bo'limni tanlang:", reply_markup=keyboard)

async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cat_telegram":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("TG Premium 3 Oy — 178,000 so'm", callback_data="buy_TG Premium 3 Oy_178000")],
            [InlineKeyboardButton("TG Premium 6 Oy — 246,000 so'm", callback_data="buy_TG Premium 6 Oy_246000")],
            [InlineKeyboardButton("TG Premium 12 Oy — 440,000 so'm", callback_data="buy_TG Premium 12 Oy_440000")],
            [InlineKeyboardButton("TG Akkaunt — 8,000 so'm", callback_data="buy_TG Akkaunt_8000")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="cat_back")]
        ])
        await query.edit_message_text("📱 Telegram xizmatlari:", reply_markup=keyboard)

    elif query.data == "cat_pubg":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("60 UC — 13,000 so'm", callback_data="buy_PUBG 60 UC_13000")],
            [InlineKeyboardButton("120 UC — 24,000 so'm", callback_data="buy_PUBG 120 UC_24000")],
            [InlineKeyboardButton("180 UC — 36,000 so'm", callback_data="buy_PUBG 180 UC_36000")],
            [InlineKeyboardButton("325 UC — 59,000 so'm", callback_data="buy_PUBG 325 UC_59000")],
            [InlineKeyboardButton("385 UC — 70,000 so'm", callback_data="buy_PUBG 385 UC_70000")],
            [InlineKeyboardButton("660 UC — 115,000 so'm", callback_data="buy_PUBG 660 UC_115000")],
            [InlineKeyboardButton("985 UC — 170,000 so'm", callback_data="buy_PUBG 985 UC_170000")],
            [InlineKeyboardButton("1320 UC — 230,000 so'm", callback_data="buy_PUBG 1320 UC_230000")],
            [InlineKeyboardButton("1800 UC — 280,000 so'm", callback_data="buy_PUBG 1800 UC_280000")],
            [InlineKeyboardButton("2460 UC — 400,000 so'm", callback_data="buy_PUBG 2460 UC_400000")],
            [InlineKeyboardButton("3850 UC — 550,000 so'm", callback_data="buy_PUBG 3850 UC_550000")],
            [InlineKeyboardButton("5650 UC — 830,000 so'm", callback_data="buy_PUBG 5650 UC_830000")],
            [InlineKeyboardButton("8100 UC — 1,100,000 so'm", callback_data="buy_PUBG 8100 UC_1100000")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="cat_back")]
        ])
        await query.edit_message_text("🎮 PUBG Mobile UC paketlari:", reply_markup=keyboard)

    elif query.data == "cat_ff":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("110 Diamond — 12,000 so'm", callback_data="buy_FF 110 Diamond_12000")],
            [InlineKeyboardButton("341 Diamond — 34,000 so'm", callback_data="buy_FF 341 Diamond_34000")],
            [InlineKeyboardButton("572 Diamond — 56,000 so'm", callback_data="buy_FF 572 Diamond_56000")],
            [InlineKeyboardButton("1166 Diamond — 110,000 so'm", callback_data="buy_FF 1166 Diamond_110000")],
            [InlineKeyboardButton("2398 Diamond — 230,000 so'm", callback_data="buy_FF 2398 Diamond_230000")],
            [InlineKeyboardButton("6160 Diamond — 550,000 so'm", callback_data="buy_FF 6160 Diamond_550000")],
            [InlineKeyboardButton("Evo Acces 3D — 8,000 so'm", callback_data="buy_FF Evo Accsess_8000")],
            [InlineKeyboardButton("Evo Acces 7D — 12,000 so'm", callback_data="buy_FF Evo Accsess 7D_12000")],
            [InlineKeyboardButton("Evo Acces 30D — 40,000 so'm", callback_data="buy_FF Evo Accsess 30D_40000")],
            [InlineKeyboardButton("Prime kichik 7 kunlik — 8,000 so'm", callback_data="buy_FF Prime kichkina 7 kunlik_8000")],
            [InlineKeyboardButton("Prime 7 kunlik — 25,000 so'm", callback_data="buy_FF Prime 7 kunlik_25000")],
            [InlineKeyboardButton("Prime oylik — 86,000 so'm", callback_data="buy_FF Prime oylik_86000")],
            [InlineKeyboardButton("6 Level Up Package — 6,000 so'm", callback_data="buy_FF 6 Level Up Package_6000")],
            [InlineKeyboardButton("10 Level Up Package — 11,000 so'm", callback_data="buy_FF 10 Level Up Package_11000")],
            [InlineKeyboardButton("15 Level Up Package — 16,000 so'm", callback_data="buy_FF 15 Level Up Package_16000")],
            [InlineKeyboardButton("20 Level Up Package — 20,000 so'm", callback_data="buy_FF 20 Level Up Package_20000")],
            [InlineKeyboardButton("25 Level Up Package — 24,000 so'm", callback_data="buy_FF 25 Level Up Package_24000")],
            [InlineKeyboardButton("30 Level Up Package — 28,000 so'm", callback_data="buy_FF 30 Level Up Package_28000")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="cat_back")]
        ])
        await query.edit_message_text("🔥 Free Fire Diamond paketlari:", reply_markup=keyboard)

    elif query.data == "cat_grand":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔥 Grand 5x Tariflar", callback_data="grand_5x")],
            [InlineKeyboardButton("💎 Grand 4x Tariflar", callback_data="grand_4x")],
            [InlineKeyboardButton("💰 Grand 3x Tariflar", callback_data="grand_3x")],
            [InlineKeyboardButton("📱 Grand Oddiy Tariflar", callback_data="grand_normal")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="cat_back")]
        ])
        await query.edit_message_text("🕹️ Grand Mobile GC paketlari:", reply_markup=keyboard)

    elif query.data == "grand_5x":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("75 Gc — 4,000 so'm", callback_data="buy_Grand 5x 75 Gc_4000")],
            [InlineKeyboardButton("150 Gc — 6,500 so'm", callback_data="buy_Grand 5x 150 Gc_6500")],
            [InlineKeyboardButton("450 Gc — 16,500 so'm", callback_data="buy_Grand 5x 450 Gc_16500")],
            [InlineKeyboardButton("1000 Gc — 35,000 so'm", callback_data="buy_Grand 5x 1000 Gc_35000")],
            [InlineKeyboardButton("2525 Gc — 86,000 so'm", callback_data="buy_Grand 5x 2525 Gc_86000")],
            [InlineKeyboardButton("5100 Gc — 171,000 so'm", callback_data="buy_Grand 5x 5100 Gc_171000")],
            [InlineKeyboardButton("12875 Gc — 424,000 so'm", callback_data="buy_Grand 5x 12875 Gc_424000")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="cat_grand")]
        ])
        await query.edit_message_text("🕹️ Grand Mobile 5x GC paketlari:", reply_markup=keyboard)

    elif query.data == "grand_4x":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("60 GC — 3,800 so'm", callback_data="buy_Grand 4x 60 GC_4500")],
            [InlineKeyboardButton("120 GC — 6,200 so'm", callback_data="buy_Grand 4x 120 GC_6200")],
            [InlineKeyboardButton("360 GC — 16,200 so'm", callback_data="buy_Grand 4x 360 GC_16500")],
            [InlineKeyboardButton("800 GC — 34,500 so'm", callback_data="buy_Grand 4x 800 GC_34500")],
            [InlineKeyboardButton("2025 GC — 85,500 so'm", callback_data="buy_Grand 4x 2025 GC_85500")],
            [InlineKeyboardButton("4100 GC — 170,500 so'm", callback_data="buy_Grand 4x 4100 GC_170500")],
            [InlineKeyboardButton("10375 GC — 423,500 so'm", callback_data="buy_Grand 4x 10375 GC_423500")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="cat_grand")]
        ])
        await query.edit_message_text("🕹️ Grand Mobile 4x GC paketlari:", reply_markup=keyboard)

    elif query.data == "grand_3x":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("45 GC — 3,500 so'm", callback_data="buy_Grand 3x 45 GC_3500")],
            [InlineKeyboardButton("90 GC — 6,000 so'm", callback_data="buy_Grand 3x 90 GC_6000")],
            [InlineKeyboardButton("270 GC — 16,000 so'm", callback_data="buy_Grand 3x 270 GC_16000")],
            [InlineKeyboardButton("600 GC — 34,000 so'm", callback_data="buy_Grand 3x 600 GC_34000")],
            [InlineKeyboardButton("1525 GC — 85,000 so'm", callback_data="buy_Grand 3x 1525 GC_85000")],
            [InlineKeyboardButton("3100 GC — 170,000 so'm", callback_data="buy_Grand 3x 3100 GC_170000")],
            [InlineKeyboardButton("7875 GC — 423,000 so'm", callback_data="buy_Grand 3x 7875 GC_423000")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="cat_grand")]
        ])
        await query.edit_message_text("🕹️ Grand Mobile 3x GC paketlari:", reply_markup=keyboard)

    elif query.data == "grand_normal":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("15 GC — 3,500 so'm", callback_data="buy_Grand 15 GC_3500")],
            [InlineKeyboardButton("30 GC — 5,000 so'm", callback_data="buy_Grand 30 GC_5000")],
            [InlineKeyboardButton("90 GC — 15,500 so'm", callback_data="buy_Grand 90 GC_15500")],
            [InlineKeyboardButton("200 GC — 34,000 so'm", callback_data="buy_Grand 200 GC_34000")],
            [InlineKeyboardButton("500 GC — 85,000 so'm", callback_data="buy_Grand 500 GC_85000")],
            [InlineKeyboardButton("1000 GC — 169,000 so'm", callback_data="buy_Grand 1000 GC_169000")],
            [InlineKeyboardButton("2500 GC — 422,000 so'm", callback_data="buy_Grand 2500 GC_422000")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="cat_grand")]
        ])
        await query.edit_message_text("🕹️ Grand Mobile oddiy GC paketlari:", reply_markup=keyboard)

    elif query.data == "cat_back":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 Telegram xizmatlari", callback_data="cat_telegram")],
            [InlineKeyboardButton("🎮 PUBG Mobile UC", callback_data="cat_pubg")],
            [InlineKeyboardButton("🔥 Free Fire Diamond", callback_data="cat_ff")],
            [InlineKeyboardButton("🕹️ Grand Mobile ID", callback_data="cat_grand")]
        ])
        await query.edit_message_text("🛒 Kerakli bo'limni tanlang:", reply_markup=keyboard)

    elif query.data == "admin_payments_history":
        cursor.execute("SELECT payment_id, user_id, amount, status, created_at FROM payments ORDER BY payment_id DESC LIMIT 10")
        payments = cursor.fetchall()
        msg = "📜 **Oxirgi to'lovlar tarixi:**\n\n"
        for p in payments:
            p_id, u_id, amt, status, date = p
            amt_str = f"{amt:,.0f} so'm" if amt else "Kiritilmagan"
            msg += f"🆔 #{p_id} | User: <code>{u_id}</code>\n💰 Summa: {amt_str}\n📌 Holat: {status} | 🕒 {date}\n-------------------\n"
        await query.message.reply_text(msg, parse_mode="HTML")

# --- BUYURTMA XARIDI ---
async def process_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    _, item_name, price = query.data.split("_")
    price = float(price)

    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    balance = res[0] if res else 0

    if balance < price:
        await query.answer("❌ Hisobingizda yetarli pul yo'q!", show_alert=True)
        return

    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (price, user_id))
    cursor.execute("INSERT INTO orders (user_id, item_name, price) VALUES (?, ?, ?)", (user_id, item_name, price))
    order_id = cursor.lastrowid
    conn.commit()

    await query.edit_message_text(f"✅ Buyurtmangiz qabul qilindi!\n🆔 Buyurtma ID: {order_id}\n📦 Mahsulot: {item_name}")

    admin_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Qabul qilish", callback_data=f"adm_accept_{order_id}"),
            InlineKeyboardButton("❌ Rad etish", callback_data=f"adm_reject_{order_id}")
        ]
    ])
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🆕 Yangi Buyurtma!\n\n🆔 ID: {order_id}\n👤 User ID: {user_id}\n📦 Mahsulot: {item_name}\n💵 Narxi: {price:,.0f} so'm",
        reply_markup=admin_keyboard
    )

# --- ADMIN BUYURTMANI TASDIQLASHI ---
async def admin_order_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, action, order_id = query.data.split("_")
    order_id = int(order_id)

    cursor.execute("SELECT user_id, item_name, price, status FROM orders WHERE order_id = ?", (order_id,))
    order = cursor.fetchone()
    
    if not order or order[3] != 'Kutilmoqda':
        await query.edit_message_text("Ushbu buyurtma ko'rib chiqilgan.")
        return

    user_id, item_name, price, status = order

    if action == "accept":
        cursor.execute("UPDATE orders SET status = 'Bajarildi' WHERE order_id = ?", (order_id,))
        conn.commit()
        await query.edit_message_text(f"✅ Buyurtma #{order_id} qabul qilindi.")
        await context.bot.send_message(user_id, f"🎉 Sizning #{order_id} raqamli buyurtmangiz muvaffaqiyatli bajarildi!")

    elif action == "reject":
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (price, user_id))
        cursor.execute("UPDATE orders SET status = 'Bekor qilindi' WHERE order_id = ?", (order_id,))
        conn.commit()
        await query.edit_message_text(f"❌ Buyurtma #{order_id} bekor qilindi.")
        await context.bot.send_message(user_id, f"⚠️ Sizning #{order_id} raqamli buyurtmangiz bekor qilindi. Pul balansingizga qaytarildi.")

# --- GLOBAL TEXT MESSAGE HANDLER ---
async def global_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return

    target_user = context.user_data.get('waiting_for_balance_user')
    payment_id = context.user_data.get('waiting_for_payment_id')

    if target_user:
        try:
            amount = float(update.message.text)
            
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, int(target_user)))
            
            if payment_id:
                cursor.execute("UPDATE payments SET amount = ?, status = 'Tasdiqlandi' WHERE payment_id = ?", (amount, int(payment_id)))
            else:
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("INSERT INTO payments (user_id, amount, status, created_at) VALUES (?, ?, 'Tasdiqlandi', ?)", (int(target_user), amount, current_time))
            
            conn.commit()

            await update.message.reply_text(f"✅ User ID {target_user} balansiga {amount:,.0f} so'm qo'shildi va to'lov saqlandi!", reply_markup=main_keyboard())
            await context.bot.send_message(int(target_user), f"🎉 Hisobingiz admin tomonidan {amount:,.0f} so'mga to'ldirildi!")

            context.user_data.pop('waiting_for_balance_user', None)
            context.user_data.pop('waiting_for_payment_id', None)
        except ValueError:
            await update.message.reply_text("❌ Xato! Faqat raqam yuboring (masalan: 10000):")
        return

# --- CANCEL ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Jarayon bekor qilindi.", reply_markup=main_keyboard())
    return ConversationHandler.END

# --- BOTNI ISHGA TUSHIRISH ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("payments", admin_payments_cmd))
    app.add_handler(MessageHandler(filters.Regex("^📊 Statistika$"), show_stats))
    app.add_handler(MessageHandler(filters.Regex("^👤 Balans va Profil$"), show_profile))
    app.add_handler(MessageHandler(filters.Regex("^🛍️ Buyurtma berish$"), order_start))
    
    app.add_handler(MessageHandler(filters.PHOTO, handle_receipt_photo))

    app.add_handler(CallbackQueryHandler(category_callback, pattern="^(cat_|grand_|admin_payments_history)"))
    app.add_handler(CallbackQueryHandler(process_buy, pattern="^buy_"))
    app.add_handler(CallbackQueryHandler(admin_order_action, pattern="^adm_"))
    app.add_handler(CallbackQueryHandler(approve_payment_callback, pattern="^pay_approve_"))
    app.add_handler(CallbackQueryHandler(reject_payment_callback, pattern="^pay_reject_"))

    # Balans to'ldirish uchun Conversation Handler
    top_up_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💳 Balans to'ldirish$"), fill_balance_start)],
        states={
            TOP_UP_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ Bekor qilish$"), fill_balance_amount)]
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ Bekor qilish$"), cancel), CommandHandler("cancel", cancel)]
    )
    app.add_handler(top_up_conv)

    transfer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💸 Pul o'tkazish$"), transfer_start)],
        states={
            TRANSFER_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ Bekor qilish$"), transfer_get_user)],
            TRANSFER_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ Bekor qilish$"), transfer_get_amount)]
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ Bekor qilish$"), cancel), CommandHandler("cancel", cancel)]
    )

    check_order_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 Buyurtmani tekshirish$"), check_order_start)],
        states={
            CHECK_ORDER: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ Bekor qilish$"), check_order_process)]
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ Bekor qilish$"), cancel), CommandHandler("cancel", cancel)]
    )

    use_promo_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎁 Promokod$"), use_promo_start)],
        states={
            USE_PROMO: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ Bekor qilish$"), use_promo_process)]
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ Bekor qilish$"), cancel), CommandHandler("cancel", cancel)]
    )

    add_promo_conv = ConversationHandler(
        entry_points=[CommandHandler("addpromo", add_promo_start)],
        states={
            PROMO_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ Bekor qilish$"), add_promo_code)],
            PROMO_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ Bekor qilish$"), add_promo_amount)],
            PROMO_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ Bekor qilish$"), add_promo_limit)]
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ Bekor qilish$"), cancel), CommandHandler("cancel", cancel)]
    )

    manual_add_conv = ConversationHandler(
        entry_points=[CommandHandler("addbalance", manual_add_start)],
        states={
            MANUAL_ADD_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ Bekor qilish$"), manual_add_user)],
            MANUAL_ADD_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ Bekor qilish$"), manual_add_amount)]
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ Bekor qilish$"), cancel), CommandHandler("cancel", cancel)]
    )

    manual_sub_conv = ConversationHandler(
        entry_points=[CommandHandler("subbalance", manual_sub_start)],
        states={
            MANUAL_SUB_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ Bekor qilish$"), manual_sub_user)],
            MANUAL_SUB_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^❌ Bekor qilish$"), manual_sub_amount)]
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ Bekor qilish$"), cancel), CommandHandler("cancel", cancel)]
    )

    post_conv = ConversationHandler(
        entry_points=[CommandHandler("post", post_start)],
        states={
            POST_MESSAGE: [MessageHandler((filters.ALL & ~filters.COMMAND) & ~filters.Regex("^❌ Bekor qilish$"), post_send)]
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ Bekor qilish$"), cancel), CommandHandler("cancel", cancel)]
    )

    app.add_handler(transfer_conv)
    app.add_handler(check_order_conv)
    app.add_handler(use_promo_conv)
    app.add_handler(add_promo_conv)
    app.add_handler(manual_add_conv)
    app.add_handler(manual_sub_conv)
    app.add_handler(post_conv)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_message_handler))

    print("Bot muvaffaqiyatli ishga tushdi...")
    app.run_polling()

if __name__ == "__main__":
    main()
