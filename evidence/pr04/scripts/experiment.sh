#!/usr/bin/env bash
# Опыт ПР04 одной командой: параметры patrol на живой ноде с turtlesim.
#   fixed  — исправный код: 10 → 5 Гц, отказ для 0, отрицательного, NaN; скорости; /clear и действия;
#   defect — ветка pr04-defect (проверка частоты отключена): тот же ноль роняет ноду.
# Каждая команда пишется в logs/<режим>/*.txt вместе с выводом, кодом возврата и временем.
#
# Запуск из корня репозитория после colcon build (нужны patrol и turtle_bringup):
#   bash evidence/pr04/scripts/experiment.sh fixed     # ~1.5 мин
#   bash evidence/pr04/scripts/experiment.sh defect    # ~1 мин
# Перед запуском остановите turtlesim, teleop и patrol в этом домене (по умолчанию 16).
# Окно turtlesim откроется на текущем дисплее; без дисплея: QT_QPA_PLATFORM=offscreen.
set -u
set -m  # job control: у каждого фонового процесса своя группа и обычная реакция на SIGINT

MODE=${1:-}
case "$MODE" in
    fixed | defect) ;;
    *) echo "использование: bash evidence/pr04/scripts/experiment.sh fixed|defect" >&2; exit 2 ;;
esac
OUT=evidence/pr04/logs/$MODE
WORK=$(mktemp -d)                # новые логи; в $OUT попадут только после успешной проверки
PROC=$(mktemp -d)                # stdout/stderr процессов

set +u
source /opt/ros/jazzy/setup.bash
source install/setup.bash
set -u
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-16}

fail() {
    echo "ОШИБКА: $*" >&2
    echo "частичные логи: $WORK, вывод процессов: $PROC" >&2
    exit 1
}

[ -f src/patrol/patrol/parameters.py ] || fail "запускать из корня репозитория"
for pkg in patrol turtle_bringup; do
    ros2 pkg prefix "$pkg" > /dev/null 2>&1 || fail "пакет $pkg не найден: нужен colcon build и source install/setup.bash"
done
if grep -q 'ДЕФЕКТ ПР04' src/patrol/patrol/parameters.py; then CODE=defect; else CODE=fixed; fi
[ "$CODE" = "$MODE" ] || fail "режим $MODE, а код в src/ — $CODE (проверьте ветку: git branch --show-current)"
# Опыт идёт только на закоммиченном коде: в evidence записываются SHA и дифф этого коммита.
git diff --quiet HEAD -- src && [ -z "$(git ls-files --others --exclude-standard src)" ] \
    || fail "в src/ есть незакоммиченные изменения (git status --short src): сначала коммит"
if [ "$MODE" = defect ]; then
    git show HEAD -- src/patrol/patrol/parameters.py | grep -q '^+.*ДЕФЕКТ ПР04' \
        || fail "HEAD — не коммит дефекта: нужны git apply evidence/pr04/defect.patch и git commit"
fi

PGIDS=()
cleanup() {
    for pgid in "${PGIDS[@]}"; do kill -INT -- "-$pgid" 2>/dev/null; done
    sleep 2
    for pgid in "${PGIDS[@]}"; do kill -KILL -- "-$pgid" 2>/dev/null; done
    ros2 daemon stop > /dev/null 2>&1
}
trap cleanup EXIT
trap 'exit 130' INT TERM

now() { date +%T.%3N; }
STEP=0
TOTAL=$([ "$MODE" = fixed ] && echo 8 || echo 5)
progress() { STEP=$((STEP + 1)); echo "[$STEP/$TOTAL $(now)] $*"; }

# run FILE CMD... — дописать в FILE строку "$ CMD", вывод команды, код возврата и время.
run() {
    local file=$1; shift
    local rc
    {
        printf '$ %s\n' "$*"
        "$@" 2>&1
        rc=$?
        printf '[exit=%s, %s]\n\n' "$rc" "$(now)"
    } >> "$WORK/$file"
    return 0
}

# Запросы графа идут через ros2 daemon; его перезапуск сбрасывает кэш остановленных нод.
fresh_daemon() {
    ros2 daemon stop > /dev/null 2>&1
    ros2 daemon start > /dev/null 2>&1
}

# wait_node NAME... — дождаться, пока daemon увидит все ноды (до ~30 с)
wait_node() {
    local list name ok
    for _ in $(seq 30); do
        list=$(ros2 node list)
        ok=1
        for name in "$@"; do grep -qx "$name" <<< "$list" || ok=0; done
        [ $ok = 1 ] && { sleep 2; return 0; }
        sleep 1
    done
    fail "не появились в графе: $*"
}

