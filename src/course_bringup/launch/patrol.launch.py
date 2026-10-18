"""
Система ПР05 одной командой: turtlesim глобально, patrol, pose_relay и pose_listener в namespace.

ros2 launch course_bringup patrol.launch.py namespace:=robot_a
    subscriber_reliability:=best_effort record:=true bag_dir:=evidence/pr05/bag
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, GroupAction, LogInfo
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node, PushRosNamespace


def generate_launch_description():
    namespace = LaunchConfiguration('namespace')
    record = LaunchConfiguration('record')
    bag_dir = LaunchConfiguration('bag_dir')
    reliability = LaunchConfiguration('subscriber_reliability')
    # Полное имя сенсорного потока: внутри нод оно относительное (sensor_pose).
    # Ведущий / в аргументе срезается: robot_a и /robot_a дают одно и то же имя.
    sensor_topic = ['/', PythonExpression(["'", namespace, "'.strip('/')"]), '/sensor_pose']

    return LaunchDescription([
        DeclareLaunchArgument(
            'namespace', default_value='robot_a',
            description='namespace of patrol, pose_relay and pose_listener'),
        DeclareLaunchArgument(
            'record', default_value='false', choices=['true', 'false'],
            description='record /<namespace>/sensor_pose to MCAP with ros2 bag record'),
        DeclareLaunchArgument(
            'bag_dir', default_value='evidence/pr05/bag',
            description='output directory of ros2 bag record; it must not exist yet'),
        DeclareLaunchArgument(
            'subscriber_reliability', default_value='best_effort',
            choices=['reliable', 'best_effort'],
            description='QoS reliability of the pose_listener subscription'),
        LogInfo(msg=[
            'PR05 bringup: namespace=', namespace, ' subscriber_reliability=', reliability,
            ' record=', record, ' bag_dir=', bag_dir]),

        # Один turtlesim на всю систему — вне namespace.
        Node(package='turtlesim', executable='turtlesim_node', name='turtlesim', output='screen'),

        GroupAction([
            PushRosNamespace(namespace),
            Node(
                package='patrol', executable='patrol', name='patrol', output='screen',
                remappings=[('cmd_vel', '/turtle1/cmd_vel')]),
            Node(
                package='course_bringup', executable='pose_relay', name='pose_relay',
                output='screen', remappings=[('pose', '/turtle1/pose')]),
            Node(
                package='course_bringup', executable='pose_listener', name='pose_listener',
                output='screen', parameters=[{'reliability': reliability}]),
        ]),

        ExecuteProcess(
            cmd=['ros2', 'bag', 'record', '-s', 'mcap', '-o', bag_dir, '--topics', sensor_topic],
            name='recorder', output='screen', condition=IfCondition(record)),
    ])
