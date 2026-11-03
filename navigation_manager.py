
import math
import time

import rclpy

from rclpy.node import Node
from rclpy.action import ActionClient

from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from action_msgs.msg import GoalStatus
from std_srvs.srv import Trigger

class NavigationManager(Node):

    def __init__(self):
        super().__init__('xuegecar_navigation_manager')

        # 默认禁止运动：必须手动开启
        self.declare_parameter('enable_motion', False)

        # Nav2 导航 Action 客户端
        self.nav_client = ActionClient(
            self,
            NavigateToPose,
            '/navigate_to_pose'
        )

        # 接收 Qt 或终端发送的地图目标点
        self.goal_sub = self.create_subscription(
            PoseStamped,
            '/xuegecar/goal_pose',
            self.goal_callback,
            10
        )

        # 导航取消服务
        self.cancel_service = self.create_service(
            Trigger,
            '/xuegecar/cancel_navigation',
            self.cancel_callback
        )

        # 导航状态查询服务
        self.status_service = self.create_service(
            Trigger,
            '/xuegecar/navigation_status',
            self.status_callback
        )

        self.goal_handle = None
        self.busy = False
        self.cancel_requested = False

        self.status = 'IDLE'
        self.distance_remaining = None
        self.recoveries = 0
        self.last_feedback_time = 0.0

        self.get_logger().info(
            'Navigation Manager started. '
            'Motion is disabled by default.'
        )

    def goal_callback(self, msg):
        """收到一个导航目标"""

        if not self.get_parameter('enable_motion').value:
            self.get_logger().warning(
                'Goal rejected: enable_motion is false'
            )
            return

        if self.busy:
            self.get_logger().warning(
                'Goal rejected: another task is running'
            )
            return

        if msg.header.frame_id != 'map':
            self.get_logger().error(
                'Goal rejected: frame_id must be map'
            )
            return

        p = msg.pose.position
        q = msg.pose.orientation

        values = [
            p.x, p.y, p.z,
            q.x, q.y, q.z, q.w
        ]

        if not all(math.isfinite(v) for v in values):
            self.get_logger().error(
                'Goal rejected: invalid pose values'
            )
            return

        qnorm = math.sqrt(
            q.x*q.x + q.y*q.y +
            q.z*q.z + q.w*q.w
        )

        if abs(qnorm - 1.0) > 0.05:
            self.get_logger().error(
                'Goal rejected: invalid quaternion'
            )
            return

        if not self.nav_client.wait_for_server(
            timeout_sec=0.2
        ):
            self.status = 'SERVER_UNAVAILABLE'
            self.get_logger().error(
                'NavigateToPose Action is unavailable'
            )
            return

        goal = NavigateToPose.Goal()

        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = (
            self.get_clock().now().to_msg()
        )
        goal.pose.pose = msg.pose

        self.busy = True
        self.cancel_requested = False
        self.goal_handle = None

        self.status = 'SENDING'
        self.distance_remaining = None
        self.recoveries = 0

        self.get_logger().info(
            f'Sending goal: x={p.x:.3f}, y={p.y:.3f}'
        )

        try:
            future = self.nav_client.send_goal_async(
                goal,
                feedback_callback=self.feedback_callback
            )
            future.add_done_callback(
                self.goal_response_callback
            )

        except Exception as exc:
            self.busy = False
            self.status = 'SEND_FAILED'
            self.get_logger().error(str(exc))

    def goal_response_callback(self, future):
        """Nav2 接受或拒绝目标"""

        try:
            handle = future.result()

            if handle is None or not handle.accepted:
                self.busy = False
                self.status = 'REJECTED'
                self.get_logger().warning(
                    'Navigation goal rejected by Nav2'
                )
                return

            self.goal_handle = handle
            self.status = 'ACTIVE'

            self.get_logger().info(
                'Navigation goal accepted'
            )

            result_future = handle.get_result_async()

            result_future.add_done_callback(
                self.result_callback
            )

            # 如果目标等待接受期间收到取消请求
            if self.cancel_requested:
                self.request_cancel()

        except Exception as exc:
            self.busy = False
            self.status = 'SEND_FAILED'
            self.get_logger().error(str(exc))

    def feedback_callback(self, feedback_msg):
        """接收导航进度"""

        feedback = feedback_msg.feedback

        self.distance_remaining = (
            feedback.distance_remaining
        )

        self.recoveries = feedback.number_of_recoveries

        # 每两秒打印一次，避免终端刷屏
        now = time.monotonic()

        if now - self.last_feedback_time >= 2.0:
            self.last_feedback_time = now

            self.get_logger().info(
                'Navigation feedback: '
                f'distance={self.distance_remaining:.2f} m, '
                f'recoveries={self.recoveries}'
            )

    def result_callback(self, future):
        """导航结束"""

        try:
            result_response = future.result()
            result_status = result_response.status

            if result_status == GoalStatus.STATUS_SUCCEEDED:
                self.status = 'SUCCEEDED'
                self.get_logger().info(
                    'Navigation succeeded'
                )

            elif result_status == GoalStatus.STATUS_CANCELED:
                self.status = 'CANCELED'
                self.get_logger().info(
                    'Navigation canceled'
                )

            elif result_status == GoalStatus.STATUS_ABORTED:
                self.status = 'ABORTED'
                self.get_logger().error(
                    'Navigation aborted'
                )

            else:
                self.status = 'FAILED'
                self.get_logger().error(
                    f'Navigation ended: status={result_status}'
                )

        except Exception as exc:
            self.status = 'FAILED'
            self.get_logger().error(str(exc))

        finally:
            self.goal_handle = None
            self.busy = False
            self.cancel_requested = False

    def request_cancel(self):
        """向 Nav2 发送异步取消请求"""

        if self.goal_handle is None:
            return

        self.status = 'CANCEL_REQUESTED'

        future = self.goal_handle.cancel_goal_async()

        future.add_done_callback(
            self.cancel_response_callback
        )

        self.get_logger().warning(
            'Navigation cancel requested'
        )

    def cancel_response_callback(self, future):
        """检查取消请求是否被接受"""

        try:
            response = future.result()

            if len(response.goals_canceling) > 0:
                self.get_logger().info(
                    'Nav2 accepted cancel request'
                )
            else:
                self.get_logger().warning(
                    'Nav2 did not accept cancel request'
                )

        except Exception as exc:
            self.get_logger().error(
                f'Cancel request failed: {exc}'
            )

    def cancel_callback(self, request, response):
        """提供给 Qt 的取消服务"""

        if not self.busy:
            response.success = False
            response.message = 'No active navigation task'
            return response

        if self.cancel_requested:
            response.success = True
            response.message = 'Cancel already requested'
            return response

        self.cancel_requested = True

        if self.goal_handle is not None:
            self.request_cancel()

        response.success = True
        response.message = (
            'Cancel requested; waiting for Nav2 confirmation'
        )

        return response

    def status_callback(self, request, response):
        """提供给 Qt 的状态查询服务"""

        response.success = True

        message = f'status={self.status}'

        if self.distance_remaining is not None:
            message += (
                f', distance={self.distance_remaining:.2f}m'
            )

        message += f', recoveries={self.recoveries}'

        response.message = message

        return response

def main(args=None):
    rclpy.init(args=args)

    node = NavigationManager()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()