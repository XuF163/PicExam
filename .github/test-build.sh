#!/bin/bash

echo "========================================"
echo "GitHub Actions 构建测试脚本"
echo "========================================"
echo

echo "检查必需文件..."
if [ ! -f "image_filter_main.py" ]; then
    echo "❌ image_filter_main.py 不存在"
    exit 1
fi
echo "✅ image_filter_main.py 存在"

if [ ! -f "ultra_fast_filter.py" ]; then
    echo "❌ ultra_fast_filter.py 不存在"
    exit 1
fi
echo "✅ ultra_fast_filter.py 存在"

if [ ! -f "remove_approval_tags.py" ]; then
    echo "❌ remove_approval_tags.py 不存在"
    exit 1
fi
echo "✅ remove_approval_tags.py 存在"

if [ ! -f "filter_config.json" ]; then
    echo "❌ filter_config.json 不存在"
    exit 1
fi
echo "✅ filter_config.json 存在"

if [ ! -f "requirements.txt" ]; then
    echo "❌ requirements.txt 不存在"
    exit 1
fi
echo "✅ requirements.txt 存在"

echo
echo "检查可选文件..."
if [ -f "config.json" ]; then
    echo "✅ config.json 存在"
else
    echo "⚠️  config.json 不存在（可选文件，构建时会跳过）"
fi

echo
echo "模拟文件复制测试..."
mkdir -p test_release

echo "测试必需文件复制..."
if [ -f "filter_config.json" ]; then
    cp "filter_config.json" "test_release/"
    echo "✅ filter_config.json 复制成功"
else
    echo "❌ filter_config.json 复制失败"
    rm -rf test_release
    exit 1
fi

echo "测试可选文件复制..."
if [ -f "config.json" ]; then
    cp "config.json" "test_release/"
    echo "✅ config.json 复制成功"
else
    echo "⚠️  config.json 不存在，跳过复制（这是正常的）"
fi

echo
echo "✅ 所有测试通过！GitHub Actions 构建应该能正常工作。"

# 清理
rm -rf test_release

echo
echo "测试完成！"
