from flask import Flask
import threading
import os
import asyncio
import time
import uuid
import aiohttp
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

from pymongo import MongoClient
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)
# ==============================
# CONFIG
# ==============================

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")

ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS").split(",")))

SHORTNER_API = "https://mdiskshort.in/api"
SHORTNER_KEY = os.getenv("SHORTNER_KEY")

BOT_USERNAME = "EarnMoneyPocket_bot"

TASK_REWARD = 0.50
DEFAULT_REF_REWARD = 1.00

MIN_WITHDRAW = 35

TASK_COOLDOWN = 60
TOKEN_EXPIRE = 300

# ==============================
# DATABASE
# ==============================

mongo = MongoClient(MONGO_URL)

db = mongo["earning_bot"]

users = db["users"]
tasks = db["tasks"]
withdrawals = db["withdrawals"]
channels = db["channels"]
settings = db["settings"]
warnings = db["warnings"]

# ==============================
# BOT INIT
# ==============================

app = Application.builder().token(BOT_TOKEN).build()

# ==============================
# DATABASE HELPERS
# ==============================


def get_user(user_id):

    user = users.find_one({"user_id": user_id})

    if not user:

        users.insert_one({
            "user_id": user_id,
            "balance": 0,
            "tasks": 0,
            "referrals": 0,
            "warnings": 0,
            "referrer": None,
            "custom_ref": None,
            "last_task": 0,
            "join_date": int(time.time())
        })

        user = users.find_one({"user_id": user_id})

    return user


def add_balance(user_id, amount):

    users.update_one(
        {"user_id": user_id},
        {"$inc": {"balance": amount}}
    )


def add_task_count(user_id):

    users.update_one(
        {"user_id": user_id},
        {"$inc": {"tasks": 1}}
    )


def add_referral(referrer):

    users.update_one(
        {"user_id": referrer},
        {"$inc": {"referrals": 1}}
    )


def get_balance(user_id):

    user = get_user(user_id)

    return user["balance"]


# ==============================
# TOKEN GENERATOR
# ==============================


def generate_token():

    return str(uuid.uuid4())


# ==============================
# TASK CREATION
# ==============================


def create_task(user_id):

    token = generate_token()

    tasks.insert_one({
        "token": token,
        "user_id": user_id,
        "created": int(time.time()),
        "status": "pending"
    })

    return token


# ==============================
# TOKEN VALIDATION
# ==============================


def validate_token(user_id, token):

    task = tasks.find_one({"token": token})

    if not task:
        return False, "invalid"

    if task["user_id"] != user_id:
        return False, "not_owner"

    if task["status"] != "pending":
        return False, "used"

    now = int(time.time())

    created = task["created"]

    if now - created < 30:
        return False, "bypass"

    if now - created > TOKEN_EXPIRE:
        return False, "expired"

    return True, task


# ==============================
# COMPLETE TASK
# ==============================


def complete_task(user_id, token):

    tasks.update_one(
        {"token": token},
        {"$set": {"status": "done"}}
    )

    add_balance(user_id, TASK_REWARD)

    add_task_count(user_id)


# ==============================
# WARNING SYSTEM
# ==============================


def add_warning(user_id):

    users.update_one(
        {"user_id": user_id},
        {"$inc": {"warnings": 1}}
    )

    user = users.find_one({"user_id": user_id})

    if user["warnings"] >= 3:
        users.update_one(
            {"user_id": user_id},
            {"$set": {"banned": True}}
        )

        return True

    return False
    # ==============================
# FORCE SUBSCRIBE CHECK
# ==============================

async def check_fsub(user_id, context: ContextTypes.DEFAULT_TYPE):

    required_channels = channels.find({"active": True})

    not_joined = []

    for ch in required_channels:

        try:
            member = await context.bot.get_chat_member(ch["channel_id"], user_id)

            if member.status not in ["member", "administrator", "creator"]:
                not_joined.append(ch)

        except:
            not_joined.append(ch)

    return not_joined


