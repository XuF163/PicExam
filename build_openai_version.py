#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini版本打包脚本 - 简化版
避免复杂依赖冲突
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def create_minimal_spec():
    """创建最小化的spec文件"""
    spec_content = '''
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['image_filter_main.py'],
    pathex=['.'],
    binaries=[],
    datas=[('filter_config.json', '.')],
    hiddenimports=[
        'google.generativeai',
        'google.generativeai.client',
        'google.generativeai.types',
        'google.ai.generativelanguage',
        'google.auth',
        'google.auth.transport',
        'google.auth.transport.requests',
        'google.protobuf',
        'PIL._tkinter_finder',
        'PIL.Image',
        'PIL.ImageTk',
        'requests',
        'urllib3',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'torch',
        'tensorflow',
        'sympy',
        'jupyter',
        'IPython',
        'sphinx',
        'pyarrow',
        'dask',
        'distributed',
        'lxml',
        'pytest',
        'black',
        'zmq',
        'PyQt5',
        'tkinter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='图片内容过滤系统_Gemini版',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    cofile=None,
    entitlements_file=None,
)
'''
    
    with open('gemini_version.spec', 'w', encoding='utf-8') as f:
        f.write(spec_content)
    
    print("✅ 创建最小化spec文件成功")

def build_exe():
    """使用spec文件构建exe"""
    print("🚀 开始构建 Gemini 版本...")
    
    try:
        # 清理旧文件
        if Path('build').exists():
            shutil.rmtree('build')
        if Path('dist').exists():
            shutil.rmtree('dist')
        
        # 创建spec文件
        create_minimal_spec()
        
        # 使用spec文件构建
        cmd = ['pyinstaller', 'gemini_version.spec', '--clean']
        subprocess.run(cmd, check=True)
        
        # 检查结果
        exe_path = Path('dist/图片内容过滤系统_Gemini版.exe')
        if exe_path.exists():
            print(f"✅ 构建成功！")
            print(f"📁 可执行文件位置: {exe_path.absolute()}")
            
            # 复制到根目录
            shutil.copy(exe_path, '.')
            print(f"📋 已复制到: {Path('.').absolute() / '图片内容过滤系统_Gemini版.exe'}")
        else:
            print("❌ 未找到生成的exe文件")
            
    except subprocess.CalledProcessError as e:
        print(f"❌ 构建失败: {e}")
    except Exception as e:
        print(f"❌ 构建过程出错: {e}")

def main():
    print("=" * 60)
    print("🎯 图片内容过滤系统 - Gemini版本构建工具")
    print("=" * 60)
    print()
    
    # 检查PyInstaller
    try:
        import PyInstaller
        print("✅ PyInstaller 可用")
    except ImportError:
        print("❌ PyInstaller 未安装")
        print("正在安装...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("✅ PyInstaller 安装完成")
    
    build_exe()
    
    print("\n🎉 构建过程完成！")
    print("\n📝 使用说明:")
    print("1. 运行生成的exe文件")
    print("2. 在配置菜单中设置 Google Gemini API 密钥")
    print("3. 享受新的Gemini AI视觉模型功能！")

if __name__ == "__main__":
    main()