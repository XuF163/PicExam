# GitHub 工作流说明

本项目包含三个 GitHub Actions 工作流，用于自动化构建、测试和发布流程。

## 工作流文件

### 1. `build.yml` - 多平台构建
**触发条件：**
- 推送到 `main`、`master`、`develop` 分支
- 向 `main`、`master` 分支提交 Pull Request
- 发布新版本

**功能：**
- 在 Windows、Linux、macOS 三个平台上构建可执行文件
- 使用 PyInstaller 打包 Python 应用
- 自动上传构建产物作为 Artifacts
- 缓存 pip 依赖以加速构建

**构建产物：**
- `PicExam-Windows` - Windows 可执行文件
- `PicExam-Linux` - Linux 可执行文件  
- `PicExam-macOS` - macOS 可执行文件

### 2. `test.yml` - 测试和代码检查
**触发条件：**
- 推送到 `main`、`master`、`develop` 分支
- 向 `main`、`master` 分支提交 Pull Request

**功能：**
- Python 代码语法检查（使用 flake8）
- 模块导入测试
- 必需文件存在性检查
- JSON 配置文件格式验证

### 3. `release.yml` - 自动发布
**触发条件：**
- 推送以 `v` 开头的标签（如 `v1.0.0`）

**功能：**
- 自动创建 GitHub Release
- 构建所有平台的可执行文件
- 打包成 ZIP 文件并上传到 Release

## 使用方法

### 日常开发
1. 提交代码到 `develop` 分支会触发构建和测试
2. 创建 Pull Request 到 `main` 分支会运行完整的 CI 流程
3. 合并到 `main` 分支会触发正式构建

### 发布新版本
1. 确保代码已合并到 `main` 分支
2. 创建并推送版本标签：
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```
3. GitHub 会自动创建 Release 并上传所有平台的构建文件

### 下载构建产物
- **开发版本**：在 Actions 页面下载 Artifacts
- **正式版本**：在 Releases 页面下载对应平台的 ZIP 文件

## 构建要求

### Python 环境
- Python 3.9
- 依赖包：见 `requirements.txt`

### 必需文件
- `image_filter_main.py` - 主程序文件
- `ultra_fast_filter.py` - 快速过滤模块
- `remove_approval_tags.py` - 标签移除模块
- `filter_config.json` - 过滤配置文件
- `requirements.txt` - Python 依赖

## 故障排除

### 构建失败
1. 检查 Python 语法错误
2. 确认所有必需文件存在
3. 验证 JSON 配置文件格式
4. 检查依赖包是否正确安装

### 发布失败
1. 确认标签格式正确（以 `v` 开头）
2. 检查 GitHub Token 权限
3. 确认构建步骤成功完成

## 自定义配置

### 修改构建平台
在 `build.yml` 和 `release.yml` 中的 `matrix` 部分添加或删除平台配置。

### 修改触发条件
在各工作流文件的 `on` 部分修改触发分支或事件。

### 添加构建步骤
在相应的工作流文件中添加新的 `steps`。
