#!/bin/sh
# Build the image and smoke-test it without bind mounts.
# Startup needs a key; /health and /agents never call the model.
set -eu

image=${IMAGE:-agplat:smoke}
name=${CONTAINER:-agplat-smoke}
port=${PORT:-8011}
tries=${TRIES:-60}

cleanup() {
    docker rm -f "$name" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

cleanup
docker compose config >/dev/null
docker build -t "$image" .

docker run -d --name "$name" \
    -e DEEPSEEK_API_KEY=dummy \
    -p "127.0.0.1:$port:8000" \
    "$image" >/dev/null

i=0
while [ "$i" -lt "$tries" ]; do
    if curl -fsS "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
        break
    fi
    i=$((i + 1))
    sleep 0.5
done

health=$(curl -fsS "http://127.0.0.1:$port/health")
agents=$(curl -fsS "http://127.0.0.1:$port/agents")
echo "health: $health"
echo "agents: $agents"
echo "$health" | grep -q '"status":"ok"'
echo "$agents" | grep -q '"name":"assistant"'
