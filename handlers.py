import asyncio
import logging
from datetime import datetime

import asyncpg
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup

import text
from kb import get_menu, get_subscription_button
from states import Gen
from vfs_trpl import main_script, DB_CONFIG

router = Router()
SCRIPT_INTERVAL = 600
user_states = {}


@router.message(Command("start"))
async def start_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        async with asyncpg.create_pool(**DB_CONFIG) as pool:
            async with pool.acquire() as conn:
                user_exists = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
                if not user_exists:
                    try:
                        async with conn.transaction():
                            await conn.execute("INSERT INTO users (user_id, last_execution_time) VALUES ($1, $2)",
                                               user_id, datetime.now())
                    except Exception as e:
                        logging.error(f"Ошибка при вставке в таблицу пользователей: {e}")
                        raise
    except Exception as e:
        logging.error(f"Ошибка подключения к PostgreSQL: {e}")
    menu = await get_menu(user_id, is_user_subscribed)
    if menu:
        await state.set_state(Gen.text_prompt)
        await message.answer(
            text.greet.format(name=message.from_user.full_name), reply_markup=menu
        )
    else:
        logging.error("Ошибка при создании меню.")


async def is_user_subscribed(user_id):
    try:
        async with asyncpg.create_pool(**DB_CONFIG) as pool:
            async with pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1 FROM subscribers WHERE user_id = $1", user_id)
                return bool(result)
    except asyncpg.exceptions.PostgresError as e:
        logging.error(f"Ошибка проверки подписки пользователя: {e}")
        return False


@router.callback_query(F.data == "generate_text")
async def generate_text_handler(clbck: CallbackQuery, state: FSMContext):
    if clbck.data == "generate_text":
        user_id = clbck.from_user.id
        await state.set_state(Gen.text_prompt)
        await clbck.message.edit_text(text.gen_text)
        await subscribe_user(clbck, user_id, state)

        menu_markup = await get_menu(user_id, is_user_subscribed)
        await clbck.message.edit_reply_markup(reply_markup=menu_markup)

        logging.info("Автоматическая подписка пользователя.")

        info_msg = await main_script(user_id)

        if info_msg:
            await msg(clbck, info_msg)
        else:
            logging.error("Ошибка: main_script не вернул действительный info_msg.")


async def msg(clbck: CallbackQuery, info_msg):
    info = "Повторный запуск через 10 минут"
    try:
        if info_msg:
            logging.info("Отправка информационного сообщения пользователю.")
            await clbck.message.answer(info_msg)
            logging.info(info)
            await clbck.message.answer(info)
        else:
            logging.error("Произошла ошибка во время обработки.")
            await clbck.message.answer(info_msg)
            logging.info(info)
            await clbck.message.answer(info)
    except Exception as e:
        logging.error(f"Ошибка во время отправки сообщения: {e}")


async def subscribe_user(clbck: CallbackQuery, user_id, state, subscribed=True):
    try:
        async with asyncpg.create_pool(**DB_CONFIG) as pool:
            async with pool.acquire() as conn:
                if subscribed:
                    await conn.execute("INSERT INTO subscribers (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)
                else:
                    await conn.execute("DELETE FROM subscribers WHERE user_id = $1", user_id)
                await state.update_data(subscription_status=subscribed)
                subscription_button = await get_subscription_button(user_id, is_user_subscribed)
                await clbck.bot.edit_message_reply_markup(chat_id=user_id, message_id=clbck.message.message_id,
                                                          reply_markup=InlineKeyboardMarkup(
                                                              inline_keyboard=[[subscription_button]]))
                await script_runner(clbck, user_id, state)
    except Exception as e:
        logging.error(f"Ошибка при управлении подпиской пользователя: {e}")


async def script_runner(clbck: CallbackQuery, user_id, state: FSMContext):
    while (await state.get_state()) == Gen.text_prompt:
        try:
            await asyncio.sleep(SCRIPT_INTERVAL)
            subscribed = await is_user_subscribed(user_id)
            data = await state.get_data()
            inner_subscription_status = data.get("subscription_status", False)
            if subscribed and inner_subscription_status:
                info_msg = await main_script(user_id)
                await state.update_data(info_message=info_msg, subscription_status=subscribed)
                await msg(clbck, info_msg)
        except Exception as e:
            logging.error(f"Ошибка во время выполнения скрипта: {e}")


async def unsubscribe_user(user_id, state):
    try:
        async with asyncpg.create_pool(**DB_CONFIG) as pool:
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM subscribers WHERE user_id = $1", user_id)
                await state.update_data(subscription_status=False)
                return True
    except Exception as e:
        logging.error(f"Ошибка управления подпиской пользователя: {e}")
        return False


@router.callback_query(F.data == "subscribe")
async def subscribe_handler(clbck: CallbackQuery, state: FSMContext):
    user_id = clbck.from_user.id
    last_execution_time = await subscribe_user(clbck, user_id, state, subscribed=True)
    if last_execution_time:
        await state.set_state(Gen.text_prompt)
        await clbck.message.answer("Вы успешно подписались на рассылку!")
        subscription_button = await get_subscription_button(user_id, is_user_subscribed)
        await clbck.bot.edit_message_reply_markup(chat_id=user_id, message_id=clbck.message.message_id,
                                                  reply_markup=InlineKeyboardMarkup(
                                                      inline_keyboard=[[subscription_button]]))
        task = asyncio.ensure_future(script_runner(clbck, user_id, state))
        task.add_done_callback(lambda t: t.result())
    else:
        await clbck.message.answer("Произошла ошибка при подписке. Попробуйте позже.")


@router.callback_query(F.data == "unsubscribe")
async def unsubscribe_handler(clbck: CallbackQuery, state):
    user_id = clbck.from_user.id
    unsubscribed = await unsubscribe_user(user_id, state)
    if unsubscribed:
        await clbck.message.answer("Вы успешно отписались от рассылки.")
        await edit_menu(clbck, user_id, is_user_subscribed)
    else:
        await clbck.message.answer("Произошла ошибка при отписке. Попробуйте позже.")


async def edit_menu(clbck: CallbackQuery, user_id, is_user_subscribed_func):
    try:
        subscription_button = await get_subscription_button(user_id, is_user_subscribed_func)
        await clbck.bot.edit_message_reply_markup(chat_id=clbck.from_user.id, message_id=clbck.message.message_id,
                                                  reply_markup=InlineKeyboardMarkup(
                                                      inline_keyboard=[[subscription_button]]))
        logging.info(f"Меню успешно обновлено для пользователя {user_id}.")
    except Exception as e:
        logging.error(f"Ошибка обновления меню для пользователя {user_id}: {e}")
