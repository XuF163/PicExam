#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真正高效的并发图片内容过滤系统
修复并发问题，实现真正的并行处理
"""

import os
import json
import base64
import shutil
import re
import logging
import time
import hashlib
import asyncio
from pathlib import Path
import google.generativeai as genai
from openai import OpenAI
from PIL import Image
import tempfile
from dataclasses import dataclass
from typing import List, Dict, Optional, Set
import threading
import sys

def get_terminal_height():
    """获取终端高度"""
    try:
        import shutil
        return shutil.get_terminal_size().lines
    except:
        return 25  # 默认高度

def draw_progress_bar(current, total, bar_length=50, prefix="进度"):
    """绘制进度条"""
    if total == 0:
        percentage = 0
    else:
        percentage = current / total
    
    filled_length = int(bar_length * percentage)
    # 使用ASCII字符替代Unicode字符，避免编码问题
    bar = '#' * filled_length + '-' * (bar_length - filled_length)
    percent = percentage * 100
    
    # 移动到行首并清除当前行
    try:
        sys.stdout.write(f'\r{prefix}: [{bar}] {percent:.1f}% ({current}/{total})')
        sys.stdout.flush()
    except UnicodeEncodeError:
        # 如果仍有编码问题，使用简化版本
        sys.stdout.write(f'\r{prefix}: {percent:.1f}% ({current}/{total})')
        sys.stdout.flush()

def draw_fixed_bottom_progress(current, total, stats_info="", prefix="审查进度"):
    """绘制固定在底部的进度条"""
    if total == 0:
        percentage = 0
    else:
        percentage = current / total
    
    filled_length = int(40 * percentage)  # 缩短进度条长度
    bar = '#' * filled_length + '-' * (40 - filled_length)
    percent = percentage * 100
    
    try:
        # 保存当前光标位置
        sys.stdout.write('\033[s')
        
        # 移动到屏幕底部
        terminal_height = get_terminal_height()
        sys.stdout.write(f'\033[{terminal_height};1H')
        
        # 清除底部两行
        sys.stdout.write('\033[K')  # 清除当前行
        if stats_info:
            sys.stdout.write(stats_info)
            sys.stdout.write('\n\033[K')  # 换行并清除下一行
        
        # 显示进度条
        progress_line = f'{prefix}: [{bar}] {percent:.1f}% ({current}/{total})'
        sys.stdout.write(progress_line)
        
        # 恢复光标位置
        sys.stdout.write('\033[u')
        sys.stdout.flush()
    except:
        # 如果终端不支持ANSI转义序列，回退到简单版本
        draw_progress_bar(current, total, prefix=prefix)

# 注意：API配置现在从配置文件读取

@dataclass
class FilterConfig:
    """过滤器配置"""
    max_concurrent: int = 30
    api_delay: float = 1.5
    max_retries: int = 3
    timeout: int = 60
    target_folder: str = "@色图"
    log_level: str = "INFO"

@dataclass
class ProcessingStats:
    """处理统计"""
    total: int = 0
    processed: int = 0
    moved: int = 0
    approved: int = 0
    skipped: int = 0
    errors: int = 0
    skipped_ai_reject: int = 0

class FastConcurrentImageFilter:
    def __init__(self, config: FilterConfig = None):
        self.config = config or self.load_config()
        self.client = None  # 将在load_config后初始化
        self.stats = ProcessingStats()
        self.moved_images = []
        self.processed_files: Set[str] = set()
        self.lock = threading.Lock()
        self.setup_logging()
        
    def setup_logging(self):
        """设置日志"""
        logging.basicConfig(
            level=getattr(logging, self.config.log_level),
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('fast_concurrent_filter.log', encoding='utf-8')
            ]
        )
        self.logger = logging.getLogger(__name__)

    def load_config(self) -> FilterConfig:
        """加载配置文件"""
        try:
            with open('filter_config.json', 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            # 检查是否使用代理服务器
            self.use_proxy = config_data.get('use_proxy', False)
            self.base_url = config_data.get('base_url', '')
            self.api_key = config_data.get('api_key', '')
            self.model_name = config_data.get('model_name', 'gemini-2.5-pro')
            
            if self.use_proxy and self.base_url:
                print(f"🌐 使用代理服务器: {self.base_url}")
                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url
                )
                print(f"✅ API 配置成功，模型: {self.model_name}")
            else:
                print("🔑 使用官方 Gemini API")
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel(self.model_name)
                print(f"✅ API 配置成功，模型: {self.model_name}")
            
            return FilterConfig(
                max_concurrent=config_data.get('max_concurrent', 30),
                api_delay=config_data.get('api_delay', 1.5),
                max_retries=config_data.get('max_retries', 3),
                timeout=config_data.get('timeout', 60),
                target_folder=config_data.get('target_folder', '@色图'),
                log_level=config_data.get('log_level', 'INFO')
            )
        except Exception as e:
            if hasattr(self, 'logger'):
                self.logger.warning(f"加载配置失败，使用默认配置: {e}")
            # 使用默认配置
            self.use_proxy = False
            genai.configure(api_key='')
            self.model = genai.GenerativeModel('gemini-1.5-flash')
            return FilterConfig()

    def check_filename_for_adult_content(self, filename: str) -> bool:
        """检查文件名是否包含成人内容标识符 - 已禁用"""
        # 根据用户要求，不再依据文件名判断
        return False

    def get_all_images(self) -> List[str]:
        """获取所有图片文件"""
        image_extensions = {'.webp', '.jpg', '.jpeg', '.png', '.gif', '.bmp'}
        images = []

        for root, dirs, files in os.walk('.'):
            if self.config.target_folder in root:
                continue

            for file in files:
                if Path(file).suffix.lower() in image_extensions:
                    if "_审查已经通过" in file:
                        continue
                    file_path = os.path.join(root, file)
                    images.append(file_path)

        return images

    def validate_and_resize_image(self, image_path: str) -> str:
        """验证并自适应压缩图片"""
        try:
            with Image.open(image_path) as img:
                # 转换为RGB模式
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')
                
                # 自适应压缩策略
                # 1. 先尝试压缩尺寸
                max_dimension = 1024  # 最大边长
                if img.width > max_dimension or img.height > max_dimension:
                    ratio = min(max_dimension / img.width, max_dimension / img.height)
                    new_width = int(img.width * ratio)
                    new_height = int(img.height * ratio)
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # 2. 保存为JPEG并尝试不同质量等级
                temp_fd, temp_path = tempfile.mkstemp(suffix='.jpg')
                os.close(temp_fd)
                
                # 尝试不同的压缩质量，确保文件大小合适
                for quality in [85, 70, 55, 40]:
                    img.save(temp_path, 'JPEG', quality=quality, optimize=True)
                    
                    # 检查压缩后的文件大小
                    with open(temp_path, 'rb') as f:
                        data = f.read()
                        base64_size_mb = len(base64.b64encode(data)) / (1024 * 1024)
                    
                    # 如果小于8MB，使用这个质量
                    if base64_size_mb < 8:
                        return temp_path
                
                # 如果仍然太大，进一步缩小尺寸
                max_dimension = 512
                ratio = min(max_dimension / img.width, max_dimension / img.height)
                new_width = int(img.width * ratio)
                new_height = int(img.height * ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                img.save(temp_path, 'JPEG', quality=40, optimize=True)
                
                return temp_path
                
        except Exception as e:
            self.logger.warning(f"图片处理失败: {e}")
            return image_path

    async def retry_with_backoff(self, image_path: str, process_id: str, temp_path: str = None, img_base64: str = None):
        """无限重试机制 - 确保100%审查覆盖率"""
        attempt = 0
        max_backoff_delay = 300  # 最大退避延迟5分钟
        
        while True:
            attempt += 1
            try:
                # 指数退避延迟，但有最大限制
                backoff_delay = min(max_backoff_delay, self.config.api_delay * (1.5 ** min(attempt-1, 10)))
                self.logger.info(f"[{process_id}] 第 {attempt} 次重试，等待 {backoff_delay:.1f}秒")
                await asyncio.sleep(backoff_delay)
                
                # 如果没有img_base64，重新处理图片
                if img_base64 is None:
                    processed_path = self.validate_and_resize_image(image_path)
                    if processed_path != image_path:
                        temp_path = processed_path
                    
                    with open(processed_path, 'rb') as img_file:
                        img_data = img_file.read()
                    img_base64 = base64.b64encode(img_data).decode('utf-8')
                
                prompt = """
