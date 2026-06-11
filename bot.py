import logging
from datetime import datetime, timezone, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from config import TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_ID, LESSON_COOLDOWN_HOURS
from database import (
    init_db,
    get_student,
    enroll_student,
    record_lesson_access,
    get_all_students,
    reset_student_progress,
    set_student_active,
)
from lessons import get_lesson, TOTAL_LESSONS, MODULES

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _hours_until_next(last_accessed_iso: str) -> float:
    """Return hours remaining before next lesson is unlocked (0 if ready)."""
    if not last_accessed_iso:
        return 0
    last = datetime.fromisoformat(last_accessed_iso)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    delta = timedelta(hours=LESSON_COOLDOWN_HOURS) - (datetime.now(timezone.utc) - last)
    return max(0.0, delta.total_seconds() / 3600)


def _progress_bar(current: int, total: int, length: int = 20) -> str:
    filled = int(length * (current - 1) / total)
    bar = "█" * filled + "░" * (length - filled)
    pct = int(100 * (current - 1) / total)
    return f"[{bar}] {pct}%"


def _main_keyboard(student: dict) -> InlineKeyboardMarkup:
    current = student["current_lesson"]
    buttons = [
        [InlineKeyboardButton("📖 Today's Lesson", callback_data="get_lesson")],
        [InlineKeyboardButton("📊 My Progress", callback_data="progress")],
        [InlineKeyboardButton("📚 Course Outline", callback_data="outline")],
    ]
    if current > 1:
        buttons.append([
            InlineKeyboardButton("🔙 Previous Lesson", callback_data="prev_lesson")
        ])
    return InlineKeyboardMarkup(buttons)


def _lesson_card(lesson: dict, show_open_btn: bool = True) -> tuple[str, InlineKeyboardMarkup]:
    text = (
        f"📘 *Module {lesson['module_number']}: {lesson['module_title']}*\n\n"
        f"*Lesson {lesson['lesson_number']} of {TOTAL_LESSONS}*\n"
        f"_{lesson['title']}_\n\n"
        f"Click the button below to watch this lesson on the course platform. "
        f"Make sure you're logged in to your account first!"
    )
    buttons = []
    if show_open_btn:
        buttons.append([
            InlineKeyboardButton("▶️ Open Lesson", url=lesson["url"])
        ])
    buttons.append([
        InlineKeyboardButton("✅ I've Watched This Lesson", callback_data="mark_done")
    ])
    buttons.append([
        InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")
    ])
    return text, InlineKeyboardMarkup(buttons)


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await enroll_student(user.id, user.username, user.first_name)
    student = await get_student(user.id)

    current = student["current_lesson"]
    done = current - 1

    welcome = (
        f"👋 Welcome to the *7-Figure Road Map* course bot, {user.first_name}!\n\n"
        f"This bot unlocks *one lesson every 24 hours* to help you stay consistent "
        f"and actually implement what you learn — not just binge-watch everything.\n\n"
        f"📚 *{TOTAL_LESSONS} lessons* across *19 modules*\n"
        f"✅ *{done}* lesson{'s' if done != 1 else ''} completed\n\n"
        f"Use the buttons below to navigate."
    )
    await update.message.reply_text(
        welcome,
        parse_mode="Markdown",
        reply_markup=_main_keyboard(student),
    )


# ── Callback router ───────────────────────────────────────────────────────────

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "get_lesson":
        await _handle_get_lesson(query)
    elif data == "mark_done":
        await _handle_mark_done(query)
    elif data == "prev_lesson":
        await _handle_prev_lesson(query)
    elif data == "progress":
        await _handle_progress(query)
    elif data == "outline":
        await _handle_outline(query)
    elif data == "main_menu":
        await _handle_main_menu(query)
    elif data.startswith("outline_mod_"):
        mod_num = int(data.split("_")[-1])
        await _handle_outline_module(query, mod_num)


async def _handle_get_lesson(query):
    user_id = query.from_user.id
    student = await get_student(user_id)
    if not student:
        await query.edit_message_text("Please /start the bot first.")
        return

    current = student["current_lesson"]

    if current > TOTAL_LESSONS:
        await query.edit_message_text(
            "🏆 *You've completed the entire course! Congratulations!*\n\n"
            "You've gone through all 37 lessons. Time to put everything into action!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")
            ]]),
        )
        return

    # Check cooldown — only applies after the first lesson access
    if student["last_accessed"]:
        hours_left = _hours_until_next(student["last_accessed"])
        if hours_left > 0:
            h = int(hours_left)
            m = int((hours_left - h) * 60)
            lesson = get_lesson(current)
            await query.edit_message_text(
                f"⏳ *Next lesson unlocks in {h}h {m}m*\n\n"
                f"You'll be able to access:\n"
                f"*Lesson {current}: {lesson['title']}*\n\n"
                f"_Come back tomorrow to keep the momentum going!_ 💪",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📊 My Progress", callback_data="progress")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
                ]),
            )
            return

    lesson = get_lesson(current)
    text, kb = _lesson_card(lesson)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)


