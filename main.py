import discord
import openai
import os
import json
import logging
import tempfile
import pendulum
from dotenv import load_dotenv
from discord.ext import commands
from index import keep_alive  # Starts your Flask server to keep the bot alive on Replit
from const import conversationSummarySchema

# -------------------------------
# Logging configuration: log to file and console
# -------------------------------
logging.basicConfig(
    level=logging.INFO,
    filename="error.log",
    filemode="a",
    format="%(asctime)s %(levelname)s: %(message)s"
)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
console_handler.setFormatter(console_formatter)
logging.getLogger('').addHandler(console_handler)
logger = logging.getLogger()

# -------------------------------
# Load environment variables from Secrets
# -------------------------------
load_dotenv()

# -------------------------------
# Intents configuration (ensure you’ve enabled Members and Message Content in the Developer Portal)
# -------------------------------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# -------------------------------
# Create bot using py-cord's commands.Bot (prefix commands)
# -------------------------------
bot = commands.Bot(command_prefix="/", description="Meeting Recorder Bot", intents=intents)

# Dictionary to store active voice connections per guild
connections = {}

# -------------------------------
# Configuration file setup
# -------------------------------
CONFIG_FILE = "config.json"
default_config = {
    "allowed_voice_channels": [],          # List of allowed voice channel IDs for auto-recording
    "SUMMARY_CHANNEL_ID": 123456789012345678,  # Default summary channel ID for auto-recording
    "TRANSCRIPT_CHANNEL_ID": 123456789012345678  # Default transcript channel ID for sending transcripts
}

if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)
else:
    config = default_config
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

allowed_voice_channels = config.get("allowed_voice_channels", [])
SUMMARY_CHANNEL_ID = config.get("SUMMARY_CHANNEL_ID", default_config["SUMMARY_CHANNEL_ID"])
TRANSCRIPT_CHANNEL_ID = config.get("TRANSCRIPT_CHANNEL_ID", default_config["TRANSCRIPT_CHANNEL_ID"])

# -------------------------------
# Set OpenAI API key from environment variables
# -------------------------------
openai.api_key = os.getenv("OPENAI_API_KEY")

# ============================
# COMMANDS
# ============================
@bot.command(help="Start recording in your current voice channel (manual mode sends summary to this text channel).")
async def record(ctx):
    logger.info("Record command called by %s", ctx.author)
    voice = ctx.author.voice
    if not voice:
        await ctx.send("⚠️ You aren't in a voice channel!")
        return
    try:
        logger.info("Connecting to voice channel: %s", voice.channel)
        vc = await voice.channel.connect()
        logger.info("Connected to voice channel: %s", voice.channel)
    except Exception as e:
        logger.error("Error connecting to voice channel: %s", e)
        await ctx.send("⚠️ Failed to connect to the voice channel.")
        return
    connections[ctx.guild.id] = {"vc": vc, "summary_channel": ctx.channel}
    logger.info("Starting manual recording...")
    vc.start_recording(
        discord.sinks.WaveSink(),
        once_done,
        ctx.channel  # Manual mode: summary is sent to the channel where the command was used
    )
    await ctx.send("🔴 Listening to this conversation.")

@bot.command(help="Stop recording (manual mode: summary is sent to the same text channel).")
async def stop_recording(ctx):
    logger.info("Stop recording command called by %s", ctx.author)
    if ctx.guild.id in connections:
        record_info = connections[ctx.guild.id]
        vc = record_info["vc"]
        logger.info("Stopping recording in voice channel: %s", vc.channel)
        vc.stop_recording()
        del connections[ctx.guild.id]
        await ctx.send("🛑 Stopped recording.")
    else:
        await ctx.send("🚫 Not recording here.")

@bot.command(help="Set allowed voice channels for auto-recording. Provide channel IDs (as strings) separated by spaces.")
async def set_auto_record_channels(ctx, *channel_ids: str):
    global allowed_voice_channels, config
    logger.info("set_auto_channels command called by %s with inputs: %s", ctx.author, channel_ids)
    try:
        allowed_voice_channels = [int(cid) for cid in channel_ids]
    except Exception as e:
        logger.error("Invalid channel ID provided: %s", e)
        await ctx.send("Invalid channel ID provided in one or more inputs!")
        return
    config["allowed_voice_channels"] = allowed_voice_channels
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)
    await ctx.send(f"Auto record channels updated to: {', '.join(str(ch) for ch in allowed_voice_channels)}")

