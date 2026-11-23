#!/usr/bin/env bash
# Builds the Disc Image Studio CLI from this repository with the .NET 10 SDK and installs the Linux GUI.
# Usage:  ./linux-gui/install.sh        (from a clone of the repository)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/.." && pwd)"
dest="${DISCSTUDIO_PREFIX:-$HOME/.local/share/disc-image-studio}"
if [ ! -d "$repo/src/DiscImageStudio.Cli" ]; then
  echo "src/DiscImageStudio.Cli not found next to linux-gui/. Run this from a clone of the repository." >&2
  exit 1
fi
command -v dotnet >/dev/null || { echo "the .NET 10 SDK is required (pacman -S dotnet-sdk)"; exit 1; }
python3 -c "import PyQt6, numpy" 2>/dev/null || { echo "needs PyQt6 and numpy (pacman -S python-pyqt6 python-numpy)"; exit 1; }
dotnet publish "$repo/src/DiscImageStudio.Cli" -c Release -o "$dest/cli" -p:UseAppHost=true
rm -rf "$dest/app"; mkdir -p "$dest/app" "$HOME/.local/bin" "$HOME/.local/share/applications"
cp -r "$here/discstudio" "$dest/app/"
find "$dest/app" -name __pycache__ -prune -exec rm -rf {} +
cat > "$HOME/.local/bin/disc-image-studio-gui" <<L
#!/usr/bin/env bash
cd "$dest/app" && exec python3 -m discstudio "\$@"
L
chmod +x "$HOME/.local/bin/disc-image-studio-gui"
cat > "$HOME/.local/share/applications/disc-image-studio.desktop" <<D
[Desktop Entry]
Type=Application
Name=Disc Image Studio
Comment=Draw pictures on blank CDs, DVDs and Blu-rays
Exec=$HOME/.local/bin/disc-image-studio-gui
Icon=$dest/app/discstudio/assets/logo.png
Categories=AudioVideo;DiscBurning;
D
echo "Installed. Run: disc-image-studio-gui"
