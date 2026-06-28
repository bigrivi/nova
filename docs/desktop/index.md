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

## License Activation

The packaged desktop app requires a license file (`license.lic`).

On first launch, the app shows a machine fingerprint. Send this fingerprint to
get a license file, then select it in the activation dialog.

### Generating Licenses

```bash
python tools/gen_license.py \
    --fingerprint "FINGERPRINT_FROM_USER" \
    --expires "2027-06-21" \
    --user "user@example.com" \
    -o license.lic
```

### Source Code Obfuscation

```bash
pip install pyarmor
python build.py --clean --obfuscate
```

## Running Without Packaging

The desktop app can also run from the source tree:

```bash
cd frontend
npm run build
cd ..
NOVA_FRONTEND_DIST=frontend/dist python -m nova desktop
```
