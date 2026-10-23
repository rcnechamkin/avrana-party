#!/usr/bin/env bash
# Make the appliance's systemd journal persistent and bounded (AVR-29). Owner-run on the Pi.
#
#   install-persistent-journal.sh preflight   read only: what is installed, what is effective, disk
#   sudo install-persistent-journal.sh install    install the drop-in, restart journald, verify;
#                                                 restores the previous file if verification fails
#   install-persistent-journal.sh verify      read only: is the journal persistent and bounded now
#   sudo install-persistent-journal.sh rollback   undo the last install (run again to step further back)
#
# install is idempotent: when the file is installed and journald already writes to /var/log/journal,
# nothing is restarted. Nothing here deletes a log. docs/runbooks/logs-and-retention.md has the
# whole procedure and the reboot proof. AVRANA_JOURNALD_ROOT points every path at a simulated host
# (tests only).
set -euo pipefail
PATH=$PATH:/usr/sbin:/usr/bin:/sbin:/bin

ROOT=${AVRANA_JOURNALD_ROOT:-}
ROOT_ARG=()
if [[ -n $ROOT ]]; then
    if [[ ! -d $ROOT || $(cd "$ROOT" && pwd -P) =~ ^/+$ ]]; then
        echo 'AVRANA_JOURNALD_ROOT must be an existing directory other than /' >&2
        exit 2
    fi
    # A simulated host must never reach the real journald: tests put stand-ins first on PATH.
    for tool in systemctl journalctl; do
        case $(command -v "$tool" || true) in
            /usr/*|/bin/*|/sbin/*|/lib/*) echo "AVRANA_JOURNALD_ROOT with the real $tool on PATH: refusing" >&2; exit 2 ;;
        esac
    done
    ROOT_ARG=(--root="$ROOT")
fi
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SOURCE=$SCRIPT_DIR/avrana-journald.conf
DEST=$ROOT/etc/systemd/journald.conf.d/avrana.conf
BACKUPS=$ROOT/var/backups/avrana-party
JOURNAL_DIR=$ROOT/var/log/journal
RUNTIME_DIR=$ROOT/run/log/journal

say() { printf '%s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

cat_config() { systemd-analyze cat-config "${ROOT_ARG[@]}" systemd/journald.conf 2>/dev/null; }

# The value journald uses for a key: the last assignment in systemd's own reading order of
# journald.conf and every drop-in (systemd-analyze cat-config prints them in that order).
effective() {
    cat_config | sed -n "s/^[[:space:]]*$1=[[:space:]]*//p" | tail -n 1 | tr -d '[:space:]'
}

need_root() {
    if [[ -z $ROOT && $EUID -ne 0 ]]; then
        echo "Run $1 as root (sudo)" >&2
        exit 2
    fi
}

check_source() {
    [[ -f $SOURCE ]] || fail "missing $SOURCE"
    grep -qx 'Storage=persistent' "$SOURCE" || fail "$SOURCE does not set Storage=persistent"
    for key in SystemMaxUse SystemKeepFree RuntimeMaxUse MaxFileSec; do
        grep -q "^$key=" "$SOURCE" || fail "$SOURCE does not bound $key"
    done
}

machine_id() { { tr -d '[:space:]' <"$ROOT/etc/machine-id"; } 2>/dev/null || true; }

preflight() {
    check_source
    say "systemd: $(systemctl --version 2>/dev/null | head -n 1 || echo unknown)"
    say 'journald drop-ins, in the order systemd applies them (a later file wins):'
    cat_config | sed -n 's/^# \(\/.*\.conf\)$/  \1/p' || true
    say "effective Storage: $(effective Storage || true) (journald's default when unset: auto)"
    say "effective SystemMaxUse: $(effective SystemMaxUse || true)"
    if [[ -f $DEST ]] && cmp -s "$SOURCE" "$DEST"; then
        say "installed $DEST: matches this release"
    elif [[ -f $DEST ]]; then
        say "installed $DEST: differs from this release (install would replace it, keeping a backup)"
    else
        say "installed $DEST: absent"
    fi
    say "free space under /var: $(df -h --output=avail "$ROOT/var" 2>/dev/null | tail -n 1 | tr -d ' ' || echo unknown) (journald keeps 1G free and uses at most 256M)"
    say "journal disk usage: $(journalctl --disk-usage 2>/dev/null || echo 'unknown (run as root or a member of adm)')"
    say "rsyslog: $(systemctl is-active rsyslog 2>/dev/null || true) (active means /var/log/syslog is a second persistent copy)"
}

