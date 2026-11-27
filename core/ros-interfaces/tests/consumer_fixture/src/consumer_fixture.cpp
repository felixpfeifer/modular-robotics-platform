#include "platform_common_interfaces/msg/component_identity.hpp"
#include "platform_control_interfaces/msg/cartesian_intent.hpp"
#include "platform_device_interfaces/msg/device_descriptor.hpp"
#include "platform_episode_interfaces/msg/episode_metadata.hpp"

int main() {
  platform_common_interfaces::msg::ComponentIdentity component;
  platform_device_interfaces::msg::DeviceDescriptor device;
  platform_control_interfaces::msg::CartesianIntent intent;
  platform_episode_interfaces::msg::EpisodeMetadata episode;
  component.component_id = "consumer";
  device.device_id = "fixture_device";
  intent.source_id = component.component_id;
  intent.target_id = device.device_id;
  episode.task_id = "fixture_task";
  return intent.source_id == "consumer" && episode.task_id == "fixture_task" ? 0 : 1;
}
