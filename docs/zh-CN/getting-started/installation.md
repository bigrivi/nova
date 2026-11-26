# 安装

## 前置条件

- Python 3.12+
- 终端界面需要 [bun](https://bun.sh)

## 用脚本安装

对大多数用户来说，这一步就是全部：

```bash
curl -fsSL https://raw.githubusercontent.com/bigrivi/nova/main/install | bash
```

脚本会检查上面两个前置条件，把 Nova 装进独立环境（有 `uv` 或 `pipx` 就用它们，
否则退回 `pip install --user`），把 `nova` 加进 `PATH`，并把对应平台的预编译终端
客户端下载到 `$NOVA_HOME/tui`。

客户端包在解压前会对照该版本发布的 `SHA256SUMS` 校验。如果某个版本没有为你这个平台
提供清单条目，包**不会**被安装，`nova tui` 会在首次运行时从源码构建。

```bash
--version <v>        安装指定的发布 tag（例如 1.0.2）
--no-modify-path     不改动 shell 的 rc 文件
```

## 从源码安装

在开发 Nova 本身时用这个：

```bash
# 把 Nova 和 SDK 克隆为兄弟目录
git clone https://github.com/bigrivi/nova.git
git clone https://github.com/bigrivi/novakit.git
cd nova

# 安装 Nova 和本地 novakit checkout
uv sync
```

## 让 `nova` 可以在 PATH 里调用 { #making-nova-available-on-path }

`uv sync` 会在 `.venv/bin` 生成 `nova` 启动器。只有该目录在 `PATH` 上，命令才能在任意目录下
使用；也可以直接用 `uv run nova`。

先找到这个目录：

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts'))"
```

然后从下面几种做法里选一种。

### A. 把虚拟环境放进 PATH

```bash
# 在 Nova checkout 中运行，并确保 ../novakit 已克隆
uv sync
# 把当前这份 checkout 的 venv 加进 PATH（在仓库根目录运行）
echo "export PATH=\"$PWD/.venv/bin:\$PATH\"" >> ~/.zshrc
exec zsh
```

这样路径只对当前这份 checkout 生效，所以移动或重命名仓库会让命令失效。用 Bash 的话，
改为追加到 `~/.bashrc`。每个项目的环境都需要单独加一次。

### B. pipx 和 uv tool

在 `novakit` 作为独立包发布之前，这两种安装方式不可用。本地开发请使用
`uv sync` 或 `uv run nova`。

### C. 用户级 Python 安装

在 `novakit` 发布前，用户级安装同样不可用。请使用 `uv sync` 创建的项目虚拟环境。

在 macOS 上，Homebrew Python 被标记为 externally managed（PEP 668），所以默认拒绝往里
`pip install`。做法 A 能绕开这一点。

### 验证

```bash
which nova     # 必须打印出一个路径
nova --help
```

如果 `which nova` 什么都不打印，说明放着启动器的那个目录不在 `PATH` 上；把上面第一条
命令给出的目录加进你的 shell 配置。

## 浏览器自动化（可选）

Playwright 包随 Nova 一起分发 —— `uv sync` 已经装上了。Nova 的浏览器工具会在
首次使用时自动安装它还需要的其他东西，并且有系统 Chrome 时优先用系统那个。想同时把
自带的 Chromium 作为兜底：

```bash
playwright install chromium
```

网页搜索和网页抓取不需要 Playwright。

## 桌面打包（可选）

要构建桌面应用，先装 PyInstaller：

```bash
pip install pyinstaller
```

构建步骤见[桌面应用](../desktop/index.md)。

## 验证安装

```bash
nova --help
```

你应该看到 Nova 的帮助输出。

## 下一步

- [快速上手](quickstart.md) ：配置提供方并开始对话
- [模型提供方](../configuration/providers.md) ：配置 Ollama 或 OpenAI
