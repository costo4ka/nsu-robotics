#!/usr/bin/env bash
# Опыт ПР03 одной командой: до первой позы → сбой (без remap) → remap → частота → остановка.
# Выводы команд — реальные: каждая команда пишется в logs/*.txt вместе с выводом, кодом возврата
# и временем. В конце logs/summary.txt сводит числа, которые цитирует demo.md.
#
# Запуск из корня репозитория после colcon build обоих пакетов (patrol и turtle_bringup):
#   bash evidence/pr03/scripts/experiment.sh
# Перед запуском остановите turtlesim, teleop и patrol в этом домене (по умолчанию 16).
# Окно turtlesim откроется на текущем дисплее; без дисплея: QT_QPA_PLATFORM=offscreen.
set -u
set -m  # job control: у каждого фонового процесса своя группа и обычная реакция на SIGINT

OUT=${1:-evidence/pr03/logs}
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)                # новые логи; в $OUT попадут только после успешного прогона
PROC=$(mktemp -d)                # stdout/stderr процессов: там домашние пути, в evidence не кладём

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

for pkg in patrol turtle_bringup; do
    ros2 pkg prefix "$pkg" > /dev/null 2>&1 || fail "пакет $pkg не найден: нужен colcon build и source install/setup.bash"
done

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

# Запросы графа идут через ros2 daemon. Перед каждым этапом он перезапускается,
# чтобы в его кэше не осталось конечных точек уже остановленных нод.
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

# wait_exit NAME — дождаться, пока в группе процессов не останется ни одного процесса (до 10 с)
wait_exit() {
    local var="PGID_$1"
    for _ in $(seq 100); do
        if ! kill -0 -- "-${!var}" 2>/dev/null; then
            printf '%s: процессов не осталось   # %s\n' "$1" "$(now)" >> "$WORK/processes.txt"
            return 0
        fi
        sleep 0.1
    done
    printf '%s: процессы всё ещё работают через 10 с   # %s\n' "$1" "$(now)" >> "$WORK/processes.txt"
}

{
    echo "date: $(date -Is)"
    echo "ROS_DISTRO=$ROS_DISTRO ROS_DOMAIN_ID=$ROS_DOMAIN_ID RMW=${RMW_IMPLEMENTATION:-default}"
    grep PRETTY_NAME /etc/os-release
} > "$WORK/env.txt"

# Посторонние ноды в домене (оставшийся turtlesim, teleop, patrol) испортят опыт.
fresh_daemon
sleep 3
leftover=$(ros2 node list)
[ -z "$leftover" ] || fail "в домене $ROS_DOMAIN_ID уже есть ноды, остановите их: $(echo $leftover)"

NODE_INFO=(ros2 node info /patrol)
LIST=(ros2 node list)
INFO_CMD=(ros2 topic info /cmd_vel --verbose)
INFO_TURTLE=(ros2 topic info /turtle1/cmd_vel --verbose)
POSE_ONCE=(timeout 5s ros2 topic echo /turtle1/pose turtlesim/msg/Pose --once)

# --- 0. Нода без turtlesim: позы нет → нулевая команда
start patrol0 ros2 run patrol patrol
fresh_daemon
wait_node /patrol
run 0-no-pose.txt "${LIST[@]}"
run 0-no-pose.txt timeout 5s ros2 topic echo /cmd_vel geometry_msgs/msg/Twist --once

# --- 1. Запускаем turtlesim: поза появилась → команда 0.5 / 0.3 (patrol без remap)
start sim ros2 launch turtle_bringup sim.launch.py
fresh_daemon
wait_node /patrol /turtlesim
run 1-broken.txt "${LIST[@]}"
run 1-broken.txt "${NODE_INFO[@]}"
run 1-broken.txt timeout 5s ros2 topic echo /cmd_vel geometry_msgs/msg/Twist --once
run 1-broken.txt "${INFO_CMD[@]}"
run 1-broken.txt "${INFO_TURTLE[@]}"
run 1-broken.txt "${POSE_ONCE[@]}"
sleep 3
run 1-broken.txt "${POSE_ONCE[@]}"
stop patrol0
wait_exit patrol0

