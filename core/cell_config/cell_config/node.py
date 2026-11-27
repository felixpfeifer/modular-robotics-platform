"""ROS 2 lifecycle for the cell configuration HTTP service."""

import threading

import rclpy
from rclpy.node import Node
from .server import serve


class CellConfigNode(Node):
    def __init__(self):
        super().__init__("cell_config")
        self.declare_parameter("host", "127.0.0.1")
        self.declare_parameter("port", 8080)
        self.declare_parameter("config_path", "/data/cell.json")
        self.declare_parameter("compose_project", "mrp-cell")
        host = self.get_parameter("host").value
        port = self.get_parameter("port").value
        path = self.get_parameter("config_path").value
        self.server = serve(
            host, port, path, self.get_parameter("compose_project").value
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.get_logger().info(
            f"Cell configuration API listening on {host}:{port}; file: {path}"
        )

    def destroy_node(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = CellConfigNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
