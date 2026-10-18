"""Нода patrol: подписка на позу черепахи и таймер команды скорости с параметрами."""

from geometry_msgs.msg import Twist
from patrol.command import choose_command
from patrol.parameters import apply_changes, LIMITS, Settings
from rcl_interfaces.msg import ParameterDescriptor, SetParametersResult
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from turtlesim.msg import Pose

DESCRIPTIONS = {
    'linear_speed': 'linear.x of the patrol command, m/s, finite, 0..1',
    'turn_rate': 'angular.z of the patrol command, rad/s, finite, -1..1',
    'publish_hz': 'command timer rate, Hz, finite, 1..30; the timer is recreated on change',
}


class Patrol(Node):
    """Хранит последнюю позу и по таймеру публикует Twist в относительный cmd_vel."""

    def __init__(self, **kwargs):
        super().__init__('patrol', **kwargs)
        self.latest_pose = None
        self.settings = Settings()
        # Проверка регистрируется до объявления параметров, поэтому недопустимое значение
        # из --ros-args -p тоже отклоняется, и нода не стартует.
        self.add_on_set_parameters_callback(self.check_parameters)
        for name, description in DESCRIPTIONS.items():
            self.declare_parameter(
                name, getattr(self.settings, name),
                ParameterDescriptor(description=description))
        self.settings, _ = apply_changes(
            self.settings, {name: self.get_parameter(name).value for name in LIMITS})
        self.pose_sub = self.create_subscription(
            Pose, '/turtle1/pose', self.on_pose, 10)
        self.cmd_pub = self.create_publisher(Twist, 'cmd_vel', 10)
        self.timer = self.create_timer(self.settings.period_sec, self.on_timer)
        # Применение — только после того, как все новые значения прошли проверку и записаны.
        self.add_post_set_parameters_callback(self.apply_parameters)

    def check_parameters(self, parameters):
        _, reason = apply_changes(self.settings, {p.name: p.value for p in parameters})
        if reason is not None:
            self.get_logger().warning(f'rejected: {reason}')
            return SetParametersResult(successful=False, reason=reason)
        return SetParametersResult(successful=True)

    def apply_parameters(self, parameters):
        settings, _ = apply_changes(self.settings, {p.name: p.value for p in parameters})
        if settings == self.settings:
            return
        if settings.publish_hz != self.settings.publish_hz:
            self.restart_timer(settings.period_sec)
        self.settings = settings
        self.get_logger().info(
            f'linear_speed={settings.linear_speed} turn_rate={settings.turn_rate} '
            f'publish_hz={settings.publish_hz} (timer period {settings.period_sec:.3f} s)')

    def restart_timer(self, period):
        """Создать таймер с новым периодом, затем остановить и удалить прежний."""
        timer = self.create_timer(period, self.on_timer)
        self.timer.cancel()
        self.destroy_timer(self.timer)
        self.timer = timer

    def on_pose(self, message):
        self.latest_pose = message

    def on_timer(self):
        self.cmd_pub.publish(choose_command(
            self.latest_pose, self.settings.linear_speed, self.settings.turn_rate))


def main(args=None):
    rclpy.init(args=args)
    node = Patrol()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
