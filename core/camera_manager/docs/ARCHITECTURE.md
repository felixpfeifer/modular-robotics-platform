# Architektur (M1)

Der M1-Kern besteht aus drei testbaren Bausteinen:

1. `ICameraDriver` kapselt blockierende oder SDK-spezifische Aufnahme.
2. `CameraWorker` isoliert jeden Treiber in einem eigenen Thread und liefert
   Frames über eine begrenzte Queue bzw. einen Callback.
3. `FrameSynchronizer` hält pro benötigter Kamera einen begrenzten Puffer und
   akzeptiert ein Set nur, wenn `max(capture_timestamp) -
   min(capture_timestamp)` innerhalb der konfigurierten Toleranz liegt.

`MockCameraDriver` erzeugt deterministische Frames ohne Kamera-Hardware. Der
aktuelle Kern ist absichtlich ROS-frei; ROS-Publisher, `CameraInfo`, JPEG und
Sinks werden als eigene Schicht in M2 ergänzt.

## Threading- und Ownership-Regeln

- Ein Worker besitzt seinen Treiber und beendet ihn über `request_stop()` vor
  dem Join.
- Nach Übergabe an eine Queue wird ein `Frame` nicht in-place verändert.
- Jede Queue ist begrenzt; bei voller Queue wird der älteste Frame verworfen.
- Ein blockierender Mock- oder SDK-Treiber besitzt keinen gemeinsamen Thread mit
  einer anderen Kamera.
