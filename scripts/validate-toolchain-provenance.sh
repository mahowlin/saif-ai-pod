#!/usr/bin/env bash
set -euo pipefail

CLUSTER="${1:?cluster name required}"
EXPECTED_ARCH="${2:-x86_64}"
CONTAINER_IMAGE="${RUNNER_CONTAINER_IMAGE:?actual runner image input is required}"
DATA_DIR="data/openshift/${CLUSTER}"
METADATA="${DATA_DIR}/metadata.yaml"
INSTALL_CONFIG="${DATA_DIR}/install-config.yaml"
SUMMARY_FILE="${GITHUB_STEP_SUMMARY:-/dev/stdout}"
TOOL_DIR="${GITHUB_WORKSPACE:-$(pwd)}/.ocp-tools/${CLUSTER}"

fail() {
  echo "❌ $*" | tee -a "$SUMMARY_FILE"
  exit 1
}

note() {
  echo "$*" >> "$SUMMARY_FILE"
}

command_version() {
  local cmd="$1"
  if command -v "$cmd" >/dev/null 2>&1; then
    "$cmd" "$@" 2>/dev/null || true
  fi
}

container_digest() {
  if command -v crane >/dev/null 2>&1; then
    crane digest "$CONTAINER_IMAGE" 2>/dev/null && return 0
  fi
  if command -v skopeo >/dev/null 2>&1; then
    skopeo inspect --format '{{.Digest}}' "docker://${CONTAINER_IMAGE}" 2>/dev/null && return 0
  fi
  if command -v docker >/dev/null 2>&1; then
    docker buildx imagetools inspect "$CONTAINER_IMAGE" --format '{{json .Manifest.Digest}}' 2>/dev/null | tr -d '"' && return 0
  fi
  return 1
}

if [ ! -f "$METADATA" ]; then
  fail "metadata file not found: \`$METADATA\`"
fi
if [ ! -f "$INSTALL_CONFIG" ]; then
  fail "install-config file not found: \`$INSTALL_CONFIG\`"
fi

if [ -n "${REGISTRY_CA_CERT:-}" ] && [ -w /usr/local/share/ca-certificates ]; then
  echo "$REGISTRY_CA_CERT" > /usr/local/share/ca-certificates/registry.crt
  update-ca-certificates >/dev/null
fi

OCP_VERSION=$(yq -r '.ocpVersion' "$METADATA")
if [ -z "$OCP_VERSION" ] || [ "$OCP_VERSION" = "null" ]; then
  fail "metadata.ocpVersion is empty in \`$METADATA\`"
fi

REGISTRY_MIRROR=$(yq -r '.imageDigestSources[0].mirrors[0]' "$INSTALL_CONFIG")
REGISTRY_HOST=$(echo "$REGISTRY_MIRROR" | cut -d: -f1)
REGISTRY_PORT=$(echo "$REGISTRY_MIRROR" | cut -d: -f2 | cut -d/ -f1)
REGISTRY="${REGISTRY_HOST}:${REGISTRY_PORT}"
RELEASE_TAG="${OCP_VERSION}-${EXPECTED_ARCH}"
RELEASE_IMAGE_TAGGED="${REGISTRY}/openshift/release-images:${RELEASE_TAG}"

note ""
note "## OpenShift Toolchain Provenance"
note ""
note "| Item | Value |"
note "| --- | --- |"
note "| Container identity | selected executor input; digest lookup is registry resolution, not runtime attestation |"
note "| GitHub Actions container image | \`${CONTAINER_IMAGE}\` |"
DIGEST="$(container_digest || true)"
if [ -n "$DIGEST" ]; then
  note "| Selected image registry digest | \`${DIGEST}\` |"
else
  note "| Selected image registry digest | not discoverable from this runner |"
fi

PREINSTALLED_INSTALLER_VERSION="$(openshift-install version 2>/dev/null | awk 'NR==1 {print $2}' || true)"
PREINSTALLED_OC_VERSION="$(oc version --client -o json 2>/dev/null | jq -r '.clientVersion.gitVersion // empty' | sed 's/^v//' || true)"
if [ -z "$PREINSTALLED_OC_VERSION" ]; then
  PREINSTALLED_OC_VERSION="$(oc version --client 2>/dev/null | awk -F': ' '/Client Version/ {print $2}' | sed 's/^v//' || true)"
