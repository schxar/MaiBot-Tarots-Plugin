from src.plugin_system.base.base_plugin import BasePlugin
from src.plugin_system.base.base_plugin import register_plugin
from src.plugin_system.base.base_action import BaseAction, ActionActivationType, ChatMode
from src.plugin_system.base.component_types import ComponentInfo
from src.common.logger import get_logger
from PIL import Image
from typing import Tuple, Dict, Optional, List, Type
from pathlib import Path
import json
import random
import asyncio
import aiohttp
import base64
import io

logger = get_logger("tarots")

class TarotsAction(BaseAction):
    action_name = "tarots"

    # 双激活类型配置
    focus_activation_type = ActionActivationType.LLM_JUDGE
    normal_activation_type = ActionActivationType.ALWAYS
    activation_keywords = ["抽一张塔罗牌", "抽张塔罗牌"]
    keyword_case_sensitive = False

     # 模式和并行控制
    mode_enable = ChatMode.ALL
    parallel_action = False

    action_description = "执行塔罗牌占卜，支持多种抽牌方式" # action描述
    action_parameters = {
        "card_type": {
            "type": "str",
            "enum": ["全部", "大阿卡纳", "小阿卡纳"],
            "default": "全部",
            "description": "抽牌范围：全部，大阿卡纳，小阿卡纳" # 具体抽牌范围的描述
        },
        "formation": {
            "type": "str",
            "enum": ["单张", "圣三角", "时间之流","四要素","五牌阵","吉普赛十字","马蹄","六芒星"],
            "default": "单张",
            "description": "抽牌方式：单张,圣三角，时间之流，四要素，五牌阵，吉普赛十字，马蹄，六芒星" # 具体抽牌方式的描述 
        }
    }
    action_require = [
        "当消息包含'抽塔罗牌''塔罗牌占卜'等关键词，且用户明确表达了要求你帮忙抽牌的意向时，看心情调用（这意味着你可以拒绝抽牌）",
        "用户需要明确指定抽牌范围和抽牌类型，如果用户未明确指定抽牌范围则默认为'全部'，未明确指定抽牌类型则默认为'单张'",
        "完成一次抽牌后，需要确定用户有没有明确要求再抽一次，没有再次要求就不要继续抽"
    ]

    associated_types = ["image", "text"] #该插件会发送的消息类型
    
    def __init__(self,
    action_data: dict,
    reasoning: str,
    cycle_timers: dict,
    thinking_id: str,
    global_config: Optional[dict] = None,
    **kwargs,
    ):
        # 显式调用父类初始化
        super().__init__(
        action_data=action_data,
        reasoning=reasoning,
        cycle_timers=cycle_timers,
        thinking_id=thinking_id,
        global_config=global_config,
        **kwargs
    )
        # 初始化路径
        self.base_dir = Path(__file__).parent.absolute()
        self.cache_dir = self.base_dir / "tarots_cache" # 定义图片缓存文件夹为tarots_cache
        self.cache_dir.mkdir(exist_ok=True) # 不存在该文件夹就创建
        
        # 加载卡牌数据
        self.card_map: Dict = {}
        self.formation_map: Dict = {}
        self._load_resources()

    def _load_resources(self):
        """同步加载资源文件(显式指定UTF-8编码)"""
        try:
            # 加载卡牌数据
            with open(
                self.base_dir / "tarot_jsons/tarots.json", 
                encoding="utf-8"  
            ) as f:
                self.card_map = json.load(f)
            
            # 加载牌阵配置
            with open(
                self.base_dir / "tarot_jsons/formation.json", 
                encoding="utf-8"  
            ) as f:
                self.formation_map = json.load(f)
                
            logger.info(f"{self.log_prefix} 已加载{len(self.card_map)}张卡牌和{len(self.formation_map)}种抽牌方式")
        except UnicodeDecodeError as e:
            logger.error(f"{self.log_prefix} 编码错误: 请确保JSON文件为UTF-8格式 - {str(e)}")
            raise
        except Exception as e:
            logger.error(f"{self.log_prefix} 资源加载失败: {str(e)}")
            raise

    async def execute(self) -> Tuple[bool, str]:
        """实现基类要求的入口方法"""
        try:
            logger.info(f"{self.log_prefix} 开始执行塔罗占卜")
            
            # 参数解析
            card_type = self.action_data.get("card_type", "全部") 
            formation_name = self.action_data.get("formation", "单张")
            
            # 参数校验
            if card_type not in ["全部", "大阿卡纳", "小阿卡纳"]:
                await self.send_reply("不存在这样的抽牌范围")
                return False, "参数错误"
                
            if formation_name not in self.formation_map:
                await self.send_reply("不存在这样的抽牌方法")
                return False, "参数错误"
    
            # 获取牌阵配置
            formation = self.formation_map[formation_name] # 根据确定好的抽牌方式名称获取具体牌阵的字典
            cards_num = formation["cards_num"] # 该抽牌方式要抽几张牌
            is_cut = formation["is_cut"] # 该抽牌方式要不要切牌
            represent_list = formation["represent"] # 该抽牌方式所包含的预言方向内容
    
            # 获取有效卡牌范围
            valid_ids = self._get_card_range(card_type)
            if not valid_ids:
                await self.send_reply("当前牌堆不对")
                return False, "参数错误"
    
            # 抽牌逻辑
            selected_ids = random.sample(valid_ids, cards_num)
            if is_cut:
                selected_cards = [
                    (cid, random.random() < 0.5)  # 切牌时50%概率逆位
                    for cid in selected_ids
                ]
            else:
                selected_cards = [
                    (cid, False)  # 不切牌时全部正位
                    for cid in selected_ids
                ]
    
            # 结果处理
            result_text = f"【{formation_name}牌阵】\n"
            for idx, (card_id, is_reverse) in enumerate(selected_cards):
                card_data = self.card_map[card_id]
                card_info = card_data["info"]
                pos_name = represent_list[0][idx] if idx < len(represent_list[0]) else f"位置{idx+1}"
                
                # 轮询发送图片
                img_data = await self._get_card_image(card_id, is_reverse)
                if img_data:
                    b64_data = base64.b64encode(img_data).decode('utf-8')
                    await self.send_reply_type("image", b64_data)
                
                # 轮询构建文本
                desc = card_info['reverseDescription'] if is_reverse else card_info['description']
                result_text += (
                    f"\n{pos_name} - {'逆位' if is_reverse else '正位'} {card_data['name']}\n"
                    f"{desc[:100]}...\n"
                )
                await asyncio.sleep(0.3)  # 防止消息频率限制
                
            # 发送最终文本
            await asyncio.sleep(1.2) # 权宜之计，给最后一张图片1.2s的发送起跑时间，无可奈何的办法
            await self.send_message_by_expressor(result_text) # 这里使用了expressor方式发送，让你的麦麦用自己的语言风格阐释结果。
            return True, "占卜成功，已发送结果"
            
        except Exception as e:
            logger.error(f"{self.log_prefix} 执行失败: {str(e)}")
            await self.send_reply(f"占卜失败: {str(e)}")
            return False, "执行错误"
        
    def _get_card_range(self, card_type: str) -> list:
        """获取卡牌范围"""
        if card_type == "大阿卡纳":
            return [str(i) for i in range(22)]
        elif card_type == "小阿卡纳":
            return [str(i) for i in range(22, 78)]
        return list(self.card_map.keys()) # 既不是大阿卡纳也不是小阿卡纳就返回全部的
    
    async def _get_card_image(self, card_id: str, is_reverse: bool) -> Optional[bytes]:
        """获取卡牌图片（有缓存机制）"""
        try:
            filename = f"{card_id}_norm.png"
            cache_path = self.cache_dir / filename
            
            if not cache_path.exists():
                await self._download_image(card_id, cache_path)
            
            with open(cache_path, "rb") as f:
                img_data = f.read()
            
            if is_reverse:
                img_data = self._rotate_image(img_data) # 如果是逆位牌，直接把正位牌扭180度

            return img_data

        except Exception as e:
            logger.warning(f"{self.log_prefix} 获取图片失败: {str(e)}")
            return None
        
    def _rotate_image(self, img_data: bytes) -> bytes:
        """将图片旋转180度生成逆位图片"""
        try:
            # bytes → PIL Image对象
            image = Image.open(io.BytesIO(img_data))
            
            # 旋转180度（逆时针）
            rotated_image = image.rotate(180)
            
            # PIL Image对象 → bytes
            buffer = io.BytesIO()
            rotated_image.save(buffer, format='PNG')
            return buffer.getvalue()
            
        except Exception as e:
            logger.error(f"{self.log_prefix} 图片旋转失败: {str(e)}")
            # 旋转失败时返回原图
            return img_data
        
    async def _download_image(self, card_id: str, save_path: Path):
        """图片本地缓存"""
        MAX_RETRIES = 3
        RETRY_DELAY = 2  # 初始重试间隔（秒）

        try:
            # 获取卡牌数据
            card_info = self.card_map[card_id]["info"]
            img_path = card_info['imgUrl']
            
            # 构建下载URL
            base_url = "https://raw.githubusercontent.com/FloatTech/zbpdata/main/Tarot/"
            full_url = f"{base_url}{img_path}"

            # 下载尝试循环
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    logger.info(f"[图片下载] 尝试 {attempt}/{MAX_RETRIES} - {card_id} - {full_url}")
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.get(full_url, timeout=15) as resp:
                            if resp.status == 200:
                                # 确保目录存在
                                save_path.parent.mkdir(parents=True, exist_ok=True)
                                
                                # 写入文件
                                with open(save_path, "wb") as f:
                                    f.write(await resp.read())
                                
                                logger.info(f"[图片下载] 成功 {save_path.name} (尝试 {attempt}次)")
                                return
                            else:
                                logger.warning(f"[图片下载] 异常状态码 {resp.status} - {full_url}")
                                
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.warning(f"[图片下载] 尝试 {attempt}/{MAX_RETRIES} 失败: {str(e)}")
                    
                # 指数退避等待
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY ** attempt)

            # 最终失败处理
            logger.error(f"[图片下载] 终极失败 {full_url}，已达最大重试次数 {MAX_RETRIES}")
            raise Exception(f"图片下载失败: {full_url}")

        except KeyError:
            logger.error(f"[图片下载] 致命错误：卡牌 {card_id} 不存在于card_map中")
            raise
        
        except Exception as e:
            logger.error(f"{self.log_prefix} 图片发送失败: {str(e)}")

    async def send_reply_type(self, type: str, text: str) -> bool:
            """发送回复消息

            Args:
                content: 回复内容

            Returns:
                bool: 是否发送成功
            """
            chat_stream = self.api.get_service("chat_stream")
            if not chat_stream:
                logger.error(f"{self.log_prefix} 没有可用的聊天流发送回复")
                return False

            if chat_stream.group_info:
                # 群聊
                return await self.api.send_message_to_target(
                    message_type=type,
                    content=text,
                    platform=chat_stream.platform,
                    target_id=str(chat_stream.group_info.group_id),
                    is_group=True
                )
            else:
                # 私聊
                return await self.api.send_message_to_target(
                    message_type=type,
                    content=text,
                    platform=chat_stream.platform,
                    target_id=str(chat_stream.user_info.user_id),
                    is_group=False
                    
                )

@register_plugin
class TarotsPlugin(BasePlugin):
    """塔罗牌插件
    - 支持多种牌阵抽取
    - 支持区分大小阿卡纳抽取
    - 会在本地逐步缓存牌面图片
    - 完整的错误处理
    - 日志记录和监控
    """

    # 插件基本信息
    plugin_name = "tarots_plugin"
    plugin_description = "塔罗牌插件"
    plugin_version = "0.4.0"
    plugin_author = "A肆零西烛"
    enable_plugin = True
    config_file_name = "config.toml"

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """返回插件包含的组件列表"""

        # 从配置获取组件启用状态
        enable_tarots = self.get_config("components.enable_tarots", True)
        components = []

        # 添加Action组件
        if enable_tarots:
            components.append(
                (
                    TarotsAction.get_action_info(
                        name="tarots_action", description="塔罗牌插件，基于AI思考触发"
                    ),
                    TarotsAction,
                )
            )

        return components
