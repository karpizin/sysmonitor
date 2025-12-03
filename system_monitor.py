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
        
        # History Data (Managed by background threads)
        self.history = {
            'cpu': deque(maxlen=history_length),
            'mem': deque(maxlen=history_length),
            'disk': deque(maxlen=history_length),
            'docker_count': deque(maxlen=history_length)
        }
        
        # Current State (Ready for UI to read instantly)
        self.state = {
            'system_ready': False,
            'cpu': 0,
            'mem': {'virtual': {'total':0, 'available':0, 'percent':0}, 'swap': {'total':0, 'used':0, 'percent':0}},
            'disk': {'total':0, 'free':0, 'percent':0},
            'ports': [],
            'system_info': {},
            
            'docker_ready': False,
            'containers': [],
            'container_count': 0,
            'port_map': {},
            
            'storage_ready': False,
            'storage_str': "Initializing..."
        }
        
        self.stop_threads = False
        
        # Thread 1: System Stats (CPU, Mem, Disk, Ports, Info)
        self.sys_thread = threading.Thread(target=self._loop_system_stats, daemon=True)
        
        # Thread 2: Docker Fast updates (Containers List + CPU/Mem Stats)
        self.container_thread = threading.Thread(target=self._loop_containers, daemon=True)
        
        # Thread 3: Docker Slow updates (Docker Disk Usage)
        self.space_thread = threading.Thread(target=self._loop_space, daemon=True)
        
        # Start threads
        self.sys_thread.start()
        self.container_thread.start()
        self.space_thread.start()

    def _format_bytes(self, b):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if b < 1024.0:
                return f"{b:.1f}{unit}"
            b /= 1024.0
        return f"{b:.1f}PB"

    def _loop_system_stats(self):
        """Loop to collect Host System Metrics"""
        # Static info (once)
        try:
             boot_time = datetime.fromtimestamp(psutil.boot_time())
             os_info = {
                'os': platform.system(),
                'release': platform.release(),
                'version': platform.version(),
                'machine': platform.machine(),
                'boot_time': boot_time
             }
        except:
             os_info = {}

        while not self.stop_threads:
            try:
                # 1. CPU
                cpu = psutil.cpu_percent(interval=None)
                self.history['cpu'].append(cpu)
                
                # 2. Memory
                v_mem = psutil.virtual_memory()
                s_mem = psutil.swap_memory()
                self.history['mem'].append(v_mem.percent)
                
                mem_data = {
                    'virtual': {
                        'total': v_mem.total / (1024**3),
                        'available': v_mem.available / (1024**3),
                        'percent': v_mem.percent
                    },
                    'swap': {
                        'total': s_mem.total / (1024**3),
                        'used': s_mem.used / (1024**3),
                        'percent': s_mem.percent
                    }
                }
                
                # 3. Disk
                d = psutil.disk_usage('/')
                self.history['disk'].append(d.percent)
                disk_data = {
                    'total': d.total / (1024**3),
                    'free': d.free / (1024**3),
                    'percent': d.percent
                }
                
                # 4. Ports (Can be slow)
                used_ports = []
                try:
                    for conn in psutil.net_connections(kind='inet'):
                        if conn.status == 'LISTEN':
                            used_ports.append(f"{conn.laddr.ip}:{conn.laddr.port}")
                except:
                    pass
                used_ports.sort()

                # 5. Uptime
                if 'boot_time' in os_info:
                    delta = datetime.now() - os_info['boot_time']
                    days = delta.days
                    hours, rem = divmod(delta.seconds, 3600)
                    mins, _ = divmod(rem, 60)
                    os_info['uptime'] = f"{days}d {hours}h {mins}m"
                
                # UPDATE STATE
                self.state['cpu'] = cpu
                self.state['mem'] = mem_data
                self.state['disk'] = disk_data
                self.state['ports'] = used_ports
                self.state['system_info'] = os_info
                self.state['system_ready'] = True
                
            except Exception:
                pass
                
            time.sleep(1) # Update system stats every 1s

    def _loop_containers(self):
        """Fast loop: Docker Lists and Stats"""
        try:
            client = docker.from_env()
        except Exception:
            return 

        while not self.stop_threads:
            try:
                containers = client.containers.list()
                count = len(containers)
                
                data_list = []
                port_map = {}

                for c in containers:
                    try:
                        # Health
                        health = "N/A"
                        if 'Health' in c.attrs['State']:
                            health = c.attrs['State']['Health']['Status']
                        
                        # Ports mapping
                        ports_list = []
                        for p in c.ports.values():
                            if p:
                                for mapping in p:
                                    if 'HostPort' in mapping:
                                        hp = mapping['HostPort']
                                        ports_list.append(hp)
                                        port_map[hp] = c.name

                        ports_str = ",".join(ports_list[:3])
                        if len(ports_list) > 3: ports_str += "..."
                        
                        # Stats Snapshot
                        stats = c.stats(stream=False)
                        
                        # CPU
                        cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                                    stats['precpu_stats']['cpu_usage']['total_usage']
                        system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                                       stats['precpu_stats']['system_cpu_usage']
                        n_cpus = stats['cpu_stats']['online_cpus']
                        cpu_p = 0.0
                        if system_delta > 0 and cpu_delta > 0:
                            cpu_p = (cpu_delta / system_delta) * n_cpus * 100.0

                        # Mem
                        mem_usage = stats['memory_stats']['usage']
                        mem_mb = mem_usage / (1024 * 1024)
                        
                        # Net
                        rx = 0
                        tx = 0
                        if 'networks' in stats:
                            for n in stats['networks'].values():
                                rx += n.get('rx_bytes', 0)
                                tx += n.get('tx_bytes', 0)
                        net_str = f"{self._format_bytes(rx)} / {self._format_bytes(tx)}"

                        data_list.append({
                            'name': c.name,
                            'status': c.status,
                            'health': health,
                            'ports': ports_str,
                            'cpu': cpu_p,
                            'mem_mb': mem_mb,
                            'net_io': net_str
                        })
                    except:
                        continue

                # UPDATE STATE
                self.state['containers'] = data_list
                self.state['container_count'] = count
                self.state['port_map'] = port_map
                self.state['docker_ready'] = True
                
                self.history['docker_count'].append(count)

            except Exception:
                pass
            
            time.sleep(2)

    def _loop_space(self):
        """Slow loop: Docker DF"""
        try:
            client = docker.from_env()
        except:
            self.state['storage_str'] = "Docker not found"
            return

        while not self.stop_threads:
            try:
                info = client.df()
                # Calculate size...
                total = sum(i['Size'] for i in info['Images'])
                total += sum(v['UsageData']['Size'] for v in info['Volumes'] if v['UsageData'])
                total += sum(c['SizeRw'] for c in info['Containers'] if c.get('SizeRw'))
                
                gb = total / (1024**3)
                self.state['storage_str'] = f"{gb:.1f}GB"
                self.state['storage_ready'] = True
            except:
                self.state['storage_str'] = "Error"
            
            # Long sleep
            for _ in range(60):
                if self.stop_threads: return
                time.sleep(1)
    
    def create_bar(self, percent, width=30):
        filled = int(width * percent / 100)
        bar = '█' * filled + '░' * (width - filled)
        return f'[{bar}] {percent:.1f}%'
    
    def create_sparkline(self, data, width=30, max_value=100):
        if not data:
            return "░" * width
        normalized = []
        if max_value is not None:
            for x in data:
                val = max(0, min(x, max_value))
                normalized.append(int(7 * val / max_value))
        else:
            mn = min(data)
            mx = max(data)
            if mn == mx:
                normalized = [4 for _ in data]
            else:
                normalized = [int(7 * (x - mn) / (mx - mn)) for x in data]
        
        spark_chars = " ▂▃▄▅▆▇█"
        return ''.join(spark_chars[n] for n in normalized[-width:])
    
    def display_metrics(self):
        # READ STATE (Instant)
        if not self.state['system_ready']:
            os.system('clear' if os.name == 'posix' else 'cls')
            print("\nInitializing system metrics...\n")
            return

        s = self.state
        h = self.history
        
        lines = []
        lines.append(f"\n{ '=' * 85}")
        lines.append(f"System Monitor - {datetime.now().strftime('%H:%M:%S')}")
        lines.append(f"{ '=' * 85}\n")
        
        # System Info
        info = s['system_info']
        if info:
            lines.append(f"SYSTEM INFO:")
            lines.append(f"OS: {info.get('os')} {info.get('release')} ({info.get('version')})")
            lines.append(f"Architecture: {info.get('machine')}")
            lines.append(f"Uptime: {info.get('uptime')}\n")
        
        # CPU
        lines.append(f"CPU Usage:")
        lines.append(f"{self.create_bar(s['cpu'])}  Trend: {self.create_sparkline(h['cpu'], 20)}")
        
        # Mem
        lines.append(f"Memory:")
        lines.append(f"Free: {s['mem']['virtual']['available']:.1f}GB / {s['mem']['virtual']['total']:.1f}GB")
        lines.append(f"{self.create_bar(s['mem']['virtual']['percent'])}  Trend: {self.create_sparkline(h['mem'], 20)}\n")
        
        # Swap
        if s['mem']['swap']['total'] > 0:
            lines.append(f"Swap:")
            lines.append(f"Used: {s['mem']['swap']['used']:.1f}GB / {s['mem']['swap']['total']:.1f}GB")
            lines.append(f"{self.create_bar(s['mem']['swap']['percent'])}\n")
            
        # Disk
        lines.append(f"Disk Usage:")
        lines.append(f"Free: {s['disk']['free']:.1f}GB / {s['disk']['total']:.1f}GB")
        lines.append(f"{self.create_bar(s['disk']['percent'])}  Trend: {self.create_sparkline(h['disk'], 20)}\n")
        
        # Docker
        lines.append("-" * 85)
        lines.append(f"DOCKER SYSTEM:")
        lines.append(f"Storage: {s['storage_str']}")
        
        if not s['docker_ready']:
             lines.append("Loading containers info...")
        else:
            lines.append(f"Active Containers: {s['container_count']}")
            if len(h['docker_count']) > 0:
                 lines.append(f"Trend: {self.create_sparkline(h['docker_count'], 40, max_value=None)}")
            lines.append("")
            
            if s['containers']:
                lines.append(f"{ 'NAME':<30} {'STATUS':<10} {'HEALTH':<10} {'CPU%':<6} {'MEM':<10} {'NET I/O':<18} {'PORTS'}")
                lines.append("-" * 85)
                for c in s['containers'][:15]:
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
                if len(s['containers']) > 15:
                    lines.append(f"... and {len(s['containers']) - 15} more")
            else:
                lines.append("No active containers found.")

        lines.append("")
        
        # Ports
        lines.append("-" * 85)
        lines.append(f"Open Ports ({len(s['ports'])}):")
        fmt_ports = []
        for p in s['ports']:
            try:
                pn = p.split(':')[-1]
                if pn in s['port_map']:
                    fmt_ports.append(f"{p} ({s['port_map'][pn]})")
                else:
                    fmt_ports.append(p)
            except:
                fmt_ports.append(p)
        
        p_str = ", ".join(fmt_ports[:8])
        if len(fmt_ports) > 8: p_str += f", ... {len(fmt_ports)-8} more"
        lines.append(p_str)
        
        # CLEAR AND PRINT INSTANTLY
        os.system('clear' if os.name == 'posix' else 'cls')
        print('\n'.join(lines))

def main():
    monitor = SystemMonitor()
    try:
        # Initial clear
        os.system('clear' if os.name == 'posix' else 'cls')
        print("Starting System Monitor (Full Async)...")
        
        while True:
            monitor.display_metrics()
            time.sleep(1) # Refresh UI every 1s (can be faster now)
    except KeyboardInterrupt:
        monitor.stop_threads = True
        print("\nShutting down...")

if __name__ == "__main__":
    main()
