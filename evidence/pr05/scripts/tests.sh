#!/usr/bin/env bash
# Сборка и тесты всех пакетов (как в CI) с сохранением реального вывода в evidence/pr05/tests.txt.
# Запуск из корня репозитория:  bash evidence/pr05/scripts/tests.sh
set -o pipefail
set +u
source /opt/ros/jazzy/setup.bash

[ -f src/course_bringup/launch/patrol.launch.py ] || { echo "запускать из корня репозитория" >&2; exit 2; }
# Тесты идут только на закоммиченном коде: в файл записывается SHA этого коммита.
git diff --quiet HEAD -- src && [ -z "$(git ls-files --others --exclude-standard src)" ] \
    || { echo "в src/ есть незакоммиченные изменения (git status --short src): сначала коммит" >&2; exit 2; }

OUT=evidence/pr05/tests.txt
mkdir -p evidence/pr05
printf '# branch: %s, HEAD: %s\n\n' "$(git branch --show-current)" "$(git rev-parse HEAD)" > "$OUT"

step() {
    printf '$ %s\n' "$*" | tee -a "$OUT"
    "$@" 2>&1 | tee -a "$OUT"
    local rc=${PIPESTATUS[0]}
    printf '[exit=%s]\n\n' "$rc" | tee -a "$OUT"
    return "$rc"
}

step colcon build --symlink-install || exit 1
step colcon test --event-handlers console_direct+ || exit 1
step colcon test-result --verbose || exit 1
echo "saved: $OUT"
