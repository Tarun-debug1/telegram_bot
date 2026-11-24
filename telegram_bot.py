
import os
import asyncio
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from assistant_agent.agent import (
    root_agent,
    build_status_report_for_user
)


# ----------------------------------
# CONFIGURATION
# ----------------------------------

env_path = (
    Path(__file__).resolve().parent
    / "assistant_agent"
    / ".env"
)

load_dotenv(env_path)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

ALLOWED_USER_IDS = {
    user_id.strip()
    for user_id in os.getenv(
        "TELEGRAM_ALLOWED_USER_IDS", ""
    ).split(",")
    if user_id.strip().isdigit()
}

APP_NAME = "telegram_personal_assistant"

TIMEZONE = ZoneInfo("Asia/Kolkata")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Scheduler instance
scheduler = None


# ----------------------------------
# ADK RUNNER
# ----------------------------------

session_service = InMemorySessionService()

runner = Runner(
    app_name=APP_NAME,
    agent=root_agent,
    session_service=session_service,
)

# Prevent overlapping requests for the same user's session.
user_locks = {}


# ----------------------------------
# HELPER FUNCTIONS
# ----------------------------------

def is_authorized(update: Update) -> bool:
    user = update.effective_user

    return (
        user is not None
        and str(user.id) in ALLOWED_USER_IDS
    )


async def send_long_message(
    bot,
    chat_id: int,
    message: str
):
    """Send long messages without exceeding Telegram's limit."""

    for start_index in range(0, len(message), 4000):
        await bot.send_message(
            chat_id=chat_id,
            text=message[start_index:start_index + 4000]
        )


# ----------------------------------
# TELEGRAM COMMANDS
# ----------------------------------

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized user.")
        return

    await update.message.reply_text(
        "Hello! Your AI Personal Assistant is ready.\n\n"
        "You can ask me to:\n"
        "- Add tasks\n"
        "- Show today's tasks\n"
        "- Complete tasks\n"
        "- Delete tasks\n"
        "- Generate your daily status report"
    )


async def myid(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if update.effective_user:
        await update.message.reply_text(
            f"Your Telegram ID: {update.effective_user.id}"
        )


# ----------------------------------
# ADK EXECUTION
# ----------------------------------

async def ask_agent(
    user_id: str,
    session_id: str,
    message: str
) -> str:

    session = await session_service.get_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )

    if session is None:
        await session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )

    content = types.Content(
        role="user",
        parts=[
            types.Part.from_text(text=message)
        ],
    )

    final_response = None

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
    ):
        if event.is_final_response():
            if event.content and event.content.parts:
                response_parts = [
                    part.text
                    for part in event.content.parts
                    if part.text
                ]

                if response_parts:
                    final_response = "\n".join(response_parts)

    return final_response or (
        "The agent did not return a text response. "
        "Please check the terminal logs."
    )


# ----------------------------------
# TELEGRAM MESSAGE HANDLER
# ----------------------------------

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not is_authorized(update):
        await update.message.reply_text("Unauthorized user.")
        return

    user_message = update.message.text

    user_id = str(update.effective_user.id)
    session_id = f"telegram_{update.effective_chat.id}"

    lock = user_locks.setdefault(
        user_id,
        asyncio.Lock()
    )

    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing",
        )

        async with lock:
            response = await ask_agent(
                user_id=user_id,
                session_id=session_id,
                message=user_message,
            )

        await send_long_message(
            context.bot,
            update.effective_chat.id,
            response
        )

    except Exception:
        logger.exception(
            "Failed to process message from user %s",
            user_id
        )

        await update.message.reply_text(
            "Something went wrong while processing your request. "
            "Please check the terminal logs."
        )


# ----------------------------------
# MORNING REMINDER — 10 AM
# ----------------------------------

async def morning_reminder(application: Application):

    logger.info("Starting 10 AM reminders.")

    for user_id in ALLOWED_USER_IDS:

        try:
            await application.bot.send_message(
                chat_id=int(user_id),
                text=(
                    "Good morning! ☀️\n\n"
                    "It's time to plan today's action items.\n\n"
                    "What do you want to accomplish today?\n"
                    "Send me your tasks and priorities, "
                    "and I'll add them to your task manager."
                )
            )

            logger.info(
                "Morning reminder sent to user %s",
                user_id
            )

        except Exception:
            logger.exception(
                "Failed to send morning reminder to user %s",
                user_id
            )


# ----------------------------------
# EVENING REMINDER + REPORT — 5 PM
# ----------------------------------

async def evening_reminder(application: Application):

    logger.info("Starting 5 PM status report generation.")

    for user_id in ALLOWED_USER_IDS:

        try:
            # Notify the user that the report is being generated.
            await application.bot.send_message(
                chat_id=int(user_id),
                text=(
                    "Good evening! 🌆\n\n"
                    "Your daily status report is being generated "
                    "from your completed tasks."
                )
            )

            # MongoDB operations are synchronous, so run them
            # in a worker thread instead of blocking the event loop.
            result = await asyncio.to_thread(
                build_status_report_for_user,
                user_id
            )

            if result.get("status") == "success":

                await send_long_message(
                    application.bot,
                    int(user_id),
                    result["report"]
                )

                logger.info(
                    "Status report successfully sent to user %s",
                    user_id
                )

            else:
                await application.bot.send_message(
                    chat_id=int(user_id),
                    text=(
                        "Unable to generate your status report.\n"
                        + result.get("message", "Unknown error.")
                    )
                )

        except Exception:
            logger.exception(
                "Report generation failed for user %s",
                user_id
            )

            try:
                await application.bot.send_message(
                    chat_id=int(user_id),
                    text=(
                        "An error occurred while generating "
                        "your daily status report."
                    )
                )
            except Exception:
                logger.exception(
                    "Could not notify user %s about report failure",
                    user_id
                )

    logger.info("5 PM report generation cycle completed.")


# ----------------------------------
# SCHEDULER STARTUP
# ----------------------------------

async def start_scheduler(application: Application):

    global scheduler

    scheduler = AsyncIOScheduler(
        timezone=TIMEZONE
    )

    # Morning reminder: 10:00 AM IST
    scheduler.add_job(
        morning_reminder,
        trigger="cron",
        hour=10,
        minute=0,
        args=[application],
        id="morning_reminder",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
    )

    # Evening report: 05:00 PM IST
    scheduler.add_job(
        evening_reminder,
        trigger="cron",
        hour=17,
        minute=0,
        args=[application],
        id="evening_status_report",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
    )

    scheduler.start()

    logger.info("APScheduler started successfully.")
    logger.info("Morning reminder: 10:00 AM IST")
    logger.info("Evening status report: 05:00 PM IST")
    logger.info(
        "Authorized Telegram users: %s",
        len(ALLOWED_USER_IDS)
    )


# ----------------------------------
# SCHEDULER SHUTDOWN
# ----------------------------------

async def stop_scheduler(application: Application):

    global scheduler

    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped successfully.")


# ----------------------------------
# MAIN
# ----------------------------------

def main():

    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing!")

    if not ALLOWED_USER_IDS:
        raise ValueError(
            "Set TELEGRAM_ALLOWED_USER_IDS in .env "
            "with at least one valid Telegram ID."
        )

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(start_scheduler)
        .post_shutdown(stop_scheduler)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    print(
        "Telegram + ADK + MongoDB + APScheduler "
        "assistant is running..."
    )

    app.run_polling()


if __name__ == "__main__":
    main()
