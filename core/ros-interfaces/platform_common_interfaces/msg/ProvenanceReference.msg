# Compact immutable provenance. Full manifests remain in an artifact store.
platform_common_interfaces/ComponentIdentity component
platform_common_interfaces/ConfigurationReference configuration
# Empty calibration_id means calibration does not apply to this artifact.
string<=64 calibration_id
# Empty only when calibration_id is empty.
string<=128 calibration_hash
