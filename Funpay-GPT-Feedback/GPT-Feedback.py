import os
import re
from datetime import datetime
from dotenv import load_dotenv

from g4f.client import Client
from FunPayAPI import Account
from FunPayAPI.types import MessageTypes
from FunPayAPI.updater.runner import Runner
from FunPayAPI.updater.events import NewMessageEvent

MAX_ATTEMPTS = 10
MAX_CHARACTERS = 700
MIN_CHARACTERS = 50
ORDER_ID_REGEX = re.compile(r"#([A-Za-z0-9]+)")

load_dotenv()
FUNPAY_AUTH_TOKEN = os.getenv("FUNPAY_AUTH_TOKEN")
if not FUNPAY_AUTH_TOKEN:
    raise ValueError("❌ FUNPAY_AUTH_TOKEN не найден в .env файле!")

MIN_RATING = int(os.getenv("MIN_RATING", "1"))

client = Client()

PROMPT_TEMPLATE = """
Привет! Ты — ИИ-ассистент в магазине игровых ценностей.
Данные заказа:
    - Оценка: {rating} из 5
    - Отзыв: {text}

Составь дружелюбный ответ:
- Используй много эмодзи.
- Пожелай что-то хорошее.
- Сделай шутку про покупку.
- В конце добавь: спасибо за {rating} звезд и отзыв от {date} {time}! Мы очень рады, что вам понравилась покупка.
Не используй HTML, markdown или код.
"""

def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."

def build_prompt(order) -> str:
    rating = getattr(order.review, "stars", None) or "5"
    text = getattr(order.review, "text", None) or "Спасибо!"
    return PROMPT_TEMPLATE.format(
        rating=rating,
        text=text,
        date=datetime.now().strftime("%d.%m.%Y"),
        time=datetime.now().strftime("%H:%M:%S"),
    )

def generate_response(prompt: str) -> str:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}]
            )
            text = " ".join(response.choices[0].message.content.strip().splitlines())

            if len(text) < MIN_CHARACTERS:
                print(f"[!] Ответ слишком короткий ({len(text)} символов), попытка {attempt}")
                continue
            if len(text) > MAX_CHARACTERS:
                text = truncate(text, MAX_CHARACTERS)

            return text
        except Exception as e:
            print(f"[!] Ошибка генерации (попытка {attempt}): {e}")

    return "Спасибо за отзыв! 😊"

def handle_feedback(event: NewMessageEvent, account: Account):
    if event.message.type not in (MessageTypes.NEW_FEEDBACK, MessageTypes.FEEDBACK_CHANGED):
        return

    order_id_match = ORDER_ID_REGEX.search(str(event.message))
    if not order_id_match:
        print("[!] Не найден ID заказа в сообщении")
        return

    order_id = order_id_match.group(1)
    order = account.get_order(order_id)

    if not order or not order.review:
        print(f"[!] Заказ {order_id} не найден или отзыв отсутствует")
        return

    stars = getattr(order.review, "stars", 0) or 0
    try:
        stars_int = int(stars)
    except Exception:
        stars_int = 0

    if stars_int < MIN_RATING:
        if order.review.reply:
            try:
                account.delete_review(order.id)
                print(f"[+] Удалён ответ на отзыв заказа #{order.id} из-за низкого рейтинга {stars_int}")
            except Exception as e:
                print(f"[!] Ошибка удаления ответа на отзыв #{order.id}: {e}")
        else:
            print(f"[=] Нет ответа на отзыв #{order.id} для удаления (рейтинг {stars_int} < {MIN_RATING})")
        return

    prompt = build_prompt(order)
    reply_text = generate_response(prompt)
    try:
        account.send_review(order.id, text=reply_text, rating=stars_int)
        print(f"[+] Ответ отправлен/обновлён на отзыв для заказа #{order.id} с рейтингом {stars_int}")
    except Exception as e:
        print(f"[!] Ошибка отправки ответа на отзыв #{order.id}: {e}")

def main():
    account = Account(golden_key=FUNPAY_AUTH_TOKEN)
    account.get()

    runner = Runner(account)
    print("🤖 GPT-бот запущен. Ожидаем отзывы и их изменения...")

    for event in runner.listen(requests_delay=3.0):
        if isinstance(event, NewMessageEvent):
            handle_feedback(event, account)

if __name__ == "__main__":
    main()
