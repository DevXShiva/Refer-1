import os
import asyncio
import uuid
import time
import aiohttp
from threading import Thread
from flask import Flask
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
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
IMAGE_URL = "https://i.postimg.cc/BnvmwT0M/LOGO.png" 
SHORTENER_URL = "https://mdiskshort.in/api?api={api}&url={url}" 
FSUB_CHANNELS = [-1003627956964] 
MIN_WITHDRAW = 10
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

# Initialize Bot with HTML Parse Mode
bot = Bot(
    token=TOKEN, 
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# --- KEYBOARDS ---

# Normal Reply Keyboard (Menu)
def main_menu_kb():
    kb = [
        [KeyboardButton(text="💰 Start Task"), KeyboardButton(text="🎥 Tutorial")],
        [KeyboardButton(text="👥 Refer & Earn"), KeyboardButton(text="🏆 Leaderboard")],
        [KeyboardButton(text="📊 Profile"), KeyboardButton(text="💳 Withdraw")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# Professional Inline Keyboard for Messages
def inline_menu_kb():
    btns = [
        [InlineKeyboardButton(text="💰 Start Task", callback_data="start_task_btn"), 
         InlineKeyboardButton(text="🎥 Tutorial", callback_data="tutorial_btn")],
        [InlineKeyboardButton(text="👥 Refer & Earn", callback_data="refer_btn"), 
         InlineKeyboardButton(text="🏆 Leaderboard", callback_data="leaderboard_btn")],
        [InlineKeyboardButton(text="📊 Profile", callback_data="profile_btn"), 
         InlineKeyboardButton(text="💳 Withdraw", callback_data="withdraw_btn")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=btns)

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
            if member.status in ["left", "kicked", "member" == False]: return False
            if member.status in ["member", "administrator", "creator"]: continue
            else: return False
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
            return await message.answer_photo(IMAGE_URL, caption="⚠️ <b>Access Denied!</b>\n\nYou must join our channels first to verify your task.", reply_markup=await get_fsub_kb())
        
        token = args.split("_")[1]
        task_data = await tasks.find_one({"token": token, "user_id": user_id, "used": False})
        if not task_data: return await message.answer("❌ Invalid or Expired Token!")

        if time.time() - task_data["created_at"] < 50:
            await users.update_one({"_id": user_id}, {"$inc": {"warnings": 1}})
            u = await users.find_one({"_id": user_id})
            if u["warnings"] >= 3:
                await users.update_one({"_id": user_id}, {"$set": {"is_banned": True}})
                return await message.answer("🚫 <b>BANNED!</b>\nReason: Continuous Timer Bypass.")
            return await message.answer(f"⚠️ <b>Warning!</b>\nDon't bypass Link. Complete All the Steps.\nWarnings: {u['warnings']}/3")

        await tasks.update_one({"token": token}, {"$set": {"used": True}})
        await users.update_one({"_id": user_id}, {"$inc": {"balance": TASK_REWARD, "tasks": 1}})
        
        u = await users.find_one({"_id": user_id})
        if u["referrer"] and not u["ref_claimed"]:
            await users.update_one({"_id": u["referrer"]}, {"$inc": {"balance": REFER_REWARD, "referrals": 1}})
            await users.update_one({"_id": user_id}, {"$set": {"ref_claimed": True}})
        
        return await message.answer_photo(IMAGE_URL, caption=f"✅ <b>Task Verified Successfully!</b>\n\n💰 Reward: <b>₹{TASK_REWARD}</b> added to your wallet.", reply_markup=main_menu_kb())

    if not await is_subscribed(user_id):
        return await message.answer_photo(IMAGE_URL, caption="👋 <b>Welcome!</b>\n\nTo start earning, please join our mandatory channels below:", reply_markup=await get_fsub_kb())
    
    welcome_text = (
        "🌟 <b>Welcome to Earn Pro Bot</b>\n\n"
        "Complete simple tasks and refer friends to earn real money.\n\n"
        "🚀 <b>Click 'Start Task' to begin!</b>"
    )
    await message.answer_photo(IMAGE_URL, caption=welcome_text, reply_markup=inline_menu_kb())
    # Also send reply keyboard to ensure user has it
    await message.answer("Use the menu below to navigate:", reply_markup=main_menu_kb())

async def generate_task(user_id, message):
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
        "🛠 <b>New Task Generated!</b>\n\n"
        "1️⃣ Click the button below\n"
        "2️⃣ Complete the shortlink\n"
        "3️⃣ Wait 30 seconds on the final page\n\n"
        f"💵 <b>Reward:</b> <code>₹{TASK_REWARD}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚀 Open Task Link", url=short_url)]])
    await bot.send_photo(user_id, photo=IMAGE_URL, caption=text, reply_markup=kb)

@dp.message(F.text == "💰 Start Task")
async def task_init_msg(message: types.Message):
    await generate_task(message.from_user.id, message)

