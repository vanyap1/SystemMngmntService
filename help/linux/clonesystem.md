# Move system to accessible block devs

```bash
#!/bin/bash
#
# clone-system.sh - copy the running Armbian system onto another disk (eMMC of the slot, SD card, USB ...).
# The target may be smaller than the source: files are copied (rsync), not a disk image.
#
#   1. finds the disks, the target is chosen (any disk except the one the system runs from)
#   2. checks that the data fits
#   3. creates the partition table (MBR, 1 partition from PART_START_SECTOR)
#   4. formats it, copies the system (incl. /var/log under zram, /boot)
#   5. writes the new UUID into /etc/fstab and /boot/armbianEnv.txt
#   6. writes u-boot (SPL) to the target
#
# Interactive:     sudo ./clone-system.sh
# Unattended:      sudo TARGET_DISK=/dev/mmcblk1 EXTRA_MB=512 ASSUME_YES=yes ./clone-system.sh
#                  or a file with VAR=value lines: sudo CONFIG_FILE=/path/env ./clone-system.sh
#                  (used by the eMMC writer web UI, System tab)
#
# WARNING: all data on the target disk is destroyed.

[[ -n ${CONFIG_FILE:-} && -f $CONFIG_FILE ]] && source "$CONFIG_FILE"

# ======================= SETTINGS (environment overrides) =======================
SOURCE_DISK="${SOURCE_DISK:-}"            # empty = the disk "/" is on
TARGET_DISK="${TARGET_DISK:-}"            # e.g. /dev/mmcblk1; empty = choose from a list
TARGET_SIZE_MB="${TARGET_SIZE_MB:-}"      # partition size in MiB, "max" = whole disk; empty = minimum + EXTRA_MB or ask
EXTRA_MB="${EXTRA_MB:-}"                  # partition = minimum for the data + this many MiB
PART_START_SECTOR="${PART_START_SECTOR:-8192}"   # 4 MiB as in the Armbian images; u-boot lives before it
FS_TYPE="${FS_TYPE:-ext4}"
FS_LABEL="${FS_LABEL:-armbi_root}"
MKFS_OPTS="${MKFS_OPTS:--m 2}"
UBOOT_BIN="${UBOOT_BIN:-}"                # empty = /usr/lib/linux-u-boot-*/u-boot-sunxi-with-spl.bin
WRITE_UBOOT="${WRITE_UBOOT:-yes}"
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
uboot_version() { (set +o pipefail; strings "$1" 2>/dev/null | grep -m1 'U-Boot SPL' || echo '?'); }

[[ $EUID -eq 0 ]] || die "run with sudo"
for cmd in rsync sfdisk wipefs blkid lsblk findmnt "mkfs.$FS_TYPE" udevadm; do
	command -v "$cmd" >/dev/null || die "command '$cmd' not found (apt install rsync fdisk e2fsprogs)"
done

cleanup() {
	set +e
	sync
	mountpoint -q "$DST_MNT/boot" 2>/dev/null && umount "$DST_MNT/boot"
	mountpoint -q "$DST_MNT" && umount "$DST_MNT"
	mountpoint -q "$SRC_MNT/boot" 2>/dev/null && umount "$SRC_MNT/boot"
	mountpoint -q "$SRC_MNT" && umount "$SRC_MNT"
	rmdir "$SRC_MNT" "$DST_MNT" 2>/dev/null
}
trap cleanup EXIT

# ---------- source ----------
ROOT_PART=$(findmnt -n -o SOURCE /)
ROOT_PART=${ROOT_PART%%[*}
[[ -n $SOURCE_DISK ]] || SOURCE_DISK="/dev/$(lsblk -no PKNAME "$ROOT_PART" | head -n1)"
[[ -b $SOURCE_DISK ]] || die "source $SOURCE_DISK not found"
BOOT_PART=""
if findmnt -n /boot >/dev/null 2>&1; then BOOT_PART=$(findmnt -n -o SOURCE /boot); fi
OLD_UUID=$(blkid -s UUID -o value "$ROOT_PART")
OLD_PARTUUID=$(blkid -s PARTUUID -o value "$ROOT_PART" || true)
info "System runs from $ROOT_PART (disk $SOURCE_DISK, UUID=$OLD_UUID)"
[[ -n $BOOT_PART ]] && info "System has a separate /boot: $BOOT_PART"

# ---------- target ----------
list_candidates() {
	lsblk -dpno NAME,TYPE | awk '$2=="disk"{print $1}' |
		grep -Ev '/dev/(loop|zram|ram|mtdblock)|boot[0-9]+$|rpmb$' | grep -vx "$SOURCE_DISK" || true
}
if [[ -z $TARGET_DISK ]]; then
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
[[ -b $TARGET_DISK ]] || die "$TARGET_DISK is not a block device"
[[ $TARGET_DISK != "$SOURCE_DISK" ]] || die "target is the source disk"
lsblk -lnpo NAME "$TARGET_DISK" | grep -qx "$ROOT_PART" && die "$TARGET_DISK carries the running root filesystem"

# ---------- size ----------
MB=$((1024 * 1024))
target_bytes=$(blockdev --getsize64 "$TARGET_DISK")
max_part_mb=$(( (target_bytes - PART_START_SECTOR * 512) / MB - 1 ))
used_bytes=$(df -B1 --output=used / | tail -n1)
if [[ -n $BOOT_PART ]]; then used_bytes=$((used_bytes + $(df -B1 --output=used /boot | tail -n1))); fi
min_part_mb=$(( (used_bytes / MB + RESERVE_MB) * 100 / 95 + 1 ))   # data + reserve + ~5 % ext4 metadata
info "System uses $((used_bytes / MB)) MiB; minimal partition $min_part_mb MiB"
info "Target $TARGET_DISK: $((target_bytes / MB)) MiB (partition at most $max_part_mb MiB)"
((min_part_mb <= max_part_mb)) || die "the system does not fit on $TARGET_DISK"

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
if [[ $WRITE_UBOOT == yes ]]; then
	[[ -n $UBOOT_BIN ]] || UBOOT_BIN=$(ls /usr/lib/linux-u-boot-*/u-boot-sunxi-with-spl.bin 2>/dev/null | head -n1 || true)
	[[ -f $UBOOT_BIN ]] || die "u-boot not found (UBOOT_BIN='$UBOOT_BIN')"
	info "u-boot: $UBOOT_BIN ($(uboot_version "$UBOOT_BIN"))"
fi

# ---------- confirmation ----------
echo "Will create: $TARGET_DISK -> 1 partition $FS_TYPE, $TARGET_SIZE_MB MiB, from sector $PART_START_SECTOR"
red "ALL DATA ON $TARGET_DISK ($(lsblk -dno SIZE "$TARGET_DISK" | xargs)) WILL BE DESTROYED!"
if [[ $ASSUME_YES != yes ]]; then
	read -rp "Type the device name to continue ($(basename "$TARGET_DISK")): " ans
	[[ $ans == "$(basename "$TARGET_DISK")" ]] || die "cancelled"
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
mount --bind / "$SRC_MNT"                 # the plain root filesystem, without zram / tmpfs / proc on top
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
sync
umount "$DST_MNT"

# ---------- u-boot ----------
if [[ $WRITE_UBOOT == yes ]]; then
	info "Writing u-boot to $TARGET_DISK"
	dd if=/dev/zero of="$TARGET_DISK" bs=1k count=1023 seek=1 conv=fsync status=none   # u-boot / env area, MBR kept
	dd if="$UBOOT_BIN" of="$TARGET_DISK" bs=1k seek=8 conv=fsync status=none
	sync
	echo "    written: $(uboot_version <(dd if="$TARGET_DISK" bs=1k skip=8 count=1024 status=none))"
fi

info "Done: system copied to $TARGET_PART (UUID=$NEW_UUID, $TARGET_SIZE_MB MiB)"
echo "Backups on the target: /etc/fstab.clone-bak, /boot/armbianEnv.txt.clone-bak"
echo "The H618 BROM tries the SD card first: with a card inserted the board boots from it."
echo "Check after a reboot: findmnt -n -o SOURCE /"

```


