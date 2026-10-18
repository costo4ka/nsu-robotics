# ПР04 — параметры patrol

Документ собран скриптом `evidence/pr04/scripts/render.py` из логов `evidence/pr04/logs/`:
все блоки `text` ниже — реальный вывод команд (у `ros2 topic hz` оставлены последние строки,
полный вывод — в `logs/`). Опыт запускался `evidence/pr04/scripts/experiment.sh`, тесты —
`evidence/pr04/scripts/tests.sh`.

- Среда: Ubuntu 24.04.2 LTS (ядро `6.14.0-37-generic`), `ROS_DISTRO=jazzy ROS_DOMAIN_ID=16 RMW=default`.
- Исправный код: ветка `main`, коммит `8f8b26b978489553c5d4701cdd56ab589e359320`, прогон 2026-10-18T22:51:07+07:00.
- Дефект: ветка `pr04-defect`, коммит `726530cd144e95fc45990b91d524dc20f0d5f9e3`, прогон 2026-10-18T22:49:25+07:00.
- Тип позы: `turtlesim/msg/Pose` (`ros2 topic type /turtle1/pose`).

## Параметры

| Параметр | По умолчанию | Допустимо | Что меняет |
|---|---|---|---|
| `linear_speed` | 0.5 м/с | конечное число, 0…1 | `linear.x` команды |
| `turn_rate` | 0.3 рад/с | конечное число, −1…1 | `angular.z` команды |
| `publish_hz` | 10.0 Гц | конечное число, 1…30 | период таймера `1/publish_hz` |

Как устроено (`src/patrol/patrol/patrol.py`, `src/patrol/patrol/parameters.py`):

- проверка — колбэк `add_on_set_parameters_callback`. Он вызывается **до** записи значения и
  отклоняет весь запрос, если недопустимо хоть одно значение (чистая функция `apply_changes`).
  Колбэк регистрируется до `declare_parameter`, поэтому плохое значение из `-p` при запуске
  тоже отклоняется;
- применение — колбэк `add_post_set_parameters_callback`, только после успешной записи. При смене
  `publish_hz` создаётся новый таймер с периодом `1/publish_hz`, затем прежний останавливается
  (`cancel`) и удаляется (`destroy_timer`). Функциональный тест проверяет, что у ноды
  ровно один таймер;
- параметры объявлены как `double`; целое `5` отклоняет сам rclpy (тип параметра не совпадает).

Вручную опыт повторяется в трёх терминалах (`source install/setup.bash`, `ROS_DOMAIN_ID=16`):

```bash
# терминал 1
ros2 launch turtle_bringup sim.launch.py
# терминал 2
ros2 run patrol patrol --ros-args -r cmd_vel:=/turtle1/cmd_vel
# терминал 3
ros2 param get /patrol publish_hz
ros2 topic hz /turtle1/cmd_vel            # ~10 Гц, Ctrl+C
ros2 param set /patrol publish_hz 5.0
ros2 topic hz /turtle1/cmd_vel            # ~5 Гц
ros2 param set /patrol publish_hz 0.0     # отказ, частота остаётся 5 Гц
```

## 1. Собрать: запуск с параметрами по умолчанию

```text
$ ros2 node list
/patrol
/turtlesim
[exit=0, 22:51:20.106]

$ ros2 topic type /turtle1/pose
turtlesim/msg/Pose
[exit=0, 22:51:20.467]

$ ros2 param list /patrol
  linear_speed
  publish_hz
  start_type_description_service
  turn_rate
  use_sim_time
[exit=0, 22:51:22.976]

$ ros2 param describe /patrol publish_hz --timeout 5
Parameter name: publish_hz
  Type: double
  Description: command timer rate, Hz, finite, 1..30; the timer is recreated on change
  Constraints:
[exit=0, 22:51:25.477]

$ ros2 param get /patrol linear_speed --timeout 5
Double value is: 0.5
[exit=0, 22:51:28.482]

$ ros2 param get /patrol turn_rate --timeout 5
Double value is: 0.3
[exit=0, 22:51:31.520]

$ ros2 param get /patrol publish_hz --timeout 5
Double value is: 10.0
[exit=0, 22:51:34.521]
```

