#!/usr/bin/env bash
# One-command setup for a Raspberry Pi. Safe to re-run.
#
#   git clone https://github.com/maartengerritse/wtp-scale.git ~/wtp-scale
#   ~/wtp-scale/pi/install.sh

set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Installing packages"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
  chromium-browser python3 python3-pip python3-tk python3-spidev python3-rpi.gpio \
  x11-xserver-utils curl git || \
sudo apt-get install -y --no-install-recommends \
  chromium python3 python3-pip python3-tk python3-spidev python3-rpi.gpio \
  x11-xserver-utils curl git

echo "==> Installing the RFID library"
pip3 install --break-system-packages mfrc522 2>/dev/null || pip3 install mfrc522

echo "==> Enabling SPI (needed by the MFRC522 reader)"
if command -v raspi-config >/dev/null 2>&1; then
  sudo raspi-config nonint do_spi 0
fi

echo "==> Installing services"
mkdir -p "$HOME/.config/systemd/user"
sed "s#%h#$HOME#g" "$REPO/pi/wtp-kiosk.service"   > "$HOME/.config/systemd/user/wtp-kiosk.service"
sed "s#%h#$HOME#g" "$REPO/pi/wtp-browser.service" > "$HOME/.config/systemd/user/wtp-browser.service"
chmod +x "$REPO/pi/kiosk.sh" "$REPO/pi/update.sh" "$REPO/pi/updater.py"

systemctl --user daemon-reload
systemctl --user enable wtp-kiosk.service wtp-browser.service

# Keep the services alive when nobody is logged in on the console.
sudo loginctl enable-linger "$USER" || true

echo "==> Adding the desktop app"
mkdir -p "$HOME/Desktop" "$HOME/.local/share/applications"
cat > "$HOME/Desktop/WTP-Scale.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=WTP Scale
Comment=Update and restart the kiosk
Exec=python3 $REPO/pi/updater.py
Icon=$REPO/assets/img/logo-colour.svg
Terminal=false
Categories=Utility;
DESKTOP
chmod +x "$HOME/Desktop/WTP-Scale.desktop"
cp "$HOME/Desktop/WTP-Scale.desktop" "$HOME/.local/share/applications/" || true
# Pi OS asks to confirm unknown launchers unless they are marked trusted.
gio set "$HOME/Desktop/WTP-Scale.desktop" metadata::trusted true 2>/dev/null || true

echo "==> Checking the data"
python3 "$REPO/tools/validate.py" || true

echo "==> Starting"
systemctl --user restart wtp-kiosk.service wtp-browser.service

cat <<DONE

Done.

  The kiosk starts automatically on boot.
  A "WTP Scale" icon on the desktop updates and restarts it.

  Logs:     journalctl --user -u wtp-kiosk -f
  Restart:  systemctl --user restart wtp-kiosk wtp-browser
DONE
