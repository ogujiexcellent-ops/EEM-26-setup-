import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from config import TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_ID
from database import (
    init_db,
    get_user,
    upsert_user,
    set_user_method,
    advance_aam_day,
    set_integration_step,
    save_whatsapp_group_link,
    save_fb_ads_details,
    save_message,
    get_conversation_history,
    clear_conversation_history,
)
from curriculum import get_day_content, get_total_days, get_platform_for_day
from ai_assistant import get_ai_response

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Conversation states
CHOOSING_METHOD = 0
AAM_LEARNING = 1
AAM_CHATTING = 2
INTEGRATION_STEP1 = 10
INTEGRATION_STEP2 = 11
INTEGRATION_STEP3_WAIT = 12
INTEGRATION_STEP4 = 13
ADMIN_SEND_FB_DETAILS = 20


# ─── Helpers ────────────────────────────────────────────────────────────────

def method_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 AAM Method (18-Day Program)", callback_data="method_aam")],
        [InlineKeyboardButton("⚡ Integration Method (₦90k)", callback_data="method_integration")],
    ])


def aam_keyboard(current_day: int, total_days: int):
    buttons = []
    if current_day <= total_days:
        buttons.append([InlineKeyboardButton(
            f"📖 Start Day {current_day}", callback_data=f"aam_day_{current_day}"
        )])
    if current_day > 1:
        buttons.append([InlineKeyboardButton(
            f"🔙 Review Day {current_day - 1}", callback_data=f"aam_day_{current_day - 1}"
        )])
    buttons.append([InlineKeyboardButton("💬 Ask a Question", callback_data="aam_ask")])
    buttons.append([InlineKeyboardButton("🔄 Change Method", callback_data="change_method")])
    return InlineKeyboardMarkup(buttons)


def integration_confirm_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Done! I've completed this step", callback_data="integration_done"),
            InlineKeyboardButton("❓ Need Help", callback_data="integration_help"),
        ]
    ])


def back_to_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
    ])


# ─── /start command ──────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    await upsert_user(user.id, user.username or "", user.first_name or "")

    db_user = await get_user(user.id)

    if db_user and db_user.get("method"):
        method = db_user["method"]
        if method == "aam":
            day = db_user.get("aam_current_day", 1)
            total = get_total_days()
            text = (
                f"Welcome back, {user.first_name}! 👋\n\n"
                f"You're on the **AAM Method** — currently on Day {day} of {total}.\n\n"
                "What would you like to do?"
            )
            await update.message.reply_text(
                text, parse_mode="Markdown",
                reply_markup=aam_keyboard(day, total)
            )
            return AAM_LEARNING
        elif method == "integration":
            step = db_user.get("integration_step", 1)
            return await _resume_integration(update, context, step, db_user)

    welcome_text = (
        f"👋 Hello {user.first_name}! Welcome to **EEM 26 — ECO SYSTEM EXPANSION MODEL**!\n\n"
        "I'm your personal promotion coach. I'll guide you step by step through your chosen method to "
        "start generating leads and growing your business.\n\n"
        "We have **two powerful methods** for you:\n\n"
        "📚 **AAM Method** — An 18-day structured learning program teaching you how to "
        "manually generate leads from TikTok, Google, and WhatsApp. Perfect if you want to "
        "learn the skills yourself.\n\n"
        "⚡ **Integration Method** — A faster paid approach where you set up a WhatsApp group "
        "and fund Facebook ads (₦90,000) to automatically receive leads. Best if you have the "
        "funds and want results quickly.\n\n"
        "Which method would you like to use?"
    )
    await update.message.reply_text(
        welcome_text, parse_mode="Markdown", reply_markup=method_keyboard()
    )
    return CHOOSING_METHOD


