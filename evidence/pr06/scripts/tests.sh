#!/usr/bin/env bash
# Проверка модели ПР06 с сохранением реального вывода:
#   fixed  — xacro → check_urdf → тесты course_description → evidence/pr06/model-check.txt;
#   defect — ветка pr06-defect (parent лидара — camera_link): check_urdf проходит, тесты падают
#            → evidence/pr06/logs/model-check-defect.txt.
# Запуск из корня репозитория:  bash evidence/pr06/scripts/tests.sh fixed|defect
set -o pipefail
set +u
source /opt/ros/jazzy/setup.bash

MODE=${1:-}
case "$MODE" in
    fixed | defect) ;;
    *) echo "использование: bash evidence/pr06/scripts/tests.sh fixed|defect" >&2; exit 2 ;;
esac
XACRO=src/course_description/urdf/vehicle.urdf.xacro
[ -f "$XACRO" ] || { echo "запускать из корня репозитория" >&2; exit 2; }
if grep -q 'ДЕФЕКТ ПР06' "$XACRO"; then CODE=defect; else CODE=fixed; fi
[ "$CODE" = "$MODE" ] || { echo "режим $MODE, а код в src/ — $CODE (git branch --show-current)" >&2; exit 2; }
# Проверка идёт только на закоммиченном коде: в файл записывается SHA этого коммита.
git diff --quiet HEAD -- src && [ -z "$(git ls-files --others --exclude-standard src)" ] \
    || { echo "в src/ есть незакоммиченные изменения (git status --short src): сначала коммит" >&2; exit 2; }

if [ "$MODE" = fixed ]; then OUT=evidence/pr06/model-check.txt; else OUT=evidence/pr06/logs/model-check-defect.txt; fi
mkdir -p evidence/pr06/logs
printf '# mode: %s, branch: %s, HEAD: %s\n\n' "$MODE" "$(git branch --show-current)" "$(git rev-parse HEAD)" > "$OUT"

step() {
    printf '$ %s\n' "$*" | tee -a "$OUT"
    "$@" 2>&1 | tee -a "$OUT"
    local rc=${PIPESTATUS[0]}
    printf '[exit=%s]\n\n' "$rc" | tee -a "$OUT"
    return "$rc"
}

step colcon build --symlink-install --packages-select course_description || exit 1
source install/setup.bash
step xacro "$XACRO" -o /tmp/vehicle.urdf || exit 1
step check_urdf /tmp/vehicle.urdf || exit 1
if [ "$MODE" = defect ]; then
    # Структура допустима, смысл — нет: check_urdf проходит, тесты геометрии падают.
    # Код pytest 1 — тесты собраны и часть упала; 0 — дефект не воспроизвёлся; иное — сбой запуска.
    step python3 -m pytest -v --tb=line src/course_description/test
    rc=$?
    [ "$rc" = 1 ] || { echo "ОШИБКА: ожидался код pytest 1 (упавшие тесты), получен $rc" >&2; exit 1; }
    echo "saved: $OUT (ожидаемо: check_urdf прошёл, тесты parent и положения лидара упали)"
    exit 0
fi
step python3 -m pytest -v src/course_description/test || exit 1
step colcon test --packages-select course_description || exit 1
step colcon test-result --verbose --test-result-base build/course_description || exit 1
echo "saved: $OUT"
