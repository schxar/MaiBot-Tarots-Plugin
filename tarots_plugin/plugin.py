from src.plugin_system.base.base_plugin import BasePlugin, register_plugin
from src.plugin_system.base.base_action import BaseAction, ActionActivationType, ChatMode
from src.plugin_system.base.base_command import BaseCommand
from src.plugin_system.base.component_types import ComponentInfo
from src.plugin_system.base.config_types import ConfigField
from src.plugin_system.apis import generator_api
from src.common.logger import get_logger
from PIL import Image
from typing import Tuple, Dict, Optional, List, Any, Type
from pathlib import Path
import json
import random
import asyncio
import aiohttp
import base64
import toml
import io
import os

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
        "card_type": "塔罗牌的抽牌范围，必填，只能填一个参数，这里请根据用户的要求填'全部'或'大阿卡纳'或'小阿卡纳'，如果用户的要求并不明确，默认填'全部'",
        "formation": "塔罗牌的抽牌方式，必填，只能填一个参数，这里请根据用户的要求填'单张'或'圣三角'或'时间之流'或'四要素'或'五牌阵'或'吉普赛十字'或'马蹄'或'六芒星'，如果用户的要求并不明确，默认填'单张'"
    }
    action_require = [
        "当消息包含'抽塔罗牌''塔罗牌占卜'等关键词，且用户明确表达了要求你帮忙抽牌的意向时，你看心情调用就行（这意味着你可以拒绝抽塔罗牌，拒绝执行这个动作）。",
        "用户需要明确指定抽牌范围和抽牌类型，如果用户未明确指定抽牌范围则默认为'全部'，未明确指定抽牌类型则默认为'单张'。",
        "请仔细辨别对方到底是不是在让你抽塔罗牌！如果用户只是单独说了'抽卡','抽牌'等，并没有上文内容验证用户是想抽塔罗牌的意思，不要抽塔罗牌，不要执行这个动作！",
        "在完成一次抽牌后，请仔细确定用户有没有明确要求再抽一次，没有再次要求就不要继续执行这个动作。"
        
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
        self._load_config()

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
                await self.send_text("不存在这样的抽牌范围")
                return False, "参数错误"
                
            if formation_name not in self.formation_map:
                await self.send_text("不存在这样的抽牌方法")
                return False, "参数错误"
    
            # 获取牌阵配置
            formation = self.formation_map[formation_name] # 根据确定好的抽牌方式名称获取具体牌阵的字典
            cards_num = formation["cards_num"] # 该抽牌方式要抽几张牌
            is_cut = formation["is_cut"] # 该抽牌方式要不要切牌
            represent_list = formation["represent"] # 该抽牌方式所包含的预言方向内容
    
            # 获取有效卡牌范围
            valid_ids = self._get_card_range(card_type)
            if not valid_ids:
                await self.send_text("当前牌堆不对")
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
                    await self.send_image(b64_data)
                
                # 轮询构建文本
                desc = card_info['reverseDescription'] if is_reverse else card_info['description']
                result_text += (
                    f"\n{pos_name} - {'逆位' if is_reverse else '正位'} {card_data['name']}\n"
                    f"{desc[:100]}...\n"
                )
                await asyncio.sleep(0.3)  # 防止消息频率限制
                
            # 发送最终文本
            await asyncio.sleep(1.2) # 权宜之计，给最后一张图片1.2s的发送起跑时间，无可奈何的办法

            result_status, result_message = await generator_api.rewrite_reply(
                chat_stream=self.chat_stream,
                reply_data={ 
                "raw_reply": result_text,
                "reason": "抽出了塔罗牌结果，请根据其内容为用户进行解牌",
            }) # 让你的麦麦用自己的语言风格阐释结果

            if result_status:
                for reply_seg in result_message:
                    data = reply_seg[1]
                    await self.send_text(data)
                    await asyncio.sleep(0.3)

            return True, "占卜成功，已发送结果"
            
        except Exception as e:
            logger.error(f"{self.log_prefix} 执行失败: {str(e)}")
            await self.send_text(f"占卜失败: {str(e)}")
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
            logger.error(f"{self.log_prefix} 图片下载失败: {str(e)}")

    def _load_config(self) -> Dict[str, Any]:
        """从同级目录的config.toml文件直接加载配置"""
        try:
            # 获取当前文件所在目录
            script_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(script_dir, "config.toml")
            
            # 读取并解析TOML配置文件
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = toml.load(f)
            
            # 构建配置字典，使用get方法安全访问嵌套值
            config = {
                "permissions": {
                    "admin_users": config_data.get("permissions", {}).get("admin_users", [])
                }
            }
            return config
        except Exception as e:
            logger.error(f"{self.log_prefix} 加载配置失败: {e}")
            raise

class TarotsCommand(BaseCommand, TarotsAction):
    command_name = "tarots_cache"
    command_description = "塔罗牌命令，目前仅做缓存"
    command_pattern = r"^/tarots\s+(?P<target_type>\w+)$"
    command_help = "使用方法: /tarots cache - 缓存所有牌面"
    command_examples = [
        "/tarots cache - 开始缓存全部牌面"
    ]
    enable_command = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 初始化 TarotsAction 的属性
        self.base_dir = Path(__file__).parent.absolute()
        self.cache_dir = self.base_dir / "tarots_cache"
        self.cache_dir.mkdir(exist_ok=True)
        self.card_map = {}
        self.formation_map = {}
        self._load_resources()

    async def execute(self) -> Tuple[bool, Optional[str]]:
        try:
            target_type = self.matched_groups.get("target_type")
            check_count=[str(i) for i in range(78)]
            sender = self.message.message_info.user_info
            
            if target_type == "cache":

                if not self._check_person_permission(sender.user_id):
                    await self.send_text("权限不足，你无权使用此命令")    
                    return False,"权限不足，无权使用此命令"
                
                # 添加进度提示
                await self.send_text("开始缓存全部牌面，请稍候...")
                success_count = 0
                
                for card in check_count:
                    try:
                        filename = f"{card}_norm.png"
                        cache_path = self.cache_dir / filename

                        if not cache_path.exists():
                            await self._download_image(card, cache_path)
                            success_count += 1

                        else:
                            success_count += 1

                    except Exception as e:
                        logger.warning(f"{self.log_prefix} 缓存卡牌 {card} 失败: {str(e)}")
                        continue 

                await self.send_text(f"缓存完成，成功缓存 {success_count}/{len(check_count)} 张牌面")

                return True,f"缓存完成，成功缓存 {success_count}/{len(check_count)} 张牌面"
            
            else:
                await self.send_text("没有这种参数，只能填cache哦")
                return False, "没有这种参数，只能填cache哦"

        except Exception as e:
            await self.send_text(f"{self.log_prefix} 一键缓存执行错误: {e}")
            logger.error(f"{self.log_prefix} 一键缓存执行错误: {e}")
            return False, f"执行失败: {str(e)}"
        
    def _check_person_permission(self, user_id: str) -> bool:
        """权限检查逻辑"""
        config = self._load_config()
        admin_users = config["permissions"].get("admin_users", [])
        if not admin_users:
            logger.warning(f"{self.log_prefix} 未配置管理员用户列表")
            return False
        return user_id in admin_users

@register_plugin
class TarotsPlugin(BasePlugin):
    """塔罗牌插件
    - 支持多种牌阵抽取
    - 支持区分大小阿卡纳抽取
    - 会在本地逐步缓存牌面图片
    - 拥有一键缓存所有牌面的指令
    - 完整的错误处理
    - 日志记录和监控
    """

    # 插件基本信息
    plugin_name = "tarots_plugin"
    plugin_description = "塔罗牌插件"
    plugin_version = "0.7.0"
    plugin_author = "A肆零西烛"
    enable_plugin = True
    config_file_name = "config.toml"

# 配置节描述
    config_section_descriptions = {
        "plugin": "插件基本配置",
        "components": "组件启用控制",
        "permissions": "管理者用户配置（支持热重载）",
        "logging": "日志记录配置",
    }

    # 配置Schema定义
    config_schema = {
        "plugin": {
            "name": ConfigField(type=str, default="tarots_plugin", description="插件名称", required=True),
            "version": ConfigField(type=str, default="0.7.0", description="插件版本号"),
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
            "description": ConfigField(
                type=str, default="塔罗牌插件", description="插件描述", required=True
            ),
        },
        "components": {
            "enable_tarots": ConfigField(type=bool, default=True, description="是否启用塔罗牌插件抽牌功能"),
            "enable_tarots_cache": ConfigField(type=bool, default=True, description="是否启用塔罗牌缓存指令")
        },
        "permissions": {
            "admin_users": ConfigField(type=List, default=["123456789"], description="请写入被许可用户的QQ号，记得用英文单引号包裹并使用逗号分隔。这个配置会决定谁被允许使用塔罗牌缓存指令，注意，这个选项支持热重载（你可以不重启麦麦，改动会即刻生效）"),
        },
        "logging": {
            "level": ConfigField(
                type=str, default="INFO", description="日志级别", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
            ),
            "prefix": ConfigField(type=str, default="[Tarots]", description="日志前缀"),
        },
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """返回插件包含的组件列表"""

        components = []

        if self.get_config("components.enable_tarots", True):
            components.append((TarotsAction.get_action_info(), TarotsAction))

        if self.get_config("components.enable_tarots_cache", True):
            components.append((TarotsCommand.get_command_info(), TarotsCommand))

        return components

