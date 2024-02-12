from aiogram.fsm.state import State, StatesGroup


class Gen(StatesGroup):
    text_prompt = State()
    info_message = State()
    subscription_status = State()

    @staticmethod
    async def set_state_subscription_status(state, status):
        async with state.update_data() as data:
            data['subscription_status'] = status
