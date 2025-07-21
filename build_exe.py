#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打包脚本 - 将图片内容过滤系统打包为exe
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

def check_requirements():
    """检查依赖"""
    print("检查依赖...")
    try:
        import PyInstaller
        print("✅ PyInstaller 已安装")
    except ImportError:
        print("❌ PyInstaller 未安装，正在安装...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller>=5.0.0"])
        print("✅ PyInstaller 安装完成")

def build_exe():
    """打包为exe"""
    print("开始打包...")
    
    # 创建打包目录
    build_dir = Path("build")
    dist_dir = Path("dist")
    
    if build_dir.exists():
        shutil.rmtree(build_dir)
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    
    # 复制必要文件到临时目录
    temp_dir = Path("temp_build")
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    
    # 复制核心文件
    for file in ["image_filter_main.py", "filter_config.json"]:
        if Path(file).exists():
            shutil.copy(file, temp_dir)
    
    # 创建图标
    icon_path = temp_dir / "icon.ico"
    if not icon_path.exists():
        try:
            from PIL import Image
            # 创建一个简单的图标
            img = Image.new('RGB', (256, 256), color=(0, 120, 212))
            img.save(temp_dir / "icon.png")
            subprocess.run([sys.executable, "-m", "pip", "install", "pillow-avif-plugin"], check=True)
            subprocess.run([sys.executable, "-c", 
                           "from PIL import Image; img = Image.open('temp_build/icon.png'); img.save('temp_build/icon.ico')"], 
                           check=True)
            print("✅ 创建图标成功")
        except Exception as e:
            print(f"⚠️ 创建图标失败: {e}")
            # 使用默认图标
            pass
    
    # 运行PyInstaller
    os.chdir(temp_dir)
    
    cmd = [
        "pyinstaller",
        "--name=图片内容过滤系统",
        "--onefile",
        "--clean",
        "--add-data=filter_config.json;."
    ]
    
    if icon_path.exists():
        cmd.append(f"--icon=icon.ico")
    
    cmd.append("image_filter_main.py")
    
    try:
        subprocess.run(cmd, check=True)
        print("✅ 打包成功")
        
        # 复制exe到上级目录
        os.chdir("..")
        if Path("temp_build/dist/图片内容过滤系统.exe").exists():
            shutil.copy("temp_build/dist/图片内容过滤系统.exe", ".")
            print(f"✅ 可执行文件已生成: {os.path.abspath('图片内容过滤系统.exe')}")
        else:
            print("❌ 找不到生成的exe文件")
        
        # 清理临时文件
        shutil.rmtree("temp_build")
        
    except Exception as e:
        print(f"❌ 打包失败: {e}")
        os.chdir("..")

if __name__ == "__main__":
    print("=" * 50)
    print("图片内容过滤系统 - 打包工具")
    print("=" * 50)
    
    check_requirements()
    build_exe()
    
    print("\n打包过程完成")
    input("按回车键退出...")
