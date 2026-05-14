# ros2_cloud_stream

Bridges the ZED ROS 2 wrapper's camera image and pose/odom topics into Google
Cloud Pub/Sub, plus a small FastAPI viewer that subscribes to those topics and
streams the latest message to a browser over a WebSocket.

## What it publishes

| ROS 2 topic | Msg type | Pub/Sub topic |
|---|---|---|
| `/zed/zed_node/rgb/color/rect/image/compressed` | `sensor_msgs/CompressedImage` | `zed-camera` |
| `/zed/zed_node/pose` | `geometry_msgs/PoseStamped` | `zed-pose` |
| `/zed/zed_node/odom` | `nav_msgs/Odometry` | `zed-odom` |

Payloads are UTF-8 JSON. Image bytes are base64-encoded under `data_b64`. Each
Pub/Sub message also carries `stamp_ns`, `frame_id` (and `format` for images)
as attributes so subscribers can filter without parsing the body.

## Prerequisites

- Ubuntu 22.04 + ROS 2 Humble (`rclpy` is system-installed)
- The ZED ROS 2 wrapper publishing under `/zed/zed_node/...`
- A GCP project with the Pub/Sub API enabled
- A service-account JSON key with `roles/pubsub.publisher` (bridge) and
  `roles/pubsub.editor` (viewer — it creates and deletes ephemeral
  subscriptions)

## Setup

1. Edit the constants at the top of `zed_pubsub_bridge.py` and `viewer.py`:
   - `GCP_PROJECT_ID` 
   - Pub/Sub topic IDs, if you want different names (must match between the
     two files)

2. Create the Pub/Sub topics:
   ```
   gcloud pubsub topics create zed-camera zed-pose zed-odom
   ```

3. Install Python deps against the system Python (so they sit alongside the
   apt-installed `rclpy`):
   ```
   pip install -r requirements.txt
   ```


## Run the bridge

```
source /opt/ros/humble/setup.bash
source ~/ros2_ws/install/setup.bash
python3 zed_pubsub_bridge.py
```

Confirm the ZED node is publishing on the expected topics first:
```
ros2 topic hz /zed/zed_node/rgb/color/rect/image/compressed
ros2 topic echo /zed/zed_node/pose --once
```

## Run the viewer

In a second terminal (no ROS sourcing needed):
```
python3 viewer.py
```
Then open <http://localhost:8080/>. 

The viewer creates a per-process subscription (`viewer-<topic>-<random>`) for
each topic on startup and deletes them on clean shutdown. If you Ctrl-C
ungracefully, list and clean up leftovers with:
```
gcloud pubsub subscriptions list --filter="name:viewer-"
gcloud pubsub subscriptions delete <name>
```

## Verify without the viewer

```
gcloud pubsub subscriptions create zed-pose-test --topic=zed-pose
gcloud pubsub subscriptions pull zed-pose-test --auto-ack --limit=5
```

## Troubleshooting

- **`ModuleNotFoundError: rclpy`** — you forgot to `source /opt/ros/humble/setup.bash`.
- **`DefaultCredentialsError`** — `GOOGLE_APPLICATION_CREDENTIALS` is unset or
  points at a missing file.
- **Viewer shows pose/odom but no image** — confirm the camera topic name in
  `ROS_CAMERA_TOPIC` matches what your ZED launch actually publishes.
