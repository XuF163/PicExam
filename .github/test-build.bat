@echo off
chcp 65001 >nul
echo ========================================
echo GitHub Actions 构建测试脚本
echo ========================================
echo.

echo 检查必需文件...
if not exist "image_filter_main.py" (
    echo ❌ image_filter_main.py 不存在
    goto :error
)
echo ✅ image_filter_main.py 存在

if not exist "ultra_fast_filter.py" (
    echo ❌ ultra_fast_filter.py 不存在
    goto :error
)
echo ✅ ultra_fast_filter.py 存在

if not exist "remove_approval_tags.py" (
    echo ❌ remove_approval_tags.py 不存在
    goto :error
)
echo ✅ remove_approval_tags.py 存在

if not exist "filter_config.json" (
    echo ❌ filter_config.json 不存在
    goto :error
)
echo ✅ filter_config.json 存在

if not exist "requirements.txt" (
    echo ❌ requirements.txt 不存在
    goto :error
)
echo ✅ requirements.txt 存在

echo.
echo 检查可选文件...
if exist "config.json" (
    echo ✅ config.json 存在
) else (
    echo ⚠️  config.json 不存在（可选文件，构建时会跳过）
)

echo.
echo 模拟文件复制测试...
mkdir test_release 2>nul

echo 测试必需文件复制...
if exist "filter_config.json" (
    copy "filter_config.json" "test_release\" >nul
    echo ✅ filter_config.json 复制成功
) else (
    echo ❌ filter_config.json 复制失败
    goto :cleanup_error
)

echo 测试可选文件复制...
if exist "config.json" (
    copy "config.json" "test_release\" >nul
    echo ✅ config.json 复制成功
) else (
    echo ⚠️  config.json 不存在，跳过复制（这是正常的）
)

echo.
echo ✅ 所有测试通过！GitHub Actions 构建应该能正常工作。

:cleanup
if exist "test_release" rmdir /s /q "test_release"
echo.
echo 测试完成！
pause
exit /b 0

:cleanup_error
if exist "test_release" rmdir /s /q "test_release"
goto :error

:error
echo.
echo ❌ 测试失败！请检查缺失的文件。
pause
exit /b 1
