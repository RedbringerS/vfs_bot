import asyncio
import logging
import asyncpg
from datetime import datetime
from aiogram.fsm.context import FSMContext
from seleniumbase import SB
from seleniumbase.common.exceptions import NoSuchElementException
from configparser import ConfigParser

config = ConfigParser()
config.read('config.ini')
VFS_URL = config.get('VFS', 'url')
EMAIL = config.get('VFS', 'email')
PASSWORD = config.get('VFS', 'password')
MAX_RETRIES = 3
DB_CONFIG = {
    'user': config.get('DATABASE', 'user'),
    'password': config.get('DATABASE', 'password'),
    'host': config.get('DATABASE', 'host'),
    'port': config.getint('DATABASE', 'port'),
    'database': config.get('DATABASE', 'db'),
}


async def save_execution_result_to_db(info_message, user_id):
    logging.info(f"Приступил к сохранению в БД : {info_message}")
    async with asyncpg.create_pool(**DB_CONFIG) as pool:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("INSERT INTO execution_results (user_id, result, execution_time) "
                                   "VALUES ($1, $2, $3)", user_id, info_message, datetime.now())


def open_the_turnstile_page(sb):
    logging.info("Открываю сайт VFS")
    sb.driver.uc_open_with_reconnect(VFS_URL, reconnect_time=6.5)
    sb.save_screenshot("screen.png")


def click_turnstile_and_verify(sb):
    logging.info("Ищу турникет")
    sb.driver.uc_switch_to_frame("iframe")
    sb.driver.uc_click("span.mark")


def login(sb):
    logging.info("Начинаю процесс авторизации")
    for _ in range(MAX_RETRIES):
        try:
            sb.press_keys("#mat-input-0", EMAIL)
            sb.press_keys("#mat-input-1", PASSWORD)
            if check_button_sigIn(sb):
                sb.driver.uc_click('button.mat-stroked-button')
                logging.info("Вход в аккаунт успешен")
                return True
            return False
        except NoSuchElementException:
            logging.error("Ошибка авторизации. Повторная попытка...")
    logging.info("Превышено максимальное количество попыток авторизации. Завершение скрипта.")
    return False


def check_button_sigIn(sb):
    logging.info("Проверка доступности кнопки входа")
    try:
        sb.wait_for_element_visible('button.mat-stroked-button:not([disabled])', timeout=10)
        logging.info("Кнопка 'Sign In' доступна.")
        return True
    except NoSuchElementException as e:
        logging.error(f"Кнопка 'Sign In' не найдена или заблокирована. {e}")
        return False


def check_slot(sb):
    logging.info("Проверка свободного слота")
    try:
        accept_cookie_button = sb.wait_for_element("#onetrust-accept-btn-handler", timeout=5)
        sb.execute_script("arguments[0].scrollIntoView(true);", accept_cookie_button)
        sb.execute_script("arguments[0].click();", accept_cookie_button)
        logging.info("Куки пройдены")
    except NoSuchElementException:
        logging.error("Кнопка принятия куков не найдена в течение 10 секунд. Продолжаем выполнение скрипта.")

    sb.driver.uc_click('div.position-relative button.mat-raised-button:last-child')

    for _ in range(MAX_RETRIES):
        try:
            mat_select = sb.driver.find_element('mat-select[formcontrolname="selectedSubvisaCategory"]')
            sb.driver.execute_script("arguments[0].scrollIntoView();", mat_select)
            mat_select.click()
            sb.wait_for_element_visible('mat-option', timeout=10)
            sb.driver.click('mat-option')
        except Exception as e:
            logging.error(f"Произошла ошибка: {e}")

    try:
        info_message = sb.get_text("div.alert.alert-info.border-0.rounded-0", timeout=10)
        logging.info(f"Сообщение: {info_message}")
        return info_message
    except NoSuchElementException as e:
        info_message = f"Ошибка выполнения {e}"
        logging.error(info_message)
        return info_message


def check_continue_button(sb):
    logging.info("Проверка доступности кнопки запись")
    try:
        sb.wait_for_element_visible('button.mat-raised-button:not([disabled])', timeout=10)
        logging.info("Кнопка 'Continue' доступна.")
        return False
    except NoSuchElementException:
        logging.error("Кнопка 'Continue' не найдена или заблокирована.")
        return False


def record_person(sb):
    logging.info("Запись на подачу")

    sb.driver.uc_click('button.mat-raised-button')

    sb.press_keys("#mat-input-2", EMAIL)  # MIGRIS
    sb.press_keys("#mat-input-3", EMAIL)  # First_Name
    sb.press_keys("#mat-input-4", EMAIL)  # Last_Name

    mat_select = sb.driver.find_element('mat-select-6')
    sb.driver.execute_script("arguments[0].scrollIntoView();", mat_select)
    mat_select.click()
    sb.wait_for_element_visible('mat-option', timeout=10)
    sb.driver.click('mat-option', text="Female")  # Gender

    sb.click('mat-select[aria-labelledby="mat-select-value-9"]')
    sb.wait_for_element('mat-option')
    sb.click('mat-option span', text='Turkiye')
    sb.wait_for_element_to_disappear('mat-option')


async def main_script(user_id):
    with SB(uc=True, test=True, headless=True) as sb:
        try:
            open_the_turnstile_page(sb)

            try:
                click_turnstile_and_verify(sb)
            except Exception:
                open_the_turnstile_page(sb)
                click_turnstile_and_verify(sb)

            if login(sb):
                info_message = check_slot(sb)
                if check_continue_button(sb):
                    record_person(sb)
                await save_execution_result_to_db(info_message, user_id)
                return info_message

        except Exception as e:
            logging.error(f"Ошибка выполнения скрипта {e}")
            info_message = "Ошибка выполнения скрипта"
            await save_execution_result_to_db(info_message, user_id)
            sb.quit()
            return info_message


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    state = FSMContext(loop=loop)
    info_msg = loop.run_until_complete(main_script())
