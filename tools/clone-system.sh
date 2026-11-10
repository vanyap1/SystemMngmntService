#!/bin/bash
#
# clone-system.sh - copy the running Armbian system onto another disk (eMMC, SD card, USB ...) or into a
# bootable .img file. Files are copied (rsync), not a disk image, so the target may be smaller than the source:
# the partition gets the size of the used data + reserve + EXTRA_MB (or the whole disk).
#
#   1. finds the disks, the target is chosen (any disk except the one the system runs from)
#   2. checks that the data fits
#   3. creates the partition table (MBR, 1 partition from the same sector as the running root partition)
#   4. formats it, copies the system (incl. /var/log under zram, /boot)
#   5. writes the new UUID into /etc/fstab and /boot/armbianEnv.txt
#   6. writes u-boot with Armbian's write_uboot_platform (sunxi, rockchip, ...)
#
# Interactive:     sudo ./clone-system.sh
# Unattended:      sudo TARGET_DISK=/dev/mmcblk1 EXTRA_MB=1024 ASSUME_YES=yes ./clone-system.sh
# Image file:      sudo IMAGE_FILE=/mnt/share/board.img EXTRA_MB=1024 COMPRESS=gz ./clone-system.sh
#                  (sparse file on a loop device; written as <file>.partial and renamed at the end)
# The web panel (HW Utils -> Clone / Image, core/sysclone.py) runs it with ASSUME_YES=yes NO_COLOR=1.
#
# WARNING: all data on the target disk is destroyed.

[[ -n ${CONFIG_FILE:-} && -f $CONFIG_FILE ]] && source "$CONFIG_FILE"
export PATH="/usr/local/sbin:/usr/sbin:/sbin:$PATH"

# ======================= SETTINGS (environment overrides) =======================
SOURCE_DISK="${SOURCE_DISK:-}"            # empty = the disk "/" is on
TARGET_DISK="${TARGET_DISK:-}"            # e.g. /dev/mmcblk1; empty = choose from a list (or IMAGE_FILE)
IMAGE_FILE="${IMAGE_FILE:-}"              # build a bootable image file instead of writing a disk
COMPRESS="${COMPRESS:-}"                  # image only: "gz" = <file>.gz (the raw .img is removed)
TARGET_SIZE_MB="${TARGET_SIZE_MB:-}"      # partition size in MiB, "max" = whole disk; empty = minimum + EXTRA_MB or ask
EXTRA_MB="${EXTRA_MB:-}"                  # partition = minimum for the data + this many MiB
PART_START_SECTOR="${PART_START_SECTOR:-}"   # empty = same as the running root partition (u-boot lives before it)
FS_TYPE="${FS_TYPE:-ext4}"
FS_LABEL="${FS_LABEL:-armbi_root}"
MKFS_OPTS="${MKFS_OPTS:--m 2}"
UBOOT_BIN="${UBOOT_BIN:-}"                # empty = Armbian write_uboot_platform, else a sunxi u-boot-with-spl.bin
WRITE_UBOOT="${WRITE_UBOOT:-yes}"
GROW_ON_BOOT="${GROW_ON_BOOT:-no}"        # yes = the copy grows its partition to the whole medium at the first boot
RESERVE_MB="${RESERVE_MB:-300}"           # free space kept in the minimum size
FLUSH_RAMLOG="${FLUSH_RAMLOG:-yes}"       # write the zram logs to disk before copying
ASSUME_YES="${ASSUME_YES:-no}"            # no confirmation question (dangerous)
SRC_MNT="${SRC_MNT:-/mnt/clone-src}"
DST_MNT="${DST_MNT:-/mnt/clone-dst}"
EXCLUDES=("/lost+found" "/swapfile" "/var/swap" "/var/cache/apt/archives/*.deb")
# ================================================================================

set -euo pipefail

if [[ -n ${NO_COLOR:-} ]]; then
	red()   { echo "$*"; }; green() { echo "$*"; }
