#!/bin/bash
#
# write-image.sh - write a disk image (.img, .img.gz, .img.xz, .img.zst) onto a whole disk (SD card, eMMC, USB ...).
# Refuses the disk the system runs from and disks with mounted partitions; checks the size when it is known.
#
#   sudo IMAGE=/mnt/share/board.img.gz TARGET_DISK=/dev/sda ./write-image.sh
#   (asks for the disk name unless ASSUME_YES=yes; the web panel: HW Utils -> Clone / Image -> Write image)
#
# Progress: dd status=progress of the bytes read from the image file (compressed or not).
# WARNING: all data on the target disk is destroyed.

export PATH="/usr/local/sbin:/usr/sbin:/sbin:$PATH"
IMAGE="${IMAGE:-${1:-}}"
TARGET_DISK="${TARGET_DISK:-${2:-}}"
ASSUME_YES="${ASSUME_YES:-no}"
BS="${BS:-4M}"

set -euo pipefail
info() { echo "==> $*"; }
die()  { echo "ERROR: $*" >&2; exit 1; }
trap 'echo "stopped - the disk content is incomplete"; exit 143' TERM INT HUP

[[ $EUID -eq 0 ]] || die "run with sudo"
[[ -n $IMAGE && -n $TARGET_DISK ]] || die "usage: IMAGE=<file> TARGET_DISK=/dev/<disk> $0"
[[ -f $IMAGE ]] || die "image $IMAGE not found"
[[ -b $TARGET_DISK ]] || die "$TARGET_DISK is not a block device"
[[ $(lsblk -dno TYPE "$TARGET_DISK") == disk ]] || die "$TARGET_DISK is not a whole disk"

ROOT_PART=$(findmnt -n -o SOURCE /)
ROOT_PART=${ROOT_PART%%[*}
SOURCE_DISK="/dev/$(lsblk -no PKNAME "$ROOT_PART" | head -n1)"
[[ $TARGET_DISK != "$SOURCE_DISK" ]] || die "$TARGET_DISK is the disk the system runs from"
mounted=$(lsblk -lnpo NAME,MOUNTPOINT "$TARGET_DISK" | awk 'NF > 1 {print $1 " -> " $2}')
[[ -z $mounted ]] || die "partitions of $TARGET_DISK are mounted, unmount them first: $mounted"

case $IMAGE in
	*.gz)  dec=(gzip -dc) ;;
	*.xz)  dec=(xz -dc -T0) ;;
	*.zst) dec=(zstd -dc) ;;
	*)     dec=() ;;
esac
[[ ${#dec[@]} -eq 0 ]] || command -v "${dec[0]}" >/dev/null || die "${dec[0]} not installed"

file_bytes=$(stat -c %s "$IMAGE")
disk_bytes=$(blockdev --getsize64 "$TARGET_DISK")
img_bytes=""
case $IMAGE in
	*.gz|*.zst) ;;                                     # size inside not reliable (gzip: modulo 4 GiB)
	*.xz) img_bytes=$(xz --robot --list "$IMAGE" 2>/dev/null | awk '$1 == "totals" {print $5}') || true ;;
	*)    img_bytes=$file_bytes ;;
esac
info "Image: $IMAGE ($((file_bytes / 1048576)) MiB on disk${img_bytes:+, $((img_bytes / 1048576)) MiB to write})"
info "Target: $TARGET_DISK ($((disk_bytes / 1048576)) MiB) $(lsblk -dno TRAN,MODEL "$TARGET_DISK" | xargs)"
if [[ -n $img_bytes ]]; then
	((img_bytes <= disk_bytes)) || die "the image ($((img_bytes / 1048576)) MiB) is larger than $TARGET_DISK ($((disk_bytes / 1048576)) MiB)"
fi

if [[ $ASSUME_YES != yes ]]; then
	echo "ALL DATA ON $TARGET_DISK WILL BE DESTROYED!"
	read -rp "Type the device name to continue ($(basename "$TARGET_DISK")): " ans
	[[ $ans == "$(basename "$TARGET_DISK")" ]] || die "cancelled"
fi

info "Clearing old signatures"
wipefs -aq "$TARGET_DISK" || true
info "Writing (takes a few minutes)"
if [[ ${#dec[@]} -eq 0 ]]; then
	dd if="$IMAGE" of="$TARGET_DISK" bs="$BS" conv=fsync status=progress
else
	dd if="$IMAGE" bs="$BS" status=progress | "${dec[@]}" | dd of="$TARGET_DISK" bs="$BS" iflag=fullblock conv=fsync status=none
fi
sync
blockdev --rereadpt "$TARGET_DISK" 2>/dev/null || partprobe "$TARGET_DISK" 2>/dev/null || true
udevadm settle 2>/dev/null || true
echo
lsblk -o NAME,SIZE,FSTYPE,LABEL "$TARGET_DISK" || true
info "Done: image written to $TARGET_DISK"
