"""Чистые функции: дерево звеньев развёрнутого URDF, преобразования вдоль цепочки, инерция."""

from dataclasses import dataclass
import math
import xml.etree.ElementTree as ElementTree


@dataclass(frozen=True)
class Joint:
    """Сочленение URDF: родитель, потомок и origin потомка относительно родителя."""

    name: str
    kind: str
    parent: str
    child: str
    xyz: tuple
    rpy: tuple


@dataclass(frozen=True)
class Model:
    """Звенья и сочленения модели; joints проиндексированы по имени потомка."""

    links: dict
    joints: dict


def _floats(text, count=3):
    values = tuple(float(v) for v in (text or '').split()) or (0.0,) * count
    if len(values) != count:
        raise ValueError(f'expected {count} numbers, got {text!r}')
    return values


def parse(urdf_text):
    """Разобрать развёрнутый URDF в Model; повторный потомок — ошибка дерева."""
    robot = ElementTree.fromstring(urdf_text)
    links = {link.get('name'): link for link in robot.findall('link')}
    joints = {}
    for element in robot.findall('joint'):
        origin = element.find('origin')
        joint = Joint(
            name=element.get('name'), kind=element.get('type'),
            parent=element.find('parent').get('link'), child=element.find('child').get('link'),
            xyz=_floats(origin.get('xyz') if origin is not None else None),
            rpy=_floats(origin.get('rpy') if origin is not None else None))
        if joint.child in joints:
            raise ValueError(f'link {joint.child} has two parents')
        joints[joint.child] = joint
    return Model(links=links, joints=joints)


def tree_problems(model):
    """Вернуть список нарушений: не один корень, неизвестные звенья, циклы."""
    problems = []
    for joint in model.joints.values():
        for link in (joint.parent, joint.child):
            if link not in model.links:
                problems.append(f'joint {joint.name} refers to unknown link {link}')
    roots = sorted(set(model.links) - set(model.joints))
    if len(roots) != 1:
        problems.append(f'expected one root link, got {roots}')
    for link in model.links:
        seen = set()
        while link in model.joints:
            if link in seen:
                problems.append(f'cycle through {link}')
                break
            seen.add(link)
            link = model.joints[link].parent
    return problems


def root(model):
    (name,) = set(model.links) - set(model.joints)
    return name


def rotation(rpy):
    """Матрица поворота URDF: rpy вокруг неподвижных осей x, y, z (R = Rz · Ry · Rx)."""
    roll, pitch, yaw = rpy
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    return (
        (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr),
        (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr),
        (-sp, cp * sr, cp * cr),
    )


def _matmul(a, b):
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _apply(matrix, vector):
    return tuple(sum(matrix[i][k] * vector[k] for k in range(3)) for i in range(3))


def chain(model, ancestor, frame):
    """Сочленения от ancestor до frame (сверху вниз); ValueError, если frame не потомок."""
    joints = []
    while frame != ancestor:
        if frame not in model.joints:
            raise ValueError(f'{frame} is not below {ancestor}')
        joints.append(model.joints[frame])
        frame = model.joints[frame].parent
    return list(reversed(joints))


def transform(model, ancestor, frame):
    """Положение и поворот frame в осях ancestor: композиция origin вдоль цепочки."""
    position = (0.0, 0.0, 0.0)
    orientation = rotation((0.0, 0.0, 0.0))
    for joint in chain(model, ancestor, frame):
        offset = _apply(orientation, joint.xyz)
        position = tuple(p + o for p, o in zip(position, offset))
        orientation = _matmul(orientation, rotation(joint.rpy))
    return position, orientation


def inertia_problems(link):
    """Нарушения inertial звена: масса > 0, моменты > 0, неравенства треугольника."""
    inertial = link.find('inertial')
    if inertial is None:
        return [f'{link.get("name")}: no inertial']
    mass = float(inertial.find('mass').get('value'))
    tensor = inertial.find('inertia')
    ixx, iyy, izz = (float(tensor.get(k)) for k in ('ixx', 'iyy', 'izz'))
    off_diagonal = [float(tensor.get(k, 0)) for k in ('ixy', 'ixz', 'iyz')]
    problems = []
    name = link.get('name')
    if not mass > 0:
        problems.append(f'{name}: mass {mass} must be positive')
    if not min(ixx, iyy, izz) > 0:
        problems.append(f'{name}: principal moments must be positive')
    if any(off_diagonal):
        problems.append(f'{name}: tensor must be given in principal axes')
    if ixx + iyy < izz or ixx + izz < iyy or iyy + izz < ixx:
        problems.append(f'{name}: moments violate the triangle inequality')
    return problems
