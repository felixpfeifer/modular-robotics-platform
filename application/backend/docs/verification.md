# Development baseline verification

Verified locally on 2026-11-10 with Docker Desktop's Linux engine and the
existing ROS 2 Jazzy / Zenoh mock SO-101 images. These results are local evidence;
the GitLab pipeline has not been run by this implementation session.

| Check | Result |
| --- | --- |
| Application and deployment-agent container builds | Passed |
| Pinned recorder converter image build | Passed |
| Python application/HTTP/artifact/deployment tests | 17 passed |
| Ruff lint and format checks | Passed |
| Frontend JavaScript syntax | Passed |
| Chromium desktop/mobile workflow | Passed |
| Actual mock recording → MCAP validation → LeRobot v3 conversion/reopening | Passed |
| Stop cell while retaining application availability and artifacts | Passed |

The browser check exercised project creation, explicit demo-cell and teleop
startup, recording, annotation, terminal outcome, page reload persistence and
390-pixel mobile layout without horizontal page overflow or JavaScript errors.

The actual ROS acceptance check produced one accepted synthetic episode and
one completed local dataset export. It used the existing recorder, validator
and locked LeRobot converter, not the UI demo or unit-test artifact bytes.
Teleoperation was disabled and the mock cell stopped after testing. Application
metadata, the raw recording, validation report and export were retained.

Evidence is generated under ignored `artifacts/`: `junit.xml`,
`record-export.json`, `dashboard-desktop.png` and `dashboard-mobile.png`.
Raw recordings and dataset outputs remain in the named Docker volumes documented
in the application README. Do not commit those data volumes or generated evidence.

The baseline implements the development workflow from the root plan. A public
Docker Hub release, immutable image catalog, installation without source mounts,
ARM64/Jetson qualification and real hardware qualification remain future work.
