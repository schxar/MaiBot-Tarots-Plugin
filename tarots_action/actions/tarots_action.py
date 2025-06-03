from src.chat.focus_chat.planners.actions.plugin_action import PluginAction, register_action
from src.common.logger_manager import get_logger
from typing import Tuple, Dict, Optional
from pathlib import Path
import json
import random
import asyncio
import aiohttp
import base64

logger = get_logger("tarots_action")

@register_action
class TarotsAction(PluginAction):
    action_name = "tarots"
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
        "当消息包含'抽塔罗牌''塔罗牌占卜'等关键词，且明确表达了要求你帮忙抽牌的意向时必须调用",
        "需要明确指定抽牌范围和抽牌类型，未明确指定抽牌范围则默认为全部，未明确指定抽牌类型则默认为单张"
    ]
    default = True  # 设置为默认启用
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

    async def process(self) -> Tuple[bool, str]:
        """实现基类要求的入口方法"""
        try:
            logger.info(f"{self.log_prefix} 开始执行塔罗占卜")
            
            # 参数解析
            card_type = self.action_data.get("card_type", "全部") 
            formation_name = self.action_data.get("formation", "单张")
            
            # 参数校验
            if card_type not in ["全部", "大阿卡纳", "小阿卡纳"]:
                await self.send_message("text", "不存在这样的抽牌范围")
                return False, "参数错误"
                
            if formation_name not in self.formation_map:
                await self.send_message("text", "不存在这样的抽牌方法")
                return False, "参数错误"
    
            # 获取牌阵配置
            formation = self.formation_map[formation_name] # 根据确定好的抽牌方式名称获取具体牌阵的字典
            cards_num = formation["cards_num"] # 该抽牌方式要抽几张牌
            is_cut = formation["is_cut"] # 该抽牌方式要不要切牌
            represent_list = formation["represent"] # 该抽牌方式所包含的预言方向内容
    
            # 获取有效卡牌范围
            valid_ids = self._get_card_range(card_type)
            if not valid_ids:
                await self.send_message("text", "当前牌堆不对")
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
                    await self.send_message("image", b64_data)
                
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
            await self.send_message("text", f"占卜失败: {str(e)}")
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
            filename = f"{card_id}_{'rev' if is_reverse else 'norm'}.png"
            cache_path = self.cache_dir / filename
            
            if not cache_path.exists():
                await self._download_image(card_id, is_reverse, cache_path)
            
            with open(cache_path, "rb") as f:
                return f.read()
        except Exception as e:
            logger.warning(f"{self.log_prefix} 获取图片失败: {str(e)}")
            return None
        
    async def _download_image(self, card_id: str, is_reverse: bool, save_path: Path):
        """图片本地缓存"""
        MAX_RETRIES = 3
        RETRY_DELAY = 2  # 初始重试间隔（秒）

        try:
            # 获取卡牌数据
            card_info = self.card_map[card_id]["info"]
            img_path = card_info['imgUrl']
            
            # 构建下载URL
            base_url = "https://raw.githubusercontent.com/FloatTech/zbpdata/main/Tarot/"
            folder = "Reverse/" if is_reverse else ""
            full_url = f"{base_url}{folder}{img_path}"

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
                                
                                logger.success(f"[图片下载] 成功 {save_path.name} (尝试 {attempt}次)")
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