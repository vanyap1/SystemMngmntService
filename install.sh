#!/bin/bash
# ============================================================================================================
#  SystemMngmntService — installer
#
#  sudo ./install.sh                      interactive menu (whiptail if available, plain prompts otherwise)
#  ./install.sh status                    what is installed, service state, available offline bundles
#  sudo ./install.sh online   [opts]      install / update dependencies from the internet (apt + pip)
#  sudo ./install.sh offline  [opts]      install / update from an offline bundle in setup_data/
#  ./install.sh bundle [--arch armhf,arm64] [--suite bookworm] [--components …]
#                                         build offline bundles (on a machine with internet, no root needed)
#  sudo ./install.sh service  [--yes]     write/enable the systemd unit, (re)start the panel
#  sudo ./install.sh uninstall [--yes]    remove the systemd unit (the project and its config stay)
#
#  Options: --components core,git,gpio,devices,video   --bundle DIR|FILE.tar   --yes (no questions)
#  Dashed forms (--online, --offline, --status, --service, --uninstall) are accepted too.
#  Re-running is safe: packages already present are skipped, the unit is rewritten only when it changes.
# ============================================================================================================

set -uo pipefail

export PATH="$PATH:/usr/local/sbin:/usr/sbin:/sbin"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT="systemmngmntservice.service"
UNIT_FILE="/etc/systemd/system/$UNIT"
DATA="$DIR/setup_data"

# Debian packages per component (keep in sync with COMPONENTS in tools/offline_bundle.py).
declare -A PKGS=(
    [core]="python3 python3-markupsafe python3-pip sudo iproute2 whiptail"
    [git]="git"
    [gpio]="python3-libgpiod gpiod python3-serial python3-smbus"
    [devices]="usbutils pciutils i2c-tools can-utils"
    [video]="ffmpeg"
)
declare -A DESC=(
    [core]="Python 3, Flask 3, pip, sudo (required)"
    [git]="Git: commit / push / pull from the panel"
    [gpio]="GPIO and test platform: libgpiod, pyserial, smbus"
    [devices]="Devices popup tools: lsusb, lspci, i2c-tools, can-utils"
    [video]="Video streaming: ffmpeg (large, ~100 MB)"
)
ORDER=(core git gpio devices video)
DEFAULT_COMPONENTS="core,git,gpio,devices"
WHEELS=("flask>=3" werkzeug jinja2 itsdangerous click blinker)

YES=0
COMPONENTS=""
BUNDLE=""
UI=""                         # whiptail | plain

# ── output ───────────────────────────────────────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then C_OK=$'\e[32m'; C_ERR=$'\e[31m'; C_WARN=$'\e[33m'; C_DIM=$'\e[2m'; C_B=$'\e[1m'; C_0=$'\e[0m'
else C_OK=""; C_ERR=""; C_WARN=""; C_DIM=""; C_B=""; C_0=""; fi
info() { echo "${C_B}[*]${C_0} $*"; }
ok()   { echo "${C_OK}[OK]${C_0} $*"; }
warn() { echo "${C_WARN}[!]${C_0} $*" >&2; }
die()  { echo "${C_ERR}[ERROR]${C_0} $*" >&2; exit 1; }
mark() { if [[ "$1" == 1 ]]; then echo "${C_OK}✔${C_0}"; else echo "${C_ERR}✘${C_0}"; fi; }

need_root() { [[ $EUID -eq 0 ]] || die "run as root: sudo $0 $*"; }

ask() {   # ask "question" default(y|n) → 0 for yes
    local q="$1" def="${2:-n}" a
    [[ $YES -eq 1 ]] && return 0
    if [[ $UI == whiptail ]]; then
        local extra=(); [[ $def == n ]] && extra=(--defaultno)
        whiptail --title "SystemMngmntService" "${extra[@]}" --yesno "$q" 10 70; return
    fi
    read -r -p "$q [$( [[ $def == y ]] && echo Y/n || echo y/N )] " a </dev/tty || a=""
    a="${a:-$def}"; [[ $a =~ ^[YyТтДд] ]]
}

