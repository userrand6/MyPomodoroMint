FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-gi \
        python3-gi-cairo \
        gir1.2-gtk-3.0 \
        gir1.2-xapp-1.0 \
        gir1.2-ayatanaappindicator3-0.1 \
        libcanberra-gtk3-module \
        gnome-session-canberra \
        pulseaudio-utils \
        sound-theme-freedesktop \
        xvfb \
        dbus-x11 \
        make \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