```text
$ timeout -s INT 9s ros2 topic hz /turtle1/cmd_vel
... (полностью: evidence/pr04/logs/fixed/2-hz-10.txt)
average rate: 10.000
	min: 0.100s max: 0.100s std dev: 0.00012s window: 54
[exit=124, 22:51:43.658]
```

## 2. Допустимое изменение 10 → 5 Гц меняет поток

```text
$ ros2 param set /patrol publish_hz 5.0 --timeout 5
Set parameter successful
[exit=0, 22:51:47.183]

$ ros2 param get /patrol publish_hz --timeout 5
Double value is: 5.0
[exit=0, 22:51:49.936]

$ timeout -s INT 9s ros2 topic hz /turtle1/cmd_vel
... (полностью: evidence/pr04/logs/fixed/3-set-5.txt)
average rate: 5.000
	min: 0.200s max: 0.200s std dev: 0.00006s window: 29
[exit=124, 22:51:59.083]
```

## 3. Ноль отклонён, старая частота сохранена

Нода отвечает отказом с причиной, `publish_hz` остаётся 5.0, поток идёт с прежней частотой,
процесс patrol работает.

```text
$ ros2 param set /patrol publish_hz 0.0 --timeout 5
Setting parameter failed: publish_hz must be in [1.0, 30.0], got 0.0
[exit=0, 22:52:07.850]

$ ros2 param get /patrol publish_hz --timeout 5
Double value is: 5.0
[exit=0, 22:52:10.873]

$ timeout -s INT 9s ros2 topic hz /turtle1/cmd_vel
... (полностью: evidence/pr04/logs/fixed/4-set-0.txt)
average rate: 5.119
	min: 0.065s max: 0.200s std dev: 0.02460s window: 29
[exit=124, 22:52:20.013]

$ alive patrol
patrol: процесс работает
[exit=0, 22:52:20.015]
```

## 4. Отрицательное значение, NaN, вне диапазона, целое

`.nan` — это NaN в синтаксисе YAML, которым `ros2 param set` разбирает значение: тип `double`
проходит, отказ даёт проверка ноды. Целое `5` отклоняет rclpy, потому что параметр объявлен как
`double`. Ни одно из значений не изменило частоту.

```text
$ ros2 param set /patrol publish_hz -2.0 --timeout 5
Setting parameter failed: publish_hz must be in [1.0, 30.0], got -2.0
[exit=0, 22:52:23.175]

$ ros2 param set /patrol publish_hz .nan --timeout 5
Setting parameter failed: publish_hz must be a finite number, got nan
[exit=0, 22:52:25.691]

$ ros2 param set /patrol publish_hz 31.0 --timeout 5
Setting parameter failed: publish_hz must be in [1.0, 30.0], got 31.0
[exit=0, 22:52:28.522]

$ ros2 param set /patrol publish_hz 5 --timeout 5
Setting parameter failed: Wrong parameter type, expected 'Type.DOUBLE' got 'Type.INTEGER'
[exit=0, 22:52:31.528]

$ ros2 param get /patrol publish_hz --timeout 5
Double value is: 5.0
[exit=0, 22:52:34.799]
```

## 5. `linear_speed` и `turn_rate` меняют команду

