ARG VSS_RTCV_IMAGE=nvcr.io/nvidia/vss-core/vss-rt-cv:3.2.1@sha256:1a8b9879686f21cb6b9589d6139b5ac2eb960f1520aa3b4bb5f079d05fee9458
FROM ${VSS_RTCV_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive

USER root

RUN apt-get update \
    && apt-get install --reinstall -y --no-install-recommends \
        gstreamer1.0-libav \
        gstreamer1.0-plugins-ugly \
        libmp3lame0 \
        libmpg123-0 \
        libvpx9 \
        libx264-164 \
        libx265-199 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER triton-server
