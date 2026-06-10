# 淘宝商品高清图保存助手

一个 Windows 本机桌面小工具，用可见浏览器辅助浏览淘宝关键词搜索结果，并保存用户正常浏览时页面暴露出的商品主图和详情图。

## 合规边界

- 本工具用于个人资料整理和手动浏览辅助。
- 需要用户自行登录淘宝，遇到登录、验证码或安全校验时会暂停并提示人工处理。
- 不包含验证码绕过、指纹伪装、代理池、隐藏自动化痕迹或高频并发采集能力。
- 请控制采集频率，并遵守淘宝网站条款、版权要求和当地法律法规。

## 安装

需要 Python 3.10 或更新版本。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
python -m playwright install chromium
```

如果当前电脑没有 `python` 命令，请先安装 Python，并在安装时勾选 `Add python.exe to PATH`。

## 运行

```powershell
python -m taobao_image_saver
```

也可以运行：

```powershell
.\run_taobao_image_saver.bat
```

第一次运行会打开一个可见 Chromium 浏览器。请在浏览器里手动登录淘宝；登录状态会保存在本项目的 `browser-user-data/` 目录，之后通常无需重复登录。

## 使用方式

1. 输入关键词。
2. 设置最大商品数、操作间隔、每页滚动次数和保存目录。
3. 点击开始。
4. 如遇登录或验证页面，按提示在浏览器中手动处理后继续。

输出示例：

```text
output/
  商品标题/
    metadata.json
    images/
      main_001.jpg
      detail_001.jpg
```

`metadata.json` 会记录标题、链接、价格、店铺名、图片文件列表、采集时间和失败原因。

## GitHub 发布

本目录已经包含开源仓库需要的源码、说明和 `.gitignore`。当前机器若没有 Git，可以：

- 安装 Git 后执行 `git init`、`git add .`、`git commit`、`git remote add origin ...`、`git push`。
- 或使用 GitHub Desktop / GitHub 网页上传这些文件。

## 测试

```powershell
pip install -r requirements.txt
pip install -e .
pytest
```
