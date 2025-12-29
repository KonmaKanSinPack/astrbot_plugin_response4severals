from dataclasses import dataclass, field
import json
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

from astrbot.core.agent.message import (
    AssistantMessageSegment,
    UserMessageSegment,
    TextPart,
)

from astrbot.core.conversation_mgr import Conversation
from astrbot.api.event import MessageChain
@dataclass
class _SessionState:
    is_listening: bool = False
    # buffer: List[str] = field(default_factory=list)
    buffer = ""

@register("astrbot_plugin_chat4severals", "兔子", "更好的聊天。", "v1.0.0")
class Chat4severals_Plugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._session_states: Dict[str, _SessionState] = {}
        self.context = context
        

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def on_all_message(self, event: AstrMessageEvent):  
        session_key, state = self._get_session_state(event)

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
                if cur_msg == "": #只收到一条信息的情况
                    return
                # state.buffer.append(cur_msg)
                state.buffer = state.buffer + f"{cur_msg}\n"
                logger.info("会话 %s 收集到消息: %s", session_key, state.buffer)
                controller.keep(timeout=timer, reset_timeout=True)
                
            try:
                state.buffer = event.message_str  # 或 append 到列表
                await wait_for_response(event)
            except TimeoutError:
                logger.info("No more messages received within timeout.")
                # collected = "\n".join(state.buffer)
                collected = state.buffer
                logger.info("Collected messages for %s: %s", session_key, collected)
                # event.message_str = collected
                await self.send_prompt(event, collected)
                state.buffer = ""
            except Exception as e:
                yield event.plain_result("发生内部错误，请联系管理员: " + str(e))
            finally:
                state.is_listening = False
                if not state.buffer:
                    self._session_states.pop(session_key, None)
                event.stop_event()
        except Exception as e:
            yield event.plain_result("发生错误，请联系管理员: " + str(e))

    async def send_prompt(self, event, msg):
        uid = event.unified_msg_origin
        provider_id = await self.context.get_current_chat_provider_id(uid)
        logger.info(f"umo:{uid}")

        #获取会话历史
        conv_mgr = self.context.conversation_manager
        curr_cid = await conv_mgr.get_curr_conversation_id(uid)
        conversation = await conv_mgr.get_conversation(uid, curr_cid)  # Conversation
        history = json.loads(conversation.history) if conversation and conversation.history else []
        # 验证历史记录格式
        # logger.info(f"原始历史记录:{history}")
        # valid_history = []
        # for item in history:
        #     if isinstance(item, dict) and "role" in item and "content" in item:
        #         if isinstance(item["content"], str):
        #             valid_history.append(item)

        #获取人格
        system_prompt = await self.get_persona_system_prompt(uid)

        #发送信息到llm
        sys_msg = f"{system_prompt}"
        user_msg = UserMessageSegment(content=[TextPart(text=msg)])
        provider = self.context.get_using_provider()
        logger.info(f"msg:{msg},\n history:{history}")
        llm_resp = await provider.text_chat(
                prompt=msg,
                session_id=None,
                contexts=history,
                image_urls=[],
                func_tool=None,
                system_prompt=sys_msg,
            )
        await conv_mgr.add_message_pair(
            cid=curr_cid,
            user_message=user_msg,
            assistant_message=AssistantMessageSegment(
                content=[TextPart(text=llm_resp.completion_text)]
            ),
        )
        message_chain = MessageChain().message(llm_resp.completion_text)
        await self.context.send_message(event.unified_msg_origin, message_chain)

    async def get_persona_system_prompt(self, session: str) -> str:
        """获取人格系统提示词

        Args:
            session: 会话ID

        Returns:
            人格系统提示词
        """
        base_system_prompt = ""
        try:
            # 尝试获取当前会话的人格设置
            uid = session  # session 就是 unified_msg_origin
            curr_cid = await self.context.conversation_manager.get_curr_conversation_id(
                uid
            )

            # 获取默认人格设置
            default_persona_obj = self.context.provider_manager.selected_default_persona

            if curr_cid:
                conversation = await self.context.conversation_manager.get_conversation(
                    uid, curr_cid
                )

                if (
                    conversation
                    and conversation.persona_id
                    and conversation.persona_id != "[%None]"
                ):
                    # 有指定人格，尝试获取人格的系统提示词
                    personas = self.context.provider_manager.personas
                    if personas:
                        for persona in personas:
                            if (
                                hasattr(persona, "name")
                                and persona.name == conversation.persona_id
                            ):
                                base_system_prompt = getattr(persona, "prompt", "")
                                
                                break

            # 如果没有获取到人格提示词，尝试使用默认人格
            if (
                not base_system_prompt
                and default_persona_obj
                and default_persona_obj.get("prompt")
            ):
                base_system_prompt = default_persona_obj["prompt"]
                

        except Exception as e:
            logger.warning(f"获取人格系统提示词失败: {e}")

        return base_system_prompt

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""

    def _get_session_state(self, event: AstrMessageEvent):
        """确保每个用户会话拥有独立的缓存状态。"""
        session_key = event.unified_msg_origin
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