# start NAME CMD... — запустить в фоне в своей группе процессов (как отдельный терминал).
start() {
    local name=$1; shift
    "$@" > "$PROC/$name.log" 2>&1 &
    local pgid=$!
    PGIDS+=("$pgid")
    printf -v "PGID_$name" '%s' "$pgid"
    printf '$ %s   # %s\n' "$*" "$(now)" >> "$WORK/processes.txt"
}

# stop NAME — Ctrl+C: SIGINT всей группе процессов
stop() {
    local var="PGID_$1"
    kill -INT -- "-${!var}" 2>/dev/null
    printf 'SIGINT -> %s   # %s\n' "$1" "$(now)" >> "$WORK/processes.txt"
}

# wait_exit NAME — дождаться завершения процесса (до 10 с) и записать его код возврата
wait_exit() {
    local var="PGID_$1"
    local rc
    for _ in $(seq 100); do
        if ! kill -0 -- "-${!var}" 2>/dev/null; then
            wait "${!var}"
            rc=$?
            printf '%s: завершился, код возврата %s   # %s\n' "$1" "$rc" "$(now)" >> "$WORK/processes.txt"
            return 0
        fi
        sleep 0.1
    done
    printf '%s: всё ещё работает через 10 с   # %s\n' "$1" "$(now)" >> "$WORK/processes.txt"
}

# alive NAME — жив ли процесс (для логов)
alive() {
    local var="PGID_$1"
    if kill -0 -- "-${!var}" 2>/dev/null; then echo "$1: процесс работает"; else echo "$1: процесса нет"; fi
}

# terminal_output NAME — что процесс напечатал в своём «терминале» (stdout и stderr)
terminal_output() {
    cat "$PROC/$1.log"
}

# Окно ros2 topic hz: первые ~2 с уходят на discovery, затем ~6 окон по 1 с.
HZ=(timeout -s INT 9s ros2 topic hz /turtle1/cmd_vel)
# ros2 param get/set по умолчанию ждут ноду 1 с; при медленном discovery это даёт
# «Node not found» на живой ноде, поэтому ждём до 5 с.
P=(--timeout 5)
GET_HZ=(ros2 param get /patrol publish_hz "${P[@]}")

{
    echo "date: $(date -Is)"
    echo "mode: $MODE"
    echo "branch: $(git branch --show-current)"
    echo "HEAD: $(git rev-parse HEAD)"
    echo "ROS_DISTRO=$ROS_DISTRO ROS_DOMAIN_ID=$ROS_DOMAIN_ID RMW=${RMW_IMPLEMENTATION:-default}"
    grep PRETTY_NAME /etc/os-release
    echo "kernel: $(uname -r)"
    echo "git status --short src: $(git status --short src | wc -l) changed paths"
} > "$WORK/env.txt"
if [ "$MODE" = defect ]; then
    run env.txt git log --oneline -3
    run env.txt git diff HEAD~1 HEAD -- src
fi

echo "ПР04, режим $MODE: логи появятся в $OUT. Окно turtlesim откроется само; ничего не нажимать."
progress "проверка, что домен $ROS_DOMAIN_ID пуст"
fresh_daemon
sleep 3
leftover=$(ros2 node list)
[ -z "$leftover" ] || fail "в домене $ROS_DOMAIN_ID уже есть ноды, остановите их: $(echo $leftover)"

progress "запуск turtlesim и patrol, параметры по умолчанию"
start sim ros2 launch turtle_bringup sim.launch.py
start patrol ros2 run patrol patrol --ros-args -r cmd_vel:=/turtle1/cmd_vel
fresh_daemon
wait_node /patrol /turtlesim
run 1-start.txt ros2 node list
run 1-start.txt ros2 topic type /turtle1/pose
if [ "$MODE" = fixed ]; then
    run 1-start.txt ros2 param list /patrol
    run 1-start.txt ros2 param describe /patrol publish_hz "${P[@]}"
    run 1-start.txt ros2 param get /patrol linear_speed "${P[@]}"
    run 1-start.txt ros2 param get /patrol turn_rate "${P[@]}"
fi
run 1-start.txt "${GET_HZ[@]}"

progress "частота по умолчанию (~10 с)"
run 2-hz-10.txt "${HZ[@]}"

progress "publish_hz 10 -> 5 (~10 с)"
run 3-set-5.txt ros2 param set /patrol publish_hz 5.0 "${P[@]}"
run 3-set-5.txt "${GET_HZ[@]}"
run 3-set-5.txt "${HZ[@]}"

