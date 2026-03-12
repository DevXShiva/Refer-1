import os
import asyncio
import uuid
import time
import aiohttp
from threading import Thread
from flask import Flask
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

# Load environment variables
load_dotenv()

TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URL = os.environ.get("MONGO_URL")
ADMIN_ID_VAL = os.environ.get("ADMIN_ID")
SHORTENER_API_KEY = os.environ.get("SHORTENER_API_KEY")

# --- CONFIGURATION ---
IMAGE_URL = "https://telegra.ph/file/your_image_id.jpg" # अपनी इमेज लिंक यहाँ डालें
SHORTENER_URL = "https://mdiskshort.in/api?api={api}&url={url}" 
FSUB_CHANNELS = [-1003627956964] 
MIN_WITHDRAW = 150
TASK_REWARD = 0.30
REFER_REWARD = 0.50

if not TOKEN:
    raise ValueError("BOT_TOKEN is not set in environment variables!")

ADMIN_ID = int(ADMIN_ID_VAL) if ADMIN_ID_VAL else 0

app = Flask('')
@app.route('/')
def home(): return "Bot is Running 24/7!"

def run_flask(): app.run(host='0.0.0.0', port=8080)

cluster = AsyncIOMotorClient(MONGO_URL)
db = cluster["tg_task_final_bot"]
users, tasks, withdraws = db["users"], db["tasks"], db["withdraws"]

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- KEYBOARDS ---
def main_menu_kb():
    kb = [
        [KeyboardButton(text="💰 Start Task"), KeyboardButton(text="🎥 Tutorial")],
        [KeyboardButton(text="👥 Refer & Earn"), KeyboardButton(text="🏆 Leaderboard")],
        [KeyboardButton(text="📊 Profile"), KeyboardButton(text="💳 Withdraw")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

async def get_fsub_kb():
    btns = []
    for i, chat_id in enumerate(FSUB_CHANNELS, 1):
        try:
            chat = await bot.get_chat(chat_id)
            btns.append([InlineKeyboardButton(text=f"📢 Join Channel {i}", url=chat.invite_link or "https://t.me/yourlink")])
        except: continue
    btns.append([InlineKeyboardButton(text="✅ Check Subscription", callback_data="check_fsub")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

async def is_subscribed(user_id):
    for chat_id in FSUB_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in ["left", "kicked"]: return False
        except: return False
    return True

# --- HANDLERS ---

@dp.message(CommandStart())
async def start_handler(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    args = command.args
    user = await users.find_one({"_id": user_id})
    
    if not user:
        ref_id = int(args) if args and args.isdigit() else None
        await users.insert_one({"_id": user_id, "balance": 0.0, "referrals": 0, "tasks": 0, "warnings": 0, "is_banned": False, "referrer": ref_id, "ref_claimed": False})

    if args and args.startswith("verify_"):
        if not await is_subscribed(user_id):
            return await message.answer_photo(IMAGE_URL, caption="⚠️ **Access Denied!**\n\nYou must join our channels first to verify your task.", reply_markup=await get_fsub_kb())
        
        token = args.split("_")[1]
        task_data = await tasks.find_one({"token": token, "user_id": user_id, "used": False})
        if not task_data: return await message.answer("❌ Invalid or Expired Token!")

        if time.time() - task_data["created_at"] < 30:
            await users.update_one({"_id": user_id}, {"$inc": {"warnings": 1}})
            u = await users.find_one({"_id": user_id})
            if u["warnings"] >= 3:
                await users.update_one({"_id": user_id}, {"$set": {"is_banned": True}})
                return await message.answer("🚫 **BANNED!**\nReason: Continuous Timer Bypass.")
            return await message.answer(f"⚠️ **Warning!**\nDon't bypass the timer. Wait at least 30s.\nWarnings: {u['warnings']}/3")

        await tasks.update_one({"token": token}, {"$set": {"used": True}})
        await users.update_one({"_id": user_id}, {"$inc": {"balance": TASK_REWARD, "tasks": 1}})
        
        u = await users.find_one({"_id": user_id})
        if u["referrer"] and not u["ref_claimed"]:
            await users.update_one({"_id": u["referrer"]}, {"$inc": {"balance": REFER_REWARD, "referrals": 1}})
            await users.update_one({"_id": user_id}, {"$set": {"ref_claimed": True}})
        
        return await message.answer_photo(IMAGE_URL, caption=f"✅ **Task Verified Successfully!**\n\n💰 Reward: `₹{TASK_REWARD}` added to your wallet.", reply_markup=main_menu_kb())

    if not await is_subscribed(user_id):
        return await message.answer_photo(IMAGE_URL, caption="👋 **Welcome!**\n\nTo start earning, please join our mandatory channels below:", reply_markup=await get_fsub_kb())
    
    await message.answer_photo(IMAGE_URL, caption="🌟 **Welcome to Earn Pro Bot**\n\nComplete simple tasks and refer friends to earn real money.\n\n🚀 **Click 'Start Task' to begin!**", reply_markup=main_menu_kb())

@dp.message(F.text == "💰 Start Task")
async def task_init(message: types.Message):
    user_id = message.from_user.id
    u = await users.find_one({"_id": user_id})
    if u.get("is_banned"): return await message.answer("🚫 Your account is banned.")
    if not await is_subscribed(user_id): return await message.answer("❌ Join channels first!", reply_markup=await get_fsub_kb())

    token = str(uuid.uuid4())[:10]
    await tasks.insert_one({"token": token, "user_id": user_id, "used": False, "created_at": time.time()})
    
    me = await bot.get_me()
    raw_url = f"https://t.me/{me.username}?start=verify_{token}"
    async with aiohttp.ClientSession() as session:
        async with session.get(SHORTENER_URL.format(api=SHORTENER_API_KEY, url=raw_url)) as r:
            res = await r.json()
            short_url = res.get("shortenedUrl", "Error")

    text = (
        "🛠 **New Task Generated!**\n\n"
        "1️⃣ Click the button below\n"
        "2️⃣ Complete the shortlink\n"
        "3️⃣ Wait 30 seconds on the final page\n\n"
        f"💵 **Reward:** `₹{TASK_REWARD}`"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚀 Open Task Link", url=short_url)]])
    await message.answer_photo(IMAGE_URL, caption=text, reply_markup=kb)

@dp.message(F.text == "🎥 Tutorial")
async def tutorial_handler(message: types.Message):
    await message.answer_photo(IMAGE_URL, caption="📖 **How to Earn?**\n\nWatch our tutorial to understand the process properly.", 
    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📺 Watch Video", url="https://youtube.com")]]))

@dp.message(F.text == "📊 Profile")
async def profile_handler(message: types.Message):
    u = await users.find_one({"_id": message.from_user.id})
    text = (
        "👤 **User Dashboard**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 **Balance:** `₹{u['balance']:.2f}`\n"
        f"✅ **Tasks Done:** `{u['tasks']}`\n"
        f"👥 **Referrals:** `{u['referrals']}`\n"
        f"⚠️ **Warnings:** `{u['warnings']}/3`\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    await message.answer_photo(IMAGE_URL, caption=text, parse_mode="Markdown")

@dp.message(F.text == "👥 Refer & Earn")
async def refer_handler(message: types.Message):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={message.from_user.id}"
    text = (
        "👥 **Referral Program**\n\n"
        "Share your link and earn for every friend who completes 1 task!\n\n"
        f"🎁 **Reward:** `₹{REFER_REWARD}`\n\n"
        f"🔗 **Your Link:** `{link}`"
    )
    await message.answer_photo(IMAGE_URL, caption=text, parse_mode="Markdown")

@dp.message(F.text == "🏆 Leaderboard")
async def leaderboard_handler(message: types.Message):
    cursor = users.find().sort("tasks", -1).limit(10)
    text = "🏆 **Top 10 Performers**\n\n"
    idx = 1
    async for u in cursor:
        text += f"{idx}️⃣ `ID: {u['_id']}` | **{u['tasks']}** Tasks\n"
        idx += 1
    await message.answer_photo(IMAGE_URL, caption=text, parse_mode="Markdown")

@dp.message(F.text == "💳 Withdraw")
async def withdraw_handler(message: types.Message):
    u = await users.find_one({"_id": message.from_user.id})
    if u["balance"] < MIN_WITHDRAW: 
        return await message.answer_photo(IMAGE_URL, caption=f"❌ **Withdrawal Failed!**\n\nMinimum amount required: `₹{MIN_WITHDRAW}`")
    
    await message.answer_photo(IMAGE_URL, caption="💳 **Withdrawal Request**\n\nPlease send your **UPI ID** or **Payment Number**.")

@dp.message(F.text.contains("@"))
async def handle_payment_input(message: types.Message):
    user_id = message.from_user.id
    u = await users.find_one({"_id": user_id})
    if u and u["balance"] >= MIN_WITHDRAW:
        amt = u["balance"]
        await users.update_one({"_id": user_id}, {"$set": {"balance": 0.0}})
        res = await withdraws.insert_one({"user_id": user_id, "amount": amt, "info": message.text, "status": "pending"})
        await bot.send_message(ADMIN_ID, f"🔔 **Withdrawal Alert**\nUser: `{user_id}`\nAmount: ₹{amt}\nDetails: {message.text}\nApprove: `/approve {res.inserted_id}`")
        await message.answer_photo(IMAGE_URL, caption="✅ **Request Sent!**\n\nYour payment will be processed within 24 hours.")

@dp.message(Command("stats"))
async def stats_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    t_u = await users.count_documents({})
    t_t = await tasks.count_documents({"used": True})
    await message.answer(f"📊 **Bot Admin Stats**\n\nTotal Users: {t_u}\nTotal Successful Tasks: {t_t}")

@dp.callback_query(F.data == "check_fsub")
async def check_fsub_callback(callback: types.CallbackQuery):
    if await is_subscribed(callback.from_user.id):
        await callback.message.delete()
        await callback.message.answer("✅ **Access Granted!** Choose an option:", reply_markup=main_menu_kb())
    else:
        await callback.answer("❌ You haven't joined yet!", show_alert=True)

async def main():
    Thread(target=run_flask).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
