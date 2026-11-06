sudo apt-get update
sudo apt-get upgrade
sudo apt-get -y install apache2
sudo mount -t cifs //192.168.1.5/NAS_drive /tmp/dt -o username=vanya,password=198808 & mkdir /tmp/dt 
ls /tmp/dt
sudo cp  /tmp/dt/OPI3/apache2/apache2.conf /etc/apache2
sudo nano /etc/apache2/apache2.conf
sudo nano /etc/apache2/sites-available/000-default.conf
sudo cp -r  /tmp/dt/OPI3/vanya/www /home/vanya
sudo chmod -R 777 ~/
sudo apt-get install samba
sudo apt-get install samba-common-bin
sudo cp -r  /tmp/dt/OPI3/samba/samba/smb.conf /etc/samba
sudo service smbd restart
ln -s /sys/class/gpio /home/vanya/www/gpio
sudo apt-get install php-mysql
sudo apt-get install php-mysql -y
sudo apt-get install php-xml -y
sudo apt-get install php-bzopen
sudo apt-get install php8.1-bz2 php8.1-zip
sudo apt install php8.1-bz2
sudo apt-get install libbz2-dev
systemctl restart apache2
reboot
sudo reboot
sudo apt-get -y install php7.0
sudo apt-get -y install php8.1
sudo apt-get -y install libapache2-mod-php
sudo apt-get install libfreetype6-dev libgl1-mesa-dev libgles2-mesa-dev     libdrm-dev libgbm-dev libudev-dev libasound2-dev liblzma-dev libjpeg-dev     libtiff-dev libwebp-dev git build-essential
sudo apt-get install gir1.2-ibus-1.0 libdbus-1-dev libegl1-mesa-dev     libibus-1.0-5 libibus-1.0-dev libice-dev libsm-dev libsndio-dev     libwayland-bin  libwayland-dev libxi-dev libxinerama-dev libxkbcommon-dev     libxrandr-dev libxss-dev libxt-dev libxv-dev x11proto-randr-dev      x11proto-scrnsaver-dev x11proto-video-dev x11proto-xinerama-dev
sudo chmod +x ~/serv.sh 
ls /home/vanya
sudo mount -t cifs //192.168.1.5/NAS_drive /tmp/dt -o username=vanya,password=198808 & mkdir /tmp/dt
sudo cp -r  /tmp/dt/OPI3/vanya/serv.sh /home/vanya
sudo chmod +x ~/serv.sh 
~/serv.sh 
sudo apt-get install php-mysql
sudo apt-get install php-xml
sudo apt-get install php-bzopen
sudo apt-get install php8.1-bz2 php8.1-zip
sudo apt install php8.1-bz2
sudo apt-get install libbz2-dev
wget https://libsdl.org/release/SDL2-2.0.10.tar.gz
wget https://libsdl.org/projects/SDL_image/release/SDL2_image-2.0.5.tar.gz
wget https://libsdl.org/projects/SDL_mixer/release/SDL2_mixer-2.0.4.tar.gz
wget https://libsdl.org/projects/SDL_ttf/release/SDL2_ttf-2.0.15.tar.gz
tar -zxvf SDL2-2.0.10.tar.gz && tar -zxvf SDL2_image-2.0.5.tar.gz
tar -zxvf SDL2_mixer-2.0.4.tar.gz && tar -zxvf SDL2_ttf-2.0.15.tar.gz
pushd SDL2-2.0.10
./configure --enable-video-kmsdrm --disable-video-opengl --disable-video-x11 --disable-video-rpi
make -j$(nproc)
sudo make install
podp
popd
pushd SDL2_image-2.0.5
./configure
make -j$(nproc)
sudo make install
popd
pushd SDL2_mixer-2.0.4
./configure
sudo make install
pushd SDL2_ttf-2.0.15
popd
pushd SDL2_ttf-2.0.15
./configure
make -j$(nproc)
sudo make install
popd
sudo apt install pkg-config libgl1-mesa-dev libgles2-mesa-dev     python3-setuptools libgstreamer1.0-dev git-core     gstreamer1.0-plugins-{bad,base,good,ugly}     gstreamer1.0-{omx,alsa} python3-dev libmtdev-dev     xclip xsel libjpeg-dev
sudo apt install python3-pip
sudo apt-get install -y     python3-pip     build-essential     git     python3     python3-dev \
sudo add-apt-repository ppa:kivy-team/kivy
sudo apt-get install python3-kivy
sudo apt-get install -y     libsdl2-dev     libsdl2-image-dev     libsdl2-mixer-dev     libsdl2-ttf-dev     libportmidi-dev     libswscale-dev     libavformat-dev     libavcodec-dev     zlib1g-dev
sudo apt-get install -y python3-smbus
sudo apt-get install -y python3-requests
python3 -m pip install kivy_garden.graph --extra-index-url https://kivy-garden.github.io/simple/
cd ~/www/GUI/
python3 main.py
nano ~/.kivy/config.ini
python3 main.py
sudo apt-get install libmtdev-dev
python3 main.py
nano ~/.kivy/config.ini
python3 main.py
sudo su
nano /etc/update-motd.d
motd
ls /etc/update-motd.d/
nano /etc/update-motd.d/10-armbian-header 
nano /etc/update-motd.d/30-armbian-sysinfo 
echo "${ips[@]}"
nano /etc/update-motd.d/10-armbian-header 
/etc/update-motd.d/10-armbian-header 
nano /etc/update-motd.d/10-armbian-header 
sudo nano /etc/update-motd.d/10-armbian-header 
/etc/update-motd.d/10-armbian-header 
sudo nano /etc/update-motd.d/10-armbian-header 
/etc/update-motd.d/10-armbian-header 
sudo nano /etc/update-motd.d/10-armbian-header 
/etc/update-motd.d/10-armbian-header 
sudo nano /etc/update-motd.d/10-armbian-header 
cp /etc/update-motd.d/10-armbian-header 
echo linux toilet -f standard -F metal $(echo "test")
echo linux toilet -f standard -F metal $("test")
sudo nano /etc/update-motd.d/10-armbian-header 
cp /etc/update-motd.d/10-armbian-header ~/
python3 main.py
sudo reboot
cd ~/www/GUI/
python3 main.py
nano ~/.kivy/config.ini
python3 main.py
sudo armbian-config
sudo apt-get install armbian-config
ls /etc/update-motd.d/
/etc/update-motd.d/30-armbian-sysinfo 
/etc/update-motd.d/35-armbian-tips 
/etc/update-motd.d/40-armbian-updates 
/etc/update-motd.d/41-armbian-config 
/etc/update-motd.d/98-armbian-autoreboot-warn 
/etc/update-motd.d/10-armbian-header 
sudo armbian-config
sudo reboot
sudo nano /lib/systemd/system/autoupdate.service
sudo chmod 644 /lib/systemd/system/autoupdate.service
sudo nano /lib/systemd/system/autoupdate.service
sudo chmod 644 /lib/systemd/system/autoupdate.service
ls/lib/systemd/system/
ls /lib/systemd/system/
sudo nano /lib/systemd/system/autoupdate.service
sudo chmod 644 /lib/systemd/autoupdate.service
sudo nano /lib/systemd/autoupdate.service
sudo chmod 644 /lib/systemd/autoupdate.service
sudo nano /lib/systemd/autoupdate.service
sudo armbian-config
sudo nano /etc/hostname
sudo reboot
ls /lib/systemd/auto*
sudo chmod 644 /lib/systemd/autoupdate.service
sudo nano /etc/hosts
sudo nano /etc/hostname
sudo nano /etc/hosts
sudo chmod 644 /lib/systemd/autoupdate.service
sudo systemctl daemon-reload
sudo systemctl enable autoupdate.service
cd ~/
nano GUIRun
sudo chmod +x GUIRun
ls
./GUIRun 
sudo nano ~/serv.sh 
reboot
sudo nano ~/serv.sh 
reudo shutdown
sudo poweroff
sudo nano ~/serv
sudo nano ~/serv.sh
~/serv.sh
sudo apt install i2c-tools -y
sudo i2cdetect -y 0
sudo armbian-config
sudo i2cdetect -y 0
sudo i2cdetect -y 1
sudo armbian-config
mc 
sudo nano /lib/systemd/autoupdate.service
sudo nano ~/serv.sh 
reboot
sudo armbian-config
reboot
cd ~/www/GUI
python3 main.py
sudo apt install psutip -y
sudo apt install psutil -y
python3 -m pip install psutil
python3 main.py
sudo nano ~/.kivy/config.ini 
python3 main.py
sudo nano ~/.kivy/config.ini 
python3 main.py
sudo nano ~/.kivy/config.ini 
python3 main.py
sudo nano ~/.kivy/config.ini 
python3 main.py
sudo nano ~/.kivy/config.ini 
python3 main.py
reboot
htop
echo "www" > /dev/ttyS2
echo "www" > /dev/ttyS3
cd ~/www/GUI
python3 main.py
ls ~/
sudo nano ~/serv.sh
python3 main.py
python3 -m pip install serial
python3 main.py
python3 -m pip install mysql
python3 main.py
cd ~/www/GUI
python3 main.py
cd ~/www/GUI
python3 main.py
nano ~/serv.sh 
python3 main.py
ls ~/
nano ~/GUIRun 
~/serv.sh 
sudo chmod 777 ~/20230429_Autowash.tar.gz 
~/serv.sh 
reboot
sudo nano /lib/systemd/autoupdate.service 
ls ~/
sudo chmod +x ~/GUIRun 
sudo systemctl enable autoupdate.service
sudo systemctl daemon-reload
reboot
nano ~/serv.sh 
sudo nano chmod 777 ~/serv.sh 
sudo chmod 777 ~/serv.sh 
sudo chmod +x ~/serv.sh 
~/GUIRun >> ~/logfile.txt
~/GUIRun > ~/logfile.txt
reboot
nano ~/serv.sh 
~/serv.sh 
nano ~/serv.sh 
~/serv.sh 
reboot
echo linux toilet -f standard -F metal $("test")
sudo python3 -m pip install pyserial
reboot
sudo /home/vanya/serv.sh 
sudo python3 -m pip install mysql.connector
sudo /home/vanya/serv.sh 
sudo python3 -m pip install bufsock
sudo /home/vanya/serv.sh 
sudo cp /home/vanya/.kivy/config.ini /home/root/.kivy
sudo cp /home/vanya/.kivy/config.ini ~/.kivy
sudo rm ~/.kivy/config.ini 
sudo cp /home/vanya/.kivy/config.ini ~/.kivy
sudo chmod 777 /home/vanya/.kivy
sudo /home/vanya/serv.sh 
sudo nano ~/.kivy/config.ini 
sudo /home/vanya/serv.sh 
sudo nano ~/.kivy/config.ini 
sudo /home/vanya/serv.sh 
sudo nano ~/.kivy/config.ini 
sudo /home/vanya/serv.sh 
reboot
exit
sudo pkill -f python3
sudo su
echo $date
echo $(date)
printf '%s %s\n' "$(date)" "$line"
/usr/share/zoneinfo
TZ=EST5EDT date
TZ=EST3EDT date
TZ=EST1EDT date
date
sudo localectl set-locale LANG=en_US.utf8
date
sudo localectl set-locale LC_TIME=en_DK.UTF-8
date
sudo nano ~/serv.sh 
echo $date
echo $(date)
sudo nano ~/serv.sh 
sudo /home/vanya/serv.sh 
sudo nano ~/serv.sh 
sudo nano ~/GUIRun 
sudo nano ~/serv.sh 
sudo /home/vanya/serv.sh 
sudo nano ~/serv.sh 
sudo nano ~/GUIRun 
sudo nano ~/serv.sh 
sudo /home/vanya/serv.sh 
sudo nano ~/GUIRun 
sudo /home/vanya/serv.sh 
sudo /home/vanya/GUIRun 
sudo nano ~/GUIRun 
sudo nano ~/serv.sh 
sudo nano ~/GUIRun 
sudo /home/vanya/GUIRun 
sudo nano ~/GUIRun 
sudo nano ~/serv.sh 
sudo nano ~/GUIRun 
sudo /home/vanya/GUIRun 
reboot
ls /boot
sudo nano /boot/armbianEnv.txt 
reboot
ls /boot
cp /boot/boot.bmp ~/
ls /usr/share/plymouth/themes/armbian/
cp /usr/share/plymouth/themes/armbian/ ~/
cp -r /usr/share/plymouth/themes/armbian/ ~/
sudo chmod 777 -r  ~/armbian/
sudo chmod 777 ~/armbian/
sudo chmod 777 ~/armbian//bgrt-fallback.png 
sudo chmod 777 -R ~/armbian//bgrt-fallback.png 
sudo chmod 777 -R ~/armbian/ 
sudo cp -r ~/armbian/bgrt-fallback.png /usr/share/plymouth/themes/armbian/
reboot
cp /boot/boot.bmp ~/
sudo nano /boot/armbianEnv.txt 
reboot
sudo nano /lib/systemd/autoupdate.service 
whoami
sudo nano ~/serv.sh 
reboot
sudo nano /lib/systemd/autoupdate.service 
sudo systemctl enable autoupdate.service
sudo systemctl daemon-reload
reboot