```text
$ ros2 param set /patrol linear_speed 1.0 --timeout 5
Set parameter successful
[exit=0, 22:52:37.806]

$ ros2 param set /patrol turn_rate -0.5 --timeout 5
Set parameter successful
[exit=0, 22:52:40.873]

$ timeout 5s ros2 topic echo /turtle1/cmd_vel geometry_msgs/msg/Twist --once
linear:
  x: 1.0
  y: 0.0
  z: 0.0
angular:
  x: 0.0
  y: 0.0
  z: -0.5
---
[exit=0, 22:52:43.849]

$ ros2 param set /patrol linear_speed 1.5 --timeout 5
Setting parameter failed: linear_speed must be in [0.0, 1.0], got 1.5
[exit=0, 22:52:46.874]

$ ros2 param get /patrol linear_speed --timeout 5
Double value is: 1.0
[exit=0, 22:52:49.872]

$ timeout 5s ros2 topic echo /turtle1/cmd_vel geometry_msgs/msg/Twist --once
linear:
  x: 1.0
  y: 0.0
  z: 0.0
angular:
  x: 0.0
  y: 0.0
  z: -0.5
---
[exit=0, 22:52:52.848]
```

## 6. Сломать: проверка частоты отключена (ветка `pr04-defect`)

В отдельной ветке одним коммитом (`evidence/pr04/defect.patch`) проверка `publish_hz`
выключена — `check_value` принимает любое значение частоты:

```text
$ git log --oneline -3
726530c PR04: temporarily disable publish_hz check
8f8b26b PR04: runtime parameters for patrol
c0789b2 PR03: record evidence and AI usage
[exit=0, 22:49:25.383]

$ git diff HEAD~1 HEAD -- src
diff --git a/src/patrol/patrol/parameters.py b/src/patrol/patrol/parameters.py
index 23fd891..1a90544 100644
--- a/src/patrol/patrol/parameters.py
+++ b/src/patrol/patrol/parameters.py
@@ -27,6 +27,8 @@ class Settings:
 
 def check_value(name, value):
     """Вернуть причину отказа или None, если значение допустимо."""
+    if name == 'publish_hz':
+        return None  # ДЕФЕКТ ПР04: проверка частоты временно отключена
     low, high = LIMITS[name]
     if isinstance(value, bool) or not isinstance(value, (int, float)):
         return f'{name} must be a number, got {value!r}'
[exit=0, 22:49:25.386]
```

Тот же опыт. Изменение 10 → 5 Гц работает как раньше:

```text
$ ros2 param set /patrol publish_hz 5.0 --timeout 5
Set parameter successful
[exit=0, 22:49:55.212]

$ ros2 param get /patrol publish_hz --timeout 5
Double value is: 5.0
[exit=0, 22:49:58.718]

$ timeout -s INT 9s ros2 topic hz /turtle1/cmd_vel
... (полностью: evidence/pr04/logs/defect/3-set-5.txt)
average rate: 5.000
	min: 0.200s max: 0.200s std dev: 0.00013s window: 29
[exit=124, 22:50:07.856]
```

Ноль: `ros2 param set` не получает ответа (обрыв по `timeout`), нода patrol падает
с `ZeroDivisionError`, издателя `/turtle1/cmd_vel` больше нет, команды не идут.

