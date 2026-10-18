"""Структурные и геометрические проверки развёрнутого vehicle.urdf.xacro."""

import math
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ElementTree

from course_description.urdf_tree import (
    chain, inertia_problems, parse, root, transform, tree_problems)
import pytest
import xacro

PACKAGE = Path(__file__).resolve().parents[1]
XACRO_FILE = PACKAGE / 'urdf' / 'vehicle.urdf.xacro'

WHEELBASE = 0.8
TRACK = 0.62
WHEEL_RADIUS = 0.12
SENSOR_OFFSET = (0.28, 0.0, 0.38)

# Контракт систем координат: звено → ожидаемый родитель и тип сочленения.
EXPECTED_PARENTS = {
    'base_link': ('base_footprint', 'fixed'),
    'camera_link': ('base_link', 'fixed'),
    'lidar_link': ('base_link', 'fixed'),
    'imu_link': ('base_link', 'fixed'),
    'camera_link_optical': ('camera_link', 'fixed'),
    'front_left_knuckle': ('base_link', 'revolute'),
    'front_right_knuckle': ('base_link', 'revolute'),
    'front_left_wheel': ('front_left_knuckle', 'continuous'),
    'front_right_wheel': ('front_right_knuckle', 'continuous'),
    'rear_left_wheel': ('base_link', 'continuous'),
    'rear_right_wheel': ('base_link', 'continuous'),
}


@pytest.fixture(scope='module')
def urdf_text():
    return xacro.process_file(str(XACRO_FILE)).toprettyxml(indent='  ')


@pytest.fixture(scope='module')
def model(urdf_text):
    return parse(urdf_text)


def position(model, frame):
    return transform(model, 'base_link', frame)[0]


def test_tree_is_connected_and_acyclic_with_root_base_footprint(model):
    assert tree_problems(model) == []
    assert root(model) == 'base_footprint'
    assert set(model.links) == {'base_footprint'} | set(EXPECTED_PARENTS)


def test_base_link_stands_on_the_ground_through_base_footprint(model):
    # base_link на высоте осей: колесо радиуса 0.12 касается земли (z = 0 у base_footprint).
    xyz, _ = transform(model, 'base_footprint', 'base_link')
    assert xyz == pytest.approx((0, 0, WHEEL_RADIUS))
    assert model.links['base_footprint'].find('inertial') is None


@pytest.mark.parametrize('frame', sorted(EXPECTED_PARENTS))
def test_expected_parent_and_joint_type(model, frame):
    parent, joint_type = EXPECTED_PARENTS[frame]
    joint = model.joints[frame]
    assert (joint.parent, joint.kind) == (parent, joint_type), joint.name


@pytest.mark.parametrize('frame', ['camera_link', 'lidar_link', 'imu_link'])
def test_sensor_position_in_base_link(model, frame):
    assert position(model, frame) == pytest.approx(SENSOR_OFFSET)
    # Сенсор закреплён одним фиксированным сочленением прямо на корпусе.
    assert [joint.kind for joint in chain(model, 'base_link', frame)] == ['fixed']


def test_camera_optical_axes_follow_rep_103(model):
    _, rotation = transform(model, 'camera_link', 'camera_link_optical')
    columns = [tuple(row[i] for row in rotation) for i in range(3)]
    # Оси оптической системы в осях камеры: x → вправо (−y), y → вниз (−z), z → вперёд (+x).
    assert columns[0] == pytest.approx((0, -1, 0), abs=1e-9)
    assert columns[1] == pytest.approx((0, 0, -1), abs=1e-9)
    assert columns[2] == pytest.approx((1, 0, 0), abs=1e-9)


def test_wheelbase_track_and_radius(model, urdf_text):
    wheels = {name: position(model, f'{name}_wheel')
              for name in ('front_left', 'front_right', 'rear_left', 'rear_right')}
    assert wheels['front_left'][0] - wheels['rear_left'][0] == pytest.approx(WHEELBASE)
    assert wheels['front_right'][0] - wheels['rear_right'][0] == pytest.approx(WHEELBASE)
    assert wheels['front_left'][1] - wheels['front_right'][1] == pytest.approx(TRACK)
    assert wheels['rear_left'][1] - wheels['rear_right'][1] == pytest.approx(TRACK)
    robot = ElementTree.fromstring(urdf_text)
    radii = {float(c.get('radius'))
             for c in robot.findall("link[@name='front_left_wheel']//cylinder")}
    assert radii == {WHEEL_RADIUS}


def test_wheel_joints_spin_about_y_and_steering_is_limited(urdf_text):
    robot = ElementTree.fromstring(urdf_text)
    for joint in robot.findall('joint'):
        axis = joint.find('axis')
        if joint.get('type') == 'continuous':
            assert axis.get('xyz') == '0 1 0', joint.get('name')
        if joint.get('type') == 'revolute':
            limit = joint.find('limit')
            assert axis.get('xyz') == '0 0 1'
            assert float(limit.get('lower')) == pytest.approx(-0.55)
            assert float(limit.get('upper')) == pytest.approx(0.55)


