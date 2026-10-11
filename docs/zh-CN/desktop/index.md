# 桌面应用

Nova 可以打包成 macOS、Windows 和 Linux 上的原生桌面应用。

## 构建

```bash
python build.py --clean
```

这会构建前端资源，并用 PyInstaller 打包全部内容。

产物：
- **macOS**：`dist/Nova.app`
- **Windows**：`dist/Nova.exe`
- **Linux**：`dist/Nova`

## 开发模式

开发前端期间，可以让桌面应用连 Vite 开发服务器：

```bash
nova desktop --dev
```

## 不打包直接运行

桌面应用也可以直接从源码树里跑：

```bash
cd frontend
npm run build
cd ..
NOVA_FRONTEND_DIST=frontend/dist nova desktop
```