@bot.command(help="Set the summary channel for auto-recording meeting notes. Provide the channel ID as a string.")
async def set_summary_channel(ctx, channel_id: str):
    global SUMMARY_CHANNEL_ID, config
    logger.info("set_summary_channel command called by %s with input: %s", ctx.author, channel_id)
    try:
        SUMMARY_CHANNEL_ID = int(channel_id)
    except Exception as e:
        logger.error("Invalid channel ID provided: %s", e)
        await ctx.send("Invalid channel ID provided!")
        return
    config["SUMMARY_CHANNEL_ID"] = SUMMARY_CHANNEL_ID
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)
    await ctx.send(f"Summary channel set to: {SUMMARY_CHANNEL_ID}")

@bot.command(help="Set the transcript channel for auto-recording meeting transcripts. Provide the channel ID as a string.")
async def set_transcript_channel(ctx, channel_id: str):
    global TRANSCRIPT_CHANNEL_ID, config
    logger.info("set_transcript_channel command called by %s with input: %s", ctx.author, channel_id)
    try:
        TRANSCRIPT_CHANNEL_ID = int(channel_id)
    except Exception as e:
        logger.error("Invalid channel ID provided: %s", e)
        await ctx.send("Invalid channel ID provided!")
        return
    config["TRANSCRIPT_CHANNEL_ID"] = TRANSCRIPT_CHANNEL_ID
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)
    await ctx.send(f"Transcript channel set to: {TRANSCRIPT_CHANNEL_ID}")

@bot.command(help="Show instructions for using and configuring the bot.")
async def how_to_configure(ctx):
    logger.info("how_to_configure command called by %s", ctx.author)
    config_message = (
        "**Bot Help & Configuration Instructions:**\n\n"
        "**Commands:**\n"
        "• `/record` - Start recording in your current voice channel. (Manual mode sends summary to this text channel.)\n"
        "• `/stop_recording` - Stop the ongoing manual recording.\n"
        "• `/set_auto_channels [channel_id1] [channel_id2] ...` - Set voice channels that trigger auto-recording.\n"
        "• `/set_summary_channel [channel_id]` - Set the text channel for auto-recording summaries.\n"
        "• `/set_transcript_channel [channel_id]` - Set the text channel for auto-recording transcripts.\n"
        "• `/how_to_configure` - Show these instructions.\n"
        "• `/show_config` - List the currently configured auto-record channels, summary channel, and transcript channel.\n\n"
        "**Usage:**\n"
        "• In manual mode, the transcript and summary are sent to the configured channels.\n"
        "• In auto mode, when a user joins an allowed voice channel, recording starts automatically; the summary is sent to the summary channel and the transcript to the transcript channel.\n"
        "• Settings are persisted in a configuration file.\n\n"
        "AscendBot v1.0.0"
    )
    await ctx.send(config_message)

@bot.command(help="List the currently configured auto-record channels, summary channel, and transcript channel.")
async def show_config(ctx):
    logger.info("show_config command called by %s", ctx.author)
    auto_channels = ', '.join(str(ch) for ch in allowed_voice_channels) if allowed_voice_channels else "None"
    config_message = (
        f"**Configured Auto-Record Channels:** {auto_channels}\n"
        f"**Configured Summary Channel:** {SUMMARY_CHANNEL_ID}\n"
        f"**Configured Transcript Channel:** {TRANSCRIPT_CHANNEL_ID}"
    )
    await ctx.send(config_message)

