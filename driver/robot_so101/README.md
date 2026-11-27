# robot_so101

ROS 2 (Jazzy) driver bring-up for the **[SO-ARM101](https://github.com/TheRobotStudio/SO-ARM100)**
robotic arm. It launches the `ros2_control` controller stack on top of the
[`feetech_ros2_driver`](https://github.com/JafarAbdi/feetech_ros2_driver)
hardware interface, so the arm can be driven over its Feetech serial servo bus.

## Layout

This package is a ROS 2 workspace whose sources are pulled in as git submodules:

- **`src/feetech_ros2_driver`** — `ros2_control` hardware interface for the Feetech servos.
- **`src/ros2_so_arm`** — SO-ARM100/101 URDF description, controllers and MoveIt config.

Clone with submodules (or initialise them after the fact):

```bash
git clone --recurse-submodules <repo-url>
# or, in an existing checkout:
git submodule update --init --recursive
```

## Robot profile

`profile.json` describes this robot to the MRP application: joint names, the follower and leader
joint-state topics, and the recorder's robot config for the mock and real backends. The
application builds the control arbiter and recorder configuration from it plus the cell settings
in the UI. A new robot driver ships its own `profile.json` with a new `id`, and a cell preset names
that id. Nothing else in the core changes.

## What gets launched

`ros2 launch so_arm101_description controllers_bringup.launch.py` starts:

- the `controller_manager` (`ros2_control_node`) bound to the chosen hardware,
- `robot_state_publisher` with the SO-ARM101 URDF, and
- the controllers: `joint_state_broadcaster`, `joint_trajectory_controller`,
  `gripper_controller`.

### Launch arguments

- **`hardware_type`** *(default `mock_components`)* — `mock_components` (no
  hardware, simulated interface), `real` (USB serial), `gazebo`, or `mujoco`.
- **`usb_port`** *(default `/dev/LeRobotFollower`)* — serial device for the
  Feetech bus; only used when `hardware_type:=real`.

> The arm is **not connected** in the current setup, so everything below
> defaults to `hardware_type:=mock_components`. The controllers still come up
> and publish `/joint_states`, so you can validate the stack without hardware.

## Usage

### Containers (recommended)

Each arm runs in its own container from one image, started with `./so101`.
Run every command below from this folder (`driver/robot_so101`).

#### 1. First-time setup (once)

```bash
cp .env.example .env                       # optional defaults (backend, ports, RMW)
sudo apt install ros-jazzy-rmw-zenoh-cpp   # lets WSL talk to the containers
./so101 viz-setup                          # builds the robot meshes into ~/so101_viz
```

#### 2. Start the arms

```bash
./so101 up follower --backend gazebo       # simulated follower
./so101 up leader --backend gazebo         # simulated leader
./so101 up follower --backend real --port /dev/ttyACM0 --calibration follower.yaml
./so101 up leader --backend real --port /dev/ttyACM1 --calibration leader.yaml
./so101 ps                                 # what is running
./so101 logs so101_follower                # follow a container's log
./so101 down                               # stop everything
```

`--backend` is `mock` (no hardware), `gazebo` or `real`. The first `up` also
starts the Zenoh router (`--rmw zenoh` is the default; `cyclonedds` and
`fastdds` also exist, but only Zenoh reaches WSL from Docker Desktop). Mix
leader and follower backends freely, e.g. a real leader driving a simulated
follower.

| | Namespace | Controllers |
|---|---|---|
| Follower | none | state broadcaster, `joint_trajectory_controller`, `gripper_controller` |
| Real leader | `/leader` | state broadcaster only, torque off |
| Mock/Gazebo leader | `/leader` | state broadcaster, `forward_position_controller` (six joints) |

#### 3. Open RViz2 (smooth, GPU-accelerated)

RViz2 inside a container is software-rendered and laggy. Run it on your own
machine instead; it joins the same Zenoh router:

```bash
./so101 viz follower --sim                 # --sim for Gazebo arms, leave it off for mock/real
./so101 viz leader --sim
```

This sources the meshes, sets the Zenoh variables and picks the right topics,
frame and clock for that arm. To use RViz2 in a container instead (slower), add
`--rviz` to `./so101 up`.

#### 4. Use ROS commands from your WSL terminal

Every new terminal needs these four lines before `ros2` can see the arms:

```bash
source /opt/ros/jazzy/setup.bash
source ~/so101_viz/install/setup.bash
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
export ZENOH_CONFIG_OVERRIDE='mode="client";connect/endpoints=["tcp/127.0.0.1:7447"]'
```

Then, for example:

```bash
ros2 node list --no-daemon                       # first call may need a few seconds
ros2 topic list --no-daemon
ros2 topic echo /joint_states                    # follower
ros2 topic echo /leader/joint_states             # leader
ros2 topic hz /joint_states
ros2 control list_controllers                    # needs: sudo apt install ros-jazzy-ros2controlcli
ros2 topic pub --once /leader/forward_position_controller/commands \
  std_msgs/msg/Float64MultiArray "{data: [0.5, 0.2, 0.1, 0.0, 0.0, 0.3]}"   # pose a sim leader
```

To paste these four lines once per terminal automatically, put them in a file
such as `~/so101_env.sh` and run `source ~/so101_env.sh`.

You can also run commands inside a container, which needs none of the above:

```bash
./so101 shell follower      # or: leader
```

#### Starting RViz2 by hand

Only needed if you do not use `./so101 viz`. Run the four lines from step 4
first, otherwise you get `Could not load resource [package://so_arm101_description/...]`,
then:

```bash
rviz2                                   # mock or real arm
rviz2 --ros-args -p use_sim_time:=true   # Gazebo follower
```

and add a **RobotModel** display:

| Setting | Follower | Leader |
|---|---|---|
| Fixed Frame | `base_link` | `leader/base_link` |
| Description Topic | `/robot_description` | `/leader/robot_description` |
| Description Topic → Durability | Transient Local | Transient Local |
| TF Prefix | empty | `leader` |

For a Gazebo leader, start RViz2 with `-r /clock:=/leader/clock`.

#### Why the terminal needs `mode="client"`

The router publishes port 7447, which is how WSL reaches Docker Desktop. The
containers join it as Zenoh peers, but a program outside Docker must join as a
**client**: as a peer it learns the arms' addresses and cannot connect to them,
so `ros2 node list` shows nothing from the arms.

#### Troubleshooting

| Symptom | Fix |
|---|---|
| `Could not load resource [package://so_arm101_description/...]` | Run `source ~/so101_viz/install/setup.bash` first, or use `./so101 viz`. After first checkout run `./so101 viz-setup`. |
| `ros2 node list` shows only `/rviz` or nothing | Check `ZENOH_CONFIG_OVERRIDE` is exported in this terminal and contains `mode="client"`. Check the arms with `./so101 ps`. |
| `Unable to connect to a Zenoh router` | The router is not running. Start an arm with `./so101 up ...`. |
| Zenoh `Unable to connect to any locator of scouted peer` | Harmless gossip noise; ignore it. |
| Robot is white or missing in RViz2 | Set Description Topic Durability to **Transient Local** and check the Fixed Frame from the table above. |
| `Serial port ... does not exist` for a real arm | Containers may not see USB serial devices on Docker Desktop (untested); see the notes below. |

> **Docker Desktop:** host networking and `/dev` belong to Docker's VM, not to
> WSL. DDS (`--rmw cyclonedds` or `fastdds`) will not reach WSL, and USB serial
> devices are unlikely to be visible to containers.

> **WSL2 note:** USB serial devices are not visible to the WSL2 kernel by
> default. Forward the adapter with `usbipd attach --wsl --busid <id>` from
> Windows first, then confirm it shows up as `/dev/ttyACM0`/`/dev/ttyUSB0`
> inside WSL before starting the container.

### Bare metal

```bash
# Install dependencies (run once, from the package root)
rosdep install --from-paths src --ignore-src -r -y

# Build and source
colcon build --symlink-install --packages-up-to so_arm101_description
source install/setup.bash

# Bring up the controllers (mock hardware)
ros2 launch so_arm101_description controllers_bringup.launch.py \
  hardware_type:=mock_components

# Or against the real arm
ros2 launch so_arm101_description controllers_bringup.launch.py \
  hardware_type:=real usb_port:=/dev/LeRobotFollower
```

The full RViz + MoveIt demo lives in the `ros2_so_arm` submodule and is **not**
built into the Docker image (it needs a display):

```bash
ros2 launch so_arm100_moveit_config demo.launch.py hardware_type:=mock_components
```

## Gazebo Simulation

A separate Docker service runs the SO-ARM101 inside the
[Gazebo](https://gazebosim.org/) physics simulator with an RViz display so you
can visualise and command the arm without any hardware.

### Prerequisites

- A working X11 display (native Linux, or an X server on WSL2/macOS).
- Allow the Docker container to access the display:

  ```bash
  xhost +local:docker
  ```

### Quick start

```bash
# Build and launch the Gazebo simulation (first run pulls ~2 GB of deps)
docker compose --profile gazebo up gazebo --build
```

> **Important:** Do *not* run this service alongside a `so101_follower`
> container — both use host networking and their
> controller managers would collide.

This starts:

| Window       | What you see                                              |
| ------------ | --------------------------------------------------------- |
| **Gazebo**   | 3-D physics world with the SO-ARM101 spawned on a table   |
| **RViz**     | Robot model, TF frames, and joint states                  |

### Launch arguments

Pass arguments through `command:` in [docker-compose.yaml](docker-compose.yaml)
or append them on the command line:

```bash
docker compose --profile gazebo run --rm gazebo \
  arm_id:=so_arm100 gazebo_gui:=true launch_rviz:=false
```

| Argument                    | Default                    | Description                                      |
| --------------------------- | -------------------------- | ------------------------------------------------ |
| `arm_id`                    | `so_arm101`                | Arm model: `so_arm100` or `so_arm101`            |
| `gazebo_gui`                | `true`                     | Show the Gazebo 3-D window                       |
| `launch_rviz`               | `true`                     | Start RViz alongside Gazebo                      |
| `initial_joint_controller`  | `forward_position_controller` | Controller to activate at startup             |
| `activate_joint_controller` | `true`                     | Activate the controller immediately              |
| `x` / `y` / `z`            | `0.0 / -0.488 / 0.845`    | Spawn position in the world (metres)             |
| `roll` / `pitch` / `yaw`   | `0.0 / 0.0 / -3.141`      | Spawn orientation (radians)                      |

### Sending commands to the simulated arm

Once the simulation is running, open a new terminal and send joint commands:

```bash
# List active controllers
ros2 control list_controllers

# Echo live joint states
ros2 topic echo /joint_states

# Send a position command via the forward_position_controller
ros2 topic pub --once /forward_position_controller/commands \
  std_msgs/msg/Float64MultiArray \
  "{data: [0.5, 0.3, -0.8, -0.5, 1.0]}"
```

### Headless mode (no GUI)

Run the physics simulation without the Gazebo window (useful on CI or
headless servers — RViz can still be disabled separately):

```bash
docker compose --profile gazebo run --rm gazebo \
  arm_id:=so_arm101 gazebo_gui:=false launch_rviz:=false
```

### Bare metal (no Docker)

```bash
# Install all dependencies including Gazebo
rosdep install --from-paths src --ignore-src -r -y

# Build the full stack
colcon build --symlink-install --packages-up-to so_arm_gz
source install/setup.bash

# Launch the simulation
ros2 launch so_arm_gz so_arm_gz_bringup.launch.py arm_id:=so_arm101
```

## The `/dev/LeRobotFollower` symlink

`real` mode defaults to the `/dev/LeRobotFollower` udev symlink rather than a
raw `/dev/ttyACM*`/`/dev/ttyUSB*` path (which can change between replugs). If
you don't have the udev rule installed, just pass the raw device with
`usb_port:=/dev/ttyACM0`.

## Verifying the bring-up

```bash
# Inside or against the running container's host network:
ros2 node list            # expect /controller_manager, /robot_state_publisher
ros2 control list_controllers
ros2 topic echo /joint_states
```
