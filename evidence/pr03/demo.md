# PR03 — нода patrol: поза и команда

ROS 2 Jazzy, `ROS_DOMAIN_ID=16`. Полные выводы команд лежат в `logs/`, по файлу на этап. Их снимает
`scripts/experiment.sh`: он запускает те же процессы, что и три терминала ниже (каждый — в своей
группе процессов, Ctrl+C = SIGINT этой группе), и пишет каждую команду наблюдения вместе с выводом,
кодом возврата и временем завершения. Запросы графа (`node list/info`, `topic info`) идут через
`ros2 daemon`, который перезапускается перед каждым этапом, чтобы в его кэше не осталось конечных
точек уже остановленных нод. Моменты запуска и остановки процессов — в `logs/processes.txt`,
числа, которые цитируются ниже, — в `logs/summary.txt`.

## Нода

Каркас пакета совпадает с тем, что генерирует команда из лекции (сверено `diff` с её выводом;
лицензия и сопровождающий — как у `turtle_bringup`):

```bash
ros2 pkg create --build-type ament_python --license Apache-2.0 --node-name patrol patrol \
  --dependencies rclpy geometry_msgs --maintainer-name arina --maintainer-email a.tebaikina@g.nsu.ru
```

В `package.xml` добавлена зависимость `turtlesim` — пакет типа позы в Jazzy
(`ros2 topic type /turtle1/pose` → `turtlesim/msg/Pose`).

`src/patrol/patrol/patrol.py`, класс `Patrol(Node)`, имя ноды `/patrol`:

- `self.pose_sub` — подписка на `/turtle1/pose`; callback `on_pose` только сохраняет сообщение
  в `self.latest_pose`;
- `self.cmd_pub` — издатель `geometry_msgs/msg/Twist` в **относительное** имя `cmd_vel`;
- `self.timer` — таймер 0.1 с; callback `on_timer` берёт последнюю позу, вызывает чистую функцию
  `choose_command` и публикует результат.

`choose_command(pose)` (`src/patrol/patrol/command.py`): `None` → нулевой Twist, иначе
`linear.x = 0.5`, `angular.z = 0.3`. Скорости проходят через `limit_command`: ограничение
`|linear.x| ≤ 1.0`, `|angular.z| ≤ 1.0`, NaN/inf → 0.

## Роли init, spin, callback и Ctrl+C

- `rclpy.init(args=args)` создаёт контекст ROS в процессе: разбирает аргументы после `--ros-args`
  (в том числе правило `-r cmd_vel:=/turtle1/cmd_vel`), подключает middleware с доменом из
  `ROS_DOMAIN_ID` и ставит обработчики SIGINT/SIGTERM. Без него ноду не создать.
- `Patrol()` только регистрирует ноду, подписку, издателя и таймер. В этот момент относительное
  `cmd_vel` разрешается в полное имя с учётом namespace и remap. Ни один callback ещё не вызван.
- `rclpy.spin(node)` отдаёт поток исполнителю: он ждёт события (пришла поза, истёк период таймера)
  и по одному вызывает готовые callback в этом же потоке, пока контекст не остановлен. Без spin
  подписка ничего не получит, а таймер не сработает.
- callback — короткие функции, которые вызываем не мы, а исполнитель внутри spin. `on_pose` только
  запоминает позу. `on_timer` читает последнее сохранённое значение и не ждёт новую позу внутри
  себя. Долгий callback задержал бы и следующий тик таймера: исполнитель однопоточный.
- Ctrl+C: терминал посылает SIGINT всей группе процессов (`ros2 run` и сама нода). Обработчик rclpy
  будит исполнитель, и `spin` выходит с `KeyboardInterrupt`. При SIGTERM или остановке контекста
  извне выход будет через `ExternalShutdownException`. Оба перехвачены, в `finally` выполняются
  `destroy_node()` (конечные точки ноды уходят из графа) и `rclpy.try_shutdown()`. Нулевую команду
  при выходе нода **не** публикует. Черепаха продолжает выполнять последний Twist, пока turtlesim
  сам не обнулит скорость по своему таймауту (этап 4).

