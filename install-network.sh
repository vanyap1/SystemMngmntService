#!/bin/bash
# ============================================================================================================
#  SystemMngmntService — Wi-Fi access point + DHCP server dependencies (Settings → Network → Access point & DHCP)
#
#  sudo ./install-network.sh [install] [--yes]   install packages (online, apt) and prepare the DHCP files
#  ./install-network.sh status                    what is installed, Wi-Fi adapters and their AP support
#
#  The panel uses NetworkManager in "shared" mode for the access point: NM starts its own dnsmasq for the Wi-Fi
#  interface (DHCP, DNS, NAT to the uplink). Needed: network-manager (>= 1.42 for the pool / lease settings),
#  dnsmasq-base (the binary NM runs — not the dnsmasq service), iw (AP support, client signal), wireless-regdb
#  (channels allowed in your country), rfkill. Also called from: sudo ./install.sh network
#  Re-running is safe. The panel needs no restart. Network settings are not changed by this script.
# ============================================================================================================

set -uo pipefail

export PATH="$PATH:/usr/local/sbin:/usr/sbin:/sbin"
PKGS="dnsmasq-base iw wireless-regdb rfkill"
NM_PKG="network-manager"
DNSMASQ_DIR="/etc/NetworkManager/dnsmasq-shared.d"
CONF="$DNSMASQ_DIR/smms-dhcp.conf"          # keep in sync with core/netap.py (DNSMASQ_DIR, CONF_NAME, HOSTS_FILE)
HOSTS="/etc/NetworkManager/smms-dhcp.hosts"
YES=0

if [[ -t 1 ]]; then C_OK=$'\e[32m'; C_ERR=$'\e[31m'; C_WARN=$'\e[33m'; C_DIM=$'\e[2m'; C_B=$'\e[1m'; C_0=$'\e[0m'
else C_OK=""; C_ERR=""; C_WARN=""; C_DIM=""; C_B=""; C_0=""; fi
info() { echo "${C_B}[*]${C_0} $*"; }
ok()   { echo "${C_OK}[OK]${C_0} $*"; }
warn() { echo "${C_WARN}[!]${C_0} $*" >&2; }
die()  { echo "${C_ERR}[ERROR]${C_0} $*" >&2; exit 1; }
mark() { if [[ "$1" == 1 ]]; then echo "${C_OK}✔${C_0}"; else echo "${C_ERR}✘${C_0}"; fi; }

ask() {   # ask "question" default(y|n) → 0 for yes
    local q="$1" def="${2:-n}" a
    [[ $YES -eq 1 ]] && return 0
    [[ -t 0 ]] || { [[ $def == y ]]; return; }
    read -r -p "$q [$( [[ $def == y ]] && echo Y/n || echo y/N )] " a </dev/tty || a=""
    a="${a:-$def}"; [[ $a =~ ^[YyТтДд] ]]
}