fi
note "| Preinstalled openshift-install | \`${PREINSTALLED_INSTALLER_VERSION:-unknown}\` |"
note "| Preinstalled oc | \`${PREINSTALLED_OC_VERSION:-unknown}\` |"
note "| metadata.ocpVersion | \`${OCP_VERSION}\` |"
note "| Expected payload architecture | \`${EXPECTED_ARCH}\` |"

if [ -n "$PREINSTALLED_INSTALLER_VERSION" ] && [ "$PREINSTALLED_INSTALLER_VERSION" != "$OCP_VERSION" ]; then
  note "| Preinstalled tool policy | warn-only; selected payload extractor is authoritative |"
else
  note "| Preinstalled tool policy | matches or unavailable; selected payload extractor remains authoritative |"
fi

RELEASE_IMAGE_INFO=$(oc image info "$RELEASE_IMAGE_TAGGED" --insecure=false -o json)
RELEASE_DIGEST=$(echo "$RELEASE_IMAGE_INFO" | jq -r '.digest // empty')
if [ -z "$RELEASE_DIGEST" ] || [ "$RELEASE_DIGEST" = "null" ]; then
  fail "Could not resolve digest for selected release image: \`$RELEASE_IMAGE_TAGGED\`"
fi
RELEASE_IMAGE_BY_DIGEST="${REGISTRY}/openshift/release-images@${RELEASE_DIGEST}"
note "| Selected release digest | \`${RELEASE_DIGEST}\` |"
note "| Selected release pullspec | \`${RELEASE_IMAGE_BY_DIGEST}\` |"

PAYLOAD_VERSION_LABEL=$(echo "$RELEASE_IMAGE_INFO" | jq -r '.config.config.Labels["io.openshift.release"] // .config.config.Labels["version"] // empty')
PAYLOAD_ARCH_LABEL=$(echo "$RELEASE_IMAGE_INFO" | jq -r '.config.config.Labels["release.openshift.io/architecture"] // .config.config.Labels["io.openshift.release.architecture"] // empty')
if [ -z "$PAYLOAD_ARCH_LABEL" ]; then
  PAYLOAD_ARCH_LABEL=$(echo "$RELEASE_TAG" | sed "s/^${OCP_VERSION}-//")
fi
note "| Payload version label | \`${PAYLOAD_VERSION_LABEL:-empty}\` |"
note "| Payload architecture label | \`${PAYLOAD_ARCH_LABEL:-empty}\` |"

if [ "$PAYLOAD_VERSION_LABEL" != "$OCP_VERSION" ]; then
  fail "Release payload version label mismatch: expected \`${OCP_VERSION}\`, got \`${PAYLOAD_VERSION_LABEL:-empty}\`"
fi
if [ "$PAYLOAD_ARCH_LABEL" != "$EXPECTED_ARCH" ]; then
  fail "Release payload architecture mismatch: expected \`${EXPECTED_ARCH}\`, got \`${PAYLOAD_ARCH_LABEL:-empty}\`"
fi

IDMS_FILE=$(mktemp)
trap 'rm -f "$IDMS_FILE"' EXIT
cat > "$IDMS_FILE" <<EOF_IDMS
apiVersion: config.openshift.io/v1
kind: ImageDigestMirrorSet
metadata:
  name: local-mirror
spec:
  imageDigestMirrors:
  - mirrors:
    - ${REGISTRY}/openshift/release-images
    source: quay.io/openshift-release-dev/ocp-release
    mirrorSourcePolicy: NeverContactSource
  - mirrors:
    - ${REGISTRY}/openshift/release
    source: quay.io/openshift-release-dev/ocp-v4.0-art-dev
    mirrorSourcePolicy: NeverContactSource
EOF_IDMS

mkdir -p "$TOOL_DIR"
oc adm release extract "$RELEASE_IMAGE_BY_DIGEST" \
  --command=openshift-install \
  --command-os=linux/amd64 \
  --to="$TOOL_DIR" \
  --idms-file="$IDMS_FILE" \
  --insecure=false
rm -f "$IDMS_FILE"
chmod +x "$TOOL_DIR/openshift-install"

EXTRACTED_INSTALLER_VERSION=$("$TOOL_DIR/openshift-install" version | awk 'NR==1 {print $2}')
note "| Extracted openshift-install | \`${EXTRACTED_INSTALLER_VERSION}\` |"
if [ "$EXTRACTED_INSTALLER_VERSION" != "$OCP_VERSION" ]; then
  fail "Extracted openshift-install version mismatch: expected \`${OCP_VERSION}\`, got \`${EXTRACTED_INSTALLER_VERSION}\`"
fi

note ""
note "✅ Toolchain provenance validated against selected OpenShift release payload."
