#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$root"

offline=false
if [ "${1:-}" = "--offline" ]; then offline=true; fi
command -v docker >/dev/null 2>&1 || { echo "Docker with Compose v2 is required." >&2; exit 2; }
docker compose version >/dev/null
[ -f release.env ] || { echo "release.env is missing. Use a complete DramaForge release bundle." >&2; exit 2; }

release_value() {
    sed -n "s/^$1=//p" release.env | tail -n 1
}
version=$(release_value DRAMAFORGE_VERSION)
source_commit=$(release_value DRAMAFORGE_SOURCE_COMMIT)
backend_image=$(release_value DRAMAFORGE_BACKEND_IMAGE)
frontend_image=$(release_value DRAMAFORGE_FRONTEND_IMAGE)
[ -n "$version" ] && [ -n "$backend_image" ] && [ -n "$frontend_image" ] || {
    echo "release.env is incomplete." >&2; exit 2;
}
case "$source_commit" in
    *[!0-9a-f]*|'') echo "release.env has an invalid source commit." >&2; exit 2 ;;
esac
[ "${#source_commit}" -eq 40 ] || { echo "release.env has an invalid source commit." >&2; exit 2; }

if [ "$offline" = true ]; then
    [ -f images.tar ] || {
        echo "images.tar is missing. Use the complete offline release bundle." >&2; exit 2;
    }
    docker load --input images.tar
fi

if [ ! -f .env ]; then
    if [ "$offline" = false ]; then docker pull "$backend_image"; fi
    temp_env=.env.installing
    trap 'rm -f "$temp_env"' EXIT HUP INT TERM
    docker run --rm -i "$backend_image" python -m app.install_env \
        --version "$version" \
        --source-commit "$source_commit" \
        --backend-image "$backend_image" \
        --frontend-image "$frontend_image" \
        < .env.example > "$temp_env"
    chmod 600 "$temp_env"
    mv "$temp_env" .env
    trap - EXIT HUP INT TERM
else
    temp_env=.env.updating.$$
    trap 'rm -f "$temp_env"' EXIT HUP INT TERM
    awk -v version="$version" -v source_commit="$source_commit" \
        -v backend_image="$backend_image" -v frontend_image="$frontend_image" '
        BEGIN {
            values["DRAMAFORGE_VERSION"] = version
            values["DRAMAFORGE_SOURCE_COMMIT"] = source_commit
            values["DRAMAFORGE_BACKEND_IMAGE"] = backend_image
            values["DRAMAFORGE_FRONTEND_IMAGE"] = frontend_image
        }
        {
            split($0, parts, "=")
            if (parts[1] in values) {
                print parts[1] "=" values[parts[1]]
                seen[parts[1]] = 1
            } else {
                print
            }
        }
        END {
            for (name in values) if (!(name in seen)) print name "=" values[name]
        }
    ' .env > "$temp_env"
    chmod 600 "$temp_env"
    mv "$temp_env" .env
    trap - EXIT HUP INT TERM
    echo "Updated release identity; existing secrets and Provider settings were preserved."
fi

set -- --env-file .env -f docker-compose.yml
if [ "$offline" = true ]; then
    set -- "$@" -f docker-compose.offline.yml
else
    docker compose "$@" pull
fi
docker compose "$@" up -d --wait --no-build
port=$(sed -n 's/^DRAMAFORGE_PORT=//p' .env | tail -n 1)
echo "DramaForge is ready at http://localhost:${port:-8080}"