# journald is writing to the card now: the system journal is under /var/log/journal and this boot's
# runtime journal under /run is gone (journald removes it when it flushes). A system.journal left
# from an earlier persistent period, with journald still volatile, does not pass.
writing_persistently() {
    local mid
    mid=$(machine_id)
    [[ -n $mid && -f $JOURNAL_DIR/$mid/system.journal && ! -e $RUNTIME_DIR/$mid/system.journal ]]
}

verify() {
    local ok=1 storage mid
    storage=$(effective Storage || true)
    if [[ $storage == persistent ]]; then say 'ok: effective Storage=persistent'; else say "NOT OK: effective Storage=${storage:-unset}"; ok=0; fi
    if [[ $(effective SystemMaxUse || true) == 256M && $(effective SystemKeepFree || true) == 1G ]]; then
        say 'ok: bounded (SystemMaxUse=256M, SystemKeepFree=1G)'
    else
        say 'NOT OK: the size bounds are not the effective values'; ok=0
    fi
    if [[ -f $DEST ]] && cmp -s "$SOURCE" "$DEST"; then say "ok: $DEST matches this release"; else say "NOT OK: $DEST does not match this release"; ok=0; fi
    mid=$(machine_id)
    if writing_persistently; then
        say "ok: journald writes $JOURNAL_DIR/$mid/system.journal (no runtime journal under /run)"
    else
        say "NOT OK: journald is not writing to $JOURNAL_DIR/${mid:-<machine-id>} yet (or still keeps a runtime journal under /run)"; ok=0
    fi
    say "journal disk usage: $(journalctl --disk-usage 2>/dev/null || echo unknown)"
    [[ $ok == 1 ]]
}

# Replace a file atomically (a crash leaves the old or the new file, never half of one), mode 0644.
put_file() {
    mkdir -p "$(dirname "$2")"
    cp "$1" "$2.new.$$"
    chmod 0644 "$2.new.$$"
    mv -f "$2.new.$$" "$2"
}

# Backups not yet rolled back, newest first. A rollback renames the one it used to *.restored, so a
# second rollback steps further back.
pending_backups() { ls -1d "$BACKUPS"/journald-* 2>/dev/null | grep -v '\.restored$' | sort -r || true; }

restore() {
    # $1: a backup directory written by install. It holds avrana.conf, or "absent" when there was none.
    if [[ -f $1/avrana.conf ]]; then
        put_file "$1/avrana.conf" "$DEST"
        say "restored $DEST from $1"
    elif [[ -f $1/absent ]]; then
        rm -f "$DEST"
        say "removed $DEST (there was none before $1)"
    else
        fail "$1 is not a journald backup"
    fi
    systemctl restart systemd-journald
}

activate() {
    systemctl restart systemd-journald
    journalctl --flush                      # move this boot's /run journal to /var/log/journal now
}

install_journal() {
    need_root install
    check_source
    if [[ -f $DEST ]] && cmp -s "$SOURCE" "$DEST" && [[ $(effective Storage || true) == persistent ]]; then
        if writing_persistently; then
            say "Already installed: $DEST matches, Storage=persistent is effective and journald writes to /var/log/journal; journald not restarted"
            verify
            return
        fi
        # Installed without being activated (a rebuild without --activate, a copy by hand).
        say "$DEST is installed but journald has not switched yet: restarting it and flushing (no file changed)"
        activate
        verify
        return
    fi
    local backup
    backup=$BACKUPS/journald-$(date -u +%Y%m%dT%H%M%SZ)-$$
    mkdir -p "$backup"
    chmod 0750 "$BACKUPS"
    chmod 0700 "$backup"
    if [[ -f $DEST ]]; then cp -p "$DEST" "$backup/avrana.conf"; else : >"$backup/absent"; fi
    say "backup: $backup"
    put_file "$SOURCE" "$DEST"
    activate
    if verify; then
        say "Installed. Rollback: sudo bash $0 rollback"
    else
        say 'Verification failed; putting the previous file back'
        restore "$backup"
        mv "$backup" "$backup.restored"
        exit 1
    fi
}

rollback() {
    need_root rollback
    local backup=${1:-}
    if [[ -z $backup ]]; then
        backup=$(pending_backups | head -n 1)
        [[ -n $backup ]] || fail "no backup under $BACKUPS that has not been rolled back: nothing to roll back to"
    fi
    restore "$backup"
    [[ $backup == *.restored ]] || mv "$backup" "$backup.restored"
    say "effective Storage now: $(effective Storage || true)"
    say "Kept: the journal files already under $JOURNAL_DIR (bounded, still readable with journalctl). Nothing was deleted."
}

case ${1:-} in
    preflight) preflight ;;
    verify) verify ;;
    install) install_journal ;;
    rollback) rollback "${2:-}" ;;
    *) echo "Usage: $0 preflight|install|verify|rollback [BACKUP_DIR]" >&2; exit 2 ;;
esac