```text
$ timeout 15s ros2 param set /patrol publish_hz 0.0 --timeout 5
[exit=124, 22:50:22.993]

$ alive patrol
patrol: процесса нет
[exit=0, 22:50:22.997]

$ terminal_output patrol
[INFO] [1792338595.078554489] [patrol]: linear_speed=0.5 turn_rate=0.3 publish_hz=5.0 (timer period 0.200 s)
Traceback (most recent call last):
  File "/tmp/robotics/install/patrol/lib/patrol/patrol", line 33, in <module>
    sys.exit(load_entry_point('patrol', 'console_scripts', 'patrol')())
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/tmp/robotics/build/patrol/patrol/patrol.py", line 79, in main
    rclpy.spin(node)
  File "/opt/ros/jazzy/lib/python3.12/site-packages/rclpy/__init__.py", line 247, in spin
    executor.spin_once()
  File "/opt/ros/jazzy/lib/python3.12/site-packages/rclpy/executors.py", line 926, in spin_once
    self._spin_once_impl(timeout_sec)
  File "/opt/ros/jazzy/lib/python3.12/site-packages/rclpy/executors.py", line 918, in _spin_once_impl
    raise handler.exception()
  File "/opt/ros/jazzy/lib/python3.12/site-packages/rclpy/task.py", line 286, in _execute_coroutine_step
    result = coro.send(None)
             ^^^^^^^^^^^^^^^
  File "/opt/ros/jazzy/lib/python3.12/site-packages/rclpy/executors.py", line 592, in handler
    await call_coroutine()
  File "/opt/ros/jazzy/lib/python3.12/site-packages/rclpy/executors.py", line 531, in _execute
    response = await await_or_execute(srv.callback, request, srv.srv_type.Response())
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/ros/jazzy/lib/python3.12/site-packages/rclpy/executors.py", line 115, in await_or_execute
    return callback(*args)
           ^^^^^^^^^^^^^^^
  File "/opt/ros/jazzy/lib/python3.12/site-packages/rclpy/parameter_service.py", line 117, in _set_parameters_callback
    result = node.set_parameters_atomically([param])
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/ros/jazzy/lib/python3.12/site-packages/rclpy/node.py", line 839, in set_parameters_atomically
    return self._set_parameters_atomically(parameter_list)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/ros/jazzy/lib/python3.12/site-packages/rclpy/node.py", line 859, in _set_parameters_atomically
    return self._set_parameters_atomically_common(parameter_list)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/ros/jazzy/lib/python3.12/site-packages/rclpy/node.py", line 962, in _set_parameters_atomically_common
    self._call_post_set_parameters_callback(parameter_list)
  File "/opt/ros/jazzy/lib/python3.12/site-packages/rclpy/node.py", line 1055, in _call_post_set_parameters_callback
    callback(parameter_list)
  File "/tmp/robotics/build/patrol/patrol/patrol.py", line 54, in apply_parameters
    self.restart_timer(settings.period_sec)
                       ^^^^^^^^^^^^^^^^^^^
  File "/tmp/robotics/build/patrol/patrol/parameters.py", line 25, in period_sec
    return 1.0 / self.publish_hz
           ~~~~^~~~~~~~~~~~~~~~~
ZeroDivisionError: float division by zero
[ros2run]: Process exited with failure 1
[exit=0, 22:50:23.000]

$ ros2 node list
/turtlesim
[exit=0, 22:50:28.171]

$ ros2 topic info /turtle1/cmd_vel
Type: geometry_msgs/msg/Twist
Publisher count: 0
Subscription count: 1
[exit=0, 22:50:28.538]

$ timeout -s INT 9s ros2 topic hz /turtle1/cmd_vel
WARNING: topic [/turtle1/cmd_vel] does not appear to be published yet
[exit=124, 22:50:37.673]
```

## 7. Причина и доказательство исправления

Причина: без проверки значение 0.0 записывается в параметр, затем post-set колбэк пересоздаёт
таймер и считает период `1.0 / publish_hz` — `ZeroDivisionError`. Исключение вылетает из
обработчика сервиса `set_parameters` прямо в `rclpy.spin`, поэтому ответ клиенту не уходит,
а процесс ноды завершается с кодом 1. Отрицательная частота так же ломает ноду (rcl:
«timer period must be non-negative»), NaN — при пересчёте периода в наносекунды.

Исправление — проверка в колбэке **до** записи: `apply_changes` отклоняет недопустимое значение,
параметр, настройки и таймер не трогаются. Тот же набор тестов на ветке дефекта
и на `main`: с дефектом падают 17 из 55, после исправления все проходят.
Среди них — тест чистой функции для 0, отрицательного значения и NaN
(`test_invalid_publish_hz_keeps_previous_settings`) и тест живого потока
(`test_stream_rate_follows_publish_hz_and_survives_zero`).

