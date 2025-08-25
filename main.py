import logging
import os
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
)
import yt_dlp
import lyricsgenius

TELEGRAM_BOT_TOKEN = "7619265642:AAG0ZdY94aNea2f4RLcy2Ubmw6qzgVx5dXQ"
GENIUS_ACCESS_TOKEN = "5j1P1reu89Ii5lr94MBbrZwlVyTqQ3d8SEp3L6kdDm8E_ZbWUHFnjL7LNRNoTZmf"

FFMPEG_PATH = "ffmpeg"  # для Railway / Linux
DOWNLOAD_DIR = "downloads"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

genius = lyricsgenius.Genius(GENIUS_ACCESS_TOKEN, verbose=False, remove_section_headers=True)


def find_lyrics(song_title, artist):
    """Ищет текст песни на Genius.com."""
    try:
        cleaned_title = re.sub(r'\(.*?\)|\[.*?\]|ft\..*|feat\..*', '', song_title, flags=re.IGNORECASE).strip()
        logger.info(f"Ищу текст для: '{cleaned_title}' исполнителя '{artist}'")
        song = genius.search_song(cleaned_title, artist)
        if song:
            return song.lyrics.replace(f"{song.title} Lyrics", "").strip()
        return None
    except Exception as e:
        logger.error(f"Ошибка при поиске текста: {e}")
        return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_html(
        f"Привет, {user.mention_html()}! 👋\n\n"
        "Отправь мне название песни, и я найду её для тебя, а также смогу показать её текст!"
    )


async def handle_song_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.message.text
    message = await update.message.reply_text("🔎 Ищу песню... Пожалуйста, подождите.")

    try:
        ydl_opts = {'format': 'bestaudio/best', 'noplaylist': True, 'quiet': True, 'extract_flat': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_query = f"ytsearch5:{query}"
            info = ydl.extract_info(search_query, download=False)

            if not info or not info.get('entries'):
                await message.edit_text("❌ К сожалению, ничего не найдено по вашему запросу.")
                return

            keyboard = []
            if 'search_results' not in context.chat_data:
                context.chat_data['search_results'] = {}

            for item in info['entries']:
                video_id = item['id']
                title = item.get('title', 'Без названия')
                context.chat_data['search_results'][video_id] = {
                    'title': title,
                    'artist': item.get('uploader', '')
                }

                button_title = title[:50] + "..." if len(title) > 50 else title
                keyboard.append([InlineKeyboardButton(button_title, callback_data=f"dl_{video_id}")])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await message.edit_text('Вот что мне удалось найти. Выберите подходящий вариант:', reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Ошибка при поиске '{query}': {e}")
        await message.edit_text("😥 Произошла ошибка во время поиска.")


async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    action, data = query.data.split('_', 1)

    if action == 'dl':
        chat_id = query.message.chat_id
        await query.message.edit_text("⏳ Скачиваю выбранный трек...")
        await download_and_send_song(chat_id, data, context, query.message)

    elif action == 'lyrics':
        video_id = data
        song_info = context.chat_data.get('search_results', {}).get(video_id)

        if not song_info:
            await query.message.reply_text("Не удалось найти информацию о песне для поиска текста. Попробуйте найти песню заново.")
            return

        await query.edit_message_reply_markup(None)
        await query.answer("Ищу текст песни...")

        lyrics = find_lyrics(song_info['title'], song_info['artist'])
        if lyrics:
            for i in range(0, len(lyrics), 4096):
                await query.message.reply_text(lyrics[i:i + 4096])
        else:
            await query.message.reply_text("К сожалению, не удалось найти текст для этой песни.")


async def download_and_send_song(chat_id: int, video_id: str, context: ContextTypes.DEFAULT_TYPE, message_to_edit) -> None:
    """Скачивает песню с YouTube, конвертирует в mp3 и отправляет с кнопкой 'Показать текст'."""
    downloaded_file_path = ""
    try:
        ydl_opts = {
            'ffmpeg_location': FFMPEG_PATH,
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192'
            }],
            'outtmpl': os.path.join(DOWNLOAD_DIR, f'{chat_id}_{video_id}.%(ext)s'),
            'noplaylist': True,
            'quiet': True,
        }

        video_url = f"https://www.youtube.com/watch?v={video_id}"
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(video_url, download=True)
            downloaded_file_path = ydl.prepare_filename(info_dict).rsplit('.', 1)[0] + '.mp3'

        if not os.path.exists(downloaded_file_path):
            raise FileNotFoundError("Скачанный mp3 файл не найден.")

        await message_to_edit.edit_text("🎧 Отправляю трек...")

        keyboard = [[InlineKeyboardButton("📜 Показать текст", callback_data=f"lyrics_{video_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        with open(downloaded_file_path, 'rb') as audio_file:
            await context.bot.send_audio(
                chat_id=chat_id,
                audio=audio_file,
                title=info_dict.get('title', 'Без названия'),
                performer=info_dict.get('uploader', 'Неизвестный исполнитель'),
                duration=info_dict.get('duration', 0),
                reply_markup=reply_markup
            )

        await message_to_edit.delete()

    except Exception as e:
        logger.error(f"Ошибка при скачивании/отправке (ID: {video_id}): {e}")
        await message_to_edit.edit_text("😥 Произошла ошибка. Не удалось скачать трек.")

    finally:
        if downloaded_file_path and os.path.exists(downloaded_file_path):
            os.remove(downloaded_file_path)


def main() -> None:
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("stpart", start))
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_song_request))

    print("Бот запущен...")
    application.run_polling()


if __name__ == "__main__":
    main()
