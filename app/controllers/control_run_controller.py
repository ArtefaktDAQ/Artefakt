"""
Control Run Controller

Manages control run data selection, time offset, and integration with the graphing system.
"""

import os
import json
import csv
import shutil
from PyQt6.QtCore import QObject, pyqtSignal
from collections import defaultdict


class ControlRunController(QObject):
    """Controls control run data management and configuration"""
    
    # Signal emitted when control run configuration changes
    control_run_changed = pyqtSignal()
    
    def __init__(self, main_window):
        """
        Initialize the control run controller
        
        Args:
            main_window: Main application window
        """
        super().__init__()
        self.main_window = main_window
        self.control_run_path = None
        self.control_run_name = None
        self.time_offset = 0.0  # Time offset in seconds
        self.control_run_data = {}  # Cached control run data
        
    def get_available_runs(self):
        """
        Get list of available runs that can be used as control runs
        
        Returns:
            List of tuples (run_path, run_display_name)
        """
        available_runs = []
        
        # Get base directory
        if not hasattr(self.main_window, 'project_controller'):
            return available_runs
            
        base_dir = self.main_window.project_base_dir.text()
        if not base_dir or not os.path.exists(base_dir):
            return available_runs
            
        # Scan for all runs in all test series in all projects
        try:
            for project_name in os.listdir(base_dir):
                project_dir = os.path.join(base_dir, project_name)
                if not os.path.isdir(project_dir):
                    continue
                    
                # Scan test series
                for series_name in os.listdir(project_dir):
                    series_dir = os.path.join(project_dir, series_name)
                    if not os.path.isdir(series_dir):
                        continue
                        
                    # Scan runs
                    for run_name in os.listdir(series_dir):
                        run_dir = os.path.join(series_dir, run_name)
                        if not os.path.isdir(run_dir):
                            continue
                            
                        # Check if this run has data files
                        csv_files = [f for f in os.listdir(run_dir) if f.endswith('.csv') and f.startswith('rundata_')]
                        if csv_files:
                            display_name = f"{project_name} > {series_name} > {run_name}"
                            available_runs.append((run_dir, display_name))
        except Exception as e:
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Error scanning for available runs: {e}", "ERROR")
                
        return available_runs
    
    def set_control_run(self, run_path, run_name):
        """
        Set the control run to use for comparison
        
        Args:
            run_path: Full path to the control run directory
            run_name: Display name of the control run
        """
        self.control_run_path = run_path
        self.control_run_name = run_name
        
        # Clear cached data - will be reloaded when needed
        self.control_run_data = {}
        
        if hasattr(self.main_window, 'logger'):
            self.main_window.logger.log(f"Control run set to: {run_name}", "INFO")
            
        # Emit signal that control run has changed
        # This will trigger on_control_run_changed_update which updates dropdowns and graph
        self.control_run_changed.emit()
    
    def set_time_offset(self, offset):
        """
        Set the time offset for the control run data
        
        Args:
            offset: Time offset in seconds (positive or negative)
        """
        self.time_offset = float(offset)
        
        if hasattr(self.main_window, 'logger'):
            self.main_window.logger.log(f"Control run time offset set to: {offset}s", "INFO")
            
        # Emit signal that control run configuration has changed
        self.control_run_changed.emit()
    
    def load_control_run_data(self):
        """
        Load control run data from CSV file
        
        Returns:
            Dictionary with sensor data: {sensor_id_ctrl: {'time': [...], 'value': [...]}}
            Keys have '_ctrl' suffix to distinguish from current run sensors
        """
        if not self.control_run_path or not os.path.exists(self.control_run_path):
            return {}
            
        # Find the CSV file in the control run directory
        try:
            csv_files = [f for f in os.listdir(self.control_run_path) 
                        if f.endswith('.csv') and f.startswith('rundata_')]
            
            if not csv_files:
                if hasattr(self.main_window, 'logger'):
                    self.main_window.logger.log(f"No rundata CSV found in control run directory: {self.control_run_path}", "WARN")
                return {}
                
            # Use the first (or only) CSV file
            csv_path = os.path.join(self.control_run_path, csv_files[0])
            
            # Read the CSV file
            control_data = defaultdict(lambda: {'time': [], 'value': []})
            
            # First pass: collect all timestamps to find the start time
            all_timestamps = []
            rows_list = []
            
            with open(csv_path, 'r', newline='') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    try:
                        timestamp = float(row['timestamp'])
                        all_timestamps.append(timestamp)
                        rows_list.append(row)
                    except (ValueError, KeyError):
                        continue
            
            # Find the start time (minimum timestamp)
            if not all_timestamps:
                return {}
            
            start_time = min(all_timestamps)
            
            # Second pass: convert to relative time and apply offset
            for row in rows_list:
                try:
                    # Convert to relative time (elapsed seconds since start)
                    timestamp = float(row['timestamp'])
                    elapsed_time = timestamp - start_time
                    # Apply user-defined time offset
                    elapsed_time += self.time_offset
                    
                    # Process each sensor column
                    for key, value in row.items():
                        if key != 'timestamp':
                            try:
                                float_value = float(value)
                                # Add '_ctrl' suffix to make the key unique
                                ctrl_key = f"{key}_ctrl"
                                control_data[ctrl_key]['time'].append(elapsed_time)
                                control_data[ctrl_key]['value'].append(float_value)
                            except ValueError:
                                continue  # Skip non-numeric values
                except (ValueError, KeyError):
                    continue  # Skip rows with invalid timestamp
                        
            # Cache the loaded data
            self.control_run_data = dict(control_data)
            
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Loaded control run data from {csv_path} with offset {self.time_offset}s ({len(self.control_run_data)} sensors)", "INFO")
                
            return self.control_run_data
            
        except Exception as e:
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Error loading control run data: {e}", "ERROR")
            return {}
    
    def save_control_run_config(self, run_dir):
        """
        Save control run configuration to the run directory
        
        Args:
            run_dir: Path to the run directory where config should be saved
        """
        if not self.control_run_path:
            # No control run configured, nothing to save
            return
            
        config = {
            "control_run_path": self.control_run_path,
            "control_run_name": self.control_run_name,
            "time_offset": self.time_offset
        }
        
        config_path = os.path.join(run_dir, "control_run_config.json")
        
        try:
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=4)
                
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Saved control run config to {config_path}", "INFO")
                
        except Exception as e:
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Error saving control run config: {e}", "ERROR")
    
    def load_control_run_config(self, run_dir):
        """
        Load control run configuration from the run directory
        
        Args:
            run_dir: Path to the run directory to load config from
            
        Returns:
            True if config was loaded successfully, False otherwise
        """
        config_path = os.path.join(run_dir, "control_run_config.json")
        
        if not os.path.exists(config_path):
            return False
            
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                
            self.control_run_path = config.get("control_run_path")
            self.control_run_name = config.get("control_run_name")
            self.time_offset = config.get("time_offset", 0.0)
            
            # Clear cached data
            self.control_run_data = {}
            
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Loaded control run config from {config_path}", "INFO")
                
            # Emit signal that control run has changed
            self.control_run_changed.emit()
            
            return True
            
        except Exception as e:
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Error loading control run config: {e}", "ERROR")
            return False
    
    def copy_control_run_data_to_run(self, target_run_dir):
        """
        Copy control run CSV data to the target run directory for export/archival
        
        Args:
            target_run_dir: Path to the run directory where control data should be copied
        """
        if not self.control_run_path or not os.path.exists(self.control_run_path):
            return
            
        try:
            # Find the CSV file in the control run directory
            csv_files = [f for f in os.listdir(self.control_run_path) 
                        if f.endswith('.csv') and f.startswith('rundata_')]
            
            if not csv_files:
                if hasattr(self.main_window, 'logger'):
                    self.main_window.logger.log("No rundata CSV found in control run to copy", "WARN")
                return
                
            # Copy the CSV file with a special name
            source_csv = os.path.join(self.control_run_path, csv_files[0])
            target_csv = os.path.join(target_run_dir, "control_run_data.csv")
            
            shutil.copy2(source_csv, target_csv)
            
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Copied control run data to {target_csv}", "INFO")
                
        except Exception as e:
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Error copying control run data: {e}", "ERROR")
    
    def has_control_run_configured(self):
        """
        Check if a control run is currently configured
        
        Returns:
            True if control run is configured, False otherwise
        """
        return self.control_run_path is not None and os.path.exists(self.control_run_path)
    
    def clear_control_run(self):
        """Clear the current control run configuration"""
        self.control_run_path = None
        self.control_run_name = None
        self.time_offset = 0.0
        self.control_run_data = {}
        
        if hasattr(self.main_window, 'logger'):
            self.main_window.logger.log("Control run configuration cleared", "INFO")
        
        # Emit signal that control run has changed
        # This will trigger on_control_run_changed_update which updates dropdowns and graph
        self.control_run_changed.emit()
    
    def get_control_run_sensors(self):
        """
        Get list of sensors from the control run
        
        Returns:
            List of tuples: [(sensor_key_with_ctrl_suffix, sensor_name), ...]
            The sensor_key has '_ctrl' suffix to distinguish from current run sensors
        """
        if not self.control_run_path or not os.path.exists(self.control_run_path):
            return []
            
        try:
            # Find the CSV file in the control run directory
            csv_files = [f for f in os.listdir(self.control_run_path) 
                        if f.endswith('.csv') and f.startswith('rundata_')]
            
            if not csv_files:
                return []
                
            # Use the first (or only) CSV file
            csv_path = os.path.join(self.control_run_path, csv_files[0])
            
            # Read the CSV header to get sensor names
            sensors = []
            with open(csv_path, 'r', newline='') as csvfile:
                reader = csv.DictReader(csvfile)
                headers = reader.fieldnames
                
                # Skip 'timestamp' column
                for header in headers:
                    if header != 'timestamp':
                        # Add '_ctrl' suffix to the key to make it unique
                        # This allows control sensors to be selected independently
                        sensor_key = f"{header}_ctrl"
                        sensor_name = header
                        sensors.append((sensor_key, sensor_name))
                        
            return sensors
            
        except Exception as e:
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Error getting control run sensors: {e}", "ERROR")
            return []

