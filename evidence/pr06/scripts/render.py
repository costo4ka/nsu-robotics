#!/usr/bin/env python3
"""Собрать evidence/pr06/frames.md из модели и логов experiment.sh и tests.sh.

Запуск из корня репозитория (ветка main, после обоих режимов опыта и тестов):
    source install/setup.bash && python3 evidence/pr06/scripts/render.py
Таблица связей строится из развёрнутого vehicle.urdf.xacro текущего кода, блоки text — вывод
команд из logs/ без правок (у длинных выводов оставлены нужные строки, полностью — в logs/).
"""

import math
from pathlib import Path
import re
import sys

from course_description.urdf_tree import parse, transform
import xacro

EVIDENCE = Path('evidence/pr06')
LOGS = EVIDENCE / 'logs'
XACRO_FILE = Path('src/course_description/urdf/vehicle.urdf.xacro')
ENTRY = re.compile(r'^\$ (.*?)\n(.*?)\[exit=(\d+)(?:, ([\d:.]+))?[^\]]*\]\n', re.S | re.M)
TEST_LINE = re.compile(r'^(src/course_description/test/\S+::\S+) (PASSED|FAILED|SKIPPED|ERROR)', re.M)
NOISE = re.compile(r'^(GID|Topic type hash|Endpoint type|Topic type):')
ECHO_KEEP = r'Translation|Rotation: in RPY \(radian|At time'
STATIC_KEEP = r'frame_id|translation|rotation|x:|y:|z:|w:'
OWNER_KEEP = r'Publisher count|Subscription count|Node name|Reliability|Durability|^/'
MOVING_KEEP = r'Publisher count|Subscription count|Node name|Reliability|Durability|Translation'

# Дефект должен ломать именно эти тесты; сверка с SDF на main должна пройти, а не пропуститься.
DEFECT_TESTS = {
    'test_expected_parent_and_joint_type[lidar_link]',
    'test_sensor_position_in_base_link[lidar_link]',
    'test_dimensions_match_kit_sdf',
}


def read(path):
    if not path.is_file():
        sys.exit(f'нет {path}: сначала tests.sh и experiment.sh в обоих режимах')
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


def block(mode, name, only=None, keep=None, last=None):
    """Блок text: команды с выводом; keep — строки вывода по шаблону, last — последние N из них."""
    path = LOGS / mode / name
    parts = []
    for command, output, rc, stamp in ENTRY.findall(read(path)):
        if only is not None and not any(word in command for word in only):
            continue
        lines = [line for line in output.rstrip('\n').split('\n')
                 if output.strip() and not NOISE.match(line.strip())]
        if keep is not None:
            kept = [line for line in lines if re.search(keep, line)]
            kept = kept[-last:] if last else kept
            if len(kept) < len(lines):
                lines = kept + [f'... (полностью: {path})']
        status = f'[exit={rc}, {stamp}]' if stamp else f'[exit={rc}]'
        parts.append('\n'.join([f'$ {command}'] + lines + [status]))
    return '```text\n' + '\n\n'.join(parts) + '\n```'


def gv_edges(mode):
    text = read(LOGS / mode / 'frames.gv')
    return '\n'.join(f'{a} -> {b}' for a, b in re.findall(r'^"([^"]+)" -> "([^"]+)"', text, re.M))


def fmt(values):
    return ', '.join(f'{0.0 if abs(v) < 1e-12 else v:.3f}'.rstrip('0').rstrip('.') for v in values)


def rpy_of(matrix):
    pitch = math.asin(-max(-1.0, min(1.0, matrix[2][0])))
    roll = math.atan2(matrix[2][1], matrix[2][2])
    yaw = math.atan2(matrix[1][0], matrix[0][0])
    return roll, pitch, yaw


