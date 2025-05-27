import os
import logging
import requests
import asyncio
from PIL import Image
from io import BytesIO

# Import for the web server
from flask import Flask, request, jsonify

# Telegram bot library
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# Replicate client library
import replicate

# --- Configuration ---
# Get your Telegram bot token from BotFather
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
# Get your Replicate API Token
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "YOUR_REPLICATE_API_TOKEN")

# This will be provided by Render's environment, e.g., "my-bot-service.onrender.com"
WEBHOOK_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")
WEBHOOK_URL_PATH = "/webhook" # Path where Telegram will send updates

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Replicate Model ID ---
# Find the DeepFloyd IF model on Replicate: https://replicate.com/stability-ai/deepfloyd-if
# Copy the model version string. Example (might be outdated, check Replicate):
DEEPFLOYD_REPLICATE_MODEL_ID = "stability-ai/deepfloyd-if:66657a7509f6e3a89e9f9116e02a0a2b5e28a50f162985392097cdb04041b312"


# --- Flask App Setup ---
app = Flask(__name__)
application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

# --- Telegram Bot Handlers ---
async def start(update: Update, context) -> None:
    """Sends a message when the command /start is issued."""
    await update.message.reply_text(
        "Hello! Send me a text prompt, and I'll generate an image using DeepFloyd IF (via Replicate.com).\n"
        "Image generation can take a bit, please be patient."
    )

async def generate_image_replicate(update: Update, context) -> None:
    """Generates an image from the user's text prompt using Replicate API."""
    prompt = update.message.text

    if not prompt:
        await update.message.reply_text("Please provide a text prompt!")
        return

    if REPLICATE_API_TOKEN == "YOUR_REPLICATE_API_TOKEN":
        await update.message.reply_text(
            "Replicate API token not set. Cannot generate image. Please inform the bot administrator."
        )
        return

    # Set Replicate API token for the library
    os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN

    sent_message = await update.message.reply_text(f"Generating image for: '{prompt}'\nThis might take a while...")

    try:
        logger.info(f"Sending prompt to Replicate: '{prompt}'")
        output = replicate.run(
            DEEPFLOYD_REPLICATE_MODEL_ID,
            input={
                "prompt": prompt,
                "width": 256,
                "height": 256,
                # Add any other parameters Replicate's model offers (e.g., num_inference_steps)
            }
        )
        
        if output and isinstance(output, list) and len(output) > 0:
            image_url = output[0] # Take the first image URL
            logger.info(f"Image URL from Replicate: {image_url}")

            response = requests.get(image_url)
            response.raise_for_status()
            image_bytes = BytesIO(response.content)
            
            await update.message.reply_photo(photo=InputFile(image_bytes), caption=f"Generated for: '{prompt}'")
            await context.bot.delete_message(chat_id=update.message.chat_id, message_id=sent_message.message_id)

        else:
            await update.message.reply_text("Failed to generate image. No output from Replicate or unexpected format.")
            await context.bot.delete_message(chat_id=update.message.chat_id, message_id=sent_message.message_id)

    except requests.exceptions.RequestException as req_err:
        logger.error(f"Error downloading image from Replicate URL: {req_err}", exc_info=True)
        await update.message.reply_text("Failed to download generated image. Please try again.")
        if sent_message:
            await context.bot.delete_message(chat_id=update.message.chat_id, message_id=sent_message.message_id)
    except Exception as e:
        logger.error(f"Error during image generation (Replicate): {e}", exc_info=True)
        await update.message.reply_text(
            "An error occurred during image generation. Please try again later or with a simpler prompt.\n"
            "Ensure your Replicate API token is correct and valid."
        )
        if sent_message:
            await context.bot.delete_message(chat_id=update.message.chat_id, message_id=sent_message.message_id)

# --- Flask Routes ---
@app.route("/")
def index():
    """Basic health check endpoint."""
    return "Telegram DeepFloyd IF Bot is running!", 200

@app.route(WEBHOOK_URL_PATH, methods=["POST"])
async def webhook_handler():
    """Handle incoming Telegram updates from the webhook."""
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), application.bot)
        # Process the update asynchronously to avoid blocking the webhook
        asyncio.create_task(application.process_update(update))
        return jsonify({"status": "ok"}), 200
    return "Method Not Allowed", 405

# --- Main Bot Logic Setup ---
async def setup_bot_handlers():
    """Sets up Telegram bot handlers."""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, generate_image_replicate))
    
    # Initialize the updater and dispatcher (required for webhook setup)
    # This must be run in an async context
    await application.initialize()
    # Build a context
    await application.bot.set_webhook(url=f"https://{WEBHOOK_HOSTNAME}{WEBHOOK_URL_PATH}")
    logger.info(f"Webhook set to: https://{WEBHOOK_HOSTNAME}{WEBHOOK_URL_PATH}")


if __name__ == "__main__":
    # For production, set environment variables on Render:
    # TELEGRAM_BOT_TOKEN="YOUR_ACTUAL_TELEGRAM_TOKEN"
    # REPLICATE_API_TOKEN="YOUR_ACTUAL_REPLICATE_TOKEN"
    # Render automatically provides RENDER_EXTERNAL_HOSTNAME

    # Check if tokens are placeholders
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.error("!!! Telegram bot token is not set. Please update TELEGRAM_BOT_TOKEN or set environment variable. !!!")
    if REPLICATE_API_TOKEN == "YOUR_REPLICATE_API_TOKEN":
        logger.error("!!! Replicate API token is not set. Please update REPLICATE_API_TOKEN or set environment variable. !!!")
    
    # Run setup for handlers and webhook in an async loop
    asyncio.run(setup_bot_handlers())

    # Start the Flask web server
    # Render provides a PORT environment variable to tell your app which port to listen on
    port = int(os.environ.get("PORT", 8080)) # Default to 8080 if PORT not set (for local testing)
    logger.info(f"Flask app starting on port {port}")
    app.run(host="0.0.0.0", port=port)

