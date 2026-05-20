# GPT 图像批量生成 WebUI

这是一个独立的 Gradio WebUI，用于通过 OpenAI GPT Image 模型批量生成或编辑图片。项目不依赖外部源码目录，clone 后可以直接在本目录启动。

## Windows 一键启动

双击或在 PowerShell 中运行：

```powershell
.\webui-user.bat
```

`webui-user.bat` 会自动完成这些步骤：

- 检查 Python 3.10 或更高版本。
- 创建或复用本目录下的 `.venv` 虚拟环境。
- 运行 `pip install -r requirements.txt` 检查并安装依赖。
- 启动中文 WebUI，默认地址为 `http://127.0.0.1:7860`。

如果 `7860` 端口已被占用，程序会自动向后查找可用端口。bat 也会把额外参数继续传给 WebUI，例如：

```powershell
.\webui-user.bat --no-auto-launch
.\webui-user.bat --listen --auth user:password
```

## 手动启动

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m app web
```

## API Key

可以使用任意一种方式提供 API Key：

- 在环境变量中设置 `OPENAI_API_KEY`。
- 在 WebUI 中将 API Key 来源设为 `keyring`，并提前配置系统密钥环。
- 在 WebUI 当前会话中直接粘贴 API Key。

粘贴到 WebUI 的 API Key 不会保存到设置文件、manifest、命令预览或日志中。

## Base URL 与代理

如果使用 OpenAI 兼容网关，在 WebUI 的“API 与多轮上下文”里填写：

- `Base URL`: 网关地址，例如 `http://66.225.232.37:8317` 或 `http://66.225.232.37:8317/v1`。程序会把根地址自动规范化为 `/v1`。
- `代理 URL`: 可选。需要代理访问网关时填写本机代理地址，例如 `http://127.0.0.1:10808`。如果 PowerShell 可以访问服务但 WebUI 报 `Connection error`，通常需要在这里显式填写代理。

点击“试运行”会用 `GET /v1/models` 做快速联通检测；这不是图像生成任务，不会消耗一次图片任务。

## 目录说明

- `app/webui`: Gradio WebUI、启动器、设置、历史记录、预设和 WebUI 任务执行器。
- `app/core`: 配置、任务规划、执行、OpenAI 客户端、输出写入和事件处理。
- `app/api_capabilities.json`: 本地能力表，用于参数校验和 UI 选项生成。
- `app/cli`: 最小独立 CLI，包含 `web` 和 `run` 命令。

本包不包含原始 PySide6 桌面 GUI。