def frames_table(model):
    owners = {
        'fixed': 'robot_state_publisher → `/tf_static` (из `robot_description`, один раз, transient local)',
        'revolute': 'robot_state_publisher → `/tf` по `/joint_states` (в опыте их публикует `zero_joint_states`)',
        'continuous': 'robot_state_publisher → `/tf` по `/joint_states` (в опыте их публикует `zero_joint_states`)',
    }
    rows = ['| Родитель | Потомок | Сочленение | Тип | origin xyz, м | origin rpy, рад '
            '| Потомок в base_link, м | Владелец публикации |', '|---' * 8 + '|']
    for joint in sorted(model.joints.values(), key=lambda j: (j.parent != 'base_footprint', j.name)):
        try:
            in_base = fmt(transform(model, 'base_link', joint.child)[0])
        except ValueError:
            in_base = '—'
        rows.append(
            f'| `{joint.parent}` | `{joint.child}` | `{joint.name}` | {joint.kind} | {fmt(joint.xyz)} '
            f'| {fmt(joint.rpy)} | {in_base} | {owners[joint.kind]} |')
    return '\n'.join(rows)


def same_tests_table():
    defect = read(LOGS / 'model-check-defect.txt').replace(str(Path.cwd()) + '/', '')
    failed = [name for name, status in TEST_LINE.findall(defect) if status in ('FAILED', 'ERROR')]
    section = re.search(r'^=+ FAILURES =+\n(.*?)^=+ ', defect, re.S | re.M)
    errors = section.group(1).strip().split('\n') if section else []
    if len(errors) != len(failed):
        errors = ['(см. logs/model-check-defect.txt)'] * len(failed)
    fixed = dict(TEST_LINE.findall(read(EVIDENCE / 'model-check.txt')))
    rows = ['| Тест | Ошибка на ветке дефекта | main |', '|---|---|---|']
    for name, error in zip(failed, errors):
        rows.append(f'| `{name.split("::", 1)[1]}` | `{error.strip()}` | {fixed.get(name, "?")} |')
    return '\n'.join(rows), failed, fixed