# ── system facts ─────────────────────────────────────────────────────────────────────────────────────────────
os_codename() { (. /etc/os-release 2>/dev/null; echo "${VERSION_CODENAME:-${DEBIAN_CODENAME:-unknown}}"); }
os_name()     { (. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-unknown}"); }
deb_arch()    { dpkg --print-architecture 2>/dev/null || uname -m; }
board()       { tr -d '\0' </proc/device-tree/model 2>/dev/null || echo "-"; }
py()          { command -v python3 >/dev/null && python3 "$@"; }
flask_ver()   { py -c 'import flask, importlib.metadata as m; print(m.version("flask"), flask.__file__.rsplit("/flask/", 1)[0])' 2>/dev/null; }
panel_port()  { (cd "$DIR" && py -c 'from core import config; print(config.get("port", 80))' 2>/dev/null) || echo 80; }

has_component() {
    case "$1" in
        core)    py -c 'import flask, importlib.metadata as m, sys; sys.exit(int(m.version("flask").split(".")[0]) < 3)' 2>/dev/null ;;
        git)     command -v git >/dev/null ;;
        gpio)    py -c 'import gpiod, serial, smbus' 2>/dev/null ;;
        devices) command -v lsusb >/dev/null && command -v lspci >/dev/null && command -v i2cdetect >/dev/null ;;
        video)   command -v ffmpeg >/dev/null ;;
        *)       return 1 ;;
    esac
}

