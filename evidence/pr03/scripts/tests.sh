#!/usr/bin/env bash
# Сборка и тесты ПР03 с сохранением реального вывода в evidence/pr03/tests.txt.
# Запуск из корня репозитория:  bash evidence/pr03/scripts/tests.sh
set -o pipefail
set +u
source /opt/ros/jazzy/setup.bash

OUT=evidence/pr03/tests.txt
mkdir -p evidence/pr03
: > "$OUT"

step() {
    printf '$ %s\n' "$*" | tee -a "$OUT"
    "$@" 2>&1 | tee -a "$OUT"
    local rc=${PIPESTATUS[0]}
    printf '[exit=%s]\n\n' "$rc" | tee -a "$OUT"
    return "$rc"
}

step colcon build --symlink-install --packages-select patrol || exit 1
source install/setup.bash
step python3 -m pytest -v src/patrol/test || exit 1
step colcon test --packages-select patrol || exit 1
step colcon test-result --verbose --test-result-base build/patrol || exit 1
echo "saved: $OUT"
