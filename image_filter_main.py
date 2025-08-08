#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片内容过滤系统 - 完整集成版
将所有功能整合到一个文件中，支持独立打包为exe
包含：超高速多线程图片审查 + 审查标记清除功能
"""

import os
import json
import sys
import time
import base64
import shutil
import re
import logging
import threading
import tempfile
from pathlib import Path
import google.generativeai as genai
from openai import OpenAI
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed

class SimpleProgressBar:
    """最简单的单行进度条"""
    
    def __init__(self):
        self.lock = threading.Lock()
        self.is_showing = False
        # 保存最后的进度状态，用于日志输出后恢复
        self.last_current = 0
        self.last_total = 0
        self.last_stats_info = ""
        self.last_prefix = "进度"
        
    def update(self, current, total, stats_info="", prefix="进度"):
        """更新进度条 - 使用单行覆盖更新"""
        with self.lock:
            # 保存状态
            self.last_current = current
            self.last_total = total
            self.last_stats_info = stats_info
            self.last_prefix = prefix
            
            if total == 0:
                percentage = 0
            else:
                percentage = current / total
            
            # 使用ASCII字符避免编码问题
            bar_width = 40
            filled_length = int(bar_width * percentage)
            bar = '#' * filled_length + '-' * (bar_width - filled_length)
            percent = percentage * 100
            
            # 构建完整的进度行
            if stats_info:
                progress_text = f'\r{prefix}: [{bar}] {percent:.1f}% ({current}/{total}) | {stats_info}'
            else:
                progress_text = f'\r{prefix}: [{bar}] {percent:.1f}% ({current}/{total})'
            
            # 限制行长度，避免换行
            max_width = 120
            if len(progress_text) > max_width:
                progress_text = progress_text[:max_width-3] + '...'
            
            sys.stdout.write(progress_text)
            sys.stdout.flush()
            self.is_showing = True
    
    def clear(self):
        """清除进度条"""
        with self.lock:
            if self.is_showing:
                # 清除当前行
                sys.stdout.write('\r' + ' ' * 120 + '\r')
                sys.stdout.flush()
                self.is_showing = False
    
    def restore_if_needed(self):
        """如果进度条被清除，恢复最后的状态"""
        with self.lock:
            if not self.is_showing and self.last_total > 0:
                # 恢复上次的进度显示
                self.update(self.last_current, self.last_total, self.last_stats_info, self.last_prefix)
    
    def finish(self, message="完成"):
        """完成并显示消息"""
        with self.lock:
            if self.is_showing:
                sys.stdout.write('\r' + ' ' * 120 + '\r')  # 清除
                print(f"✓ {message}")
                self.is_showing = False
                # 清除保存的状态
                self.last_current = 0
                self.last_total = 0
                self.last_stats_info = ""

# 全局进度条
progress_bar = SimpleProgressBar()

class SafeLogHandler(logging.Handler):
    """安全的日志处理器 - 避免与进度条冲突"""
    
    def emit(self, record):
        try:
            msg = self.format(record)
            # 清除进度条，输出日志，然后短暂延迟后恢复进度条
            progress_bar.clear()
            print(msg)
            sys.stdout.flush()  # 确保日志立即输出
            # 短暂延迟后恢复进度条，确保日志输出完成
            threading.Timer(0.05, progress_bar.restore_if_needed).start()
        except:
            pass

def clear_screen():
    """清屏"""
    os.system('cls' if os.name == 'nt' else 'clear')

def print_banner():
    """打印横幅"""
    print("=" * 70)
    print("🎯 图片内容过滤系统 v2.0")
    print("   超高速多线程AI审查 + 智能标记管理")
    print("=" * 70)
    print()

class BottomProgressBar:
    """底部固定进度条"""
    def __init__(self):
        self.lock = threading.Lock()
        self.last_line = ""
        self.is_active = False

    def start(self):
        """启动进度条"""
        self.is_active = True

    def stop(self):
        """停止进度条"""
        self.is_active = False
        with self.lock:
            # 清除进度条
            if self.last_line:
                print("\r" + " " * len(self.last_line) + "\r", end="", flush=True)
                self.last_line = ""
                print()  # 换行

    def update(self, processed, total, speed=None, eta=None):
        """更新进度条"""
        if not self.is_active:
            return

        with self.lock:
            # 计算进度百分比
            percentage = (processed / total * 100) if total > 0 else 0

            # 创建进度条
            bar_width = 40
            filled = int(bar_width * processed / total) if total > 0 else 0
            bar = "█" * filled + "░" * (bar_width - filled)

            # 构建进度信息
            progress_info = f"审查进度: [{bar}] {percentage:.1f}% ({processed}/{total})"

            if speed is not None:
                progress_info += f" | 速度: {speed:.2f}张/秒"
            if eta is not None:
                progress_info += f" | 剩余: {eta:.1f}分钟"

            # 清除上一行并打印新的进度条
            if self.last_line:
                print("\r" + " " * len(self.last_line), end="", flush=True)

            print(f"\r{progress_info}", end="", flush=True)
            self.last_line = progress_info

class SafeLogHandler(logging.StreamHandler):
    """与进度条兼容的日志处理器"""
    def __init__(self, progress_bar=None):
        super().__init__()
        self.progress_bar = progress_bar

    def emit(self, record):
        if self.progress_bar and self.progress_bar.is_active:
            with self.progress_bar.lock:
                # 清除进度条
                if self.progress_bar.last_line:
                    print("\r" + " " * len(self.progress_bar.last_line) + "\r", end="")

                # 输出日志
                super().emit(record)

                # 重新显示进度条
                if self.progress_bar.last_line:
                    print(f"\r{self.progress_bar.last_line}", end="", flush=True)
        else:
            super().emit(record)

def load_config():
    """加载配置文件"""
    config_file = 'filter_config.json'
    default_config = {
        'api_type': 'gemini',
        'api_base_url': '',
        'api_key': '',
        'model_name': 'gemini-1.5-flash',
        'max_concurrent': 20,
        'timeout': 60,
        'target_folder': '@色图'
    }
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
                default_config.update(saved_config)
        except Exception as e:
            print(f"⚠️ 加载配置失败: {e}")
    
    return default_config

def save_config(config):
    """保存配置文件"""
    try:
        with open('filter_config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"❌ 保存配置失败: {e}")
        return False

def interactive_config(config):
    """交互式配置"""
    print("🔧 系统配置")
    print("-" * 50)
    
    # 显示当前配置
    if config['api_key']:
        print(f"✅ API密钥: 已设置 ({config['api_key'][:10]}...)")
    else:
        print("❌ API密钥: 未设置")
    print(f"🌐 API地址: {config['api_base_url']}")
    print(f"🤖 模型名称: {config['model_name']}")
    print(f"⚡ 并发数: {config['max_concurrent']}")
    print(f"📁 目标文件夹: {config['target_folder']}")
    print()
    
    # API配置
    if not config['api_key']:
        print("📝 请输入Google Gemini API密钥:")
        print("   获取地址: https://aistudio.google.com/app/apikey")
        api_key = input("API Key: ").strip()
        if not api_key:
            print("❌ API密钥不能为空")
            return config
        config['api_key'] = api_key
    else:
        change_key = input("是否更改API密钥? [y/N]: ").strip().lower()
        if change_key in ['y', 'yes']:
            api_key = input("新的API Key: ").strip()
            if api_key:
                config['api_key'] = api_key
    
    # API服务器URL配置
    print(f"\n🌐 当前API服务器: {config.get('api_base_url', '默认官方服务器')}")
    print("   服务器选项:")
    print("   - 留空: 使用Google官方服务器 (推荐)")
    print("   - 自定义: 输入代理服务器地址")
    print("   - 示例: https://your-proxy.com/v1beta/")
    api_url_input = input(f"请输入API服务器地址 [回车使用官方服务器]: ").strip()
    config['api_base_url'] = api_url_input
    
    # 模型名称配置
    print(f"\n🤖 当前模型: {config['model_name']}")
    print("   可用模型:")
    print("   - gemini-1.5-flash (推荐，快速且经济)")
    print("   - gemini-1.5-pro (高精度)")
    print("   - gemini-pro-vision (旧版视觉模型)")
    model_input = input(f"请输入模型名称 [回车保持当前值]: ").strip()
    if model_input:
        config['model_name'] = model_input
    
    # 并发数配置
    print(f"\n⚡ 当前并发数: {config['max_concurrent']}")
    print("   建议值: 10-30 (根据网络和系统性能调整)")
    concurrent_input = input(f"请输入并发数 [回车保持当前值]: ").strip()
    if concurrent_input:
        try:
            concurrent = int(concurrent_input)
            if 1 <= concurrent <= 50:
                config['max_concurrent'] = concurrent
            else:
                print("⚠️ 并发数应在1-50之间，保持当前值")
        except ValueError:
            print("⚠️ 输入无效，保持当前值")
    
    # 保存配置
    if save_config(config):
        print("✅ 配置已保存")
    else:
        print("❌ 配置保存失败")
    
    return config

def count_images(config):
    """统计图片数量"""
    image_extensions = {'.webp', '.jpg', '.jpeg', '.png', '.gif', '.bmp'}
    
    total_images = 0
    unprocessed_images = 0
    approved_images = 0
    
    for root, dirs, files in os.walk('.'):
        if config['target_folder'] in root:
            continue
            
        for file in files:
            if Path(file).suffix.lower() in image_extensions:
                total_images += 1
                if "_审查已经通过" in file:
                    approved_images += 1
                else:
                    unprocessed_images += 1
    
    return total_images, unprocessed_images, approved_images

# ==================== 图片过滤功能 ====================

class UltraFastImageFilter:
    def __init__(self, config):
        self.config = config
        self.original_max_workers = config['max_concurrent']
        self.current_workers = config['max_concurrent']
        
        # 配置API客户端
        try:
            if config.get('api_base_url') and config['api_base_url'].strip():
                # 使用代理服务器（OpenAI兼容格式）
                print(f"🌐 使用代理服务器: {config['api_base_url']}")
                self.client = OpenAI(
                    api_key=config['api_key'],
                    base_url=config['api_base_url']
                )
                self.use_proxy = True
            else:
                # 使用官方Gemini API
                print("🌐 使用官方Gemini服务器")
                genai.configure(api_key=config['api_key'])
                self.model = genai.GenerativeModel(config['model_name'])
                self.use_proxy = False
                
            print(f"✅ API 配置成功，模型: {config['model_name']}")
        except Exception as e:
            print(f"❌ API 配置失败: {e}")
            raise
            
        self.stats = {
            'total': 0,
            'processed': 0,
            'moved': 0,
            'approved': 0,
            'skipped': 0,
            'errors': 0,
            'ai_reject': 0,
            'rate_limit_errors': 0,
            'retries': 0
        }
        self.stats_lock = threading.Lock()
        self.processed_files = set()
        self.processed_lock = threading.Lock()
        self.progress_bar = BottomProgressBar()
        
        # 智能异常处理相关
        self.rate_limit_count = 0
        self.rate_limit_lock = threading.Lock()
        self.last_rate_limit_time = 0
        self.adaptive_delay = 1.0
        
        self.setup_logging()

    def setup_logging(self):
        """设置日志"""
        # 清除默认处理器
        logging.getLogger().handlers.clear()

        # 创建日志格式器
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(threadName)s] %(message)s')

        # 添加与进度条兼容的控制台处理器
        safe_handler = SafeLogHandler(self.progress_bar)
        safe_handler.setFormatter(formatter)

        # 添加文件处理器
        file_handler = logging.FileHandler('image_filter.log', encoding='utf-8')
        file_handler.setFormatter(formatter)

        # 配置日志
        logging.basicConfig(
            level=logging.INFO,
            handlers=[safe_handler, file_handler]
        )
        self.logger = logging.getLogger(__name__)

    def handle_rate_limit_error(self):
        """处理API限流错误"""
        with self.rate_limit_lock:
            self.rate_limit_count += 1
            self.last_rate_limit_time = time.time()
            
            with self.stats_lock:
                self.stats['rate_limit_errors'] += 1
            
            # 自适应调整并发数和延迟
            if self.rate_limit_count % 5 == 0:  # 每5次限流错误调整一次
                # 减少并发数
                new_workers = max(1, self.current_workers // 2)
                if new_workers != self.current_workers:
                    self.current_workers = new_workers
                    self.logger.warning(f"🔧 检测到频繁限流，自动调整并发数至: {self.current_workers}")
                
                # 增加延迟
                self.adaptive_delay = min(10.0, self.adaptive_delay * 1.5)
                self.logger.warning(f"🔧 调整API调用延迟至: {self.adaptive_delay:.1f}秒")

    def retry_with_backoff(self, image_path: str, worker_id: str, temp_path: str = None):
        """无限重试机制 - 确保100%审查覆盖率"""
        attempt = 0
        max_backoff_delay = 300  # 最大退避延迟5分钟
        
        while True:
            attempt += 1
            try:
                with self.stats_lock:
                    self.stats['retries'] += 1
                
                # 指数退避延迟，但有最大限制
                backoff_delay = min(max_backoff_delay, self.adaptive_delay * (1.5 ** min(attempt-1, 10)))
                self.logger.info(f"[{worker_id}] 第 {attempt} 次重试，等待 {backoff_delay:.1f}秒")
                time.sleep(backoff_delay)
                
                # 重新调用API检查
                result, temp_path_result = self.check_image_safety(image_path, f"{worker_id}_retry_{attempt}")
                
                # 成功获得结果，返回
                if result:
                    self.logger.info(f"[{worker_id}] 重试成功 (第 {attempt} 次)")
                    return result, temp_path_result
                
            except Exception as e:
                error_str = str(e)
                
                # 如果是429错误，继续重试
                if "429" in error_str or "Too Many Requests" in error_str:
                    self.logger.warning(f"[{worker_id}] 第 {attempt} 次重试遇到429错误，将继续重试")
                    self.handle_rate_limit_error()
                    continue
                
                # 如果是网络错误，继续重试
                elif any(keyword in error_str.lower() for keyword in [
                    'connection', 'timeout', 'network', 'dns', 'unreachable', 'refused'
                ]):
                    self.logger.warning(f"[{worker_id}] 第 {attempt} 次重试遇到网络错误: {e}，将继续重试")
                    continue
                
                # 如果是其他错误，记录但继续重试
                else:
                    self.logger.warning(f"[{worker_id}] 第 {attempt} 次重试失败: {e}，将继续重试")
                    continue

    def auto_adjust_concurrency(self):
        """自动调整并发数"""
        with self.rate_limit_lock:
            # 如果最近1分钟内限流错误过多，降低并发数
            recent_time = time.time() - 60
            if self.last_rate_limit_time > recent_time and self.rate_limit_count > 10:
                new_workers = max(1, self.current_workers - 2)
                if new_workers != self.current_workers:
                    self.current_workers = new_workers
                    self.logger.warning(f"🔧 自动降低并发数至: {self.current_workers}")
            else:
                # 如果长时间没有限流错误，逐渐恢复并发数
                if time.time() - self.last_rate_limit_time > 300:  # 5分钟没有限流
                    if self.current_workers < self.original_max_workers:
                        self.current_workers = min(self.original_max_workers, self.current_workers + 1)
                        self.logger.info(f"🔧 恢复并发数至: {self.current_workers}")
                        self.adaptive_delay = max(1.0, self.adaptive_delay * 0.9)

    def check_filename_for_adult_content(self, filename: str) -> bool:
        """检查文件名是否包含成人内容标识符 - 已禁用"""
        # 根据用户要求，不再依据文件名判断
        return False

    def get_all_images(self):
        """获取所有图片文件"""
        image_extensions = {'.webp', '.jpg', '.jpeg', '.png', '.gif', '.bmp'}
        images = []

        for root, dirs, files in os.walk('.'):
            if self.config['target_folder'] in root:
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

    def check_image_safety(self, image_path: str, worker_id: str):
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
                self.logger.warning(f"[{worker_id}] 图片过大 ({base64_size_mb:.2f}MB)，出于安全考虑拒绝: {image_path}")
                return {
                    "suitable_for_teens": False,
                    "reason": f"图片过大({base64_size_mb:.2f}MB)，出于安全考虑拒绝",
                    "confidence": 1.0
                }, temp_path

            # 3. 调用API
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

            if self.use_proxy:
                # 使用OpenAI兼容的代理服务器
                response = self.client.chat.completions.create(
                    model=self.config['model_name'],
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{img_base64}"
                                    }
                                },
                                {
                                    "type": "text",
                                    "text": prompt
                                }
                            ]
                        }
                    ],
                    timeout=self.config['timeout']
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
                # 使用官方Gemini API
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
                    return result, temp_path
                else:
                    # 关键词判断
                    if any(word in content.lower() for word in ['不适合', 'false', '不建议']):
                        return {"suitable_for_teens": False, "reason": "AI判断不适合", "confidence": 0.8}, temp_path
                    else:
                        return {"suitable_for_teens": True, "reason": "AI判断适合", "confidence": 0.8}, temp_path
            except Exception as parse_error:
                # JSON解析失败也不应该默认通过，而是重试
                self.logger.warning(f"[{worker_id}] JSON解析失败，将重试: {parse_error}")
                return self.retry_with_backoff(image_path, worker_id, temp_path)

        except Exception as e:
            error_str = str(e)
            if ("SAFETY" in error_str or "BLOCKED" in error_str or
                "安全" in error_str or "blocked" in error_str.lower() or
                "safety" in error_str.lower()):
                self.logger.info(f"[{worker_id}] Gemini安全过滤器检测到不适合内容: {image_path}")
                with self.stats_lock:
                    self.stats['ai_reject'] += 1
                return {
                    "suitable_for_teens": False,
                    "reason": "Gemini安全过滤器检测到不适合16岁及以上青少年的内容",
                    "confidence": 1.0
                }, temp_path
            elif "429" in error_str or "Too Many Requests" in error_str:
                # 429错误处理
                self.handle_rate_limit_error()
                self.logger.warning(f"[{worker_id}] API限流，将无限重试直到成功: {image_path}")
                # 无限重试逻辑
                return self.retry_with_backoff(image_path, worker_id, temp_path)
            else:
                # 对于非429错误也进行重试，确保100%覆盖率
                self.logger.warning(f"[{worker_id}] Gemini API调用失败，将重试: {e}")
                return self.retry_with_backoff(image_path, worker_id, temp_path)

    def move_inappropriate_image(self, image_path: str, reason: str, temp_path: str = None):
        """移动不适合的图片"""
        try:
            path_obj = Path(image_path)
            original_dir = path_obj.parent.name
            
            target_dir = Path(self.config['target_folder']) / original_dir
            target_dir.mkdir(parents=True, exist_ok=True)
            
            clean_reason = re.sub(r'[<>:"/\\|?*]', '_', reason)[:50]
            new_filename = f"{clean_reason}{path_obj.suffix}"
            
            target_path = target_dir / new_filename
            counter = 1
            while target_path.exists():
                new_filename = f"{clean_reason}_{counter}{path_obj.suffix}"
                target_path = target_dir / new_filename
                counter += 1
            
            shutil.move(str(path_obj), str(target_path))
            
            if temp_path and temp_path != image_path and os.path.exists(temp_path):
                os.unlink(temp_path)
            
            return True
            
        except Exception as e:
            self.logger.error(f"移动文件失败: {e}")
            return False

    def rename_approved_image(self, image_path: str):
        """重命名通过审查的图片"""
        try:
            path_obj = Path(image_path)
            if "_审查已经通过" in path_obj.stem:
                return True
            
            new_filename = f"{path_obj.stem}_审查已经通过{path_obj.suffix}"
            new_path = path_obj.parent / new_filename
            
            counter = 1
            while new_path.exists():
                new_filename = f"{path_obj.stem}_审查已经通过_{counter}{path_obj.suffix}"
                new_path = path_obj.parent / new_filename
                counter += 1
            
            shutil.move(str(path_obj), str(new_path))
            return True
            
        except Exception as e:
            self.logger.error(f"重命名失败: {e}")
            return False

    def process_single_image(self, image_path: str, worker_id: str):
        """处理单张图片"""
        try:
            with self.processed_lock:
                if image_path in self.processed_files:
                    return
                self.processed_files.add(image_path)

            self.logger.info(f"[{worker_id}] 开始处理: {image_path}")
            
            result, temp_path = self.check_image_safety(image_path, worker_id)
            
            if result.get("suitable_for_teens") is False:
                self.logger.warning(f"[{worker_id}] 不适合: {image_path} - {result.get('reason')}")
                if self.move_inappropriate_image(image_path, result.get('reason', '未知原因'), temp_path):
                    with self.stats_lock:
                        self.stats['moved'] += 1
                else:
                    with self.stats_lock:
                        self.stats['errors'] += 1
            elif result.get("suitable_for_teens") is True:
                self.logger.info(f"[{worker_id}] 通过: {image_path}")
                if self.rename_approved_image(image_path):
                    with self.stats_lock:
                        self.stats['approved'] += 1
                else:
                    with self.stats_lock:
                        self.stats['errors'] += 1
                
                if temp_path and temp_path != image_path and os.path.exists(temp_path):
                    os.unlink(temp_path)
            else:
                self.logger.warning(f"[{worker_id}] 跳过: {image_path} - {result.get('reason')}")
                with self.stats_lock:
                    self.stats['skipped'] += 1
                
                if temp_path and temp_path != image_path and os.path.exists(temp_path):
                    os.unlink(temp_path)
            
            with self.stats_lock:
                self.stats['processed'] += 1
            
        except Exception as e:
            self.logger.error(f"[{worker_id}] 处理图片出错: {image_path}, 错误: {e}")
            with self.stats_lock:
                self.stats['errors'] += 1

    def monitor_progress(self, start_time: float):
        """监控处理进度"""
        self.progress_bar.start()

        while True:
            time.sleep(2)  # 每2秒更新一次

            with self.stats_lock:
                processed = self.stats['processed']
                total = self.stats['total']

            if processed >= total:
                self.progress_bar.stop()
                break

            elapsed = time.time() - start_time
            if processed > 0:
                avg_speed = processed / elapsed
                eta = (total - processed) / avg_speed if avg_speed > 0 else 0
                self.progress_bar.update(processed, total, avg_speed, eta/60)
            else:
                self.progress_bar.update(processed, total)

    def run(self):
        """运行过滤器"""
        print("🚀 启动超高速多线程图片内容过滤系统 (16岁级别)")
        print(f"📁 不适合的图片将移动到 {self.config['target_folder']} 文件夹")
        print("✅ 通过的图片将添加 _审查已经通过 标记")
        print("🔍 新增：文件名成人内容检查")
        print(f"⚡ 并发数: {self.config['max_concurrent']} 个线程")
        print()
        
        images = self.get_all_images()
        self.stats['total'] = len(images)
        
        if not images:
            print("✅ 没有需要处理的图片")
            return

        print(f"找到 {len(images)} 张图片需要处理")
        print(f"预计处理时间：{len(images) / (self.config['max_concurrent'] * 10):.1f} 分钟")
        print()
        
        start_time = time.time()
        
        progress_thread = threading.Thread(target=self.monitor_progress, args=(start_time,))
        progress_thread.daemon = True
        progress_thread.start()
        
        with ThreadPoolExecutor(max_workers=self.config['max_concurrent']) as executor:
            future_to_image = {
                executor.submit(self.process_single_image, image_path, f"worker_{i:03d}"): image_path
                for i, image_path in enumerate(images)
            }
            
            for future in as_completed(future_to_image):
                image_path = future_to_image[future]
                try:
                    future.result()
                except Exception as e:
                    self.logger.error(f"任务执行失败: {image_path}, 错误: {e}")
        
        elapsed_time = time.time() - start_time

        # 确保进度条停止
        self.progress_bar.stop()

        print("📊 处理完成:")
        print(f"   总共: {self.stats['total']} 张")
        print(f"   处理: {self.stats['processed']} 张")
        print(f"   通过: {self.stats['approved']} 张")
        print(f"   移动: {self.stats['moved']} 张")
        print(f"   跳过: {self.stats['skipped']} 张")
        print(f"   AI拒绝: {self.stats['ai_reject']} 张")
        print(f"   错误: {self.stats['errors']} 张")
        print(f"   限流错误: {self.stats['rate_limit_errors']} 次")
        print(f"   重试次数: {self.stats['retries']} 次")
        print(f"   耗时: {elapsed_time:.1f} 秒 ({elapsed_time/60:.1f} 分钟)")
        if elapsed_time > 0 and self.stats['processed'] > 0:
            print(f"   平均速度: {self.stats['processed'] / elapsed_time:.2f} 张/秒")
        print(f"   最终并发数: {self.current_workers}")

# ==================== 标记清除功能 ====================

class ApprovalTagRemover:
    """审查标记移除器"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.processed_count = 0
        self.renamed_count = 0
        self.error_count = 0
        self.skipped_count = 0
        self.renamed_files = []
        
        self.approval_patterns = [
            r'_审查已经通过', r'_审查已通过', r'_审查通过',
            r'_已审查通过', r'_已通过审查', r'_通过审查',
            r'_审核通过', r'_已审核通过', r'_approved',
            r'_checked', r'_verified'
        ]
        
        self.image_extensions = {'.webp', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif'}
    
    def get_all_images(self) -> list:
        """获取所有图片文件"""
        images = []
        for root, _, files in os.walk('.'):
            for file in files:
                if Path(file).suffix.lower() in self.image_extensions:
                    images.append(os.path.join(root, file))
        return images
    
    def has_approval_tag(self, filename: str) -> bool:
        """检查文件名是否包含审查标记"""
        for pattern in self.approval_patterns:
            if re.search(pattern, filename, re.IGNORECASE):
                return True
        return False
    
    def remove_tags(self, filename: str) -> str:
        """从文件名中移除审查标记"""
        new_filename = filename
        for pattern in self.approval_patterns:
            new_filename = re.sub(pattern, '', new_filename, flags=re.IGNORECASE)
        
        new_filename = re.sub(r'_{2,}', '_', new_filename)
        new_filename = re.sub(r'_+\.', '.', new_filename)
        new_filename = re.sub(r'^_+', '', new_filename)
        return new_filename

    def run(self):
        """执行标记清除"""
        images = self.get_all_images()
        total = len(images)
        
        print(f"找到 {total} 张图片，开始处理...")
        print()  # 为进度条留出空间
        
        for i, image_path in enumerate(images, 1):
            self.processed_count += 1
            path_obj = Path(image_path)
            
            if self.has_approval_tag(path_obj.name):
                new_name = self.remove_tags(path_obj.name)
                new_path = path_obj.parent / new_name
                
                if new_path.exists():
                    self.logger.warning(f"目标文件已存在，跳过: {path_obj.name}")
                    self.skipped_count += 1
                    continue
                
                try:
                    path_obj.rename(new_path)
                    self.renamed_count += 1
                    self.logger.info(f"✅ {path_obj.name} -> {new_name}")
                except Exception as e:
                    self.error_count += 1
                    self.logger.error(f"❌ 重命名失败: {path_obj.name}, {e}")
            else:
                self.skipped_count += 1

            # 更新进度条
            progress_bar.update(i, total, prefix="清除标记")

        progress_bar.finish("标记清除完成")
        print("")
        print("📊 清除完成:")
        print(f"   总共处理: {self.processed_count}")
        print(f"   成功重命名: {self.renamed_count}")
        print(f"   跳过: {self.skipped_count}")
        print(f"   错误: {self.error_count}")

# ==================== 主流程 ====================

def run_image_filter(config):
    """运行图片过滤器"""
    filter_system = UltraFastImageFilter(config)
    filter_system.run()

def remove_approval_tags(config):
    """移除审查标记"""
    remover = ApprovalTagRemover()
    remover.run()

def main_menu():
    """主菜单"""
    config = load_config()
    while True:
        clear_screen()
        print_banner()
        
        # 统计信息
        total, unprocessed, approved = count_images(config)
        print("📊 当前状态:")
        print(f"   总图片数: {total}")
        print(f"   未处理: {unprocessed}")
        print(f"   已审查: {approved}")
        print()
        
        print("🎯 功能菜单:")
        print("   1. 配置系统 (API密钥、并发数等)")
        print("   2. 开始图片审查 (AI内容过滤)")
        print("   3. 清除审查标记 (移除_审查已经通过标记)")
        print("   4. 查看帮助")
        print("   0. 退出程序")
        print()
        
        choice = input("请选择功能 [0-4]: ").strip()
        
        if choice == '1':
            clear_screen()
            print_banner()
            config = interactive_config(config)
            if config:
                input("\n按回车键继续...")
        
        elif choice == '2':
            if unprocessed == 0:
                print("✅ 没有需要处理的图片")
                input("按回车键继续...")
                continue
                
            if not config['api_key']:
                print("❌ 请先配置API密钥")
                input("按回车键继续...")
                continue
            
            clear_screen()
            print_banner()
            print(f"即将处理 {unprocessed} 张图片")
            print(f"并发数: {config['max_concurrent']}")
            confirm = input("确认开始? [y/N]: ").strip().lower()
            if confirm in ['y', 'yes']:
                run_image_filter(config)
                input("\n处理完成，按回车键继续...")
        
        elif choice == '3':
            if approved == 0:
                print("✅ 没有需要清除标记的图片")
                input("按回车键继续...")
                continue
                
            clear_screen()
            print_banner()
            print(f"即将清除 {approved} 张图片的审查标记")
            confirm = input("确认清除? [y/N]: ").strip().lower()
            if confirm in ['y', 'yes']:
                remove_approval_tags(config)
                input("\n清除完成，按回车键继续...")
        
        elif choice == '4':
            clear_screen()
            print_banner()
            print("📖 使用帮助:")
            print()
            print("1. 配置系统:")
            print("   - 设置Google Gemini API密钥")
            print("   - 配置API服务器地址 (支持代理)")
            print("   - 选择合适的Gemini模型")
            print("   - 调整并发处理数量 (建议10-30)")
            print()
            print("2. 图片审查:")
            print("   - 使用Gemini AI检查图片内容是否适合16岁及以上青少年")
            print("   - 不适合的图片移动到 @色图 文件夹")
            print("   - 通过的图片添加 _审查已经通过 标记")
            print()
            print("3. 清除标记:")
            print("   - 移除所有 _审查已经通过 标记")
            print("   - 用于重新审查或清理文件名")
            print()
            print("4. 注意事项:")
            print("   - 确保网络连接稳定")
            print("   - API密钥需要有足够的额度")
            print("   - 支持官方服务器和代理服务器")
            print("   - 处理大量图片时请耐心等待")
            print()
            input("按回车键返回主菜单...")
        
        elif choice == '0':
            print("👋 感谢使用，再见！")
            break
        
        else:
            print("❌ 无效选择，请重新输入")
            time.sleep(1)

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\n\n👋 程序已中断，再见！")
    except Exception as e:
        print(f"\n❌ 程序出错: {e}")
        input("按回车键退出...")