selected_pkgs() {   # packages of $COMPONENTS; with a list of available ones ($1), only those
    local c p out=""
    for c in ${COMPONENTS//,/ }; do
        for p in ${PKGS[$c]}; do [[ -z "${1:-}" || " $1 " == *" $p "* ]] && out+=" $p"; done
    done
    echo "$out"
}

manifest_list() {   # manifest_list FILE KEY → comma-separated items of a JSON string list (works without python)
    sed -n "/\"$2\": \[/,/\]/p" "$1" | sed '1d' | tr -d ' ",]' | grep . | paste -sd, -
}

check_components() {   # normalises $COMPONENTS (core always first)
    local c list="core"
    for c in ${COMPONENTS//,/ }; do
        [[ -n "${PKGS[$c]+x}" ]] || die "unknown component: $c (known: ${ORDER[*]})"
        [[ $c == core || ,$list, == *,$c,* ]] || list+=",$c"
    done
    COMPONENTS="$list"
}

choose_components() {   # interactive selection unless --components was given
    [[ -n "$COMPONENTS" ]] && { check_components; return; }
    local def="$DEFAULT_COMPONENTS" c
    if [[ $YES -eq 1 ]]; then COMPONENTS="$def"; check_components; return; fi
    if [[ $UI == whiptail ]]; then
        local args=()
        for c in "${ORDER[@]}"; do
            local on=OFF; [[ ,$def, == *,$c,* ]] && on=ON
            has_component "$c" && on=ON
            args+=("$c" "${DESC[$c]}" "$on")
        done
        local sel
        sel=$(whiptail --title "Components" --separate-output --checklist "Space toggles, Enter confirms" 15 76 6 "${args[@]}" 3>&1 1>&2 2>&3) || exit 0
        COMPONENTS="$(echo "$sel" | paste -sd, -)"
    else
        echo "Components:"
        for c in "${ORDER[@]}"; do printf "  %-8s %s %s\n" "$c" "$(has_component "$c" && echo "${C_DIM}(installed)${C_0}")" "${DESC[$c]}"; done
        read -r -p "Install which? [$def] " sel </dev/tty || sel=""
        COMPONENTS="${sel:-$def}"
    fi
    COMPONENTS="${COMPONENTS// /}"
    check_components
}

pip_flags() {   # flags this pip understands
    local h; h="$(python3 -m pip install --help 2>/dev/null)"
    local f=(--upgrade --disable-pip-version-check)
    grep -q -- '--break-system-packages' <<<"$h" && f+=(--break-system-packages)
    grep -q -- '--root-user-action' <<<"$h" && f+=(--root-user-action=ignore)
    echo "${f[@]}"
}

# ── status ───────────────────────────────────────────────────────────────────────────────────────────────────
cmd_status() {
    local fv c
    echo "${C_B}SystemMngmntService${C_0}  $DIR"
    printf "  %-12s %s\n" "System" "$(os_name) · $(deb_arch) · $(board)"
    printf "  %-12s %s\n" "Python" "$(py -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || echo 'not installed')"
    fv="$(flask_ver)"
    printf "  %-12s %s\n" "Flask" "${fv:-not installed}"
    echo "  Components"
    for c in "${ORDER[@]}"; do
        local h=0; has_component "$c" && h=1
        printf "    %s %-8s %s\n" "$(mark $h)" "$c" "${C_DIM}${DESC[$c]}${C_0}"
    done
    echo "  Service"
    if [[ -f "$UNIT_FILE" ]]; then
        local exec; exec="$(systemctl show -p ExecStart --value "$UNIT" 2>/dev/null | sed -n 's/.*argv\[\]=\([^;]*\);.*/\1/p' | sed 's/ *$//')"
        printf "    %-10s %s\n" "unit" "$UNIT_FILE"
        [[ -n "$exec" ]] && printf "    %-10s %s\n" "runs" "$exec"
        [[ -n "$exec" && "$exec" != *"$DIR/app.py"* ]] && warn "the unit runs another copy of the panel (not $DIR)"
    else
        printf "    %-10s %s\n" "unit" "not installed"
    fi
    printf "    %-10s %s / %s\n" "state" "$(systemctl is-enabled "$UNIT" 2>/dev/null || echo disabled)" "$(systemctl is-active "$UNIT" 2>/dev/null || echo inactive)"
    printf "    %-10s %s\n" "port" "$(panel_port)"
    local pybin; pybin="$(readlink -f "$(command -v python3 2>/dev/null)" 2>/dev/null)"
    if [[ -n "$pybin" ]] && command -v getcap >/dev/null && getcap "$pybin" 2>/dev/null | grep -q cap_net_bind_service; then
        warn "$pybin has cap_net_bind_service (set by the old setup.sh; not needed, the service runs as root)."
        echo "      remove it with: sudo setcap -r $pybin"
    fi
    echo "  Offline bundles ($DATA)"
    local found=0 m
    for m in "$DATA"/*/manifest.json; do
        [[ -f "$m" ]] || continue; found=1
        py - "$m" <<'EOF' 2>/dev/null || echo "    $(basename "$(dirname "$m")")"
import json, sys
m = json.load(open(sys.argv[1]))
print(f"    {m['suite']}-{m['arch']}: {', '.join(m['components'])} · {m['debs']} debs · Python {m['python']} · {m['created']}")
EOF
    done
    for m in "$DATA"/smms-offline-*.tar; do [[ -f "$m" ]] && { found=1; echo "    $(basename "$m")"; }; done
    [[ $found -eq 1 ]] || echo "    none"
    echo "  This machine needs: $(os_codename)-$(deb_arch)"
}

# ── online install ───────────────────────────────────────────────────────────────────────────────────────────
cmd_online() {
    need_root online
    command -v apt-get >/dev/null || die "apt-get not found (Debian-based systems only)"
    choose_components
    info "Components: $COMPONENTS"
    info "apt-get update..."
    apt-get update -q || die "apt-get update failed (no internet? use: sudo $0 offline)"
    info "Installing packages:$(selected_pkgs)"
    # shellcheck disable=SC2046
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends $(selected_pkgs) || die "apt-get install failed"
    info "Installing Flask 3 (pip)..."
    # shellcheck disable=SC2046
    python3 -m pip install -q $(pip_flags) "${WHEELS[@]}" || die "pip install failed"
    ok "Dependencies installed: $(flask_ver | cut -d' ' -f1 | sed 's/^/Flask /')"
    service_step
}

# ── offline install ──────────────────────────────────────────────────────────────────────────────────────────
find_bundle() {   # sets BUNDLE to a directory with manifest.json
    local want; want="$(os_codename)-$(deb_arch)"
    if [[ -n "$BUNDLE" ]]; then
        [[ -e "$BUNDLE" ]] || die "$BUNDLE not found"
        BUNDLE="$(readlink -f "$BUNDLE")"
        if [[ -f "$BUNDLE" ]]; then
            local tag; tag="$(tar -tf "$BUNDLE" | head -1 | cut -d/ -f1)"
            [[ -n "$tag" ]] || die "$BUNDLE is not a bundle archive"
            info "Unpacking $(basename "$BUNDLE") into $DATA..."
            mkdir -p "$DATA" && tar -xf "$BUNDLE" -C "$DATA" || die "cannot unpack $BUNDLE"
            BUNDLE="$DATA/$tag"
        fi
    else
        if [[ ! -f "$DATA/$want/manifest.json" && -f "$DATA/smms-offline-$want.tar" ]]; then
            info "Unpacking smms-offline-$want.tar..."
            tar -xf "$DATA/smms-offline-$want.tar" -C "$DATA" || die "cannot unpack the bundle"
        fi
        BUNDLE="$DATA/$want"
    fi
    if [[ ! -f "$BUNDLE/manifest.json" ]]; then
        echo "No offline bundle for this machine ($want) in $DATA." >&2
        echo "Build one on a PC with internet:  ./install.sh bundle --arch $(deb_arch) --suite $(os_codename)" >&2
        echo "and copy setup_data/smms-offline-$want.tar here (or pass --bundle FILE)." >&2
        exit 1
    fi
    local b_arch b_suite
    b_arch="$(grep -m1 '"arch"' "$BUNDLE/manifest.json" | cut -d'"' -f4)"
    b_suite="$(grep -m1 '"suite"' "$BUNDLE/manifest.json" | cut -d'"' -f4)"
    [[ "$b_arch" == "$(deb_arch)" ]] || die "bundle is for $b_arch, this machine is $(deb_arch)"
    if [[ "$b_suite" != "$(os_codename)" ]]; then
        warn "bundle is for Debian $b_suite, this system is $(os_codename) — packages may not fit."
        ask "Use it anyway?" n || exit 1
    fi
}

cmd_offline() {
    need_root offline
    find_bundle
    local comps avail
    comps="$(manifest_list "$BUNDLE/manifest.json" components)"
    avail="$(manifest_list "$BUNDLE/manifest.json" packages | tr , ' ')"
    info "Bundle: $BUNDLE ($comps)"
    if [[ -z "$COMPONENTS" ]]; then
        if [[ $YES -eq 1 ]]; then COMPONENTS="$comps"; else choose_components; fi
    fi
    check_components
    local c
    for c in ${COMPONENTS//,/ }; do
        [[ ,$comps, == *,$c,* ]] || die "component '$c' is not in this bundle (it has: $comps)"
    done

    local tmp; tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"; trap - RETURN' RETURN
    mkdir -p "$tmp/lists/partial" "$tmp/archives/partial"
    echo "deb [trusted=yes] file:$BUNDLE/debs ./" >"$tmp/sources.list"
    local o=(-o "Dir::Etc::SourceList=$tmp/sources.list" -o "Dir::Etc::SourceParts=/dev/null"
             -o "Dir::State::Lists=$tmp/lists" -o "Dir::Cache=$tmp" -o "Dir::Cache::archives=$tmp/archives"
             -o "APT::Install-Recommends=false" -o "Acquire::Languages=none")
    info "Reading the bundle's package index..."
    apt-get "${o[@]}" update -q >/dev/null || die "cannot read $BUNDLE/debs"
    info "Installing packages:$(selected_pkgs "$avail")"
    # shellcheck disable=SC2046
    DEBIAN_FRONTEND=noninteractive apt-get "${o[@]}" install -y -q $(selected_pkgs "$avail") \
        || die "apt-get install failed — the system may lack a base package the bundle assumes (see above)"
    info "Installing Flask 3 from the bundle's wheels..."
    # shellcheck disable=SC2046
    python3 -m pip install -q --no-index --find-links "$BUNDLE/wheels" $(pip_flags) "${WHEELS[@]}" || die "pip install failed"
    ok "Dependencies installed: $(flask_ver | cut -d' ' -f1 | sed 's/^/Flask /')"
    service_step
}

# ── offline bundle ───────────────────────────────────────────────────────────────────────────────────────────
cmd_bundle() {
    local args=("$@")
    if [[ ${#args[@]} -eq 0 && -t 0 && $YES -eq 0 ]]; then
        local arch suite
        echo "Targets: armhf = Allwinner H3 (32-bit), arm64 = Allwinner H5 (64-bit); x86 machines install online."
        read -r -p "Architectures [armhf,arm64]: " arch </dev/tty || arch=""
        read -r -p "Debian release of the targets [bookworm]: " suite </dev/tty || suite=""
        choose_components
        args=(--arch "${arch:-armhf,arm64}" --suite "${suite:-bookworm}" --components "$COMPONENTS")
    elif [[ -n "$COMPONENTS" ]]; then
        args+=(--components "$COMPONENTS")
    fi
    command -v python3 >/dev/null || die "python3 is needed to build a bundle"
    python3 "$DIR/tools/offline_bundle.py" --out "$DATA" "${args[@]}" || exit 1
    # Built with sudo: give the files back to the user.
    [[ $EUID -eq 0 && -n "${SUDO_USER:-}" ]] && chown -R "$SUDO_USER": "$DATA"
    return 0
}

# ── systemd unit ─────────────────────────────────────────────────────────────────────────────────────────────
unit_text() {
    cat <<EOF
[Unit]
Description=SystemMngmntService — device management web panel
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$DIR
ExecStart=$(command -v python3) $DIR/app.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
}

cmd_service() {
    need_root service
    [[ -f "$DIR/app.py" ]] || die "app.py not found in $DIR"
    command -v python3 >/dev/null || die "python3 is not installed (run: sudo $0 online|offline)"
    local tmp; tmp="$(mktemp)"
    unit_text >"$tmp"
    if cmp -s "$tmp" "$UNIT_FILE"; then
        rm -f "$tmp"; info "Unit is up to date: $UNIT_FILE"
    else
        if [[ -f "$UNIT_FILE" ]]; then
            echo "Unit changes:"; diff -u "$UNIT_FILE" "$tmp" | tail -n +3 | sed 's/^/    /'
        fi
        install -m 0644 "$tmp" "$UNIT_FILE" && rm -f "$tmp"
        systemctl daemon-reload
        ok "Unit written: $UNIT_FILE"
    fi
    systemctl is-enabled -q "$UNIT" 2>/dev/null || { systemctl enable -q "$UNIT" && ok "Enabled at boot"; }
    if systemctl is-active -q "$UNIT"; then
        if ask "The panel is running. Restart it now to apply the changes (it is unavailable for a few seconds)?" y; then
            systemctl restart "$UNIT" && ok "Restarted"
        else
            info "Not restarted — later: sudo systemctl restart $UNIT"
        fi
    else
        systemctl start "$UNIT" && ok "Started"
    fi
    sleep 1
    systemctl --no-pager -l status "$UNIT" | head -5
    echo "  Panel: http://$(hostname -I 2>/dev/null | awk '{print $1}'):$(panel_port)/   Logs: journalctl -u $UNIT -f"
}

service_step() {   # after an install: set up the unit if wanted
    if [[ -f "$UNIT_FILE" ]] || ask "Install and start the systemd service now?" y; then cmd_service; fi
}

cmd_uninstall() {
    need_root uninstall
    [[ -f "$UNIT_FILE" ]] || { info "The service is not installed"; return 0; }
    ask "Stop the panel and remove $UNIT? (the project, config.json and packages stay)" n || return 0
    systemctl disable --now -q "$UNIT" 2>/dev/null
    rm -f "$UNIT_FILE" && systemctl daemon-reload
    ok "Service removed. Reinstall: sudo $0 service"
}

# ── menu ─────────────────────────────────────────────────────────────────────────────────────────────────────
menu() {
    local choice items=(
        status    "Status: what is installed, service state, bundles"
        online    "Install / update from the internet (apt + pip)"
        offline   "Install / update from an offline bundle (setup_data/)"
        bundle    "Build offline bundles for H3 (armhf) / H5 (arm64)"
        service   "Install / update the systemd service and restart"
        uninstall "Remove the systemd service"
        quit      "Exit"
    )
    while true; do
        if [[ $UI == whiptail ]]; then
            choice=$(whiptail --title "SystemMngmntService installer" --menu "$(os_name) · $(deb_arch)\n$DIR" 18 76 7 \
                     "${items[@]}" 3>&1 1>&2 2>&3) || return 0
        else
            echo; echo "${C_B}SystemMngmntService installer${C_0} — $(os_name) · $(deb_arch)"
            local i; for ((i = 0; i < ${#items[@]}; i += 2)); do printf "  %d) %-10s %s\n" $((i / 2 + 1)) "${items[i]}" "${items[i + 1]}"; done
            read -r -p "Choice: " i </dev/tty || return 0
            [[ $i =~ ^[0-9]+$ && $i -ge 1 && $i -le $((${#items[@]} / 2)) ]] || continue
            choice="${items[(i - 1) * 2]}"
        fi
        COMPONENTS=""
        case "$choice" in
            quit) return 0 ;;
            status) cmd_status ;;
            *) if [[ $choice != bundle && $EUID -ne 0 ]]; then warn "needs root: sudo $0"; else ( "cmd_$choice" ); fi ;;
        esac
        [[ $UI == whiptail ]] && { read -r -p "Press Enter to return to the menu..." _ </dev/tty || return 0; }
    done
}

# ── arguments ────────────────────────────────────────────────────────────────────────────────────────────────
main() {
    local cmd="" rest=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -y|--yes) YES=1 ;;
            --components) COMPONENTS="${2:?}"; shift ;;
            --components=*) COMPONENTS="${1#*=}" ;;
            --bundle) BUNDLE="${2:?}"; shift ;;
            --bundle=*) BUNDLE="${1#*=}" ;;
            --plain) UI=plain ;;
            -h|--help) sed -n '2,/^# =\{5,\}$/p' "$0" | sed '1d;$d;s/^# \{0,1\}//'; exit 0 ;;
            status|online|offline|bundle|service|uninstall|menu) cmd="$1" ;;
            --status|--online|--offline|--service|--uninstall) cmd="${1#--}" ;;
            *) [[ $cmd == bundle ]] && rest+=("$1") || die "unknown argument: $1 (see $0 --help)" ;;
        esac
        shift
    done
    if [[ -z $UI ]]; then
        if [[ -t 0 && -t 1 ]] && command -v whiptail >/dev/null; then UI=whiptail; else UI=plain; fi
    fi
    case "${cmd:-menu}" in
        menu)
            [[ -t 0 ]] || die "no command given and no terminal for the menu (see $0 --help)"
            menu ;;
        bundle) cmd_bundle "${rest[@]}" ;;
        *) "cmd_$cmd" ;;
    esac
}

main "$@"
