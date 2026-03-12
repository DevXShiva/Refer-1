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

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
SHORTENER_API_KEY = os.getenv("SHORTENER_API_KEY")

SHORTENER_URL = "https://mdiskshort.in/api?api={api}&url={url}" 
FSUB_CHANNELS = [-1003627956964] 
MIN_WITHDRAW = 150
TASK_REWARD = 0.30
REFER_REWARD = 0.50

app = Flask('')

@app.route('/')
def home():
    return "Bot is Running 24/7 with Flask Server!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

cluster = AsyncIOMotorClient(MONGO_URL)
db = cluster["tg_task_final_bot"]
users = db["users"]
tasks = db["tasks"]
withdraws = db["withdraws"]

bot = Bot(token=TOKEN)
dp = Dispatcher()

def main_menu_kb():
    kb = [
        [KeyboardButton(text="💰 Start Task"), KeyboardButton(text="🎥 Tutorial")],
        [KeyboardButton(text="👥 Refer & Earn"), KeyboardButton(text="🏆 Leaderboard")],
        [KeyboardButton(text="📊 Profile"), KeyboardButton(text="💳 Withdraw")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

async def is_subscribed(user_id):
    for chat_id in FSUB_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in ["left", "kicked"]: return False
        except: return False
    return True

async def get_fsub_kb():
    btns = []
    for i, chat_id in enumerate(FSUB_CHANNELS, 1):
        try:
            chat = await bot.get_chat(chat_id)
            link = chat.invite_link or f"https://t.me/c/{str(chat_id)[4:]}/1"
            btns.append([InlineKeyboardButton(text=f"Join Channel {i}", url=link)])
        except: continue
    btns.append([InlineKeyboardButton(text="Check Join ✅", callback_data="check_fsub")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

@dp.message(CommandStart())
async def start_handler(message: types.Message, command: CommandObject):
    user_id = message.from_id
    args = command.args
    user = await users.find_one({"_id": user_id})
    if not user:
        ref_id = int(args) if args and args.isdigit() else None
        await users.insert_one({"_id": user_id, "balance": 0.0, "referrals": 0, "tasks": 0, "warnings": 0, "is_banned": False, "referrer": ref_id, "ref_claimed": False})
    
    if args and args.startswith("verify_"):
        if not await is_subscribed(user_id): return await message.answer("First join channels!", reply_markup=await get_fsub_kb())
        token = args.split("_")[1]
        task_data = await tasks.find_one({"token": token, "user_id": user_id, "used": False})
        if not task_data: return await message.answer("Invalid or Expired Token!")
        
        if time.time() - task_data["created_at"] < 30:
            await users.update_one({"_id": user_id}, {"$inc": {"warnings": 1}})
            u = await users.find_one({"_id": user_id})
            if u["warnings"] >= 3:
                await users.update_one({"_id": user_id}, {"$set": {"is_banned": True}})
                return await message.answer("BANNED! Reason: Bypassing Timer.")
            return await message.answer(f"Warning! Don't bypass timer. ({u['warnings']}/3)")
            
        await tasks.update_one({"token": token}, {"$set": {"used": True}})
        await users.update_one({"_id": user_id}, {"$inc": {"balance": TASK_REWARD, "tasks": 1}})
        u = await users.find_one({"_id": user_id})
        if u["referrer"] and not u["ref_claimed"]:
            await users.update_one({"_id": u["referrer"]}, {"$inc": {"balance": REFER_REWARD, "referrals": 1}})
            await users.update_one({"_id": user_id}, {"$set": {"ref_claimed": True}})
        return await message.answer(f"✅ Task Verified! ₹{TASK_REWARD} added.", reply_markup=main_menu_kb())
    
    if not await is_subscribed(user_id): return await message.answer("Join our channels to start earning:", reply_markup=await get_fsub_kb())
    await message.answer("Welcome to Earn Bot! Choose an option:", reply_markup=main_menu_kb())

@dp.message(F.text == "💰 Start Task")
async def task_init(message: types.Message):
    u = await users.find_one({"_id": message.from_id})
    if u.get("is_banned"): return await message.answer("You are BANNED!")
    if not await is_subscribed(message.from_id): return await message.answer("Join channels first!", reply_markup=await get_fsub_kb())
    
    token = str(uuid.uuid4())[:10]
    await tasks.insert_one({"token": token, "user_id": message.from_id, "used": False, "created_at": time.time()})
    me = await bot.get_me()
    raw_url = f"https://t.me/{me.username}?start=verify_{token}"
    async with aiohttp.ClientSession() as session:
        async with session.get(SHORTENER_URL.format(api=SHORTENER_API_KEY, url=raw_url)) as r:
            res = await r.json()
            short_url = res.get("shortenedUrl", "Error")
    await message.answer("Complete the shortlink (Wait 30s) to earn:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Open Task Link", url=short_url)]]))

