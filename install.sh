#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.local/share/media2mqtt"
PLIST_NAME="com.media2mqtt"
PLIST_DST="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$INSTALL_DIR/.env"

echo "==> Installing media2mqtt to $INSTALL_DIR"

mkdir -p "$INSTALL_DIR"
cp "$SCRIPT_DIR"/main.py "$SCRIPT_DIR"/media_apps.py "$SCRIPT_DIR"/mqtt_publisher.py "$SCRIPT_DIR"/requirements.txt "$INSTALL_DIR/"

if [ ! -d "$INSTALL_DIR/venv" ]; then
    echo "==> Creating virtualenv"
    python3 -m venv "$INSTALL_DIR/venv"
fi

echo "==> Installing dependencies"
"$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

if [ ! -f "$ENV_FILE" ]; then
    echo "==> Creating .env file — edit this with your MQTT settings"
    cat > "$ENV_FILE" <<'EOF'
MQTT_HOST=
MQTT_PORT=1883
MQTT_USERNAME=
MQTT_PASSWORD=
MQTT_DISCOVERY_PREFIX=homeassistant
MQTT_TOPIC_PREFIX=media2mqtt
DEVICE_NAME=
ENABLED_APPS=music
POLL_INTERVAL_SECONDS=1
EOF
    echo "    $ENV_FILE"
    echo "    Fill in at least MQTT_HOST, then re-run this script."
    exit 0
fi

source "$ENV_FILE"
if [ -z "${MQTT_HOST:-}" ]; then
    echo "ERROR: MQTT_HOST is not set in $ENV_FILE"
    exit 1
fi

echo "==> Generating launchd plist"

PLIST_CONTENT=$(cat "$SCRIPT_DIR/com.media2mqtt.plist")

# Build EnvironmentVariables XML from .env
ENV_XML="<key>EnvironmentVariables</key>\n    <dict>"
while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" == \#* ]] && continue
    [ -n "$value" ] && ENV_XML="$ENV_XML\n        <key>$key</key>\n        <string>$value</string>"
done < "$ENV_FILE"
ENV_XML="$ENV_XML\n    </dict>"

VENV_PYTHON="$INSTALL_DIR/venv/bin/python"

# Start from a clean plist template and substitute
cat > "$PLIST_DST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.media2mqtt</string>
    <key>ProgramArguments</key>
    <array>
        <string>${VENV_PYTHON}</string>
        <string>${INSTALL_DIR}/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${INSTALL_DIR}</string>
    $(echo -e "$ENV_XML")
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${INSTALL_DIR}/media2mqtt.log</string>
    <key>StandardErrorPath</key>
    <string>${INSTALL_DIR}/media2mqtt.log</string>
</dict>
</plist>
PLIST

echo "==> Plist written to $PLIST_DST"
echo ""
echo "To start the service:"
echo "    launchctl load $PLIST_DST"
echo ""
echo "To check status:"
echo "    launchctl list | grep media2mqtt"
echo ""
echo "Logs: $INSTALL_DIR/media2mqtt.log"
