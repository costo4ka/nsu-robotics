#!/usr/bin/env python3
"""Собрать evidence/pr04/parameters.md и tests.txt из логов experiment.sh и tests.sh.

Запуск из корня репозитория после обоих режимов опыта и тестов:
    python3 evidence/pr04/scripts/render.py
Все блоки text в parameters.md — вывод команд из logs/ без правок; длинный вывод
ros2 topic hz сокращён до последних строк, полностью он лежит в logs/.
"""

import re
import sys
from pathlib import Path

EVIDENCE = Path('evidence/pr04')
LOGS = EVIDENCE / 'logs'
ENTRY = re.compile(r'^\$ (.*?)\n(.*?)\[exit=(\d+), ([\d:.]+)\]\n', re.S | re.M)
TEST_LINE = re.compile(r'^(src/patrol/test/\S+::\S+) (PASSED|FAILED|SKIPPED|ERROR)', re.M)


def read(path):
    if not path.is_file():
        sys.exit(f'нет {path}: сначала запустите tests.sh и experiment.sh в обоих режимах')
    return path.read_text(encoding='utf-8')


def env(mode):
    values = {}
    for line in read(LOGS / mode / 'env.txt').splitlines():
        key, sep, value = line.partition(': ')
        if sep and key in ('date', 'branch', 'HEAD', 'kernel'):
            values[key] = value
        elif line.startswith('ROS_DISTRO='):
            values['ros'] = line
        elif line.startswith('PRETTY_NAME='):
            values['os'] = line.split('=', 1)[1].strip('"')
    return values


def block(mode, name, only=None):
    """Блок text из лога: команды с выводом; для ros2 topic hz — последние две строки."""
    path = LOGS / mode / name
    parts = []
    for command, output, rc, stamp in ENTRY.findall(read(path)):
        if only is not None and not any(word in command for word in only):
            continue
        lines = output.rstrip('\n').split('\n') if output.strip() else []
        if 'ros2 topic hz' in command and len(lines) > 2:
            lines = [f'... (полностью: {path})'] + lines[-2:]
        parts.append('\n'.join([f'$ {command}'] + lines + [f'[exit={rc}, {stamp}]']))
    return '```text\n' + '\n\n'.join(parts) + '\n```'


def test_statuses(mode):
    return dict(TEST_LINE.findall(read(LOGS / f'tests-{mode}.txt')))


def same_tests_table():
    """Упавшие на ветке дефекта тесты: конкретная ошибка (pytest --tb=line) и статус на main.

    При --tb=line pytest печатает в разделе FAILURES по одной строке на упавший тест
    в том же порядке, что и строки FAILED выше.
    """
    text = read(LOGS / 'tests-defect.txt').replace(str(Path.cwd()) + '/', '')
    failed = [name for name, status in TEST_LINE.findall(text) if status in ('FAILED', 'ERROR')]
    section = re.search(r'^=+ FAILURES =+\n(.*?)^=+ ', text, re.S | re.M)
    errors = section.group(1).strip().split('\n') if section else []
    if len(errors) != len(failed):
        errors = ['(см. tests.txt)'] * len(failed)
    fixed = test_statuses('fixed')
    rows = ['| Тест | Ошибка на ветке дефекта | main |', '|---|---|---|']
    for name, error in zip(failed, errors):
        rows.append(f'| `{name.split("::", 1)[1]}` | `{error.strip()}` | {fixed.get(name, "?")} |')
    return '\n'.join(rows), len(failed), len(test_statuses('defect'))