async def _handle_mark_done(query):
    user_id = query.from_user.id
    student = await get_student(user_id)
    if not student:
        return

    current = student["current_lesson"]

    # Record access time and advance to next lesson
    await record_lesson_access(user_id, current + 1)

    if current >= TOTAL_LESSONS:
        await query.edit_message_text(
            "🏆 *Course Complete! You did it!*\n\n"
            "You've finished all 37 lessons of the 7-Figure Road Map.\n\n"
            "Now the real work begins — go implement everything you've learned! 🚀",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")
            ]]),
        )
        return

    next_lesson = get_lesson(current + 1)
    await query.edit_message_text(
        f"✅ *Lesson {current} marked as done!*\n\n"
        f"Great work! Your next lesson will unlock in *{LESSON_COOLDOWN_HOURS} hours*:\n\n"
        f"📘 *Lesson {current + 1}:* _{next_lesson['title']}_\n"
        f"_(Module {next_lesson['module_number']}: {next_lesson['module_title']})_\n\n"
        f"See you tomorrow! Consistency is the key to success. 💪",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 My Progress", callback_data="progress")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
        ]),
    )


async def _handle_prev_lesson(query):
    user_id = query.from_user.id
    student = await get_student(user_id)
    if not student:
        return

    current = student["current_lesson"]
    prev = max(1, current - 1)
    lesson = get_lesson(prev)
    text, kb = _lesson_card(lesson)

    # Remove "mark done" button for already-completed lessons
    buttons = [
        [InlineKeyboardButton("▶️ Open Lesson", url=lesson["url"])],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
    ]
    await query.edit_message_text(
        f"🔙 *Reviewing a previous lesson:*\n\n" + text.split("\n\n", 1)[1],
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _handle_progress(query):
    user_id = query.from_user.id
    student = await get_student(user_id)
    if not student:
        return

    current = student["current_lesson"]
    done = current - 1
    bar = _progress_bar(current, TOTAL_LESSONS)

    # Current module
    if current <= TOTAL_LESSONS:
        lesson = get_lesson(current)
        next_info = (
            f"📖 *Up next:* Lesson {current} — _{lesson['title']}_\n"
            f"_(Module {lesson['module_number']}: {lesson['module_title']})_\n\n"
        )
    else:
        next_info = "🏆 *Course fully completed!*\n\n"

    cooldown_info = ""
    if student["last_accessed"] and current <= TOTAL_LESSONS:
        hours_left = _hours_until_next(student["last_accessed"])
        if hours_left > 0:
            h = int(hours_left)
            m = int((hours_left - h) * 60)
            cooldown_info = f"⏳ Next lesson unlocks in *{h}h {m}m*\n\n"
        else:
            cooldown_info = "✅ *Your next lesson is ready!*\n\n"

    text = (
        f"📊 *Your Progress*\n\n"
        f"{bar}\n\n"
        f"✅ Completed: *{done}* lesson{'s' if done != 1 else ''}\n"
        f"📚 Remaining: *{max(0, TOTAL_LESSONS - done)}* lessons\n"
        f"📋 Total: *{TOTAL_LESSONS}* lessons\n\n"
        f"{cooldown_info}"
        f"{next_info}"
        f"_Keep going — every lesson brings you closer to 7 figures!_"
    )
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📖 Today's Lesson", callback_data="get_lesson")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
        ]),
    )


async def _handle_outline(query):
    lines = ["📚 *7-Figure Road Map — Course Outline*\n"]
    for mod in MODULES:
        count = len(mod["lessons"])
        lines.append(
            f"Module {mod['number']}: {mod['title']} "
            f"({count} lesson{'s' if count != 1 else ''})"
        )
    lines.append(f"\n_Total: {TOTAL_LESSONS} lessons across 19 modules_")

    buttons = []
    row = []
    for mod in MODULES:
        row.append(InlineKeyboardButton(
            f"M{mod['number']}", callback_data=f"outline_mod_{mod['number']}"
        ))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _handle_outline_module(query, mod_num: int):
    from lessons import get_module_lessons
    mod_lessons = get_module_lessons(mod_num)
    user_id = query.from_user.id
    student = await get_student(user_id)
    current = student["current_lesson"] if student else 1

    mod = next(m for m in MODULES if m["number"] == mod_num)
    lines = [f"📘 *Module {mod_num}: {mod['title']}*\n"]
    for l in mod_lessons:
        if l["lesson_number"] < current:
            status = "✅"
        elif l["lesson_number"] == current:
            status = "▶️"
        else:
            status = "🔒"
        lines.append(f"{status} Lesson {l['lesson_number']}: {l['title']}")

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Outline", callback_data="outline")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
        ]),
    )


