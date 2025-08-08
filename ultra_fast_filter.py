#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
超高速多线程图片内容过滤系统
使用真正的多线程并发，大幅提升处理速度
"""

import os
import json
import base64
import shutil
import re
import logging
import time
import threading
from pathlib import Path
import google.generativeai as genai
from openai import OpenAI
from PIL import Image
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
import signal
import sys

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
                sys.stdout.write('\r' + ' ' * 120 + '\r')
                print(f"✓ {message}")
                self.is_showing = False
                # 清除保存的状态
                self.last_current = 0
                self.last_total = 0
                self.last_stats_info = ""

# 全局进度条
progress_bar = SimpleProgressBar()

class SafeLogHandler(logging.Handler):
    """安全的日志处理器"""
    
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

# 注意：API配置现在从配置文件读取

class UltraFastImageFilter:
    def __init__(self, max_workers=20):
        self.max_workers = max_workers
        self.original_max_workers = max_workers  # 保存原始并发数
        self.current_workers = max_workers
        self.load_config()
        self.stats = {
            'total': 0,
            'processed': 0,
            'moved': 0,
            'approved': 0,
            'skipped': 0,
            'errors': 0,
            'ai_reject': 0,
            'rate_limit_errors': 0,
            'retries': 0,
            'failed_checks': 0,  # 检查失败的图片
            'oversized_skipped': 0,  # 因过大跳过的图片
            'suspicious_passes': 0  # 可疑的通过（低置信度）
        }
        self.stats_lock = threading.Lock()
        self.processed_files = set()
        self.processed_lock = threading.Lock()
        
        # 智能异常处理相关
        self.rate_limit_count = 0
        self.rate_limit_lock = threading.Lock()
        self.last_rate_limit_time = 0
        self.adaptive_delay = 1.0  # 自适应延迟
        self.setup_logging()
    
    def load_config(self):
        """加载配置文件"""
        try:
            with open('filter_config.json', 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            # 检查是否使用代理服务器
            self.use_proxy = config_data.get('use_proxy', False)
            self.base_url = config_data.get('base_url', '')
            self.api_key = config_data.get('api_key', '')
            self.model_name = config_data.get('model_name', 'gemini-2.5-pro')
            self.timeout = config_data.get('timeout', 60)
            self.target_folder = config_data.get('target_folder', '@色图')
            
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
            
        except Exception as e:
            print(f"⚠️ 加载配置失败，使用默认配置: {e}")
            # 使用默认配置
            self.use_proxy = False
            genai.configure(api_key='')
            self.model = genai.GenerativeModel('gemini-1.5-flash')
            self.timeout = 60
            self.target_folder = '@色图'
        
    def setup_logging(self):
        """设置日志"""
        # 清除默认处理器
        logging.getLogger().handlers.clear()
        
        # 创建日志格式器
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(threadName)s] %(message)s')
        
        # 添加安全日志处理器
        safe_handler = SafeLogHandler()
        safe_handler.setFormatter(formatter)
        
        # 添加文件处理器
        file_handler = logging.FileHandler('ultra_fast_filter.log', encoding='utf-8')
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

    def should_reduce_concurrency(self) -> bool:
        """判断是否应该降低并发数"""
        with self.rate_limit_lock:
            # 如果最近1分钟内有超过10次限流错误，降低并发数
            recent_time = time.time() - 60
            if self.last_rate_limit_time > recent_time and self.rate_limit_count > 10:
                return True
        return False

    def auto_adjust_concurrency(self):
        """自动调整并发数"""
        if self.should_reduce_concurrency():
            with self.rate_limit_lock:
                new_workers = max(1, self.current_workers - 2)
                if new_workers != self.current_workers:
                    self.current_workers = new_workers
                    self.logger.warning(f"🔧 自动降低并发数至: {self.current_workers}")
        else:
            # 如果长时间没有限流错误，逐渐恢复并发数
            with self.rate_limit_lock:
                if time.time() - self.last_rate_limit_time > 300:  # 5分钟没有限流
                    if self.current_workers < self.original_max_workers:
                        self.current_workers = min(self.original_max_workers, self.current_workers + 1)
                        self.logger.info(f"🔧 恢复并发数至: {self.current_workers}")
                        self.adaptive_delay = max(1.0, self.adaptive_delay * 0.9)  # 减少延迟

    def check_filename_for_adult_content(self, filename: str) -> bool:
        """检查文件名是否包含成人内容标识符 - 已禁用"""
        # 根据用户要求，不再依据文件名判断
        return False

    def get_all_images(self):
        """获取所有图片文件"""
        image_extensions = {'.webp', '.jpg', '.jpeg', '.png', '.gif', '.bmp'}
        images = []

        for root, dirs, files in os.walk('.'):
            if self.target_folder in root:
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
                    timeout=self.timeout
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
            
            target_dir = Path(self.target_folder) / original_dir
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
            # 检查是否已经处理过
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
                
                # 清理临时文件
                if temp_path and temp_path != image_path and os.path.exists(temp_path):
                    os.unlink(temp_path)
            else:
                self.logger.warning(f"[{worker_id}] 跳过: {image_path} - {result.get('reason')}")
                with self.stats_lock:
                    self.stats['skipped'] += 1
                
                # 清理临时文件
                if temp_path and temp_path != image_path and os.path.exists(temp_path):
                    os.unlink(temp_path)
            
            # 检查是否需要手动复查
            if result.get("confidence", 1.0) < 0.5:
                with self.review_lock:
                    self.manual_review_list.append({
                        'file': image_path,
                        'reason': result.get('reason', '未知'),
                        'confidence': result.get('confidence', 0.0),
                        'action': 'passed_low_confidence'
                    })
            
            with self.stats_lock:
                self.stats['processed'] += 1
            
        except Exception as e:
            self.logger.error(f"[{worker_id}] 处理图片出错: {image_path}, 错误: {e}")
            with self.stats_lock:
                self.stats['errors'] += 1

    def run(self):
        """运行过滤器"""
        print("🚀 启动超高速多线程图片内容过滤系统 (16岁级别)")
        print("📁 不适合的图片将移动到 @色图 文件夹")
        print("✅ 通过的图片将添加 _审查已经通过 标记")
        print("🔍 新增：文件名成人内容检查")
        print(f"⚡ 真正多线程并发：{self.max_workers} 个线程同时工作")
        print()
        
        images = self.get_all_images()
        self.stats['total'] = len(images)
        
        print(f"找到 {len(images)} 张图片需要处理")
        print(f"预计处理时间：{len(images) / (self.max_workers * 10):.1f} 分钟")
        print()
        
        start_time = time.time()
        
        # 启动进度监控线程
        progress_thread = threading.Thread(target=self.monitor_progress, args=(start_time,))
        progress_thread.daemon = True
        progress_thread.start()
        
        # 使用线程池并发处理
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            future_to_image = {
                executor.submit(self.process_single_image, image_path, f"worker_{i:03d}"): image_path
                for i, image_path in enumerate(images)
            }
            
            # 等待所有任务完成
            for future in as_completed(future_to_image):
                image_path = future_to_image[future]
                try:
                    future.result()
                except Exception as e:
                    self.logger.error(f"任务执行失败: {image_path}, 错误: {e}")
        
        elapsed_time = time.time() - start_time
        
        # 打印最终统计
        print(f"\n📊 处理完成:")
        print(f"   总共: {self.stats['total']} 张")
        print(f"   处理: {self.stats['processed']} 张")
        print(f"   通过: {self.stats['approved']} 张")
        print(f"   移动: {self.stats['moved']} 张")
        print(f"   跳过: {self.stats['skipped']} 张")
        print(f"   AI拒绝: {self.stats['ai_reject']} 张")
        print(f"   错误: {self.stats['errors']} 张")
        print(f"   耗时: {elapsed_time:.1f} 秒 ({elapsed_time/60:.1f} 分钟)")
        if elapsed_time > 0:
            print(f"   平均速度: {self.stats['processed'] / elapsed_time:.2f} 张/秒")

    def monitor_progress(self, start_time: float):
        """监控处理进度"""
        while True:
            time.sleep(2)  # 每2秒更新一次
            
            with self.stats_lock:
                processed = self.stats['processed']
                total = self.stats['total']
                moved = self.stats['moved']
                approved = self.stats['approved']
                errors = self.stats['errors']
            
            if processed >= total:
                progress_bar.finish("审查完成")
                break
                
            elapsed = time.time() - start_time
            if processed > 0:
                avg_speed = processed / elapsed
                eta = (total - processed) / avg_speed if avg_speed > 0 else 0
                
                # 构建统计信息 - 保持简洁
                stats_info = f"通过:{approved} 移动:{moved} 错误:{errors} 速度:{avg_speed:.1f}/秒 剩余:{eta/60:.1f}分"
                
                # 更新进度条
                progress_bar.update(processed, total, stats_info, "审查进度")
            else:
                progress_bar.update(processed, total, "准备中...", "审查进度")

def main():
    """主函数"""
    # 设置信号处理
    def signal_handler(sig, frame):
        print('\n收到中断信号，正在安全退出...')
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    # 创建并运行过滤器
    filter_system = UltraFastImageFilter(max_workers=20)  # 20个线程并发
    filter_system.run()

if __name__ == "__main__":
    main()
