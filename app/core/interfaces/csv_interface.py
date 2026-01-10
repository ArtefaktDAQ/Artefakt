import time
import os
import csv
import re
from PyQt6.QtCore import QThread, pyqtSignal, QMutex
from app.core.interfaces.base_interface import BaseInterface

class CSVInterface(BaseInterface):
    """Interface for reading data from CSV files periodically."""
    
    DISPLAY_NAME = "Read CSV"
    DESCRIPTION = "Read sensor data from a CSV file"
    ICON = "📄"
    
    CONFIG_SCHEMA = {
        "file_path": {"type": "string", "label": "File Path", "default": ""},
        "poll_interval": {"type": "number", "label": "Poll Interval (s)", "default": 1.0}
    }

    def __init__(self, file_path, poll_interval=1.0, mappings=None):
        super().__init__(name="CSVInterface")
        self.file_path = file_path
        self.poll_interval = float(poll_interval)
        # mappings: list of {column: name_or_idx, sensor_name: str, extract_rule: str}
        self.mappings = mappings or []
        self.connected = False
        self.last_poll_time = 0
        self.last_file_size = -1
        self.last_mtime = -1
        self.headers = None
        self.error_message = ""
        self.should_stop = False
        
    def connect(self):
        if not os.path.exists(self.file_path):
            self.error_message = f"File not found: {self.file_path}"
            self.connected = False
            return False
        try:
            with open(self.file_path, 'r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                self.headers = next(reader, None)
            self.connected = True
            self.error_message = ""
            return True
        except Exception as e:
            self.error_message = str(e)
            self.connected = False
            return False

    def disconnect(self):
        self.connected = False

    def is_connected(self):
        return self.connected and os.path.exists(self.file_path)

    def read_data(self):
        """Reads the last line of the CSV file, with retry on block."""
        if not self.is_connected():
            return None
        
        curr_time = time.time()
        if curr_time - self.last_poll_time < self.poll_interval:
            return None
        
        # Update last_poll_time immediately
        self.last_poll_time = curr_time

        # Check if file has been updated (size or modification time changed)
        try:
            current_size = os.path.getsize(self.file_path)
            current_mtime = os.path.getmtime(self.file_path)
            
            if current_size == self.last_file_size and current_mtime == self.last_mtime:
                # No changes to the file, return None to avoid re-processing old data
                return None
            
            # Update markers
            self.last_file_size = current_size
            self.last_mtime = current_mtime
        except Exception:
            # File might be temporarily inaccessible
            return None

        # Retry logic for blocked files (Windows file locks)
        max_retries = 3
        retry_delay = 0.05  # 50ms
        
        # Only retry if the total delay fits within half the poll interval to be safe
        if self.poll_interval < (max_retries * retry_delay * 2):
            max_retries = 1 # Skip retries for high-speed polling

        for attempt in range(max_retries):
            try:
                if not os.path.exists(self.file_path):
                    return None
                    
                with open(self.file_path, 'r', newline='', encoding='utf-8', errors='ignore') as f:
                    # Seek to near the end
                    f.seek(0, os.SEEK_END)
                    pos = f.tell()
                    if pos == 0: return None
                    
                    # Read a chunk from the end to find the last line
                    chunk_size = 4096
                    f.seek(max(0, pos - chunk_size))
                    lines = f.readlines()
                    
                    if not lines: return None
                    
                    # Get the last complete non-empty line
                    last_line = ""
                    for line in reversed(lines):
                        if line.strip():
                            last_line = line.strip()
                            break
                    
                    if not last_line: return None
                    
                    # Use csv reader to handle quotes correctly
                    reader = csv.reader([last_line])
                    row = next(reader, None)
                    if not row: return None
                    
                    data = {}
                    for m in self.mappings:
                        col_key = m.get('column')
                        sensor_name = m.get('sensor_name')
                        idx = -1
                        
                        if isinstance(col_key, int):
                            idx = col_key
                        elif self.headers:
                            try:
                                idx = self.headers.index(col_key)
                            except ValueError:
                                if str(col_key).isdigit():
                                    idx = int(col_key)
                        
                        if 0 <= idx < len(row):
                            raw = row[idx]
                            val = self._process_value(raw, m.get('extract_rule'))
                            if val is not None:
                                data[sensor_name] = val
                    
                    if data:
                        return data
                    return None # No mapping matches
                    
            except IOError as e:
                # Likely a file lock (Sharing Violation)
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                else:
                    # Final attempt failed
                    return None
            except Exception:
                return None
                
        return None

    def write_data(self, data):
        """CSV interface does not support writing data."""
        return False

    def _process_value(self, text, rule):
        """Extracts numeric values using regex or basic cleaning."""
        if text is None: return None
        text = str(text).strip()
        if not text: return None
        
        if rule:
            try:
                # Improved regex to handle negative values and capture groups
                # Default suggests ([-+]?[0-9]*\.?[0-9]+)
                match = re.search(rule, text)
                if match:
                    text = match.group(1) if match.groups() else match.group(0)
            except Exception:
                pass
                
        try:
            # Remove units/text and convert to float
            # Only keep digits, dot, and leading minus sign
            # Using a more robust cleaning: find the first number-like part
            # Support scientific notation as well
            num_match = re.search(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', text)
            if num_match:
                return float(num_match.group(0))
            return None
        except (ValueError, TypeError):
            return None

class CSVThread(QThread):
    """Thread for managing multiple CSV interfaces."""
    data_received_signal = pyqtSignal(dict)
    
    def __init__(self):
        super().__init__()
        self.interfaces = []
        self.running = True
        self.mutex = QMutex()
        
    def set_configs(self, configs):
        """Update interface configurations."""
        self.mutex.lock()
        self.interfaces = []
        for cfg in configs:
            if cfg.get('enabled', True):
                iface = CSVInterface(
                    file_path=cfg['file'],
                    poll_interval=cfg.get('poll', 1.0),
                    mappings=cfg.get('mappings', [])
                )
                if iface.connect():
                    self.interfaces.append(iface)
        self.mutex.unlock()

    def run(self):
        self.running = True
        while self.running:
            self.mutex.lock()
            current_interfaces = list(self.interfaces)
            self.mutex.unlock()
            
            if not current_interfaces:
                # No interfaces configured yet, just wait
                time.sleep(0.5)
                continue

            for iface in current_interfaces:
                if not self.running: break
                try:
                    data = iface.read_data()
                    if data:
                        # print(f"CSVThread: Emitting data from {iface.file_path}: {data}")
                        self.data_received_signal.emit(data)
                except Exception as e:
                    # Silence thread errors
                    pass
            
            time.sleep(0.1)
        print("CSVThread: Stopped")

    def stop(self):
        self.running = False
        if self.isRunning():
            self.wait()

