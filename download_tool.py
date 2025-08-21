import aiohttp
import asyncio
import os
from pathlib import Path
from typing import Optional
from PIL import Image
import logging

logger = logging.getLogger("tarots_download_tool")

async def download_image(url: str, save_path: Path, proxy: Optional[str] = None, max_retries: int = 3, retry_delay: int = 2) -> bool:
    """
    下载图片到指定路径，支持重试和完整性校验。
    :param url: 图片直链
    :param save_path: 保存路径（Path对象）
    :param proxy: 可选，http代理
    :param max_retries: 最大重试次数
    :param retry_delay: 重试间隔（秒）
    :return: 下载并校验成功返回True，否则False
    """
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"[图片下载] 尝试 {attempt}/{max_retries} - {url}")
            async with aiohttp.ClientSession() as session:
                req_kwargs = {"timeout": 15}
                if proxy:
                    req_kwargs["proxy"] = proxy
                async with session.get(url, **req_kwargs) as resp:
                    if resp.status == 200:
                        save_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(save_path, "wb") as f:
                            f.write(await resp.read())
                        if validate_image_integrity(save_path):
                            logger.info(f"[图片下载] 成功并通过完整性检测 {save_path.name} (尝试 {attempt}次)")
                            return True
                        else:
                            logger.warning(f"[图片下载] 完整性检测失败，删除文件: {save_path}")
                            try:
                                save_path.unlink()
                            except Exception as delete_error:
                                logger.error(f"[图片下载] 删除损坏文件失败: {delete_error}")
                    else:
                        logger.warning(f"[图片下载] 异常状态码 {resp.status} - {url}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.warning(f"[图片下载] 尝试 {attempt}/{max_retries} 失败: {str(e)}")
        if attempt < max_retries:
            await asyncio.sleep(retry_delay ** attempt)
    logger.error(f"[图片下载] 终极失败 {url}，已达最大重试次数 {max_retries}")
    return False

def validate_image_integrity(file_path: Path) -> bool:
    """
    检查图片文件完整性
    :param file_path: 图片文件路径
    :return: 完整返回True，否则False
    """
    try:
        if not file_path.exists() or file_path.stat().st_size == 0:
            return False
        try:
            with Image.open(file_path) as img:
                if img.size[0] <= 0 or img.size[1] <= 0:
                    return False
                img.load()
                return True
        except Exception:
            return False
    except Exception:
        return False
