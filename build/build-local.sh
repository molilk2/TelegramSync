#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

rm -rf build-cache dist out
find . -type d -name '__pycache__' -prune -exec rm -rf {} +

python -m PyInstaller --clean --workpath build-cache/server --distpath dist build/tg-server.spec
python -m PyInstaller --clean --workpath build-cache/cli --distpath dist build/tg-cli.spec

test -f dist/tg-server
mkdir -p out/linux
cp dist/tg-server out/linux/
cp dist/tg-cli out/linux/
cp README.md out/linux/
[ -f docs.md ] && cp docs.md out/linux/
chmod +x out/linux/tg-server out/linux/tg-cli

tar -C out/linux -czf out/tg-linux-x86_64.tar.gz .
echo "Built: out/tg-linux-x86_64.tar.gz"
