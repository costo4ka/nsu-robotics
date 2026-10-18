#!/usr/bin/env bash
# Опыт ПР06 одной командой: модель в tf2 через robot_state_publisher.
#   fixed  — QoS /tf_static (поздний transient local / volatile) → tf-qos.txt; tf2_echo, view_frames,
#            echo /tf_static; затем /joint_states → колёса в /tf и единственные владельцы рёбер;
#   defect — ветка pr06-defect (parent лидара — camera_link): тот же tf2_echo и view_frames.
# Каждая команда пишется в evidence/pr06/logs/<режим>/*.txt с выводом, кодом возврата и временем.
#
# Запуск из корня репозитория после colcon build:
#   bash evidence/pr06/scripts/experiment.sh fixed     # ~1 мин
#   bash evidence/pr06/scripts/experiment.sh defect    # ~40 с
# GUI не нужен: RViz в опыте не открывается (rviz:=false). Перед запуском остановите прежние
# launch с robot_state_publisher в этом домене (по умолчанию 16): два издателя /tf_static дают
# случайный ответ — скрипт проверит.
set -u
set -m  # job control: у каждого фонового процесса своя группа и обычная реакция на SIGINT

MODE=${1:-}
case "$MODE" in
    fixed | defect) ;;
    *) echo "использование: bash evidence/pr06/scripts/experiment.sh fixed|defect" >&2; exit 2 ;;
esac
EV=evidence/pr06
OUT=$EV/logs/$MODE
XACRO=src/course_description/urdf/vehicle.urdf.xacro
WORK=$(mktemp -d)                # новые логи; в evidence попадут только после успешной проверки
PROC=$(mktemp -d)                # stdout/stderr процессов

set +u
source /opt/ros/jazzy/setup.bash
source install/setup.bash
set -u
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-16}
export PYTHONUNBUFFERED=1

fail() {
    echo "ОШИБКА: $*" >&2
    echo "частичные логи: $WORK, вывод процессов: $PROC" >&2
    exit 1
}

[ -f "$XACRO" ] || fail "запускать из корня репозитория"
ros2 pkg prefix course_description > /dev/null 2>&1 \
    || fail "пакет course_description не найден: нужен colcon build и source install/setup.bash"
if grep -q 'ДЕФЕКТ ПР06' "$XACRO"; then CODE=defect; else CODE=fixed; fi
[ "$CODE" = "$MODE" ] || fail "режим $MODE, а код в src/ — $CODE (проверьте ветку: git branch --show-current)"
# Опыт идёт только на закоммиченном коде: в evidence записываются SHA и дифф этого коммита.
git diff --quiet HEAD -- src && [ -z "$(git ls-files --others --exclude-standard src)" ] \
    || fail "в src/ есть незакоммиченные изменения (git status --short src): сначала коммит"
if [ "$MODE" = defect ]; then
    git show HEAD -- "$XACRO" | grep -q '^+.*ДЕФЕКТ ПР06' \
        || fail "HEAD — не коммит дефекта: нужны git apply evidence/pr06/defect.patch и git commit"
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
TOTAL=$([ "$MODE" = fixed ] && echo 7 || echo 5)
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

# run_until FILE PATTERN CMD... — как run, но для запросов графа: повторить (до 5 раз, пауза 2 с),
# пока в выводе нет PATTERN; номер попытки виден в строке [exit=...].
run_until() {
    local file=$1 pattern=$2; shift 2
    local out rc attempt
    for attempt in 1 2 3 4 5; do
        out=$("$@" 2>&1)
        rc=$?
        grep -qE "$pattern" <<< "$out" && break
        sleep 2
    done
    {
        printf '$ %s\n' "$*"
        [ -n "$out" ] && printf '%s\n' "$out"
        printf '[exit=%s, %s, попытка %s]\n\n' "$rc" "$(now)" "$attempt"
    } >> "$WORK/$file"
    return 0
}

fresh_daemon() {
    ros2 daemon stop > /dev/null 2>&1
    ros2 daemon start > /dev/null 2>&1
}

