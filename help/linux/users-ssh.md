# Users and SSH keys

## Users

```bash
sudo adduser vanya                 # create
sudo usermod -aG sudo vanya        # allow sudo
sudo deluser --remove-home pi      # remove with home folder
```

## Log in with a key instead of a password

On the client (Windows PowerShell or Linux):

```bash
ssh-keygen -t rsa -b 4096 -f ~/.ssh/my_server_key
```

On the server, put the **public** key (`my_server_key.pub`, one line `ssh-rsa AAAA… user@host`) into `authorized_keys`:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
echo "ssh-rsa AAAA...key... ivan@DESKTOP" >> ~/.ssh/authorized_keys
```

From Linux it is one command: `ssh-copy-id -i ~/.ssh/my_server_key.pub vanya@<host>`.

> [!WARNING]
> sshd ignores the key if the permissions are too open: home `700` (or `755`), `~/.ssh` `700`, `authorized_keys` `600`.

```bash
chmod 700 ~ ~/.ssh
chmod 600 ~/.ssh/authorized_keys
```

Connect: `ssh -i ~/.ssh/my_server_key vanya@<host>`.
