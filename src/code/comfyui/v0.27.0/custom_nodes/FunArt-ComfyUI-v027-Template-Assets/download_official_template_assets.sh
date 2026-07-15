#!/bin/sh
set -eu

PLUGIN_DIR=${1:-"$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"}
MANIFEST_PATH="${PLUGIN_DIR}/official_template_inputs.json"
ASSET_DIR="${PLUGIN_DIR}/bundled_template_assets"
REVISION=$(jq -e -r '.source.revision | select(type == "string" and length > 0)' "${MANIFEST_PATH}")
URL_PREFIX="https://raw.githubusercontent.com/Comfy-Org/workflow_templates/${REVISION}/input/"

mkdir -p "${ASSET_DIR}"

asset_list=$(mktemp)
temporary=""
cleanup() {
    rm -f "${asset_list}" "${temporary}"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

jq -e -r '
    if (.schema_version == 1 and (.assets | type) == "array" and (.assets | length) > 0)
    then .assets[] | [.filename, .url, .sha256, (.size | tostring)] | @tsv
    else error("invalid official template asset manifest")
    end
' "${MANIFEST_PATH}" > "${asset_list}"

while IFS="$(printf '\t')" read -r filename url expected_sha256 expected_size; do
    case "${filename}" in
        ""|.|..|*/*|*\\*)
            echo "Invalid official template asset filename: ${filename}" >&2
            exit 1
            ;;
    esac

    if [ "${url}" != "${URL_PREFIX}${filename}" ]; then
        echo "Official template asset URL is not pinned to ${REVISION}: ${url}" >&2
        exit 1
    fi

    destination="${ASSET_DIR}/${filename}"
    temporary="${destination}.download"
    rm -f "${temporary}"

    echo "Downloading pinned workflow template asset: ${filename}"
    wget -q -T 120 -t 3 -O "${temporary}" "${url}"

    actual_size=$(wc -c < "${temporary}" | tr -d ' ')
    if [ "${actual_size}" -ne "${expected_size}" ]; then
        echo "Size mismatch for ${filename}: expected ${expected_size}, got ${actual_size}" >&2
        rm -f "${temporary}"
        exit 1
    fi

    printf '%s  %s\n' "${expected_sha256}" "${temporary}" | sha256sum -c - >/dev/null
    chmod 0444 "${temporary}"
    mv "${temporary}" "${destination}"
    temporary=""
done < "${asset_list}"
