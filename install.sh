#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/share/mypomodoro-mint"
BIN_DIR="$PREFIX/bin"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

mkdir -p "$APP_DIR" "$BIN_DIR" "$DESKTOP_DIR"
cp -R mypomodoro_mint "$APP_DIR/"
install -m 755 mypomodoro "$APP_DIR/mypomodoro"
ln -sf "$APP_DIR/mypomodoro" "$BIN_DIR/mypomodoro"

cat > "$DESKTOP_DIR/mypomodoro.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=MyPomodoro
Comment=Lightweight Linux Mint Pomodoro tray timer
Exec=$BIN_DIR/mypomodoro
Icon=alarm-symbolic
Terminal=false
Categories=Utility;Clock;
EOF

echo "Installed MyPomodoroMint to $BIN_DIR/mypomodoro"
echo "Run 'mypomodoro &' or launch 'MyPomodoro' from your application menu."