# --- 2. Исправление: тот же код, только remap при запуске
start patrol ros2 run patrol patrol --ros-args -r cmd_vel:=/turtle1/cmd_vel
fresh_daemon
wait_node /patrol /turtlesim
run 2-fixed.txt "${LIST[@]}"
run 2-fixed.txt "${NODE_INFO[@]}"
run 2-fixed.txt "${INFO_TURTLE[@]}"
run 2-fixed.txt "${INFO_CMD[@]}"
run 2-fixed.txt timeout 5s ros2 topic echo /turtle1/cmd_vel geometry_msgs/msg/Twist --once
run 2-fixed.txt "${POSE_ONCE[@]}"
sleep 3
run 2-fixed.txt "${POSE_ONCE[@]}"

# --- 3. Реальная частота команды. Первые секунды hz уходят на запуск и discovery,
#        поэтому 20 с работы: окно (window) должно покрыть не меньше 100 интервалов = 10 с.
run 3-hz.txt timeout -s INT 20s ros2 topic hz /turtle1/cmd_vel

# --- 4. Ctrl+C у patrol: черепаха ещё едет, пока turtlesim не остановит её по своему таймауту
run 4-stop.txt python3 "$(realpath --relative-to=. "$HERE/stop_probe.py")" "$PGID_patrol"
wait_exit patrol
fresh_daemon
wait_node /turtlesim
run 4-stop.txt "${LIST[@]}"
run 4-stop.txt "${POSE_ONCE[@]}"

# --- 5. Ctrl+C у launch: turtlesim завершается вместе с ним
stop sim
wait_exit sim
fresh_daemon
sleep 5
run 5-shutdown.txt "${LIST[@]}"

# --- Сводка для demo.md и проверки
python3 - "$WORK" > "$WORK/summary.txt" <<'PYCODE'
import math
import re
import sys
from datetime import datetime
from pathlib import Path

work = Path(sys.argv[1])
fixed = (work / '2-fixed.txt').read_text(encoding='utf-8')
poses = re.findall(
    r'x: (\S+)\ny: (\S+)\ntheta: (\S+)\nlinear_velocity: (\S+)\nangular_velocity: (\S+)\n---\n'
    r'\[exit=0, (\S+)\]', fixed)
print('# Сводка, извлечённая из логов этого прогона (для demo.md)')
if len(poses) == 2:
    (x1, y1, t1, v1, w1, s1), (x2, y2, t2, v2, w2, s2) = poses
    dt = (datetime.strptime(s2, '%H:%M:%S.%f') - datetime.strptime(s1, '%H:%M:%S.%f')).total_seconds()
    dtheta = math.atan2(math.sin(float(t2) - float(t1)), math.cos(float(t2) - float(t1)))
    print(f'2-fixed: поза 1 = ({float(x1):.3f}, {float(y1):.3f}, theta={float(t1):.3f}) в {s1}')
    print(f'2-fixed: поза 2 = ({float(x2):.3f}, {float(y2):.3f}, theta={float(t2):.3f}) в {s2}')
    print(f'2-fixed: между чтениями {dt:.1f} с, dtheta = {dtheta:.2f} рад '
          f'(ожидаемо 0.3 рад/с * {dt:.1f} с = {0.3 * dt:.2f} рад, по модулю 2pi)')
else:
    print(f'2-fixed: ПРОВЕРИТЬ ВРУЧНУЮ, найдено поз: {len(poses)}')
hz = (work / '3-hz.txt').read_text(encoding='utf-8')
last = re.findall(r'average rate: (\S+)\n\s+min: (\S+) max: (\S+) std dev: (\S+) window: (\d+)', hz)
if last:
    rate, mn, mx, sd, window = last[-1]
    ok = 'OK' if int(window) >= 100 else 'МАЛО: меньше 10 с, увеличьте timeout hz'
    print(f'3-hz: average rate {rate}, min {mn}, max {mx}, std dev {sd}, window {window} ({ok})')
else:
    print('3-hz: ПРОВЕРИТЬ ВРУЧНУЮ, строк average rate нет')
stop = (work / '4-stop.txt').read_text(encoding='utf-8')
m = re.search(r'последнее изменение позы через (\S+) с', stop)
print(f'4-stop: черепаха двигалась ещё {m.group(1)} с после SIGINT' if m
      else '4-stop: ПРОВЕРИТЬ ВРУЧНУЮ')
PYCODE

rm -f "$OUT"/*.txt
mkdir -p "$OUT"
mv "$WORK"/*.txt "$OUT"/
rmdir "$WORK"
cat "$OUT/summary.txt"
echo "done: $OUT"
