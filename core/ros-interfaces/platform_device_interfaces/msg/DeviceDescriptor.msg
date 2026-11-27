# Static description of one registered device instance.
string<=64 device_id
# Vendor-neutral adapter contract name, not a vendor SDK class.
string<=64 adapter_type
string<=64 model
string<=64 role
# Fully qualified ROS namespace. Empty means the root namespace.
string<=128 ros_namespace
# Declarative capability identifiers; no executable configuration.
string<=64[<=32] capabilities
platform_common_interfaces/ComponentIdentity adapter
