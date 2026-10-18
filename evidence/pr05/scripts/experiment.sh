#!/usr/bin/env bash
# Опыт ПР05 одной командой: несовместимый QoS на живом потоке → исправление и запись MCAP →
# повтор той же записи с QoS override. Вывод команд — реальный, с кодом возврата и временем.
#   1. launch с subscriber_reliability:=reliable: топик виден, сообщений нет   → qos-before.txt
#   2. launch с subscriber_reliability:=best_effort record:=true: поток идёт   → qos-after.txt
#   3. ros2 bag play той же записи: reliable — ничего, best_effort — сообщения → оба файла
# В конце: ros2 bag info → qos-after.txt, metadata.yaml → bag-metadata.yaml, сводка с проверкой.
#
# Запуск из корня репозитория после colcon build:  bash evidence/pr05/scripts/experiment.sh
# ~2.5 мин, откроется окно turtlesim; ничего не нажимать. Перед запуском остановите turtlesim,
# teleop, patrol и прежние launch в этом домене (по умолчанию 16) — скрипт проверит.
set -u
set -m  # job control: у каждого фонового процесса своя группа и обычная реакция на SIGINT

EV=evidence/pr05
BAG=$EV/bag
LOGS=$EV/logs
NS=robot_a
TOPIC=/$NS/sensor_pose
RECORD_SEC=30                    # запись должна пережить discovery и оба echo на replay
WORK=$(mktemp -d)                # новые файлы; в evidence попадут только после успешной проверки
PROC=$(mktemp -d)                # stdout/stderr процессов
PREV=$(mktemp -d)                # прежняя запись evidence/pr05/bag на время опыта
DONE=0

set +u
source /opt/ros/jazzy/setup.bash
source install/setup.bash
set -u
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-16}
export PYTHONUNBUFFERED=1        # вывод launch в файл без буфера: логи полные даже при аварии
OVERRIDES=config/qos-overrides.yaml

fail() {
    echo "ОШИБКА: $*" >&2
    echo "частичные логи: $WORK, вывод процессов: $PROC" >&2
    exit 1
}

[ -f src/course_bringup/launch/patrol.launch.py ] || fail "запускать из корня репозитория"
for pkg in patrol course_bringup; do
    ros2 pkg prefix "$pkg" > /dev/null 2>&1 || fail "пакет $pkg не найден: нужен colcon build и source install/setup.bash"
done
[ -f "$OVERRIDES" ] || fail "нет $OVERRIDES (запускать из корня репозитория)"
# Опыт идёт только на закоммиченном коде: в evidence записывается SHA этого коммита.
git diff --quiet HEAD -- src && [ -z "$(git ls-files --others --exclude-standard src)" ] \
    || fail "в src/ есть незакоммиченные изменения (git status --short src): сначала коммит"

PGIDS=()
cleanup() {
    for pgid in "${PGIDS[@]}"; do kill -INT -- "-$pgid" 2>/dev/null; done
    sleep 2
    for pgid in "${PGIDS[@]}"; do kill -KILL -- "-$pgid" 2>/dev/null; done
    ros2 daemon stop > /dev/null 2>&1
    # Неудачный или прерванный прогон: вернуть прежнюю запись к прежним qos-*.txt.
    if [ "$DONE" != 1 ] && [ -d "$PREV/bag" ]; then rm -rf "$BAG"; mv "$PREV/bag" "$BAG"; fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

now() { date +%T.%3N; }
STEP=0
progress() { STEP=$((STEP + 1)); echo "[$STEP/8 $(now)] $*"; }

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

# run_until FILE PATTERNS CMD... — как run, но для запросов графа: повторить (до 5 раз, пауза 2 с),
# пока в выводе нет всех шаблонов (PATTERNS — через « && »). ros2 daemon на загруженной машине
# иногда отдаёт пустой граф; в лог идёт последняя попытка, её номер виден в строке [exit=...].
run_until() {
    local file=$1 patterns=$2; shift 2
    local out rc attempt pattern ok
    for attempt in 1 2 3 4 5; do
        out=$("$@" 2>&1)
        rc=$?
        ok=1
        while read -r pattern; do grep -qE "$pattern" <<< "$out" || ok=0; done <<< "${patterns//' && '/$'\n'}"
        [ $ok = 1 ] && break
        sleep 2
    done
    {
        printf '$ %s\n' "$*"
        [ -n "$out" ] && printf '%s\n' "$out"
        printf '[exit=%s, %s, попытка %s]\n\n' "$rc" "$(now)" "$attempt"
    } >> "$WORK/$file"
    return 0
}

# section FILE TITLE — заголовок раздела в файле evidence
section() { printf '## %s\n\n' "$2" >> "$WORK/$1"; }

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
    ps -o pid,stat,etime,args -g "${!var}" >> "$WORK/processes.txt"
    return 1
}

