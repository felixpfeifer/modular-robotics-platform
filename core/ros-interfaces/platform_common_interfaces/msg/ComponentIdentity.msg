# Stable identity and immutable build provenance for one running component.
# component_id is deployment-stable and unique within a workcell.
string<=64 component_id
# Human-readable component name; not an identity key.
string<=128 name
# SemVer 2 version of the component. Empty is invalid.
string<=32 semantic_version
# Immutable source revision, normally a full Git commit.
string<=128 source_revision
# Immutable build or artifact identifier.
string<=128 build_id
