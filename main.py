import os
import telebot
from gtts import gTTS
import tempfile
import logging
import re
from pydub import AudioSegment

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MAX_CHUNK_LENGTH = 180
MAX_TEXT_LENGTH = 100000
TELEGRAM_MAX_AUDIO_SIZE_MB = 50

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')

if not BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN not found in environment variables!")
    raise ValueError("TELEGRAM_BOT_TOKEN is required")

bot = telebot.TeleBot(BOT_TOKEN)

user_speed_settings = {}

def get_user_speed(user_id):
    """Get user's speed preference (1.0 for normal, 2.0 for 2x)."""
    return user_speed_settings.get(user_id, 1.0)

def set_user_speed(user_id, speed):
    """Set user's speed preference."""
    user_speed_settings[user_id] = speed

def split_text_into_chunks(text, max_length=MAX_CHUNK_LENGTH):
    """Split text into chunks with sentence-aware splitting."""
    if len(text) <= max_length:
        return [text]
    
    sentences = re.split(r'([.!?।॥\n]+)', text)
    
    chunks = []
    current_chunk = ""
    
    for i in range(0, len(sentences), 2):
        sentence = sentences[i]
        separator = sentences[i + 1] if i + 1 < len(sentences) else ""
        
        combined = sentence + separator
        
        if len(current_chunk) + len(combined) <= max_length:
            current_chunk += combined
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            
            if len(combined) > max_length:
                words = combined.split()
                temp_chunk = ""
                for word in words:
                    if len(temp_chunk) + len(word) + 1 <= max_length:
                        temp_chunk += (" " if temp_chunk else "") + word
                    else:
                        if temp_chunk:
                            chunks.append(temp_chunk.strip())
                        temp_chunk = word
                current_chunk = temp_chunk
            else:
                current_chunk = combined
    
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    return [chunk for chunk in chunks if chunk]

def convert_text_to_speech(chat_id, text, title="Malayalam TTS", user_id=None, speed=1.0):
    """Convert text to speech with support for unlimited text length."""
    
    if len(text) > MAX_TEXT_LENGTH:
        bot.send_message(chat_id, f"Text is too long. Maximum supported length is {MAX_TEXT_LENGTH:,} characters. Your text has {len(text):,} characters.")
        return
    
    if user_id:
        speed = get_user_speed(user_id)
    
    chunks = split_text_into_chunks(text)
    
    if len(chunks) == 1:
        _convert_single_chunk(chat_id, text, title, speed)
    else:
        _convert_multiple_chunks(chat_id, chunks, title, speed)

def _convert_single_chunk(chat_id, text, title, speed=1.0):
    """Convert a single text chunk to voice message with optional speed adjustment."""
    bot.send_chat_action(chat_id, 'record_audio')
    
    temp_files = []
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as temp_audio:
            temp_filename = temp_audio.name
            temp_files.append(temp_filename)
        
        tts = gTTS(text=text, lang='ml', slow=False)
        tts.save(temp_filename)
        
        audio = AudioSegment.from_mp3(temp_filename)
        
        if speed != 1.0:
            audio = audio.speedup(playback_speed=speed)
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.ogg') as voice_file_temp:
            voice_filename = voice_file_temp.name
            temp_files.append(voice_filename)
        
        audio.export(voice_filename, format='ogg', codec='libopus')
        
        logger.info(f"Voice message created: {voice_filename} (speed: {speed}x)")
        
        with open(voice_filename, 'rb') as voice_file:
            bot.send_voice(
                chat_id,
                voice_file
            )
        
        logger.info(f"Voice message sent successfully to chat {chat_id}")
        
    finally:
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                os.remove(temp_file)
                logger.debug(f"Temporary file removed: {temp_file}")

def _safe_edit_message(chat_id, message_id, text):
    """Safely edit a message, ignoring errors if message is unchanged."""
    try:
        bot.edit_message_text(text, chat_id, message_id)
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            logger.warning(f"Failed to edit message: {str(e)}")

