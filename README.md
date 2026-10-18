# Robotics ROS 2 practices

## PR01 — ROS 2 environment and graph

Environment:
- Ubuntu 24.04.5 LTS under WSL2
- ROS 2 Jazzy
- Gazebo 8.15.0
- RMW: rmw_fastrtps_cpp

### Normal graph

Terminal A:

export ROS_DOMAIN_ID=16
ros2 run turtlesim turtlesim_node

Terminal B:

export ROS_DOMAIN_ID=16
ros2 run turtlesim turtle_teleop_key

Terminal C:

export ROS_DOMAIN_ID=16
ros2 node list --no-daemon --spin-time 2
ros2 topic list -t
ros2 node info /turtlesim
ros2 topic type /turtle1/pose
ros2 topic echo /turtle1/pose --once
ros2 topic hz /turtle1/pose

### Broken discovery

Keep turtlesim in domain 16.

Restart teleop in domain 17:

export ROS_DOMAIN_ID=17
ros2 run turtlesim turtle_teleop_key

In observer terminal:

export ROS_DOMAIN_ID=17
ros2 node list --no-daemon --spin-time 2

### Restore discovery

Restart teleop and observer in domain 16.

Expected result:
- domain 16 / 16: communication works
- domain 16 / 17: communication is lost
- domain 16 / 16 again: communication is restored

## PR02 — turtle_bringup

Создан ROS 2 пакет `turtle_bringup` с launch-файлом для запуска `turtlesim`.

Сборка:

`source /opt/ros/jazzy/setup.bash`
`colcon build --symlink-install --packages-select turtle_bringup`
`source install/setup.bash`

Запуск:

`export ROS_DOMAIN_ID=16`
`ros2 launch turtle_bringup sim.launch.py`

Для управления использовался топик `/turtle1/cmd_vel` типа `geometry_msgs/msg/Twist`.
При публикации того же сообщения в `/cmd_vel` publisher существовал, но подписчиков не было.
После исправления имени на `/turtle1/cmd_vel` движение восстановилось.

## PR03 — patrol

Пакет `patrol` с нодой `/patrol`:
- подписка на `/turtle1/pose` только сохраняет последнюю позу;
- таймер с периодом 0.1 с публикует `geometry_msgs/msg/Twist` в относительный топик `cmd_vel`;
- до первой позы команда нулевая, после — `linear.x = 0.5`, `angular.z = 0.3`;
- выбор команды вынесен в чистую функцию `patrol.command.choose_command`, скорости ограничиваются `limit_command`.

Сборка и тесты:

```bash
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select patrol
source install/setup.bash
python3 -m pytest src/patrol/test
```

Запуск в новом терминале из корня репозитория (turtlesim уже запущен через `ros2 launch turtle_bringup sim.launch.py`):

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=16
ros2 run patrol patrol --ros-args -r cmd_vel:=/turtle1/cmd_vel
```

Без remap относительное имя `cmd_vel` разрешается в `/cmd_vel`: у него есть издатель `/patrol`, но нет подписчика turtlesim, и черепаха стоит.

## PR04 — параметры patrol

Нода `/patrol` читает три параметра и меняет их на лету через `ros2 param set`:

| Параметр | По умолчанию | Допустимо | Что меняет |
|---|---|---|---|
| `linear_speed` | 0.5 м/с | конечное число, 0…1 | `linear.x` команды |
| `turn_rate` | 0.3 рад/с | конечное число, −1…1 | `angular.z` команды |
| `publish_hz` | 10.0 Гц | конечное число, 1…30 | период таймера `1/publish_hz` |

- Проверка значений — чистая функция `patrol.parameters.apply_changes` в колбэке
  `add_on_set_parameters_callback`: недопустимое значение отклоняется до записи параметра,
  таймер и активные настройки не меняются. Колбэк регистрируется до объявления параметров,
  поэтому недопустимое `-p` при запуске тоже отклоняется.
- Применение — в `add_post_set_parameters_callback`: при смене `publish_hz` создаётся новый
  таймер с периодом `1/publish_hz`, прежний останавливается и удаляется — у ноды один таймер.
- Тип параметров — `double`: целое (`ros2 param set /patrol publish_hz 5`, `-p publish_hz:=5`)
  rclpy отклоняет, нужно писать `5.0`.

Запуск (turtlesim уже запущен через `ros2 launch turtle_bringup sim.launch.py`):

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=16
ros2 run patrol patrol --ros-args -r cmd_vel:=/turtle1/cmd_vel
# в другом терминале
ros2 param set /patrol publish_hz 5.0     # Set parameter successful, поток ~5 Гц
ros2 param set /patrol publish_hz 0.0     # Setting parameter failed, остаётся 5 Гц
```

Тесты: `python3 -m pytest src/patrol/test`. Опыт и дефект (ветка `pr04-defect`, проверка частоты
отключена) — `evidence/pr04/parameters.md`.
