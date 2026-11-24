#!/bin/sh
O=/data/options.json
HOST=$(jq -r .console_host "$O")
KEY=$(jq -r .api_key "$O")
CAM=$(jq -r .camera_id "$O")
ALIAS=$(jq -r .rtsp_alias "$O")
NAME=$(jq -r .stream_name "$O")

if [ -z "$HOST" ] || [ -z "$KEY" ] || [ -z "$CAM" ]; then
  echo "Set console_host, api_key and camera_id in the add-on configuration first."
  exit 1
fi

{
cat <<YAML
api:
  listen: ":1984"
rtsp:
  listen: ":8554"
webrtc:
  listen: ":8555"
streams:
  ${NAME}:
YAML
if [ -n "$ALIAS" ] && [ "$ALIAS" != "null" ]; then
cat <<YAML
    - 'rtspx://${HOST}:7441/${ALIAS}#backchannel=0'
    - 'ffmpeg:${NAME}#audio=opus'
YAML
fi
cat <<YAML
    - 'unifi-talkback:https://${HOST}?camera_id=${CAM}&api_key=${KEY}'
YAML
} > /tmp/go2rtc.yaml

exec go2rtc -config /tmp/go2rtc.yaml