async def fsub_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, missing):

    buttons = []

    for ch in missing:
        buttons.append([InlineKeyboardButton(
            f"Join {ch['title']}",
            url=f"https://t.me/{ch['username']}"
        )])

    buttons.append([InlineKeyboardButton("✅ Joined", callback_data="recheck_fsub")])

    await update.message.reply_text(
        "⚠️ You must join all channels to use the bot.",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ==============================
# MAIN MENU
# ==============================

def main_menu():

    keyboard = [
        [InlineKeyboardButton("💰 Start Task", callback_data="start_task")],
        [InlineKeyboardButton("🎥 Tutorial", callback_data="tutorial")],
        [
            InlineKeyboardButton("👥 Refer & Earn", callback_data="refer"),
            InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")
        ],
        [
            InlineKeyboardButton("📊 Profile", callback_data="profile"),
            InlineKeyboardButton("💳 Withdraw", callback_data="withdraw")
        ],
        [InlineKeyboardButton("📢 Add Your Channel", callback_data="promo")]
    ]

    return InlineKeyboardMarkup(keyboard)


# ==============================
# START COMMAND
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    user = get_user(user_id)

    # referral detection

    if context.args:

        try:
            ref_id = int(context.args[0])

            if ref_id != user_id and user["referrer"] is None:

                users.update_one(
                    {"user_id": user_id},
                    {"$set": {"referrer": ref_id}}
                )

        except:
            pass

    # banned check

    if user.get("banned"):

        await update.message.reply_text("❌ You are banned.")
        return

    # force subscribe check

    missing = await check_fsub(user_id, context)

    if missing:

        await fsub_prompt(update, context, missing)
        return

    # welcome message

    text = (
        "👋 Welcome to the earning bot.\n\n"
        "💰 Complete tasks and earn money.\n"
        "👥 Invite friends to earn more.\n\n"
        "Choose an option below."
    )

    await update.message.reply_text(
        text,
        reply_markup=main_menu()
    )


# ==============================
# FSUB RECHECK
# ==============================

async def recheck_fsub(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user_id = query.from_user.id

    await query.answer()

    missing = await check_fsub(user_id, context)

    if missing:

        await query.message.reply_text("❌ You still haven't joined all channels.")
        return

    await query.message.reply_text(
        "✅ Access granted.",
        reply_markup=main_menu()
    )


# ==============================
# PROFILE
# ==============================

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user_id = query.from_user.id

    await query.answer()

    user = get_user(user_id)

    text = (
        f"👤 Your Profile\n\n"
        f"💰 Balance: ₹{user['balance']:.2f}\n"
        f"⚡ Tasks Completed: {user['tasks']}\n"
        f"👥 Referrals: {user['referrals']}\n"
        f"⚠️ Warnings: {user['warnings']}"
    )

    await query.message.edit_text(
        text,
        reply_markup=main_menu()
    )


# ==============================
# REFER SYSTEM
# ==============================

async def refer(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user_id = query.from_user.id

    await query.answer()

    user = get_user(user_id)

    ref_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"

    reward = user["custom_ref"] if user["custom_ref"] else DEFAULT_REF_REWARD

    text = (
        "👥 Refer & Earn\n\n"
        f"💰 Earn ₹{reward} per referral\n\n"
        "Share your link:\n"
        f"{ref_link}"
    )

    await query.message.edit_text(
        text,
        reply_markup=main_menu()
    )


# ==============================
# TUTORIAL BUTTON
# ==============================

async def tutorial(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    tutorial = settings.find_one({"key": "tutorial"})

    if tutorial:

        await context.bot.send_video(
            chat_id=query.from_user.id,
            video=tutorial["file_id"],
            caption="📺 How to complete tasks"
        )

    else:

        await query.message.reply_text("Tutorial not set yet.")


# ==============================
# HANDLERS
# ==============================

app.add_handler(CommandHandler("start", start))

app.add_handler(CallbackQueryHandler(recheck_fsub, pattern="recheck_fsub"))
app.add_handler(CallbackQueryHandler(profile, pattern="profile"))
app.add_handler(CallbackQueryHandler(refer, pattern="refer"))
app.add_handler(CallbackQueryHandler(tutorial, pattern="tutorial"))
# ==============================
# TASK COOLDOWN CHECK
# ==============================

def check_cooldown(user_id):

    user = users.find_one({"user_id": user_id})

    now = int(time.time())

    if now - user["last_task"] < TASK_COOLDOWN:
        return False

    return True


def update_last_task(user_id):

    users.update_one(
        {"user_id": user_id},
        {"$set": {"last_task": int(time.time())}}
    )


# ==============================
# SHORTLINK GENERATOR
# ==============================

async def create_shortlink(url):

    api_url = f"https://mdiskshort.in/api?api={SHORTNER_KEY}&url={url}"

    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as resp:

            data = await resp.json()

            if data.get("status") == "success":
                return data.get("shortenedUrl")

            return None


# ==============================
# START TASK BUTTON
# ==============================

async def start_task(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user_id = query.from_user.id

    await query.answer()

    user = get_user(user_id)

    # banned check
    if user.get("banned"):
        await query.message.reply_text("❌ You are banned.")
        return

    # force subscribe check
    missing = await check_fsub(user_id, context)

    if missing:
        await query.message.reply_text("⚠️ Join required channels first.")
        return

    # cooldown check
    if not check_cooldown(user_id):

        await query.message.reply_text(
            "⏳ Please wait before starting another task."
        )
        return

    # create token
    token = create_task(user_id)

    # deep link
    deep_link = f"https://t.me/{BOT_USERNAME}?start=verify_{token}"

    # shortlink
    shortlink = await create_shortlink(deep_link)

    # tutorial button
    buttons = [
        [InlineKeyboardButton("🔗 Open Shortlink", url=shortlink)],
        [InlineKeyboardButton("🎥 Tutorial", callback_data="tutorial")]
    ]

    update_last_task(user_id)

    text = (
        "💰 Task Started\n\n"
        "1️⃣ Open the shortlink\n"
        "2️⃣ Complete verification\n"
        "3️⃣ You will receive reward\n\n"
        "⚠️ Do not bypass the system."
    )

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ==============================
# TOKEN VERIFICATION
# ==============================

async def verify_token(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if not context.args:
        return

    arg = context.args[0]

    if not arg.startswith("verify_"):
        return

    token = arg.replace("verify_", "")

    valid, result = validate_token(user_id, token)

    if not valid:

        if result == "bypass":

            banned = add_warning(user_id)

            if banned:

                await update.message.reply_text(
                    "🚫 You are banned for repeated bypass attempts."
                )

                return

            await update.message.reply_text(
                "⚠️ Bypass detected.\n\n"
                "Generate a new task link and try again."
            )

            return

        await update.message.reply_text(
            "❌ Invalid or expired task."
        )

        return

    # complete task
    complete_task(user_id, token)

    await update.message.reply_text(
        f"✅ Task verified!\n\n"
        f"💰 Earned: ₹{TASK_REWARD:.2f}",
        reply_markup=main_menu()
    )


# ==============================
# HANDLER
# ==============================

app.add_handler(CallbackQueryHandler(start_task, pattern="start_task"))
app.add_handler(CommandHandler("start", verify_token))
# ==============================
# REFERRAL REWARD LOGIC
# ==============================

def process_referral_reward(user_id):

    user = users.find_one({"user_id": user_id})

    referrer = user.get("referrer")

    if not referrer:
        return

    ref_user = users.find_one({"user_id": referrer})

    if not ref_user:
        return

    # reward only on first task
    if user["tasks"] == 1:

        reward = ref_user["custom_ref"] if ref_user.get("custom_ref") else DEFAULT_REF_REWARD

        users.update_one(
            {"user_id": referrer},
            {"$inc": {"balance": reward}}
        )

        add_referral(referrer)


# ==============================
# UPDATE TASK COMPLETE HOOK
# ==============================

def complete_task(user_id, token):

    tasks.update_one(
        {"token": token},
        {"$set": {"status": "done"}}
    )

    add_balance(user_id, TASK_REWARD)

    add_task_count(user_id)

    process_referral_reward(user_id)


# ==============================
# LEADERBOARD SYSTEM
# ==============================

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    top_users = users.find().sort("tasks", -1).limit(10)

    text = "🏆 Top Task Earners\n\n"

    rank = 1

    for user in top_users:

        text += f"{rank}. {user['user_id']} — {user['tasks']} tasks\n"

        rank += 1

    await query.message.edit_text(
        text,
        reply_markup=main_menu()
    )


# ==============================
# PROFILE EXTENDED
# ==============================

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user_id = query.from_user.id

    await query.answer()

    user = users.find_one({"user_id": user_id})

    balance = user["balance"]
    tasks_done = user["tasks"]
    refs = user["referrals"]
    warns = user["warnings"]

    rank = users.count_documents({"tasks": {"$gt": tasks_done}}) + 1

    text = (
        "📊 Your Dashboard\n\n"
        f"💰 Balance: ₹{balance:.2f}\n"
        f"⚡ Tasks Completed: {tasks_done}\n"
        f"👥 Referrals: {refs}\n"
        f"🏆 Rank: #{rank}\n"
        f"⚠️ Warnings: {warns}"
    )

    await query.message.edit_text(
        text,
        reply_markup=main_menu()
    )


# ==============================
# STATS COMMAND (ADMIN)
# ==============================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if user_id not in ADMIN_IDS:
        return

    total_users = users.count_documents({})
    total_tasks = users.aggregate([
        {"$group": {"_id": None, "sum": {"$sum": "$tasks"}}}
    ])

    tasks_count = 0
    for i in total_tasks:
        tasks_count = i["sum"]

    total_paid = users.aggregate([
        {"$group": {"_id": None, "sum": {"$sum": "$balance"}}}
    ])

    paid = 0
    for i in total_paid:
        paid = i["sum"]

    pending_withdraw = withdrawals.count_documents({"status": "pending"})

    text = (
        "📊 Bot Statistics\n\n"
        f"👤 Users: {total_users}\n"
        f"⚡ Tasks Completed: {tasks_count}\n"
        f"💰 Total Balance Held: ₹{paid:.2f}\n"
        f"💳 Pending Withdrawals: {pending_withdraw}"
    )

    await update.message.reply_text(text)


# ==============================
# HANDLERS
# ==============================

app.add_handler(CallbackQueryHandler(leaderboard, pattern="leaderboard"))
app.add_handler(CommandHandler("stats", stats))
# ==============================
# WITHDRAW REQUEST
# ==============================

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    user_id = query.from_user.id

    await query.answer()

    user = users.find_one({"user_id": user_id})

    balance = user["balance"]

    if balance < MIN_WITHDRAW:

        await query.message.reply_text(
            f"❌ Minimum withdraw is ₹{MIN_WITHDRAW}"
        )
        return

    pending = withdrawals.find_one({
        "user_id": user_id,
        "status": "pending"
    })

    if pending:

        await query.message.reply_text(
            "⚠️ You already have a pending withdrawal."
        )
        return

    context.user_data["withdraw_mode"] = True

    await query.message.reply_text(
        "💳 Send your payment details.\n\nExample:\nUPI: name@upi"
    )


# ==============================
# RECEIVE PAYMENT DETAILS
# ==============================

async def withdraw_details(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if not context.user_data.get("withdraw_mode"):
        return

    payment = update.message.text

    user = users.find_one({"user_id": user_id})

    amount = user["balance"]

    withdraw_id = str(uuid.uuid4())

    withdrawals.insert_one({
        "withdraw_id": withdraw_id,
        "user_id": user_id,
        "amount": amount,
        "payment": payment,
        "status": "pending",
        "time": int(time.time())
    })

    users.update_one(
        {"user_id": user_id},
        {"$set": {"balance": 0}}
    )

    context.user_data["withdraw_mode"] = False

    await update.message.reply_text(
        "✅ Withdrawal request submitted.\nAdmin will review it soon."
    )

    # notify admin
    for admin in ADMIN_IDS:

        text = (
            "💳 New Withdrawal Request\n\n"
            f"User: {user_id}\n"
            f"Amount: ₹{amount}\n"
            f"Payment: {payment}\n"
            f"ID: {withdraw_id}"
        )

        buttons = [
            [
                InlineKeyboardButton(
                    "✅ Approve",
                    callback_data=f"approve_{withdraw_id}"
                ),
                InlineKeyboardButton(
                    "❌ Reject",
                    callback_data=f"reject_{withdraw_id}"
                )
            ]
        ]

        await context.bot.send_message(
            chat_id=admin,
            text=text,
            reply_markup=InlineKeyboardMarkup(buttons)
        )


# ==============================
# ADMIN WITHDRAW PANEL
# ==============================

async def withdrawals_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if user_id not in ADMIN_IDS:
        return

    pending = withdrawals.find({"status": "pending"})

    text = "💳 Pending Withdrawals\n\n"

    for w in pending:

        text += (
            f"ID: {w['withdraw_id']}\n"
            f"User: {w['user_id']}\n"
            f"Amount: ₹{w['amount']}\n\n"
        )

    await update.message.reply_text(text)


# ==============================
# APPROVE WITHDRAW
# ==============================

async def approve_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    withdraw_id = query.data.replace("approve_", "")

    w = withdrawals.find_one({"withdraw_id": withdraw_id})

    if not w:
        return

    withdrawals.update_one(
        {"withdraw_id": withdraw_id},
        {"$set": {"status": "approved"}}
    )

    await query.message.edit_text(
        "✅ Withdrawal approved"
    )


# ==============================
# REJECT WITHDRAW
# ==============================

async def reject_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    withdraw_id = query.data.replace("reject_", "")

    w = withdrawals.find_one({"withdraw_id": withdraw_id})

    if not w:
        return

    withdrawals.update_one(
        {"withdraw_id": withdraw_id},
        {"$set": {"status": "rejected"}}
    )

    # refund user
    users.update_one(
        {"user_id": w["user_id"]},
        {"$inc": {"balance": w["amount"]}}
    )

    await query.message.edit_text(
        "❌ Withdrawal rejected"
    )


# ==============================
# HANDLERS
# ==============================

app.add_handler(CallbackQueryHandler(withdraw, pattern="withdraw"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_details))

app.add_handler(CommandHandler("withdrawals", withdrawals_panel))

app.add_handler(CallbackQueryHandler(approve_withdraw, pattern="approve_"))
app.add_handler(CallbackQueryHandler(reject_withdraw, pattern="reject_"))
# ==============================
# BROADCAST SYSTEM
# ==============================

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if user_id not in ADMIN_IDS:
        return

    if not update.message.reply_to_message:

        await update.message.reply_text(
            "Reply to a message with /broadcast"
        )
        return

    msg = update.message.reply_to_message

    all_users = users.find()

    sent = 0
    failed = 0

    for u in all_users:

        try:

            await msg.copy(chat_id=u["user_id"])

            sent += 1

            await asyncio.sleep(0.05)

        except:

            failed += 1

    await update.message.reply_text(
        f"📢 Broadcast Complete\n\n"
        f"Sent: {sent}\n"
        f"Failed: {failed}"
    )


# ==============================
# TUTORIAL SETUP
# ==============================

async def set_tutorial(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if user_id not in ADMIN_IDS:
        return

    if not update.message.reply_to_message:

        await update.message.reply_text(
            "Reply to a video with /tutorial"
        )
        return

    msg = update.message.reply_to_message

    if not msg.video:

        await update.message.reply_text("Please reply to a video.")
        return

    file_id = msg.video.file_id

    settings.update_one(
        {"key": "tutorial"},
        {"$set": {"file_id": file_id}},
        upsert=True
    )

    await update.message.reply_text("✅ Tutorial saved.")


# ==============================
# ADD FSUB CHANNEL
# ==============================

async def add_fsub(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if user_id not in ADMIN_IDS:
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "Usage:\n/addfsub channel_id username"
        )
        return

    channel_id = int(context.args[0])
    username = context.args[1]

    channels.insert_one({
        "channel_id": channel_id,
        "username": username,
        "title": username,
        "active": True
    })

    await update.message.reply_text("✅ Channel added.")


# ==============================
# REMOVE FSUB CHANNEL
# ==============================

async def remove_fsub(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if user_id not in ADMIN_IDS:
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n/removefsub channel_id"
        )
        return

    channel_id = int(context.args[0])

    channels.delete_one({"channel_id": channel_id})

    await update.message.reply_text("❌ Channel removed.")


# ==============================
# CUSTOM REFERRAL RATE
# ==============================

async def set_refer(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if user_id not in ADMIN_IDS:
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "Usage:\n/setrefer user_id amount"
        )
        return

    target = int(context.args[0])
    amount = float(context.args[1])

    users.update_one(
        {"user_id": target},
        {"$set": {"custom_ref": amount}}
    )

    await update.message.reply_text(
        f"✅ Custom referral set: ₹{amount}"
    )


# ==============================
# BAN USER
# ==============================

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id not in ADMIN_IDS:
        return

    if not context.args:
        return

    target = int(context.args[0])

    users.update_one(
        {"user_id": target},
        {"$set": {"banned": True}}
    )

    await update.message.reply_text("🚫 User banned.")


# ==============================
# UNBAN USER
# ==============================

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id not in ADMIN_IDS:
        return

    if not context.args:
        return

    target = int(context.args[0])

    users.update_one(
        {"user_id": target},
        {"$set": {"banned": False}}
    )

    await update.message.reply_text("✅ User unbanned.")


# ==============================
# HANDLERS
# ==============================

app.add_handler(CommandHandler("broadcast", broadcast))
app.add_handler(CommandHandler("tutorial", set_tutorial))

app.add_handler(CommandHandler("addfsub", add_fsub))
app.add_handler(CommandHandler("removefsub", remove_fsub))

app.add_handler(CommandHandler("setrefer", set_refer))

app.add_handler(CommandHandler("ban", ban_user))
app.add_handler(CommandHandler("unban", unban_user))
# ==============================
# CHANNEL PROMOTION SYSTEM
# ==============================

async def promotion_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    text = (
        "📢 Promote Your Channel\n\n"
        "Get real Telegram members from our task network.\n\n"
        "Choose a promotion plan:"
    )

    buttons = [
        [InlineKeyboardButton("📅 Weekly Plan – ₹49", callback_data="plan_week")],
        [InlineKeyboardButton("📆 Monthly Plan – ₹149", callback_data="plan_month")],
        [InlineKeyboardButton("⚡ Daily Plan – ₹15", callback_data="plan_day")],
        [InlineKeyboardButton("💬 Contact Admin", callback_data="contact_admin")]
    ]

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ==============================
# PLAN DETAILS
# ==============================

async def plan_details(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    plan = query.data

    if plan == "plan_week":
        price = "₹49 / week"

    elif plan == "plan_month":
        price = "₹149 / month"

    else:
        price = "₹15 / day"

    text = (
        "📢 Channel Promotion\n\n"
        f"Plan: {price}\n\n"
        "Your channel will be added to our bot tasks.\n"
        "Users will join your channel to complete tasks.\n\n"
        "Contact admin to activate your promotion."
    )

    buttons = [
        [InlineKeyboardButton("💬 Message Admin", url="https://t.me/theprofessorreport_bot")],
        [InlineKeyboardButton("⬅ Back", callback_data="promo")]
    ]

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ==============================
# CONTACT ADMIN BUTTON
# ==============================

async def contact_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    text = (
        "💬 Contact Admin\n\n"
        "To add your channel in the bot promotion system,\n"
        "message the admin below."
    )

    buttons = [
        [InlineKeyboardButton("📩 Message Admin", url="https://t.me/theprofessorreport_bot")],
        [InlineKeyboardButton("⬅ Back", callback_data="promo")]
    ]

    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ==============================
# EXTRA CALLBACK HANDLERS
# ==============================

app.add_handler(CallbackQueryHandler(promotion_menu, pattern="promo"))
app.add_handler(CallbackQueryHandler(plan_details, pattern="plan_"))
app.add_handler(CallbackQueryHandler(contact_admin, pattern="contact_admin"))


# ==============================
# BOT STARTUP
# ==============================

if __name__ == "__main__":

    threading.Thread(target=run_flask).start()

    print("Bot running...")

    app.run_polling()
