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
