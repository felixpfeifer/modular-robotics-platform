# M0 Repository-Audit

## Befund

Der Ausgangszustand am 27.10.2026 bestand aus einem initialen README, einer
GitLab-SAST-Include-Datei und leeren `include/`, `src/` und `test/`-Ordnern.
Es existierten kein ROS-2-Paket, kein `package.xml`, kein CMake-Projekt,
keine Docker-Datei, keine Launch-Datei, keine Kamera- oder Sink-Implementierung
und keine projektspezifischen Tests.

Die lokale Umgebung ist `x86_64` auf Ubuntu 24.04.5 mit CMake 3.28.3, GCC
13.3.0 und `cppcheck`. `colcon`, `ros2`, `clang-tidy` und `clang-format` sind
nicht installiert. Jetson/L4T, ROS 2 Jazzy, Geräte, Runner-Konfigurationen,
RealSense- und GigE-SDKs konnten deshalb nicht verifiziert werden.

## M0-Entscheidungen

- M1 startet als hardwarefreier C++17-Kern, damit Mock-Tests auf AMD64 und
  später auf ARM64 ohne proprietäre SDKs laufen.
- `Frame` trägt die Kamera-ID, Sequenz, Dimensionen, Encoding und eine explizite
  Timestamp-Domain. Nicht validierte SDK-Zeit wird nicht als ROS-Zeit ausgegeben.
- Jede Kamera erhält einen eigenen `CameraWorker` und ein begrenztes FIFO mit
  Drop-oldest-Verhalten. Capture darf nicht auf einen Subscriber warten.
- Synchronisation erfolgt über Aufnahmezeitstempel und begrenzte Ringbuffer;
  Hardware-Sync/PTP ist eine spätere Fähigkeit und wird nicht versprochen.
- Die Treibergrenze bleibt zunächst als C++-Interface bestehen. USB/V4L2,
  RealSense und GigE werden erst nach Verifikation ihrer SDKs ergänzt.
- ROS-Nachrichten, Publisher, Lifecycle, Diagnostics und Sinks folgen in M2.

## Risiken und offene Prüfungen

| Risiko | Status | Nächste Prüfung |
| --- | --- | --- |
| ROS-2-Jazzy-/ament-Kompatibilität | offen | Jazzy-Container oder Jazzy-Runner bereitstellen |
| Jetson-L4T- und NVIDIA-Runtime-Kompatibilität | offen | ARM64-Runner und Zielgerät prüfen |
| RealSense/GigE SDK und Lizenz/SBOM | offen | konkrete Modelle, Versionen und Lieferanten erfassen |
| Capture-Timestamp-Domain | teilweise adressiert | Gerätedaten gegen Host-/ROS-Uhr messen |
| Privileged Docker/DinD | ungeprüft | Runner-Konfiguration read-only auditieren |
| ROS QoS, rosbag2 und VLA-Message | noch nicht implementiert | M2-Design und Integrationstests |

Hardware- und Containeraussagen gelten bis zu diesen Prüfungen als ausstehend.
Der CRA-Bezug ist ein technischer Prozessrahmen und keine Konformitätszusage.