else
	red()   { echo -e "\e[31m$*\e[0m"; }; green() { echo -e "\e[32m$*\e[0m"; }
fi
info()  { echo "==> $*"; }
die()   { echo "ERROR: $*" >&2; exit 1; }
uboot_version() { (set +o pipefail; strings "$1" 2>/dev/null | grep -m1 -E 'U-Boot (SPL|TPL|20)' || echo '?'); }

[[ $EUID -eq 0 ]] || die "run with sudo"
for cmd in rsync sfdisk wipefs blkid lsblk findmnt blockdev "mkfs.$FS_TYPE" udevadm; do
	command -v "$cmd" >/dev/null || die "command '$cmd' not found (apt install rsync fdisk e2fsprogs)"
done
[[ -z $IMAGE_FILE ]] || command -v losetup >/dev/null || die "command 'losetup' not found (apt install mount)"

LOOP_DEV=""
IMAGE_TMP=""
DONE=no
cleanup() {
	set +e
	sync
	mountpoint -q "$DST_MNT/boot" 2>/dev/null && umount "$DST_MNT/boot"
	mountpoint -q "$DST_MNT" && umount "$DST_MNT"
	mountpoint -q "$SRC_MNT/boot" 2>/dev/null && umount "$SRC_MNT/boot"
	mountpoint -q "$SRC_MNT" && umount "$SRC_MNT"
	rmdir "$SRC_MNT" "$DST_MNT" 2>/dev/null
	[[ -n $LOOP_DEV ]] && losetup -d "$LOOP_DEV" 2>/dev/null
	if [[ $DONE != yes && -n $IMAGE_TMP && -f $IMAGE_TMP ]]; then
		echo "removing the unfinished image $IMAGE_TMP"
		rm -f "$IMAGE_TMP"
	fi
}
trap cleanup EXIT
trap 'echo "stopped"; exit 143' TERM INT HUP