if [ "$MODE" = defect ]; then
    progress "publish_hz 0 при отключённой проверке (~30 с: ros2 param set ждёт ответа 15 с)"
    run 4-set-0.txt timeout 15s ros2 param set /patrol publish_hz 0.0 "${P[@]}"
    wait_exit patrol
    run 4-set-0.txt alive patrol
    run 4-set-0.txt terminal_output patrol
    fresh_daemon
    wait_node /turtlesim
    run 4-set-0.txt ros2 node list
    run 4-set-0.txt ros2 topic info /turtle1/cmd_vel
    run 4-set-0.txt "${HZ[@]}"
    stop sim
    wait_exit sim
else
    progress "publish_hz 0 отклоняется, 5 Гц остаются (~10 с)"
    run 4-set-0.txt ros2 param set /patrol publish_hz 0.0 "${P[@]}"
    run 4-set-0.txt "${GET_HZ[@]}"
    run 4-set-0.txt "${HZ[@]}"
    run 4-set-0.txt alive patrol

    progress "отрицательное, NaN, вне диапазона и целое значение"
    run 5-invalid.txt ros2 param set /patrol publish_hz -2.0 "${P[@]}"
    run 5-invalid.txt ros2 param set /patrol publish_hz .nan "${P[@]}"
    run 5-invalid.txt ros2 param set /patrol publish_hz 31.0 "${P[@]}"
    run 5-invalid.txt ros2 param set /patrol publish_hz 5 "${P[@]}"
    run 5-invalid.txt "${GET_HZ[@]}"

    progress "linear_speed и turn_rate меняют команду"
    run 6-speeds.txt ros2 param set /patrol linear_speed 1.0 "${P[@]}"
    run 6-speeds.txt ros2 param set /patrol turn_rate -0.5 "${P[@]}"
    run 6-speeds.txt timeout 5s ros2 topic echo /turtle1/cmd_vel geometry_msgs/msg/Twist --once
    run 6-speeds.txt ros2 param set /patrol linear_speed 1.5 "${P[@]}"
    run 6-speeds.txt ros2 param get /patrol linear_speed "${P[@]}"
    run 6-speeds.txt timeout 5s ros2 topic echo /turtle1/cmd_vel geometry_msgs/msg/Twist --once

    progress "готовый сервис /clear и действие /turtle1/rotate_absolute"
    run 7-clear-action.txt ros2 service type /clear
    run 7-clear-action.txt ros2 service call /clear std_srvs/srv/Empty
    run 7-clear-action.txt ros2 action list -t
    run 7-clear-action.txt ros2 action info /turtle1/rotate_absolute -t

    stop patrol
    wait_exit patrol
    stop sim
    wait_exit sim
    cp "$PROC/patrol.log" "$WORK/patrol-node.txt"
fi

# --- Сводка и проверка: числа, которые цитирует parameters.md, и ожидаемые исходы опыта
python3 - "$WORK" "$MODE" > "$WORK/summary.txt" <<'PYCODE'
import re
import sys
from pathlib import Path

work, mode = Path(sys.argv[1]), sys.argv[2]
RATE = re.compile(r'average rate: (\S+)\n\s+min: (\S+) max: (\S+) std dev: (\S+) window: (\d+)')
logs = {path.name: path.read_text(encoding='utf-8') for path in work.glob('*.txt')}
checks = []


def entry(name, command):
    """Вывод и код возврата первой команды в логе, которая начинается с command."""
    match = re.search(rf'^\$ (?:timeout \S+ )?{re.escape(command)}[^\n]*\n(.*?)\[exit=(\d+)',
                      logs.get(name, ''), re.S | re.M)
    return (match.group(1).strip(), int(match.group(2))) if match else ('', None)


def rate(name):
    found = RATE.findall(logs.get(name, ''))
    return float(found[-1][0]) if found else None


def rate_text(name):
    found = RATE.findall(logs.get(name, ''))
    if not found:
        return 'нет сообщений'
    value, low, high, _, window = found[-1]
    return f'average rate {value}, min {low}, max {high}, window {window}'


def check(ok, text):
    checks.append(f'{"OK    " if ok else "ОШИБКА"} {text}')


def near(value, target):
    return value is not None and abs(value - target) <= 0.05 * target


print(f'# Сводка логов режима {mode} (для parameters.md)')
for name, title in [('2-hz-10.txt', 'hz до изменения'), ('3-set-5.txt', 'hz после 5.0'),
                    ('4-set-0.txt', 'hz после 0.0')]:
    print(f'{title}: {rate_text(name)}')
set5 = entry('3-set-5.txt', 'ros2 param set /patrol publish_hz 5.0')
set0 = entry('4-set-0.txt', 'ros2 param set /patrol publish_hz 0.0')
print(f'set 5.0: {set5[0] or "(нет вывода)"} [exit={set5[1]}]')
print(f'set 0.0: {set0[0] or "(нет вывода)"} [exit={set0[1]}]')
codes = re.findall(r'patrol: завершился, код возврата (\d+)', logs['processes.txt'])
print(f'код возврата patrol: {codes[-1] if codes else "нет (работал до конца опыта)"}')

