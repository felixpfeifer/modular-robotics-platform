#include <chrono>
#include <memory>

#include "platform_control_interfaces/msg/teleop_state.hpp"
#include "rclcpp/rclcpp.hpp"

using namespace std::chrono_literals;

class FixturePublisher final : public rclcpp::Node {
 public:
  FixturePublisher() : Node("teleop_cpp_fixture_publisher") {
    publisher_ = create_publisher<platform_control_interfaces::msg::TeleopState>(
        "/platform_interface_tests/teleop_cpp_to_python", 10);
    timer_ = create_wall_timer(50ms, [this]() {
      publisher_->publish(fixture());
      if (++count_ >= 60) {
        rclcpp::shutdown();
      }
    });
  }

 private:
  static platform_control_interfaces::msg::TeleopState fixture() {
    platform_control_interfaces::msg::TeleopState message;
    message.header.stamp.sec = 123;
    message.header.stamp.nanosec = 456;
    message.header.frame_id = "world";
    for (std::size_t index = 0; index < message.sample_id.uuid.size(); ++index) {
      message.sample_id.uuid[index] = static_cast<uint8_t>(index + 1);
    }
    message.source_id = "cpp_source";
    message.pose.position.x = 1.25;
    message.pose.position.y = -2.5;
    message.pose.position.z = 0.75;
    message.pose.orientation.x = 0.1;
    message.pose.orientation.y = 0.2;
    message.pose.orientation.z = 0.3;
    message.pose.orientation.w = 0.9;
    message.velocity.linear.x = 0.4;
    message.velocity.linear.y = -0.5;
    message.velocity.linear.z = 0.6;
    message.velocity.angular.x = -0.1;
    message.velocity.angular.y = 0.2;
    message.velocity.angular.z = -0.3;
    message.gripper_position = 0.625F;
    message.buttons = 0xA5U;
    message.clutch_engaged = true;
    message.tracking_valid = true;
    message.pose_valid = true;
    message.velocity_valid = true;
    return message;
  }

  rclcpp::Publisher<platform_control_interfaces::msg::TeleopState>::SharedPtr publisher_;
  rclcpp::TimerBase::SharedPtr timer_;
  int count_{0};
};

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<FixturePublisher>());
  return 0;
}