def main():
    for mode in ('fixed', 'defect'):
        if 'ОШИБКА' in read(LOGS / mode / 'summary.txt'):
            sys.exit(f'в logs/{mode}/summary.txt есть ОШИБКА: повторите experiment.sh {mode}')
    table, failed, fixed_status = same_tests_table()
    failed_names = {name.split('::', 1)[1] for name in failed}
    if failed_names != DEFECT_TESTS:
        sys.exit(f'на ветке дефекта упали {sorted(failed_names)}, ожидались {sorted(DEFECT_TESTS)}')
    by_name = {name.split('::', 1)[1]: status for name, status in fixed_status.items()}
    skipped = sorted(n for n, s in by_name.items() if s == 'SKIPPED' and n != 'test_copyright')
    if any(s not in ('PASSED', 'SKIPPED') for s in by_name.values()) or skipped:
        sys.exit(f'на main не все тесты прошли (пропущены: {skipped}); нужен .course-kit и tests.sh fixed')
    if not (EVIDENCE / 'rviz.png').is_file():
        sys.exit('нет evidence/pr06/rviz.png: сохраните снимок окна RViz (шаг 5 инструкции)')
    model = parse(xacro.process_file(str(XACRO_FILE)).toprettyxml(indent='  '))
    _, optical = transform(model, 'camera_link', 'camera_link_optical')
    fixed, defect = env('fixed'), env('defect')
    check_urdf_defect = block('defect', '../model-check-defect.txt', only=['check_urdf'])

    text = f'''# ПР06 — системы координат модели `course_ackermann`

Документ собран скриптом `evidence/pr06/scripts/render.py`: таблица связей — из развёрнутого
`src/course_description/urdf/vehicle.urdf.xacro`, блоки `text` — реальный вывод команд из
`evidence/pr06/logs/` (опыт — `scripts/experiment.sh`, проверки модели — `scripts/tests.sh`).

- Среда: {fixed.get('os', '?')} (ядро `{fixed.get('kernel', '?')}`), `{fixed.get('ros', '?')}`.
- Исправная модель: ветка `{fixed.get('branch')}`, коммит `{fixed.get('HEAD')}`, прогон {fixed.get('date')}.
- Дефект: ветка `{defect.get('branch')}`, коммит `{defect.get('HEAD')}`, прогон {defect.get('date')}.
- Размеры — из `.course-kit/v1/models/course_ackermann/model.sdf`: база 0.8 м, колея 0.62 м,
  радиус колеса 0.12 м (Xacro-свойства `wheelbase`, `track`, `wheel_radius`); единицы СИ, оси REP-103.

## Связи дерева и их владельцы

Корень — `base_footprint` (REP-105: проекция `base_link` на землю, без инерции: KDL в
robot_state_publisher не принимает инерцию у корня). `map` и `odom` пока никто не публикует.
Каждое ребро публикует ровно один участник — robot_state_publisher; подвижные рёбра он считает по
`/joint_states`, у которых тоже один издатель.

{frames_table(model)}

Камера, лидар и IMU в SDF закреплены в одной точке, поэтому их `origin` совпадают.
`camera_link_optical` (REP-103: z вперёд, x вправо, y вниз) повёрнут относительно `camera_link`
на rpy = ({fmt(rpy_of(optical))}) рад.

## Модель в RViz

`ros2 launch course_description display.launch.py rviz:=true zero_joint_states:=true`,
Fixed Frame `base_link`, Global Status: Ok; колёса видны благодаря `/joint_states`.

![Модель в RViz](rviz.png)

## Одна связь: `tf2_echo base_link lidar_link`

Исправная модель:

{block('fixed', '2-tf2-echo.txt', only=['lidar_link'], keep=ECHO_KEEP, last=3)}

С дефектом (родитель лидара — `camera_link`, origin прежний):

{block('defect', '2-tf2-echo.txt', only=['lidar_link'], keep=ECHO_KEEP, last=3)}

## Всё дерево: `view_frames`

Рёбра графа из `frames.gv` (PDF — `logs/fixed/frames.pdf` и `logs/defect/frames.pdf`).
`view_frames` слушает tf 5 с; колёса без `/joint_states` в него не попадают.

```text
# исправная модель
{gv_edges('fixed')}

# дефект
{gv_edges('defect')}
```

## `/tf_static` целиком: `ros2 topic echo /tf_static --once`

{block('fixed', '4-tf-static.txt', keep=STATIC_KEEP)}

С дефектом у `lidar_link` другой родитель при том же смещении:

{block('defect', '4-tf-static.txt', keep='frame_id')}

## Один владелец у каждого ребра

{block('fixed', '1-graph.txt', keep=OWNER_KEEP)}

С `/joint_states` (нода `zero_joint_states`) колёса и кулаки появляются в `/tf`; у `/tf` и
`/joint_states` по одному издателю:

{block('fixed', '5-moving.txt', keep=MOVING_KEEP)}

## Сломать: `lidar_link` прикреплён к `camera_link` (ветка `{defect.get('branch')}`)

Один коммит (`evidence/pr06/defect.patch`): у вызова макроса лидара `parent="camera_link"`,
`origin` не менялся.

{block('defect', 'env.txt')}

`check_urdf` такое дерево принимает: структура допустима, смысл — нет.

{check_urdf_defect}

## Доказать: тот же тест до и после

Тесты проверяют ожидаемого родителя и положение каждого сенсора в `base_link` (композиция origin
вдоль цепочки), а не только структуру. На ветке дефекта упавших тестов: {len(failed)}, на `main`
проходят все; полный вывод — `evidence/pr06/model-check.txt` и `logs/model-check-defect.txt`.

{table}

Причина: у сочленения `base_to_lidar` родитель `camera_link`, а origin (0.28, 0, 0.38) задан
относительно родителя, поэтому смещение камеры и лидара складываются: лидар оказывается в
(0.56, 0, 0.76) от `base_link`. Исправление — вернуть `parent` по умолчанию (`base_link`).
'''
    (EVIDENCE / 'frames.md').write_text(text, encoding='utf-8')
    print(f'{EVIDENCE}/frames.md: собран')


if __name__ == '__main__':
    main()