async def _handle_main_menu(query):
    user_id = query.from_user.id
    student = await get_student(user_id)
    if not student:
        await query.edit_message_text("Please /start the bot first.")
        return

    current = student["current_lesson"]
    done = current - 1
    text = (
        f"🏠 *Main Menu*\n\n"
        f"✅ *{done}* lesson{'s' if done != 1 else ''} completed\n"
        f"📚 *{max(0, TOTAL_LESSONS - done)}* remaining\n\n"
        f"What would you like to do?"
    )
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=_main_keyboard(student),
    )


# ── Admin commands ────────────────────────────────────────────────────────────

def _admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_TELEGRAM_ID:
            await update.message.reply_text("⛔ Admin only.")
            return
        await func(update, context)
    return wrapper


@_admin_only
async def cmd_students(update: Update, context: ContextTypes.DEFAULT_TYPE):
    students = await get_all_students()
    if not students:
        await update.message.reply_text("No students enrolled yet.")
        return

    lines = [f"👥 *Students ({len(students)} total)*\n"]
    for s in students:
        done = s["current_lesson"] - 1
        status = "🟢" if s["is_active"] else "🔴"
        lines.append(
            f"{status} {s['first_name']} (@{s['username'] or '—'})\n"
            f"   ID: `{s['user_id']}` | Lesson {s['current_lesson']}/{TOTAL_LESSONS} "
            f"({done} done)"
        )

    # Split into chunks of 10 to avoid message length limits
    chunk_size = 10
    for i in range(0, len(students), chunk_size):
        chunk = students[i:i + chunk_size]
        chunk_lines = [f"👥 *Students ({len(students)} total)*\n"] if i == 0 else []
        for s in chunk:
            done = s["current_lesson"] - 1
            status = "🟢" if s["is_active"] else "🔴"
            chunk_lines.append(
                f"{status} {s['first_name']} (@{s['username'] or '—'})\n"
                f"   ID: `{s['user_id']}` | Lesson {s['current_lesson']}/{TOTAL_LESSONS} "
                f"({done} done)"
            )
        await update.message.reply_text("\n".join(chunk_lines), parse_mode="Markdown")


@_admin_only
async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: `/reset <user_id>`", parse_mode="Markdown"
        )
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid user ID.")
        return
    await reset_student_progress(uid)
    await update.message.reply_text(f"✅ Progress reset for user `{uid}`.", parse_mode="Markdown")


@_admin_only
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: `/broadcast <message>`", parse_mode="Markdown"
        )
        return
    msg = " ".join(context.args)
    students = await get_all_students()
    sent = 0
    failed = 0
    for s in students:
        if not s["is_active"]:
            continue
        try:
            await context.bot.send_message(
                s["user_id"],
                f"📢 *Message from your coach:*\n\n{msg}",
                parse_mode="Markdown",
            )
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(
        f"✅ Sent to {sent} students. Failed: {failed}."
    )


@_admin_only
async def cmd_set_lesson(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Force a student to a specific lesson: /set_lesson <user_id> <lesson_number>"""
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/set_lesson <user_id> <lesson_number>`", parse_mode="Markdown"
        )
        return
    try:
        uid = int(context.args[0])
        lesson_num = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Invalid arguments.")
        return
    if not (1 <= lesson_num <= TOTAL_LESSONS + 1):
        await update.message.reply_text(f"Lesson number must be between 1 and {TOTAL_LESSONS}.")
        return
    from database import record_lesson_access
    # Set to the desired lesson, clear cooldown so they can access immediately
    async with __import__('aiosqlite').connect(__import__('config').DB_PATH) as db:
        await db.execute(
            "UPDATE students SET current_lesson = ?, last_accessed = NULL WHERE user_id = ?",
            (lesson_num, uid),
        )
        await db.commit()
    await update.message.reply_text(
        f"✅ User `{uid}` moved to lesson {lesson_num}.", parse_mode="Markdown"
    )


# ── App setup ─────────────────────────────────────────────────────────────────

async def post_init(app: Application):
    await init_db()
    logger.info("Database ready.")


def main():
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("students", cmd_students))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("set_lesson", cmd_set_lesson))
    app.add_handler(CallbackQueryHandler(callback_router))

    logger.info("7FIRM AAM bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
