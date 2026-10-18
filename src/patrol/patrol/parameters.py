"""Чистые функции: допустимые значения параметров patrol и период таймера."""

from dataclasses import dataclass, replace
import math

# Допустимые конечные значения (включительно): linear_speed в м/с, turn_rate в рад/с,
# publish_hz в Гц.
LIMITS = {
    'linear_speed': (0.0, 1.0),
    'turn_rate': (-1.0, 1.0),
    'publish_hz': (1.0, 30.0),
}


@dataclass(frozen=True)
class Settings:
    """Активные настройки ноды; меняются только целиком и только допустимыми значениями."""

    linear_speed: float = 0.5
    turn_rate: float = 0.3
    publish_hz: float = 10.0

    @property
    def period_sec(self):
        return 1.0 / self.publish_hz


def check_value(name, value):
    """Вернуть причину отказа или None, если значение допустимо."""
    low, high = LIMITS[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f'{name} must be a number, got {value!r}'
    if not math.isfinite(value):
        return f'{name} must be a finite number, got {value}'
    if not low <= value <= high:
        return f'{name} must be in [{low}, {high}], got {value}'
    return None


def apply_changes(settings, changes):
    """
    Проверить все изменения сразу и вернуть пару (настройки, причина отказа).

    Если хотя бы одно значение недопустимо, возвращаются прежние настройки целиком.
    Чужие параметры ноды (например, use_sim_time) не проверяются и не меняют настройки.
    """
    known = {name: value for name, value in changes.items() if name in LIMITS}
    for name, value in known.items():
        reason = check_value(name, value)
        if reason is not None:
            return settings, reason
    return replace(settings, **{name: float(value) for name, value in known.items()}), None
