import logging
import random
import string
import requests
import asyncio
import io
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import BufferedInputFile
from dotenv import load_dotenv

# ================== Завантаження .env ==================
# Вказуємо точний шлях і гарантуємо перевизначення змінних
load_dotenv(dotenv_path="/home/oldiezy/Provisional_Mail/.env", override=True)

API_TOKEN = os.getenv("BOT_TOKEN")
print("DEBUG: BOT_TOKEN =", API_TOKEN)  # Перевірка, щоб переконатися, що токен читається

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# ================== Пам’ять користувачів ==================
user_accounts = {}        # user_id -> {"address": ..., "password": ..., "token": ...}
last_mail_ids = {}        # user_id -> set(message_ids)
stored_messages = {}      # (user_id, mail_id) -> body
stored_attachments = {}   # (user_id, mail_id) -> [attachments]
new_users = set()         # для відстеження нових користувачів

BASE_URL = "https://api.mail.tm"

# ================== Допоміжні функції ==================
def gen_password(length=12):
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def create_account():
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
        raise Exception(f"Помилка створення акаунта: {acc.text}")

    token_resp = requests.post(f"{BASE_URL}/token", json={
        "address": email,
        "password": password
    }).json()

    return {"address": email, "password": password, "token": token_resp["token"]}


def get_messages(token):
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{BASE_URL}/messages", headers=headers).json()
    return resp.get("hydra:member", [])


def get_message(token, msg_id):
    headers = {"Authorization": f"Bearer {token}"}
    return requests.get(f"{BASE_URL}/messages/{msg_id}", headers=headers).json()


# Жорстке зміщення +3 години від UTC
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
            "— 📎 Підтримка вкладень (зображення, документи, відео)\n"
            "— 🔘 Кнопка «Показати вкладення» для зручного завантаження файлів\n"
            "— 📄 Кнопка «Показати повний лист» для довгих листів\n"
            "— 🎨 Оновлена структура повідомлень:\n"
            "  📬 Новий лист!\n"
            "  ⏰ Час отримання листа – ...\n"
            "— 🛡 Оптимізована перевірка пошти та покращена стабільність\n"
            "— 🗒️ Примітка: отримання листа ботом ≈ 1-2 хвилини!\n"
        )
        await message.answer(changelog, parse_mode="Markdown")


@dp.message(F.text == "📧 Згенерувати нову пошту")
async def get_mail(message: types.Message):
    account = create_account()
    user_accounts[message.from_user.id] = account
    last_mail_ids[message.from_user.id] = set()
    await message.answer(
        f"📧 Твоя тимчасова пошта: `{account['address']}`",
        parse_mode="Markdown"
    )


@dp.message(F.text == "📬 Перевірити скриньку")
async def inbox(message: types.Message):
    if message.from_user.id not in user_accounts:
        await message.answer("⚠️ Спочатку створи пошту натиснувши '📧 Згенерувати нову пошту'")
        return

    account = user_accounts[message.from_user.id]
    messages = get_messages(account["token"])

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


# 🔄 Автоматична перевірка нових листів
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


# 📄 Показати повний лист
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


# 📎 Показати вкладення
@dp.callback_query(F.data.startswith("show_attachments:"))
async def show_attachments(callback: types.CallbackQuery):
    mail_id = callback.data.split(":")[1]
    key = (callback.from_user.id, mail_id)
    attachments = stored_attachments.get(key, [])

    if not attachments:
        await callback.message.answer("📎 Вкладень немає.")
        await callback.answer()
        return

    for att in attachments:
        fname = att.get("filename", "file")
        f_url = att.get("url")
        if f_url:
            r = requests.get(f_url)
            f = BufferedInputFile(io.BytesIO(r.content), filename=fname)
            await callback.message.answer_document(f)
    await callback.answer()


# ================== Запуск бота ==================
async def main():
    # Паралельно polling та перевірка нових листів
    task1 = asyncio.create_task(dp.start_polling(bot))
    task2 = asyncio.create_task(check_new_mails())
    await asyncio.gather(task1, task2)


if __name__ == "__main__":
    asyncio.run(main())
