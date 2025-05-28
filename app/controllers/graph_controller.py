"""
Graph Controller

Manages graph visualization and data plotting.
"""

import pyqtgraph as pg
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QGraphicsRectItem, QGraphicsLineItem # Import necessary QtWidgets
import time
from collections import defaultdict
import numpy as np # Import numpy for efficient filtering
import re # Import regular expressions
from scipy.fft import fft, fftfreq
from PyQt6.QtCore import QTimer # Import QTimer

class GraphController:
    """Controls graph visualization and plotting"""
    
    def __init__(self, main_window, sensor_controller, settings_model):
        """
        Initialize the graph controller
        
        Args:
            main_window: Main application window
            sensor_controller: The application's SensorController instance
            settings_model: The application's SettingsModel instance
        """
        self.main_window = main_window
        self.sensor_controller = sensor_controller # Store sensor controller
        self.settings_model = settings_model     # Store settings model
        self.live_plotting_active = False
        self.dashboard_start_time = None
        # Stores {sensor_id: {'x': [], 'y': [], 'plot_item': PlotDataItem, 'name': str}}
        self.dashboard_plot_data = {} 
        self.dashboard_graph_widget = None # Will be set in start_live_dashboard_update
        self.last_plot_update_time = 0 # Time of the last visual plot update
        self.plot_update_interval = 0.2 # Update plot visuals every 200ms
        
        # Timer for main graph live updates
        self.main_graph_update_timer = QTimer()
        self.main_graph_update_timer.setInterval(1500) # Update every 1.5 seconds
        self.main_graph_update_timer.timeout.connect(self.update_graph) 
        
    def connect_signals(self):
        """Connect UI signals to controller methods"""
        if hasattr(self.main_window, 'graph_type_combo'):
            self.main_window.graph_type_combo.currentIndexChanged.connect(self.on_graph_type_changed)
            self.main_window.graph_primary_sensor.currentIndexChanged.connect(self.update_graph)
            self.main_window.graph_secondary_sensor.currentIndexChanged.connect(self.update_graph)
            self.main_window.graph_timespan.currentIndexChanged.connect(self.on_timespan_changed)
            self.main_window.dashboard_timespan.currentIndexChanged.connect(self.on_dashboard_timespan_changed)
    
    def on_graph_type_changed(self):
        """Handle graph type change"""
        if hasattr(self.main_window, 'update_graph_ui_elements'):
            self.main_window.update_graph_ui_elements()
        self.update_graph()
    
    def on_timespan_changed(self):
        """Handle timespan change for main graph"""
        self.update_graph()
    
    def on_dashboard_timespan_changed(self):
        """Handle timespan change for dashboard graph"""
        # Update the visuals immediately based on the new timespan
        if self.live_plotting_active:
            self._update_all_plot_visuals()
        else:
            # If not live plotting, update might involve reloading historical data
            # For now, just call the original method
            self.update_dashboard_graph()
    
    def update_graph(self):
        """Update the main graph"""
        # Only update if data collection is active
        if not hasattr(self.main_window, 'data_collection_controller') or not self.main_window.data_collection_controller.collecting_data:
            print("DEBUG: Skipping main graph update as data collection is not active")
            return
        if hasattr(self.main_window, 'logger'):
            self.main_window.logger.debug("Updating main graph (triggered by timer or UI change)")
        # Trigger the main window's update method which gathers params and calls update_specific_graph
        if hasattr(self.main_window, 'update_graph'):
            self.main_window.update_graph()
            # --- Ensure all lines have the correct line width after update ---
            if hasattr(self.main_window, 'plot_line_width') and hasattr(self.main_window, 'graph_widget'):
                line_width = self.main_window.plot_line_width.value()
                for item in self.main_window.graph_widget.listDataItems():
                    pen = item.opts.get('pen', None)
                    if pen is not None:
                        if isinstance(pen, str):
                            color = pen
                        else:
                            color = pen.color()
                        if hasattr(item, "setPen"):
                            item.setPen(pg.mkPen(color=color, width=line_width))

    def update_dashboard_graph(self):
        """Update the dashboard graph"""
        if hasattr(self.main_window, 'logger'):
            self.main_window.logger.debug("Updating dashboard graph")

        # If live plotting is active, don't overwrite the live plot when tab is changed
        if self.live_plotting_active:
             return
             
        # TODO: Implement logic to display historical data if needed when not live plotting
        if self.dashboard_graph_widget:
             self.dashboard_graph_widget.clear()
             # Optionally add placeholder text
             self.dashboard_graph_widget.setLabel('bottom', 'Time (s)')
             self.dashboard_graph_widget.setLabel('left', 'Value')
             self.dashboard_graph_widget.addLegend()

    def start_live_dashboard_update(self, start_time):
        """Prepare and start live plotting on the dashboard graph."""
        self.main_window.logger.log("Starting live dashboard graph updates.", "INFO")
        print(f"DEBUG: start_live_dashboard_update called with start_time: {start_time}")
        
        if not hasattr(self.main_window, 'dashboard_graph_widget'):
            self.main_window.logger.log("Dashboard graph widget not found.", "ERROR")
            print("ERROR: Dashboard graph widget not found.")
            return
            
        self.dashboard_graph_widget = self.main_window.dashboard_graph_widget    
        self.dashboard_graph_widget.clear()
        self.dashboard_plot_data.clear()
        self.dashboard_start_time = start_time
        self.live_plotting_active = True
        print(f"DEBUG: Set live_plotting_active={self.live_plotting_active}, dashboard_start_time={self.dashboard_start_time}")

        # Set up axes and legend
        print("DEBUG: Setting up dashboard graph axes and legend")
        self.dashboard_graph_widget.setLabel('bottom', 'Time (s)')
        self.dashboard_graph_widget.setLabel('left', 'Value') # Generic Y-label
        # Clear any existing legend first
        if hasattr(self.dashboard_graph_widget, 'legend') and self.dashboard_graph_widget.legend is not None:
            self.dashboard_graph_widget.legend.scene().removeItem(self.dashboard_graph_widget.legend)
        self.dashboard_graph_widget.addLegend()
        self.dashboard_graph_widget.showGrid(x=True, y=True, alpha=0.3)
        
        # Set auto range on the plot so it updates as new data comes in
        self.dashboard_graph_widget.enableAutoRange()
        # Make sure viewbox is set to auto-range for both axes
        view_box = self.dashboard_graph_widget.getViewBox()
        if view_box:
            view_box.setAutoVisible(x=True, y=True)
            view_box.enableAutoRange(axis='xy', enable=True)
        
        # Set antialiasing for smoother lines
        self.dashboard_graph_widget.setAntialiasing(True)

        # --- Apply formatting to dashboard graph ---
        if hasattr(self.main_window, 'apply_dashboard_plot_formatting'):
            self.main_window.apply_dashboard_plot_formatting()
        elif hasattr(self, 'apply_dashboard_plot_formatting'):
            self.apply_dashboard_plot_formatting()

        # Get sensors to plot from SensorController
        if not hasattr(self.main_window, 'sensor_controller'):
             self.main_window.logger.log("Sensor controller not found.", "ERROR")
             print("ERROR: Sensor controller not found.")
             self.live_plotting_active = False # Cannot proceed
             return
             
        # Access the sensors directly from the sensor_controller's sensors list
        sensors = self.main_window.sensor_controller.sensors
        print(f"DEBUG: Found {len(sensors)} sensors to check for graphing")
        self.main_window.logger.log(f"Found {len(sensors)} sensors to check for graphing", "INFO")
        
        sensors_added = 0
        self.dashboard_plot_data.clear() # Ensure it's clear before adding new plots
        
        # Get line width from UI
        line_width = 2
        if hasattr(self.main_window, 'plot_line_width'):
            line_width = self.main_window.plot_line_width.value()
        
        for sensor in sensors:
            show_in_graph = getattr(sensor, 'show_in_graph', False)
            enabled = getattr(sensor, 'enabled', False)
            if show_in_graph and enabled:
                color_str = getattr(sensor, 'color', '#FFFFFF')
                sensor_name_for_legend = getattr(sensor, 'name', 'Unknown Sensor')
                interface_type = getattr(sensor, 'interface_type', 'Unknown')

                # --- Determine the CORRECT key for matching incoming data --- 
                sensor_key_for_data = None
                if interface_type == "Arduino":
                    # Use the sensor name for Arduino data keys (address is often empty)
                    sensor_key_for_data = getattr(sensor, 'name', None)
                    if not sensor_key_for_data:
                        print(f"WARNING GRAPH: Arduino sensor '{sensor_name_for_legend}' has no name defined. Skipping plot.")
                        continue
                elif interface_type == "LabJack":
                    # LabJack uses channel name (port/address field in SensorModel)
                    sensor_key_for_data = getattr(sensor, 'port', None) # Assuming 'port' holds the channel name
                    if not sensor_key_for_data:
                        print(f"WARNING GRAPH: LabJack sensor '{sensor_name_for_legend}' has no port/channel defined. Skipping plot.")
                        continue
                elif interface_type == "OtherSerial":
                    # OtherSerial data is keyed by the user-defined sensor name
                    sensor_key_for_data = sensor_name_for_legend 
                else:
                    print(f"WARNING GRAPH: Unknown interface type '{interface_type}' for sensor '{sensor_name_for_legend}'. Skipping plot.")
                    continue
                # --------------------------------------------------------

                print(f"DEBUG: Adding sensor to graph: Name='{sensor_name_for_legend}', KeyForData='{sensor_key_for_data}', Type='{interface_type}', Color='{color_str}'")
                
                try:
                    color = QColor(color_str)
                    pen = pg.mkPen(color=color, width=line_width)
                    # Create plot item using sensor_name_for_legend for the legend
                    plot_item = self.dashboard_graph_widget.plot([], [], pen=pen, name=sensor_name_for_legend)
                    # Store plot data using sensor_key_for_data as the dictionary key
                    self.dashboard_plot_data[sensor_key_for_data] = {
                        'x': [], 
                        'y': [], 
                        'plot_item': plot_item,
                        'name': sensor_name_for_legend, # Keep user-defined name for reference
                        'color': color_str
                    }
                    sensors_added += 1
                    print(f"DEBUG: Successfully added plot for sensor '{sensor_name_for_legend}' (key: '{sensor_key_for_data}').")
                    self.main_window.logger.log(f"Added plot for sensor '{sensor_name_for_legend}' (key: '{sensor_key_for_data}') to dashboard.", "INFO")
                except Exception as e:
                    print(f"ERROR: Failed to add sensor {sensor_name_for_legend} to graph: {e}")
                    self.main_window.logger.log(f"Error adding sensor {sensor_name_for_legend} to graph: {e}. Color string: {color_str}", "ERROR")
                    import traceback
                    traceback_text = traceback.format_exc()
                    print(traceback_text)
                    self.main_window.logger.log(traceback_text, "ERROR")

        print(f"DEBUG: Added {sensors_added} plots. Final dashboard_plot_data keys: {list(self.dashboard_plot_data.keys())}")
        self.main_window.logger.log(f"Added {sensors_added} plots to the dashboard graph", "INFO")
        if not self.dashboard_plot_data:
            print("WARNING: No sensors configured to show in dashboard graph.")
            self.main_window.logger.log("No sensors configured to show in dashboard graph.", "WARNING")
            # Optionally add a message to the plot
            text = pg.TextItem("No sensors selected for graphing", anchor=(0.5, 0.5))
            # Adjust the position; you might need to experiment with these values
            # Or calculate based on the current view range if available
            view_box = self.dashboard_graph_widget.getViewBox()
            if view_box:
                 # Position roughly in the center
                 view_range = view_box.viewRange()
                 x_pos = view_range[0][0] + (view_range[0][1] - view_range[0][0]) / 2
                 y_pos = view_range[1][0] + (view_range[1][1] - view_range[1][0]) / 2
                 text.setPos(x_pos, y_pos)
            else: # Fallback position if view range isn't ready
                 text.setPos(0, 0) 
            self.dashboard_graph_widget.addItem(text)
            
        # --- Set up dashboard update timer to match sampling interval, but not faster than 1s ---
        update_interval_ms = 1000  # Default 1s
        if hasattr(self.main_window, 'sampling_rate_spinbox'):
            interval = self.main_window.sampling_rate_spinbox.value()
            update_interval_ms = max(int(interval * 1000), 1000)
        if not hasattr(self, 'dashboard_update_timer'):
            from PyQt6.QtCore import QTimer
            self.dashboard_update_timer = QTimer()
            self.dashboard_update_timer.timeout.connect(self._update_all_plot_visuals)
        self.dashboard_update_timer.setInterval(update_interval_ms)
        # Only start the timer if data collection is active
        if hasattr(self.main_window, 'data_collection_controller') and self.main_window.data_collection_controller.collecting_data:
            self.dashboard_update_timer.start()
            print(f"Dashboard update timer started with interval {update_interval_ms} ms")
        else:
            print(f"Dashboard update timer not started as data collection is not active")
            self.main_window.logger.log("Dashboard update timer not started: data collection not active", "INFO")

    def stop_live_dashboard_update(self):
        """Stop live plotting on the dashboard graph."""
        self.main_window.logger.log("Stopping live dashboard graph updates.", "INFO")
        self.live_plotting_active = False
        self.dashboard_start_time = None
        if hasattr(self, 'dashboard_update_timer'):
            self.dashboard_update_timer.stop()
        # Keep the plot data and items, don't clear graph here
        # User might want to see the final state
        
    def plot_new_data(self, data):
        """Plot new incoming data point(s)."""
        if not self.live_plotting_active or self.dashboard_start_time is None:
            return
            
        try:
            # ... (data source identification, plot key checks, timestamp extraction) ...
            # (Keep the previous code here for finding data source, checking plot keys, getting timestamp)
            
            # --- Check for empty plots and reinitialize if needed ---
            plot_keys = list(self.dashboard_plot_data.keys())
            if len(plot_keys) == 0:
                print("DEBUG GRAPH: No plots are set up. Attempting to reinitialize.")
                self.main_window.logger.log("No plots set up, reinitializing graph.", "WARNING")
                if hasattr(self.main_window, 'data_collection_controller') and hasattr(self.main_window.data_collection_controller, 'start_time'):
                    self.start_live_dashboard_update(self.main_window.data_collection_controller.start_time)
                return # Exit after reinit attempt
            # -----------------------------------------------------------

            # --- Timestamp handling ---
            timestamp = None
            if 'timestamp' in data:
                try:
                    timestamp = float(data['timestamp'])
                except (ValueError, TypeError):
                    timestamp = time.time()
            else:
                timestamp = time.time()
                
            if self.dashboard_start_time is None:
                print(f"DEBUG GRAPH: dashboard_start_time was None. Setting it now to {timestamp}")
                self.dashboard_start_time = float(timestamp)
            elif not isinstance(self.dashboard_start_time, (float, int)):
                try:
                    self.dashboard_start_time = float(self.dashboard_start_time)
                except (ValueError, TypeError):
                    print(f"DEBUG GRAPH: dashboard_start_time invalid: {self.dashboard_start_time}. Resetting.")
                    self.dashboard_start_time = float(timestamp)
            
            # Ensure timestamp is float for arithmetic
            try:
                timestamp = float(timestamp)
            except (ValueError, TypeError):
                timestamp = time.time()
            
            elapsed_time = timestamp - self.dashboard_start_time
            if elapsed_time < 0:
                 print(f"WARNING GRAPH: Negative elapsed time detected ({elapsed_time:.2f}s). Using 0.")
                 elapsed_time = 0.0
            # --------------------------

            # Process data points and add to internal buffers
            keys_to_process = [k for k in data.keys() if k != 'timestamp']
            data_added = False
            for key in keys_to_process:
                if key.startswith('_') or key.endswith('_timestamp'): 
                    continue
                value = data[key]
                try:
                    if isinstance(value, str):
                        value = float(value)
                    elif not isinstance(value, (int, float)):
                        continue
                    # Add data point internally
                    if self._add_data_point(key, value, elapsed_time):
                        data_added = True
                except (ValueError, TypeError):
                    continue
            
            # --- Throttle visual updates --- 
            current_time = time.time()
            if data_added and (current_time - self.last_plot_update_time > self.plot_update_interval):
                # print(f"DEBUG GRAPH: Performing visual update. Time since last: {current_time - self.last_plot_update_time:.2f}s") # Optional debug
                self._update_all_plot_visuals()
                self.last_plot_update_time = current_time
            # ------------------------------- 
            
        except Exception as e:
            print(f"ERROR GRAPH: Error plotting new data: {e}")
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Error plotting new data: {e}", "ERROR")
                import traceback
                traceback_text = traceback.format_exc()
                print(traceback_text)
                self.main_window.logger.log(traceback_text, "ERROR")

    def _add_data_point(self, sensor_id, value, elapsed_time):
        """Adds a single data point to the internal buffer for a sensor.
           Now uses direct key matching based on sensor_id (channel name).
           Returns True if data was added, False otherwise.
        """
        plot_info = None
        matched_key = None
        
        # --- Direct matching first --- 
        if sensor_id in self.dashboard_plot_data:
            plot_info = self.dashboard_plot_data[sensor_id]
            matched_key = sensor_id
            print(f"DEBUG GRAPH: Direct match found for sensor_id='{sensor_id}'")
        # Try for OtherSerial sensors which may have prefixes
        elif sensor_id.startswith("other_serial_"):
            # Extract the actual sensor name from the prefixed key
            unprefixed_key = sensor_id[len("other_serial_"):]
            if unprefixed_key in self.dashboard_plot_data:
                plot_info = self.dashboard_plot_data[unprefixed_key]
                matched_key = unprefixed_key
                print(f"DEBUG GRAPH: OtherSerial match found: prefixed_key='{sensor_id}', unprefixed='{unprefixed_key}'")
        # Check for other prefixed keys like arduino_ or labjack_
        elif any(sensor_id.startswith(prefix) for prefix in ["arduino_", "labjack_"]):
            # Extract the actual sensor name from the prefixed key
            if sensor_id.startswith("arduino_"):
                unprefixed_key = sensor_id[len("arduino_"):]
            elif sensor_id.startswith("labjack_"):
                unprefixed_key = sensor_id[len("labjack_"):]
            
            if unprefixed_key in self.dashboard_plot_data:
                plot_info = self.dashboard_plot_data[unprefixed_key]
                matched_key = unprefixed_key
                print(f"DEBUG GRAPH: Prefix match found: prefixed_key='{sensor_id}', unprefixed='{unprefixed_key}'")
            
        if plot_info:
            plot_info['x'].append(elapsed_time)
            plot_info['y'].append(value)
            return True
            
        if "other_serial" in sensor_id:
            print(f"DEBUG GRAPH: *** No plot found *** for OtherSerial sensor: {sensor_id}")
            # Print dashboard plot keys for debugging
            print(f"DEBUG GRAPH: Available plot keys: {list(self.dashboard_plot_data.keys())}")
        return False

    def _update_all_plot_visuals(self):
        """Updates the setData for all plots based on current buffers and selected timespan, and updates legend with current sensor values."""
        # Only update visuals if data collection is active
        if not hasattr(self.main_window, 'data_collection_controller') or not self.main_window.data_collection_controller.collecting_data:
            print("DEBUG: Skipping graph visual update as data collection is not active")
            return
        
        if not hasattr(self.main_window, 'dashboard_timespan'):
            print("WARNING GRAPH: dashboard_timespan widget not found. Cannot apply timespan filter.")
            return
            
        selected_timespan_str = self.main_window.dashboard_timespan.currentText()
        timespan_seconds = self._parse_timespan_string(selected_timespan_str)
        
        now = time.time()
        current_elapsed_time = now - self.dashboard_start_time if self.dashboard_start_time else 0

        min_time = -np.inf # Default to show all if timespan is invalid or "All"
        if timespan_seconds is not None:
            max_time = current_elapsed_time
            all_x = [t for plot_info in self.dashboard_plot_data.values() for t in plot_info.get('x', [])]
            if all_x:
                max_time = max(max(all_x), current_elapsed_time)
            min_time = max_time - timespan_seconds

        # --- Update plot data and legend names with current values ---
        for sensor_id, plot_info in self.dashboard_plot_data.items():
            if plot_info.get('plot_item') and plot_info.get('x') and plot_info.get('y'):
                try:
                    x_data = np.array(plot_info['x'])
                    y_data = np.array(plot_info['y'])
                    indices = np.where(x_data >= min_time)[0]
                    if len(indices) > 0:
                        filtered_x = x_data[indices]
                        filtered_y = y_data[indices]
                        plot_info['plot_item'].setData(filtered_x, filtered_y)
                    else:
                        plot_info['plot_item'].setData([], [])
                except Exception as e:
                    print(f"ERROR GRAPH: Failed to filter/update plot for {sensor_id}: {e}")
                    plot_info['plot_item'].setData(plot_info['x'], plot_info['y'])

            # --- Update legend name with current value ---
            # Find the sensor object by name (for Arduino/OtherSerial) or port (for LabJack)
            sensor_obj = None
            if hasattr(self.main_window, 'sensor_controller'):
                for sensor in self.main_window.sensor_controller.sensors:
                    if (getattr(sensor, 'name', None) == plot_info['name']) or (getattr(sensor, 'port', None) == sensor_id):
                        sensor_obj = sensor
                        break
            value_str = "N/A"
            if sensor_obj is not None:
                val = getattr(sensor_obj, 'current_value', None)
                if val is not None:
                    try:
                        value_str = f"{val:.2f}"
                    except Exception:
                        value_str = str(val)
                unit = getattr(sensor_obj, 'unit', None)
                if unit:
                    value_str = f"{value_str} {unit}"
            legend_name = f"{plot_info['name']} ({value_str})"
            # Update the legend entry (PyQtGraph does not support direct legend label update, so we update the plot item's name)
            plot_info['plot_item'].opts['name'] = legend_name
            # If legend is visible, force update
            if hasattr(self.dashboard_graph_widget, 'legend') and self.dashboard_graph_widget.legend is not None:
                self.dashboard_graph_widget.legend.updateItem(plot_info['plot_item'])

    def _parse_timespan_string(self, timespan_str):
        """Parse timespan string (e.g., '10s', '5min', '1h', 'All') into seconds."""
        if timespan_str.lower() == "all":
            return None # Indicate show all data

        # Use regex to extract number and unit (s, min, h)
        match = re.match(r"(\d+)\s*(s|min|h)$", timespan_str, re.IGNORECASE)
        
        if not match:
            print(f"WARNING GRAPH: Could not parse timespan string: {timespan_str}")
            return None # Fallback to show all if parsing fails

        value = int(match.group(1))
        unit = match.group(2).lower()

        if unit == 's':
            return value
        elif unit == 'min':
            return value * 60
        elif unit == 'h':
            return value * 3600
        else:
            # This case should not be reached due to regex matching
            print(f"WARNING GRAPH: Unknown timespan unit after regex match: {unit}")
            return None

    def update_specific_graph(self, graph_widget, primary_sensor_key, secondary_sensor_key, timespan, graph_type, multi_sensor_keys, window_size, histogram_bins, is_main_graph=False):
        """Update a specific graph widget based on selected parameters using historical keys."""
        if not graph_widget:
            self.main_window.logger.error("update_specific_graph called with invalid graph_widget")
            return

        if not hasattr(self.main_window, 'data_collection_controller') or not hasattr(self.main_window, 'sensor_controller'):
            self.main_window.logger.error("DataCollectionController or SensorController not found for updating graph")
            return
            
        # Use sensor controller to get display names from keys for logging/titles
        primary_sensor_name = self.main_window.sensor_controller.get_sensor_name_by_historical_key(primary_sensor_key) if primary_sensor_key else "None"
        secondary_sensor_name = self.main_window.sensor_controller.get_sensor_name_by_historical_key(secondary_sensor_key) if secondary_sensor_key else "None"
        
        self.main_window.logger.info(f"Updating graph: Type='{graph_type}', Primary='{primary_sensor_name}' (key:{primary_sensor_key}), Timespan='{timespan}'")

        # Clear the graph and add legend
        graph_widget.clear()
        if hasattr(graph_widget, 'legend') and graph_widget.legend is not None:
            try:
                graph_widget.legend.scene().removeItem(graph_widget.legend)
            except Exception as e:
                self.main_window.logger.warning(f"Could not remove existing legend: {e}")
        legend = graph_widget.addLegend()
        graph_widget.showGrid(x=True, y=True, alpha=0.3)
        graph_widget.setLabel('bottom', 'Elapsed Time (s)')
        graph_widget.setLabel('left', 'Value') # Default Y label

        # --- Ensure Y Axis is visible by default before specific types hide it ---
        graph_widget.getAxis('left').setWidth() # Reset width to default
        graph_widget.getAxis('left').setStyle(showValues=True) # Reset show values
        # ---------------------------------------------------------------------

        # Always hide legend for these types
        legendless_types = ["Fourier Analysis", "Histogram", "Correlation Analysis"]
        if graph_type in legendless_types:
            legend.setVisible(False)
        else:
            legend.setVisible(True)

        # Determine which timespan we're working with
        timespan_seconds = None
        if timespan:
            if timespan.lower() == "all":
                timespan_seconds = None  # None means all data
            else:
                # Call the internal parsing function to get timespan in seconds
                timespan_seconds = self._parse_timespan_string(timespan)
                
        # --- Data Fetching --- 
        # Determine required sensors using KEYS
        required_sensor_keys = []
        
        # Always include the primary sensor if specified
        if primary_sensor_key:
            required_sensor_keys.append(primary_sensor_key)
            
        # For graph types that need secondary sensor
        if secondary_sensor_key and graph_type in ["Temperature Difference", "Correlation Analysis"]:
            required_sensor_keys.append(secondary_sensor_key)
            
        # For Standard Time Series with multi-sensor selection
        if graph_type == "Standard Time Series" and multi_sensor_keys:
            required_sensor_keys.extend(multi_sensor_keys)
            
        # Remove duplicates and None values
        required_sensor_keys = list(set(filter(None, required_sensor_keys)))
        if not required_sensor_keys:
            graph_widget.setTitle("No sensor selected")
            return
        
        # Debug logging for required sensor keys
        print(f"DEBUG GRAPH: Required sensor keys for graph: {required_sensor_keys}")
        
        # Check for any OtherSerial sensors in the required keys
        other_serial_keys = [k for k in required_sensor_keys if 'other_serial' in k]
        if other_serial_keys:
            print(f"DEBUG GRAPH: OtherSerial sensors in required keys: {other_serial_keys}")
        
        # Fetch data (assuming a method in DataCollectionController)
        try:
            # This method needs to exist and return data in a suitable format, 
            # e.g., {sensor_id: {'time': [t1, t2,...], 'value': [v1, v2,...]}}
            historical_data = self.main_window.data_collection_controller.get_historical_data(
                sensor_ids=required_sensor_keys, # Use KEYS here
                timespan_seconds=timespan_seconds
            )
            
            # Debug any OtherSerial data retrieved
            for key, data in historical_data.items():
                if 'other_serial' in key:
                    print(f"DEBUG GRAPH: Found OtherSerial data for key '{key}': {len(data['time'])} points")
                    if len(data['time']) > 0:
                        print(f"DEBUG GRAPH: First few values: {data['value'][:5]}")
                        
        except AttributeError:
            self.main_window.logger.error("'get_historical_data' method not found in DataCollectionController.")
            graph_widget.setTitle("Error: Could not fetch data")
            return
        except Exception as e:
            self.main_window.logger.error(f"Error fetching historical data: {e}")
            graph_widget.setTitle("Error fetching data")
            return

        if not historical_data:
            graph_widget.setTitle(f"No data available for selected sensors/timespan")
            self.main_window.logger.warning(f"No historical data returned for keys: {required_sensor_keys}, timespan: {timespan}")
            return

        # Apply current formatting settings before plotting
        self.apply_plot_formatting() 

        # --- Plotting Logic --- 
        try:
            if graph_type == "Standard Time Series":
                graph_widget.setTitle(f"Time Series - Timespan: {timespan}")
                graph_widget.setLabel('left', 'Sensor Value')
                
                sensors_keys_to_plot = [primary_sensor_key] + multi_sensor_keys
                sensors_keys_to_plot = list(set(filter(None, sensors_keys_to_plot))) # Unique, non-empty keys
                
                for sensor_key in sensors_keys_to_plot:
                    if sensor_key in historical_data and len(historical_data[sensor_key]['time']) > 0:
                        data = historical_data[sensor_key]
                        times = np.array(data['time'], dtype=float)
                        values = np.array(data['value'], dtype=float)
                        sensor_name = self.main_window.sensor_controller.get_sensor_name_by_historical_key(sensor_key)
                        sensor_obj = self.main_window.sensor_controller.get_sensor_by_name(sensor_name)
                        color = getattr(sensor_obj, 'color', '#FFFFFF') if sensor_obj else '#FFFFFF'
                        pen = pg.mkPen(color=color, width=getattr(self.main_window, 'plot_line_width_value', 2))
                        # --- Append latest value to legend ---
                        value_str = "N/A"
                        if sensor_obj is not None:
                            if len(values) > 0:
                                try:
                                    value_str = f"{values[-1]:.2f}"
                                except Exception:
                                    value_str = str(values[-1])
                            unit = getattr(sensor_obj, 'unit', None)
                            if unit:
                                value_str = f"{value_str} {unit}"
                        legend_name = f"{sensor_name} ({value_str})"
                        graph_widget.plot(times, values, pen=pen, name=legend_name)
                    else:
                         self.main_window.logger.warning(f"No data found for sensor key '{sensor_key}' in Standard Time Series plot")

            elif graph_type == "Temperature Difference":
                graph_widget.setTitle(f"Temperature Difference ({primary_sensor_name} - {secondary_sensor_name}) - Timespan: {timespan}")
                graph_widget.setLabel('left', 'Difference (°C or unit)')
                if primary_sensor_key and secondary_sensor_key and primary_sensor_key in historical_data and secondary_sensor_key in historical_data:
                    data1 = historical_data[primary_sensor_key]
                    data2 = historical_data[secondary_sensor_key]
                    
                    # Ensure data is numerical numpy arrays
                    t1 = np.array(data1['time'], dtype=float)
                    v1 = np.array(data1['value'], dtype=float)
                    t2 = np.array(data2['time'], dtype=float)
                    v2 = np.array(data2['value'], dtype=float)
                    
                    # Align data based on timestamps (simple interpolation)
                    time_combined = np.unique(np.concatenate((t1, t2)))
                    time_combined.sort()
                    
                    # Ensure we have enough points to interpolate
                    if len(t1) < 2 or len(t2) < 2:
                         graph_widget.setTitle("Not enough data points on one or both sensors for difference plot")
                         return
                    
                    # Interpolate data1 and data2 onto the combined time axis
                    val1_interp = np.interp(time_combined, t1, v1)
                    val2_interp = np.interp(time_combined, t2, v2)
                    
                    difference = val1_interp - val2_interp
                    pen = pg.mkPen(color='c', width=getattr(self.main_window, 'plot_line_width_value', 2))
                    graph_widget.plot(time_combined, difference, pen=pen, name=f"{primary_sensor_name}-{secondary_sensor_name}") # Use names in legend
                else:
                    graph_widget.setTitle("Select two valid sensors for difference plot")

            elif graph_type == "Rate of Change (dT/dt)":
                graph_widget.setTitle(f"Rate of Change ({primary_sensor_name}) - Timespan: {timespan}")
                graph_widget.setLabel('left', 'Rate (unit/s)')
                if primary_sensor_key and primary_sensor_key in historical_data and len(historical_data[primary_sensor_key]['time']) > 1:
                    data = historical_data[primary_sensor_key]
                    # Ensure data is numerical numpy arrays
                    times = np.array(data['time'], dtype=float)
                    values = np.array(data['value'], dtype=float)
                    
                    # Calculate gradient (rate of change)
                    rate = np.gradient(values, times)
                    pen = pg.mkPen(color='m', width=getattr(self.main_window, 'plot_line_width_value', 2))
                    graph_widget.plot(times, rate, pen=pen, name=f"d({primary_sensor_name})/dt") # Use name in legend
                else:
                     graph_widget.setTitle("Select a valid sensor with at least 2 data points for rate plot")

            elif graph_type == "Moving Average":
                graph_widget.setTitle(f"Moving Average ({primary_sensor_name}, Window: {window_size}) - Timespan: {timespan}")
                graph_widget.setLabel('left', 'Smoothed Value')
                if primary_sensor_key and primary_sensor_key in historical_data and window_size is not None and window_size > 1 and len(historical_data[primary_sensor_key]['time']) >= window_size:
                    data = historical_data[primary_sensor_key]
                    # Ensure data is numerical numpy arrays
                    times = np.array(data['time'], dtype=float)
                    values = np.array(data['value'], dtype=float)

                    # Filter out NaN or inf values before processing
                    valid_mask = np.isfinite(values)
                    times = times[valid_mask]
                    values = values[valid_mask]

                    if len(times) < window_size:
                         graph_widget.setTitle(f"Not enough data points ({len(times)}) for window size {window_size}")
                         return

                    # Calculate moving average
                    # Use pandas for robust rolling calculations if available, otherwise numpy
                    try:
                        import pandas as pd
                        s = pd.Series(values)
                        moving_avg = s.rolling(window=window_size, center=True).mean().to_numpy()
                        moving_std = s.rolling(window=window_size, center=True).std().to_numpy()
                        # For centered window, the time axis doesn't need slicing like 'valid' numpy convolve
                        time_avg = times
                        # Rolling calculation introduces NaNs at edges
                        nan_mask = ~np.isnan(moving_avg)
                        time_avg = time_avg[nan_mask]
                        moving_avg = moving_avg[nan_mask]
                        moving_std = moving_std[nan_mask] # Ensure std is aligned
                    except ImportError:
                        # Fallback to numpy convolve for average (less robust for std)
                        weights = np.ones(window_size) / window_size
                        moving_avg = np.convolve(values, weights, mode='valid')

                        # Approximate moving std using stride tricks (more complex)
                        shape = values.shape[:-1] + (values.shape[-1] - window_size + 1, window_size)
                        strides = values.strides + (values.strides[-1],)
                        rolling_vals = np.lib.stride_tricks.as_strided(values, shape=shape, strides=strides)
                        moving_std = np.std(rolling_vals, axis=1)

                        # Adjust time axis to match the output length of 'valid' convolution
                        start_idx = (window_size - 1) // 2
                        end_idx = len(times) - (window_size - 1) // 2 - (window_size % 2 == 0) # Adjust for even/odd window size
                        time_avg = times[start_idx:end_idx]
                        # Ensure time_avg matches length of moving_avg/std
                        if len(time_avg) > len(moving_avg):
                            time_avg = time_avg[:len(moving_avg)]
                        elif len(moving_avg) > len(time_avg):
                            moving_avg = moving_avg[:len(time_avg)]
                            moving_std = moving_std[:len(time_avg)] # Align std as well

                    # Plotting
                    line_width = getattr(self.main_window, 'plot_line_width_value', 2)
                    avg_pen = pg.mkPen(color='y', width=line_width)
                    std_pen = pg.mkPen(color=(255, 255, 0, 100), width=1, style=pg.QtCore.Qt.PenStyle.DashLine) # Use pg.QtCore.Qt

                    # Plot average
                    graph_widget.plot(time_avg, moving_avg, pen=avg_pen, name=f"Avg({primary_sensor_name}, N={window_size})")

                    # Plot +/- 1 Standard Deviation Lines
                    graph_widget.plot(time_avg, moving_avg + moving_std, pen=std_pen, name=f"+1 Std Dev")
                    graph_widget.plot(time_avg, moving_avg - moving_std, pen=std_pen, name=f"-1 Std Dev")

                    # Optional: Fill between standard deviations (can be visually busy)
                    # fill_brush = pg.mkBrush(255, 255, 0, 50) # Semi-transparent yellow
                    # fill = pg.FillBetweenItem(curve1=upper_std_line, curve2=lower_std_line, brush=fill_brush)
                    # graph_widget.addItem(fill)

                else:
                    graph_widget.setTitle("Select sensor, ensure sufficient data and valid window size (>1) for moving average")
            
            elif graph_type == "Fourier Analysis":
                graph_widget.setTitle(f"Fourier Analysis ({primary_sensor_name}) - Timespan: {timespan}")
                graph_widget.setLabel('bottom', 'Frequency (Hz)')
                graph_widget.setLabel('left', 'Amplitude')
                legend.setVisible(False) # Legend not very useful for FFT
                if primary_sensor_key and primary_sensor_key in historical_data and len(historical_data[primary_sensor_key]['time']) > 1:
                    data = historical_data[primary_sensor_key]
                    # Ensure data is numerical numpy arrays
                    times = np.array(data['time'], dtype=float)
                    values = np.array(data['value'], dtype=float)
                    
                    n = len(values)
                    if n < 2:
                         graph_widget.setTitle("Not enough data for Fourier Analysis")
                         return
                         
                    # Calculate average sample spacing, check for validity
                    sample_spacing = np.mean(np.diff(times)) 
                    if sample_spacing <= 0 or np.isnan(sample_spacing):
                        graph_widget.setTitle("Invalid or non-uniform time data for Fourier Analysis")
                        return
                    
                    yf = fft(values)
                    xf = fftfreq(n, sample_spacing)[:n//2] # Get positive frequencies
                    
                    amplitude = 2.0/n * np.abs(yf[0:n//2])
                    
                    graph_widget.plot(xf, amplitude, pen=pg.mkPen(color='g', width=getattr(self.main_window, 'plot_line_width_value', 2)))
                else:
                    graph_widget.setTitle(f"Select a sensor with at least 2 data points for Fourier Analysis ({primary_sensor_name})") # Show name even on error

            elif graph_type == "Histogram":
                graph_widget.setTitle(f"Histogram ({primary_sensor_name}, Bins: {histogram_bins}) - Timespan: {timespan}")
                graph_widget.setLabel('bottom', 'Value Bins')
                graph_widget.setLabel('left', 'Frequency')
                legend.setVisible(False)
                if primary_sensor_key and primary_sensor_key in historical_data and histogram_bins is not None and histogram_bins > 0 and len(historical_data[primary_sensor_key]['value']) > 0:
                    # Ensure data is numerical numpy arrays
                    values = np.array(historical_data[primary_sensor_key]['value'], dtype=float)
                    
                    # Filter out NaN or inf values before histogramming
                    values = values[np.isfinite(values)]
                    
                    if len(values) == 0:
                        graph_widget.setTitle(f"No valid numerical data for Histogram ({primary_sensor_name})")
                        return
                    
                    hist, bin_edges = np.histogram(values, bins=histogram_bins)
                    
                    # Create bar graph
                    bar_graph = pg.BarGraphItem(x=bin_edges[:-1], height=hist, width=(bin_edges[1]-bin_edges[0])*0.9, brush='b')
                    graph_widget.addItem(bar_graph)
                    # Set Y range manually if needed, as autorange might be weird for single bars
                    if len(hist) > 0:
                        graph_widget.setYRange(0, max(hist) * 1.1)
                    graph_widget.getAxis('bottom').setLabel("Sensor Value")
                    # Adjust X range for better visualization
                    if len(bin_edges) > 1:
                        graph_widget.setXRange(bin_edges[0], bin_edges[-1])

                else:
                     graph_widget.setTitle(f"Select sensor, ensure data exists and valid bin number (>0) for Histogram ({primary_sensor_name})")
            
            elif graph_type == "Box Plot":
                graph_widget.setTitle(f"Box Plot ({primary_sensor_name}) - Timespan: {timespan}")
                graph_widget.setLabel('bottom', 'Sensor Value')
                graph_widget.setLabel('left', '') # Y axis is positional, no label needed
                graph_widget.getAxis('left').setWidth(0) # Hide left axis ticks/line
                graph_widget.getAxis('left').setStyle(showValues=False)
                legend.setVisible(False)
                if primary_sensor_key and primary_sensor_key in historical_data and len(historical_data[primary_sensor_key]['value']) > 0:
                    values = np.array(historical_data[primary_sensor_key]['value'], dtype=float)
                    values = values[np.isfinite(values)] # Filter NaNs/infs

                    if len(values) < 5: # Need at least a few points for meaningful stats
                        graph_widget.setTitle(f"Not enough data points ({len(values)}) for Box Plot ({primary_sensor_name})")
                        return

                    # Calculate statistics
                    q1, median, q3 = np.percentile(values, [25, 50, 75])
                    iqr = q3 - q1
                    whisker_low = q1 - 1.5 * iqr
                    whisker_high = q3 + 1.5 * iqr

                    # Find actual values within whisker range
                    actual_whisker_low = np.min(values[values >= whisker_low])
                    actual_whisker_high = np.max(values[values <= whisker_high])

                    # Find outliers
                    outliers = values[(values < actual_whisker_low) | (values > actual_whisker_high)]

                    # Drawing parameters
                    y_center = 0
                    box_height = 0.6 # Arbitrary height for visual clarity
                    pen = pg.mkPen(color='w', width=getattr(self.main_window, 'plot_line_width_value', 2))
                    brush = pg.mkBrush(color=(0, 0, 255, 150))
                    outlier_pen = pg.mkPen(color=(255, 0, 0, 150), width=1)
                    outlier_brush = pg.mkBrush(color=(255, 0, 0, 150))
                    outlier_size = max(5, getattr(self.main_window, 'plot_line_width_value', 2) * 2)

                    # Create Box (Rectangle)
                    box = QGraphicsRectItem(q1, y_center - box_height / 2, q3 - q1, box_height) # Use direct import
                    box.setPen(pen)
                    box.setBrush(brush)
                    graph_widget.addItem(box)

                    # Create Median Line
                    median_line = QGraphicsLineItem(median, y_center - box_height / 2, median, y_center + box_height / 2) # Use direct import
                    median_line.setPen(pen)
                    graph_widget.addItem(median_line)

                    # Create Whiskers (Lines)
                    whisker_pen = pg.mkPen(color='w', width=pen.widthF(), style=pg.QtCore.Qt.PenStyle.DashLine) # Use pg.QtCore.Qt
                    # Low whisker line
                    line_low = QGraphicsLineItem(actual_whisker_low, y_center, q1, y_center) # Use direct import
                    line_low.setPen(whisker_pen)
                    graph_widget.addItem(line_low)
                    cap_low = QGraphicsLineItem(actual_whisker_low, y_center - box_height / 4, actual_whisker_low, y_center + box_height / 4) # Use direct import
                    cap_low.setPen(pen)
                    graph_widget.addItem(cap_low)
                    # High whisker line
                    line_high = QGraphicsLineItem(q3, y_center, actual_whisker_high, y_center) # Use direct import
                    line_high.setPen(whisker_pen)
                    graph_widget.addItem(line_high)
                    cap_high = QGraphicsLineItem(actual_whisker_high, y_center - box_height / 4, actual_whisker_high, y_center + box_height / 4) # Use direct import
                    cap_high.setPen(pen)
                    graph_widget.addItem(cap_high)

                    # Create Outliers (Scatter)
                    if len(outliers) > 0:
                        outlier_plot = pg.ScatterPlotItem(x=outliers, y=np.full(len(outliers), y_center), 
                                                          size=outlier_size, pen=outlier_pen, brush=outlier_brush)
                        graph_widget.addItem(outlier_plot)
                    
                    # Set Y range to encompass the box/whiskers visually
                    graph_widget.setYRange(y_center - box_height, y_center + box_height)
                    # Autorange X based on whisker limits + some padding
                    x_range_padding = (actual_whisker_high - actual_whisker_low) * 0.1
                    graph_widget.setXRange(actual_whisker_low - x_range_padding, actual_whisker_high + x_range_padding)

                else:
                    graph_widget.setTitle(f"Select a sensor with data for Box Plot ({primary_sensor_name})")

            elif graph_type == "Correlation Analysis":
                graph_widget.setTitle(f"Correlation ({primary_sensor_name} vs {secondary_sensor_name}) - Timespan: {timespan}")
                graph_widget.setLabel('bottom', f'{primary_sensor_name} Value')
                graph_widget.setLabel('left', f'{secondary_sensor_name} Value')
                legend.setVisible(False)
                if primary_sensor_key and secondary_sensor_key and primary_sensor_key in historical_data and secondary_sensor_key in historical_data:
                    data1 = historical_data[primary_sensor_key]
                    data2 = historical_data[secondary_sensor_key]
                    
                    # Ensure data is numerical numpy arrays
                    t1 = np.array(data1['time'], dtype=float)
                    v1 = np.array(data1['value'], dtype=float)
                    t2 = np.array(data2['time'], dtype=float)
                    v2 = np.array(data2['value'], dtype=float)
                    
                    # Align data based on timestamps (simple interpolation)
                    time_combined = np.unique(np.concatenate((t1, t2)))
                    time_combined.sort()
                    
                    # Ensure we have enough points to interpolate
                    if len(t1) < 2 or len(t2) < 2:
                        graph_widget.setTitle("Not enough data points on one or both sensors for correlation plot")
                        return
                        
                    val1_interp = np.interp(time_combined, t1, v1)
                    val2_interp = np.interp(time_combined, t2, v2)

                    # Create scatter plot
                    scatter = pg.ScatterPlotItem(size=5, pen=pg.mkPen(None), brush=pg.mkBrush(255, 255, 255, 120))
                    scatter.addPoints(x=val1_interp, y=val2_interp)
                    graph_widget.addItem(scatter)
                    
                    # Optional: Calculate and display correlation coefficient
                    if len(val1_interp) > 1: # Need at least 2 points for correlation
                        # Filter NaNs before correlation calculation
                        mask = np.isfinite(val1_interp) & np.isfinite(val2_interp)
                        if np.sum(mask) > 1:
                             corr_coef = np.corrcoef(val1_interp[mask], val2_interp[mask])[0, 1]
                             corr_text = pg.TextItem(f"Correlation (r): {corr_coef:.2f}", anchor=(0, 1), color=(200, 200, 200))
                             graph_widget.addItem(corr_text)
                        # Position text - needs adjustment based on data range
                        # view_box = graph_widget.getViewBox()
                        # view_range = view_box.viewRange()
                        # corr_text.setPos(view_range[0][0], view_range[1][1]) # Top-left corner
                        
                else:
                    graph_widget.setTitle(f"Select two valid sensors for correlation plot ({primary_sensor_name} vs {secondary_sensor_name})")

        except Exception as e:
            self.main_window.logger.error(f"Error plotting graph type '{graph_type}': {e}")
            import traceback
            self.main_window.logger.error(traceback.format_exc())
            graph_widget.setTitle(f"Error plotting {graph_type}")
            
        # Ensure autorange updates the view
        graph_widget.enableAutoRange() 
    
    def apply_plot_formatting(self):
        """Apply plot formatting based on settings"""
        try:
            # Check if we have the required UI elements
            if not (hasattr(self.main_window, 'graph_widget') and 
                    hasattr(self.main_window, 'plot_style_preset') and
                    hasattr(self.main_window, 'plot_font_size') and
                    hasattr(self.main_window, 'plot_line_width')):
                return
            
            # Get settings
            style_preset = self.main_window.plot_style_preset.currentText()
            font_size = self.main_window.plot_font_size.value()
            line_width = self.main_window.plot_line_width.value()
            
            # Apply to main graph
            self._apply_formatting_to_widget(
                self.main_window.graph_widget, 
                style_preset, 
                font_size, 
                line_width
            )
            # Update line width for all existing plots on the main graph
            for item in self.main_window.graph_widget.listDataItems():
                pen = item.opts.get('pen', None)
                if pen is not None:
                    if isinstance(pen, str):
                        color = pen
                    else:
                        color = pen.color()
                    if hasattr(item, "setPen"):
                        item.setPen(pg.mkPen(color=color, width=line_width))
            # Log the change
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Applied plot formatting: {style_preset}, size {font_size}pt, width {line_width}px")
            # Apply the same formatting to dashboard graph if it exists
            self.apply_dashboard_plot_formatting()
        except Exception as e:
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Error applying plot formatting: {str(e)}")
    
    def apply_dashboard_plot_formatting(self):
        """Apply plot formatting to dashboard graph"""
        try:
            # Check if we have the required UI elements
            if not (hasattr(self.main_window, 'dashboard_graph_widget') and 
                    hasattr(self.main_window, 'plot_style_preset') and
                    hasattr(self.main_window, 'plot_font_size') and
                    hasattr(self.main_window, 'plot_line_width')):
                return
            
            # Get settings
            style_preset = self.main_window.plot_style_preset.currentText()
            font_size = self.main_window.plot_font_size.value()
            line_width = self.main_window.plot_line_width.value()
            
            # Apply to dashboard graph
            self._apply_formatting_to_widget(
                self.main_window.dashboard_graph_widget, 
                style_preset, 
                font_size, 
                line_width
            )
            # Also update line width for all existing plots
            for plot_info in self.dashboard_plot_data.values():
                if 'plot_item' in plot_info and plot_info['plot_item'] is not None:
                    pen = plot_info['plot_item'].opts.get('pen', None)
                    if pen is not None:
                        if isinstance(pen, str):
                            color = pen
                        else:
                            color = pen.color()
                        if hasattr(plot_info['plot_item'], "setPen"):
                            plot_info['plot_item'].setPen(pg.mkPen(color=color, width=line_width))
        except Exception as e:
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Error applying dashboard plot formatting: {str(e)}")
    
    def _apply_formatting_to_widget(self, widget, style_preset, font_size, line_width):
        """Apply formatting to a specific graph widget"""
        if not widget:
            return
            
        # Add more bottom margin to ensure axis labels don't get clipped
        widget.getPlotItem().layout.setContentsMargins(10, 10, 10, 20)
        
        # Apply style preset
        if style_preset == "Standard":
            widget.setBackground('#FFFFFF')
            widget.getAxis('bottom').setPen('#000000')
            widget.getAxis('left').setPen('#000000')
            widget.getAxis('bottom').setTextPen('#000000')
            widget.getAxis('left').setTextPen('#000000')
        
        elif style_preset == "Dark":
            widget.setBackground('#2D2D2D')
            widget.getAxis('bottom').setPen('#BBBBBB')
            widget.getAxis('left').setPen('#BBBBBB')
            widget.getAxis('bottom').setTextPen('#EEEEEE')
            widget.getAxis('left').setTextPen('#EEEEEE')
        
        elif style_preset == "Solarized":
            # Solarized Light
            widget.setBackground('#FDF6E3')
            widget.getAxis('bottom').setPen('#586E75')
            widget.getAxis('left').setPen('#586E75')
            widget.getAxis('bottom').setTextPen('#657B83')
            widget.getAxis('left').setTextPen('#657B83')
        
        elif style_preset == "High Contrast":
            widget.setBackground('#000000')
            widget.getAxis('bottom').setPen('#FFFFFF')
            widget.getAxis('left').setPen('#FFFFFF')
            widget.getAxis('bottom').setTextPen('#FFFFFF')
            widget.getAxis('left').setTextPen('#FFFFFF')
        
        elif style_preset == "Pastel":
            # Pastel theme: soft background and gentle axis colors
            widget.setBackground('#F8F8FF')  # GhostWhite
            widget.getAxis('bottom').setPen('#A3A3C2')  # Soft blue-gray
            widget.getAxis('left').setPen('#A3A3C2')
            widget.getAxis('bottom').setTextPen('#7D8BA6')
            widget.getAxis('left').setTextPen('#7D8BA6')
        
        elif style_preset == "Colorful":
            widget.setBackground('#1A1A2E')
            widget.getAxis('bottom').setPen('#FFD700')
            widget.getAxis('left').setPen('#FFD700')
            widget.getAxis('bottom').setTextPen('#FFFFFF')
            widget.getAxis('left').setTextPen('#FFFFFF')
        
        # Apply font size to axis labels
        # Create QFont object instead of dict
        font = QFont()
        font.setPointSize(font_size) 
        # Pass the QFont object to setStyle
        widget.getAxis('bottom').setStyle(tickFont=font)
        widget.getAxis('left').setStyle(tickFont=font)
        
        # Set grid options (with alpha based on the style)
        if style_preset in ["Dark", "High Contrast", "Colorful"]:
            widget.showGrid(x=True, y=True, alpha=0.3)
        else:
            widget.showGrid(x=True, y=True, alpha=0.2)
        
        # Apply line width to all plots in the graph
        # This would be better handled when creating/updating the plots themselves
        # But for now we can store the value for future use
        if hasattr(self.main_window, 'plot_line_width_value'):
            self.main_window.plot_line_width_value = line_width 
            
    def start_main_graph_live_update(self):
        """Starts the timer for live updating the main graph."""
        # Set timer interval to match sampling interval, but not faster than 1s
        update_interval_ms = 1500
        if hasattr(self.main_window, 'sampling_rate_spinbox'):
            interval = self.main_window.sampling_rate_spinbox.value()
            update_interval_ms = max(int(interval * 1000), 1000)
        self.main_graph_update_timer.setInterval(update_interval_ms)
        # Only start the timer if data collection is active
        if hasattr(self.main_window, 'data_collection_controller') and self.main_window.data_collection_controller.collecting_data:
            if not self.main_graph_update_timer.isActive():
                self.main_window.logger.info(f"Starting main graph live update timer (interval: {update_interval_ms} ms).")
                # Trigger an immediate update first
                self.update_graph() 
                self.main_graph_update_timer.start()
            else:
                self.main_window.logger.info(f"Main graph live update timer already active. Updating interval to {update_interval_ms} ms.")
                self.main_graph_update_timer.setInterval(update_interval_ms)
        else:
            self.main_window.logger.info(f"Main graph live update timer not started: data collection not active")
            print(f"Main graph live update timer not started as data collection is not active")

    def stop_main_graph_live_update(self):
        """Stops the timer for live updating the main graph."""
        if self.main_graph_update_timer.isActive():
            self.main_window.logger.info("Stopping main graph live update timer.")
            self.main_graph_update_timer.stop() 

    def ensure_main_graph_live_update(self):
        """Ensure the main graph live update timer is started if the checkbox is checked, and interval is correct."""
        if hasattr(self.main_window, 'graph_live_update_checkbox'):
            if self.main_window.graph_live_update_checkbox.isChecked():
                # Only start if data collection is active
                if hasattr(self.main_window, 'data_collection_controller') and self.main_window.data_collection_controller.collecting_data:
                    self.start_main_graph_live_update()
                else:
                    self.main_window.logger.info(f"Main graph live update not started: data collection not active")
                    print(f"Main graph live update not started as data collection is not active")
            else:
                self.stop_main_graph_live_update() 

    def clear_graphs(self):
        """Clear all graphs and plot data buffers"""
        # Clear internal data buffers
        self.dashboard_plot_data.clear()
        
        # Reset time tracking
        self.dashboard_start_time = None
        self.last_plot_update_time = 0
        
        # Clear the dashboard graph if it exists
        if self.dashboard_graph_widget:
            self.dashboard_graph_widget.clear()
            print("DEBUG: Cleared dashboard graph")
            
        # Clear the main graph if it exists
        if hasattr(self.main_window, 'graph_widget'):
            self.main_window.graph_widget.clear()
            print("DEBUG: Cleared main graph")
            
        # Reset live plotting flag
        self.live_plotting_active = False
        
        print("DEBUG: All graphs and plot data cleared")
        
    def plot_historical_data(self, historical_data):
        """
        Plot historical data from the CSV file at program start.
        
        Args:
            historical_data: Data in the format {sensor_id: {'time': [...], 'value': [...]}}
        """
        print(f"DEBUG: plot_historical_data called with {len(historical_data)} sensors")
        
        # Exit if no data
        if not historical_data:
            print("DEBUG: No historical data to plot")
            return
            
        # Get the main graph widget
        graph_widget = None
        if hasattr(self.main_window, 'graph_widget'):
            graph_widget = self.main_window.graph_widget
        elif hasattr(self.main_window, 'graph_tab') and hasattr(self.main_window.graph_tab, 'graph_widget'):
            graph_widget = self.main_window.graph_tab.graph_widget
        
        if not graph_widget:
            print("DEBUG: No graph widget found to display historical data")
            return
            
        # Clear the graph and prepare it
        graph_widget.clear()
        if hasattr(graph_widget, 'legend') and graph_widget.legend is not None:
            try:
                graph_widget.legend.scene().removeItem(graph_widget.legend)
            except Exception as e:
                print(f"DEBUG: Could not remove existing legend: {e}")
                
        legend = graph_widget.addLegend()
        graph_widget.showGrid(x=True, y=True, alpha=0.3)
        graph_widget.setLabel('bottom', 'Elapsed Time (s)')
        graph_widget.setLabel('left', 'Sensor Value')
        graph_widget.setTitle("Historical Data from Last Run")
        
        # Apply formatting
        self.apply_plot_formatting()
        
        # Plot each sensor's data
        for sensor_id, data in historical_data.items():
            if len(data['time']) > 0 and len(data['value']) > 0:
                try:
                    # Convert to numpy arrays for efficient handling
                    times = np.array(data['time'], dtype=float)
                    values = np.array(data['value'], dtype=float)
                    
                    # Get sensor information for better display
                    sensor_name = sensor_id
                    color = '#FFFFFF'  # Default white
                    
                    # Try to get sensor name and color if available
                    if hasattr(self.main_window, 'sensor_controller'):
                        sensor_name = self.main_window.sensor_controller.get_sensor_name_by_historical_key(sensor_id) or sensor_id
                        sensor_obj = self.main_window.sensor_controller.get_sensor_by_name(sensor_name)
                        if sensor_obj:
                            color = getattr(sensor_obj, 'color', '#FFFFFF')
                    
                    # Create a pen with the right color and width
                    pen = pg.mkPen(color=color, width=getattr(self.main_window, 'plot_line_width_value', 2))
                    
                    # Add the plot to the graph
                    graph_widget.plot(times, values, pen=pen, name=sensor_name)
                    print(f"DEBUG: Plotted {len(times)} points for sensor {sensor_name}")
                except Exception as e:
                    print(f"DEBUG: Error plotting historical data for sensor {sensor_id}: {e}")
        
        # Set auto range so all data is visible
        graph_widget.autoRange()
        print("DEBUG: Historical data plotting completed") 