@dp.message(F.text == "📊 Profile")
async def profile_msg(message: types.Message):
    user_id = message.from_user.id
    u = await users.find_one({"_id": user_id})
    text = (
        "👤 <b>User Dashboard</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Balance:</b> <code>₹{u['balance']:.2f}</code>\n"
        f"✅ <b>Tasks Done:</b> <code>{u['tasks']}</code>\n"
        f"👥 <b>Referrals:</b> <code>{u['referrals']}</code>\n"
        f"⚠️ <b>Warnings:</b> <code>{u['warnings']}/3</code>\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    await message.answer_photo(IMAGE_URL, caption=text)

@dp.message(F.text == "👥 Refer & Earn")
async def refer_msg(message: types.Message):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={message.from_user.id}"
    text = (
        "👥 <b>Referral Program</b>\n\n"
        "Share your link and earn for every friend who completes 1 task!\n\n"
        f"🎁 <b>Reward:</b> <code>₹{REFER_REWARD}</code>\n\n"
        f"🔗 <b>Your Link:</b>\n<code>{link}</code>"
    )
    await message.answer_photo(IMAGE_URL, caption=text)

# --- CALLBACK HANDLERS FOR INLINE BUTTONS ---

@dp.callback_query(F.data == "start_task_btn")
async def cb_start_task(callback: types.CallbackQuery):
    await callback.answer()
    await generate_task(callback.from_user.id, callback.message)

@dp.callback_query(F.data == "profile_btn")
async def cb_profile(callback: types.CallbackQuery):
    await callback.answer()
    u = await users.find_one({"_id": callback.from_user.id})
    text = f"👤 <b>User Dashboard</b>\n\n💰 <b>Balance:</b> <code>₹{u['balance']:.2f}</code>\n✅ <b>Tasks:</b> <code>{u['tasks']}</code>"
    await callback.message.answer_photo(IMAGE_URL, caption=text)

@dp.callback_query(F.data == "refer_btn")
async def cb_refer(callback: types.CallbackQuery):
    await callback.answer()
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={callback.from_user.id}"
    await callback.message.answer_photo(IMAGE_URL, caption=f"👥 <b>Refer & Earn</b>\n\nLink: <code>{link}</code>")

@dp.callback_query(F.data == "leaderboard_btn")
async def cb_leaderboard(callback: types.CallbackQuery):
    await callback.answer()
    cursor = users.find().sort("tasks", -1).limit(10)
    text = "🏆 <b>Top 10 Performers</b>\n\n"
    idx = 1
    async for u in cursor:
        text += f"{idx}️⃣ <code>ID: {u['_id']}</code> | <b>{u['tasks']}</b> Tasks\n"
        idx += 1
    await callback.message.answer_photo(IMAGE_URL, caption=text)

@dp.callback_query(F.data == "tutorial_btn")
async def cb_tutorial(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer_photo(IMAGE_URL, caption="📖 <b>Tutorial</b>\n\nWatch our video guide here:", 
    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📺 Watch Now", url="https://youtube.com")]]))

@dp.callback_query(F.data == "withdraw_btn")
async def cb_withdraw(callback: types.CallbackQuery):
    await callback.answer()
    u = await users.find_one({"_id": callback.from_user.id})
    if u["balance"] < MIN_WITHDRAW:
        await callback.message.answer(f"❌ <b>Insufficient Balance!</b>\nMin: ₹{MIN_WITHDRAW}")
    else:
        await callback.message.answer("💳 <b>Withdrawal</b>\n\nSend your UPI ID now.")

@dp.callback_query(F.data == "check_fsub")
async def check_fsub_callback(callback: types.CallbackQuery):
    if await is_subscribed(callback.from_user.id):
        await callback.message.delete()
        await callback.message.answer("✅ <b>Access Granted!</b> Choose an option:", reply_markup=inline_menu_kb())
    else:
        await callback.answer("❌ You haven't joined yet!", show_alert=True)

# --- OTHER HANDLERS ---

@dp.message(F.text == "🎥 Tutorial")
async def tutorial_handler(message: types.Message):
    await message.answer_photo(IMAGE_URL, caption="📖 <b>How to Earn?</b>\n\nWatch our tutorial to understand the process properly.", 
    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📺 Watch Video", url="https://youtube.com")]]))

@dp.message(F.text == "🏆 Leaderboard")
async def leaderboard_handler(message: types.Message):
    cursor = users.find().sort("tasks", -1).limit(10)
    text = "🏆 <b>Top 10 Performers</b>\n\n"
    idx = 1
    async for u in cursor:
        text += f"{idx}️⃣ <code>ID: {u['_id']}</code> | <b>{u['tasks']}</b> Tasks\n"
        idx += 1
    await message.answer_photo(IMAGE_URL, caption=text)

@dp.message(F.text == "💳 Withdraw")
async def withdraw_handler(message: types.Message):
    u = await users.find_one({"_id": message.from_user.id})
    if u["balance"] < MIN_WITHDRAW: 
        return await message.answer_photo(IMAGE_URL, caption=f"❌ <b>Withdrawal Failed!</b>\n\nMinimum amount required: <b>₹{MIN_WITHDRAW}</b>")
    await message.answer_photo(IMAGE_URL, caption="💳 <b>Withdrawal Request</b>\n\nPlease send your <b>UPI ID</b> or <b>Payment Number</b>.")

@dp.message(F.text.contains("@"))
async def handle_payment_input(message: types.Message):
    user_id = message.from_user.id
    u = await users.find_one({"_id": user_id})
    if u and u["balance"] >= MIN_WITHDRAW:
        amt = u["balance"]
        await users.update_one({"_id": user_id}, {"$set": {"balance": 0.0}})
        res = await withdraws.insert_one({"user_id": user_id, "amount": amt, "info": message.text, "status": "pending"})
        await bot.send_message(ADMIN_ID, f"🔔 <b>Withdrawal Alert</b>\nUser: <code>{user_id}</code>\nAmount: ₹{amt}\nDetails: {message.text}\nApprove: <code>/approve {res.inserted_id}</code>")
        await message.answer_photo(IMAGE_URL, caption="✅ <b>Request Sent!</b>\n\nYour payment will be processed within 24 hours.")

async def main():
    Thread(target=run_flask).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
