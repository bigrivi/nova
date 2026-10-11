# 安装

## 前置条件

- Python 3.12+
- pip

## 从源码安装

```bash
# 克隆仓库
git clone https://github.com/bigrivi/nova.git
cd nova

# 以可编辑模式安装 Nova
pip install -e .
```

## 让 `nova` 可以在 PATH 里调用 { #making-nova-available-on-path }

`pip install -e .` 会把 `nova` 启动器写进你安装时所用的那个 Python 环境的 `bin/` 目录。
只有该目录在 `PATH` 上，命令才能在任意目录下使用。装进一个你从没激活过的虚拟环境，
是 `zsh: command not found: nova` 最常见的原因。

先找到这个目录：

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts'))"
```

然后从下面几种做法里选一种。

### A. 把虚拟环境放进 PATH

```bash
git clone https://github.com/bigrivi/nova.git
cd nova
python3.12 -m venv .venv
.venv/bin/pip install -e .
# 把当前这份 checkout 的 venv 加进 PATH（在仓库根目录运行）
echo "export PATH=\"$PWD/.venv/bin:\$PATH\"" >> ~/.zshrc
exec zsh
```

这样路径只对当前这份 checkout 生效，所以移动或重命名仓库会让命令失效。用 Bash 的话，
改为追加到 `~/.bashrc`。每个项目的环境都需要单独加一次。

### B. pipx（推荐给最终用户）

pipx 把 Nova 装进独立的隔离环境，并把一个 shim 放进已经在 `PATH` 上的目录。

```bash
brew install pipx                 # macOS；或：python3 -m pip install --user pipx
pipx ensurepath                   # 把 ~/.local/bin 加进 PATH
cd nova
pipx install -e .                 # 生成 ~/.local/bin/nova
```

`ensurepath` 之后要开一个新 shell，`PATH` 的改动才会生效。

### C. uv tool

```bash
cd nova
uv tool install -e .
uv tool update-shell              # 确保 ~/.local/bin 在 PATH 上
```

### D. 用户级 Python 安装

如果你装的是系统级或用户级 Python，而不是虚拟环境，就把它的 scripts 目录加进 `PATH`：

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts'))"
# macOS 示例：/Users/<you>/Library/Python/3.12/bin
echo 'export PATH="$HOME/Library/Python/3.12/bin:$PATH"' >> ~/.zshrc
```

在 macOS 上，Homebrew Python 被标记为 externally managed（PEP 668），所以默认拒绝往里
`pip install`。做法 A、B、C 都能绕开这一点。

### 验证

```bash
which nova     # 必须打印出一个路径
nova --help
```

如果 `which nova` 什么都不打印，说明放着启动器的那个目录不在 `PATH` 上；把上面第一条
命令给出的目录加进你的 shell 配置。

## 浏览器自动化（可选）

Playwright 包随 Nova 一起分发 —— `pip install -e .` 已经装上了。Nova 的浏览器工具会在
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
