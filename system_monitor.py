import psutil
import time
import os
import docker
import socket
import threading
from datetime import datetime
from collections import deque
import platform

class SystemMonitor:
    def __init__(self, history_length=60):
        self.history_length = history_length
        
        # Initialize histories for graphs
        self.cpu_history = deque(maxlen=history_length)
        self.memory_history = deque(maxlen=history_length)
        self.disk_usage_history = deque(maxlen=history_length)
        self.docker_containers_history = deque(maxlen=history_length)
        
        # Shared State (Thread-Safeish via direct replacement)
        self.docker_state = {
            'containers': [],
            'container_count': 0,
            'space_str': "Initializing...",
            'containers_ready': False,
            'space_ready': False,
            'port_map': {} # Map port -> container name
        }
        
        self.stop_threads = False
        
        # Thread 1: Fast updates (Containers List + CPU/Mem Stats)
        self.container_thread = threading.Thread(target=self._loop_containers, daemon=True)
        
        # Thread 2: Slow updates (Docker Disk Usage)
        self.space_thread = threading.Thread(target=self._loop_space, daemon=True)
        
        # Start threads
        self.container_thread.start()
        self.space_thread.start()

    def _format_bytes(self, b):
        """Helper to format bytes to human readable string"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if b < 1024.0:
                return f"{b:.1f}{unit}"
            b /= 1024.0
        return f"{b:.1f}PB"

    def _loop_containers(self):
        """Fast loop: Lists containers and grabs their stats."""
        try:
            client = docker.from_env()
        except Exception:
            return # Docker likely not available

        while not self.stop_threads:
            try:
                containers = client.containers.list()
                count = len(containers)
                
                data_list = []
                port_map = {}

                for c in containers:
                    # Basic Info
                    try:
                        # Health
                        health = "N/A"
                        if 'Health' in c.attrs['State']:
                            health = c.attrs['State']['Health']['Status']
                        
                        # Ports
                        ports_list = []
                        for p in c.ports.values():
                            if p:
                                for mapping in p:
                                    if 'HostPort' in mapping:
                                        host_port = mapping['HostPort']
                                        ports_list.append(host_port)
                                        # Map this port to container name for later lookup
                                        port_map[host_port] = c.name

                        ports_str = ",".join(ports_list[:3])
                        if len(ports_list) > 3: ports_str += "..."
                        
                        # Stats (Snapshot)
                        stats = c.stats(stream=False)
                        
                        # CPU Calc
                        cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                                    stats['precpu_stats']['cpu_usage']['total_usage']
                        system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                                       stats['precpu_stats']['system_cpu_usage']
                        number_cpus = stats['cpu_stats']['online_cpus']
                        
                        if system_delta > 0 and cpu_delta > 0:
                            cpu_percent = (cpu_delta / system_delta) * number_cpus * 100.0
                        else:
                            cpu_percent = 0.0

                        # Mem Calc
                        mem_usage = stats['memory_stats']['usage']
                        mem_limit = stats['memory_stats']['limit']
                        mem_mb = mem_usage / (1024 * 1024)
                        
                        # Net I/O Calc
                        rx_bytes = 0
                        tx_bytes = 0
                        if 'networks' in stats:
                            for net_name, net_data in stats['networks'].items():
                                rx_bytes += net_data.get('rx_bytes', 0)
                                tx_bytes += net_data.get('tx_bytes', 0)
                        
                        net_io_str = f"{self._format_bytes(rx_bytes)} / {self._format_bytes(tx_bytes)}"

                        data_list.append({
                            'name': c.name,
                            'status': c.status,
                            'health': health,
                            'ports': ports_str,
                            'cpu': cpu_percent,
                            'mem_mb': mem_mb,
                            'net_io': net_io_str
                        })
                    except Exception:
                        continue

                # Update State
                self.docker_state['containers'] = data_list
                self.docker_state['container_count'] = count
                self.docker_state['port_map'] = port_map
                self.docker_state['containers_ready'] = True
                
                # Update History for Sparkline
                self.docker_containers_history.append(count)

            except Exception as e:
                # On error, keep old data or set error flag
                pass
            
            time.sleep(2)

    def _loop_space(self):
        """Slow loop: heavy 'docker df' operation."""
        try:
            client = docker.from_env()
        except Exception:
            self.docker_state['space_str'] = "Docker not found"
            return

        while not self.stop_threads:
            try:
                info = client.df()
                total_space = sum(image['Size'] for image in info['Images'])
                volumes_space = sum(volume['UsageData']['Size'] for volume in info['Volumes'] if volume['UsageData'])
                containers_space = sum(container['SizeRw'] for container in info['Containers'] if container.get('SizeRw'))
                
                total_gb = (total_space + volumes_space + containers_space) / (1024**3)
                
                self.docker_state['space_str'] = f"{total_gb:.1f}GB"
                self.docker_state['space_ready'] = True
            except Exception as e:
                self.docker_state['space_str'] = "Error"
            
            # Sleep 60s between heavy checks
            for _ in range(60):
                if self.stop_threads: return
                time.sleep(1)

    def get_cpu_usage(self):
        cpu_percent = psutil.cpu_percent(interval=None)
        self.cpu_history.append(cpu_percent)
        return cpu_percent
    
    def get_memory_usage(self):
        virtual_mem = psutil.virtual_memory()
        swap_mem = psutil.swap_memory()
        
        self.memory_history.append(virtual_mem.percent) # History still based on virtual mem percent
        
        return {
            'virtual': {
                'total': virtual_mem.total / (1024**3),  # GB
                'available': virtual_mem.available / (1024**3), # GB
                'percent': virtual_mem.percent
            },
            'swap': {
                'total': swap_mem.total / (1024**3),    # GB
                'used': swap_mem.used / (1024**3),      # GB
                'percent': swap_mem.percent
            }
        }
    
    def get_disk_space(self):
        disk = psutil.disk_usage('/')
        self.disk_usage_history.append(disk.percent)
        return {
            'total': disk.total / (1024**3),
            'free': disk.free / (1024**3),
            'percent': disk.percent
        }
    
    def get_used_ports(self):
        used_ports = []
        try:
            for conn in psutil.net_connections(kind='inet'):
                if conn.status == 'LISTEN':
                    used_ports.append(f"{conn.laddr.ip}:{conn.laddr.port}")
        except Exception:
            pass
        return sorted(used_ports)
    
    def get_system_info(self):
        boot_time_timestamp = psutil.boot_time()
        boot_datetime = datetime.fromtimestamp(boot_time_timestamp)
        now_datetime = datetime.now()
        uptime_delta = now_datetime - boot_datetime
        
        days = uptime_delta.days
        hours, remainder = divmod(uptime_delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        uptime_str = f"{days}d {hours}h {minutes}m"
        
        return {
            'os': platform.system(),
            'release': platform.release(),
            'version': platform.version(),
            'machine': platform.machine(),
            'uptime': uptime_str
        }
    
    def create_bar(self, percent, width=30):
        filled = int(width * percent / 100)
        bar = '█' * filled + '░' * (width - filled)
        return f'[{bar}] {percent:.1f}%'
    
    def create_sparkline(self, data, width=30, max_value=100):
        if not data:
            return "░" * width
        
        normalized = []
        if max_value is not None:
            # Absolute scaling (0 to max_value)
            # Clamp values between 0 and max_value
            for x in data:
                val = max(0, min(x, max_value))
                # Scale 0..max_value -> 0..7
                norm = int(7 * val / max_value)
                normalized.append(norm)
        else:
            # Relative scaling (min to max of data)
            min_val = min(data)
            max_val = max(data)
            if min_val == max_val:
                normalized = [4 for _ in data] # Middle line
            else:
                normalized = [int(7 * (x - min_val) / (max_val - min_val)) for x in data]
        
        spark_chars = " ▂▃▄▅▆▇█"
        graph = ''.join(spark_chars[n] for n in normalized[-width:])
        return graph
    
    def display_metrics(self):
        # Gather data
        cpu_percent = self.get_cpu_usage()
        mem_info = self.get_memory_usage()
        disk_info = self.get_disk_space()
        raw_ports = self.get_used_ports()
        
        # Read from async state
        docker_count = self.docker_state['container_count']
        docker_containers = self.docker_state['containers']
        docker_space_str = self.docker_state['space_str']
        port_map = self.docker_state['port_map'] # Get the port map
        
        system_info = self.get_system_info() # Get system info
        
        lines = []
        lines.append(f"\n{ '=' * 85}") # Widened separator
        lines.append(f"System Monitor - {datetime.now().strftime('%H:%M:%S')}")
        lines.append(f"{ '=' * 85}\n")
        
        # System Info Section
        lines.append(f"SYSTEM INFO:")
        lines.append(f"OS: {system_info['os']} {system_info['release']} ({system_info['version']})")
        lines.append(f"Architecture: {system_info['machine']}")
        lines.append(f"Uptime: {system_info['uptime']}\n")
        
        # CPU
        lines.append(f"CPU Usage:")
        lines.append(f"{self.create_bar(cpu_percent)}  Trend: {self.create_sparkline(self.cpu_history, 20)}")
        
        # Memory
        lines.append(f"Memory:")
        lines.append(f"Free: {mem_info['virtual']['available']:.1f}GB / {mem_info['virtual']['total']:.1f}GB")
        lines.append(f"{self.create_bar(mem_info['virtual']['percent'])}  Trend: {self.create_sparkline(self.memory_history, 20)}\n") 

        # Swap Memory
        if mem_info['swap']['total'] > 0:
            lines.append(f"Swap:")
            lines.append(f"Used: {mem_info['swap']['used']:.1f}GB / {mem_info['swap']['total']:.1f}GB")
            lines.append(f"{self.create_bar(mem_info['swap']['percent'])}\n")
        
        # Disk
        lines.append(f"Disk Usage:")
        lines.append(f"Free: {disk_info['free']:.1f}GB / {disk_info['total']:.1f}GB")
        lines.append(f"{self.create_bar(disk_info['percent'])}  Trend: {self.create_sparkline(self.disk_usage_history, 20)}\n")
        
        # Docker Section
        lines.append("-" * 85)
        lines.append(f"DOCKER SYSTEM:")
        lines.append(f"Storage: {docker_space_str}")
        
        if not self.docker_state['containers_ready']:
             lines.append("Loading containers info...")
        else:
            lines.append(f"Active Containers: {docker_count}")
            if len(self.docker_containers_history) > 0:
                 # Use relative scaling (max_value=None) for container count
                 lines.append(f"Trend: {self.create_sparkline(self.docker_containers_history, 40, max_value=None)}")
            lines.append("")
            
            # Table
            if docker_containers:
                # Updated Header with wider NAME and new NET I/O column
                # NAME: 30 chars
                # NET IO: 15 chars
                lines.append(f"{ 'NAME':<30} {'STATUS':<10} {'HEALTH':<10} {'CPU%':<6} {'MEM':<10} {'NET I/O':<18} {'PORTS'}")
                lines.append("-" * 85)
                for c in docker_containers[:15]:
                    # Wider truncation for name
                    name = (c['name'][:28] + '..') if len(c['name']) > 30 else c['name']
                    lines.append(
                        f"{name:<30} "
                        f"{c['status']:<10} "
                        f"{c['health']:<10} "
                        f"{c['cpu']:>5.1f}% "
                        f"{c['mem_mb']:>6.1f}MB "
                        f"{c['net_io']:<18} "
                        f"{c['ports']}"
                    )
                if len(docker_containers) > 15:
                    lines.append(f"... and {len(docker_containers) - 15} more")
            else:
                lines.append("No active containers found.")

        lines.append("")

        # Ports Section
        lines.append("-" * 85)
        lines.append(f"Open Ports ({len(raw_ports)}):")
        
        # Format ports with service names
        formatted_ports = []
        for p_str in raw_ports:
             try:
                 port_num = p_str.split(':')[-1]
                 if port_num in port_map:
                     formatted_ports.append(f"{p_str} ({port_map[port_num]})")
                 else:
                     formatted_ports.append(p_str)
             except:
                 formatted_ports.append(p_str)
        
        port_str = ", ".join(formatted_ports[:8]) 
        if len(formatted_ports) > 8:
            port_str += f", ... and {len(formatted_ports)-8} more"
        lines.append(port_str)
            
        # Render
        os.system('clear' if os.name == 'posix' else 'cls')
        print('\n'.join(lines))

def main():
    monitor = SystemMonitor()
    try:
        # Initial clear
        os.system('clear' if os.name == 'posix' else 'cls')
        print("Starting System Monitor (Async Mode)...")
        
        while True:
            monitor.display_metrics()
            time.sleep(2)
    except KeyboardInterrupt:
        monitor.stop_threads = True
        print("\nShutting down...")

if __name__ == "__main__":
    main()