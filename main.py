from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.provider import ProviderRequest
import astrbot.api.message_components as Comp
from astrbot.core.utils.session_waiter import (
    session_waiter,
    SessionController,
)
import asyncio
from astrbot.api.event import MessageChain
from astrbot.api import AstrBotConfig
@register("astrbot_plugin_betterchat", "兔子", "更好的聊天。", "v1.0.0")
class Chat4severals_Plugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        # self.is_listening = asyncio.Lock()
        self.is_listening = False
        self.hole_msgs = ""
        self.iswaitting = False
        self._ready_event = asyncio.Event()
        self.timer = self.config.get("timer", 4.0)

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def on_all_message(self, event: AstrMessageEvent):
        if self.is_listening:
            logger.info("当前正在监听消息，请稍后再试。")
            return
        # umo = event.unified_msg_origin
        self.is_listening = True
        try:
            @session_waiter(timeout=self.timer, record_history_chains=False)
            async def wait_for_response(controller: SessionController, event: AstrMessageEvent):
                cur_msg = event.message_str
                self.hole_msgs += f"{cur_msg}\n"
                controller.keep(timeout=self.timer, reset_timeout=True)
            try:
                await wait_for_response(event)
            except TimeoutError:
                logger.info("No more messages received within timeout.")
                logger.info(f"Collected messages:{self.hole_msgs}")
                # message_chain = MessageChain().message(self.hole_msgs)
                self._ready_event.set()
                self.is_listening = False
                event.message_str=self.hole_msgs
            except Exception as e:
                yield event.plain_result("发生内部错误，请联系管理员: " + str(e))
            finally:
                self.is_listening = False
                # event.stop_event()
        except Exception as e:
            yield event.plain_result("发生错误，请联系管理员: " + str(e))


    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
