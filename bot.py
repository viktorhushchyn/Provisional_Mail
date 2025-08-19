import logging
import random
import string
import requests
import asyncio
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import BufferedInputFile
from dotenv import load_dotenv

# ================== Завантаження .env ==================
print("DEBUG: loading .env...")
load_dotenv()  # Завантажує .env
API_TOKEN = os.getenv("BOT_TOKEN")
print("DEBUG: BOT_TOKEN =", API_TOKEN)  # Перевірка

if not API_TOKEN:
    raise ValueError("⚠️ BOT_TOKEN не знайдено в .env!")

# ================== Логування ==================
logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# ================== Пам’ять користувачів ==================
user_accounts = {}
last_mail_ids = {}
stored_messages = {}
stored_attachments = {}
new_users = set()

BASE_URL = "https://api.mail.tm"

# ================== Допоміжні функції ==================
def gen_password(length=12):
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))

def create_account(retries=3):
    for attempt in range(retries):
        try:
            domains = requests.get(f"{BASE_URL}/domains").json()["hydra:member"]
            domain = random.choice(domains)["domain"]

            username = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
            email = f"{username}@{domain}"
            password = gen_password()

            acc = requests.post(f"{BASE_URL}/accounts", json={
                "address": email,
                "password": password
            })

            if acc.status_code not in (200, 201):
                raise Exception(f"{acc.status_code}: {acc.text}")

            token_resp = requests.post(f"{BASE_URL}/token", json={
                "address": email,
                "password": password
            }).json()

            return {"address": email, "password": password, "token": token_resp["token"]}
        except Exception as e:
            logging.warning(f"❌ Помилка створення акаунта (спроба {attempt+1}/{retries}): {e}")
            if attempt == retries - 1:
                raise Exception(f"Не вдалося створити акаунт після {retries} спроб: {e}")
            asyncio.sleep(1)  # пауза перед повтором

def get_messages(token):
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{BASE_URL}/messages", headers=headers).json()
    return resp.get("hydra:member", [])

def get_message(token, msg_id):
    headers = {"Authorization": f"Bearer {token}"}
    return requests.get(f"{BASE_URL}/messages/{msg_id}", headers=headers).json()

def to_kyiv_time_forced(iso_str: str) -> str:
    if not iso_str:
        return ""
    try:
        dt_utc = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        dt_fixed = dt_utc + timedelta(hours=3)
        return dt_fixed.strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        return iso_str

