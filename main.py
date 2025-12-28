from dataclasses import dataclass, field
from typing import Dict, List

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
# from astrbot.api.provider import ProviderRequest
import astrbot.api.message_components as Comp
from astrbot.core.utils.session_waiter import (
    session_waiter,
    SessionController,
)
# import asyncio
# from astrbot.api.event import MessageChain
from astrbot.api import AstrBotConfig


@dataclass
class _SessionState:
    is_listening: bool = False
    buffer: List[str] = field(default_factory=list)

@register("astrbot_plugin_chat4severals", "兔子", "更好的聊天。", "v1.0.0")
class Chat4severals_Plugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._session_states: Dict[str, _SessionState] = {}
        

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def on_all_message(self, event: AstrMessageEvent):
        
        session_key = event.get_sender_name()
        state = self._session_states.get(session_key)
        if state is None:
            state = _SessionState()
            self._session_states[session_key] = state

        logger.info(f"得到state:{state}")
        if state.is_listening:
            logger.info(
                "会话 %s 正在收集消息，忽略并发请求。",
                session_key,
            )
            return
        timer = self.config.get("timer", 4.0)
        state.is_listening = True
        try:
            @session_waiter(timeout=timer, record_history_chains=False)
            async def wait_for_response(controller: SessionController, event: AstrMessageEvent):
                cur_msg = event.message_str
                state.buffer.append(cur_msg)
                logger.info("会话 %s 收集到消息: %s", session_key, state.buffer)
                controller.keep(timeout=timer, reset_timeout=True)
                
            try:
                await wait_for_response(event)
            except TimeoutError:
                logger.info("No more messages received within timeout.")
                collected = "\n".join(state.buffer)
                logger.info("Collected messages for %s: %s", session_key, collected)
                event.message_str = collected
                state.buffer.clear()
            except Exception as e:
                yield event.plain_result("发生内部错误，请联系管理员: " + str(e))
            finally:
                state.is_listening = False
                if not state.buffer:
                    self._session_states.pop(session_key, None)
                # event.stop_event()
        except Exception as e:
            yield event.plain_result("发生错误，请联系管理员: " + str(e))


    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""

    def _get_session_state(self, event: AstrMessageEvent):
        """确保每个用户会话拥有独立的缓存状态。"""
        session_key = event.get_sender_name()
        state = self._session_states.get(session_key)
        if state is None:
            state = _SessionState()
            self._session_states[session_key] = state
        return session_key, state

    # @staticmethod
    # def _resolve_session_key(event: AstrMessageEvent) -> str:
    #     """优先使用统一会话标识，否则退化为消息 ID。"""
    #     return event.get_sender_name()
    #     # for attr in ("unified_msg_origin", "session_id", "user_id", "message_id"):
    #     #     value = getattr(event, attr, None)
    #     #     if value:
    #     #         return str(value)
    #     return f"fallback-session-{id(event)}"
