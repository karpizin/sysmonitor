# SysMonitor (System Monitor)

**SysMonitor** is a high-performance, lightweight, command-line interface (CLI) system monitoring tool written in Python. It provides real-time visualization of system resources and Docker containers using ASCII graphics.

Designed for DevOps engineers and system administrators who need a quick, "glanceable" overview of their server's health directly from the terminal, without setting up heavy monitoring stacks like Prometheus/Grafana.

![SysMonitor](https://via.placeholder.com/800x400?text=Imagine+ASCII+Dashboard+Here)

## 🚀 Key Features

### 🖥 System Metrics
*   **CPU Usage:** Real-time percentage bar + 60-second sparkline trend.
*   **Memory:** Detailed Virtual RAM (Used/Free/Total) + Swap usage.
*   **Disk:** Root partition usage monitoring.
*   **Network:** List of active open ports mapped to specific services or Docker containers.
*   **System Info:** Uptime, OS version, Kernel release, and Architecture.

### 🐳 Docker Integration
*   **Container Dashboard:** Real-time list of active containers.
*   **Performance Stats per Container:** CPU %, RAM usage (MB), and Network I/O (RX/TX).
*   **Health Checks:** Displays health status (`healthy`, `unhealthy`, `starting`).
*   **Port Mapping:** Automatically correlates host ports to container names.
*   **Storage Analysis:** Tracks total disk space used by Docker images, volumes, and containers (cached to prevent lag).
*   **Trends:** Sparkline graph for the number of active containers.

### ⚡ Performance & Architecture
*   **Fully Asynchronous:** Uses a multi-threaded architecture to separate data collection from UI rendering.
    *   *Thread 1:* System stats (CPU/Mem/Disk/Ports) - updates every 1s.
    *   *Thread 2:* Docker container stats - updates every 2s.
    *   *Thread 3:* Heavy operations (Docker Disk Usage) - updates every 60s.
*   **Zero Flicker:** The UI renders instantly from cached state, eliminating the "blinking" effect common in simple CLI tools.
*   **Low Overhead:** Uses lightweight `psutil` and `docker-py` libraries.

---

## 📦 Installation & Usage

### Option 1: Docker Compose (Recommended)

This is the easiest way to run SysMonitor. It handles all necessary permissions automatically.

1.  Clone the repository:
    ```bash
    git clone https://github.com/karpizin/sysmonitor.git
    cd sysmonitor
    ```

2.  Run with Docker Compose:
    ```bash
    docker-compose up -d --build
    ```

3.  Attach to the container to view the dashboard:
    ```bash
    docker attach sysmonitor
    ```
    *(Press `Ctrl+C` to detach if running with `-d`, or stop if running interactively)*.

### Option 2: Docker CLI

If you prefer a single command, ensure you pass the required flags for host monitoring:

```bash
docker build -t sysmonitor .

docker run --rm -it \
  --name sysmonitor \
  --pid=host \
  --network=host \
  -v /var/run/docker.sock:/var/run/docker.sock \
  sysmonitor
```

**Why these flags?**
*   `--pid=host`: Allows the monitor to see host processes and accurate CPU usage.
*   `--network=host`: Allows monitoring of host network interfaces and ports.
*   `-v /var/run/docker.sock...`: Grants access to the Docker daemon to list containers.

### Option 3: Local Python Execution

Requires Python 3.9+ installed on the host.

1.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

2.  Run the script:
    ```bash
    python system_monitor.py
    ```

---

## 🖥 Sample Output

```text
=====================================================================================
System Monitor - 14:35:12
=====================================================================================

SYSTEM INFO:
OS: Linux 5.15.0-91-generic (Ubuntu 22.04)
Architecture: x86_64
Uptime: 12d 4h 32m

CPU Usage:
[██████████░░░░░░░░░░░░░░░░░░░░] 32.5%  Trend: ▅▄▅▆▅▄▃▄▅▆▇▆▅▄▃▂▃▄▅▆▅▄▃▄▅▆

Memory:
Free: 4.2GB / 16.0GB
[██████░░░░░░░░░░░░░░░░░░░░░░░░] 24.1%  Trend: ▂▂▂▂▂▂▃▃▃▃▃▃▄▄▄▄▄▄▅▅▅▅▅▅

Swap:
Used: 0.0GB / 2.0GB
[░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] 0.0%

Disk Usage:
Free: 45.1GB / 100.0GB
[███████████████░░░░░░░░░░░░░░░] 54.9%  Trend: ▂▂▂▂▂▂▂▂▂▂▂▂▂▂▂▂▂▂▂▂▂▂▂▂

-------------------------------------------------------------------------------------
DOCKER SYSTEM:
Storage: 14.5GB
Active Containers: 4
Trend: ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░

NAME                           STATUS     HEALTH     CPU%   MEM        NET I/O            PORTS
-------------------------------------------------------------------------------------
nginx-proxy                    running    healthy    0.2%   14.5MB     50.1MB / 48.2MB    0.0.0.0:80, 0.0.0.0:443
postgres-db                    running    healthy    1.5%   145.0MB    12.5KB / 45.0KB    0.0.0.0:5432
redis-cache                    running    healthy    0.1%   8.4MB      1.2KB / 1.2KB      0.0.0.0:6379
worker-node-1                  running    N/A        4.2%   250.1MB    150.5MB / 10.2MB   

-------------------------------------------------------------------------------------
Open Ports (5):
0.0.0.0:22, 0.0.0.0:80 (nginx-proxy), 0.0.0.0:443 (nginx-proxy), 0.0.0.0:5432 (postgres-db), 0.0.0.0:6379 (redis-cache)
```

---

## 🛠 Troubleshooting

**Q: I don't see my host's CPU/RAM, only the container's.**
A: Ensure you are running with `--pid=host`. Without this flag, `psutil` can only see the resources allocated to the container itself.

**Q: Network I/O shows 0 for containers.**
A: This feature relies on Docker statistics. Ensure the user running the script has access to the Docker socket.

**Q: The Docker Storage size is "Initializing..."**
A: Calculating total Docker disk usage (`docker df`) is a heavy operation. It runs in a background thread and updates once every 60 seconds to avoid freezing the UI. Wait up to a minute for it to appear.

## 📄 License

MIT License. Feel free to use and modify for your own needs.