@dp.message(F.text == "🎥 Tutorial")
async def tutorial_handler(message: types.Message):
    await message.answer("Video tutorial placeholder: [Add link or video in admin setting]")

@dp.message(F.text == "📊 Profile")
async def profile_handler(message: types.Message):
    u = await users.find_one({"_id": message.from_id})
    await message.answer(f"👤 **Your Profile**\n\nBalance: ₹{u['balance']:.2f}\nTasks Done: {u['tasks']}\nReferrals: {u['referrals']}\nWarnings: {u['warnings']}/3\nID: `{u['_id']}`", parse_mode="Markdown")

@dp.message(F.text == "👥 Refer & Earn")
async def refer_handler(message: types.Message):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={message.from_id}"
    await message.answer(f"Invite friends and earn ₹{REFER_REWARD} when they complete their first task!\n\nYour Link: `{link}`", parse_mode="Markdown")

@dp.message(F.text == "🏆 Leaderboard")
async def leaderboard_handler(message: types.Message):
    cursor = users.find().sort("tasks", -1).limit(10)
    text = "🏆 **Top 10 Earners**\n\n"
    idx = 1
    async for u in cursor:
        text += f"{idx}. User ID: {u['_id']} | Tasks: {u['tasks']}\n"; idx += 1
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "💳 Withdraw")
async def withdraw_handler(message: types.Message):
    u = await users.find_one({"_id": message.from_id})
    if u["balance"] < MIN_WITHDRAW: return await message.answer(f"Insufficient balance! Minimum withdraw is ₹{MIN_WITHDRAW}")
    await message.answer("Send your UPI ID or Payment Details to proceed:")

@dp.message(F.text.contains("@"))
async def handle_payment_input(message: types.Message):
    u = await users.find_one({"_id": message.from_id})
    if u["balance"] >= MIN_WITHDRAW:
        amt = u["balance"]
        await users.update_one({"_id": message.from_id}, {"$set": {"balance": 0.0}})
        res = await withdraws.insert_one({"user_id": message.from_id, "amount": amt, "info": message.text, "status": "pending"})
        await bot.send_message(ADMIN_ID, f"📢 **New Withdrawal Request**\nUser: `{message.from_id}`\nAmount: ₹{amt}\nDetails: {message.text}\nApprove: `/approve {res.inserted_id}`", parse_mode="Markdown")
        await message.answer("Your withdrawal request has been sent for approval! ✅")

@dp.message(Command("stats"))
async def stats_admin(message: types.Message):
    if message.from_id != ADMIN_ID: return
    total = await users.count_documents({})
    tasks_done = await tasks.count_documents({"used": True})
    await message.answer(f"📊 **Bot Stats**\nTotal Users: {total}\nTotal Tasks Completed: {tasks_done}")

@dp.message(Command("broadcast"))
async def broadcast_admin(message: types.Message):
    if message.from_id != ADMIN_ID or not message.reply_to_message: return
    s, f = 0, 0
    async for u in users.find():
        try:
            await bot.copy_message(u["_id"], ADMIN_ID, message.reply_to_message.message_id)
            s += 1
        except: f += 1
    await message.answer(f"📢 **Broadcast Finished**\nSuccess: {s}\nFailed: {f}")

@dp.message(Command("approve"))
async def approve_withdraw(message: types.Message, command: CommandObject):
    if message.from_id != ADMIN_ID: return
    try:
        w_id = ObjectId(command.args)
        w = await withdraws.find_one({"_id": w_id})
        if w:
            await withdraws.update_one({"_id": w_id}, {"$set": {"status": "paid"}})
            await bot.send_message(w["user_id"], "💰 Your withdrawal has been approved and paid!")
            await message.answer("Marked as Paid Successfully.")
    except: pass

@dp.callback_query(F.data == "check_fsub")
async def check_fsub_callback(callback: types.CallbackQuery):
    if await is_subscribed(callback.from_user.id):
        await callback.message.delete()
        await callback.message.answer("Access Granted! Welcome back.", reply_markup=main_menu_kb())
    else: await callback.answer("Please join all channels first!", show_alert=True)

async def main():
    Thread(target=run_flask).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