def _convert_multiple_chunks(chat_id, chunks, title, speed=1.0):
    """Convert multiple text chunks and concatenate them into a single voice message."""
    total_chunks = len(chunks)
    logger.info(f"Processing {total_chunks} chunks for chat {chat_id}")
    
    progress_msg = bot.send_message(
        chat_id,
        f"Converting your text to speech...\nProcessing {total_chunks} segments. This may take a moment."
    )
    
    temp_files = []
    audio_segments = []
    success = False
    
    try:
        for i, chunk in enumerate(chunks, 1):
            try:
                bot.send_chat_action(chat_id, 'record_audio')
            except:
                pass
            
            if i % 5 == 0 or i == total_chunks:
                _safe_edit_message(
                    chat_id,
                    progress_msg.message_id,
                    f"Converting your text to speech...\nProcessed {i}/{total_chunks} segments."
                )
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as temp_audio:
                temp_filename = temp_audio.name
                temp_files.append(temp_filename)
            
            tts = gTTS(text=chunk, lang='ml', slow=False)
            tts.save(temp_filename)
            
            audio_segment = AudioSegment.from_mp3(temp_filename)
            audio_segments.append(audio_segment)
            
            logger.debug(f"Processed chunk {i}/{total_chunks}")
        
        _safe_edit_message(
            chat_id,
            progress_msg.message_id,
            f"Combining audio segments..."
        )
        
        combined_audio = audio_segments[0]
        for segment in audio_segments[1:]:
            combined_audio += segment
        
        if speed != 1.0:
            _safe_edit_message(
                chat_id,
                progress_msg.message_id,
                f"Applying {speed}x speed..."
            )
            combined_audio = combined_audio.speedup(playback_speed=speed)
        
        _safe_edit_message(
            chat_id,
            progress_msg.message_id,
            f"Converting to voice format..."
        )
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.ogg') as final_audio:
            final_filename = final_audio.name
            temp_files.append(final_filename)
        
        combined_audio.export(final_filename, format='ogg', codec='libopus')
        
        file_size_mb = os.path.getsize(final_filename) / (1024 * 1024)
        logger.info(f"Combined voice message created: {final_filename}, size: {file_size_mb:.2f} MB (speed: {speed}x)")
        
        if file_size_mb > TELEGRAM_MAX_AUDIO_SIZE_MB:
            _safe_edit_message(
                chat_id,
                progress_msg.message_id,
                f"The combined audio file is too large ({file_size_mb:.1f} MB). Telegram's limit is {TELEGRAM_MAX_AUDIO_SIZE_MB} MB. Please try with shorter text."
            )
            logger.warning(f"Audio file too large: {file_size_mb:.2f} MB")
            return
        
        try:
            bot.delete_message(chat_id, progress_msg.message_id)
        except:
            pass
        
        with open(final_filename, 'rb') as voice_file:
            bot.send_voice(
                chat_id,
                voice_file
            )
        
        logger.info(f"Combined audio sent successfully to chat {chat_id}")
        success = True
        
    except Exception as e:
        logger.error(f"Error in chunk processing: {str(e)}", exc_info=True)
        try:
            _safe_edit_message(
                chat_id,
                progress_msg.message_id,
                f"Sorry, there was an error processing your text. Please try again with shorter text."
            )
        except:
            bot.send_message(
                chat_id,
                f"Sorry, there was an error processing your text. Please try again with shorter text."
            )
        
    finally:
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                os.remove(temp_file)
                logger.debug(f"Temporary file removed: {temp_file}")

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    user_id = message.from_user.id
    current_speed = get_user_speed(user_id)
    welcome_text = f"""
Welcome to Malayalam Text-to-Speech Bot! 🎙️

Send me any text message or .txt file and I'll convert it to voice messages.

Features:
✅ Malayalam language support
✅ Unlimited text length support (up to 100,000 characters)
✅ Voice messages (not audio files)
✅ Text file (.txt) support
✅ Normal and 2x speed options
✅ Smart text chunking and audio merging
✅ Progress updates for long texts

Current speed: {current_speed}x

Commands:
/speed - Toggle between normal (1x) and 2x speed
/help - Show this message

Just send me any text message or upload a .txt file to get started!
    """
    bot.reply_to(message, welcome_text)

@bot.message_handler(commands=['speed'])
def toggle_speed(message):
    user_id = message.from_user.id
    current_speed = get_user_speed(user_id)
    
    if current_speed == 1.0:
        new_speed = 2.0
        set_user_speed(user_id, new_speed)
        bot.reply_to(message, "Speed set to 2x ⚡\nAll your voice messages will now be generated at 2x speed.")
    else:
        new_speed = 1.0
        set_user_speed(user_id, new_speed)
        bot.reply_to(message, "Speed set to normal (1x) 🔊\nAll your voice messages will now be generated at normal speed.")
    
    logger.info(f"User {user_id} changed speed from {current_speed}x to {new_speed}x")

@bot.message_handler(content_types=['document'])
def handle_document(message):
    try:
        document = message.document
        
        if not document.file_name.endswith('.txt'):
            bot.reply_to(message, "Please send only .txt files. Other file types are not supported.")
            return
        
        logger.info(f"Received document from user {message.from_user.id}: {document.file_name}")
        
        bot.send_chat_action(message.chat.id, 'typing')
        
        file_info = bot.get_file(document.file_id)
        
        if not file_info.file_path:
            bot.reply_to(message, "Sorry, I couldn't download your file. Please try again.")
            return
        
        downloaded_file = bot.download_file(file_info.file_path)
        
        try:
            text = downloaded_file.decode('utf-8')
        except UnicodeDecodeError:
            try:
                text = downloaded_file.decode('latin-1')
            except Exception:
                bot.reply_to(message, "Sorry, I couldn't read this file. Please make sure it's a valid text file.")
                return
        
        if not text or text.strip() == '':
            bot.reply_to(message, "The file is empty. Please send a file with some text content.")
            return
        
        logger.info(f"Processing text file with {len(text)} characters")
        
        convert_text_to_speech(message.chat.id, text, title=f"TTS: {document.file_name}", user_id=message.from_user.id)
    
    except Exception as e:
        logger.error(f"Error processing document: {str(e)}", exc_info=True)
        bot.reply_to(message, "Sorry, there was an error processing your file. Please try again.")

@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_text_message(message):
    try:
        text = message.text
        
        if not text or text.strip() == '':
            bot.reply_to(message, "Please send me some text to convert to speech!")
            return
        
        logger.info(f"Received text from user {message.from_user.id}: {text[:50]}...")
        
        convert_text_to_speech(message.chat.id, text, user_id=message.from_user.id)
    
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}", exc_info=True)
        bot.reply_to(message, f"Sorry, there was an error converting your text to speech. Please try again.")

def main():
    logger.info("Starting Malayalam TTS Telegram Bot...")
    logger.info("Bot is ready to receive messages!")
    bot.infinity_polling()

if __name__ == '__main__':
    main()
