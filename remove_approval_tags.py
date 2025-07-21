#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
去除图片文件名中的审查通过标记
功能：
1. 扫描所有图片文件
2. 去除文件名中的 "_审查已通过"、"_审查通过"、"_审查已经通过" 等标记
3. 批量重命名文件
4. 提供详细的操作日志和统计
"""

import os
import re
import logging
from pathlib import Path
from typing import List, Tuple, Dict
import time

class ApprovalTagRemover:
    """审查标记移除器"""
    
    def __init__(self):
        self.setup_logging()
        self.processed_count = 0
        self.renamed_count = 0
        self.error_count = 0
        self.skipped_count = 0
        self.renamed_files = []
        
        # 定义需要移除的标记模式
        self.approval_patterns = [
            r'_审查已经通过',
            r'_审查已通过', 
            r'_审查通过',
            r'_已审查通过',
            r'_已通过审查',
            r'_通过审查',
            r'_审核通过',
            r'_已审核通过',
            r'_approved',
            r'_checked',
            r'_verified'
        ]
        
        # 支持的图片格式
        self.image_extensions = {'.webp', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif'}
    
    def setup_logging(self):
        """设置日志系统"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('remove_approval_tags.log', encoding='utf-8')
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def get_all_images(self) -> List[str]:
        """获取所有图片文件"""
        images = []
        
        for root, dirs, files in os.walk('.'):
            for file in files:
                file_path = Path(file)
                if file_path.suffix.lower() in self.image_extensions:
                    full_path = os.path.join(root, file)
                    images.append(full_path)
        
        return images
    
    def has_approval_tag(self, filename: str) -> bool:
        """检查文件名是否包含审查标记"""
        for pattern in self.approval_patterns:
            if re.search(pattern, filename, re.IGNORECASE):
                return True
        return False
    
    def remove_approval_tags(self, filename: str) -> str:
        """从文件名中移除审查标记"""
        new_filename = filename
        
        for pattern in self.approval_patterns:
            new_filename = re.sub(pattern, '', new_filename, flags=re.IGNORECASE)
        
        # 清理可能产生的多余下划线
        new_filename = re.sub(r'_{2,}', '_', new_filename)  # 多个下划线合并为一个
        new_filename = re.sub(r'_+\.', '.', new_filename)   # 扩展名前的下划线
        new_filename = re.sub(r'^_+', '', new_filename)     # 开头的下划线
        
        return new_filename
    
    def rename_file(self, old_path: str) -> Tuple[bool, str, str]:
        """重命名单个文件"""
        try:
            old_path_obj = Path(old_path)
            old_filename = old_path_obj.name
            
            # 检查是否需要重命名
            if not self.has_approval_tag(old_filename):
                return False, old_path, "无需重命名"
            
            # 生成新文件名
            new_filename = self.remove_approval_tags(old_filename)
            new_path = old_path_obj.parent / new_filename
            
            # 检查新文件名是否与原文件名相同
            if new_filename == old_filename:
                return False, old_path, "移除标记后文件名未变化"
            
            # 检查目标文件是否已存在
            if new_path.exists():
                # 如果目标文件已存在，添加序号
                counter = 1
                name_without_ext = new_path.stem
                extension = new_path.suffix
                
                while new_path.exists():
                    new_filename_with_counter = f"{name_without_ext}_{counter}{extension}"
                    new_path = old_path_obj.parent / new_filename_with_counter
                    counter += 1
                
                self.logger.warning(f"目标文件已存在，使用新名称: {new_path.name}")
            
            # 执行重命名
            old_path_obj.rename(new_path)
            
            return True, str(new_path), "重命名成功"
            
        except Exception as e:
            self.logger.error(f"重命名文件失败: {old_path}, 错误: {e}")
            return False, old_path, f"重命名失败: {str(e)}"
    
    def process_all_images(self, dry_run: bool = False) -> Dict:
        """处理所有图片文件"""
        start_time = time.time()
        
        # 获取所有图片文件
        images = self.get_all_images()
        total_images = len(images)
        
        self.logger.info(f"找到 {total_images} 张图片文件")
        
        if dry_run:
            self.logger.info("🔍 预览模式：只显示将要重命名的文件，不执行实际操作")
        else:
            self.logger.info("🚀 开始批量移除审查标记")
        
        # 处理每个图片文件
        for i, image_path in enumerate(images, 1):
            self.processed_count += 1
            
            try:
                old_filename = Path(image_path).name
                
                # 检查是否包含审查标记
                if not self.has_approval_tag(old_filename):
                    self.skipped_count += 1
                    if i % 100 == 0:  # 每100个文件显示一次进度
                        self.logger.info(f"进度: {i}/{total_images} ({i/total_images*100:.1f}%)")
                    continue
                
                if dry_run:
                    # 预览模式：只显示将要重命名的文件
                    new_filename = self.remove_approval_tags(old_filename)
                    if new_filename != old_filename:
                        self.logger.info(f"将重命名: {old_filename} -> {new_filename}")
                        self.renamed_count += 1
                else:
                    # 实际重命名
                    success, new_path, message = self.rename_file(image_path)
                    
                    if success:
                        self.renamed_count += 1
                        self.renamed_files.append({
                            "old_path": image_path,
                            "new_path": new_path,
                            "old_filename": old_filename,
                            "new_filename": Path(new_path).name
                        })
                        self.logger.info(f"✅ {old_filename} -> {Path(new_path).name}")
                    else:
                        if "无需重命名" not in message:
                            self.error_count += 1
                            self.logger.warning(f"❌ {old_filename}: {message}")
                        else:
                            self.skipped_count += 1
                
                # 显示进度
                if i % 50 == 0:
                    self.logger.info(f"进度: {i}/{total_images} ({i/total_images*100:.1f}%)")
                    
            except Exception as e:
                self.error_count += 1
                self.logger.error(f"处理文件时出错: {image_path}, 错误: {e}")
        
        # 计算处理时间
        elapsed_time = time.time() - start_time
        
        # 返回统计信息
        return {
            "total_images": total_images,
            "processed": self.processed_count,
            "renamed": self.renamed_count,
            "skipped": self.skipped_count,
            "errors": self.error_count,
            "elapsed_time": elapsed_time,
            "renamed_files": self.renamed_files,
            "dry_run": dry_run
        }
    
    def print_summary(self, stats: Dict):
        """打印处理摘要"""
        print(f"\n{'='*60}")
        print(f"📊 处理完成摘要")
        print(f"{'='*60}")
        print(f"总共扫描图片: {stats['total_images']} 张")
        print(f"处理的图片: {stats['processed']} 张")
        print(f"{'预计重命名' if stats['dry_run'] else '成功重命名'}: {stats['renamed']} 张")
        print(f"跳过的图片: {stats['skipped']} 张 (无审查标记)")
        print(f"错误数量: {stats['errors']} 张")
        print(f"处理耗时: {stats['elapsed_time']:.2f} 秒")
        print(f"{'='*60}")
        
        if stats['dry_run']:
            print(f"🔍 这是预览模式，没有执行实际的重命名操作")
            print(f"如果确认无误，请运行: python remove_approval_tags.py --execute")
        else:
            if stats['renamed'] > 0:
                print(f"✅ 成功移除了 {stats['renamed']} 个文件的审查标记")
            if stats['errors'] > 0:
                print(f"⚠️ 有 {stats['errors']} 个文件处理失败，请检查日志")
        
        # 显示重命名的文件列表（限制显示数量）
        if stats['renamed_files'] and not stats['dry_run']:
            print(f"\n📋 重命名的文件列表 (显示前20个):")
            print("-" * 80)
            for i, file_info in enumerate(stats['renamed_files'][:20], 1):
                print(f"{i:2d}. {file_info['old_filename']}")
                print(f"    -> {file_info['new_filename']}")
            
            if len(stats['renamed_files']) > 20:
                print(f"    ... 还有 {len(stats['renamed_files']) - 20} 个文件")

def main():
    """主函数"""
    import sys
    
    # 检查命令行参数
    dry_run = True
    if len(sys.argv) > 1 and sys.argv[1] in ['--execute', '-e']:
        dry_run = False
    
    print("🧹 图片审查标记移除工具")
    print("=" * 50)
    
    if dry_run:
        print("🔍 预览模式：将显示需要重命名的文件，但不执行实际操作")
        print("如需执行实际操作，请使用: python remove_approval_tags.py --execute")
    else:
        print("⚠️  执行模式：将实际重命名文件")
        print("请确保已备份重要文件！")
        
        # 确认操作
        confirm = input("\n确认要执行批量重命名操作吗？(y/N): ")
        if confirm.lower() not in ['y', 'yes']:
            print("操作已取消")
            return
    
    print()
    
    # 创建移除器并执行
    remover = ApprovalTagRemover()
    stats = remover.process_all_images(dry_run=dry_run)
    
    # 打印摘要
    remover.print_summary(stats)

if __name__ == "__main__":
    main()
