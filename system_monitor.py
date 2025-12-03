import psutil
import time
import os
import docker
import socket
from datetime import datetime
from collections import deque

class SystemMonitor:
    def __init__(self, history_length=60):
        self.docker_client = docker.from_env()
        self.history_length = history_length
        # Initialize histories for graphs
        self.cpu_history = deque(maxlen=history_length)
        self.memory_history = deque(maxlen=history_length)
        self.disk_usage_history = deque(maxlen=history_length)
        self.docker_containers_history = deque(maxlen=history_length)
        
        # Caching for heavy operations
        self.last_docker_space_check = 0
        self.cached_docker_space = 0
        
    def get_cpu_usage(self):
        cpu_percent = psutil.cpu_percent(interval=None)
        self.cpu_history.append(cpu_percent)
        return cpu_percent
    
    def get_memory_usage(self):
        memory = psutil.virtual_memory()
        self.memory_history.append(memory.percent)
        return memory.percent
    
    def get_disk_space(self):
        disk = psutil.disk_usage('/')
        self.disk_usage_history.append(disk.percent)
        return {
            'total': disk.total / (1024**3),  # GB
            'free': disk.free / (1024**3),    # GB
            'percent': disk.percent
        }
    
    def get_docker_space(self):
        # Cache this heavy operation (docker df takes time)
        current_time = time.time()
        if current_time - self.last_docker_space_check < 60 and self.last_docker_space_check != 0:
            return self.cached_docker_space

        try:
            info = self.docker_client.df()
            total_space = sum(image['Size'] for image in info['Images'])
            volumes_space = sum(volume['UsageData']['Size'] for volume in info['Volumes'] if volume['UsageData'])
            containers_space = sum(container['SizeRw'] for container in info['Containers'] if container.get('SizeRw'))
            
            total_used = (total_space + volumes_space + containers_space) / (1024**3)  # Convert to GB
            
            self.cached_docker_space = total_used
            self.last_docker_space_check = current_time
            return total_used
        except Exception as e:
            return f"Docker space error: {str(e)}"
    
    def get_docker_containers(self):
        try:
            containers = self.docker_client.containers.list()
            count = len(containers)
            self.docker_containers_history.append(count)
            return {
                'count': count,
                'names': [container.name for container in containers]
            }
        except Exception as e:
            self.docker_containers_history.append(0)
            return {'count': 0, 'names': [f"Docker containers error: {str(e)}"]}
    
    def get_used_ports(self):
        used_ports = []
        try:
            # Use net_connections with handling for potential permission issues or timeouts
            for conn in psutil.net_connections(kind='inet'):
                if conn.status == 'LISTEN':
                    used_ports.append(f"{conn.laddr.ip}:{conn.laddr.port}")
        except Exception:
            pass
        return sorted(used_ports)
    
    def create_bar(self, percent, width=30):
        filled = int(width * percent / 100)
        bar = '█' * filled + '░' * (width - filled)
        return f'[{bar}] {percent:.1f}%'
    
    def create_sparkline(self, data, width=30):
        if not data:
            return "░" * width
        
        # Normalize data for the graph
        min_val = min(data)
        max_val = max(data)
        if min_val == max_val:
            normalized = [4 for _ in data]  # Middle line
        else:
            normalized = [int(7 * (x - min_val) / (max_val - min_val)) for x in data]
        
        # Characters for different graph levels
        spark_chars = " ▂▃▄▅▆▇█"
        
        # Create graph
        graph = ''.join(spark_chars[n] for n in normalized[-width:])
        return graph
    
    def display_metrics(self):
        # 1. Gather all data FIRST (prevents flickering and blank screens during calculation)
        cpu_percent = self.get_cpu_usage()
        mem_percent = self.get_memory_usage()
        disk_info = self.get_disk_space()
        docker_space = self.get_docker_space()
        containers = self.get_docker_containers()
        ports = self.get_used_ports()
        
        # 2. Prepare the output buffer
        lines = []
        
        lines.append(f"\n{'=' * 60}")
        lines.append(f"System Monitor - {datetime.now().strftime('%H:%M:%S')}")
        lines.append(f"{'=' * 60}\n")
        
        # CPU
        lines.append(f"CPU Usage:")
        lines.append(f"{self.create_bar(cpu_percent)}")
        lines.append(f"Last minute trend:")
        lines.append(f"{self.create_sparkline(self.cpu_history)}\n")
        
        # Memory
        lines.append(f"Memory:")
        lines.append(f"{self.create_bar(mem_percent)}")
        lines.append(f"Last minute trend:")
        lines.append(f"{self.create_sparkline(self.memory_history)}\n")
        
        # Disk
        lines.append(f"Disk:")
        lines.append(f"Free: {disk_info['free']:.1f}GB of {disk_info['total']:.1f}GB")
        lines.append(f"{self.create_bar(disk_info['percent'])}")
        lines.append(f"Usage trend:")
        lines.append(f"{self.create_sparkline(self.disk_usage_history)}\n")
        
        # Docker space
        lines.append(f"Docker Storage (Cached, updates every 60s):")
        if isinstance(docker_space, float):
            lines.append(f"Used: {docker_space:.1f}GB\n")
        else:
            lines.append(f"{docker_space}\n")
        
        # Docker containers
        lines.append(f"Docker Containers ({containers['count']}):")
        lines.append(f"Container count trend:")
        lines.append(f"{self.create_sparkline(self.docker_containers_history)}")
        
        max_display = 5
        for i, name in enumerate(containers['names']):
            if i >= max_display:
                lines.append(f"... and {len(containers['names']) - max_display} more")
                break
            lines.append(f"- {name}")
        lines.append("")
        
        # Network ports
        lines.append(f"Used Network Ports ({len(ports)}):")
        max_ports = 10
        for i, port in enumerate(ports):
            if i >= max_ports:
                lines.append(f"... and {len(ports) - max_ports} more")
                break
            lines.append(f"- {port}")
            
        # 3. Clear screen and print everything at once
        os.system('clear' if os.name == 'posix' else 'cls')
        print('\n'.join(lines))

def main():
    monitor = SystemMonitor()
    try:
        # Initial clear
        os.system('clear' if os.name == 'posix' else 'cls')
        print("Starting System Monitor...")
        
        while True:
            monitor.display_metrics()
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nShutting down...")

if __name__ == "__main__":
    main()