# wait_node NAME... — дождаться, пока daemon увидит все ноды (до ~40 с)
wait_node() {
    local list name ok
    for _ in $(seq 40); do
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

# stop NAME — Ctrl+C: SIGINT всей группе процессов, как из терминала
stop() {
    local var="PGID_$1"
    kill -INT -- "-${!var}" 2>/dev/null
    printf 'SIGINT -> %s   # %s\n' "$1" "$(now)" >> "$WORK/processes.txt"
}

# wait_exit NAME — дождаться завершения (до 20 с) и записать код возврата
wait_exit() {
    local var="PGID_$1"
    local rc
    for _ in $(seq 200); do
        if ! kill -0 -- "-${!var}" 2>/dev/null; then
            wait "${!var}"
            rc=$?
            printf '%s: завершился, код возврата %s   # %s\n' "$1" "$rc" "$(now)" >> "$WORK/processes.txt"
            return 0
        fi
        sleep 0.1
    done
    printf '%s: всё ещё работает через 20 с   # %s\n' "$1" "$(now)" >> "$WORK/processes.txt"
    return 1
}

# terminal_output NAME — что процесс напечатал в своём «терминале» (stdout и stderr).
# Строка launch «All log files can be found below …» не нужна: в имени каталога логов стоит имя хоста.
terminal_output() {
    sed '/All log files can be found below/d' "$PROC/$1.log"
}

# tf2_echo печатает преобразование раз в секунду, пока его не остановят: 6 с хватает на discovery.
TF2_ECHO=(timeout -s INT 6 ros2 run tf2_ros tf2_echo)

{
    echo "date: $(date -Is)"
    echo "mode: $MODE"
    echo "branch: $(git branch --show-current)"
    echo "HEAD: $(git rev-parse HEAD)"
    echo "ROS_DISTRO=$ROS_DISTRO ROS_DOMAIN_ID=$ROS_DOMAIN_ID RMW=${RMW_IMPLEMENTATION:-default}"
    grep PRETTY_NAME /etc/os-release
    echo "kernel: $(uname -r)"
} > "$WORK/env.txt"
if [ "$MODE" = defect ]; then
    run env.txt git log --oneline -3
    run env.txt git diff HEAD~1 HEAD -- src
fi

echo "ПР06, режим $MODE: логи появятся в $OUT. GUI не нужен, ничего не нажимать."
progress "проверка, что домен $ROS_DOMAIN_ID пуст"
fresh_daemon
sleep 3
leftover=$(ros2 node list)
[ -z "$leftover" ] || fail "в домене $ROS_DOMAIN_ID уже есть ноды, остановите их: $(echo $leftover)"

progress "запуск robot_state_publisher (display.launch.py rviz:=false)"
start rsp ros2 launch course_description display.launch.py rviz:=false
fresh_daemon
wait_node /robot_state_publisher

if [ "$MODE" = fixed ]; then
    progress "QoS /tf_static: поздний подписчик transient local и volatile (~10 с)"
    # Блок из условия ПР06. Тип задан явно: без него echo выходит с кодом 1, если ещё не успел
    # обнаружить топик, и отсутствие сообщений нельзя было бы отличить от медленного discovery.
    {
        echo '## topic info /tf_static'
        # Запрос графа идёт через только что перезапущенный daemon и может опередить discovery
        # топика («Unknown topic»): повторяем до 5 раз, пока не появится издатель.
        for attempt in 1 2 3 4 5; do
            info=$(ros2 topic info /tf_static --verbose 2>&1)
            grep -qE 'Publisher count: [1-9]' <<< "$info" && break
            sleep 2
        done
        echo "$info"
        echo '## echo transient_local'
        timeout 4 ros2 topic echo /tf_static tf2_msgs/msg/TFMessage --once \
            --qos-durability transient_local --qos-reliability reliable; echo "exit=$?"
        echo '## echo volatile'
        timeout 4 ros2 topic echo /tf_static tf2_msgs/msg/TFMessage --once \
            --qos-durability volatile --qos-reliability reliable; echo "exit=$?"
    } > "$WORK/tf-qos.txt" 2>&1
fi

progress "дерево: tf2_echo base_link lidar_link, view_frames, echo /tf_static (~20 с)"
run_until 1-graph.txt '^/robot_state_publisher$' ros2 node list
run_until 1-graph.txt 'Publisher count: [1-9]' ros2 topic info /tf_static --verbose
run 2-tf2-echo.txt "${TF2_ECHO[@]}" base_link lidar_link
[ "$MODE" = fixed ] && run 2-tf2-echo.txt "${TF2_ECHO[@]}" camera_link camera_link_optical
(cd "$WORK" && run 3-view-frames.txt ros2 run tf2_tools view_frames -o frames)
# Команда из условия без типа: пока топик не обнаружен, echo сразу выходит с кодом 1 — повторяем.
run_until 4-tf-static.txt 'child_frame_id: lidar_link' timeout 5 ros2 topic echo /tf_static --once

if [ "$MODE" = fixed ]; then
    progress "подвижные сочленения: /joint_states → колёса в /tf, владельцы рёбер (~15 с)"
    start joints ros2 run course_description zero_joint_states
    wait_node /robot_state_publisher /zero_joint_states
    run_until 5-moving.txt 'Publisher count: [1-9]' ros2 topic info /joint_states --verbose
    run_until 5-moving.txt 'Publisher count: [1-9]' ros2 topic info /tf --verbose
    run 5-moving.txt "${TF2_ECHO[@]}" base_link front_left_wheel
    {
        echo
        echo '## topic info /tf (zero_joint_states публикует /joint_states, robot_state_publisher — /tf)'
        grep -A40 '^\$ ros2 topic info /tf --verbose' "$WORK/5-moving.txt" | sed '/^\[exit=/q'
    } >> "$WORK/tf-qos.txt"
    stop joints
    wait_exit joints
fi

progress "Ctrl+C у launch"
stop rsp
wait_exit rsp
run launch.txt terminal_output rsp

if [ "$MODE" = fixed ]; then
    cat >> "$WORK/tf-qos.txt" <<'TEXT'

## Вывод

У robot_state_publisher /tf_static — RELIABLE и TRANSIENT_LOCAL: фиксированные звенья (камера, лидар,
IMU) не меняются, поэтому их преобразования публикуются один раз при запуске, а издатель хранит
последнее сообщение для подписчиков, которые подключатся позже. /tf — RELIABLE и VOLATILE: подвижные
звенья и одометрия публикуются непрерывно с отметками времени, прошлое значение сразу устаревает,
и поздний подписчик просто дождётся следующего сообщения. Поэтому подписка с volatile на /tf_static
ничего не получает (exit=124): новых сообщений нет, а сохранённое отдаётся только transient local.
TEXT
fi

progress "сводка и проверка"
python3 - "$WORK" "$MODE" > "$WORK/summary.txt" <<'PYCODE'
import re
import sys
from pathlib import Path

work, mode = Path(sys.argv[1]), sys.argv[2]
logs = {path.name: path.read_text(encoding='utf-8') for path in work.glob('*.txt')}
checks = []


def check(ok, text):
    checks.append(f'{"OK    " if ok else "ОШИБКА"} {text}')


def translation(name, frame):
    text = logs.get(name, '')
    block = re.search(rf'tf2_echo base_link {frame}\n(.*?)\[exit=', text, re.S)
    found = re.findall(r'Translation: \[([-\d.]+), ([-\d.]+), ([-\d.]+)\]', block.group(1) if block else '')
    return tuple(float(v) for v in found[-1]) if found else None


def parent_in_static(frame):
    match = re.search(rf'frame_id: (\S+)\n\s+child_frame_id: {frame}\n', logs.get('4-tf-static.txt', ''))
    return match.group(1) if match else None


gv = (work / 'frames.gv').read_text(encoding='utf-8') if (work / 'frames.gv').is_file() else ''
lidar = translation('2-tf2-echo.txt', 'lidar_link')
lidar_parent = parent_in_static('lidar_link')
publishers = re.findall(r'Publisher count: (\d+)', logs.get('1-graph.txt', ''))
print(f'# Сводка опыта ПР06, режим {mode}')
print(f'tf2_echo base_link lidar_link: {lidar}')
print(f'родитель lidar_link в /tf_static: {lidar_parent}')
check(publishers[-1:] == ['1'], 'у /tf_static ровно один издатель')
if mode == 'fixed':
    qos = logs.get('tf-qos.txt', '')
    transient = qos.split('## echo transient_local', 1)[-1].split('## echo volatile', 1)[0]
    volatile = qos.split('## echo volatile', 1)[-1].split('## topic info /tf', 1)[0]
    head = qos.split('## echo transient_local', 1)[0]
    check('Node name: robot_state_publisher' in head and 'Reliability: RELIABLE' in head
          and 'Durability: TRANSIENT_LOCAL' in head, '/tf_static: RELIABLE + TRANSIENT_LOCAL у robot_state_publisher')
    check('exit=0' in transient and 'child_frame_id: lidar_link' in transient,
          'поздний transient local подписчик получил преобразования (exit=0)')
    check('exit=124' in volatile and 'child_frame_id' not in volatile,
          'поздний volatile подписчик ничего не получил (exit=124)')
    check(lidar == (0.28, 0.0, 0.38), 'tf2_echo base_link lidar_link: [0.280, 0.000, 0.380]')
    check(lidar_parent == 'base_link', '/tf_static: родитель lidar_link — base_link')
    check('"base_link" -> "lidar_link"' in gv, 'view_frames: base_link -> lidar_link')
    moving = logs.get('5-moving.txt', '')
    tf_info = moving.split('ros2 topic info /tf --verbose', 1)[-1]
    check(re.search(r'Publisher count: 1\n', tf_info) is not None
          and 'Node name: robot_state_publisher' in tf_info and 'Durability: VOLATILE' in tf_info,
          '/tf: один издатель robot_state_publisher, VOLATILE')
    joint_info = moving.split('ros2 topic info /joint_states --verbose', 1)[-1].split('$ ', 1)[0]
    check('Publisher count: 1' in joint_info and 'Node name: zero_joint_states' in joint_info,
          '/joint_states: один издатель zero_joint_states')
    check(translation('5-moving.txt', 'front_left_wheel') == (0.4, 0.31, 0.0),
          'tf2_echo base_link front_left_wheel: [0.400, 0.310, 0.000]')
else:
    check(lidar == (0.56, 0.0, 0.76), 'дефект: tf2_echo base_link lidar_link: [0.560, 0.000, 0.760]')
    check(lidar_parent == 'camera_link', 'дефект: в /tf_static родитель lidar_link — camera_link')
    check('"camera_link" -> "lidar_link"' in gv, 'дефект: view_frames: camera_link -> lidar_link')
processes = logs.get('processes.txt', '')
codes = dict(re.findall(r'^(\w+): завершился, код возврата (\d+)', processes, re.M))
check(codes.get('rsp') == '0', 'launch завершился по Ctrl+C с кодом 0')
check('process has died' not in logs.get('launch.txt', ''), 'по Ctrl+C ни один процесс launch не упал')
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
[ "$MODE" = fixed ] && [ "$CHECK" = 0 ] && mv "$WORK/tf-qos.txt" "$EV/tf-qos.txt"
mv "$WORK"/* "$DEST"/
rmdir "$WORK"
cat "$DEST/summary.txt"
if [ "$CHECK" != 0 ]; then
    echo "ОПЫТ НЕ ПОДТВЕРДИЛСЯ: см. строки ОШИБКА выше и логи в $DEST; запустите скрипт ещё раз" >&2
    exit 1
fi
rm -rf "$OUT-failed"
echo "done: $OUT"
