@echo off
chcp 65001 >nul
echo ========================================
echo 图片内容过滤系统 - 打包工具
echo ========================================
echo.

echo 检查Python环境...
python --version
if errorlevel 1 (
    echo ❌ Python未安装或未添加到PATH
    pause
    exit /b 1
)

echo.
echo 安装依赖...
pip install -r requirements.txt

echo.
echo 开始打包...
pyinstaller --name="图片内容过滤系统" ^
    --onefile ^
    --console ^
    --clean ^
    --add-data="ultra_fast_filter.py;." ^
    --add-data="remove_approval_tags.py;." ^
    --add-data="filter_config.json;." ^
    image_filter_main.py

echo.
if exist "dist\图片内容过滤系统.exe" (
    echo ✅ 打包成功！
    copy "dist\图片内容过滤系统.exe" "."
    echo 可执行文件: %cd%\图片内容过滤系统.exe
) else (
    echo ❌ 打包失败
)

echo.
echo 清理临时文件...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "图片内容过滤系统.spec" del "图片内容过滤系统.spec"

echo.
echo 打包完成！
pause