def main():
    fixed, defect = env('fixed'), env('defect')
    table, failed, total = same_tests_table()
    summary_fixed = read(LOGS / 'fixed' / 'summary.txt').strip()
    summary_defect = read(LOGS / 'defect' / 'summary.txt').strip()
    if 'ОШИБКА' in summary_fixed + summary_defect:
        sys.exit('в summary.txt есть ОШИБКА: повторите experiment.sh этого режима')
    if failed == 0 or any(status != 'PASSED' and status != 'SKIPPED'
                          for status in test_statuses('fixed').values()):
        sys.exit('нужны упавшие тесты на ветке дефекта и все прошедшие на main: повторите tests.sh')
    pose_type = re.search(r'ros2 topic type /turtle1/pose\n(\S+)', read(LOGS / 'fixed' / '1-start.txt'))

    text = f'''# ПР04 — параметры patrol

Документ собран скриптом `evidence/pr04/scripts/render.py` из логов `evidence/pr04/logs/`:
все блоки `text` ниже — реальный вывод команд (у `ros2 topic hz` оставлены последние строки,
полный вывод — в `logs/`). Опыт запускался `evidence/pr04/scripts/experiment.sh`, тесты —
`evidence/pr04/scripts/tests.sh`.

- Среда: {fixed.get('os', '?')} (ядро `{fixed.get('kernel', '?')}`), `{fixed.get('ros', '?')}`.
- Исправный код: ветка `{fixed.get('branch')}`, коммит `{fixed.get('HEAD')}`, прогон {fixed.get('date')}.
- Дефект: ветка `{defect.get('branch')}`, коммит `{defect.get('HEAD')}`, прогон {defect.get('date')}.
- Тип позы: `{pose_type.group(1) if pose_type else '?'}` (`ros2 topic type /turtle1/pose`).

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

{block('fixed', '1-start.txt')}

{block('fixed', '2-hz-10.txt')}

## 2. Допустимое изменение 10 → 5 Гц меняет поток

{block('fixed', '3-set-5.txt')}

## 3. Ноль отклонён, старая частота сохранена

Нода отвечает отказом с причиной, `publish_hz` остаётся 5.0, поток идёт с прежней частотой,
процесс patrol работает.

{block('fixed', '4-set-0.txt')}

## 4. Отрицательное значение, NaN, вне диапазона, целое

`.nan` — это NaN в синтаксисе YAML, которым `ros2 param set` разбирает значение: тип `double`
проходит, отказ даёт проверка ноды. Целое `5` отклоняет rclpy, потому что параметр объявлен как
`double`. Ни одно из значений не изменило частоту.

{block('fixed', '5-invalid.txt')}

## 5. `linear_speed` и `turn_rate` меняют команду

{block('fixed', '6-speeds.txt')}

## 6. Сломать: проверка частоты отключена (ветка `{defect.get('branch')}`)

В отдельной ветке одним коммитом (`evidence/pr04/defect.patch`) проверка `publish_hz`
выключена — `check_value` принимает любое значение частоты:

{block('defect', 'env.txt')}

Тот же опыт. Изменение 10 → 5 Гц работает как раньше:

{block('defect', '3-set-5.txt')}

Ноль: `ros2 param set` не получает ответа (обрыв по `timeout`), нода patrol падает
с `ZeroDivisionError`, издателя `/turtle1/cmd_vel` больше нет, команды не идут.

{block('defect', '4-set-0.txt')}

## 7. Причина и доказательство исправления

Причина: без проверки значение 0.0 записывается в параметр, затем post-set колбэк пересоздаёт
таймер и считает период `1.0 / publish_hz` — `ZeroDivisionError`. Исключение вылетает из
обработчика сервиса `set_parameters` прямо в `rclpy.spin`, поэтому ответ клиенту не уходит,
а процесс ноды завершается с кодом 1. Отрицательная частота так же ломает ноду (rcl:
«timer period must be non-negative»), NaN — при пересчёте периода в наносекунды.

Исправление — проверка в колбэке **до** записи: `apply_changes` отклоняет недопустимое значение,
параметр, настройки и таймер не трогаются. Тот же набор тестов на ветке дефекта
и на `main`: с дефектом падают {failed} из {total}, после исправления все проходят.
Среди них — тест чистой функции для 0, отрицательного значения и NaN
(`test_invalid_publish_hz_keeps_previous_settings`) и тест живого потока
(`test_stream_rate_follows_publish_hz_and_survives_zero`).

{table}

Ошибки — строки `pytest --tb=line`, полный вывод тестов — `evidence/pr04/tests.txt`.

## 8. Готовый сервис `/clear` и действие `/turtle1/rotate_absolute`

{block('fixed', '7-clear-action.txt')}

Запрос сервиса (`/clear`, `std_srvs/srv/Empty`) — короткий вызов «запрос → один ответ», без
промежуточного состояния и без отмены. Цель действия (`/turtle1/rotate_absolute`,
`turtlesim/action/RotateAbsolute`) запускает долгую работу: сервер принимает или отклоняет цель,
шлёт feedback (оставшийся угол), её можно отменить, а результат приходит только в конце.

## Журнал ноды patrol (исправный прогон)

```text
{read(LOGS / 'fixed' / 'patrol-node.txt').strip()}
```

## Сводка логов

```text
{summary_fixed}

{summary_defect}
```
'''
    (EVIDENCE / 'parameters.md').write_text(text, encoding='utf-8')

    tests = (
        '# ПР04: тесты. Сначала исправный код (main), затем тот же набор на ветке дефекта.\n'
        '# Источник: evidence/pr04/logs/tests-fixed.txt и tests-defect.txt (scripts/tests.sh).\n\n'
        + read(LOGS / 'tests-fixed.txt')
        + '\n# ---------------------------------------------------------------------------\n\n'
        + read(LOGS / 'tests-defect.txt'))
    (EVIDENCE / 'tests.txt').write_text(tests, encoding='utf-8')
    print(f'{EVIDENCE}/parameters.md, {EVIDENCE}/tests.txt: собраны')


if __name__ == '__main__':
    main()
