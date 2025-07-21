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
from zhipuai import ZhipuAI
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed

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

def load_config():
    """加载配置文件"""
    config_file = 'config.json'
    default_config = {
        'api_key': '',
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
        with open('config.json', 'w', encoding='utf-8') as f:
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
    print(f"⚡ 并发数: {config['max_concurrent']}")
    print(f"📁 目标文件夹: {config['target_folder']}")
    print()
    
    # API密钥配置
    if not config['api_key']:
        print("📝 请输入智谱AI的API密钥:")
        print("   (可在 https://open.bigmodel.cn 获取)")
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
        self.client = ZhipuAI(api_key=config['api_key'])
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
                logging.FileHandler('image_filter.log', encoding='utf-8')
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
                timeout=self.config['timeout']
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
        while True:
            time.sleep(10)
            
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
        
        print(f"\n📊 处理完成:")
        print(f"   总共: {self.stats['total']} 张")
        print(f"   处理: {self.stats['processed']} 张")
        print(f"   通过: {self.stats['approved']} 张")
        print(f"   移动: {self.stats['moved']} 张")
        print(f"   跳过: {self.stats['skipped']} 张")
        print(f"   AI拒绝: {self.stats['ai_reject']} 张")
        print(f"   错误: {self.stats['errors']} 张")
        print(f"   耗时: {elapsed_time:.1f} 秒 ({elapsed_time/60:.1f} 分钟)")
        if elapsed_time > 0 and self.stats['processed'] > 0:
            print(f"   平均速度: {self.stats['processed'] / elapsed_time:.2f} 张/秒")

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

            if i % 100 == 0:
                print(f"进度: {i}/{total} ({i/total*100:.1f}%)")

        print("\n📊 清除完成:")
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
            print("   - 设置智谱AI的API密钥")
            print("   - 调整并发处理数量 (建议10-30)")
            print()
            print("2. 图片审查:")
            print("   - 使用AI检查图片内容是否适合16岁及以上青少年")
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
