#!/usr/bin/env bash
# Сборка и тесты ПР04 с сохранением реального вывода в evidence/pr04/logs/tests-<режим>.txt.
#   fixed  — исправный код: сборка, pytest, colcon test; все тесты должны пройти;
#   defect — ветка pr04-defect: те же тесты, ожидаемо падают тесты частоты.
# Запуск из корня репозитория:  bash evidence/pr04/scripts/tests.sh fixed|defect
set -o pipefail
set +u
source /opt/ros/jazzy/setup.bash

MODE=${1:-}
case "$MODE" in
    fixed | defect) ;;
    *) echo "использование: bash evidence/pr04/scripts/tests.sh fixed|defect" >&2; exit 2 ;;
esac
[ -f src/patrol/patrol/parameters.py ] || { echo "запускать из корня репозитория" >&2; exit 2; }
if grep -q 'ДЕФЕКТ ПР04' src/patrol/patrol/parameters.py; then CODE=defect; else CODE=fixed; fi
[ "$CODE" = "$MODE" ] || { echo "режим $MODE, а код в src/ — $CODE (git branch --show-current)" >&2; exit 2; }
# Тесты идут только на закоммиченном коде: в лог записывается SHA этого коммита.
git diff --quiet HEAD -- src && [ -z "$(git ls-files --others --exclude-standard src)" ] \
    || { echo "в src/ есть незакоммиченные изменения (git status --short src): сначала коммит" >&2; exit 2; }

OUT=evidence/pr04/logs/tests-$MODE.txt
mkdir -p evidence/pr04/logs
{
    echo "# mode: $MODE, branch: $(git branch --show-current), HEAD: $(git rev-parse HEAD)"
    echo
} > "$OUT"

step() {
    printf '$ %s\n' "$*" | tee -a "$OUT"
    "$@" 2>&1 | tee -a "$OUT"
    local rc=${PIPESTATUS[0]}
    printf '[exit=%s]\n\n' "$rc" | tee -a "$OUT"
    return "$rc"
}

step colcon build --symlink-install --packages-select patrol || exit 1
source install/setup.bash
if [ "$MODE" = defect ]; then
    # Короткий traceback: по строке на упавший тест с конкретной ошибкой.
    # Код pytest 1 — тесты собраны и часть упала; 0 — дефект не воспроизвёлся; иное — сбой запуска.
    step python3 -m pytest -v --tb=line src/patrol/test
    rc=$?
    [ "$rc" = 1 ] || { echo "ОШИБКА: ожидался код pytest 1 (упавшие тесты), получен $rc" >&2; exit 1; }
    echo "saved: $OUT (ожидаемо: тесты частоты упали)"
    exit 0
fi
step python3 -m pytest -v src/patrol/test || exit 1
step colcon test --packages-select patrol || exit 1
step colcon test-result --verbose --test-result-base build/patrol || exit 1
echo "saved: $OUT"