# ---------- source ----------
ROOT_PART=$(findmnt -n -o SOURCE /)
ROOT_PART=${ROOT_PART%%[*}
[[ -n $SOURCE_DISK ]] || SOURCE_DISK="/dev/$(lsblk -no PKNAME "$ROOT_PART" | head -n1)"
[[ -b $SOURCE_DISK ]] || die "source $SOURCE_DISK not found"
BOOT_PART=""
if findmnt -n /boot >/dev/null 2>&1; then BOOT_PART=$(findmnt -n -o SOURCE /boot); fi
[[ $BOOT_PART == "$ROOT_PART" ]] && BOOT_PART=""
OLD_UUID=$(blkid -s UUID -o value "$ROOT_PART")
OLD_PARTUUID=$(blkid -s PARTUUID -o value "$ROOT_PART" || true)
info "System runs from $ROOT_PART (disk $SOURCE_DISK, UUID=$OLD_UUID)"
[[ -n $BOOT_PART ]] && info "System has a separate /boot: $BOOT_PART"
if [[ -z $PART_START_SECTOR ]]; then
	PART_START_SECTOR=$(cat "/sys/class/block/$(basename "$ROOT_PART")/start" 2>/dev/null || echo 8192)
	((PART_START_SECTOR >= 8192)) || PART_START_SECTOR=8192
fi
info "Partition starts at sector $PART_START_SECTOR ($((PART_START_SECTOR / 2048)) MiB, as on the running system)"

# ---------- size of the data ----------
MB=$((1024 * 1024))
used_bytes=$(df -B1 --output=used / | tail -n1)
if [[ -n $BOOT_PART ]]; then used_bytes=$((used_bytes + $(df -B1 --output=used /boot | tail -n1))); fi
min_part_mb=$(( (used_bytes / MB + RESERVE_MB) * 100 / 95 + 1 ))   # data + reserve + ~5 % ext4 metadata
info "System uses $((used_bytes / MB)) MiB; minimal partition $min_part_mb MiB"

# ---------- target ----------
list_candidates() {
	lsblk -dpno NAME,TYPE | awk '$2=="disk"{print $1}' |
		grep -Ev '/dev/(loop|zram|ram|mtdblock)|boot[0-9]+$|rpmb$' | grep -vx "$SOURCE_DISK" || true
}
if [[ -n $IMAGE_FILE ]]; then
	[[ -z $TARGET_DISK ]] || die "TARGET_DISK and IMAGE_FILE are exclusive"
	[[ $TARGET_SIZE_MB != max ]] || die "an image has no 'whole disk' size; use EXTRA_MB"
	[[ -d $(dirname "$IMAGE_FILE") ]] || die "folder $(dirname "$IMAGE_FILE") not found"
	[[ ! -e $IMAGE_FILE && ! -e $IMAGE_FILE.gz ]] || die "$IMAGE_FILE already exists"
elif [[ -z $TARGET_DISK ]]; then
	mapfile -t CANDIDATES < <(list_candidates)
	[[ ${#CANDIDATES[@]} -gt 0 ]] || die "no other disk found"
	echo; echo "Disks:"
	i=1
	for d in "${CANDIDATES[@]}"; do
		printf "  [%d] %-14s %8s  %s %s\n" "$i" "$d" "$(lsblk -dno SIZE "$d" | xargs)" \
			"$(lsblk -dno TRAN "$d" 2>/dev/null | xargs)" "$(lsblk -dno MODEL "$d" 2>/dev/null | xargs)"
		lsblk -lno NAME,SIZE,FSTYPE,LABEL "$d" | tail -n +2 | sed 's/^/        /'
		i=$((i + 1))
	done
	echo
	read -rp "Number of the disk to copy the system to: " n
	[[ $n =~ ^[0-9]+$ ]] && ((n >= 1 && n <= ${#CANDIDATES[@]})) || die "invalid choice"
	TARGET_DISK=${CANDIDATES[$((n - 1))]}
fi
if [[ -z $IMAGE_FILE ]]; then
	[[ -b $TARGET_DISK ]] || die "$TARGET_DISK is not a block device"
	[[ $TARGET_DISK != "$SOURCE_DISK" ]] || die "target is the source disk"
	lsblk -lnpo NAME "$TARGET_DISK" | grep -qx "$ROOT_PART" && die "$TARGET_DISK carries the running root filesystem"
	[[ -z $BOOT_PART ]] || ! lsblk -lnpo NAME "$TARGET_DISK" | grep -qx "$BOOT_PART" || die "$TARGET_DISK carries the running /boot"
fi

# ---------- size of the partition ----------
if [[ -n $IMAGE_FILE ]]; then
	max_part_mb=$((min_part_mb + 1024 * 1024))     # an image only has to hold the data
else
	target_bytes=$(blockdev --getsize64 "$TARGET_DISK")
	max_part_mb=$(( (target_bytes - PART_START_SECTOR * 512) / MB - 1 ))
	info "Target $TARGET_DISK: $((target_bytes / MB)) MiB (partition at most $max_part_mb MiB)"
	((min_part_mb <= max_part_mb)) || die "the system does not fit on $TARGET_DISK"
fi

if [[ $TARGET_SIZE_MB == max ]]; then
	TARGET_SIZE_MB=$max_part_mb
elif [[ -z $TARGET_SIZE_MB && -n $EXTRA_MB ]]; then
	[[ $EXTRA_MB =~ ^[0-9]+$ ]] || die "EXTRA_MB must be a number: '$EXTRA_MB'"
	TARGET_SIZE_MB=$((min_part_mb + EXTRA_MB))
	((TARGET_SIZE_MB <= max_part_mb)) || die "minimum $min_part_mb + extra $EXTRA_MB = $TARGET_SIZE_MB MiB, the disk holds $max_part_mb MiB"
elif [[ -z $TARGET_SIZE_MB ]]; then
	read -rp "Partition size in MiB [$min_part_mb..$max_part_mb, Enter = $max_part_mb]: " TARGET_SIZE_MB
	TARGET_SIZE_MB=${TARGET_SIZE_MB:-$max_part_mb}
fi
[[ $TARGET_SIZE_MB =~ ^[0-9]+$ ]] || die "size must be a number of MiB: '$TARGET_SIZE_MB'"
((TARGET_SIZE_MB <= max_part_mb)) || die "$TARGET_SIZE_MB MiB is larger than the disk (max $max_part_mb MiB)"
((TARGET_SIZE_MB >= min_part_mb)) || die "$TARGET_SIZE_MB MiB is too small, the system needs $min_part_mb MiB"
PART_SECTORS=$((TARGET_SIZE_MB * MB / 512))
info "Partition: $TARGET_SIZE_MB MiB"

# ---------- u-boot ----------
UBOOT_PLATFORM=/usr/lib/u-boot/platform_install.sh
if [[ $WRITE_UBOOT == yes ]]; then
	if [[ -z $UBOOT_BIN && -f $UBOOT_PLATFORM ]]; then
		info "u-boot: Armbian $UBOOT_PLATFORM ($(head -n1 "$UBOOT_PLATFORM" | sed 's/^# *//'))"
	else
		[[ -n $UBOOT_BIN ]] || UBOOT_BIN=$(ls /usr/lib/linux-u-boot-*/u-boot-sunxi-with-spl.bin 2>/dev/null | head -n1 || true)
		[[ -f $UBOOT_BIN ]] || die "u-boot not found (no $UBOOT_PLATFORM, UBOOT_BIN='$UBOOT_BIN')"
		info "u-boot: $UBOOT_BIN ($(uboot_version "$UBOOT_BIN"))"
	fi
fi

# ---------- image file ----------
if [[ -n $IMAGE_FILE ]]; then
	IMAGE_TMP="$IMAGE_FILE.partial"
	rm -f "$IMAGE_TMP"
	image_bytes=$(( (PART_START_SECTOR + PART_SECTORS) * 512 + MB ))
	info "Creating the image $IMAGE_FILE ($((image_bytes / MB)) MiB, sparse)"
	truncate -s "$image_bytes" "$IMAGE_TMP"
	LOOP_DEV=$(losetup -fP --show "$IMAGE_TMP")
	TARGET_DISK=$LOOP_DEV
	info "Loop device: $LOOP_DEV"
fi

# ---------- confirmation ----------
echo "Will create: $TARGET_DISK -> 1 partition $FS_TYPE, $TARGET_SIZE_MB MiB, from sector $PART_START_SECTOR"
if [[ -z $IMAGE_FILE ]]; then
	red "ALL DATA ON $TARGET_DISK ($(lsblk -dno SIZE "$TARGET_DISK" | xargs)) WILL BE DESTROYED!"
	if [[ $ASSUME_YES != yes ]]; then
		read -rp "Type the device name to continue ($(basename "$TARGET_DISK")): " ans
		[[ $ans == "$(basename "$TARGET_DISK")" ]] || die "cancelled"
	fi
fi

# ---------- partitions ----------
info "Partitioning $TARGET_DISK"
for p in $(lsblk -lnpo NAME "$TARGET_DISK" | tail -n +2); do
	umount -q "$p" 2>/dev/null || true
	swapoff "$p" 2>/dev/null || true
done
wipefs -aq "$TARGET_DISK"
dd if=/dev/zero of="$TARGET_DISK" bs=1M count=$(( (PART_START_SECTOR * 512) / MB + 1 )) conv=fsync status=none
sfdisk -q "$TARGET_DISK" <<END_SFDISK || true
label: dos
start=${PART_START_SECTOR}, size=${PART_SECTORS}, type=83, bootable
END_SFDISK
blockdev --rereadpt "$TARGET_DISK" 2>/dev/null || partprobe "$TARGET_DISK" 2>/dev/null || true
[[ -z $LOOP_DEV ]] || partx -u "$LOOP_DEV" 2>/dev/null || true
udevadm settle
TARGET_PART=$(lsblk -lnpo NAME,TYPE "$TARGET_DISK" | awk '$2=="part"{print $1; exit}')
[[ -b ${TARGET_PART:-} ]] || die "no partition appeared on $TARGET_DISK"

info "Formatting $TARGET_PART ($FS_TYPE)"
# shellcheck disable=SC2086
"mkfs.$FS_TYPE" -F -q -L "$FS_LABEL" $MKFS_OPTS "$TARGET_PART"
udevadm settle
NEW_UUID=$(blkid -p -s UUID -o value "$TARGET_PART")
NEW_PARTUUID=$(blkid -s PARTUUID -o value "$TARGET_PART" || true)
info "New UUID: $NEW_UUID"

# ---------- copy ----------
if [[ $FLUSH_RAMLOG == yes && -x /usr/lib/armbian/armbian-ramlog ]]; then
	info "Flushing the zram logs to disk"
	/usr/lib/armbian/armbian-ramlog write >/dev/null 2>&1 || true
fi
mkdir -p "$SRC_MNT" "$DST_MNT"
mount --bind / "$SRC_MNT"                 # the plain root filesystem, without zram / tmpfs / proc / shares on top
mount -o ro,remount,bind "$SRC_MNT" 2>/dev/null || true
if [[ -n $BOOT_PART ]]; then mount --bind /boot "$SRC_MNT/boot"; fi
mount "$TARGET_PART" "$DST_MNT"
RSYNC_EXCL=()
for e in "${EXCLUDES[@]}"; do RSYNC_EXCL+=(--exclude="$e"); done

info "Copying the system (takes a few minutes)"
rc=0
rsync -aAXH --numeric-ids --info=progress2 --no-inc-recursive "${RSYNC_EXCL[@]}" "$SRC_MNT"/ "$DST_MNT"/ || rc=$?
# 24 = some files vanished during the copy (normal on a running system)
((rc == 0 || rc == 24)) || die "rsync failed (exit $rc)"
((rc == 24)) && echo "note: some files vanished during the copy (rsync 24) - ignored"

# ---------- configuration of the copy ----------
info "Updating /etc/fstab and /boot/armbianEnv.txt"
FSTAB="$DST_MNT/etc/fstab"
if [[ -f $FSTAB ]]; then
	cp -a "$FSTAB" "$FSTAB.clone-bak"
	sed -i "s|UUID=$OLD_UUID|UUID=$NEW_UUID|g" "$FSTAB"
	if [[ -n $OLD_PARTUUID && -n $NEW_PARTUUID ]]; then sed -i "s|PARTUUID=$OLD_PARTUUID|PARTUUID=$NEW_PARTUUID|g" "$FSTAB"; fi
	sed -i "s|^$ROOT_PART[[:space:]]|UUID=$NEW_UUID\t|" "$FSTAB"
	if [[ -n $BOOT_PART ]]; then sed -i -E '/[[:space:]]\/boot[[:space:]]/s/^/#clone# /' "$FSTAB"; fi
	grep -q "[[:space:]]/[[:space:]]" "$FSTAB" ||
		printf "UUID=%s\t/\t%s\tdefaults,noatime,commit=600,errors=remount-ro\t0 1\n" "$NEW_UUID" "$FS_TYPE" >>"$FSTAB"
fi
ENV="$DST_MNT/boot/armbianEnv.txt"
if [[ -f $ENV ]]; then
	cp -a "$ENV" "$ENV.clone-bak"
	if grep -q '^rootdev=' "$ENV"; then sed -i "s|^rootdev=.*|rootdev=UUID=$NEW_UUID|" "$ENV"; else echo "rootdev=UUID=$NEW_UUID" >>"$ENV"; fi
	if grep -q '^rootfstype=' "$ENV"; then sed -i "s|^rootfstype=.*|rootfstype=$FS_TYPE|" "$ENV"; else echo "rootfstype=$FS_TYPE" >>"$ENV"; fi
else
	red "warning: $ENV not found - check the boot configuration manually"
fi
if [[ -f $DST_MNT/boot/boot.cmd && ! -f $DST_MNT/boot/boot.scr ]] && command -v mkimage >/dev/null; then
	mkimage -C none -A arm -T script -d "$DST_MNT/boot/boot.cmd" "$DST_MNT/boot/boot.scr" >/dev/null
fi
[[ -f $DST_MNT/boot/boot.scr ]] || red "warning: no /boot/boot.scr on the target"
if [[ $GROW_ON_BOOT == yes ]]; then
	unit=lib/systemd/system/armbian-resize-filesystem.service
	if [[ -f $DST_MNT/$unit ]]; then
		info "The copy grows its partition to the whole medium at the first boot (armbian-resize-filesystem)"
		rm -f "$DST_MNT/root/.no_rootfs_resize" "$DST_MNT/root/.rootfs_resize"
		mkdir -p "$DST_MNT/etc/systemd/system/basic.target.wants"
		ln -sf "/$unit" "$DST_MNT/etc/systemd/system/basic.target.wants/armbian-resize-filesystem.service"
	else
		red "warning: no armbian-resize-filesystem.service - the partition will not grow at the first boot"
	fi
fi
sync
umount "$DST_MNT"

# ---------- u-boot ----------
if [[ $WRITE_UBOOT == yes ]]; then
	info "Writing u-boot to $TARGET_DISK"
	dd if=/dev/zero of="$TARGET_DISK" bs=1k count=1023 seek=1 conv=fsync status=none   # old u-boot / env, MBR kept
	if [[ -z $UBOOT_BIN ]]; then
		# shellcheck disable=SC1090
		( source "$UBOOT_PLATFORM"; write_uboot_platform "$DIR" "$TARGET_DISK" ) 2>&1 | grep -v 'records\|copied' || true
	else
		dd if="$UBOOT_BIN" of="$TARGET_DISK" bs=1k seek=8 conv=fsync status=none
		echo "    written: $(uboot_version <(dd if="$TARGET_DISK" bs=1k skip=8 count=1024 status=none))"
	fi
	sync
fi

# ---------- image: finish ----------
if [[ -n $IMAGE_FILE ]]; then
	losetup -d "$LOOP_DEV"
	LOOP_DEV=""
	if [[ $COMPRESS == gz ]]; then
		gz=gzip; command -v pigz >/dev/null && gz=pigz
		info "Compressing to $IMAGE_FILE.gz ($gz)"
		"$gz" -c "$IMAGE_TMP" >"$IMAGE_FILE.gz.partial"
		mv "$IMAGE_FILE.gz.partial" "$IMAGE_FILE.gz"
		rm -f "$IMAGE_TMP"
		RESULT="$IMAGE_FILE.gz"
	else
		mv "$IMAGE_TMP" "$IMAGE_FILE"
		RESULT="$IMAGE_FILE"
	fi
	DONE=yes
	sync
	info "Done: image $RESULT ($(du -h --apparent-size "$RESULT" | cut -f1), UUID=$NEW_UUID, partition $TARGET_SIZE_MB MiB)"
	echo "Write it to an SD card / eMMC (balenaEtcher, Win32DiskImager, dd)."
	[[ $GROW_ON_BOOT == yes ]] && echo "The partition grows to the whole card at the first boot."
	exit 0
fi

DONE=yes
info "Done: system copied to $TARGET_PART (UUID=$NEW_UUID, $TARGET_SIZE_MB MiB)"
echo "Backups on the target: /etc/fstab.clone-bak, /boot/armbianEnv.txt.clone-bak"
echo "Most boards try the SD card first: with a card inserted the board boots from it."
echo "Check after a reboot: findmnt -n -o SOURCE /"