## Терминалы

```bash
# во всех терминалах, из корня репозитория
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=16

# A: симулятор
ros2 launch turtle_bringup sim.launch.py
# B: нода; сначала без remap (сбой), затем с remap (исправление)
ros2 run patrol patrol
ros2 run patrol patrol --ros-args -r cmd_vel:=/turtle1/cmd_vel
# C: наблюдение — команды ниже
```

## 0. Нода появилась, позы ещё нет → нулевая команда (`logs/0-no-pose.txt`)

turtlesim не запущен, patrol запущен без remap.

- `ros2 node list` → `/patrol`.
- `ros2 topic echo /cmd_vel geometry_msgs/msg/Twist --once` → все шесть полей `0.0`.

Подписка есть, первой позы нет, поэтому таймер публикует нулевую команду.

## 1. Сбой: команда уходит в относительный cmd_vel (`logs/1-broken.txt`)

Проверяемая гипотеза: команда patrol доходит до turtlesim. Запущен turtlesim, patrol — без remap.

| Проверка | Результат |
|---|---|
| `ros2 node list` | `/patrol`, `/turtlesim` |
| `ros2 node info /patrol` | Subscribers: `/turtle1/pose`; Publishers: `/cmd_vel` |
| `ros2 topic echo /cmd_vel --once` | `linear.x: 0.5`, `angular.z: 0.3` |
| `ros2 topic info /cmd_vel --verbose` | Publisher count: 1 (`patrol`), Subscription count: 0 |
| `ros2 topic info /turtle1/cmd_vel --verbose` | Publisher count: 0, Subscription count: 1 (`turtlesim`) |
| два чтения позы с интервалом в несколько секунд | обе: `x = y = 5.544444561004639`, `theta = 0.0`, `linear_velocity = 0.0` |

Команда 0.5 / 0.3 означает, что поза до patrol доходит (без позы команда была бы нулевой). Сломан
только выход. Причина: имя `cmd_vel` относительное, нода живёт в корневом namespace `/`, поэтому
полное имя — `/cmd_vel`. turtlesim подписан на `/turtle1/cmd_vel`. Discovery видит обе конечные
точки, но это два разных топика: у издателя нет подписчика, у подписчика нет издателя. Совпадение
типа `geometry_msgs/msg/Twist` топики не связывает. Черепаха стоит в точке появления.

## 2. Исправление: remap при запуске (`logs/2-fixed.txt`)

Изменён только запуск: `ros2 run patrol patrol --ros-args -r cmd_vel:=/turtle1/cmd_vel`. Код,
тип, скорости и домен прежние.

| Проверка | Результат |
|---|---|
| `ros2 node info /patrol` | Subscribers: `/turtle1/pose`; Publishers: `/turtle1/cmd_vel` |
| `ros2 topic info /turtle1/cmd_vel --verbose` | Publisher count: 1 (`patrol`), Subscription count: 1 (`turtlesim`) |
| `ros2 topic info /cmd_vel --verbose` | `Unknown topic '/cmd_vel'` |
| `ros2 topic echo /turtle1/cmd_vel --once` | `linear.x: 0.5`, `angular.z: 0.3` |
| два чтения позы | координаты и `theta` меняются, `linear_velocity = 0.5`, `angular_velocity ≈ 0.3` |

Два чтения позы из `logs/summary.txt`:

```text
2-fixed: поза 1 = (6.180, 8.750, theta=2.746) в 20:08:22.961
2-fixed: поза 2 = (4.237, 8.250, theta=-2.246) в 20:08:27.277
2-fixed: между чтениями 4.3 с, dtheta = 1.29 рад (ожидаемо 0.3 рад/с * 4.3 с = 1.29 рад, по модулю 2pi)
```

Между чтениями больше 3 с паузы скрипта: к ней добавляется время запуска второго
`ros2 topic echo`. Изменение угла совпадает с `angular.z = 0.3`: поза поступает в patrol, команда
доходит до turtlesim, черепаха едет по окружности радиусом `0.5 / 0.3 ≈ 1.67`.

