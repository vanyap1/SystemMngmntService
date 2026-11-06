# Storage, images, backups

## Full SD / eMMC image

```bash
# Backup, compressed on the fly
sudo dd if=/dev/mmcblk0 bs=10M status=progress | gzip -c > /media/vanya/USB/opi_zero2.img.gz
# Restore
gunzip -c /path/to/Armbian-clone.img.gz | sudo dd of=/dev/mmcblk0 bs=10M status=progress
# Uncompressed
sudo dd if=/dev/mmcblk0 of=/media/vanya/USB/opi_zero2.img bs=10M status=progress
```

> [!CAUTION]
> `of=` overwrites the whole device. Check the name with `lsblk` first.

## gzip / tar

```bash
sudo gzip -1 sdhRootFs.img          # compress (fast)
gzip -d sdhRootFs.img.gz            # decompress

sudo tar -czpvf PyEmmcCloner_30112025.tar.gz PyEmmcCloner                    # pack a project
sudo tar -czpvf PyEmmcCloner_30112025.tar.gz --exclude='*.img' PyEmmcCloner  # skip files
sudo tar -xzpvf PyEmmcCloner_30112025.tar.gz                                 # unpack
```

## Partitions

Grow the last partition to the end of the disk:

```bash
sudo parted /dev/mmcblk2
(parted) print
(parted) resizepart 9 100%
(parted) quit
sudo resize2fs /dev/mmcblk2p9
```

Read speed:

```bash
sudo hdparm -t --direct /dev/sdX
```

## Installing the panel offline

```bash
tar -xzf SystemMngmntService_offline.tar.gz -C /home/pi/
cd /home/pi/SystemMngmntService
sudo bash setup_offline.sh
```

Copy Python packages from a reference machine:

```bash
# on the reference machine
sudo tar -czvf full_python_dist_packages.tar.gz /usr/lib/python3/dist-packages/
# on the target: keep the old folder, unpack the reference one into /
sudo mv /usr/lib/python3/dist-packages /usr/lib/python3/dist-packages.old
sudo tar -xzvf full_python_dist_packages.tar.gz -C /
```

## Raw flash (MTD): JFFS2 and UBI

```bash
sudo apt-get install mtd-utils
```

### JFFS2

```bash
sudo mkfs.jffs2 -r /path/to/files -o image.jffs2 -e 0x1000 -l -n
sudo flashcp image.jffs2 /dev/mtd0

sudo modprobe mtdblock                   # /dev/mtdblock* appears
echo "mtdblock" | sudo tee -a /etc/modules
sudo mkdir -p /mnt/flash
sudo mount -t jffs2 /dev/mtdblock0 /mnt/flash
```

`/etc/fstab`:

```
/dev/mtdblock0  /mnt/flash  jffs2  defaults,noatime  0  0
```

### UBI (better for NAND)

```bash
sudo ubiformat /dev/mtd0
sudo ubiattach -p /dev/mtd0
sudo ubimkvol /dev/ubi0 -N rootfs -m
sudo mkfs.ubifs -r /path/to/files -m 2048 -e 126976 -c 256 -o image.ubifs
sudo mount -t ubifs ubi0:rootfs /mnt/flash
```
