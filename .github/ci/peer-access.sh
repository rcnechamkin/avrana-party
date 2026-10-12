#!/usr/bin/env bash
# Read access to the OTHER private repository from CI (AVR-428). Identical in avrana-party and
# avrana-party-games; one mechanism only: a read-only deploy key over SSH.
#
# Runs before any test step so that a red job is unambiguous: every failure here is printed as
# "ACCESS PROBLEM", names the secret and the documentation section, and is a credential/access
# fault, never a test failure. It lists the other repository's branches (ls-remote), which proves
# the key works, and resolves the branch to check out (the one carrying this branch's AVR number,
# otherwise main). A failure to list must fail the job: falling back to main would report
# compatibility that was never checked against the paired branch.
#
# Inputs (environment): PEER_REPO owner/name, PEER_KEY (private key text, from a secret),
# SECRET_NAME, DOC, BRANCH (may be empty: ref is then main), IS_FORK ('true' on a fork PR).
# Output: ref=<branch> on $GITHUB_OUTPUT. The key lives in a private temp directory removed on exit
# and is never printed, written to .git/config, or exported to later steps. No `set -x`.
set -euo pipefail

: "${PEER_REPO:?}" "${SECRET_NAME:?}" "${DOC:?}"
fail() { echo "::error::ACCESS PROBLEM (credentials, not a test failure): $* See $DOC"; exit 1; }

if [ -z "${PEER_KEY:-}" ]; then
  if [ "${IS_FORK:-}" = true ]; then
    fail "this pull request comes from a fork, and GitHub withholds secrets (including $SECRET_NAME) from fork runs, so $PEER_REPO cannot be read. A maintainer must run this check from a branch of this repository."
  fi
  fail "the secret $SECRET_NAME is empty or not set for this repository, so $PEER_REPO cannot be read."
fi

umask 077
dir=$(mktemp -d "${RUNNER_TEMP:-/tmp}/peer.XXXXXX")
trap 'rm -rf "$dir"' EXIT
printf '%s\n' "$PEER_KEY" > "$dir/key"
# GitHub's published SSH host keys (https://api.github.com/meta, "ssh_keys"), pinned here so no
# host key is trusted on first use.
cat > "$dir/known_hosts" <<'HOSTS'
github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl
github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=
github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CSSNY7GidjMIZ7Q4zMjA2n1nGrlTDkzwDCsw+wqFPGQA179cnfGWOWRVruj16z6XyvxvjJwbz0wQZ75XK5tKSb7FNyeIEs4TT4jk+S4dhPeAUC5y+bDYirYgM4GC7uEnztnZyaVWQ7B381AK4Qdrwt51ZqExKbQpTUNn+EjqoTwvqNj4kqx5QUCI0ThS/YkOxJCXmPUWZbhjpCg56i+2aB6CmK2JGhn57K5mj0MNdBXA4/WnwH6XoPWJzK5Nyu2zB3nAZp+S5hpQs+p1vN1/wsjk=
HOSTS
export GIT_SSH_COMMAND="ssh -i $dir/key -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$dir/known_hosts -o GlobalKnownHostsFile=/dev/null"

if ! out=$(git ls-remote --heads "git@github.com:$PEER_REPO.git" 2>"$dir/err"); then
  if grep -qiE 'libcrypto|invalid format|incorrect passphrase|no such identity' "$dir/err"; then
    fail "the value of $SECRET_NAME is not a usable private key (it must be the full OpenSSH key text, BEGIN and END lines included, with no passphrase)."
  elif grep -qiE 'host key verification failed|REMOTE HOST IDENTIFICATION' "$dir/err"; then
    fail "the pinned github.com SSH host keys in .github/ci/peer-access.sh no longer match; refresh them from https://api.github.com/meta."
  elif grep -qiE 'permission denied|repository not found' "$dir/err"; then
    fail "GitHub refused the key in $SECRET_NAME for $PEER_REPO (permission denied or repository not found): the matching public key is not added as a deploy key on $PEER_REPO, or it was deleted, or the secret holds a different key."
  fi
  echo "ssh/git said (last lines):"; tail -n 3 "$dir/err" | sed 's/^/  /'
  fail "could not list the branches of $PEER_REPO for a reason other than a rejected key (network or GitHub outage?); this is not a test failure."
fi
heads=$(printf '%s\n' "$out" | awk '{print $2}' | sed 's#refs/heads/##')
[ -n "$heads" ] || fail "$PEER_REPO lists no branches."

BRANCH=${BRANCH:-}
avr=$(echo "$BRANCH" | grep -oiE 'avr-[0-9]+' | head -1 | tr 'A-Z' 'a-z' || true)
ref=main; why='no AVR id in this branch name'
if [ -n "$avr" ]; then
  why="no branch of $PEER_REPO carries $avr"
  if echo "$heads" | grep -qxF "$BRANCH"; then
    ref=$BRANCH; why='same branch name'
  else
    match=$(echo "$heads" | grep -iE "(^|[/-])${avr}([-/]|$)" | sort | head -1 || true)
    if [ -n "$match" ]; then ref=$match; why="first branch carrying $avr"; fi
  fi
fi
echo "ref=$ref" >> "$GITHUB_OUTPUT"
echo "Access to $PEER_REPO verified. Ref for this run: $ref ($why)" | tee -a "$GITHUB_STEP_SUMMARY"