async def _resume_integration(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    step: int,
    db_user: dict,
) -> int:
    user = update.effective_user
    msg = update.message or update.callback_query.message

    if step == 1:
        text = (
            f"Welcome back, {user.first_name}! 👋\n\n"
            "You're on the **Integration Method** — Step 1.\n\n"
            "Please send me your **WhatsApp group link** to get started."
        )
        await msg.reply_text(text, parse_mode="Markdown")
        return INTEGRATION_STEP1
    elif step == 2:
        text = (
            f"Welcome back, {user.first_name}! 👋\n\n"
            "You're on the **Integration Method** — Step 2.\n\n"
            "Please complete these actions on your WhatsApp group:\n\n"
            "1️⃣ Change your group name to:\n"
            "**ECO SYSTEM EXPANSION MODEL EEM 26**\n\n"
            "2️⃣ Turn off **ALL** group permissions (only admins can send messages, add members, edit info)\n\n"
            "Once done, tap the button below."
        )
        await msg.reply_text(
            text, parse_mode="Markdown",
            reply_markup=integration_confirm_keyboard()
        )
        return INTEGRATION_STEP2
    elif step == 3:
        text = (
            f"Welcome back, {user.first_name}! 👋\n\n"
            "You're on **Integration Method — Step 3**.\n\n"
            "⏳ Your submission is being reviewed. The admin is generating your Facebook ads details.\n\n"
            "You'll receive a message here as soon as it's ready. Please be patient!"
        )
        await msg.reply_text(text, parse_mode="Markdown", reply_markup=back_to_menu_keyboard())
        return INTEGRATION_STEP3_WAIT
    elif step == 4:
        fb_details = db_user.get("fb_ads_details", "")
        text = (
            f"Welcome back, {user.first_name}! 👋\n\n"
            "You're on **Integration Method — Step 4**.\n\n"
            "Here are your Facebook ads details:\n\n"
            f"{fb_details}\n\n"
            "💰 Fund **₦90,000** to Facebook using the details above.\n\n"
            "Once funded, your leads will start coming in automatically! 🎉\n\n"
            "Let me know when you've completed the funding!"
        )
        await msg.reply_text(text, parse_mode="Markdown", reply_markup=integration_confirm_keyboard())
        return INTEGRATION_STEP4

    return CHOOSING_METHOD


# ─── Method Selection ────────────────────────────────────────────────────────

async def method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    data = query.data

    if data == "method_aam":
        await set_user_method(user_id, "aam")
        await advance_aam_day(user_id, 1)
        total = get_total_days()

        text = (
            "🎉 Great choice! You've chosen the **AAM Method**.\n\n"
            "Over the next 18 days, you'll learn:\n"
            "• Days 1-6: TikTok lead generation\n"
            "• Days 7-12: Google lead generation\n"
            "• Days 13-18: WhatsApp lead generation\n\n"
            "Consistency is key! Try to complete one day at a time and implement what you learn.\n\n"
            "Ready to start **Day 1**? 👇"
        )
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=aam_keyboard(1, total)
        )
        return AAM_LEARNING

    elif data == "method_integration":
        await set_user_method(user_id, "integration")
        await set_integration_step(user_id, 1)

        text = (
            "⚡ Great choice! You've chosen the **Integration Method**.\n\n"
            "Here's the overview of what we'll do:\n\n"
            "**Step 1:** Send your WhatsApp group link\n"
            "**Step 2:** Rename your group & turn off all permissions\n"
            "**Step 3:** Admin generates your Facebook ads details\n"
            "**Step 4:** Fund ₦90,000 to Facebook & start receiving leads!\n\n"
            "Let's start with **Step 1**:\n\n"
            "📲 Please send me your **WhatsApp group link** (the invite link for your group).\n\n"
            "_Example: https://chat.whatsapp.com/xxxxxxxxxx_"
        )
        await query.edit_message_text(text, parse_mode="Markdown")
        return INTEGRATION_STEP1

    elif data == "change_method":
        await set_user_method(user_id, "")
        await clear_conversation_history(user_id)
        text = (
            "No problem! Let's choose a different method.\n\n"
            "Which promotion method would you like to use?"
        )
        await query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=method_keyboard()
        )
        return CHOOSING_METHOD

    elif data == "main_menu":
        db_user = await get_user(user_id)
        if db_user and db_user.get("method") == "aam":
            day = db_user.get("aam_current_day", 1)
            total = get_total_days()
            await query.edit_message_text(
                f"Welcome back! You're on Day {day} of {total}. What would you like to do?",
                parse_mode="Markdown",
                reply_markup=aam_keyboard(day, total),
            )
            return AAM_LEARNING
        else:
            await query.edit_message_text(
                "Which promotion method would you like to use?",
                parse_mode="Markdown",
                reply_markup=method_keyboard(),
            )
            return CHOOSING_METHOD

    return CHOOSING_METHOD


# ─── AAM Flow ────────────────────────────────────────────────────────────────