# terminal_output NAME [ШАБЛОН] — что процесс напечатал (строки по шаблону grep -E)
terminal_output() {
    if [ $# -ge 2 ]; then grep -E "$2" "$PROC/$1.log"; else cat "$PROC/$1.log"; fi
}

# Тип задан явно: без него echo выходит с кодом 1, если ещё не успел обнаружить топик,
# и отсутствие сообщений нельзя отличить от медленного discovery.
ECHO=(timeout 5s ros2 topic echo "$TOPIC" turtlesim/msg/Pose --once --qos-reliability)
LISTENER_LINES='subscribed|incompatible|received|first message'

{
    echo "date: $(date -Is)"
    echo "branch: $(git branch --show-current)"
    echo "HEAD: $(git rev-parse HEAD)"
    echo "ROS_DISTRO=$ROS_DISTRO ROS_DOMAIN_ID=$ROS_DOMAIN_ID RMW=${RMW_IMPLEMENTATION:-default}"
    grep PRETTY_NAME /etc/os-release
    echo "kernel: $(uname -r)"
    echo "qos overrides: $OVERRIDES"
} > "$WORK/env.txt"

echo "ПР05: файлы появятся в $EV. Окно turtlesim откроется само; ничего не нажимать (~2.5 мин)."
progress "проверка, что домен $ROS_DOMAIN_ID пуст"
fresh_daemon
sleep 3
leftover=$(ros2 node list)
[ -z "$leftover" ] || fail "в домене $ROS_DOMAIN_ID уже есть ноды, остановите их: $(echo $leftover)"
[ -d "$BAG" ] && mv "$BAG" "$PREV/bag"

LAUNCH=(ros2 launch course_bringup patrol.launch.py namespace:=$NS)
NODES=(/turtlesim /$NS/patrol /$NS/pose_relay /$NS/pose_listener)

# --- 1. Сломать: reliable-подписчик против best effort-сенсора
progress "live: subscriber_reliability:=reliable (~20 с)"
start broken "${LAUNCH[@]}" subscriber_reliability:=reliable record:=false
fresh_daemon
wait_node "${NODES[@]}"
B=qos-before.txt
section $B "live: ${LAUNCH[*]} subscriber_reliability:=reliable record:=false"
run_until $B "^/$NS/pose_listener$" ros2 node list
run_until $B "^$TOPIC$" ros2 topic list
run_until $B 'Subscription count: [1-9]' ros2 topic info "$TOPIC" --verbose
run $B "${ECHO[@]}" reliable
sleep 2
run $B terminal_output broken "$LISTENER_LINES"
stop broken
wait_exit broken

# --- 2. Исправить и записать: best_effort-подписчик, запись MCAP
progress "live: subscriber_reliability:=best_effort record:=true, запись ${RECORD_SEC} с"
start fixed "${LAUNCH[@]}" subscriber_reliability:=best_effort record:=true bag_dir:=$BAG
fresh_daemon
wait_node "${NODES[@]}" /rosbag2_recorder
A=qos-after.txt
section $A "live: ${LAUNCH[*]} subscriber_reliability:=best_effort record:=true bag_dir:=$BAG"
run_until $A '^/rosbag2_recorder$' ros2 node list
run_until $A 'Subscription count: [2-9]' ros2 topic info "$TOPIC" --verbose
run $A "${ECHO[@]}" best_effort
sleep "$RECORD_SEC"
run $A terminal_output fixed "$LISTENER_LINES"
progress "Ctrl+C у launch: recorder и ноды завершаются"
stop fixed
wait_exit fixed || fail "launch с записью не завершился за 20 с после Ctrl+C (см. processes.txt) — запустите скрипт ещё раз"
[ -f "$BAG/metadata.yaml" ] || fail "запись $BAG не закрылась (нет metadata.yaml) — запустите скрипт ещё раз"
run $A terminal_output fixed 'process has|Recording stopped'

# --- 3. Повтор той же записи с тем же QoS override. Как в лекции 05: перед каждым чтением
#        запись стартует заново, живой издатель остановлен — у «до» и «после» один и тот же вход.
# replay FILE RELIABILITY — проиграть запись с начала и проверить одного читателя
replay() {
    local file=$1 rel=$2
    fresh_daemon
    start "play_$rel" ros2 bag play "$BAG" --qos-profile-overrides-path "$OVERRIDES"
    start "replay_$rel" ros2 run course_bringup pose_listener \
        --ros-args -r __ns:=/$NS -r __node:=replay_$rel -p reliability:=$rel
    wait_node /rosbag2_player "/$NS/replay_$rel"
    section "$file" "replay: ros2 bag play $BAG --qos-profile-overrides-path $OVERRIDES (читатель $rel)"
    run "$file" cat "$OVERRIDES"
    run_until "$file" 'Node name: rosbag2_player && Subscription count: [1-9]' \
        ros2 topic info "$TOPIC" --verbose
    run "$file" "${ECHO[@]}" "$rel"
    sleep 3
    stop "replay_$rel"
    wait_exit "replay_$rel"
    run "$file" terminal_output "replay_$rel" "$LISTENER_LINES"
    stop "play_$rel"
    wait_exit "play_$rel"
    run play.txt terminal_output "play_$rel"
}
progress "replay той же записи: читатель reliable (~20 с)"
replay $B reliable
progress "replay той же записи заново: читатель best_effort (~20 с)"
replay $A best_effort
# Строка launch «All log files can be found below …» не нужна: в имени каталога логов стоит имя хоста.
for name in broken fixed; do sed '/All log files can be found below/d' "$PROC/$name.log" > "$WORK/launch-$name.txt"; done

progress "ros2 bag info и metadata.yaml"
section $A "запись: ros2 bag info"
run $A ros2 bag info "$BAG"
cp "$BAG/metadata.yaml" "$WORK/bag-metadata.yaml"

progress "сводка и проверка"
python3 - "$WORK" "$TOPIC" > "$WORK/summary.txt" <<'PYCODE'
import re
import sys
from pathlib import Path

work, topic = Path(sys.argv[1]), sys.argv[2]
before = (work / 'qos-before.txt').read_text(encoding='utf-8')
after = (work / 'qos-after.txt').read_text(encoding='utf-8')
processes = (work / 'processes.txt').read_text(encoding='utf-8')
checks = []


def sections(text):
    return dict(re.findall(r'^## (\w+):.*?\n(.*?)(?=^## |\Z)', text, re.S | re.M))


def entry(text, command):
    match = re.search(rf'^\$ {re.escape(command)}[^\n]*\n(.*?)\[exit=(\d+)', text, re.S | re.M)
    return (match.group(1), int(match.group(2))) if match else ('', None)


def check(ok, text):
    checks.append(f'{"OK    " if ok else "ОШИБКА"} {text}')


b, a = sections(before), sections(after)
echo = f'timeout 5s ros2 topic echo {topic} turtlesim/msg/Pose --once --qos-reliability'
for place in ('live', 'replay'):
    out, rc = entry(b.get(place, ''), f'{echo} reliable')
    check(rc == 124 and 'x:' not in out, f'{place}: reliable echo — сообщений нет, timeout (exit=124)')
    out, rc = entry(a.get(place, ''), f'{echo} best_effort')
    check(rc == 0 and 'x:' in out, f'{place}: best_effort echo — сообщение получено (exit=0)')
info, _ = entry(b.get('live', ''), 'ros2 topic info')
check('Reliability: BEST_EFFORT' in info and 'Reliability: RELIABLE' in info,
      'live: у топика издатель BEST_EFFORT и подписчик RELIABLE')
check(topic in entry(b.get('live', ''), 'ros2 topic list')[0], f'live: {topic} виден в ros2 topic list')
names = entry(b.get('live', ''), 'ros2 node list')[0].split()
check({'/robot_a/patrol', '/robot_a/pose_relay', '/robot_a/pose_listener', '/turtlesim'} <= set(names),
      'live: ноды в /robot_a, turtlesim глобально')
LISTENER_INCOMPATIBLE = 'incompatible QoS with a publisher of'  # строка pose_listener, не echo
check(LISTENER_INCOMPATIBLE in b.get('live', '') and 'received 0 messages' in b.get('live', ''),
      'live: pose_listener reliable — incompatible QoS и received 0')
check(LISTENER_INCOMPATIBLE in b.get('replay', '') and 'received 0 messages' in b.get('replay', ''),
      'replay: reliable-подписчик — incompatible QoS и received 0')
for place, text in (('qos-before', b.get('replay', '')), ('qos-after', a.get('replay', ''))):
    replay_info = entry(text, 'ros2 topic info')[0]
    player = replay_info.split('Node name: rosbag2_player', 1)[-1].split('Subscription count', 1)[0]
    check('Node name: rosbag2_player' in replay_info and 'Reliability: BEST_EFFORT' in player,
          f'replay ({place}): издатель — rosbag2_player с BEST_EFFORT')
received = [int(n) for n in re.findall(r'received (\d+) messages', a.get('replay', ''))]
check(bool(received) and max(received) > 0, 'replay: best_effort-подписчик получает сообщения')
live_received = [int(n) for n in re.findall(r'received (\d+) messages', a.get('live', ''))]
check(bool(live_received) and max(live_received) > 0, 'live: pose_listener best_effort получает сообщения')
bag_info = entry(a.get('запись', after), 'ros2 bag info')[0]
topics = re.findall(r'Topic: (\S+) \| Type: (\S+) \| Count: (\d+)', bag_info)
check(len(topics) == 1 and topics[0][0] == topic and int(topics[0][2]) > 0,
      f'запись: ровно один поток {topic}, сообщений > 0')
check('Storage id:        mcap' in bag_info or 'Storage id: mcap' in bag_info, 'запись в MCAP')
check('Recording stopped' in a.get('live', ''), 'recorder остановился по Ctrl+C')
check('process has died' not in after, 'по Ctrl+C ни один процесс launch не упал')
codes = re.findall(r'^(broken|fixed): завершился, код возврата (\d+)', processes, re.M)
check(dict(codes) == {'broken': '0', 'fixed': '0'}, 'оба launch завершились с кодом 0')

print('# Сводка опыта ПР05')
if topics:
    print(f'запись: {topics[0][0]} {topics[0][1]}, сообщений {topics[0][2]}')
print(f'live best_effort pose_listener: received до {max(live_received, default=0)}')
print(f'replay best_effort pose_listener: received до {max(received, default=0)}')
print()
print('# Проверка опыта')
print('\n'.join(checks))
sys.exit(1 if any(line.startswith('ОШИБКА') for line in checks) else 0)
PYCODE
CHECK=$?

# Неудачный прогон не затирает прежние файлы: он сохраняется в logs-failed.
if [ "$CHECK" != 0 ]; then
    rm -rf "$EV/logs-failed" && mkdir -p "$EV/logs-failed" && mv "$WORK"/* "$EV/logs-failed"/
    cat "$EV/logs-failed/summary.txt"
    echo "ОПЫТ НЕ ПОДТВЕРДИЛСЯ: см. ОШИБКА выше и $EV/logs-failed; запустите скрипт ещё раз" >&2
    exit 1
fi
mv "$WORK/qos-before.txt" "$WORK/qos-after.txt" "$WORK/bag-metadata.yaml" "$EV"/
DONE=1
rm -rf "$PREV"
rm -rf "$LOGS" "$EV/logs-failed"
mkdir -p "$LOGS"
mv "$WORK"/*.txt "$LOGS"/
rmdir "$WORK"
cat "$LOGS/summary.txt"
echo "done: $EV/qos-before.txt, $EV/qos-after.txt, $EV/bag-metadata.yaml, $LOGS/"
