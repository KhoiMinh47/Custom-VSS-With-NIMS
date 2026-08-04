ARG VSS_MEDIA_IMAGE=nvcr.io/nvidia/vss-core/vss-vios-nvstreamer:3.2.1@sha256:7074784d32f996734ef091405f14965573d40257d843bba29d7ca2ef36f58e4d
FROM ${VSS_MEDIA_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive

USER root

RUN apt-get update \
    && apt-get install --reinstall -y --no-install-recommends \
        gstreamer1.0-libav \
        gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-bad \
        gstreamer1.0-plugins-ugly \
        gstreamer1.0-tools \
        libavcodec-dev \
        libavcodec60 \
        libavfilter-dev \
        libavfilter9 \
        libavformat-dev \
        libavformat60 \
        libavutil-dev \
        libavutil58 \
        libswresample-dev \
        libswresample4 \
        liba52-0.7.4 \
        libbs2b0 \
        libcdio19 \
        libdca0 \
        libdvdnav4 \
        libdvdread8 \
        libflac12 \
        liblrdf0 \
        libmjpegutils-2.1-0 \
        libmp3lame0 \
        libmpg123-0 \
        libneon27 \
        libreadline8 \
        libsbc1 \
        libsidplay1v5 \
        libvo-aacenc0 \
        libvpx9 \
        libx264-164 \
        libx265-199 \
        libxvidcore4 \
        libzvbi0 \
    && ldconfig \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER 1000:1000
