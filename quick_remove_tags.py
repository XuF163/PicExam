#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速移除审查标记工具
简化版本，直接执行重命名操作
"""

import os
import re
from pathlib import Path

def remove_approval_tags():
    """快速移除所有图片的审查标记"""
    
    # 定义审查标记模式
    patterns = [
        r'_审查已经通过',
        r'_审查已通过', 
        r'_审查通过',
        r'_已审查通过',
        r'_已通过审查',
        r'_通过审查',
        r'_审核通过',
        r'_已审核通过'
    ]
    
    # 图片扩展名
    image_extensions = {'.webp', '.jpg', '.jpeg', '.png', '.gif', '.bmp'}
    
    renamed_count = 0
    error_count = 0
    
    print("🧹 开始移除审查标记...")
    
    # 遍历所有文件
    for root, dirs, files in os.walk('.'):
        for file in files:
            file_path = Path(root) / file
            
            # 检查是否是图片文件
            if file_path.suffix.lower() not in image_extensions:
                continue
            
            # 检查是否包含审查标记
            has_tag = False
            new_name = file
            
            for pattern in patterns:
                if re.search(pattern, file):
                    has_tag = True
                    new_name = re.sub(pattern, '', new_name)
            
            if not has_tag:
                continue
            
            # 清理多余的下划线
            new_name = re.sub(r'_{2,}', '_', new_name)
            new_name = re.sub(r'_+\.', '.', new_name)
            new_name = re.sub(r'^_+', '', new_name)
            
            # 如果新名称与原名称相同，跳过
            if new_name == file:
                continue
            
            try:
                new_path = file_path.parent / new_name
                
                # 如果目标文件已存在，添加序号
                if new_path.exists():
                    counter = 1
                    name_without_ext = new_path.stem
                    extension = new_path.suffix
                    
                    while new_path.exists():
                        new_name_with_counter = f"{name_without_ext}_{counter}{extension}"
                        new_path = file_path.parent / new_name_with_counter
                        counter += 1
                
                # 执行重命名
                file_path.rename(new_path)
                print(f"✅ {file} -> {new_path.name}")
                renamed_count += 1
                
            except Exception as e:
                print(f"❌ 重命名失败: {file} - {e}")
                error_count += 1
    
    print(f"\n📊 处理完成:")
    print(f"   成功重命名: {renamed_count} 个文件")
    print(f"   失败: {error_count} 个文件")

if __name__ == "__main__":
    # 确认操作
    print("⚠️  此操作将移除所有图片文件名中的审查标记")
    confirm = input("确认执行吗？(y/N): ")
    
    if confirm.lower() in ['y', 'yes']:
        remove_approval_tags()
    else:
        print("操作已取消")
