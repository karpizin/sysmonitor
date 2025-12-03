# System Monitor

A lightweight system monitoring tool that provides real-time metrics for system resources and Docker containers with ASCII-based visualization.

## Features

- Real-time system metrics monitoring:
  - CPU usage with trend graph
  - Memory usage with trend graph
  - Disk space usage with trend graph
  - Docker storage usage
  - Active Docker containers count and names
  - Network ports in use
- ASCII-based visualization with progress bars and sparkline graphs
- Docker support for containerized deployment
- Minute-by-minute trend visualization
- Automatic updates every 2 seconds

## Screenshots

```
System Monitor - 12:34:56
============================================================

CPU Usage:
[██████████░░░░░░░░░░░░░░░░░░░░] 32.5%
Last minute trend:
▅▄▅▆▅▄▃▄▅▆▇▆▅▄▃▂▃▄▅▆▅▄▃▄▅▆
```

## Requirements

- Python 3.9+
- Docker (for containerized deployment)
- Access to Docker socket for container metrics

## Installation

### Local Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/system-monitor.git
cd system-monitor
```

2. Install required packages:
```bash
pip install -r requirements.txt
```

3. Run the monitor:
```bash
python system_monitor.py
```

### Docker Installation

1. Build the Docker image:
```bash
docker build -t system-monitor .
```

2. Run the container:
```bash
docker run --rm -it \
  --pid=host \
  --network=host \
  -v /var/run/docker.sock:/var/run/docker.sock \
  system-monitor
```

## Development

### Project Structure

```
system-monitor/
├── system_monitor.py   # Main application code
├── Dockerfile         # Docker configuration
├── requirements.txt   # Python dependencies
└── README.md         # Documentation
```

### Running Tests

```bash
python -m pytest tests/
```

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
