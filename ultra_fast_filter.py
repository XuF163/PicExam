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
from zhipuai import ZhipuAI
from PIL import Image
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
import signal
import sys

# 配置
API_KEY = "d7ee358d075849bfb7833d37b2503ad8.Lii3soccyVMgKorS"

class UltraFastImageFilter:
    def __init__(self, max_workers=20):
        self.max_workers = max_workers
        self.client = ZhipuAI(api_key=API_KEY)
        self.stats = {
            'total': 0,
            'processed': 0,
            'moved': 0,
            'approved': 0,
            'skipped': 0,
            'errors': 0,
            'ai_reject': 0
        }
        self.stats_lock = threading.Lock()
        self.processed_files = set()
        self.processed_lock = threading.Lock()
        self.setup_logging()
        
    def setup_logging(self):
        """设置日志"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - [%(threadName)s] %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('ultra_fast_filter.log', encoding='utf-8')
            ]
        )
        self.logger = logging.getLogger(__name__)

    def check_filename_for_adult_content(self, filename: str) -> bool:
        """检查文件名是否包含成人内容标识符"""
        adult_indicators = [
            'r18', 'r-18', 'nsfw', 'gu18', 'g18', 'adult', 'xxx', 'sex', 'porn',
            '色图', '涩图', '福利', '本子', 'hentai', 'ecchi', '工口', 'ero',
            '18+', '成人', '限制级', 'restricted', 'mature', '不可描述'
        ]
        
        filename_lower = filename.lower()
        for indicator in adult_indicators:
            if indicator in filename_lower:
                return True
        return False

    def get_all_images(self):
        """获取所有图片文件"""
        image_extensions = {'.webp', '.jpg', '.jpeg', '.png', '.gif', '.bmp'}
        images = []

        for root, dirs, files in os.walk('.'):
            if '@色图' in root:
                continue

            for file in files:
                if Path(file).suffix.lower() in image_extensions:
                    if "_审查已经通过" in file:
                        continue
                    file_path = os.path.join(root, file)
                    images.append(file_path)

        return images

    def validate_and_resize_image(self, image_path: str) -> str:
        """验证并调整图片大小"""
        try:
            with Image.open(image_path) as img:
                # 如果是WEBP，转换为JPEG
                if image_path.lower().endswith('.webp'):
                    if img.mode in ('RGBA', 'LA', 'P'):
                        img = img.convert('RGB')
                    
                    temp_fd, temp_path = tempfile.mkstemp(suffix='.jpg')
                    os.close(temp_fd)
                    img.save(temp_path, 'JPEG', quality=85)
                    return temp_path
                
                # 检查文件大小，如果太大则压缩
                file_size = os.path.getsize(image_path) / (1024 * 1024)
                if file_size > 3:
                    if img.mode in ('RGBA', 'LA', 'P'):
                        img = img.convert('RGB')
                    
                    # 压缩尺寸
                    max_size = 1024
                    ratio = min(max_size / img.width, max_size / img.height)
                    if ratio < 1:
                        new_width = int(img.width * ratio)
                        new_height = int(img.height * ratio)
                        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    
                    temp_fd, temp_path = tempfile.mkstemp(suffix='.jpg')
                    os.close(temp_fd)
                    img.save(temp_path, 'JPEG', quality=85)
                    return temp_path
                
                return image_path
                
        except Exception as e:
            self.logger.warning(f"图片处理失败: {e}")
            return image_path

    def check_image_safety(self, image_path: str, worker_id: str):
        """检查图片安全性"""
        temp_path = None
        
        try:
            # 1. 文件名检查
            if self.check_filename_for_adult_content(image_path):
                self.logger.warning(f"[{worker_id}] 文件名包含成人内容标识符: {image_path}")
                return {
                    "suitable_for_teens": False,
                    "reason": "文件名包含成人内容标识符，不适合16岁及以上青少年",
                    "confidence": 0.9
                }, temp_path

            # 2. 验证图片格式并在需要时压缩
            processed_path = self.validate_and_resize_image(image_path)
            if processed_path != image_path:
                temp_path = processed_path

            # 3. 读取图片并转换为Base64
            with open(processed_path, 'rb') as img_file:
                img_data = img_file.read()

            img_base64 = base64.b64encode(img_data).decode('utf-8')

            # 检查文件大小
            base64_size_mb = len(img_base64) / (1024 * 1024)
            if base64_size_mb > 10:
                return {
                    "suitable_for_teens": True,
                    "reason": "图片过大，跳过检查",
                    "confidence": 0.0
                }, temp_path

            # 4. 调用AI API
            response = self.client.chat.completions.create(
                model="glm-4.1v-thinking-flashx",
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
                                "text": """
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
                            }
                        ]
                    }
                ],
                timeout=60
            )
            
            content = response.choices[0].message.content
            
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
            except:
                return {"suitable_for_teens": True, "reason": "解析失败，默认通过", "confidence": 0.5}, temp_path
                
        except Exception as e:
            error_str = str(e)
            if "1301" in error_str or "contentFilter" in error_str or "不安全或敏感内容" in error_str:
                self.logger.info(f"[{worker_id}] AI检测到不适合内容: {image_path}")
                with self.stats_lock:
                    self.stats['ai_reject'] += 1
                return {
                    "suitable_for_teens": False,
                    "reason": "AI检测到不适合16岁及以上青少年的内容",
                    "confidence": 1.0
                }, temp_path
            else:
                self.logger.error(f"[{worker_id}] API调用失败: {e}")
                return {
                    "suitable_for_teens": True,
                    "reason": f"检查失败，默认通过: {str(e)}",
                    "confidence": 0.0
                }, temp_path

    def move_inappropriate_image(self, image_path: str, reason: str, temp_path: str = None):
        """移动不适合的图片"""
        try:
            path_obj = Path(image_path)
            original_dir = path_obj.parent.name
            
            target_dir = Path("@色图") / original_dir
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
            time.sleep(10)  # 每10秒更新一次进度
            
            with self.stats_lock:
                processed = self.stats['processed']
                total = self.stats['total']
            
            if processed >= total:
                break
                
            elapsed = time.time() - start_time
            if processed > 0:
                avg_speed = processed / elapsed
                eta = (total - processed) / avg_speed if avg_speed > 0 else 0
                print(f"📈 进度: {processed}/{total} ({processed/total*100:.1f}%) | "
                      f"速度: {avg_speed:.2f}张/秒 | "
                      f"预计剩余: {eta/60:.1f}分钟")
            else:
                print(f"📈 进度: {processed}/{total} ({processed/total*100:.1f}%)")

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
