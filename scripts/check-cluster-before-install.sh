#!/usr/bin/env bash
# Copyright (c) 2026 Cisco and/or its affiliates.
# Licensed under the Cisco Sample Code License, Version 1.1. See LICENSE.
# Read only. Exit zero only after a successful privileged observation finds no
# installation kubeconfig. Existing/indeterminate installations require review.
set -euo pipefail
: "${CLUSTER_IP:?missing node address}" "${SSH_PRIVATE_KEY:?missing runtime key}"
case "$CLUSTER_IP" in
  *[!a-zA-Z0-9.:-]*|'') echo 'Invalid node address' >&2; exit 1 ;;
esac
umask 077
KEY=$(mktemp "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/install-observation.XXXXXX")
trap 'rm -f "$KEY"' EXIT
printf '%s\n' "$SSH_PRIVATE_KEY" > "$KEY"
SSH_ARGS=(-i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes)
if [ -n "${SSH_PROXY_JUMP:-}" ]; then
  SSH_ARGS+=(-J "$SSH_PROXY_JUMP")
fi
STATUS=0
ssh "${SSH_ARGS[@]}" "core@$CLUSTER_IP" 'sudo -n sh -s' <<'REMOTE' || STATUS=$?
set -eu
FOUND=0
for path in /opt/openshift/auth/kubeconfig /var/opt/openshift/auth/kubeconfig /etc/kubernetes/static-pod-resources/kube-apiserver-certs/secrets/node-kubeconfigs/localhost-recovery.kubeconfig /etc/kubernetes/kubeconfig; do
  if [ -e "$path" ]; then
    FOUND=1
    if [ -s "$path" ] && KUBECONFIG="$path" oc get --raw=/version >/dev/null 2>&1; then
      exit 0
    fi
  fi
done
# A present but unusable kubeconfig is an uncertain observation, not a fresh node.
[ "$FOUND" -eq 0 ] || exit 11
exit 10
REMOTE
case "$STATUS" in
  10) echo 'Privileged node observation succeeded: no known installation kubeconfig exists.' ;;
  0) echo 'ERROR: cluster API is operational; deployment blocked.' >&2; exit 1 ;;
  *) echo 'ERROR: installation state is indeterminate; deployment blocked.' >&2; exit 1 ;;
esac