## 3. Реальная частота команды (`logs/3-hz.txt`)

```bash
timeout -s INT 20s ros2 topic hz /turtle1/cmd_vel
```

Первые секунды уходят на запуск `ros2 topic hz` и discovery, поэтому команда работает 20 с. Итоговое
окно (`window`) — число интервалов между принятыми сообщениями; при 0.1 с на интервал 100 интервалов
= 10 с. Последний вывод:

```text
average rate: 9.999
	min: 0.099s max: 0.101s std dev: 0.00053s window: 181
```

Средняя частота — 10 Гц, как задано таймером (0.1 с), на окне больше 10 с. `ros2 topic hz` меряет
моменты **приёма**, поэтому в интервалы входят и дрожание таймера, и доставка. В этом прогоне
интервалы между приёмами — от 0.099 до 0.101 с, среднее 9.999 Гц. Таймер задаёт намерение, фактический поток видно
только измерением.

## 4. Остановка patrol (`logs/4-stop.txt`)

`scripts/stop_probe.py` подписан на `/turtle1/pose`. Он посылает SIGINT группе процессов patrol
(как Ctrl+C в терминале B) и следит за позой ещё 3 с:

```text
до SIGINT: x=3.8744 y=7.1651 theta=-1.5456 linear_velocity=0.50
последнее изменение позы через 0.960 с после SIGINT
через 3.0 с: x=3.9561 y=6.6938 theta=-1.2576 linear_velocity=0.00
```

После этого `ros2 node list` показывает только `/turtlesim`, а поза остаётся неподвижной с
`linear_velocity: 0.0`. Процесс patrol выходит по SIGINT почти сразу: при остановке первой копии
между SIGINT и пустой группой процессов прошло около 0.3 с (`logs/processes.txt`). Черепаха же
ехала по последней команде ещё меньше секунды и остановилась только по таймауту turtlesim: он
обнуляет скорость, если новая команда не приходила 1 с. Исчезновение издателя не равно команде
торможения. Чтобы остановить робота сразу, нужно явно отправить нулевой Twist или иметь watchdog
на стороне исполнителя.

## 5. Остановка launch (`logs/5-shutdown.txt`)

Ctrl+C (SIGINT группе процессов терминала A) завершает `ros2 launch`: он передаёт SIGINT
turtlesim, и группа процессов пустеет за доли секунды (`logs/processes.txt`). После этого
`ros2 node list` пуст.

## До / сбой / после

| | Сбой: `ros2 run patrol patrol` | После: `... --ros-args -r cmd_vel:=/turtle1/cmd_vel` |
|---|---|---|
| издатель patrol | `/cmd_vel` | `/turtle1/cmd_vel` |
| `/turtle1/cmd_vel` | 0 издателей, 1 подписчик | 1 издатель (`patrol`), 1 подписчик (`turtlesim`) |
| поза в patrol | поступает (команда 0.5 / 0.3) | поступает (команда 0.5 / 0.3) |
| черепаха | стоит | едет по окружности |
| частота команды | — | ≈10 Гц на окне больше 10 с (`logs/3-hz.txt`) |

## Тесты

`tests.txt` — вывод `colcon build`, `python3 -m pytest -v src/patrol/test`, `colcon test` и
`colcon test-result` (снимает `scripts/tests.sh`):

- `test_command.py`: чистая функция без ROS-графа — нет позы → нулевой Twist; обычная поза →
  0.5 / 0.3, остальные поля нулевые; поза не меняется; ограничение скоростей;
- `test_patrol_node.py`: без remap издатель разрешается в `/cmd_vel`, с remap — в
  `/turtle1/cmd_vel`; период таймера 100 мс; пробная нода получает нулевые команды до первой позы и
  0.5 / 0.3 после неё. Топики теста переименованы в `/pr03_test_<pid>/...`, поэтому тест не мешает
  работающему turtlesim и параллельной копии теста;
- линтеры `ament_flake8` и `ament_pep257` проверяют только каталог пакета, даже если pytest
  запущен из корня репозитория.