| Тест | Ошибка на ветке дефекта | main |
|---|---|---|
| `test_invalid_publish_hz_keeps_previous_settings[0.0]` | `src/patrol/test/test_parameters.py:24: assert (None is not None)` | PASSED |
| `test_invalid_publish_hz_keeps_previous_settings[-5.0]` | `src/patrol/test/test_parameters.py:24: assert (None is not None)` | PASSED |
| `test_invalid_publish_hz_keeps_previous_settings[nan]` | `src/patrol/test/test_parameters.py:24: assert (None is not None)` | PASSED |
| `test_invalid_publish_hz_keeps_previous_settings[inf]` | `src/patrol/test/test_parameters.py:24: assert (None is not None)` | PASSED |
| `test_invalid_publish_hz_keeps_previous_settings[0.5]` | `src/patrol/test/test_parameters.py:24: assert (None is not None)` | PASSED |
| `test_invalid_publish_hz_keeps_previous_settings[30.5]` | `src/patrol/test/test_parameters.py:24: assert (None is not None)` | PASSED |
| `test_invalid_values_are_rejected[publish_hz-10]` | `src/patrol/test/test_parameters.py:44: AssertionError: assert None is not None` | PASSED |
| `test_invalid_values_are_rejected[publish_hz-True]` | `src/patrol/test/test_parameters.py:44: AssertionError: assert None is not None` | PASSED |
| `test_invalid_values_are_rejected[publish_hz-None]` | `src/patrol/test/test_parameters.py:44: AssertionError: assert None is not None` | PASSED |
| `test_one_invalid_value_rejects_the_whole_change` | `src/patrol/test/test_parameters.py:49: assert None is not None` | PASSED |
| `test_invalid_publish_hz_is_rejected_and_timer_kept[0.0]` | `build/patrol/patrol/parameters.py:25: ZeroDivisionError: float division by zero` | PASSED |
| `test_invalid_publish_hz_is_rejected_and_timer_kept[-5.0]` | `/opt/ros/jazzy/lib/python3.12/site-packages/rclpy/timer.py:60: rclpy._rclpy_pybind11.RCLError: failed to create timer: timer period must be non-negative, at ./src/rcl/timer.c:157` | PASSED |
| `test_invalid_publish_hz_is_rejected_and_timer_kept[nan]` | `/opt/ros/jazzy/lib/python3.12/site-packages/rclpy/node.py:1774: ValueError: cannot convert float NaN to integer` | PASSED |
| `test_invalid_publish_hz_is_rejected_and_timer_kept[inf]` | `src/patrol/test/test_patrol_node.py:171: AssertionError: assert not True` | PASSED |
| `test_invalid_publish_hz_is_rejected_and_timer_kept[31.0]` | `src/patrol/test/test_patrol_node.py:171: AssertionError: assert not True` | PASSED |
| `test_invalid_startup_value_is_rejected` | `build/patrol/patrol/parameters.py:25: ZeroDivisionError: float division by zero` | PASSED |
| `test_stream_rate_follows_publish_hz_and_survives_zero` | `build/patrol/patrol/parameters.py:25: ZeroDivisionError: float division by zero` | PASSED |

Ошибки — строки `pytest --tb=line`, полный вывод тестов — `evidence/pr04/tests.txt`.

## 8. Готовый сервис `/clear` и действие `/turtle1/rotate_absolute`

```text
$ ros2 service type /clear
std_srvs/srv/Empty
[exit=0, 22:52:53.200]

$ ros2 service call /clear std_srvs/srv/Empty
waiting for service to become available...
requester: making request: std_srvs.srv.Empty_Request()

response:
std_srvs.srv.Empty_Response()
[exit=0, 22:52:55.459]

$ ros2 action list -t
/turtle1/rotate_absolute [turtlesim/action/RotateAbsolute]
[exit=0, 22:52:55.815]

$ ros2 action info /turtle1/rotate_absolute -t
Action: /turtle1/rotate_absolute
Action clients: 0
Action servers: 1
    /turtlesim [turtlesim/action/RotateAbsolute]
[exit=0, 22:52:56.180]
```