start = logs.get('1-start.txt', '')
check(entry('1-start.txt', 'ros2 node list')[0].split() == ['/patrol', '/turtlesim'],
      'ros2 node list: /patrol и /turtlesim')
check(entry('1-start.txt', 'ros2 topic type /turtle1/pose')[0] in (
    'turtlesim/msg/Pose', 'turtlesim_msgs/msg/Pose'), 'тип /turtle1/pose')
check(entry('1-start.txt', 'ros2 param get /patrol publish_hz')[0] == 'Double value is: 10.0',
      'publish_hz по умолчанию 10.0')
if mode == 'fixed':
    names = entry('1-start.txt', 'ros2 param list /patrol')[0].split()
    check({'linear_speed', 'turn_rate', 'publish_hz'} <= set(names), 'ros2 param list: три параметра')
    check('Type: double' in start and 'Double value is: 0.5' in start and 'Double value is: 0.3' in start,
          'describe и значения по умолчанию 0.5 и 0.3')
check(near(rate('2-hz-10.txt'), 10.0), 'по умолчанию поток ~10 Гц')
check(set5[0] == 'Set parameter successful', 'publish_hz 5.0 принят')
check(near(rate('3-set-5.txt'), 5.0), 'после 5.0 поток ~5 Гц')
if mode == 'fixed':
    check(set0[0].startswith('Setting parameter failed: publish_hz '), 'publish_hz 0.0 отклонён с причиной')
    check(entry('4-set-0.txt', 'ros2 param get /patrol publish_hz')[0] == 'Double value is: 5.0',
          'после отказа publish_hz = 5.0')
    check(near(rate('4-set-0.txt'), 5.0), 'после отказа поток ~5 Гц')
    check('patrol: процесс работает' in logs['4-set-0.txt'], 'patrol работает после отказа')
    for value in ('-2.0', '.nan', '31.0', '5'):
        output = entry('5-invalid.txt', f'ros2 param set /patrol publish_hz {value} ')[0]
        check(output.startswith('Setting parameter failed'), f'publish_hz {value} отклонён')
    check(entry('5-invalid.txt', 'ros2 param get /patrol publish_hz')[0] == 'Double value is: 5.0',
          'после недопустимых значений publish_hz = 5.0')
    speeds = logs.get('6-speeds.txt', '')
    check(speeds.count('x: 1.0\n') == 2 and speeds.count('z: -0.5\n') == 2,
          'команда linear.x = 1.0, angular.z = -0.5 до и после отказа 1.5')
    check(entry('6-speeds.txt', 'ros2 param set /patrol linear_speed 1.5')[0].startswith(
        'Setting parameter failed'), 'linear_speed 1.5 отклонён')
    check('/turtle1/rotate_absolute [turtlesim/action/RotateAbsolute]' in logs.get('7-clear-action.txt', ''),
          'ros2 action list -t показывает /turtle1/rotate_absolute')
    check('std_srvs.srv.Empty_Response()' in logs.get('7-clear-action.txt', ''), '/clear ответил')
    check(codes[-1:] == ['0'], 'patrol завершился по Ctrl+C с кодом 0')
else:
    check(set0[1] == 124, 'ros2 param set publish_hz 0.0 не получил ответа (timeout, exit=124)')
    check(bool(codes) and codes[-1] != '0', 'patrol упал с ненулевым кодом')
    check('ZeroDivisionError: float division by zero' in logs['4-set-0.txt'], 'в логе patrol ZeroDivisionError')
    check('Publisher count: 0' in logs['4-set-0.txt'], 'у /turtle1/cmd_vel не осталось издателя')
    check(rate('4-set-0.txt') is None, 'команды больше не идут')
print()
print('# Проверка опыта')
print('\n'.join(checks))
sys.exit(1 if any(line.startswith('ОШИБКА') for line in checks) else 0)
PYCODE
CHECK=$?

# Неудачный прогон не затирает прежние логи: он сохраняется рядом, в $OUT-failed.
DEST=$OUT
[ "$CHECK" = 0 ] || DEST=$OUT-failed
rm -rf "$DEST"
mkdir -p "$DEST"
mv "$WORK"/*.txt "$DEST"/
rmdir "$WORK"
cat "$DEST/summary.txt"
if [ "$CHECK" != 0 ]; then
    echo "ОПЫТ НЕ ПОДТВЕРДИЛСЯ: см. строки ОШИБКА выше и логи в $DEST; запустите скрипт ещё раз" >&2
    exit 1
fi
rm -rf "$OUT-failed"
echo "done: $OUT"
