from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import logging


async def get_subscription_button(user_id, is_user_subscribed_func):
    try:
        subscribed = await is_user_subscribed_func(user_id)
        if subscribed:
            return InlineKeyboardButton(
                text="🚫 Отписаться от рассылки", callback_data="unsubscribe"
            )
        else:
            return InlineKeyboardButton(
                text="📝 Подписаться на рассылку свободных мест", callback_data="generate_text"
            )
    except Exception as e:
        logging.error(f"Ошибка при получении кнопки подписки: {e}")
        return None


async def get_menu(user_id, is_user_subscribed_func):
    try:
        subscription_button = await get_subscription_button(user_id, is_user_subscribed_func)
        return InlineKeyboardMarkup(inline_keyboard=[[subscription_button]])
    except Exception as e:
        logging.error(f"Error while creating menu: {e}")
        return None
