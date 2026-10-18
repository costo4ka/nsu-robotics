"""
Модель робота в tf2: robot_state_publisher по развёрнутому Xacro и, по желанию, RViz.

ros2 launch course_description display.launch.py rviz:=true
Колёса и кулаки появятся в /tf, только если кто-то публикует /joint_states
(zero_joint_states:=true публикует нулевые положения всех подвижных сочленений).
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import Command, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    share = FindPackageShare('course_description')
    xacro_file = PathJoinSubstitution([share, 'urdf', 'vehicle.urdf.xacro'])
    rviz_config = PathJoinSubstitution([share, 'rviz', 'vehicle.rviz'])
    robot_description = ParameterValue(Command(['xacro ', xacro_file]), value_type=str)

    return LaunchDescription([
        DeclareLaunchArgument(
            'rviz', default_value='false', choices=['true', 'false'],
            description='open RViz with Fixed Frame base_link'),
        DeclareLaunchArgument(
            'zero_joint_states', default_value='false', choices=['true', 'false'],
            description='publish zero /joint_states so that wheels and knuckles appear in /tf'),

        Node(
            package='robot_state_publisher', executable='robot_state_publisher',
            name='robot_state_publisher', output='screen',
            parameters=[{'robot_description': robot_description}]),
        Node(
            package='rviz2', executable='rviz2', name='rviz2', output='screen',
            arguments=['-d', rviz_config], condition=IfCondition(LaunchConfiguration('rviz'))),
        Node(
            package='course_description', executable='zero_joint_states',
            name='zero_joint_states', output='screen',
            condition=IfCondition(LaunchConfiguration('zero_joint_states'))),
    ])
