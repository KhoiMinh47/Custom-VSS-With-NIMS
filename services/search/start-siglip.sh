#!/usr/bin/env bash
set -euo pipefail

app=/opt/nvidia/deepstream/deepstream/sources/apps/sample_apps/metropolis_perception_app
mkdir -p "$app/configs"
cp -a /opt/ntc/search-config/. "$app/configs/"
cp -a /opt/ntc/base-deepstream/ds-pgie-config.yml "$app/configs/"
cp -a /opt/ntc/base-deepstream/ds-detector-labels.txt "$app/configs/"
cp -a /opt/ntc/base-deepstream/ds-kafka-config.txt "$app/configs/"
export GST_PLUGIN_PATH="/opt/nvidia/deepstream/deepstream/lib/gst-plugins:/usr/lib/x86_64-linux-gnu/gstreamer-1.0/deepstream:/opt/nvidia/deepstream/deepstream/sources/gst-plugins/gst-nvdstextembedder"
cd "$app"
exec bash "$app/ds-start.sh"
