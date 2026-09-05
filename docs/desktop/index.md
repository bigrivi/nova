# Desktop App

Nova can be packaged as a native desktop application for macOS, Windows, and
Linux.

## Building

```bash
python build.py --clean
```

This builds the frontend assets and packages everything with PyInstaller.

Output:
- **macOS**: `dist/Nova.app`
- **Windows**: `dist/Nova.exe`
- **Linux**: `dist/Nova`

## Development Mode

During frontend development, run the desktop app against the Vite dev server:

```bash
python -m nova desktop --dev
```

## Running Without Packaging

The desktop app can also run from the source tree:

```bash
cd frontend
npm run build
cd ..
NOVA_FRONTEND_DIST=frontend/dist python -m nova desktop
```