# ================== Хендлери ==================
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    kb = [
        [types.KeyboardButton(text="📧 Згенерувати нову пошту")],
        [types.KeyboardButton(text="📬 Перевірити скриньку")]
    ]
    keyboard = types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

    await message.answer(
        "👋 Вітаю!\n\n"
        "✨ **ProvisionalMail** – бот для створення **тимчасових поштових скриньок**.\n\n"
        "📩 Тимчасові пошти потрібні для:\n"
        "— Реєстрації на сайтах без ризику спаму 🛡️\n"
        "— Тестування сервісів ⚙️\n"
        "— Захисту приватності 🔒\n\n"
        "⚡ Натискай кнопки нижче, щоб почати:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

    if message.from_user.id not in new_users:
        new_users.add(message.from_user.id)
        changelog = (
            "📢 **Що нового в ProvisionalMail v1.2**\n"
            "— 🕒 Виправлено відображення часу\n"
            "— 📎 Підтримка вкладень\n"
            "— 🔘 Кнопка «Показати вкладення»\n"
            "— 📄 Кнопка «Показати повний лист»\n"
            "— 🎨 Оновлена структура повідомлень\n"
            "— 🛡 Оптимізована перевірка пошти\n"
            "— 🗒️ Примітка: отримання листа ботом ≈ 1-2 хвилини!"
        )
        await message.answer(changelog, parse_mode="Markdown")

@dp.message(F.text == "📧 Згенерувати нову пошту")
async def get_mail(message: types.Message):
    try:
        account = create_account()
        user_accounts[message.from_user.id] = account
        last_mail_ids[message.from_user.id] = set()
        await message.answer(
            f"📧 Твоя тимчасова пошта: `{account['address']}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"❌ Помилка створення акаунта: {e}")
        await message.answer(f"⚠️ Не вдалося створити акаунт: {e}")

@dp.message(F.text == "📬 Перевірити скриньку")
async def inbox(message: types.Message):
    if message.from_user.id not in user_accounts:
        await message.answer("⚠️ Спочатку створи пошту натиснувши '📧 Згенерувати нову пошту'")
        return

    account = user_accounts[message.from_user.id]
    try:
        messages = get_messages(account["token"])
    except Exception as e:
        logging.error(f"❌ Помилка отримання листів: {e}")
        await message.answer(f"⚠️ Не вдалося отримати листи: {e}")
        return

    if not messages:
        await message.answer("📭 Поки що листів немає.")
    else:
        text = "📨 Вхідні листи:\n\n"
        for mail in messages:
            mail_id = mail["id"]
            subject = mail.get("subject", "(без теми)")
            from_who = mail.get("from", {}).get("address", "невідомо")
            date_str = to_kyiv_time_forced(mail.get("createdAt", ""))
            has_att = "так" if mail.get("hasAttachments") else "ні"

            text += (
                f"ID: {mail_id}\n"
                f"Від: {from_who}\n"
                f"Тема: {subject}\n"
                f"⏰ {date_str}\n"
                f"📎 Вкладення: {has_att}\n\n"
            )
        await message.answer(text)

# ================== Фоновий таск ==================
async def check_new_mails():
    while True:
        for user_id, account in list(user_accounts.items()):
            try:
                messages = get_messages(account["token"])
                for mail in messages:
                    mail_id = mail["id"]
                    if mail_id not in last_mail_ids.get(user_id, set()):
                        last_mail_ids.setdefault(user_id, set()).add(mail_id)
                        full_mail = get_message(account["token"], mail_id)

                        subject = full_mail.get("subject", "Без теми")
                        from_who = full_mail.get("from", {}).get("address", "невідомо")
                        body = full_mail.get("text") or "📎 (у листі лише вкладення)"
                        date_str = to_kyiv_time_forced(full_mail.get("createdAt", ""))
                        attachments = full_mail.get("attachments", []) or []
                        stored_attachments[(user_id, mail_id)] = attachments

                        kb = InlineKeyboardBuilder()
                        have_buttons = False

                        if attachments:
                            kb.button(
                                text=f"📎 Показати вкладення ({len(attachments)})",
                                callback_data=f"show_attachments:{mail_id}"
                            )
                            have_buttons = True

                        if len(body) > 1500:
                            stored_messages[(user_id, mail_id)] = body
                            kb.button(
                                text="📄 Показати повний лист",
                                callback_data=f"show_full:{mail_id}"
                            )
                            have_buttons = True
                            await bot.send_message(
                                user_id,
                                "📬 Новий лист!\n"
                                f"⏰ Час отримання листа – {date_str}\n\n"
                                f"Від: {from_who}\n"
                                f"Тема: {subject}\n\n"
                                "ℹ️ У листі забагато символів.",
                                reply_markup=kb.as_markup() if have_buttons else None
                            )
                        else:
                            await bot.send_message(
                                user_id,
                                "📬 Новий лист!\n"
                                f"⏰ Час отримання листа – {date_str}\n\n"
                                f"Від: {from_who}\n"
                                f"Тема: {subject}\n\n"
                                f"{body}",
                                reply_markup=kb.as_markup() if have_buttons else None
                            )

            except Exception as e:
                logging.error(f"❌ Помилка у check_new_mails: {e}")

        await asyncio.sleep(30)

# ================== Callback хендлери ==================
@dp.callback_query(F.data.startswith("show_full:"))
async def show_full(callback: types.CallbackQuery):
    mail_id = callback.data.split(":")[1]
    key = (callback.from_user.id, mail_id)
    if key in stored_messages:
        body = stored_messages[key]
        await callback.message.answer(f"📄 Повний текст листа:\n\n{body}")
    else:
        await callback.message.answer("⚠️ Лист недоступний.")
    await callback.answer()

@dp.callback_query(F.data.startswith("show_attachments:"))
async def show_attachments(callback: types.CallbackQuery):
    mail_id = callback.data.split(":")[1]
    key = (callback.from_user.id, mail_id)
    account = user_accounts.get(callback.from_user.id)

    if not account or key not in stored_attachments:
        await callback.message.answer("⚠️ Вкладення недоступні.")
        await callback.answer()
        return

    attachments = stored_attachments[key]

    for att in attachments:
        try:
            url = f"{BASE_URL}/messages/{mail_id}/attachments/{att['id']}"
            headers = {"Authorization": f"Bearer {account['token']}"}
            file_resp = requests.get(url, headers=headers)

            filename = att.get("filename") or "attachment"
            content_type = (att.get("mimeType") or att.get("contentType") or "").lower()
            data = file_resp.content
            input_file = BufferedInputFile(data, filename=filename)

            if content_type.startswith("image/"):
                await bot.send_photo(callback.from_user.id, input_file, caption="🖼 Вкладене зображення")
            elif content_type.startswith("video/"):
                await bot.send_video(callback.from_user.id, input_file, caption="🎥 Вкладене відео")
            else:
                await bot.send_document(callback.from_user.id, input_file)

        except Exception as e:
            logging.error(f"❌ Помилка при завантаженні вкладення: {e}")
            await callback.message.answer(f"⚠️ Не вдалося надіслати один із файлів: {e}")

    await callback.answer()

# ================== Main ==================
async def main():
    asyncio.create_task(check_new_mails())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
