#include <chrono>
#include <cmath>
#include <memory>

#include "platform_control_interfaces/msg/teleop_state.hpp"
#include "rclcpp/rclcpp.hpp"

using namespace std::chrono_literals;

class FixtureSubscriber final : public rclcpp::Node {
 public:
  FixtureSubscriber() : Node("teleop_cpp_fixture_subscriber") {
    subscription_ = create_subscription<platform_control_interfaces::msg::TeleopState>(
        "/platform_interface_tests/teleop_python_to_cpp", 10,
        [this](platform_control_interfaces::msg::TeleopState::ConstSharedPtr message) {
          result_ = matches(*message) ? 0 : 2;
          rclcpp::shutdown();
        });
    timeout_ = create_wall_timer(5s, [this]() {
      result_ = 3;
      rclcpp::shutdown();
    });
  }

  int result() const { return result_; }

 private:
  static bool close(double left, double right) {
    return std::abs(left - right) < 1e-6;
  }

  static bool matches(const platform_control_interfaces::msg::TeleopState &message) {
    return message.header.stamp.sec == 321 &&
           message.header.stamp.nanosec == 654 &&
           message.header.frame_id == "base" &&
           message.sample_id.uuid[0] == 16 &&
           message.sample_id.uuid[15] == 1 &&
           message.source_id == "python_source" &&
           close(message.pose.position.x, -1.5) &&
           close(message.pose.orientation.w, 1.0) &&
           close(message.velocity.linear.y, 0.75) &&
           close(message.velocity.angular.z, -0.25) &&
           close(message.gripper_position, 0.375) &&
           message.buttons == 0x5AU &&
           !message.clutch_engaged &&
           message.tracking_valid &&
           message.pose_valid &&
           message.velocity_valid;
  }

  rclcpp::Subscription<platform_control_interfaces::msg::TeleopState>::SharedPtr
      subscription_;
  rclcpp::TimerBase::SharedPtr timeout_;
  int result_{4};
};

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  auto node = std::make_shared<FixtureSubscriber>();
  rclcpp::spin(node);
  return node->result();
}