def test_si_units_and_physical_inertia(model):
    problems = [p for link in model.links.values() if link.find('inertial') is not None
                for p in inertia_problems(link)]
    assert problems == []
    masses = {name: float(link.find('inertial/mass').get('value'))
              for name, link in model.links.items() if link.find('inertial') is not None}
    # Килограммы, а не граммы: корпус 12 кг, колесо 0.8 кг, весь робот ~16 кг.
    assert masses['base_link'] == pytest.approx(12.0)
    assert 10.0 < sum(masses.values()) < 25.0
    for name, xyz in ((frame, position(model, frame)) for frame in EXPECTED_PARENTS
                      if frame != 'base_link'):
        assert all(abs(value) < 2.0 for value in xyz), f'{name}: {xyz} is not in metres'


def expected_inertia(mass, geometry):
    """Главные моменты однородного тела в его собственных осях (ось цилиндра — z)."""
    if geometry.tag == 'box':
        x, y, z = (float(v) for v in geometry.get('size').split())
        return (mass * (y * y + z * z) / 12, mass * (x * x + z * z) / 12,
                mass * (x * x + y * y) / 12)
    radius, length = float(geometry.get('radius')), float(geometry.get('length'))
    side = mass * (3 * radius * radius + length * length) / 12
    return (side, side, mass * radius * radius / 2)


@pytest.mark.parametrize('link_name', [
    'base_link', 'camera_link', 'lidar_link', 'imu_link',
    'front_left_wheel', 'front_right_wheel', 'rear_left_wheel', 'rear_right_wheel'])
def test_inertia_matches_own_geometry(model, link_name):
    link = model.links[link_name]
    inertial = link.find('inertial')
    (geometry,) = list(link.find('visual/geometry'))
    # Инерция задана в тех же осях, что и геометрия: origin inertial и visual совпадают.
    if link.find('visual/origin') is not None:
        assert inertial.find('origin').attrib == link.find('visual/origin').attrib
    tensor = inertial.find('inertia')
    actual = tuple(float(tensor.get(k)) for k in ('ixx', 'iyy', 'izz'))
    mass = float(inertial.find('mass').get('value'))
    assert actual == pytest.approx(expected_inertia(mass, geometry), rel=1e-9)


@pytest.mark.parametrize('link_name', [
    'base_link', 'camera_link', 'lidar_link', 'imu_link',
    'front_left_wheel', 'front_right_wheel', 'rear_left_wheel', 'rear_right_wheel'])
def test_visual_and_collision_are_separate(model, link_name):
    link = model.links[link_name]
    assert link.find('visual/geometry') is not None
    assert link.find('collision/geometry') is not None


def test_check_urdf_accepts_expanded_model(urdf_text, tmp_path):
    check_urdf = shutil.which('check_urdf')
    if check_urdf is None:
        pytest.skip('check_urdf is not installed')
    path = tmp_path / 'vehicle.urdf'
    path.write_text(urdf_text, encoding='utf-8')
    result = subprocess.run([check_urdf, str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'root Link: base_footprint' in result.stdout


def find_kit_model():
    for directory in [PACKAGE, *PACKAGE.parents]:
        candidate = directory / '.course-kit' / 'v1' / 'models' / 'course_ackermann' / 'model.sdf'
        if candidate.is_file():
            return candidate
    return None


def test_dimensions_match_kit_sdf(model):
    """Расширение ПР06: общие размеры URDF и SDF из course kit совпадают."""
    sdf_path = find_kit_model()
    if sdf_path is None:
        pytest.skip('course kit model.sdf not found next to the workspace')
    sdf = ElementTree.parse(sdf_path).getroot().find('model')
    poses = {link.get('name'): [float(v) for v in link.findtext('pose', '0 0 0 0 0 0').split()]
             for link in sdf.findall('link')}
    for frame in ('camera_link', 'lidar_link', 'imu_link', 'front_left_wheel',
                  'front_right_wheel', 'rear_left_wheel', 'rear_right_wheel'):
        assert position(model, frame) == pytest.approx(poses[frame][:3]), frame
    plugin = sdf.find('plugin')
    assert float(plugin.findtext('wheel_base')) == pytest.approx(WHEELBASE)
    assert float(plugin.findtext('wheel_separation')) == pytest.approx(TRACK)
    assert float(plugin.findtext('wheel_radius')) == pytest.approx(WHEEL_RADIUS)
    sdf_body = sdf.find("link[@name='base_link']/visual/geometry/box/size").text
    urdf_body = model.links['base_link'].find('visual/geometry/box').get('size')
    assert [float(v) for v in urdf_body.split()] == pytest.approx(
        [float(v) for v in sdf_body.split()])
    assert float(sdf.find("link[@name='base_link']/inertial/mass").text) == pytest.approx(12.0)
    steering = sdf.find("joint[@name='front_left_steering_joint']/axis/limit")
    assert float(steering.findtext('upper')) == pytest.approx(0.55)
    assert math.isclose(float(model.links['front_left_wheel'].find('inertial/mass').get('value')),
                        float(sdf.find("link[@name='front_left_wheel']/inertial/mass").text))