async def aam_day_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = update.effective_user.id
    total = get_total_days()

    if data == "aam_ask":
        await query.edit_message_text(
            "💬 Go ahead and ask your question! I'm here to help.\n\n"
            "_You can ask anything about lead generation, the platforms, or your progress._",
            parse_mode="Markdown",
        )
        return AAM_CHATTING

    if data.startswith("aam_day_"):
        day = int(data.split("_")[-1])
        day_content = get_day_content(day)

        if not day_content:
            await query.edit_message_text("Sorry, that day's content isn't available.")
            return AAM_LEARNING

        await advance_aam_day(user_id, day)

        text = f"*{day_content['title']}*\n\n{day_content['content']}"

        next_day = day + 1
        buttons = []
        if next_day <= total:
            buttons.append([InlineKeyboardButton(
                f"➡️ Next: Day {next_day}", callback_data=f"aam_day_{next_day}"
            )])
        else:
            buttons.append([InlineKeyboardButton(
                "🎉 You've completed the full program!", callback_data="aam_complete"
            )])
        buttons.append([InlineKeyboardButton("💬 Ask a Question", callback_data="aam_ask")])
        buttons.append([InlineKeyboardButton("📋 Back to Menu", callback_data=f"aam_menu_{day}")])

        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return AAM_LEARNING

    if data == "aam_complete":
        text = (
            "🏆 **CONGRATULATIONS!** 🏆\n\n"
            "You've completed all 18 days of the AAM Method!\n\n"
            "You now have the knowledge to generate leads from:\n"
            "✅ TikTok\n"
            "✅ Google\n"
            "✅ WhatsApp\n\n"
            "Remember: Knowledge without action is worthless. Start implementing TODAY!\n\n"
            "Keep coming back to review any day's content or ask questions. I'm always here to help! 💪"
        )
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Ask the Coach a Question", callback_data="aam_ask")],
                [InlineKeyboardButton("🔄 Restart Program", callback_data="aam_day_1")],
            ]),
        )
        return AAM_CHATTING

    if data.startswith("aam_menu_"):
        day = int(data.split("_")[-1])
        db_user = await get_user(user_id)
        current_day = db_user.get("aam_current_day", 1) if db_user else 1
        await query.edit_message_text(
            f"You're on Day {current_day} of {total}. What would you like to do?",
            parse_mode="Markdown",
            reply_markup=aam_keyboard(current_day, total),
        )
        return AAM_LEARNING

    return AAM_LEARNING


async def aam_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_message = update.message.text

    await update.message.chat.send_action("typing")

    db_user = await get_user(user.id)
    current_day = db_user.get("aam_current_day", 1) if db_user else 1
    platform = get_platform_for_day(current_day)

    context_str = (
        f"User is on Day {current_day} of the AAM Method (currently learning {platform} lead generation). "
        f"Total program: 18 days."
    )

    history = await get_conversation_history(user.id)
    response = await get_ai_response(user_message, history, context=context_str)

    await save_message(user.id, "user", user_message)
    await save_message(user.id, "assistant", response)

    total = get_total_days()
    await update.message.reply_text(
        response,
        parse_mode="Markdown",
        reply_markup=aam_keyboard(current_day, total),
    )
    return AAM_CHATTING


# ─── Integration Flow ────────────────────────────────────────────────────────