Запрос сервиса (`/clear`, `std_srvs/srv/Empty`) — короткий вызов «запрос → один ответ», без
промежуточного состояния и без отмены. Цель действия (`/turtle1/rotate_absolute`,
`turtlesim/action/RotateAbsolute`) запускает долгую работу: сервер принимает или отклоняет цель,
шлёт feedback (оставшийся угол), её можно отменить, а результат приходит только в конце.

## Журнал ноды patrol (исправный прогон)

```text
[INFO] [1792338707.045539226] [patrol]: linear_speed=0.5 turn_rate=0.3 publish_hz=5.0 (timer period 0.200 s)
[WARN] [1792338727.714403887] [patrol]: rejected: publish_hz must be in [1.0, 30.0], got 0.0
[WARN] [1792338742.989591948] [patrol]: rejected: publish_hz must be in [1.0, 30.0], got -2.0
[WARN] [1792338745.555132913] [patrol]: rejected: publish_hz must be a finite number, got nan
[WARN] [1792338748.321395495] [patrol]: rejected: publish_hz must be in [1.0, 30.0], got 31.0
[INFO] [1792338757.673246981] [patrol]: linear_speed=1.0 turn_rate=0.3 publish_hz=5.0 (timer period 0.200 s)
[INFO] [1792338760.738908884] [patrol]: linear_speed=1.0 turn_rate=-0.5 publish_hz=5.0 (timer period 0.200 s)
[WARN] [1792338766.739687076] [patrol]: rejected: linear_speed must be in [0.0, 1.0], got 1.5
```

## Сводка логов

```text
# Сводка логов режима fixed (для parameters.md)
hz до изменения: average rate 10.000, min 0.100s, max 0.100s, window 54
hz после 5.0: average rate 5.000, min 0.200s, max 0.200s, window 29
hz после 0.0: average rate 5.119, min 0.065s, max 0.200s, window 29
set 5.0: Set parameter successful [exit=0]
set 0.0: Setting parameter failed: publish_hz must be in [1.0, 30.0], got 0.0 [exit=0]
код возврата patrol: 0

# Проверка опыта
OK     ros2 node list: /patrol и /turtlesim
OK     тип /turtle1/pose
OK     publish_hz по умолчанию 10.0
OK     ros2 param list: три параметра
OK     describe и значения по умолчанию 0.5 и 0.3
OK     по умолчанию поток ~10 Гц
OK     publish_hz 5.0 принят
OK     после 5.0 поток ~5 Гц
OK     publish_hz 0.0 отклонён с причиной
OK     после отказа publish_hz = 5.0
OK     после отказа поток ~5 Гц
OK     patrol работает после отказа
OK     publish_hz -2.0 отклонён
OK     publish_hz .nan отклонён
OK     publish_hz 31.0 отклонён
OK     publish_hz 5 отклонён
OK     после недопустимых значений publish_hz = 5.0
OK     команда linear.x = 1.0, angular.z = -0.5 до и после отказа 1.5
OK     linear_speed 1.5 отклонён
OK     ros2 action list -t показывает /turtle1/rotate_absolute
OK     /clear ответил
OK     patrol завершился по Ctrl+C с кодом 0

# Сводка логов режима defect (для parameters.md)
hz до изменения: average rate 10.000, min 0.099s, max 0.101s, window 64
hz после 5.0: average rate 5.000, min 0.200s, max 0.200s, window 29
hz после 0.0: нет сообщений
set 5.0: Set parameter successful [exit=0]
set 0.0: (нет вывода) [exit=124]
код возврата patrol: 1

# Проверка опыта
OK     ros2 node list: /patrol и /turtlesim
OK     тип /turtle1/pose
OK     publish_hz по умолчанию 10.0
OK     по умолчанию поток ~10 Гц
OK     publish_hz 5.0 принят
OK     после 5.0 поток ~5 Гц
OK     ros2 param set publish_hz 0.0 не получил ответа (timeout, exit=124)
OK     patrol упал с ненулевым кодом
OK     в логе patrol ZeroDivisionError
OK     у /turtle1/cmd_vel не осталось издателя
OK     команды больше не идут
```