has_pkg()    { dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'install ok installed'; }
nm_version() { nmcli --version 2>/dev/null | grep -o '[0-9]\+\.[0-9]\+\(\.[0-9]\+\)\?' | head -1; }
nm_ok()      {   # NetworkManager >= 1.42 (ipv4.shared-dhcp-range / -lease-time)
    local v; v="$(nm_version)"; [[ -n $v ]] || return 1
    local ma="${v%%.*}" mi; mi="${v#*.}"; mi="${mi%%.*}"
    (( ma > 1 || (ma == 1 && mi >= 42) ))
}
wifi_ifaces() { local d; for d in /sys/class/net/*; do [[ -d $d/wireless || -e $d/phy80211 ]] && basename "$d"; done; }
ap_support() {    # ap_support IFACE → yes / no / ?
    local phy; phy="$(cat "/sys/class/net/$1/phy80211/name" 2>/dev/null)"
    [[ -n $phy ]] && command -v iw >/dev/null || { echo "?"; return; }
    iw phy "$phy" info 2>/dev/null | sed -n '/Supported interface modes:/,/^\s*[^*[:space:]]/p' | grep -q '\* AP$' && echo yes || echo no
}

cmd_status() {
    local p v
    echo "${C_B}Wi-Fi access point + DHCP${C_0}"
    v="$(nm_version)"
    printf "  %s %-16s %s\n" "$(mark "$( nm_ok && echo 1 || echo 0)")" "NetworkManager" "${v:-not installed}$(nm_ok || [[ -z $v ]] || echo ' (1.42+ needed for pool / lease settings)')"
    printf "  %s %-16s %s\n" "$(mark "$(systemctl is-active -q NetworkManager 2>/dev/null && echo 1 || echo 0)")" "NM service" "$(systemctl is-active NetworkManager 2>/dev/null)"
    for p in $PKGS; do
        printf "  %s %-16s\n" "$(mark "$(has_pkg "$p" && echo 1 || echo 0)")" "$p"
    done
    printf "  %s %-16s %s\n" "$(mark "$([[ -f $CONF ]] && echo 1 || echo 0)")" "DHCP conf" "$CONF"
    if systemctl is-active -q dnsmasq 2>/dev/null; then
        warn "the dnsmasq service is running — it may hold port 53/67 on all interfaces and block NM's dnsmasq of the access point"
    fi
    echo "  Wi-Fi adapters"
    local i found=0
    for i in $(wifi_ifaces); do
        found=1
        printf "    %-12s AP mode: %s  %s\n" "$i" "$(ap_support "$i")" "${C_DIM}$(nmcli -g GENERAL.STATE device show "$i" 2>/dev/null)${C_0}"
    done
    [[ $found -eq 1 ]] || echo "    none found"
    if command -v rfkill >/dev/null && rfkill list wifi 2>/dev/null | grep -q 'Soft blocked: yes'; then
        warn "Wi-Fi is soft-blocked (rfkill) — the panel turns the radio on when it starts the access point"
    fi
    command -v iw >/dev/null && echo "  Regulatory domain: $(iw reg get 2>/dev/null | sed -n 's/^country \([A-Z0-9]*\).*/\1/p' | head -1)"
}

cmd_install() {
    [[ $EUID -eq 0 ]] || die "run as root: sudo $0 install"
    command -v apt-get >/dev/null || die "apt-get not found (Debian-based systems only)"
    local want="" p
    if ! command -v nmcli >/dev/null; then
        warn "NetworkManager is not installed. The panel's network settings need it."
        warn "Installing it hands the network over to NetworkManager — interfaces configured in /etc/network/interfaces"
        warn "or netplan may change their behaviour. Do it from a local console, not over the only SSH link."
        ask "Install network-manager anyway?" n && want+=" $NM_PKG"
    fi
    for p in $PKGS; do has_pkg "$p" || want+=" $p"; done
    if [[ -n $want ]]; then
        info "apt-get update..."
        apt-get update -q || die "apt-get update failed (no internet?)"
        info "Installing:$want"
        # shellcheck disable=SC2086
        DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends $want || die "apt-get install failed"
    else
        ok "Packages already installed:$( for p in $PKGS; do echo -n " $p"; done)"
    fi
    if systemctl is-active -q dnsmasq 2>/dev/null; then
        warn "the dnsmasq *service* is running; it can block NM's dnsmasq for the access point (ports 53 / 67)."
        if ask "Stop and disable the dnsmasq service?" n; then systemctl disable --now dnsmasq && ok "dnsmasq service disabled"; fi
    fi
    mkdir -p "$DNSMASQ_DIR"
    [[ -f $HOSTS ]] || { install -m 0644 /dev/null "$HOSTS" && ok "Created $HOSTS (MAC → IP reservations)"; }
    local text="# Written by SystemMngmntService (Settings → Network → Access point & DHCP).
dhcp-hostsfile=$HOSTS"
    if [[ "$(cat "$CONF" 2>/dev/null)" != "$text" ]]; then
        printf '%s\n' "$text" >"$CONF" && chmod 0644 "$CONF" && ok "Written $CONF"
    fi
    nm_ok || warn "NetworkManager $(nm_version) — pool range / lease time need 1.42+ (older ones use their defaults)"
    echo
    cmd_status
    echo
    ok "Done. Open the panel: Settings → Network → Access point & DHCP (no panel restart needed)."
}

main() {
    local cmd=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -y|--yes) YES=1 ;;
            -h|--help) sed -n '2,/^# =\{5,\}$/p' "$0" | sed '1d;$d;s/^# \{0,1\}//'; exit 0 ;;
            install|status) cmd="$1" ;;
            *) die "unknown argument: $1 (see $0 --help)" ;;
        esac
        shift
    done
    "cmd_${cmd:-install}"
}

main "$@"
