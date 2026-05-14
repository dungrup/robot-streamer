#!/usr/bin/env python3
"""Bridge ZED ROS2 wrapper stereo images + pose/odom to Google Cloud Pub/Sub."""

import base64
import json
import sys

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data

from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import CompressedImage

from google.cloud import pubsub_v1


GCP_PROJECT_ID = "yoon-lab"  # TODO: set to your GCP project ID

TOPIC_CAMERA = "zed-camera"   # TODO: confirm Pub/Sub topic name
TOPIC_POSE = "zed-pose"                 # TODO: confirm Pub/Sub topic name
TOPIC_ODOM = "zed-odom"                 # TODO: confirm Pub/Sub topic name

ROS_TOPIC_LEFT = "zed/zed_node/left/image_rect_color/compressed"
ROS_TOPIC_RIGHT = "zed/zed_node/right/image_rect_color/compressed"
ROS_CAMERA_TOPIC = "/zed/zed_node/rgb/color/rect/image/compressed"
ROS_TOPIC_POSE = "/zed/zed_node/pose"
ROS_TOPIC_ODOM = "/zed/zed_node/odom"


def _stamp_ns(header) -> int:
    return int(header.stamp.sec) * 1_000_000_000 + int(header.stamp.nanosec)


def _header_dict(header) -> dict:
    return {"stamp_ns": _stamp_ns(header), "frame_id": header.frame_id}


class ZedPubSubBridge(Node):
    def __init__(self) -> None:
        super().__init__("zed_pubsub_bridge")

        self._publisher = pubsub_v1.PublisherClient()
        self._path_camera = self._publisher.topic_path(GCP_PROJECT_ID, TOPIC_CAMERA)
        self._path_pose = self._publisher.topic_path(GCP_PROJECT_ID, TOPIC_POSE)
        self._path_odom = self._publisher.topic_path(GCP_PROJECT_ID, TOPIC_ODOM)

        self.create_subscription(
            CompressedImage, ROS_CAMERA_TOPIC,
            lambda m: self._on_image(m, self._path_camera),
            qos_profile_sensor_data,
        )
        self.create_subscription(PoseStamped, ROS_TOPIC_POSE, self._on_pose, 10)
        self.create_subscription(Odometry, ROS_TOPIC_ODOM, self._on_odom, 10)

        self.get_logger().info(
            f"Bridging to Pub/Sub project '{GCP_PROJECT_ID}' "
            f"(topics: {TOPIC_CAMERA}, {TOPIC_POSE}, {TOPIC_ODOM})"
        )

    def _publish(self, topic_path: str, payload: bytes, attributes: dict) -> None:
        future = self._publisher.publish(topic_path, data=payload, **attributes)
        future.add_done_callback(self._on_publish_done)

    def _on_publish_done(self, future) -> None:
        exc = future.exception()
        if exc is not None:
            self.get_logger().error(f"Pub/Sub publish failed: {exc}")

    def _on_image(self, msg: CompressedImage, topic_path: str) -> None:
        payload = json.dumps({
            "header": _header_dict(msg.header),
            "format": msg.format,
            "data_b64": base64.b64encode(bytes(msg.data)).decode("ascii"),
        }).encode("utf-8")
        attrs = {
            "stamp_ns": str(_stamp_ns(msg.header)),
            "frame_id": msg.header.frame_id,
            "format": msg.format,
        }
        self._publish(topic_path, payload, attrs)

    def _on_pose(self, msg: PoseStamped) -> None:
        p, o = msg.pose.position, msg.pose.orientation
        payload = json.dumps({
            "header": _header_dict(msg.header),
            "position": {"x": p.x, "y": p.y, "z": p.z},
            "orientation": {"x": o.x, "y": o.y, "z": o.z, "w": o.w},
        }).encode("utf-8")
        attrs = {"stamp_ns": str(_stamp_ns(msg.header)), "frame_id": msg.header.frame_id}
        self._publish(self._path_pose, payload, attrs)

    def _on_odom(self, msg: Odometry) -> None:
        p, o = msg.pose.pose.position, msg.pose.pose.orientation
        lv, av = msg.twist.twist.linear, msg.twist.twist.angular
        payload = json.dumps({
            "header": _header_dict(msg.header),
            "child_frame_id": msg.child_frame_id,
            "pose": {
                "position": {"x": p.x, "y": p.y, "z": p.z},
                "orientation": {"x": o.x, "y": o.y, "z": o.z, "w": o.w},
                "covariance": list(msg.pose.covariance),
            },
            "twist": {
                "linear": {"x": lv.x, "y": lv.y, "z": lv.z},
                "angular": {"x": av.x, "y": av.y, "z": av.z},
                "covariance": list(msg.twist.covariance),
            },
        }).encode("utf-8")
        attrs = {"stamp_ns": str(_stamp_ns(msg.header)), "frame_id": msg.header.frame_id}
        self._publish(self._path_odom, payload, attrs)


def main() -> int:
    rclpy.init()
    node = ZedPubSubBridge()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