# ============================
# AUTO-RECORDING VIA VOICE STATE
# ============================
@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild
    try:
        # Auto-record when a user joins an allowed voice channel
        if before.channel is None and after.channel is not None:
            if after.channel.id in allowed_voice_channels:
                if guild.id not in connections and any(not m.bot for m in after.channel.members):
                    logger.info("Auto-record: %s joined %s. Connecting...", member.display_name, after.channel)
                    vc = await after.channel.connect()
                    summary_channel = guild.get_channel(SUMMARY_CHANNEL_ID)
                    connections[guild.id] = {"vc": vc, "summary_channel": summary_channel}
                    logger.info("Starting auto-recording in channel: %s", after.channel)
                    vc.start_recording(
                        discord.sinks.WaveSink(),
                        once_done,
                        summary_channel,
                    )
                    logger.info("Auto-recording started in %s", after.channel)
        # Auto-stop if the bot is the only member left in an allowed voice channel
        if before.channel is not None and before.channel.id in allowed_voice_channels:
            if before.channel.members == [guild.me]:
                if guild.id in connections:
                    logger.info("Auto-stop: Only bot left in %s. Stopping recording...", before.channel)
                    record_info = connections[guild.id]
                    vc = record_info["vc"]
                    vc.stop_recording()
                    del connections[guild.id]
                    logger.info("Auto-recording stopped in %s", before.channel)
    except Exception as e:
        logger.error("Error in on_voice_state_update: %s", e)

# ============================
# PROCESSING THE RECORDED AUDIO
# ============================
async def once_done(sink, channel, *args):
    try:
        recorded_users = [f"<@{user_id}>" for user_id in sink.audio_data.keys()]
        await sink.vc.disconnect()

        transcripts = []
        # Transcribe each user's audio using OpenAI Whisper API
        for user_id, audio in sink.audio_data.items():
            try:
                logger.info("Calling OpenAI Whisper API to transcribe audio for user: %s", user_id)
                audio.file.seek(0)
                # Option B: Write the BytesIO to a temporary file
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
                    temp_audio.write(audio.file.read())
                    temp_audio_path = temp_audio.name

                with open(temp_audio_path, "rb") as audio_file:
                    response = openai.Audio.transcribe(
                        "whisper-1",
                        audio_file,
                        response_format="json"
                    )
                transcript_text = response.get("text", "")
                logger.info("Received transcription for user %s", user_id)
                os.remove(temp_audio_path)
            except Exception as e:
                logger.error("Error transcribing audio for user %s: %s", user_id, e)
                transcript_text = "[Error transcribing audio]"
            transcripts.append((user_id, transcript_text))

        # Assemble the final transcript with each speaker's text
        final_transcript = ""
        for user_id, text in transcripts:
            final_transcript += f"\n\nSpeaker <@{user_id}>: {text}"
        final_transcript = final_transcript.strip()

        # Use OpenAI ChatCompletion for summarization with a supported model
        logger.info("Calling OpenAI API for summarization")
        chat_completion = await openai.ChatCompletion.acreate(
            model="gpt-4o-mini",  # Updated to supported model
            messages=[
                {"role": "system", "content": "You are a conversation summarizer and task assigner. Summarize the conversation below and list any action items."},
                {"role": "user", "content": final_transcript}
            ],
            temperature=0.7,
            functions=[conversationSummarySchema],
        )
        summary = chat_completion.choices[0].message.content
        logger.info("Received summary from OpenAI API")

        meeting_time = pendulum.now().format("Do MMM, YYYY | hh:mm A")
        num_participants = len(recorded_users)
        summary_message = (
            f"**Meeting Date & Time:** {meeting_time}\n"
            f"**Participants:** {', '.join(recorded_users)}\n"
            f"**Summary:**\n{summary}\n\n"
        )

        # Send summary message to the configured summary channel
        await channel.send(summary_message)

        # Retrieve the transcript channel and send the full transcript there
        transcript_channel = bot.get_channel(TRANSCRIPT_CHANNEL_ID)
        if transcript_channel:
            transcript_message = (
                f"**Meeting Date & Time:** {meeting_time}\n"
                f"**Participants:** {', '.join(recorded_users)}\n"
                f"**Transcript:**\n{final_transcript}")
            await transcript_channel.send(transcript_message)
        else:
            logger.error("Transcript channel not found!")

    except Exception as e:
        logger.error("Error in once_done: %s", e)

# ============================
# ON READY EVENT
# ============================
@bot.event
async def on_ready():
    logger.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)

# ============================
# RUN THE BOT
# ============================
keep_alive()
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
