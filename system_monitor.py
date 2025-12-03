import psutil
import time
import os
import docker
import socket
import threading
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
        
        # Container Stats Cache (managed by background thread)
        self.container_stats = {}
        self.stop_threads = False
        self.stats_thread = threading.Thread(target=self._collect_docker_stats, daemon=True)
        self.stats_thread.start()

    def _collect_docker_stats(self):
        """Background thread to collect CPU/Mem stats for containers without blocking UI"""
        while not self.stop_threads:
            try:
                containers = self.docker_client.containers.list()
                for container in containers:
                    try:
                        # stats(stream=False) takes a snapshot. Can still be slow-ish.
                        # We catch errors to prevent thread death.
                        stats = container.stats(stream=False)
                        
                        # Calculate CPU %
                        # Docker returns standard stats format
                        cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                                    stats['precpu_stats']['cpu_usage']['total_usage']
                        system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                                       stats['precpu_stats']['system_cpu_usage']
                        
                        number_cpus = stats['cpu_stats']['online_cpus']
                        if system_delta > 0 and cpu_delta > 0:
                            cpu_percent = (cpu_delta / system_delta) * number_cpus * 100.0
                        else:
                            cpu_percent = 0.0

                        # Calculate Memory Usage
                        mem_usage = stats['memory_stats']['usage']
                        mem_limit = stats['memory_stats']['limit']
                        mem_percent = (mem_usage / mem_limit) * 100.0 if mem_limit > 0 else 0.0
                        
                        # Convert Mem to MB
                        mem_mb = mem_usage / (1024 * 1024)

                        self.container_stats[container.name] = {
                            'cpu': cpu_percent,
                            'mem_percent': mem_percent,
                            'mem_mb': mem_mb
                        }
                    except Exception:
                        # Container might have died or stats unavailable
                        pass
                
                # Sleep a bit to not hammer the Docker API
                time.sleep(2) 
            except Exception:
                time.sleep(5)

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
            
            container_data = []
            for c in containers:
                # Health check extraction
                health = "N/A"
                if 'Health' in c.attrs['State']:
                    health = c.attrs['State']['Health']['Status']
                
                # Ports extraction (simplified)
                ports_list = []
                for p in c.ports.values():
                    if p:
                        for mapping in p:
                            if 'HostPort' in mapping:
                                ports_list.append(mapping['HostPort'])
                ports_str = ",".join(ports_list[:3]) # Show max 3 ports
                if len(ports_list) > 3: ports_str += "..."

                # Get Stats from Cache
                stats = self.container_stats.get(c.name, {'cpu': 0.0, 'mem_percent': 0.0, 'mem_mb': 0.0})

                container_data.append({
                    'name': c.name,
                    'id': c.short_id,
                    'status': c.status,
                    'health': health,
                    'ports': ports_str,
                    'cpu': stats['cpu'],
                    'mem_mb': stats['mem_mb'],
                    'mem_percent': stats['mem_percent']
                })
                
            return {
                'count': count,
                'data': container_data
            }
        except Exception as e:
            self.docker_containers_history.append(0)
            return {'count': 0, 'data': [], 'error': str(e)}
    
    def get_used_ports(self):
        used_ports = []
        try:
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
        min_val = min(data)
        max_val = max(data)
        if min_val == max_val:
            normalized = [4 for _ in data]
        else:
            normalized = [int(7 * (x - min_val) / (max_val - min_val)) for x in data]
        spark_chars = " ▂▃▄▅▆▇█"
        graph = ''.join(spark_chars[n] for n in normalized[-width:])
        return graph
    
    def display_metrics(self):
        cpu_percent = self.get_cpu_usage()
        mem_percent = self.get_memory_usage()
        disk_info = self.get_disk_space()
        docker_space = self.get_docker_space()
        containers = self.get_docker_containers()
        ports = self.get_used_ports()
        
        lines = []
        lines.append(f"\n{ '=' * 70}")
        lines.append(f"System Monitor - {datetime.now().strftime('%H:%M:%S')}")
        lines.append(f"{ '=' * 70}\n")
        
        # CPU
        lines.append(f"CPU Usage:")
        lines.append(f"{self.create_bar(cpu_percent)}  Spark: {self.create_sparkline(self.cpu_history, 20)}")
        
        # Memory
        lines.append(f"Memory:")
        lines.append(f"{self.create_bar(mem_percent)}  Spark: {self.create_sparkline(self.memory_history, 20)}\n")
        
        # Disk
        lines.append(f"Disk Usage:")
        lines.append(f"Free: {disk_info['free']:.1f}GB / {disk_info['total']:.1f}GB")
        lines.append(f"{self.create_bar(disk_info['percent'])}  Spark: {self.create_sparkline(self.disk_usage_history, 20)}\n")
        
        # Docker Info
        lines.append("-" * 70)
        lines.append(f"DOCKER SYSTEM:")
        lines.append(f"Storage: {docker_space:.1f}GB" if isinstance(docker_space, float) else f"Storage: {docker_space}")
        lines.append(f"Active Containers: {containers['count']}")
        lines.append(f"Trend: {self.create_sparkline(self.docker_containers_history, 40)}")
        lines.append("")
        
        # Container Table
        if containers['data']:
            # Header
            lines.append(f"{ 'NAME':<20} {'STATUS':<10} {'HEALTH':<10} {'CPU%':<6} {'MEM':<10} {'PORTS'}")
            lines.append("-" * 70)
            
            for c in containers['data'][:15]: # Show max 15 containers
                # Format health with basic indicators
                health_str = c['health']
                
                # Truncate name if too long
                name = (c['name'][:18] + '..') if len(c['name']) > 20 else c['name']
                
                lines.append(
                    f"{name:<20} "
                    f"{c['status']:<10} "
                    f"{health_str:<10} "
                    f"{c['cpu']:>5.1f}% "
                    f"{c['mem_mb']:>6.1f}MB "
                    f"{c['ports']}"
                )
            if len(containers['data']) > 15:
                lines.append(f"... and {len(containers['data']) - 15} more")
        else:
            lines.append("No active containers.")
        lines.append("")

        # Network Ports
        lines.append("-" * 70)
        lines.append(f"Open Ports ({len(ports)}):")
        # Compact display of ports
        port_str = ", ".join(ports[:12])
        if len(ports) > 12:
            port_str += f", ... and {len(ports)-12} more"
        lines.append(port_str)
            
        # Clear and Print
        os.system('clear' if os.name == 'posix' else 'cls')
        print('\n'.join(lines))

def main():
    monitor = SystemMonitor()
    try:
        # Initial clear
        os.system('clear' if os.name == 'posix' else 'cls')
        print("Starting System Monitor with Threaded Stats Collection...")
        print("Please wait a few seconds for stats to populate...")
        
        while True:
            monitor.display_metrics()
            time.sleep(2)
    except KeyboardInterrupt:
        monitor.stop_threads = True
        print("\nShutting down...")

if __name__ == "__main__":
    main()
