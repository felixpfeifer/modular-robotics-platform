"""Synthetic camera: publishes a moving test pattern as sensor_msgs/CompressedImage."""

import os

import cv2
import numpy as np
import rclpy
from sensor_msgs.msg import CompressedImage

WIDTH = int(os.environ.get("CAMERA_WIDTH", "320"))
HEIGHT = int(os.environ.get("CAMERA_HEIGHT", "240"))
FPS = float(os.environ.get("CAMERA_FPS", "15"))
TOPIC = os.environ["CAMERA_TOPIC"]
LABEL = os.environ.get("CAMERA_LABEL", "Simulated camera")

rclpy.init()
node = rclpy.create_node(os.environ.get("CAMERA_NODE", "mock_camera"))
publisher = node.create_publisher(CompressedImage, TOPIC, 10)
frame = 0


def publish():
    global frame
    image = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    image[:] = (45, 35, 25)
    cv2.putText(image, LABEL, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    cv2.circle(image, (20 + (frame * 4) % max(1, WIDTH - 40), HEIGHT // 2), HEIGHT // 8, (30, 180, 255), -1)
    ok, encoded = cv2.imencode(".jpg", image)
    if ok:
        msg = CompressedImage()
        msg.header.stamp = node.get_clock().now().to_msg()
        msg.header.frame_id = node.get_name()
        msg.format = "jpeg"
        msg.data = encoded.tobytes()
        publisher.publish(msg)
    frame += 1


node.create_timer(1.0 / FPS, publish)
try:
    rclpy.spin(node)
finally:
    node.destroy_node()
    rclpy.shutdown()
