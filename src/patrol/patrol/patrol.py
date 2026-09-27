"""Нода patrol: подписка на позу черепахи и таймер команды скорости."""

from geometry_msgs.msg import Twist
from patrol.command import choose_command
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from turtlesim.msg import Pose

TIMER_PERIOD_SEC = 0.1


class Patrol(Node):
    """Хранит последнюю позу и по таймеру публикует Twist в относительный cmd_vel."""

    def __init__(self, **kwargs):
        super().__init__('patrol', **kwargs)
        self.latest_pose = None
        self.pose_sub = self.create_subscription(
            Pose, '/turtle1/pose', self.on_pose, 10)
        self.cmd_pub = self.create_publisher(Twist, 'cmd_vel', 10)
        self.timer = self.create_timer(TIMER_PERIOD_SEC, self.on_timer)

    def on_pose(self, message):
        self.latest_pose = message

    def on_timer(self):
        self.cmd_pub.publish(choose_command(self.latest_pose))


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
