#!/bin/bash
#/usr/local/bin/stream_camera.sh


CAM_DEVICE="$1"
MULTICAST="udp://192.168.1.255:12341?broadcast=1&pkt_size=1316"
LOGFILE="/var/log/camera_stream.log"

echo "$(date) Starting stream for $CAM_DEVICE" >> "$LOGFILE"

sleep 2

ffmpeg -f v4l2 -input_format h264 -video_size 1920x1080 -framerate 30 \
-i "$CAM_DEVICE" -c copy -f mpegts "$MULTICAST" >> "$LOGFILE" 2>&1

ffmpeg -f v4l2 -input_format h264 -video_size 1920x1080 -framerate 30 -\
i "$CAM_DEVICE" -c copy -f mpegts "udp://239.0.0.1:1234" 

ffmpeg -f v4l2 -input_format h264 -video_size 1920x1080 -framerate 30 \
-i /dev/video2 -c copy -f mpegts "$MULTICAST" >> "$LOGFILE" 2>&1