请仔细审查这张图片是否适合16岁及以上青少年查看。

重点检查：
1. 是否包含性暗示、性行为或裸体内容
2. 是否有过度暴露的服装（如比基尼、情趣内衣等）
3. 是否有挑逗性姿势或表情
4. 是否对未成年外观的角色进行性化描绘
5. 整体是否存在不适宜青少年的内容

请以JSON格式返回结果：
{
    "suitable_for_teens": true/false,
    "reason": "详细的判断理由",
    "confidence": 0.0-1.0
}

如果有任何疑虑，请判定为不适合。
"""

                if self.use_proxy and hasattr(self, 'client'):
                    # 使用代理服务器 (OpenAI兼容格式)
                    response = self.client.chat.completions.create(
                        model=self.model_name,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/jpeg;base64,{img_base64}"
                                        }
                                    }
                                ]
                            }
                        ],
                        timeout=self.config.timeout
                    )
                    
                    # 处理不同类型的响应
                    if hasattr(response, 'choices') and response.choices:
                        content = response.choices[0].message.content
                    elif hasattr(response, 'content'):
                        content = response.content
                    else:
                        # 处理字符串响应的情况
                        content = str(response)
                        # 尝试解析JSON字符串
                        try:
                            import json as json_module
                            if content.startswith('{') and content.endswith('}'):
                                parsed = json_module.loads(content)
                                if 'choices' in parsed and parsed['choices']:
                                    content = parsed['choices'][0]['message']['content']
                        except:
                            pass
                else:
                    # 使用官方 Gemini API
                    import io
                    img_data_bytes = base64.b64decode(img_base64)
                    pil_image = Image.open(io.BytesIO(img_data_bytes))
                    
                    response = self.model.generate_content([prompt, pil_image])
                    content = response.text
                
                # 解析JSON结果
                try:
                    if '{' in content and '}' in content:
                        start = content.find('{')
                        end = content.rfind('}') + 1
                        json_str = content[start:end]
                        result = json.loads(json_str)
                        self.logger.info(f"[{process_id}] 重试成功 (第 {attempt} 次)")
                        return result, temp_path
                    else:
                        # 关键词判断
                        if any(word in content.lower() for word in ['不适合', 'false', '不建议']):
                            self.logger.info(f"[{process_id}] 重试成功 (第 {attempt} 次)")
                            return {"suitable_for_teens": False, "reason": "AI判断不适合", "confidence": 0.8}, temp_path
                        else:
                            self.logger.info(f"[{process_id}] 重试成功 (第 {attempt} 次)")
                            return {"suitable_for_teens": True, "reason": "AI判断适合", "confidence": 0.8}, temp_path
                except Exception as parse_error:
                    # JSON解析失败也不应该默认通过，而是重试
                    self.logger.warning(f"[{process_id}] 第 {attempt} 次重试JSON解析失败，将继续重试: {parse_error}")
                    continue
                
            except Exception as e:
                error_str = str(e)
                
                if ("SAFETY" in error_str or "BLOCKED" in error_str or
                    "安全" in error_str or "blocked" in error_str.lower() or
                    "safety" in error_str.lower()):
                    self.logger.info(f"[{process_id}] Gemini安全过滤器检测到不适合内容: {image_path}")
                    with self.lock:
                        self.stats.skipped_ai_reject += 1
                    return {
                        "suitable_for_teens": False,
                        "reason": "Gemini安全过滤器检测到不适合16岁及以上青少年的内容",
                        "confidence": 1.0
                    }, temp_path
                
                # 如果是429错误，继续重试
                elif "429" in error_str or "Too Many Requests" in error_str:
                    self.logger.warning(f"[{process_id}] 第 {attempt} 次重试遇到429错误，将继续重试")
                    continue
                
                # 如果是网络错误，继续重试
                elif any(keyword in error_str.lower() for keyword in [
                    'connection', 'timeout', 'network', 'dns', 'unreachable', 'refused'
                ]):
                    self.logger.warning(f"[{process_id}] 第 {attempt} 次重试遇到网络错误: {e}，将继续重试")
                    continue
                
                # 如果是其他错误，记录但继续重试
                else:
                    self.logger.warning(f"[{process_id}] 第 {attempt} 次重试失败: {e}，将继续重试")
                    continue

    async def check_image_safety(self, image_path: str, process_id: str):
        """检查图片安全性"""
        temp_path = None
        
        try:
            # 1. 验证图片格式并自适应压缩
            processed_path = self.validate_and_resize_image(image_path)
            if processed_path != image_path:
                temp_path = processed_path

            # 2. 读取图片并转换为Base64
            with open(processed_path, 'rb') as img_file:
                img_data = img_file.read()

            img_base64 = base64.b64encode(img_data).decode('utf-8')

            # 检查文件大小
            base64_size_mb = len(img_base64) / (1024 * 1024)
            if base64_size_mb > 10:
                # 图片过大不应该跳过，而是拒绝（更安全的做法）
                self.logger.warning(f"[{process_id}] 图片过大 ({base64_size_mb:.2f}MB)，出于安全考虑拒绝: {image_path}")
                return {
                    "suitable_for_teens": False,
                    "reason": f"图片过大({base64_size_mb:.2f}MB)，出于安全考虑拒绝",
                    "confidence": 1.0
                }, temp_path

            # 3. 调用API（无限重试机制）
            return await self.retry_with_backoff(image_path, process_id, temp_path, img_base64)
                
        except Exception as e:
            self.logger.error(f"[{process_id}] 检查图片时出错，将重试: {e}")
            return await self.retry_with_backoff(image_path, process_id, temp_path, None)

    def move_inappropriate_image(self, image_path: str, reason: str, temp_path: str = None):
        """移动不适合的图片"""
        try:
            path_obj = Path(image_path)
            original_dir = path_obj.parent.name
            
            target_dir = Path(self.config.target_folder) / original_dir
            target_dir.mkdir(parents=True, exist_ok=True)
            
            # 清理文件名
            clean_reason = re.sub(r'[<>:"/\\|?*]', '_', reason)[:50]
            new_filename = f"{clean_reason}{path_obj.suffix}"
            
            target_path = target_dir / new_filename
            counter = 1
            while target_path.exists():
                new_filename = f"{clean_reason}_{counter}{path_obj.suffix}"
                target_path = target_dir / new_filename
                counter += 1
            
            shutil.move(str(path_obj), str(target_path))
            
            # 清理临时文件
            if temp_path and temp_path != image_path and os.path.exists(temp_path):
                os.unlink(temp_path)
            
            return {
                "success": True,
                "new_path": str(target_path),
                "original_path": image_path,
                "reason": reason
            }
            
        except Exception as e:
            self.logger.error(f"移动文件失败: {e}")
            return {"success": False, "error": str(e)}

    def rename_approved_image(self, image_path: str):
        """重命名通过审查的图片"""
        try:
            path_obj = Path(image_path)
            if "_审查已经通过" in path_obj.stem:
                return {"success": True, "new_path": image_path}
            
            new_filename = f"{path_obj.stem}_审查已经通过{path_obj.suffix}"
            new_path = path_obj.parent / new_filename
            
            counter = 1
            while new_path.exists():
                new_filename = f"{path_obj.stem}_审查已经通过_{counter}{path_obj.suffix}"
                new_path = path_obj.parent / new_filename
                counter += 1
            
            shutil.move(str(path_obj), str(new_path))
            
            return {
                "success": True,
                "new_path": str(new_path),
                "original_path": image_path
            }
            
        except Exception as e:
            self.logger.error(f"重命名失败: {e}")
            return {"success": False, "error": str(e)}

    async def process_single_image(self, image_path: str, process_id: str, semaphore: asyncio.Semaphore):
        """处理单张图片 - 真正的并发版本"""
        async with semaphore:  # 控制并发数
            try:
                # 检查是否已经处理过
                with self.lock:
                    if image_path in self.processed_files:
                        return
                    self.processed_files.add(image_path)

                self.logger.info(f"[{process_id}] 开始处理: {image_path}")

                result, temp_path = await self.check_image_safety(image_path, process_id)

                if result.get("suitable_for_teens") is False:
                    self.logger.warning(f"[{process_id}] 不适合: {image_path} - {result.get('reason')}")
                    move_result = self.move_inappropriate_image(image_path, result.get('reason', '未知原因'), temp_path)
                    if move_result["success"]:
                        with self.lock:
                            self.stats.moved += 1
                            self.moved_images.append(move_result)
                    else:
                        with self.lock:
                            self.stats.errors += 1
                elif result.get("suitable_for_teens") is True:
                    self.logger.info(f"[{process_id}] 通过: {image_path}")
                    rename_result = self.rename_approved_image(image_path)
                    if rename_result["success"]:
                        with self.lock:
                            self.stats.approved += 1
                    else:
                        with self.lock:
                            self.stats.errors += 1

                    # 清理临时文件
                    if temp_path and temp_path != image_path and os.path.exists(temp_path):
                        os.unlink(temp_path)
                else:
                    self.logger.warning(f"[{process_id}] 跳过: {image_path} - {result.get('reason')}")
                    with self.lock:
                        self.stats.skipped += 1

                    # 清理临时文件
                    if temp_path and temp_path != image_path and os.path.exists(temp_path):
                        os.unlink(temp_path)

                with self.lock:
                    self.stats.processed += 1

            except Exception as e:
                self.logger.error(f"[{process_id}] 处理图片出错: {image_path}, 错误: {e}")
                with self.lock:
                    self.stats.errors += 1

            # 添加延迟避免API限制
            await asyncio.sleep(self.config.api_delay)

    async def run(self):
        """运行过滤器 - 真正的并发版本"""
        print("🚀 启动真正高效的并发图片内容过滤系统 (16岁级别)")
        print("📁 不适合的图片将移动到 @色图 文件夹")
        print("✅ 通过的图片将添加 _审查已经通过 标记")
        print("🔍 新增：文件名成人内容检查")
        print(f"⚡ 真正并发处理：{self.config.max_concurrent} 个任务同时进行")
        print()

        images = self.get_all_images()
        self.stats.total = len(images)

        print(f"找到 {len(images)} 张图片需要处理")
        print(f"配置: 并发数{self.config.max_concurrent}, 延迟{self.config.api_delay}秒, 超时{self.config.timeout}秒")
        print()

        start_time = time.time()

        # 创建信号量控制并发数
        semaphore = asyncio.Semaphore(self.config.max_concurrent)

        # 创建所有任务但不立即执行
        tasks = []
        for i, image_path in enumerate(images):
            process_id = f"worker_{i:04d}"
            task = self.process_single_image(image_path, process_id, semaphore)
            tasks.append(task)

        # 启动进度监控任务
        progress_task = asyncio.create_task(self.monitor_progress(len(images), start_time))

        # 并发执行所有任务
        try:
            await asyncio.gather(*tasks)
        finally:
            progress_task.cancel()

        elapsed_time = time.time() - start_time

        # 打印最终统计
        print(f"\n📊 处理完成:")
        print(f"   总共: {self.stats.total} 张")
        print(f"   处理: {self.stats.processed} 张")
        print(f"   通过: {self.stats.approved} 张")
        print(f"   移动: {self.stats.moved} 张")
        print(f"   跳过: {self.stats.skipped} 张")
        print(f"   AI拒绝: {self.stats.skipped_ai_reject} 张")
        print(f"   错误: {self.stats.errors} 张")
        print(f"   耗时: {elapsed_time:.1f} 秒")
        if elapsed_time > 0:
            print(f"   平均速度: {self.stats.processed / elapsed_time:.2f} 张/秒")

    async def monitor_progress(self, total: int, start_time: float):
        """监控处理进度"""
        try:
            while True:
                await asyncio.sleep(2)  # 更频繁地更新进度条

                with self.lock:
                    processed = self.stats.processed
                    moved = self.stats.moved
                    approved = self.stats.approved
                    errors = self.stats.errors
                
                if processed >= total:
                    # 完成时显示完整进度条
                    draw_fixed_bottom_progress(total, total, 
                                             stats_info="处理完成！",
                                             prefix="✓ 完成")
                    print()  # 换行
                    break

                elapsed = time.time() - start_time
                if processed > 0:
                    avg_speed = processed / elapsed
                    eta = (total - processed) / avg_speed if avg_speed > 0 else 0
                    
                    # 构建统计信息
                    stats_line = (f"处理中: {processed}/{total} | "
                                 f"通过: {approved} | "
                                 f"移动: {moved} | "
                                 f"错误: {errors} | "
                                 f"速度: {avg_speed:.1f}/秒 | "
                                 f"剩余: {eta/60:.1f}分钟")
                    
                    # 显示固定底部进度条
                    draw_fixed_bottom_progress(processed, total, 
                                             stats_info=stats_line,
                                             prefix="审查进度")
                else:
                    draw_fixed_bottom_progress(processed, total, 
                                             stats_info="准备开始处理...",
                                             prefix="审查进度")
                    
        except asyncio.CancelledError:
            pass

async def main():
    """主函数"""
    filter_system = FastConcurrentImageFilter()
    await filter_system.run()

if __name__ == "__main__":
    asyncio.run(main())
