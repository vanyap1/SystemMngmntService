# USB camera streaming

Stream an H.264 USB camera to the local network, started automatically by udev when the camera is plugged in.

Files: [stream_camera.sh](../docs/stream_camera.sh) [camera-stream@.service](../docs/camera-stream@.service)

## 1. Tools and camera formats

```bash
sudo apt update
sudo apt install v4l-utils ffmpeg vlc
v4l2-ctl --device=/dev/video1 --list-formats-ext
```

The camera must offer `H264` to use `-c copy` (no re-encoding, almost no CPU).

## 2. Stream script

`/usr/local/bin/stream_camera.sh` (`sudo chmod +x`):

```bash
#!/bin/bash
CAM_DEVICE="$1"
TARGET="udp://192.168.1.255:12341?broadcast=1&pkt_size=1316"   # broadcast
# TARGET="udp://239.0.0.1:1234"                                # or multicast
LOGFILE="/var/log/camera_stream.log"

echo "$(date) Starting stream for $CAM_DEVICE" >> "$LOGFILE"
sleep 2
ffmpeg -f v4l2 -input_format h264 -video_size 1920x1080 -framerate 30 \
       -i "$CAM_DEVICE" -c copy -f mpegts "$TARGET" >> "$LOGFILE" 2>&1
```

## 3. systemd template unit

`/etc/systemd/system/camera-stream@.service` — one file for any `/dev/videoN` (`%i` = `video1`…):

```ini
[Unit]
Description=Camera stream for %i
BindsTo=dev-%i.device
After=dev-%i.device

[Service]
Type=simple
ExecStart=/usr/local/bin/stream_camera.sh /dev/%i
Restart=always

[Install]
WantedBy=multi-user.target
```

`BindsTo=` stops the stream when the camera is unplugged.

## 4. udev rule — start on plug-in

Find the camera IDs: `udevadm info -a -n /dev/video1 | grep -E "idVendor|idProduct"`.

`/etc/udev/rules.d/99-camera.rules`:

```bash
KERNEL=="video[0-9]*", SUBSYSTEM=="video4linux", ATTRS{idVendor}=="0ac8", ATTRS{idProduct}=="3420", TAG+="systemd", ENV{SYSTEMD_WANTS}="camera-stream@%k.service"
```

```bash
sudo udevadm control --reload
sudo udevadm trigger
systemctl status camera-stream@video1.service
journalctl -u camera-stream@video1.service -f
```

## 5. Watch

VLC → *Media → Open Network Stream*:

| Stream | URL |
|---|---|
| broadcast | `udp://@:12341` |
| multicast | `udp://@239.0.0.1:1234` |
| RTSP (below) | `rtsp://192.168.1.11:8554/` |

> [!TIP]
> Lower latency: VLC → *Show more options* → network caching 50–100 ms; or `ffplay -fflags nobuffer udp://@:12341`.

## Alternative: RTSP with VLC

```bash
cvlc v4l2:///dev/video1 --sout '#rtp{sdp=rtsp://:8554/}' :input-slave=alsa://
```

> [!NOTE]
> For a camera without H.264 (MJPEG/YUYV) on Rockchip use the hardware encoder: `-c:v h264_rkmpp` instead of `-c copy`.