async def integration_step1_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    text = update.message.text.strip()

    if not (text.startswith("https://chat.whatsapp.com/") or text.startswith("http://chat.whatsapp.com/")):
        await update.message.reply_text(
            "⚠️ That doesn't look like a valid WhatsApp group link.\n\n"
            "A valid link looks like:\n"
            "`https://chat.whatsapp.com/xxxxxxxxxx`\n\n"
            "Please send your correct WhatsApp group invite link.",
            parse_mode="Markdown",
        )
        return INTEGRATION_STEP1

    await save_whatsapp_group_link(user.id, text)
    await set_integration_step(user.id, 2)

    step2_text = (
        "✅ Great! Your WhatsApp group link has been received.\n\n"
        "Now for **Step 2**, please do the following in your WhatsApp group:\n\n"
        "1️⃣ **Change your group name** to exactly:\n"
        "`ECO SYSTEM EXPANSION MODEL EEM 26`\n\n"
        "2️⃣ **Turn off ALL group permissions:**\n"
        "   • Go to Group Info → Group Settings\n"
        "   • Set 'Send Messages' to Admins Only\n"
        "   • Set 'Edit Group Info' to Admins Only\n"
        "   • Set 'Add Members' to Admins Only\n\n"
        "Once you've done both, tap the button below! 👇"
    )
    await update.message.reply_text(
        step2_text,
        parse_mode="Markdown",
        reply_markup=integration_confirm_keyboard(),
    )

    try:
        admin_text = (
            f"🔔 **New Integration Submission**\n\n"
            f"User: {user.first_name} (@{user.username or 'no username'})\n"
            f"User ID: `{user.id}`\n"
            f"WhatsApp Group Link: {text}\n\n"
            f"Status: Waiting for user to complete Step 2"
        )
        await context.bot.send_message(
            ADMIN_TELEGRAM_ID, admin_text, parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")

    return INTEGRATION_STEP2


async def integration_step2_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    if query.data == "integration_help":
        help_text = (
            "🆘 **Need help with Step 2?**\n\n"
            "**How to change group name:**\n"
            "1. Open your WhatsApp group\n"
            "2. Tap the group name at the top\n"
            "3. Tap the pencil icon (edit)\n"
            "4. Type: `ECO SYSTEM EXPANSION MODEL EEM 26`\n"
            "5. Save\n\n"
            "**How to turn off all permissions:**\n"
            "1. Open group → Group Info\n"
            "2. Tap 'Group Settings'\n"
            "3. Set 'Send Messages' → 'Only Admins'\n"
            "4. Set 'Edit Group Info' → 'Only Admins'\n"
            "5. If available, set 'Add Members' → 'Only Admins'\n\n"
            "Done? Tap the button below! 👇"
        )
        await query.edit_message_text(
            help_text,
            parse_mode="Markdown",
            reply_markup=integration_confirm_keyboard(),
        )
        return INTEGRATION_STEP2

    if query.data == "integration_done":
        await set_integration_step(user.id, 3)

        db_user = await get_user(user.id)
        group_link = db_user.get("whatsapp_group_link", "N/A") if db_user else "N/A"

        step3_text = (
            "✅ Excellent! Step 2 complete!\n\n"
            "**Step 3 — Admin Review:**\n\n"
            "Your information has been sent to the admin. They will review your group setup and "
            "generate your **Facebook ads details**.\n\n"
            "⏳ Please wait — you will receive a message here with your Facebook ads details soon.\n\n"
            "_This usually takes a few hours. Please be patient!_"
        )
        await query.edit_message_text(step3_text, parse_mode="Markdown")

        try:
            admin_text = (
                f"🔔 **Integration Step 2 Complete!**\n\n"
                f"User: {user.first_name} (@{user.username or 'no username'})\n"
                f"User ID: `{user.id}`\n"
                f"Group Link: {group_link}\n\n"
                f"⚡ **Action Required:** Generate Facebook ads details and send to this user.\n\n"
                f"Use this command to send FB ads details:\n"
                f"`/send_fb_details {user.id} <your_fb_ads_details_here>`"
            )
            await context.bot.send_message(
                ADMIN_TELEGRAM_ID, admin_text, parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")

        return INTEGRATION_STEP3_WAIT

    return INTEGRATION_STEP2


async def integration_step4_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    if query.data == "integration_help":
        db_user = await get_user(user.id)
        fb_details = db_user.get("fb_ads_details", "Contact admin for details.") if db_user else ""
        help_text = (
            "🆘 **Need help funding Facebook ads?**\n\n"
            f"Your Facebook ads details:\n{fb_details}\n\n"
            "**Steps to fund:**\n"
            "1. Open Facebook → Ads Manager\n"
            "2. Use the account details provided above\n"
            "3. Add ₦90,000 as your ad budget\n"
            "4. Confirm payment\n\n"
            "If you're still stuck, please contact the admin directly for assistance."
        )
        await query.edit_message_text(
            help_text,
            parse_mode="Markdown",
            reply_markup=integration_confirm_keyboard(),
        )
        return INTEGRATION_STEP4

    if query.data == "integration_done":
        await set_integration_step(user.id, 5)

        final_text = (
            "🎉 **AMAZING! Step 4 Complete!**\n\n"
            "You've successfully funded your Facebook ads!\n\n"
            "**What happens next:**\n"
            "• Facebook will review and activate your ad (usually within 24-48 hours)\n"
            "• Once active, leads will start flowing into your WhatsApp group automatically\n"
            "• You'll receive notifications in your group as new leads join\n\n"
            "🏆 You've completed the **Integration Method**! Congratulations!\n\n"
            "If you have any questions or need support, just send me a message anytime. "
            "I'm here to help you succeed! 💪\n\n"
            "_Your journey to consistent lead generation has begun!_"
        )
        await query.edit_message_text(final_text, parse_mode="Markdown")

        try:
            admin_text = (
                f"✅ **Integration Complete!**\n\n"
                f"User: {user.first_name} (@{user.username or 'no username'})\n"
                f"User ID: `{user.id}`\n\n"
                f"User has confirmed Facebook ads funding. All 4 steps completed!"
            )
            await context.bot.send_message(
                ADMIN_TELEGRAM_ID, admin_text, parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")

        return ConversationHandler.END

    return INTEGRATION_STEP4


# ─── Admin Commands ──────────────────────────────────────────────────────────

async def admin_send_fb_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "Usage: `/send_fb_details <user_id> <details>`\n\n"
            "Example: `/send_fb_details 123456789 Ad Account ID: 123456\\nBusiness Manager ID: 789`",
            parse_mode="Markdown",
        )
        return

    try:
        target_user_id = int(args[0])
        fb_details = " ".join(args[1:]).replace("\\n", "\n")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Please provide a valid numeric user ID.")
        return

    await save_fb_ads_details(target_user_id, fb_details)
    await set_integration_step(target_user_id, 4)

    user_message = (
        "🎉 **Great news!** Your Facebook ads details are ready!\n\n"
        "**Step 4 — Fund Your Facebook Ads:**\n\n"
        f"{fb_details}\n\n"
        "💰 Please fund **₦90,000** to Facebook using the details above.\n\n"
        "Once you've completed the funding, use the button below to confirm!"
    )
    try:
        await context.bot.send_message(
            target_user_id,
            user_message,
            parse_mode="Markdown",
            reply_markup=integration_confirm_keyboard(),
        )
        await update.message.reply_text(
            f"✅ Facebook ads details successfully sent to user `{target_user_id}`.",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to send message to user: {e}")


async def admin_list_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    from database import get_pending_integration_users
    pending = await get_pending_integration_users()

    if not pending:
        await update.message.reply_text("✅ No users currently waiting for FB ads details.")
        return

    lines = ["📋 **Users waiting for FB ads details:**\n"]
    for u in pending:
        lines.append(
            f"• {u['first_name']} (@{u.get('username') or 'no username'})\n"
            f"  ID: `{u['user_id']}`\n"
            f"  Group: {u.get('whatsapp_group_link', 'N/A')}\n"
        )
    lines.append("\nUse `/send_fb_details <user_id> <details>` to send their ads details.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─── General message handler ─────────────────────────────────────────────────

async def general_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_message = update.message.text

    await update.message.chat.send_action("typing")

    db_user = await get_user(user.id)

    if not db_user or not db_user.get("method"):
        await update.message.reply_text(
            "Please choose your promotion method to get started! 👇",
            reply_markup=method_keyboard(),
        )
        return CHOOSING_METHOD

    method = db_user["method"]
    if method == "aam":
        current_day = db_user.get("aam_current_day", 1)
        platform = get_platform_for_day(current_day)
        context_str = (
            f"User is on Day {current_day} of the AAM Method (currently learning {platform} "
            f"lead generation). Total program: 18 days."
        )
        state = AAM_CHATTING
    else:
        step = db_user.get("integration_step", 1)
        context_str = f"User is on Step {step} of the Integration Method."
        state = INTEGRATION_STEP3_WAIT

    history = await get_conversation_history(user.id)
    response = await get_ai_response(user_message, history, context=context_str)

    await save_message(user.id, "user", user_message)
    await save_message(user.id, "assistant", response)

    if method == "aam":
        total = get_total_days()
        current_day = db_user.get("aam_current_day", 1)
        await update.message.reply_text(
            response,
            parse_mode="Markdown",
            reply_markup=aam_keyboard(current_day, total),
        )
    else:
        await update.message.reply_text(response, parse_mode="Markdown")

    return state


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    import asyncio

    async def post_init(app: Application) -> None:
        await init_db()
        logger.info("Database initialized.")

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_METHOD: [
                CallbackQueryHandler(method_callback),
            ],
            AAM_LEARNING: [
                CallbackQueryHandler(aam_day_callback, pattern=r"^(aam_day_|aam_ask|aam_complete|aam_menu_|change_method|main_menu)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, aam_chat_message),
            ],
            AAM_CHATTING: [
                CallbackQueryHandler(aam_day_callback, pattern=r"^(aam_day_|aam_ask|aam_complete|aam_menu_|change_method|main_menu)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, aam_chat_message),
            ],
            INTEGRATION_STEP1: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, integration_step1_receive),
            ],
            INTEGRATION_STEP2: [
                CallbackQueryHandler(integration_step2_callback, pattern=r"^integration_"),
            ],
            INTEGRATION_STEP3_WAIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, general_message),
                CallbackQueryHandler(method_callback, pattern=r"^main_menu$"),
            ],
            INTEGRATION_STEP4: [
                CallbackQueryHandler(integration_step4_callback, pattern=r"^integration_"),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, general_message),
        ],
        allow_reentry=True,
        per_message=False,
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("send_fb_details", admin_send_fb_details))
    app.add_handler(CommandHandler("pending", admin_list_pending))
    app.add_error_handler(error_handler)

    logger.info("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
