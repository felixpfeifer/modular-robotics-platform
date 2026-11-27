# References needed to interpret an immutable raw recording.
unique_identifier_msgs/UUID episode_id
string<=64 workcell_id
string<=64 task_id
string<=64 recording_profile_id
platform_common_interfaces/ConfigurationReference configuration
platform_common_interfaces/ProvenanceReference[<=32] producers
# Calibration IDs used during acquisition. Contents remain external.
string<=64[<=32] calibration_ids
