"""
Graph Controller

Manages graph visualization and data plotting.
"""

import pyqtgraph as pg
# Enable performance optimizations for pyqtgraph
pg.setConfigOptions(antialias=False) # Antialiasing is slow for many points
from PyQt6.QtGui import QColor, QFont, QDesktopServices
from PyQt6.QtWidgets import QGraphicsRectItem, QGraphicsLineItem, QMenu # Import necessary QtWidgets
import time
import os
import csv
import glob
from collections import defaultdict
import numpy as np # Import numpy for efficient filtering
import re # Import regular expressions
import bisect # For efficient data slicing
from scipy.fft import fft, fftfreq
from PyQt6.QtCore import QTimer, Qt, QMutex, QUrl  # Import QTimer, Qt, and QMutex for pen styles and thread safety

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
        self.plot_update_interval = 0.3 # Update plot visuals every 300ms (reduced frequency for performance)
        
        # Store automation event markers for graph visualization
        self.event_markers = []  # List of event dictionaries with timestamps
        self.event_markers_mutex = QMutex() if hasattr(QMutex, '__init__') else None
        self.show_automation_markers = True
        self._event_marker_items = {}
        self._last_marker_add_time = 0 # Rate limit for UI markers
        
        # Track legend labels to prevent duplicates and improve update speed
        self._dashboard_legend_labels = {} 

        # Replay-specific helpers
        self.replay_playhead_line = None
        self.replay_data_bounds = (0.0, 0.0)
        self.replay_dataset_loaded = False
        
        # Timer for main graph live updates
        self.main_graph_update_timer = QTimer()
        self.main_graph_update_timer.setInterval(1500) # Update every 1.5 seconds
        self.main_graph_update_timer.timeout.connect(self.update_graph)

    def _resolve_start_time(self, preferred=None, allow_now=False):
        """Resolve a start_time for marker placement with sensible fallbacks."""
        if preferred is not None:
            return preferred
        if self.dashboard_start_time:
            return self.dashboard_start_time
        if hasattr(self.main_window, "data_collection_controller"):
            st = getattr(self.main_window.data_collection_controller, "start_time", None)
            if st is not None:
                return st
        if hasattr(self, "event_markers") and self.event_markers:
            return min(e.get("timestamp", time.time()) for e in self.event_markers)
        return time.time() if allow_now else None

    def _update_dashboard_axis_labels(self):
        """Update dashboard graph Y-axis labels based on units of active sensors."""
        if not self.dashboard_graph_widget:
            return
            
        active_left = []
        active_right = []
        
        # Use dashboard_plot_data as the source of truth for what's actually being graphed
        for plot_info in self.dashboard_plot_data.values():
            sensor_obj = plot_info.get('sensor_obj')
            # Check the dictionary flag first (set during replay load), then fallback to sensor_obj
            use_secondary = plot_info.get('use_secondary', False)
            if not use_secondary and sensor_obj:
                use_secondary = getattr(sensor_obj, 'use_secondary_axis', False)
                
            if use_secondary:
                if sensor_obj: active_right.append(sensor_obj)
            else:
                if sensor_obj: active_left.append(sensor_obj)
                    
        # Update Left Axis
        left_units = sorted(list(set(s.unit for s in active_left if s.unit)))
        if len(left_units) == 1:
            self.dashboard_graph_widget.setLabel('left', f"Sensor Value ({left_units[0]})")
        elif len(left_units) > 1:
            self.dashboard_graph_widget.setLabel('left', "Sensor Value (Mixed Units)")
        else:
            self.dashboard_graph_widget.setLabel('left', "Sensor Value")
            
        # Update Right Axis
        if active_right:
            right_units = sorted(list(set(s.unit for s in active_right if s.unit)))
            label = "Secondary Value"
            if len(right_units) == 1:
                label = f"Sensor Value ({right_units[0]})"
            elif len(right_units) > 1:
                label = "Sensor Value (Mixed Units)"
                
            # Try to match color of the first secondary sensor for the axis label
            color_str = getattr(active_right[0], 'color', '#FFFFFF')
            self.dashboard_graph_widget.getAxis('right').setLabel(label, color=color_str)
        else:
            self.dashboard_graph_widget.setLabel('right', "")

    def _update_main_graph_axis_labels(self, graph_widget, sensor_keys):
        """Update main graph Y-axis labels based on units of active sensors."""
        if not graph_widget or not hasattr(self.main_window, 'sensor_controller'):
            return
            
        active_left = []
        active_right = []
        
        for key in sensor_keys:
            # Handle control sensors correctly
            lookup_key = key[:-5] if key.endswith('_ctrl') else key
            sensor_obj = self.main_window.sensor_controller.get_sensor_by_historical_key(lookup_key)
            if sensor_obj:
                if getattr(sensor_obj, 'use_secondary_axis', False):
                    active_right.append(sensor_obj)
                else:
                    active_left.append(sensor_obj)
                    
        # Update Left Axis
        left_units = sorted(list(set(s.unit for s in active_left if s.unit)))
        if len(left_units) == 1:
            graph_widget.setLabel('left', f"Sensor Value ({left_units[0]})")
        elif len(left_units) > 1:
            graph_widget.setLabel('left', "Sensor Value (Mixed Units)")
        else:
            graph_widget.setLabel('left', "Sensor Value")
            
        # Update Right Axis
        if active_right:
            right_units = sorted(list(set(s.unit for s in active_right if s.unit)))
            label = "Secondary Value"
            if len(right_units) == 1:
                label = f"Sensor Value ({right_units[0]})"
            elif len(right_units) > 1:
                label = "Sensor Value (Mixed Units)"
                
            # Try to match color of the first secondary sensor
            color_str = getattr(active_right[0], 'color', '#FFFFFF')
            graph_widget.getAxis('right').setLabel(label, color=color_str)
        else:
            graph_widget.setLabel('right', "")

    def _debug(self, message):
        """Log debug messages when a logger is available."""
        if hasattr(self.main_window, "logger"):
            self.main_window.logger.debug(message)

    def _warn(self, message):
        """Log warnings when a logger is available."""
        if hasattr(self.main_window, "logger"):
            self.main_window.logger.warning(message)

    def _error(self, message):
        """Log errors when a logger is available."""
        if hasattr(self.main_window, "logger"):
            self.main_window.logger.error(message)

    def _get_event_markers_snapshot(self):
        """
        Thread-safe snapshot of stored automation events.
        
        Returns:
            list: Copy of event marker dictionaries
        """
        if self.event_markers_mutex:
            self.event_markers_mutex.lock()
            try:
                return list(self.event_markers)
            finally:
                self.event_markers_mutex.unlock()
        return list(self.event_markers)

    def _clear_event_markers_for_widget(self, graph_widget):
        """Remove automation marker items from a graph widget."""
        if not graph_widget:
            return
        items = self._event_marker_items.get(graph_widget, [])
        for item in items:
            try:
                graph_widget.removeItem(item)
            except Exception:
                continue
        self._event_marker_items[graph_widget] = []

    def set_show_automation_markers(self, enabled: bool):
        """Enable/disable automation markers and refresh graphs accordingly."""
        self.show_automation_markers = bool(enabled)
        self._debug(
            f"Graph: set_show_automation_markers -> {self.show_automation_markers}, "
            f"events stored={len(self._get_event_markers_snapshot())}"
        )
        print(f"[AUTOMATION MARKERS] toggle -> {self.show_automation_markers}, stored={len(self._get_event_markers_snapshot())}")

        # Always clear existing markers from both graphs
        self._clear_event_markers_for_widget(self.dashboard_graph_widget)
        self._clear_event_markers_for_widget(getattr(self.main_window, "graph_widget", None))

        if not self.show_automation_markers:
            return

        # Re-add markers to dashboard graph if possible
        dashboard_start = self._resolve_start_time(self.dashboard_start_time, allow_now=True)
        if self.dashboard_graph_widget:
            self._debug(f"Graph: re-adding dashboard markers with start={dashboard_start}")
            self._add_event_markers_to_graph(self.dashboard_graph_widget, dashboard_start, force=True)

        # Re-add markers to main graph if possible
        if hasattr(self.main_window, "graph_widget") and hasattr(self.main_window, "data_collection_controller"):
            # Check if current graph type allows markers
            current_graph_type = ""
            if hasattr(self.main_window, 'graph_type_combo'):
                current_graph_type = self.main_window.graph_type_combo.currentText()
            
            if current_graph_type not in ["Histogram", "Box Plot"]:
                main_start = self._resolve_start_time(getattr(self.main_window.data_collection_controller, "start_time", None), allow_now=True)
                self._debug(f"Graph: re-adding main markers with start={main_start}")
                self._add_event_markers_to_graph(self.main_window.graph_widget, main_start, force=True)

        # Force a redraw to ensure markers appear after toggling back on
        for gw in [getattr(self.main_window, 'graph_widget', None), self.dashboard_graph_widget]:
            if gw:
                try:
                    gw.update()
                except Exception:
                    pass

    def connect_signals(self):
        """Connect UI signals to controller methods"""
        if hasattr(self.main_window, 'graph_type_combo'):
            self.main_window.graph_type_combo.currentIndexChanged.connect(self.on_graph_type_changed)
            self.main_window.graph_primary_sensor.currentIndexChanged.connect(self.update_graph)
            self.main_window.graph_secondary_sensor.currentIndexChanged.connect(self.update_graph)
            self.main_window.graph_timespan.currentIndexChanged.connect(self.on_timespan_changed)
            self.main_window.dashboard_timespan.currentIndexChanged.connect(self.on_dashboard_timespan_changed)
        
        # Setup custom context menu for graph widget to override "View All"
        if hasattr(self.main_window, 'graph_widget'):
            self._setup_graph_context_menu(self.main_window.graph_widget)
    
    def _get_data_bounds(self, graph_widget):
        """
        Calculate the actual data bounds from plot items, excluding markers and other non-data items.
        Only includes regular (non-control) sensor data to match the CSV bounds.
        Only includes X values where there's actual Y data (not just empty space).
        
        Args:
            graph_widget: The PlotWidget to analyze
            
        Returns:
            tuple: (min_x, max_x, min_y, max_y) or None if no data found
        """
        if not graph_widget:
            return None
        
        plot_item = graph_widget.getPlotItem()
        if not plot_item:
            return None
        
        # Get all data items in the plot
        all_items = plot_item.listDataItems()
        
        # Filter to only PlotDataItem (actual data curves, not markers or other items)
        data_items = [item for item in all_items if isinstance(item, pg.PlotDataItem)]
        
        if not data_items:
            return None
        
        # Collect x and y values from data items, but only where both X and Y are valid
        # Store data per item to find the main data cluster
        sensor_x_ranges = []  # List of (min_x, max_x, point_count) for each sensor
        all_x_values = []
        all_y_values = []
        
        for item in data_items:
            try:
                # Get the data from the plot item
                x_data = item.xData
                y_data = item.yData
                
                # Skip if data is empty
                if x_data is None or len(x_data) == 0:
                    continue
                if y_data is None or len(y_data) == 0:
                    continue
                
                # Check if this is control run data by checking the pen style
                # Control sensors use dashed lines, regular sensors use solid lines
                is_control = self._is_control_item(item)
                
                # Skip control run data - we only want the actual CSV data bounds
                if is_control:
                    self._debug(f"Skipping control run data item (dashed line or control in name)")
                    continue
                
                # Convert to arrays for easier processing
                if isinstance(x_data, np.ndarray):
                    x_arr = x_data
                else:
                    x_arr = np.array(x_data, dtype=float)
                
                if isinstance(y_data, np.ndarray):
                    y_arr = y_data
                else:
                    y_arr = np.array(y_data, dtype=float)
                
                # Only include points where BOTH X and Y are finite and valid
                # This ensures we only count actual data points, not gaps or invalid data
                valid_mask = np.isfinite(x_arr) & np.isfinite(y_arr)
                
                if np.any(valid_mask):
                    valid_x = x_arr[valid_mask]
                    valid_y = y_arr[valid_mask]
                    
                    if len(valid_x) > 0:
                        # Store the range for this sensor
                        sensor_x_ranges.append((np.min(valid_x), np.max(valid_x), len(valid_x)))
                        all_x_values.extend(valid_x.tolist())
                        all_y_values.extend(valid_y.tolist())
                    
            except Exception as e:
                self._debug(f"Error getting data from plot item: {e}")
                continue
        
        if not all_x_values:
            self._debug("No valid X values found in data items")
            return None
        
        min_x = min(all_x_values)
        
        # Find the maximum X from the main data cluster
        # If we have multiple sensors, use the maximum X where most sensors have data
        # This prevents a single outlier sensor from extending the range too far
        if len(sensor_x_ranges) > 1:
            # Find the maximum X that's within the range of at least 2 sensors
            # This ensures we don't include sparse outliers
            max_xes = [r[1] for r in sensor_x_ranges]  # Get max X for each sensor
            max_xes.sort()
            # Use the second-highest max (or highest if only 2 sensors)
            # This helps filter out single-sensor outliers
            if len(max_xes) >= 2:
                # Use the maximum X from sensors that have substantial data
                # Find sensors with more than 10 data points
                substantial_sensors = [r for r in sensor_x_ranges if r[2] > 10]
                if substantial_sensors:
                    max_x = max(r[1] for r in substantial_sensors)
                else:
                    # All sensors have few points, use the median max X
                    max_x = np.median(max_xes)
            else:
                max_x = max_xes[-1]
        else:
            # Single sensor or all sensors have similar ranges
            max_x = max(all_x_values)
        
        # Y values are optional - if we have them, use them, otherwise just set X range
        if all_y_values:
            min_y = min(all_y_values)
            max_y = max(all_y_values)
        else:
            # If no Y values, we'll let Y auto-range
            min_y = None
            max_y = None
        
        self._debug(f"Data bounds calculated: X=[{min_x:.2f}, {max_x:.2f}] seconds, Y=[{min_y}, {max_y}], from {len(sensor_x_ranges)} regular sensors")
        
        return (min_x, max_x, min_y, max_y)
    
    def _is_control_item(self, item):
        """Check if a plot item is a control run item"""
        try:
            if hasattr(item, 'opts') and 'pen' in item.opts:
                pen = item.opts['pen']
                if hasattr(pen, 'style'):
                    if pen.style() == pg.QtCore.Qt.PenStyle.DashLine:
                        return True
            item_name = ""
            if hasattr(item, 'name'):
                item_name = str(item.name()) if callable(item.name) else str(item.name)
            elif hasattr(item, 'opts') and 'name' in item.opts:
                item_name = str(item.opts['name'])
            
            if item_name and ('_ctrl' in item_name.lower() or 'control' in item_name.lower()):
                return True
        except:
            pass
        return False
    
    def _view_all_data(self, graph_widget):
        """
        Zoom to show only the actual data bounds (up to last CSV line), not all items.
        
        Args:
            graph_widget: The PlotWidget to zoom
        """
        bounds = self._get_data_bounds(graph_widget)
        if bounds is None:
            # Fallback to standard autoRange if no data bounds found
            self._debug("No data bounds found, using standard autoRange")
            graph_widget.autoRange()
            return
        
        min_x, max_x, min_y, max_y = bounds
        
        # Add small padding (2%) for better visualization
        x_range = max_x - min_x
        x_padding = x_range * 0.02 if x_range > 0 else 1
        
        self._debug(f"Setting X range to [{min_x - x_padding:.2f}, {max_x + x_padding:.2f}]")
        
        # Set the X range to show only the data (up to last CSV line)
        graph_widget.setXRange(min_x - x_padding, max_x + x_padding, padding=0)
        
        # Set Y range if we have Y bounds, otherwise let it auto-range
        if min_y is not None and max_y is not None:
            y_range = max_y - min_y
            y_padding = y_range * 0.02 if y_range > 0 else 1
            graph_widget.setYRange(min_y - y_padding, max_y + y_padding, padding=0)
        else:
            # Only auto-range Y axis
            graph_widget.enableAutoRange(axis='y')
    
    def _setup_graph_context_menu(self, graph_widget):
        """
        Setup custom context menu for graph widget to override "View All" behavior.
        
        Args:
            graph_widget: The PlotWidget to setup context menu for
        """
        if not graph_widget:
            return
        
        # Get the PlotItem's ViewBox
        plot_item = graph_widget.getPlotItem()
        if not plot_item:
            return
        
        view_box = plot_item.getViewBox()
        if not view_box:
            return
        
        # Store reference to graph_widget and controller for the menu handler
        view_box._graph_widget = graph_widget
        view_box._graph_controller = self
        
        # Override the getMenu method to customize the context menu
        # Save the original method
        if not hasattr(view_box, '_original_get_menu'):
            view_box._original_get_menu = view_box.getMenu
        
        def custom_get_menu(ev):
            """Create custom context menu with overridden View All"""
            try:
                # Get the original menu first
                original_menu = view_box._original_get_menu(ev)
                
                if not original_menu:
                    # If no original menu, create a basic one with our custom View All
                    menu = QMenu(graph_widget)
                    view_all_action = menu.addAction("View All")
                    view_all_action.triggered.connect(lambda checked, gw=graph_widget: self._view_all_data(gw))
                    return menu
                
                # Find and modify the "View All" action in the original menu
                for action in original_menu.actions():
                    action_text = action.text() if action.text() else ""
                    action_text_lower = action_text.lower()
                    
                    # Check for View All or Auto Range actions
                    if "view all" in action_text_lower or "auto range" in action_text_lower:
                        # Disconnect all existing connections
                        try:
                            action.triggered.disconnect()
                        except:
                            pass
                        # Connect to our custom handler
                        action.triggered.connect(lambda checked, gw=graph_widget: self._view_all_data(gw))
                        break  # Only modify the first match
                
                return original_menu
            except Exception as e:
                # If anything goes wrong, fall back to original menu
                self._debug(f"Error creating custom context menu: {e}")
                try:
                    return view_box._original_get_menu(ev)
                except:
                    return None
        
        # Override the getMenu method
        view_box.getMenu = custom_get_menu
    
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
        if not hasattr(self.main_window, 'data_collection_controller'):
            return

        # Update if data collection is active OR if we are in replay/review mode
        collecting = self.main_window.data_collection_controller.collecting_data
        replay_mode = getattr(self.main_window, 'replay_mode_enabled', False)

        if not collecting and not replay_mode:
            self._debug("Skipping main graph update as neither collection nor replay is active")
            return

        if hasattr(self.main_window, 'logger'):
            self.main_window.logger.debug(f"Updating main graph (collecting={collecting}, replay={replay_mode})")
        
        # Trigger the main window's update method which gathers params and calls update_specific_graph
        if hasattr(self.main_window, 'update_graph'):
            self.main_window.update_graph()
            # --- Ensure all lines have the correct line width after update ---
            # Preserve pen style (dashed/solid) when updating width
            if hasattr(self.main_window, 'plot_line_width') and hasattr(self.main_window, 'graph_widget'):
                line_width = self.main_window.plot_line_width.value()
                for item in self.main_window.graph_widget.listDataItems():
                    pen = item.opts.get('pen', None)
                    if pen is not None:
                        if isinstance(pen, str):
                            color = pen
                            style = pg.QtCore.Qt.PenStyle.SolidLine
                        else:
                            color = pen.color()
                            # Preserve the pen style (dashed, solid, etc.)
                            style = pen.style()
                        if hasattr(item, "setPen"):
                            item.setPen(pg.mkPen(color=color, width=line_width, style=style))

    def update_dashboard_graph(self):
        """Update the dashboard graph"""
        if hasattr(self.main_window, 'logger'):
            self.main_window.logger.debug("Updating dashboard graph")

        # If live plotting is active, visuals are handled by plot_new_data/timer
        if self.live_plotting_active:
             return
             
        # If not live plotting, update visuals to reflect current buffer/timespan
        if self.dashboard_graph_widget:
             self._update_all_plot_visuals(force=True)

    def start_live_dashboard_update(self, start_time):
        """Prepare and start live plotting on the dashboard graph."""
        self.main_window.logger.log("Starting live dashboard graph updates.", "INFO")
        print(f"DEBUG: start_live_dashboard_update called with start_time: {start_time}")
        # Update header to reflect live context
        if hasattr(self.main_window, "_update_dashboard_header_for_run"):
            run_dir = None
            if hasattr(self.main_window, "project_controller"):
                run_dir = self.main_window.project_controller.get_current_run_directory()
            self.main_window._update_dashboard_header_for_run(run_dir, mode_label="Live")
        
        if not hasattr(self.main_window, 'dashboard_graph_widget'):
            self.main_window.logger.log("Dashboard graph widget not found.", "ERROR")
            print("ERROR: Dashboard graph widget not found.")
            return
            
        self.dashboard_graph_widget = self.main_window.dashboard_graph_widget    
        self.dashboard_graph_widget.clear()
        
        # Clear the legend explicitly to prevent orphaned items from previous runs
        try:
            plot_item = self.dashboard_graph_widget.getPlotItem()
            if hasattr(plot_item, 'legend') and plot_item.legend:
                plot_item.legend.clear()
        except Exception:
            pass

        self._dashboard_legend_labels.clear()

        # Configure global downsampling on the PlotItem for better performance
        # This is safer than per-plot downsampling in some pyqtgraph versions
        try:
            # Check for setting
            downsampling_enabled = True
            if hasattr(self.main_window, 'graph_downsampling_checkbox'):
                downsampling_enabled = self.main_window.graph_downsampling_checkbox.isChecked()
            elif self.settings_model:
                downsampling_enabled = self.settings_model.get_bool("graph_downsampling", True)

            plot_item = self.dashboard_graph_widget.getPlotItem()
            if downsampling_enabled:
                plot_item.setDownsampling(ds=True, auto=True, mode='peak')
            else:
                plot_item.setDownsampling(ds=False)
            plot_item.setClipToView(True)
        except Exception as e:
            print(f"DEBUG: Could not set global downsampling: {e}")

        self.dashboard_plot_data.clear()
        
        # Robust start time assignment: preserve existing if mid-run reinit, or resolve from dcc/now
        resolved_start = self._resolve_start_time(start_time, allow_now=True)
        if self.dashboard_start_time is None or (start_time is not None and abs(float(start_time) - float(self.dashboard_start_time)) > 1.0):
            self.dashboard_start_time = float(resolved_start) if resolved_start else time.time()
            self._debug(f"Graph: start_live_dashboard_update - set dashboard_start_time={self.dashboard_start_time}")
            
        self.live_plotting_active = True
        self.replay_dataset_loaded = False
        self.replay_playhead_line = None
        print(f"DEBUG: Set live_plotting_active={self.live_plotting_active}, dashboard_start_time={self.dashboard_start_time}")

        # Set up axes and legend
        print("DEBUG: Setting up dashboard graph axes and legend")
        self.dashboard_graph_widget.setLabel('bottom', 'Time (s)')
        self.dashboard_graph_widget.setLabel('left', 'Value') # Generic Y-label
        
        # Clear any existing legend first via PlotItem
        plot_item = self.dashboard_graph_widget.getPlotItem()
        
        # --- Handle Secondary Axis cleanup if exists ---
        if hasattr(self, 'secondary_vb') and self.secondary_vb:
            try:
                # Explicitly remove all items from secondary ViewBox before deleting it
                # to prevent LegendItem from holding onto deleted C++ objects
                for item in self.secondary_vb.allChildItems():
                    self.secondary_vb.removeItem(item)
                plot_item.scene().removeItem(self.secondary_vb)
            except Exception:
                pass
            self.secondary_vb = None
        plot_item.hideAxis('right')
        # -----------------------------------------------

        try:
            # Handle main legend - search multiple possible locations
            leg = getattr(plot_item, 'legend', None)
            if not leg:
                # Check if it's stored on the widget (our custom attribute)
                leg = getattr(self.dashboard_graph_widget, 'legend', None)
                
            if leg:
                try:
                    leg.clear()
                    scene = leg.scene()
                    if scene:
                        scene.removeItem(leg)
                    leg.setParentItem(None)
                except Exception:
                    pass
                
            # Clear all references everywhere
            if hasattr(plot_item, 'legend'):
                plot_item.legend = None
            if hasattr(self.dashboard_graph_widget, 'legend'):
                self.dashboard_graph_widget.legend = None
        except Exception:
            pass

        # Create a fresh legend
        legend = plot_item.addLegend(offset=(30, 30))
        self.dashboard_graph_widget.legend = legend # Store reference
        
        if legend:
            legend.setVisible(True)
            legend.setBrush(pg.mkBrush(20, 20, 30, 180)) # Dark, slightly purple background
            legend.setPen(pg.mkPen(150, 150, 150, 150))  # Muted border
            legend.setZValue(1000)
            # Ensure the legend can be seen
            # LegendItem's layout often needs a nudge
            legend.update()
        
        self.dashboard_graph_widget.showGrid(x=True, y=True, alpha=0.3)
        
        # Add event markers to dashboard graph
        start_time = self._resolve_start_time(self.dashboard_start_time, allow_now=self.show_automation_markers)
        self._add_event_markers_to_graph(self.dashboard_graph_widget, start_time, force=self.show_automation_markers)
        
        # Set auto range on the plot so it updates as new data comes in
        self.dashboard_graph_widget.enableAutoRange()
        # Make sure viewbox is set to auto-range for both axes
        view_box = self.dashboard_graph_widget.getViewBox()
        if view_box:
            view_box.setAutoVisible(x=True, y=True)
            view_box.enableAutoRange(axis='xy', enable=True)
        
        # Set antialiasing for smoother lines
        self.dashboard_graph_widget.setAntialiasing(True)

        # Update labels based on sensors
        self._update_dashboard_axis_labels()

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
        
        # --- Secondary Axis Setup ---
        needs_secondary = any(getattr(s, 'use_secondary_axis', False) and getattr(s, 'show_in_graph', True) and getattr(s, 'enabled', True) for s in sensors)
        self.secondary_vb = None
        if needs_secondary:
            self.secondary_vb = pg.ViewBox()
            plot_item.scene().addItem(self.secondary_vb)
            right_axis = plot_item.getAxis('right')
            right_axis.linkToView(self.secondary_vb)
            self.secondary_vb.setXLink(plot_item.vb) # Sync X axis
            plot_item.showAxis('right')
            
            # Update secondary viewbox geometry when main one changes
            def update_views():
                if hasattr(self, 'secondary_vb') and self.secondary_vb:
                    self.secondary_vb.setGeometry(plot_item.vb.sceneBoundingRect())
            plot_item.vb.sigResized.connect(update_views)
            update_views() # Initial call
        # ----------------------------

        for sensor in sensors:
            try:
                # Use getattr with defaults to be safe
                show_in_graph = getattr(sensor, 'show_in_graph', True)
                enabled = getattr(sensor, 'enabled', True)
                
                if show_in_graph and enabled:
                    color_str = getattr(sensor, 'color', '#FFFFFF')
                    sensor_name_for_legend = getattr(sensor, 'name', 'Unknown Sensor')
                    interface_type = str(getattr(sensor, 'interface_type', 'Unknown')).upper()
                    # print(f"DEBUG GRAPH: Adding sensor {sensor_name_for_legend} (type {interface_type}) to graph")

                    # --- Determine the CORRECT key for matching incoming data --- 
                    sensor_key_for_data = None
                    if interface_type == "ARDUINO":
                        # Use the sensor name for Arduino data keys (address is often empty)
                        sensor_key_for_data = getattr(sensor, 'name', None)
                        if not sensor_key_for_data:
                            print(f"WARNING GRAPH: Arduino sensor '{sensor_name_for_legend}' has no name defined. Skipping plot.")
                            continue
                    elif interface_type == "LABJACK":
                        # LabJack uses channel name (port/address field in SensorModel)
                        sensor_key_for_data = getattr(sensor, 'port', None) # Assuming 'port' holds the channel name
                        if not sensor_key_for_data:
                            print(f"WARNING GRAPH: LabJack sensor '{sensor_name_for_legend}' has no port/channel defined. Skipping plot.")
                            continue
                    elif interface_type == "OTHERSERIAL":
                        # OtherSerial data is keyed by the user-defined sensor name
                        sensor_key_for_data = sensor_name_for_legend 
                    elif interface_type == "OPTICALSENSOR":
                        # OpticalSensor uses the sensor name for data keys
                        sensor_key_for_data = sensor_name_for_legend
                    elif interface_type == "AUDIOSENSOR":
                        # AudioSensor uses the sensor name for data keys
                        sensor_key_for_data = sensor_name_for_legend
                    elif interface_type == "CSV":
                        # CSV uses the prefixed key stored in the port field
                        sensor_key_for_data = getattr(sensor, 'port', None)
                        if not sensor_key_for_data:
                            sensor_key_for_data = f"csv_{sensor_name_for_legend}"
                    else:
                        # Handle generic plugins
                        # For dynamic plugins, the key is "Interface Name_Measurement" or "Interface Name_Sensor Name"
                        if hasattr(sensor, 'mapping') and sensor.mapping:
                            sensor_key_for_data = f"{sensor.interface_type}_{sensor.mapping}"
                        else:
                            sensor_key_for_data = f"{sensor.interface_type}_{sensor.name}"
                        print(f"DEBUG GRAPH: Using generic key '{sensor_key_for_data}' for plugin sensor '{sensor_name_for_legend}'")
                    # --------------------------------------------------------

                    print(f"DEBUG: Adding sensor to graph: Name='{sensor_name_for_legend}', KeyForData='{sensor_key_for_data}', Type='{interface_type}', Color='{color_str}'")
                    
                    try:
                        color = QColor(color_str)
                        pen = pg.mkPen(color=color, width=line_width)
                        
                        # --- Determine which ViewBox to use ---
                        use_secondary = getattr(sensor, 'use_secondary_axis', False)
                        
                        if use_secondary and self.secondary_vb:
                            plot_item_obj = pg.PlotDataItem(
                                [], [], 
                                pen=pen, 
                                name=sensor_name_for_legend,
                                connect='finite'
                            )
                            self.secondary_vb.addItem(plot_item_obj)
                            # Add to legend manually as it's not in the main PlotWidget
                            if legend:
                                legend.addItem(plot_item_obj, sensor_name_for_legend)
                        else:
                            plot_item_obj = self.dashboard_graph_widget.plot(
                                [], [], 
                                pen=pen, 
                                name=sensor_name_for_legend,
                                connect='finite'
                            )
                        
                        # Store plot data using sensor_key_for_data as the dictionary key
                        self.dashboard_plot_data[sensor_key_for_data] = {
                            'x': [], 
                            'y': [], 
                            'plot_item': plot_item_obj,
                            'name': sensor_name_for_legend, # Keep user-defined name for reference
                            'color': color_str,
                            'sensor_obj': sensor
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
            except Exception as e:
                print(f"ERROR GRAPH: Unexpected error processing sensor: {e}")
                if hasattr(self.main_window, 'logger'):
                    self.main_window.logger.log(f"Unexpected error processing sensor: {e}", "ERROR")

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
            
        # --- Set up dashboard update timer to match sampling rate, but not faster than 1s ---
        update_interval_ms = 1000  # Default 1s
        if hasattr(self.main_window, 'sampling_rate_spinbox'):
            rate_hz = self.main_window.sampling_rate_spinbox.value()
            if rate_hz > 0:
                # Convert Hz to ms interval: 1000 / Hz
                update_interval_ms = max(int(1000 / rate_hz), 1000)
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
    
    def load_replay_dataset(self, rows, automation_columns=None):
        """Preload full replay dataset into dashboard plots and set up playhead."""
        if not self.dashboard_graph_widget:
            self._warn("Graph: dashboard_graph_widget missing; cannot load replay data")
            return

        # 1. THE CLEAN SLATE
        # Clear dictionary and widget to ensure no orphan objects from live mode remain.
        self.dashboard_plot_data.clear()
        self._dashboard_legend_labels.clear()
        self.dashboard_graph_widget.clear()
        
        plot_item = self.dashboard_graph_widget.getPlotItem()
        
        # Explicitly cleanup and recreate the legend
        try:
            leg = getattr(plot_item, 'legend', None)
            if not leg:
                leg = getattr(self.dashboard_graph_widget, 'legend', None)
            if leg:
                try:
                    leg.clear()
                    scene = leg.scene()
                    if scene: scene.removeItem(leg)
                    leg.setParentItem(None)
                except Exception: pass
        except Exception: pass
        plot_item.legend = None
        self.dashboard_graph_widget.legend = None
        
        legend = plot_item.addLegend(offset=(30, 30))
        self.dashboard_graph_widget.legend = legend
        if legend:
            legend.setVisible(True)
            legend.setBrush(pg.mkBrush(20, 20, 30, 180))
            legend.setPen(pg.mkPen(150, 150, 150, 150))
            legend.setZValue(1000)

        # Cleanup and reset secondary axis
        if hasattr(self, 'secondary_vb') and self.secondary_vb:
            try:
                for item in self.secondary_vb.allChildItems():
                    self.secondary_vb.removeItem(item)
                plot_item.scene().removeItem(self.secondary_vb)
            except Exception: pass
            self.secondary_vb = None
        plot_item.hideAxis('right')

        # 2. Clear previous replay state
        self.replay_dataset_loaded = False
        self.replay_data_bounds = (0.0, 0.0)
        if hasattr(self, 'replay_playhead_line') and self.replay_playhead_line:
            try: 
                self.dashboard_graph_widget.removeItem(self.replay_playhead_line)
            except Exception: 
                pass
            self.replay_playhead_line = None

        if not rows:
            self._warn("Graph: No replay rows provided to load")
            return

        automation_columns = automation_columns or []

        # 3. Collect sensor keys
        replay_sensor_keys = set()
        for row in rows:
            for key in row.keys():
                if key in ("timestamp", "_timestamp", "_rel_time") or key.endswith("_timestamp"):
                    continue
                if key in automation_columns:
                    continue
                replay_sensor_keys.add(key)

        def _resolve_sensor_info(sensor_key):
            """
            Resolve sensor object and display name using the sensor controller.
            This ensures consistency between dashboard and analysis tabs.
            """
            sensor_obj = None
            legend_name = sensor_key
            color_str = None
            
            if hasattr(self.main_window, "sensor_controller"):
                sc = self.main_window.sensor_controller
                # This is the primary lookup method used by the Graphs tab
                sensor_obj = sc.get_sensor_by_historical_key(sensor_key)
                if sensor_obj:
                    legend_name = getattr(sensor_obj, 'name', sensor_key)
                    color_str = getattr(sensor_obj, 'color', None)
            
            return sensor_obj, legend_name, color_str

        # 4. Secondary Axis setup
        needs_secondary = False
        for key in replay_sensor_keys:
            sensor_obj, _, _ = _resolve_sensor_info(key)
            if sensor_obj and getattr(sensor_obj, 'use_secondary_axis', False):
                self.main_window.logger.log(f"Graph Replay: Sensor '{key}' requires secondary axis.", "DEBUG")
                needs_secondary = True
                break
        
        if needs_secondary:
            self.main_window.logger.log("Graph Replay: Constructing secondary Y axis layer.", "DEBUG")
            self.secondary_vb = pg.ViewBox()
            plot_item.scene().addItem(self.secondary_vb)
            right_axis = plot_item.getAxis('right')
            right_axis.linkToView(self.secondary_vb)
            self.secondary_vb.setXLink(plot_item.vb)
            plot_item.showAxis('right')
            def update_views():
                if hasattr(self, 'secondary_vb') and self.secondary_vb:
                    self.secondary_vb.setGeometry(plot_item.vb.sceneBoundingRect())
            plot_item.vb.sigResized.connect(update_views)
            update_views()

        # 5. Process Rows
        self.main_window.logger.log(f"Graph: Processing {len(rows)} rows for replay", "INFO")
        min_x = None
        max_x = None
        self.event_markers = []
        color_index = 0
        
        for row in rows:
            rel_time = float(row.get("_rel_time", 0.0) or 0.0)
            min_x = rel_time if min_x is None else min(min_x, rel_time)
            max_x = rel_time if max_x is None else max(max_x, rel_time)
            for key, val in row.items():
                if key in ("timestamp", "_timestamp", "_rel_time") or key.endswith("_timestamp"): continue
                if key in automation_columns: continue
                
                if key not in self.dashboard_plot_data:
                    try:
                        sensor_obj, legend_name, color_str = _resolve_sensor_info(key)
                        color = QColor(color_str) if color_str else pg.intColor(color_index)
                        if not color_str: color_index += 1
                        
                        pen = pg.mkPen(color=color, width=2)
                        use_sec = sensor_obj and getattr(sensor_obj, 'use_secondary_axis', False)
                        
                        if use_sec and self.secondary_vb:
                            self.main_window.logger.log(f"Graph Replay: Adding '{legend_name}' to secondary axis.", "DEBUG")
                            plot_item_obj = pg.PlotDataItem([], [], pen=pen, name=legend_name, connect='finite')
                            self.secondary_vb.addItem(plot_item_obj)
                            if self.dashboard_graph_widget.legend: 
                                self.dashboard_graph_widget.legend.addItem(plot_item_obj, legend_name)
                        else:
                            plot_item_obj = self.dashboard_graph_widget.plot([], [], pen=pen, name=legend_name, connect='finite')
                        
                        self.dashboard_plot_data[key] = {
                            "x": [], 
                            "y": [], 
                            "plot_item": plot_item_obj, 
                            "name": legend_name, 
                            "sensor_obj": sensor_obj,
                            "use_secondary": bool(use_sec)
                        }
                    except Exception as e:
                        self.main_window.logger.log(f"Graph Replay: Error creating plot for '{key}': {e}", "ERROR")
                        continue
                
                if val is not None and val != "":
                    try:
                        val_f = float(val)
                        self.dashboard_plot_data[key]["x"].append(rel_time)
                        self.dashboard_plot_data[key]["y"].append(val_f)
                    except (TypeError, ValueError): pass
            if any(row.get(col) for col in automation_columns):
                event = {"timestamp": row.get("_timestamp", time.time()), "type": "replay_event", "sequence_name": row.get("automation_sequence", ""), "trigger_description": row.get("automation_trigger", ""), "action_description": row.get("automation_action", ""), "image_path": row.get("automation_image", "")}
                self.add_event_marker(event)

        # 6. Finalize datasets
        for key, plot_info in self.dashboard_plot_data.items():
            if plot_info["x"]:
                plot_info["x"] = np.array(plot_info["x"], dtype=float)
                plot_info["y"] = np.array(plot_info["y"], dtype=float)
                plot_info["plot_item"].setData(plot_info["x"], plot_info["y"])

        if min_x is None or max_x is None:
            self._warn("Graph: No data found in replay")
            return

        self.replay_data_bounds = (min_x, max_x)
        try:
            pen = pg.mkPen(color="#ffaa00", width=2, style=pg.QtCore.Qt.PenStyle.DashLine)
            self.replay_playhead_line = pg.InfiniteLine(pos=min_x, angle=90, pen=pen, movable=False)
            self.dashboard_graph_widget.addItem(self.replay_playhead_line)
        except Exception: pass

        try:
            self.dashboard_graph_widget.setXRange(min_x, max_x, padding=0.02)
            self.dashboard_graph_widget.enableAutoRange(axis='y', enable=True)
            if hasattr(self, 'secondary_vb') and self.secondary_vb: self.secondary_vb.enableAutoRange(axis='y', enable=True)
        except Exception: pass

        if rows and not self.dashboard_start_time:
            first_ts = rows[0].get("_timestamp") or rows[0].get("timestamp")
            if first_ts:
                try: self.dashboard_start_time = float(first_ts)
                except: pass

        self._update_dashboard_axis_labels()
        self.replay_dataset_loaded = True
        self.live_plotting_active = False 
        self._update_all_plot_visuals(force=True)
        if self.dashboard_graph_widget and self.show_automation_markers and self.event_markers:
            try: self._add_event_markers_to_graph(self.dashboard_graph_widget, self.dashboard_start_time)
            except: pass

    def update_replay_position(self, rel_time):
        """Move the playhead and adjust view based on the replay time."""
        if not self.replay_dataset_loaded or not self.dashboard_graph_widget:
            return

        rel_time = float(rel_time)
        min_x, max_x = self.replay_data_bounds
        if self.replay_playhead_line:
            try:
                self.replay_playhead_line.setPos(rel_time)
            except Exception:
                pass

        # Determine zoom window from dashboard timespan selection
        window_seconds = None
        if hasattr(self.main_window, "dashboard_timespan"):
            window_seconds = self._parse_timespan_string(self.main_window.dashboard_timespan.currentText())
        elif hasattr(self.main_window, "dashboard_timespan_combo"):
            window_seconds = self._parse_timespan_string(self.main_window.dashboard_timespan_combo.currentText())

        try:
            if window_seconds is None:
                self.dashboard_graph_widget.setXRange(min_x, max_x, padding=0.05)
            else:
                # Center the view on the current position
                # Per user request: timespan amount into past AND into future
                start = max(min_x, rel_time - window_seconds)
                end = min(max_x, rel_time + window_seconds)
                
                # Ensure we have a minimum width to avoid crashes
                if end - start < 0.1:
                    end = start + 0.1
                
                self.dashboard_graph_widget.setXRange(start, end, padding=0)
            vb = self.dashboard_graph_widget.getViewBox()
            if vb:
                vb.enableAutoRange(axis="y", enable=True)
                
            # Update the legend values for the current replay position
            self._update_all_plot_visuals(force=True, elapsed_time_override=rel_time)
        except Exception as e:
            self._warn(f"Graph: Failed to adjust replay view: {e}")
        
    def plot_new_data(self, data):
        """Plot new incoming data point(s)."""
        # In review mode, ignore live incoming data; only accept replay-tagged payloads
        if hasattr(self.main_window, "replay_mode_enabled") and self.main_window.replay_mode_enabled:
            if data.get("_source") != "replay":
                return

        if not self.live_plotting_active:
            return
            
        try:
            # --- Timestamp handling ---
            timestamp = None
            if 'timestamp' in data:
                try:
                    timestamp = float(data['timestamp'])
                except (ValueError, TypeError):
                    timestamp = time.time()
            else:
                timestamp = time.time()

            # Ensure we're using floats for arithmetic
            timestamp = float(timestamp)

            # --- Check for empty plots and reinitialize if needed ---
            # Added a flag to prevent repeated reinitialization in the same call
            if not self.dashboard_plot_data:
                # If we've already tried to initialize in this call, don't do it again
                if getattr(self, '_is_initializing', False):
                    return
                    
                print("DEBUG GRAPH: No plots are set up. Attempting to reinitialize.")
                if hasattr(self.main_window, 'data_collection_controller') and hasattr(self.main_window.data_collection_controller, 'start_time'):
                    self._is_initializing = True
                    try:
                        self.start_live_dashboard_update(self.main_window.data_collection_controller.start_time)
                    finally:
                        self._is_initializing = False
                return # Exit after reinit attempt
            # -----------------------------------------------------------

            # --- Robust Start Time Management ---
            # Source of Truth is always the DataCollectionController if a run is active
            official_start = None
            if hasattr(self.main_window, 'data_collection_controller'):
                official_start = getattr(self.main_window.data_collection_controller, 'start_time', None)
            
            if official_start is not None:
                # Synchronize if we were using a temporary start time
                if self.dashboard_start_time != official_start:
                    self._debug(f"Graph: Synchronizing dashboard_start_time to official run start: {official_start}")
                    self.dashboard_start_time = float(official_start)
            
            if self.dashboard_start_time is None:
                # No official start yet, use this point's timestamp as temporary start
                self.dashboard_start_time = timestamp
                self._debug(f"Graph: Set temporary dashboard_start_time from first data point: {self.dashboard_start_time}")
                
                # Now that we have a start_time, add any pending event markers
                if hasattr(self, 'event_markers') and self.event_markers and self.dashboard_graph_widget:
                    self._debug(f"Graph: Adding {len(self.event_markers)} pending event markers now that start_time is set")
                    self._add_event_markers_to_graph(self.dashboard_graph_widget, self.dashboard_start_time)
            elif not isinstance(self.dashboard_start_time, (float, int)):
                try:
                    self.dashboard_start_time = float(self.dashboard_start_time)
                except (ValueError, TypeError):
                    self.dashboard_start_time = float(timestamp)

            elapsed_time = timestamp - float(self.dashboard_start_time)
            
            # Sanity check for "jumping" timestamps
            if elapsed_time < -5.0:
                # If data is more than 5 seconds "before" the start of the run, 
                # it's likely a sensor with a different clock or a late-arriving packet.
                # Clamping it to 0 prevents the graph from "jumping back" too far.
                self._debug(f"Graph: Warning - received data point from the 'past' (elapsed={elapsed_time:.2f}s). Clamping to 0.")
                elapsed_time = 0.0
            elif elapsed_time < 0:
                elapsed_time = 0.0
            # -----------------------------------

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
            # During replay, allow faster updates if force is requested in data
            is_replay = hasattr(self.main_window, "replay_mode_enabled") and self.main_window.replay_mode_enabled
            update_threshold = self.plot_update_interval
            
            # Check if this is high-speed LabJack data (has labjack_ prefix and multiple data points)
            # Allow faster updates for LabJack to support high-speed data acquisition
            has_labjack_data = any(k.startswith('labjack_') for k in data.keys() if k != 'timestamp')
            if has_labjack_data and len([k for k in data.keys() if k != 'timestamp']) > 0:
                # Allow up to 100 Hz updates for LabJack data (10ms minimum interval)
                update_threshold = 0.01  # 10ms = 100 Hz max visual update rate
            
            if is_replay and data.get("_force_update", False):
                update_threshold = 0.05 # Allow 20Hz updates during replay scrub

            if data_added and (current_time - self.last_plot_update_time > update_threshold):
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
            self._debug(f"Graph: Direct match found for sensor_id='{sensor_id}'")
        # Try for OtherSerial sensors which may have prefixes
        elif sensor_id.startswith("other_serial_"):
            # Extract the actual sensor name from the prefixed key
            unprefixed_key = sensor_id[len("other_serial_"):]
            if unprefixed_key in self.dashboard_plot_data:
                plot_info = self.dashboard_plot_data[unprefixed_key]
                matched_key = unprefixed_key
                self._debug(f"Graph: OtherSerial match found: prefixed_key='{sensor_id}', unprefixed='{unprefixed_key}'")
        # Check for other prefixed keys like arduino_, labjack_, or audio_
        elif any(sensor_id.startswith(prefix) for prefix in ["arduino_", "labjack_", "audio_"]):
            # Extract the actual sensor name from the prefixed key
            if sensor_id.startswith("arduino_"):
                unprefixed_key = sensor_id[len("arduino_"):]
            elif sensor_id.startswith("labjack_"):
                unprefixed_key = sensor_id[len("labjack_"):]
            elif sensor_id.startswith("audio_"):
                unprefixed_key = sensor_id[len("audio_"):]
            
            if unprefixed_key in self.dashboard_plot_data:
                plot_info = self.dashboard_plot_data[unprefixed_key]
                matched_key = unprefixed_key
                self._debug(f"Graph: Prefix match found: prefixed_key='{sensor_id}', unprefixed='{unprefixed_key}'")
        else:
            # Handle generic plugins: just try the sensor_id directly if not caught above
            # (In some cases the sensor_id might already be the full prefixed key)
            if sensor_id in self.dashboard_plot_data:
                plot_info = self.dashboard_plot_data[sensor_id]
                matched_key = sensor_id
            
        if plot_info:
            # Ensure monotonicity to prevent "zigzag" jumping if sensor clocks or timestamps jitter
            if plot_info['x']:
                last_x = plot_info['x'][-1]
                if elapsed_time < last_x:
                    # If it's a small jitter (less than 1s), just clamp to last value
                    if last_x - elapsed_time < 1.0:
                        elapsed_time = last_x
                    else:
                        # Large jump back - likely a sensor reset or major clock desync
                        self._debug(f"Graph: Large negative time jump for {sensor_id} ({elapsed_time - last_x:.2f}s). Skipping point.")
                        return False

            plot_info['x'].append(elapsed_time)
            plot_info['y'].append(value)
            return True
            
        if "other_serial" in sensor_id:
            self._debug(f"Graph: No plot found for OtherSerial sensor: {sensor_id}")
            self._debug(f"Graph: Available plot keys: {list(self.dashboard_plot_data.keys())}")
        return False

    def _update_all_plot_visuals(self, force=False, elapsed_time_override=None):
        """Updates the setData for all plots based on current buffers and selected timespan, and updates legend with current sensor values."""
        # Determine the current time position
        now = time.time()
        
        # Only skip when neither live collection nor replay is active, unless forced
        collecting = hasattr(self.main_window, 'data_collection_controller') and self.main_window.data_collection_controller.collecting_data
        in_replay = hasattr(self.main_window, 'replay_mode_enabled') and self.main_window.replay_mode_enabled
        
        # Sync start time before calculating current position
        # ONLY sync if NOT in replay mode, to avoid overwriting the replay's start_time with a live run's leftover start_time
        if not in_replay and hasattr(self.main_window, 'data_collection_controller'):
            official_start = getattr(self.main_window.data_collection_controller, 'start_time', None)
            if official_start is not None:
                official_start_f = float(official_start)
                if self.dashboard_start_time is None or abs(float(self.dashboard_start_time) - official_start_f) > 0.001:
                    self.dashboard_start_time = official_start_f

        current_elapsed_time = 0
        
        if elapsed_time_override is not None:
            current_elapsed_time = elapsed_time_override
        elif in_replay:
            # For replay mode, use the current playhead position if available
            if hasattr(self, 'replay_playhead_line') and self.replay_playhead_line:
                current_elapsed_time = self.replay_playhead_line.value()
            else:
                # Fallback to the maximum time in the dataset if playhead isn't ready
                # Use numpy for efficiency if possible
                max_t = 0
                for plot_info in self.dashboard_plot_data.values():
                    x_data = plot_info.get('x')
                    if x_data is not None and len(x_data) > 0:
                        # plot_info['x'] should be a numpy array at this point
                        local_max = x_data[-1] if isinstance(x_data, np.ndarray) else max(x_data)
                        if local_max > max_t:
                            max_t = local_max
                current_elapsed_time = max_t
        elif not collecting and not force:
            self._debug("Skipping graph visual update as data collection is not active")
            return
        elif not collecting:
            # If not collecting but forced, use the latest data point
            max_t = 0
            for plot_info in self.dashboard_plot_data.values():
                x_data = plot_info.get('x')
                if x_data is not None and len(x_data) > 0:
                    local_max = x_data[-1] if isinstance(x_data, np.ndarray) else max(x_data)
                    if local_max > max_t:
                        max_t = local_max
            current_elapsed_time = max_t
        else:
            # For live plotting, we use the wall clock to keep the sliding window moving smoothly
            current_elapsed_time = now - self.dashboard_start_time if self.dashboard_start_time else 0

        if not hasattr(self.main_window, 'dashboard_timespan'):
            self._warn("Graph: dashboard_timespan widget not found. Cannot apply timespan filter.")
            return
            
        selected_timespan_str = self.main_window.dashboard_timespan.currentText()
        timespan_seconds = self._parse_timespan_string(selected_timespan_str)
        
        # Determine the X range for the view
        if timespan_seconds is not None:
            if in_replay:
                # Replay mode: Centered window (past and future)
                min_time = current_elapsed_time - timespan_seconds
                max_time = current_elapsed_time + timespan_seconds
            else:
                # Live mode: Trailing window
                min_time = current_elapsed_time - timespan_seconds
                max_time = current_elapsed_time
            
            # Apply the range to the graph
            if self.dashboard_graph_widget:
                self.main_window.logger.log(f"Graph: Setting dashboard X range: {min_time:.2f} to {max_time:.2f} (current={current_elapsed_time:.2f}, timespan={timespan_seconds})", "DEBUG")
                # Only apply if not in "All" mode (which is handled by auto-range)
                self.dashboard_graph_widget.setXRange(min_time, max_time, padding=0)
        else:
            # "All" selected or invalid timespan - show all data
            if self.dashboard_graph_widget:
                # If we have an override (replay playhead scrubbing), we might want to keep the current range
                # but for "All" it's usually best to auto-range
                if elapsed_time_override is None:
                    self.dashboard_graph_widget.enableAutoRange(axis='x', enable=True)
                    self.dashboard_graph_widget.enableAutoRange(axis='y', enable=True)
                    if hasattr(self, 'secondary_vb') and self.secondary_vb:
                        # ONLY auto-range Y for secondary axis; X is linked to main
                        self.secondary_vb.enableAutoRange(axis='y', enable=True)
                else:
                    # In scrubbing mode, ensure secondary Y still auto-ranges
                    if hasattr(self, 'secondary_vb') and self.secondary_vb:
                        self.secondary_vb.enableAutoRange(axis='y', enable=True)

        # min_time_val is used for data slicing below
        min_time_val = -np.inf
        if timespan_seconds is not None:
             min_time_val = current_elapsed_time - timespan_seconds
             # Clamp min_time_val to 0 if it's very small and negative to avoid slicing issues
             if min_time_val < 0 and min_time_val > -0.001:
                 min_time_val = 0.0

        # --- Update plot data and legend names with current values ---
        for sensor_id, plot_info in self.dashboard_plot_data.items():
            if not plot_info.get('plot_item'):
                continue
                
            x_data = plot_info.get('x', [])
            y_data = plot_info.get('y', [])
            
            if len(x_data) == 0:
                continue

            try:
                # 1. Update Plot Data (Slicing/Filtering)
                if timespan_seconds is not None:
                    # Efficiently find the start index for the visible timespan
                    if isinstance(x_data, np.ndarray):
                        start_idx = np.searchsorted(x_data, min_time_val)
                    else:
                        start_idx = bisect.bisect_left(x_data, min_time_val)
                    
                    if start_idx < len(x_data):
                        # Use slicing (O(1) for numpy, O(k) for list)
                        # Load data for the entire visible range
                        # In replay, we need past and future data
                        # In live mode, max_time_val is essentially "now"
                        max_time_val = current_elapsed_time + (timespan_seconds if in_replay else 0)
                        
                        if isinstance(x_data, np.ndarray):
                            end_idx = np.searchsorted(x_data, max_time_val, side='right')
                        else:
                            end_idx = bisect.bisect_right(x_data, max_time_val)
                        
                        plot_info['plot_item'].setData(x_data[start_idx:end_idx], y_data[start_idx:end_idx])
                    else:
                        plot_info['plot_item'].setData([], [])
                else:
                    # "All" selected - show full buffer
                    plot_info['plot_item'].setData(x_data, y_data)
            except Exception as e:
                self._debug(f"Graph: Error updating data for {sensor_id}: {e}")

            # 2. Update Legend (Current Value)
            value_str = "N/A"
            try:
                # Find value at current playhead/time
                if in_replay or elapsed_time_override is not None:
                    # For replay, we always use the indexed value from the data buffer
                    if isinstance(x_data, np.ndarray):
                        idx = np.searchsorted(x_data, current_elapsed_time)
                    else:
                        idx = bisect.bisect_left(x_data, current_elapsed_time)
                        
                    if idx >= len(y_data):
                        idx = len(y_data) - 1
                    
                    if idx >= 0:
                        val = y_data[idx]
                        value_str = f"{val:.2f}" if val is not None else "N/A"
                else:
                    # For live mode, use the latest value from the sensor object
                    sensor_obj = plot_info.get('sensor_obj')
                    if sensor_obj:
                        val = getattr(sensor_obj, 'current_value', None)
                        value_str = f"{val:.2f}" if val is not None else "N/A"
            except Exception:
                pass

            unit = None
            if plot_info.get('sensor_obj'):
                unit = getattr(plot_info.get('sensor_obj'), 'unit', None)
            
            if unit:
                value_str = f"{value_str} {unit}"
            
            legend_name = f"{plot_info['name']} ({value_str})"
            
            # 3. Fast Legend Label Update
            try:
                plot_item_parent = self.dashboard_graph_widget.getPlotItem()
                legend = getattr(plot_item_parent, 'legend', None)
                if not legend:
                    legend = getattr(self.dashboard_graph_widget, 'legend', None)
                
                if legend:
                    # Check if we have a cached label for this sensor
                    label = self._dashboard_legend_labels.get(sensor_id)
                    if label:
                        try:
                            label.setText(legend_name)
                        except Exception:
                            # If label is orphaned, remove from cache to trigger re-add
                            if sensor_id in self._dashboard_legend_labels:
                                del self._dashboard_legend_labels[sensor_id]
                            label = None
                    
                    if not label:
                        # Robust iteration for different pyqtgraph versions
                        try:
                            # LegendItem.items is a list of tuples (ItemSample, LabelItem) or ItemRecord
                            for item in list(legend.items):
                                try:
                                    # Handle both ItemRecord (newer) and tuple (older)
                                    if hasattr(item, 'sample') and hasattr(item, 'label'):
                                        sample = item.sample
                                        lbl = item.label
                                    elif isinstance(item, (list, tuple)) and len(item) >= 2:
                                        sample = item[0]
                                        lbl = item[1]
                                    else:
                                        continue

                                    actual_item = getattr(sample, 'item', sample)
                                    if actual_item is plot_info['plot_item']:
                                        lbl.setText(legend_name)
                                        self._dashboard_legend_labels[sensor_id] = lbl
                                        label = lbl
                                        break
                                except Exception:
                                    continue
                        except Exception:
                            pass
                        
                        if not label:
                            # Not in legend yet, add it
                            legend.addItem(plot_info['plot_item'], legend_name)
                            # Re-scan to catch the label reference
                            for sample, lbl in legend.items:
                                actual_item = getattr(sample, 'item', sample)
                                if actual_item is plot_info['plot_item']:
                                    self._dashboard_legend_labels[sensor_id] = lbl
                                    break
                    
                    # Ensure legend appearance
                    legend.setBrush(pg.mkBrush(20, 20, 30, 180))
                    legend.setPen(pg.mkPen(150, 150, 150, 150))
                    legend.setZValue(1000)
                    legend.setVisible(True)
            except Exception as e:
                pass

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

    def _get_sensor_display_name(self, sensor_key):
        """
        Get display name for a sensor, handling both regular and control sensors.
        
        Args:
            sensor_key: Sensor key (may have '_ctrl' suffix for control sensors)
            
        Returns:
            Display name for the sensor
        """
        if sensor_key.endswith('_ctrl'):
            # Control sensor - strip _ctrl suffix and add (Control) label
            base_key = sensor_key[:-5]  # Remove '_ctrl'
            return f"{base_key} (Control)"
        else:
            # Regular sensor - use sensor controller to get name
            name = self.main_window.sensor_controller.get_sensor_name_by_historical_key(sensor_key)
            return name if name else sensor_key
    
    def update_specific_graph(self, graph_widget, primary_sensor_key, secondary_sensor_key, timespan, graph_type, multi_sensor_keys, window_size, histogram_bins, is_main_graph=False, show_control_run=False, control_run_data=None):
        """Update a specific graph widget based on selected parameters using historical keys."""
        if not graph_widget:
            self.main_window.logger.error("update_specific_graph called with invalid graph_widget")
            return

        if not hasattr(self.main_window, 'data_collection_controller') or not hasattr(self.main_window, 'sensor_controller'):
            self.main_window.logger.error("DataCollectionController or SensorController not found for updating graph")
            return
            
        # Use sensor controller to get display names from keys for logging/titles
        primary_sensor_name = self._get_sensor_display_name(primary_sensor_key) if primary_sensor_key else "None"
        secondary_sensor_name = self._get_sensor_display_name(secondary_sensor_key) if secondary_sensor_key else "None"
        
        self.main_window.logger.info(f"Updating graph: Type='{graph_type}', Primary='{primary_sensor_name}' (key:{primary_sensor_key}), Timespan='{timespan}'")

        try:
            # Handle main legend - search multiple possible locations
            leg = getattr(graph_widget, 'legend', None)
            if not leg:
                # Try getting it from PlotItem
                p_item = graph_widget.getPlotItem()
                if p_item:
                    leg = getattr(p_item, 'legend', None)
                
            if leg:
                try:
                    leg.clear()
                    # Remove from scene if possible
                    sc = leg.scene()
                    if sc:
                        sc.removeItem(leg)
                    leg.setParentItem(None)
                except Exception:
                    pass
                
            # Clear the references everywhere
            if hasattr(graph_widget, 'legend'):
                graph_widget.legend = None
            p_item = graph_widget.getPlotItem()
            if p_item and hasattr(p_item, 'legend'):
                p_item.legend = None
        except Exception as e:
            self._debug(f"Graph: Error clearing legend during pre-clear: {e}")
        graph_widget.legend = None

        if is_main_graph and hasattr(self, 'main_secondary_vb') and self.main_secondary_vb:
            try:
                for item in self.main_secondary_vb.allChildItems():
                    self.main_secondary_vb.removeItem(item)
                graph_widget.getPlotItem().scene().removeItem(self.main_secondary_vb)
            except Exception as e:
                self._debug(f"Graph: Error clearing secondary ViewBox during pre-clear: {e}")
            self.main_secondary_vb = None
        graph_widget.getPlotItem().hideAxis('right')
        # -------------------------

        # Clear the graph
        graph_widget.clear()
        
        # Configure global downsampling on the PlotItem for better performance
        try:
            # Check for setting
            downsampling_enabled = True
            if hasattr(self.main_window, 'graph_downsampling_checkbox'):
                downsampling_enabled = self.main_window.graph_downsampling_checkbox.isChecked()
            elif self.settings_model:
                downsampling_enabled = self.settings_model.get_bool("graph_downsampling", True)

            plot_item = graph_widget.getPlotItem()
            if downsampling_enabled:
                plot_item.setDownsampling(ds=True, auto=True, mode='peak')
            else:
                plot_item.setDownsampling(ds=False)
            plot_item.setClipToView(True)
        except Exception as e:
            self._debug(f"Graph: Could not set global downsampling: {e}")

        # Re-add legend
        legend = graph_widget.addLegend()
        graph_widget.legend = legend
        graph_widget.showGrid(x=True, y=True, alpha=0.3)
        graph_widget.setLabel('bottom', 'Elapsed Time (s)')
        graph_widget.setLabel('left', 'Value') # Default Y label
        
        # Note: Event markers will be added after we fetch the data, so we can calculate
        # the correct start_time from the actual data being plotted

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
                
        # --- Secondary Axis Setup for Main Graph ---
        # First, clear any previous secondary viewbox from this graph widget
        if is_main_graph:
            if hasattr(self, 'main_secondary_vb') and self.main_secondary_vb:
                try:
                    # Explicitly remove all items from secondary ViewBox before deleting it
                    for item in self.main_secondary_vb.allChildItems():
                        self.main_secondary_vb.removeItem(item)
                    graph_widget.getPlotItem().scene().removeItem(self.main_secondary_vb)
                except Exception:
                    pass
                self.main_secondary_vb = None
            graph_widget.getPlotItem().hideAxis('right')
        # --------------------------------------------

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
        self._debug(f"Graph: Required sensor keys for graph: {required_sensor_keys}")
        
        # Separate control sensor keys (ending with _ctrl) from regular keys
        control_sensor_keys = [k for k in required_sensor_keys if k.endswith('_ctrl')]
        regular_sensor_keys = [k for k in required_sensor_keys if not k.endswith('_ctrl')]
        
        if control_sensor_keys:
            self._debug(f"Graph: Control sensor keys: {control_sensor_keys}")
        if regular_sensor_keys:
            self._debug(f"Graph: Regular sensor keys: {regular_sensor_keys}")
        
        # Check for any OtherSerial sensors in the required keys
        other_serial_keys = [k for k in regular_sensor_keys if 'other_serial' in k]
        if other_serial_keys:
            self._debug(f"Graph: OtherSerial sensors in regular keys: {other_serial_keys}")
        
        # Determine the start_time to use for relative time calculation
        # PRIORITY: DCC Source of Truth > dashboard_start_time
        graph_start_time = None
        if hasattr(self.main_window, 'data_collection_controller'):
            dc = self.main_window.data_collection_controller
            # Use active run start time if it exists
            graph_start_time = getattr(dc, 'start_time', None)
            
        # Fallback to internal dashboard start time if run haven't started or DCC not found
        if graph_start_time is None:
            graph_start_time = self.dashboard_start_time
        
        # Ensure we update our internal dashboard_start_time if DCC has a more official one
        if graph_start_time is not None and self.dashboard_start_time is None:
            self.dashboard_start_time = graph_start_time
        # -----------------------------------------------------------------
        
        # Fetch data (assuming a method in DataCollectionController)
        try:
            # Fetch current/historical data for regular sensors
            data_to_plot = {}
            if regular_sensor_keys:
                data_to_plot = self.main_window.data_collection_controller.get_historical_data(
                    sensor_ids=regular_sensor_keys,
                    timespan_seconds=timespan_seconds,
                    start_time=graph_start_time
                )
                self._debug(f"Graph: Fetched {len(data_to_plot)} regular sensors with start_time={graph_start_time}")
            
            # Handle control sensors
            if control_sensor_keys:
                if control_run_data is None:
                    # Control sensors selected but no control run data available
                    self._warn(f"Control sensors selected ({control_sensor_keys}) but no control run configured or loaded")
                else:
                    # Add control run data for control sensors
                    if hasattr(self.main_window, 'logger'):
                        self.main_window.logger.debug(f"Adding control run data for {len(control_sensor_keys)} control sensors")
                    
                    for ctrl_key in control_sensor_keys:
                        if ctrl_key in control_run_data:
                            # Apply timespan filter if needed
                            ctrl_data = control_run_data[ctrl_key]
                            if timespan_seconds is not None and len(ctrl_data['time']) > 0:
                                # Filter data to only include points within timespan
                                # numpy is already imported at the top of the file
                                times = np.array(ctrl_data['time'])
                                values = np.array(ctrl_data['value'])
                                max_time = times[-1] if len(times) > 0 else 0
                                min_time = max_time - timespan_seconds
                                mask = times >= min_time
                                data_to_plot[ctrl_key] = {
                                    'time': times[mask].tolist(),
                                    'value': values[mask].tolist()
                                }
                            else:
                                # No timespan filter, use all data
                                data_to_plot[ctrl_key] = {
                                    'time': ctrl_data['time'].copy() if isinstance(ctrl_data['time'], list) else ctrl_data['time'].tolist(),
                                    'value': ctrl_data['value'].copy() if isinstance(ctrl_data['value'], list) else ctrl_data['value'].tolist()
                                }
                            if hasattr(self.main_window, 'logger'):
                                self.main_window.logger.debug(f"Added control data for '{ctrl_key}': {len(data_to_plot[ctrl_key]['time'])} points")
                        else:
                            if hasattr(self.main_window, 'logger'):
                                self.main_window.logger.warning(f"Control sensor '{ctrl_key}' not found in control run data")
            
            # Debug any OtherSerial data retrieved
            for key, data in data_to_plot.items():
                if 'other_serial' in key:
                    self._debug(f"Graph: Found OtherSerial data for key '{key}': {len(data['time'])} points")
                    if len(data['time']) > 0:
                        self._debug(f"Graph: First few values: {data['value'][:5]}")
                        
        except AttributeError:
            self.main_window.logger.error("'get_historical_data' method not found in DataCollectionController.")
            graph_widget.setTitle("Error: Could not fetch data")
            return
        except Exception as e:
            self.main_window.logger.error(f"Error fetching historical data: {e}")
            graph_widget.setTitle("Error fetching data")
            return

        if not data_to_plot:
            graph_widget.setTitle(f"No data available for selected sensors/timespan")
            self.main_window.logger.debug(f"No historical data returned for keys: {required_sensor_keys}, timespan: {timespan}")
            return

        # Apply current formatting settings before plotting
        self.apply_plot_formatting() 

        # --- Plotting Logic ---
        try:
            # Determine current elapsed time for gap injection and view range calculation
            now = time.time()
            collecting = hasattr(self.main_window, 'data_collection_controller') and self.main_window.data_collection_controller.collecting_data
            # Also allow gaps if live plotting is active (monitoring)
            is_monitoring = getattr(self, 'live_plotting_active', False)
            
            # Use the resolved graph_start_time for consistent relative timing
            start_ref = graph_start_time if graph_start_time is not None else self.dashboard_start_time
            current_elapsed_time = 0
            if (collecting or is_monitoring) and start_ref is not None:
                current_elapsed_time = now - float(start_ref)
            
            if graph_type == "Standard Time Series":
                graph_widget.setTitle(f"Time Series - Timespan: {timespan}")
                graph_widget.setLabel('left', 'Sensor Value')
                
                sensors_keys_to_plot = [primary_sensor_key] + multi_sensor_keys
                sensors_keys_to_plot = list(set(filter(None, sensors_keys_to_plot))) # Unique, non-empty keys
                
                # --- Secondary Axis setup for Main Graph ---
                if is_main_graph:
                    needs_secondary = False
                    for sensor_key in sensors_keys_to_plot:
                        # Control sensors use same axis as base sensor
                        lookup_key = sensor_key[:-5] if sensor_key.endswith('_ctrl') else sensor_key
                        sensor_obj = self.main_window.sensor_controller.get_sensor_by_historical_key(lookup_key)
                        if sensor_obj and getattr(sensor_obj, 'use_secondary_axis', False):
                            needs_secondary = True
                            break
                    
                    if needs_secondary:
                        plot_item = graph_widget.getPlotItem()
                        self.main_secondary_vb = pg.ViewBox()
                        plot_item.scene().addItem(self.main_secondary_vb)
                        right_axis = plot_item.getAxis('right')
                        right_axis.linkToView(self.main_secondary_vb)
                        self.main_secondary_vb.setXLink(plot_item.vb)
                        plot_item.showAxis('right')
                        
                        def update_main_views():
                            if hasattr(self, 'main_secondary_vb') and self.main_secondary_vb:
                                self.main_secondary_vb.setGeometry(plot_item.vb.sceneBoundingRect())
                        plot_item.vb.sigResized.connect(update_main_views)
                        update_main_views()
                # ---------------------------------------------

                for sensor_key in sensors_keys_to_plot:
                    if sensor_key in data_to_plot and len(data_to_plot[sensor_key]['time']) > 0:
                        data = data_to_plot[sensor_key]
                        times = np.array(data['time'], dtype=float)
                        values = np.array(data['value'], dtype=float)

                        # Inject a NaN point at "now" when the sensor is stale, so gaps appear immediately (like dashboard)
                        try:
                            dc = getattr(self.main_window, 'data_collection_controller', None)
                            if dc:
                                # Prefixed keys are used in historical buffer (e.g., arduino_temp)
                                pref_key = sensor_key
                                # Determine per-sensor timeout if available, else fall back
                                stale_timeout = None
                                if hasattr(dc, '_get_stale_timeout_for_key'):
                                    stale_timeout = dc._get_stale_timeout_for_key(pref_key)
                                if stale_timeout is None:
                                    stale_timeout = getattr(dc, 'stale_timeout_seconds', None)

                                if stale_timeout and stale_timeout > 0 and times.size > 0:
                                    last_rel = float(times[-1])
                                    # current elapsed time matches dashboard clock
                                    current_rel = current_elapsed_time
                                    if (current_rel - last_rel) > stale_timeout:
                                        times = np.append(times, current_rel)
                                        values = np.append(values, np.nan)
                        except Exception:
                            pass
                        
                        # Get sensor display name
                        sensor_name = self._get_sensor_display_name(sensor_key)
                        
                        # Determine if this is a control sensor
                        is_control = sensor_key.endswith('_ctrl')
                        
                        # Get color - for control sensors, try to match the color of the corresponding current sensor
                        if is_control:
                            # Strip _ctrl and find matching sensor
                            base_key = sensor_key[:-5]
                            base_sensor_obj = self.main_window.sensor_controller.get_sensor_by_historical_key(base_key)
                            color = getattr(base_sensor_obj, 'color', '#FFFFFF') if base_sensor_obj else '#FFFFFF'
                        else:
                            # Regular sensor
                            sensor_obj = self.main_window.sensor_controller.get_sensor_by_historical_key(sensor_key)
                            color = getattr(sensor_obj, 'color', '#FFFFFF') if sensor_obj else '#FFFFFF'
                        
                        # Create pen - dashed for control sensors, solid for regular sensors
                        line_width = getattr(self.main_window, 'plot_line_width_value', 2)
                        if is_control:
                            pen = pg.mkPen(color=color, width=line_width, style=pg.QtCore.Qt.PenStyle.DashLine)
                        else:
                            pen = pg.mkPen(color=color, width=line_width)
                        
                        # --- Append latest value to legend ---
                        value_str = "N/A"
                        if len(values) > 0:
                            try:
                                value_str = f"{values[-1]:.2f}"
                            except Exception:
                                value_str = str(values[-1])
                            
                            # Try to get unit - for control sensors, look up the base sensor
                            unit = None
                            if is_control:
                                base_key = sensor_key[:-5]
                                base_sensor_obj = self.main_window.sensor_controller.get_sensor_by_historical_key(base_key)
                                if base_sensor_obj:
                                    unit = getattr(base_sensor_obj, 'unit', None)
                            else:
                                sensor_obj = self.main_window.sensor_controller.get_sensor_by_historical_key(sensor_key)
                                if sensor_obj:
                                    unit = getattr(sensor_obj, 'unit', None)
                            
                            if unit:
                                value_str = f"{value_str} {unit}"
                        
                        legend_name = f"{sensor_name} ({value_str})"
                        # connect='finite' prevents lines across NaN/None gaps
                        # Create plot with performance optimizations
                        
                        # Determine if this sensor should go on secondary axis
                        lookup_key = sensor_key[:-5] if sensor_key.endswith('_ctrl') else sensor_key
                        sensor_obj = self.main_window.sensor_controller.get_sensor_by_historical_key(lookup_key)
                        use_secondary = sensor_obj and getattr(sensor_obj, 'use_secondary_axis', False)
                        
                        if is_main_graph and use_secondary and hasattr(self, 'main_secondary_vb') and self.main_secondary_vb:
                            plot_item_obj = pg.PlotDataItem(
                                times, values, 
                                pen=pen, 
                                name=legend_name, 
                                connect='finite'
                            )
                            self.main_secondary_vb.addItem(plot_item_obj)
                            # Add to legend manually for secondary ViewBox items
                            if legend:
                                legend.addItem(plot_item_obj, legend_name)
                        else:
                            graph_widget.plot(
                                times, values, 
                                pen=pen, 
                                name=legend_name, 
                                connect='finite'
                            )
                    else:
                         self.main_window.logger.warning(f"No data found for sensor key '{sensor_key}' in Standard Time Series plot")

                # Update main graph labels if needed
                if is_main_graph:
                    self._update_main_graph_axis_labels(graph_widget, sensors_keys_to_plot)

            elif graph_type == "Temperature Difference":
                graph_widget.setTitle(f"Temperature Difference ({primary_sensor_name} - {secondary_sensor_name}) - Timespan: {timespan}")
                graph_widget.setLabel('left', 'Difference (°C or unit)')
                if primary_sensor_key and secondary_sensor_key and primary_sensor_key in data_to_plot and secondary_sensor_key in data_to_plot:
                    data1 = data_to_plot[primary_sensor_key]
                    data2 = data_to_plot[secondary_sensor_key]
                    
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
                    
                    # Get primary sensor color
                    sensor_obj = self.main_window.sensor_controller.get_sensor_by_historical_key(primary_sensor_key)
                    color = getattr(sensor_obj, 'color', '#FFFFFF') if sensor_obj else '#FFFFFF'
                    
                    pen = pg.mkPen(color=color, width=getattr(self.main_window, 'plot_line_width_value', 2))
                    graph_widget.plot(
                        time_combined, difference, 
                        pen=pen, 
                        name=f"{primary_sensor_name}-{secondary_sensor_name}"
                    ) # Use names in legend
                else:
                    graph_widget.setTitle("Select two valid sensors for difference plot")

            elif graph_type == "Rate of Change (dT/dt)":
                graph_widget.setTitle(f"Rate of Change ({primary_sensor_name}) - Timespan: {timespan}")
                graph_widget.setLabel('left', 'Rate (unit/s)')
                if primary_sensor_key and primary_sensor_key in data_to_plot and len(data_to_plot[primary_sensor_key]['time']) > 1:
                    data = data_to_plot[primary_sensor_key]
                    # Ensure data is numerical numpy arrays
                    times = np.array(data['time'], dtype=float)
                    values = np.array(data['value'], dtype=float)
                    
                    # Calculate gradient (rate of change)
                    rate = np.gradient(values, times)
                    
                    # Get primary sensor color
                    sensor_obj = self.main_window.sensor_controller.get_sensor_by_historical_key(primary_sensor_key)
                    color = getattr(sensor_obj, 'color', '#FFFFFF') if sensor_obj else '#FFFFFF'
                    
                    pen = pg.mkPen(color=color, width=getattr(self.main_window, 'plot_line_width_value', 2))
                    graph_widget.plot(
                        times, rate, 
                        pen=pen, 
                        name=f"d({primary_sensor_name})/dt"
                    ) # Use name in legend
                else:
                     graph_widget.setTitle("Select a valid sensor with at least 2 data points for rate plot")

            elif graph_type == "Moving Average":
                graph_widget.setTitle(f"Moving Average ({primary_sensor_name}, Window: {window_size}) - Timespan: {timespan}")
                graph_widget.setLabel('left', 'Smoothed Value')
                if primary_sensor_key and primary_sensor_key in data_to_plot and window_size is not None and window_size > 1 and len(data_to_plot[primary_sensor_key]['time']) >= window_size:
                    data = data_to_plot[primary_sensor_key]
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
                    
                    # Get primary sensor color
                    sensor_obj = self.main_window.sensor_controller.get_sensor_by_historical_key(primary_sensor_key)
                    color = getattr(sensor_obj, 'color', '#FFFFFF') if sensor_obj else '#FFFFFF'
                    
                    avg_pen = pg.mkPen(color=color, width=line_width)
                    
                    # Create a semi-transparent version for standard deviation
                    std_color = QColor(color)
                    std_color.setAlpha(100)
                    std_pen = pg.mkPen(color=std_color, width=1, style=pg.QtCore.Qt.PenStyle.DashLine)

                    # Plot average
                    graph_widget.plot(
                        time_avg, moving_avg, 
                        pen=avg_pen, 
                        name=f"Avg({primary_sensor_name}, N={window_size})"
                    )

                    # Plot +/- 1 Standard Deviation Lines
                    graph_widget.plot(
                        time_avg, moving_avg + moving_std, 
                        pen=std_pen, 
                        name=f"+1 Std Dev"
                    )
                    graph_widget.plot(
                        time_avg, moving_avg - moving_std, 
                        pen=std_pen, 
                        name=f"-1 Std Dev"
                    )

                    # Optional: Fill between standard deviations (can be visually busy)
                    # fill_brush = pg.mkBrush(255, 255, 0, 50) # Semi-transparent yellow
                    # fill = pg.FillBetweenItem(curve1=upper_std_line, curve2=lower_std_line, brush=fill_brush)
                    # graph_widget.addItem(fill)

                else:
                    graph_widget.setTitle("Select sensor, ensure sufficient data and valid window size (>1) for moving average")
            
            elif graph_type == "Fourier Analysis":
                graph_widget.setLabel('bottom', 'Frequency (Hz)')
                graph_widget.setLabel('left', 'Amplitude')
                legend.setVisible(False)  # Legend not very useful for FFT
                
                if primary_sensor_key and primary_sensor_key in data_to_plot and len(data_to_plot[primary_sensor_key]['time']) > 1:
                    data = data_to_plot[primary_sensor_key]
                    # Ensure data is numerical numpy arrays
                    times = np.array(data['time'], dtype=float)
                    values = np.array(data['value'], dtype=float)
                    
                    n = len(values)
                    if n < 8:  # Need at least 8 points for meaningful FFT
                        graph_widget.setTitle("Not enough data for Fourier Analysis (min. 8 points)")
                        return
                         
                    # Calculate average sample spacing, check for validity
                    sample_spacing = np.mean(np.diff(times)) 
                    if sample_spacing <= 0 or np.isnan(sample_spacing):
                        graph_widget.setTitle("Invalid or non-uniform time data for Fourier Analysis")
                        return
                    
                    sample_rate = 1.0 / sample_spacing
                    nyquist_freq = sample_rate / 2.0
                    
                    # Apply Hanning window for cleaner spectrum (reduces spectral leakage)
                    window = np.hanning(n)
                    # Remove DC offset and apply window
                    values_windowed = (values - np.mean(values)) * window
                    
                    yf = fft(values_windowed)
                    xf = fftfreq(n, sample_spacing)[:n//2]  # Get positive frequencies
                    
                    amplitude = 2.0/n * np.abs(yf[0:n//2])
                    
                    # Plot the spectrum
                    line_width = getattr(self.main_window, 'plot_line_width_value', 2)
                    
                    # Get primary sensor color
                    sensor_obj = self.main_window.sensor_controller.get_sensor_by_historical_key(primary_sensor_key)
                    color = getattr(sensor_obj, 'color', '#FFFFFF') if sensor_obj else '#FFFFFF'
                    
                    graph_widget.plot(
                        xf, amplitude, 
                        pen=pg.mkPen(color=color, width=line_width)
                    )
                    
                    # === Peak Detection ===
                    # Find peaks above noise threshold (5% of max amplitude)
                    max_amplitude = np.max(amplitude)
                    noise_threshold = max_amplitude * 0.05
                    
                    # Only consider frequencies above 0.5 Hz (ignore near-DC)
                    valid_indices = np.where((xf > 0.5) & (amplitude > noise_threshold))[0]
                    
                    if len(valid_indices) > 0:
                        # Find local maxima (simple peak detection)
                        peaks = []
                        for i in valid_indices:
                            if i > 0 and i < len(amplitude) - 1:
                                if amplitude[i] > amplitude[i-1] and amplitude[i] > amplitude[i+1]:
                                    peaks.append((xf[i], amplitude[i], i))
                        
                        # Sort by amplitude (descending) and take top 5
                        peaks.sort(key=lambda x: x[1], reverse=True)
                        top_peaks = peaks[:5]
                        
                        if len(top_peaks) > 0:
                            # Fundamental frequency is the strongest peak
                            fundamental_freq = top_peaks[0][0]
                            fundamental_amp = top_peaks[0][1]
                            
                            # === Mark peaks on the plot ===
                            colors = ['#FF5722', '#FFC107', '#03A9F4', '#E91E63', '#9C27B0']  # Orange, Yellow, Blue, Pink, Purple
                            peak_info_parts = []
                            
                            for idx, (freq, amp, _) in enumerate(top_peaks):
                                color = colors[idx % len(colors)]
                                
                                # Vertical line at peak frequency
                                peak_line = pg.InfiniteLine(
                                    pos=freq, 
                                    angle=90, 
                                    pen=pg.mkPen(color=color, width=1, style=Qt.PenStyle.DashLine)
                                )
                                graph_widget.addItem(peak_line)
                                
                                # Text label for the peak
                                # Check if this might be a harmonic of fundamental
                                harmonic_num = None
                                if idx > 0 and fundamental_freq > 0:
                                    ratio = freq / fundamental_freq
                                    # Check if it's close to an integer multiple (within 5%)
                                    for h in range(2, 11):
                                        if abs(ratio - h) < 0.05 * h:
                                            harmonic_num = h
                                            break
                                
                                if harmonic_num:
                                    label_text = f"{freq:.1f} Hz ({harmonic_num}x)"
                                else:
                                    label_text = f"{freq:.1f} Hz"
                                
                                text_item = pg.TextItem(label_text, color=color, anchor=(0, 1))
                                text_item.setPos(freq, amp)
                                graph_widget.addItem(text_item)
                                
                                # Collect info for title
                                if idx == 0:
                                    peak_info_parts.append(f"f₀={freq:.2f} Hz")
                                elif harmonic_num:
                                    peak_info_parts.append(f"{harmonic_num}x")
                            
                            # === Calculate THD if harmonics detected ===
                            harmonic_amplitudes_sq = []
                            for h in range(2, 11):  # 2nd to 10th harmonic
                                target_freq = fundamental_freq * h
                                if target_freq < nyquist_freq:
                                    # Find closest frequency bin
                                    closest_idx = np.argmin(np.abs(xf - target_freq))
                                    harmonic_amplitudes_sq.append(amplitude[closest_idx] ** 2)
                            
                            if fundamental_amp > 0 and len(harmonic_amplitudes_sq) > 0:
                                thd = np.sqrt(sum(harmonic_amplitudes_sq)) / fundamental_amp * 100
                                thd_text = f" | THD={thd:.1f}%"
                            else:
                                thd_text = ""
                            
                            # Build title with peak info
                            peaks_str = ", ".join(peak_info_parts[:3])  # Show max 3 peaks in title
                            graph_widget.setTitle(
                                f"FFT: {primary_sensor_name} | {peaks_str}{thd_text} | SR={sample_rate:.1f} Hz"
                            )
                        else:
                            graph_widget.setTitle(f"FFT: {primary_sensor_name} | No significant peaks | SR={sample_rate:.1f} Hz")
                    else:
                        graph_widget.setTitle(f"FFT: {primary_sensor_name} | No peaks above threshold | SR={sample_rate:.1f} Hz")
                else:
                    graph_widget.setTitle(f"Select a sensor with sufficient data for Fourier Analysis ({primary_sensor_name})")

            elif graph_type == "Histogram":
                graph_widget.setTitle(f"Histogram ({primary_sensor_name}, Bins: {histogram_bins}) - Timespan: {timespan}")
                graph_widget.setLabel('bottom', 'Sensor Value')
                graph_widget.setLabel('left', 'Frequency')
                legend.setVisible(False)
                if primary_sensor_key and primary_sensor_key in data_to_plot and histogram_bins is not None and histogram_bins > 0 and len(data_to_plot[primary_sensor_key]['value']) > 0:
                    # Ensure data is numerical numpy arrays
                    values = np.array(data_to_plot[primary_sensor_key]['value'], dtype=float)
                    
                    # Filter out NaN or inf values before histogramming
                    values = values[np.isfinite(values)]
                    
                    if len(values) == 0:
                        graph_widget.setTitle(f"No valid numerical data for Histogram ({primary_sensor_name})")
                        return
                    
                    hist, bin_edges = np.histogram(values, bins=histogram_bins)
                    
                    # Create bar graph - ensure bars start from y=0 baseline
                    
                    # Get primary sensor color
                    sensor_obj = self.main_window.sensor_controller.get_sensor_by_historical_key(primary_sensor_key)
                    color = getattr(sensor_obj, 'color', '#FFFFFF') if sensor_obj else '#FFFFFF'
                    
                    bar_graph = pg.BarGraphItem(x=bin_edges[:-1], y=0, height=hist, width=(bin_edges[1]-bin_edges[0])*0.9, brush=color)
                    graph_widget.addItem(bar_graph)
                    # Set Y range manually if needed, as autorange might be weird for single bars
                    if len(hist) > 0:
                        graph_widget.setYRange(0, max(hist) * 1.1)
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
                if primary_sensor_key and primary_sensor_key in data_to_plot and len(data_to_plot[primary_sensor_key]['value']) > 0:
                    values = np.array(data_to_plot[primary_sensor_key]['value'], dtype=float)
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
                    
                    # Get primary sensor color
                    sensor_obj = self.main_window.sensor_controller.get_sensor_by_historical_key(primary_sensor_key)
                    color = getattr(sensor_obj, 'color', '#FFFFFF') if sensor_obj else '#FFFFFF'
                    
                    pen = pg.mkPen(color=color, width=getattr(self.main_window, 'plot_line_width_value', 2))
                    
                    # Create semi-transparent brush from sensor color
                    box_color = QColor(color)
                    box_color.setAlpha(150)
                    brush = pg.mkBrush(color=box_color)
                    
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
                    whisker_pen = pg.mkPen(color=color, width=pen.widthF(), style=pg.QtCore.Qt.PenStyle.DashLine) # Use pg.QtCore.Qt
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
                if primary_sensor_key and secondary_sensor_key and primary_sensor_key in data_to_plot and secondary_sensor_key in data_to_plot:
                    data1 = data_to_plot[primary_sensor_key]
                    data2 = data_to_plot[secondary_sensor_key]
                    
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
                    
                    # Get primary sensor color
                    sensor_obj = self.main_window.sensor_controller.get_sensor_by_historical_key(primary_sensor_key)
                    color = getattr(sensor_obj, 'color', '#FFFFFF') if sensor_obj else '#FFFFFF'
                    
                    scatter_color = QColor(color)
                    scatter_color.setAlpha(120)
                    
                    scatter = pg.ScatterPlotItem(size=5, pen=pg.mkPen(None), brush=pg.mkBrush(scatter_color))
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
            
        # Set view range based only on regular (non-control) sensors
        # This prevents control data from zooming out the view too much
        if graph_type == "Standard Time Series" and data_to_plot:
            # Collect time ranges only from non-control sensors
            regular_times = []
            for key in data_to_plot.keys():
                if not key.endswith('_ctrl') and 'time' in data_to_plot[key]:
                    regular_times.extend(data_to_plot[key]['time'])
            
            # If we have regular data, set range based on it
            if regular_times:
                latest_data_time = max(regular_times)
                
                # If a timespan is selected, use it to provide a consistent scrolling view
                if timespan_seconds is not None:
                    # In live mode, we want to see the trailing window
                    # current_elapsed_time is the "now" point relative to the run start
                    # Use the max of latest_data_time and current_elapsed_time to ensure we see the latest data
                    view_max = max(latest_data_time, current_elapsed_time)
                    view_min = view_max - timespan_seconds
                    graph_widget.setXRange(view_min, view_max, padding=0)
                else:
                    # No timespan (All) - show everything with padding
                    min_time = min(regular_times)
                    max_time = latest_data_time
                    time_range = max_time - min_time
                    padding = time_range * 0.05 if time_range > 0 else 1
                    graph_widget.setXRange(min_time - padding, max_time + padding, padding=0)
                
                # Enable autorange only for Y axis
                graph_widget.enableAutoRange(axis='y')
                if is_main_graph and hasattr(self, 'main_secondary_vb') and self.main_secondary_vb:
                    self.main_secondary_vb.enableAutoRange(axis='y', enable=True)
            else:
                # No regular data, use standard autorange
                graph_widget.enableAutoRange()
        else:
            # For other graph types, use standard autorange
            graph_widget.enableAutoRange()
        
        # Add event markers if available (after plotting data so markers appear on top)
        # Skip markers for Histogram and Box Plot as they don't have a time-based X-axis
        if graph_type not in ["Histogram", "Box Plot"]:
            # Use the same start_time that was used for relative time calculation
            # This ensures markers align correctly with the plotted data
            start_time = None
            if graph_start_time is not None:
                start_time = graph_start_time
            elif hasattr(self.main_window, 'data_collection_controller'):
                start_time = getattr(self.main_window.data_collection_controller, 'start_time', None)
            
            if start_time is not None:
                start_time = self._resolve_start_time(start_time, allow_now=self.show_automation_markers)
                print(f"DEBUG: update_specific_graph: Adding event markers with start_time={start_time}, show_automation_markers={self.show_automation_markers}")
                self._add_event_markers_to_graph(graph_widget, start_time, force=self.show_automation_markers)
            else:
                print(f"DEBUG: update_specific_graph: Cannot add event markers - no start_time available") 
    
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
            # Preserve pen style (dashed/solid) when updating width
            for item in self.main_window.graph_widget.listDataItems():
                pen = item.opts.get('pen', None)
                if pen is not None:
                    if isinstance(pen, str):
                        color = pen
                        style = pg.QtCore.Qt.PenStyle.SolidLine
                    else:
                        color = pen.color()
                        # Preserve the pen style (dashed, solid, etc.)
                        style = pen.style()
                    if hasattr(item, "setPen"):
                        item.setPen(pg.mkPen(color=color, width=line_width, style=style))
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
            # Preserve pen style (dashed/solid) when updating width
            for plot_info in self.dashboard_plot_data.values():
                if 'plot_item' in plot_info and plot_info['plot_item'] is not None:
                    pen = plot_info['plot_item'].opts.get('pen', None)
                    if pen is not None:
                        if isinstance(pen, str):
                            color = pen
                            style = pg.QtCore.Qt.PenStyle.SolidLine
                        else:
                            color = pen.color()
                            # Preserve the pen style (dashed, solid, etc.)
                            style = pen.style()
                        if hasattr(plot_info['plot_item'], "setPen"):
                            plot_info['plot_item'].setPen(pg.mkPen(color=color, width=line_width, style=style))
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
            
        # Apply downsampling (Graph Simplification)
        try:
            # Check for setting in SettingsModel or UI checkbox
            downsampling_enabled = True
            if hasattr(self.main_window, 'graph_downsampling_checkbox'):
                downsampling_enabled = self.main_window.graph_downsampling_checkbox.isChecked()
            elif self.settings_model:
                downsampling_enabled = self.settings_model.get_bool("graph_downsampling", True)
                
            plot_item = widget.getPlotItem()
            if downsampling_enabled:
                plot_item.setDownsampling(ds=True, auto=True, mode='peak')
            else:
                plot_item.setDownsampling(ds=False)
            plot_item.setClipToView(True)
        except Exception as e:
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.debug(f"Could not apply downsampling to widget: {e}")
        
        # Apply line width to all plots in the graph
        # This would be better handled when creating/updating the plots themselves
        # But for now we can store the value for future use
        if hasattr(self.main_window, 'plot_line_width_value'):
            self.main_window.plot_line_width_value = line_width 
            
    def start_main_graph_live_update(self):
        """Starts the timer for live updating the main graph."""
        # Check if the live update checkbox is checked
        if hasattr(self.main_window, 'graph_live_update_checkbox') and not self.main_window.graph_live_update_checkbox.isChecked():
            self.main_window.logger.info("Main graph live update not started: checkbox is not checked")
            print("Main graph live update not started: checkbox is not checked")
            return
            
        # Set timer interval to match sampling rate, but not faster than 1s
        update_interval_ms = 1500
        if hasattr(self.main_window, 'sampling_rate_spinbox'):
            rate_hz = self.main_window.sampling_rate_spinbox.value()
            if rate_hz > 0:
                # Convert Hz to ms interval: 1000 / Hz
                update_interval_ms = max(int(1000 / rate_hz), 1000)
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
                    # Check if timer is already active to avoid restarting it unnecessarily
                    if not self.main_graph_update_timer.isActive():
                        self.start_main_graph_live_update()
                        print("DEBUG: Started main graph live update timer from ensure_main_graph_live_update")
                    else:
                        # Timer is already active, just update the interval if needed
                        update_interval_ms = 1500
                        if hasattr(self.main_window, 'sampling_rate_spinbox'):
                            rate_hz = self.main_window.sampling_rate_spinbox.value()
                            if rate_hz > 0:
                                # Convert Hz to ms interval: 1000 / Hz
                                update_interval_ms = max(int(1000 / rate_hz), 1000)
                        self.main_graph_update_timer.setInterval(update_interval_ms)
                        print("DEBUG: Main graph live update timer already active, updated interval")
                else:
                    self.main_window.logger.info(f"Main graph live update not started: data collection not active")
                    print(f"Main graph live update not started as data collection is not active")
            else:
                self.stop_main_graph_live_update()

    def clear_graphs(self):
        """Clear all graphs and plot data buffers"""
        # Clear internal data buffers
        self.dashboard_plot_data.clear()
        
        # --- ADDED: Clear automation markers for new run ---
        if self.event_markers_mutex:
            self.event_markers_mutex.lock()
        try:
            self.event_markers = []
        finally:
            if self.event_markers_mutex:
                self.event_markers_mutex.unlock()
        self._event_marker_items = {} 
        # --------------------------------------------------
        
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
        
    def plot_historical_data(self, historical_data, run_dir=None):
        """
        Plot historical data from the CSV file at program start.
        
        Args:
            historical_data: Data in the format {sensor_id: {'time': [...], 'value': [...]}}
            run_dir: Optional run directory path to load automation events from
        """
        print(f"DEBUG: plot_historical_data called with {len(historical_data)} sensors")
        
        # Exit if no data
        if not historical_data:
            print("DEBUG: No historical data to plot")
            return
        
        # Load automation events from CSV if run directory is provided
        if run_dir:
            print(f"DEBUG: plot_historical_data: Loading automation events from run_dir={run_dir}")
            # Load events but don't add markers yet (we'll add them after plotting with correct base_time)
            self.load_automation_events_from_csv(run_dir, add_markers_immediately=False)
            # Check how many events were loaded
            markers_count = len(self._get_event_markers_snapshot())
            print(f"DEBUG: plot_historical_data: After loading, {markers_count} events stored in event_markers")
        elif hasattr(self.main_window, 'project_controller'):
            # Try to get run directory from project controller
            project_controller = self.main_window.project_controller
            if hasattr(project_controller, 'get_current_run_directory'):
                run_dir = project_controller.get_current_run_directory()
                if run_dir:
                    print(f"DEBUG: plot_historical_data: Loading automation events from project controller run_dir={run_dir}")
                    self.load_automation_events_from_csv(run_dir, add_markers_immediately=False)
                    markers_count = len(self._get_event_markers_snapshot())
                    print(f"DEBUG: plot_historical_data: After loading, {markers_count} events stored in event_markers")
        
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
        
        try:
            # Handle main legend
            leg = getattr(graph_widget, 'legend', None)
            if not leg:
                # Try getting it from PlotItem
                p_item = graph_widget.getPlotItem()
                if p_item:
                    leg = getattr(p_item, 'legend', None)
                
            if leg:
                try:
                    leg.clear()
                    scene = leg.scene()
                    if scene:
                        scene.removeItem(leg)
                    leg.setParentItem(None)
                except Exception:
                    pass
                
                # Clear references
                if hasattr(graph_widget, 'legend'):
                    graph_widget.legend = None
                p_item = graph_widget.getPlotItem()
                if p_item and hasattr(p_item, 'legend'):
                    p_item.legend = None
        except Exception as e:
            print(f"DEBUG: Could not remove existing legend: {e}")
        
        legend = graph_widget.addLegend()
        graph_widget.legend = legend
        graph_widget.showGrid(x=True, y=True, alpha=0.3)
        graph_widget.setLabel('bottom', 'Time Since Run Start (s)')
        graph_widget.setLabel('left', 'Sensor Value')
        graph_widget.setTitle("Historical Data from Last Run")
        
        # Determine a common zero so the X axis shows elapsed time from the run start
        base_time = None
        try:
            all_times = []
            for sensor_data in historical_data.values():
                times = sensor_data.get('time') if isinstance(sensor_data, dict) else None
                if times:
                    for t in times:
                        try:
                            all_times.append(float(t))
                        except (TypeError, ValueError):
                            continue
            if all_times:
                base_time = min(all_times)
                self._debug(f"Graph: Using base_time {base_time:.3f} for historical x-axis")
        except Exception as e:
            self._warn(f"Graph: Failed to derive base_time for historical data: {e}")
            base_time = None
        
        # Apply formatting
        self.apply_plot_formatting()
        
        # Plot each sensor's data
        for sensor_id, data in historical_data.items():
            if len(data['time']) > 0 and len(data['value']) > 0:
                try:
                    # Convert to numpy arrays for efficient handling
                    times = np.array(data['time'], dtype=float)
                    if base_time is not None:
                        times = times - base_time
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
                    graph_widget.plot(
                        times, values, 
                        pen=pen, 
                        name=sensor_name
                    )
                    print(f"DEBUG: Plotted {len(times)} points for sensor {sensor_name}")
                except Exception as e:
                    print(f"DEBUG: Error plotting historical data for sensor {sensor_id}: {e}")
        
        # Set auto range so all data is visible
        graph_widget.autoRange()
        
        # Add event markers if available (after plotting data so markers appear on top)
        # Use base_time as the start_time for historical data so markers align with sensor data
        if base_time is not None:
            start_time = base_time
        elif hasattr(self.main_window, 'data_collection_controller'):
            start_time = getattr(self.main_window.data_collection_controller, 'start_time', None)
        else:
            start_time = None
            
        if start_time is not None:
            start_time = self._resolve_start_time(start_time, allow_now=self.show_automation_markers)
            self._debug(f"Graph: Adding event markers to historical graph with start_time={start_time}, base_time={base_time}")
            print(f"DEBUG: plot_historical_data: Adding event markers with start_time={start_time}, show_automation_markers={self.show_automation_markers}")
            markers_before = len(self._get_event_markers_snapshot())
            print(f"DEBUG: plot_historical_data: {markers_before} events available before adding markers")
            self._add_event_markers_to_graph(graph_widget, start_time, force=self.show_automation_markers)
        else:
            self._debug("Graph: Cannot add event markers - no start_time available")
            print("DEBUG: plot_historical_data: Cannot add event markers - no start_time available")
        
        print("DEBUG: Historical data plotting completed")
    
    def _merge_control_and_current_data(self, control_data, current_data, required_sensor_keys):
        """
        Merge control run data with current data for seamless visualization.
        Both datasets are kept separate and will be plotted with different styles.
        
        Args:
            control_data: Control run data in format {sensor_id: {'time': [...], 'value': [...]}}
            current_data: Current data in format {sensor_id: {'time': [...], 'value': [...]}}
            required_sensor_keys: List of sensor keys to include in the merged data
            
        Returns:
            Merged data in the same format as input - contains all sensors from both datasets
        """
        if not control_data and not current_data:
            return {}
            
        merged_data = {}
        
        # First, add all current data
        for sensor_key, data in current_data.items():
            merged_data[sensor_key] = {
                'time': data['time'].copy() if isinstance(data['time'], list) else data['time'].tolist(),
                'value': data['value'].copy() if isinstance(data['value'], list) else data['value'].tolist()
            }
        
        # Then, add all control data (don't merge, keep separate so they can be plotted differently)
        # Control data is already merged with current data in the time series
        # We just need to ensure all sensors are available
        for sensor_key in required_sensor_keys:
            # If sensor exists only in control data, add it
            if sensor_key in control_data and sensor_key not in merged_data:
                ctrl_data = control_data[sensor_key]
                if 'time' in ctrl_data and 'value' in ctrl_data:
                    merged_data[sensor_key] = {
                        'time': ctrl_data['time'].copy() if isinstance(ctrl_data['time'], list) else ctrl_data['time'].tolist(),
                        'value': ctrl_data['value'].copy() if isinstance(ctrl_data['value'], list) else ctrl_data['value'].tolist()
                    }
            # If sensor exists in both, merge the time series
            elif sensor_key in control_data and sensor_key in merged_data:
                ctrl_data = control_data[sensor_key]
                if 'time' in ctrl_data and 'value' in ctrl_data:
                    # Convert to numpy arrays for easier manipulation
                    ctrl_times = np.array(ctrl_data['time'], dtype=float)
                    ctrl_values = np.array(ctrl_data['value'], dtype=float)
                    cur_times = np.array(merged_data[sensor_key]['time'], dtype=float)
                    cur_values = np.array(merged_data[sensor_key]['value'], dtype=float)
                    
                    # Combine and sort by time
                    all_times = np.concatenate([ctrl_times, cur_times])
                    all_values = np.concatenate([ctrl_values, cur_values])
                    
                    # Sort by time
                    sort_indices = np.argsort(all_times)
                    all_times = all_times[sort_indices]
                    all_values = all_values[sort_indices]
                    
                    merged_data[sensor_key] = {
                        'time': all_times.tolist(),
                        'value': all_values.tolist()
                    }
                    
                    if hasattr(self.main_window, 'logger'):
                        self.main_window.logger.debug(f"Merged {len(all_times)} data points for sensor {sensor_key}")
        
        return merged_data
    
    def add_event_marker(self, event):
        """
        Add an automation event marker for visualization in graphs.
        Thread-safe: schedules the UI update on the main thread.
        """
        if not event:
            return

        # Use a single-shot timer to ensure the marker is added on the main thread
        # and not during a sensitive part of the graphing update cycle.
        QTimer.singleShot(0, lambda: self._add_event_marker_ui(event))

    def _add_event_marker_ui(self, event):
        """Internal method to add marker to UI, called on main thread."""
        print(f"DEBUG: _add_event_marker_ui called with event: type={event.get('type')}, trigger='{event.get('trigger_description', '')}', action='{event.get('action_description', '')}', timestamp={event.get('timestamp')}")
        
        # Skip trigger events - only show action events on graph
        event_type = event.get('type', 'unknown')
        if event_type == 'trigger':
            print("DEBUG: _add_event_marker_ui: Skipping trigger event")
            return
        
        # Store event (always store, even if dashboard not started yet)
        event_copy = event.copy()
        if self.event_markers_mutex:
            self.event_markers_mutex.lock()
        try:
            # Rate limit marker storage per-sequence to prevent memory issues if triggers rapid-fire
            # but allow different sequences to trigger simultaneously
            current_time = time.time()
            seq_name = event_copy.get('sequence_name', 'unknown')
            
            # Find if a similar event happened recently
            # Only check for duplicates if we're in live collection mode (not loading from CSV)
            # When loading from CSV, we want to show all events even if they're close together
            is_duplicate = False
            event_timestamp = event_copy.get('timestamp', current_time)
            # Only check for duplicates if this is a live event (timestamp is very recent)
            # Events loaded from CSV have historical timestamps, so we don't filter them as duplicates
            if abs(current_time - event_timestamp) < 1.0:  # Only check duplicates for recent events
                for last_event in reversed(self.event_markers[-10:]): # Check last 10 markers
                    last_timestamp = last_event.get('timestamp', 0)
                    # Only consider it a duplicate if timestamps are very close AND it's a recent event
                    if (abs(event_timestamp - last_timestamp) < 0.1 and 
                        abs(current_time - last_timestamp) < 1.0 and
                        last_event.get('sequence_name') == seq_name and
                        last_event.get('type') == event_type):
                        is_duplicate = True
                        break
            
            if is_duplicate:
                # Too many similar markers in storage, skip this one for UI (still in CSV)
                print(f"DEBUG: _add_event_marker_ui: Event filtered as duplicate")
                return

            self.event_markers.append(event_copy)
            print(f"DEBUG: _add_event_marker_ui: Event added to event_markers. Total events: {len(self.event_markers)}")
            
            # Do not delete events - preserve all scientific data
            # The user controls visibility via the "Show automation events" checkbox
            # All events are preserved regardless of age to maintain data integrity
        finally:
            if self.event_markers_mutex:
                self.event_markers_mutex.unlock()
        
        # Dashboard: draw if widget exists and markers are enabled
        if self.dashboard_graph_widget and self.show_automation_markers:
            # For replay events loaded from CSV, always add them (they're historical data)
            # For live events during replay playback, rate limit to avoid performance issues
            is_replay_event = event.get('type') == 'replay_event'
            in_replay = hasattr(self.main_window, "replay_mode_enabled") and self.main_window.replay_mode_enabled
            
            # Always add replay events (loaded from CSV), or if not in replay, or if rate limit allows
            if is_replay_event or not in_replay or (time.time() - getattr(self, '_last_marker_add_time', 0) > 0.5):
                actual_start_time = self._resolve_start_time(self.dashboard_start_time, allow_now=True)
                self._add_single_event_marker(self.dashboard_graph_widget, event, actual_start_time, force=True)
                if not is_replay_event:  # Only update rate limit for live events
                    self._last_marker_add_time = time.time()
        
        # Main graph: draw if widget exists and collection active and markers enabled
        # Skip markers for Histogram and Box Plot as they don't have a time-based X-axis
        current_graph_type = ""
        if hasattr(self.main_window, 'graph_type_combo'):
            current_graph_type = self.main_window.graph_type_combo.currentText()
            
        if (current_graph_type not in ["Histogram", "Box Plot"] and
            hasattr(self.main_window, 'data_collection_controller') and 
            hasattr(self.main_window.data_collection_controller, 'collecting_data') and
            self.main_window.data_collection_controller.collecting_data and
            hasattr(self.main_window, 'graph_widget') and 
            self.main_window.graph_widget and
            self.show_automation_markers):
            start_time = self._resolve_start_time(getattr(self.main_window.data_collection_controller, 'start_time', None), allow_now=True)
            self._add_single_event_marker(self.main_window.graph_widget, event, start_time, force=True)
    
    def load_automation_events_from_csv(self, run_dir, add_markers_immediately=True):
        """
        Load automation events from CSV file in the run directory and add them as event markers.
        
        Args:
            run_dir: Path to the run directory containing the CSV file
            add_markers_immediately: If True, add markers to graphs immediately. If False, only load events into storage.
        """
        if not run_dir or not os.path.isdir(run_dir):
            self._debug(f"Graph: Invalid run directory for loading automation events: {run_dir}")
            return
        
        # Find the most recent CSV file in the run directory
        csv_files = glob.glob(os.path.join(run_dir, 'rundata_*.csv'))
        if not csv_files:
            # Try a broader search in case naming convention differs
            csv_files = glob.glob(os.path.join(run_dir, '*.csv'))
            if not csv_files:
                self._debug(f"Graph: No CSV files found in {run_dir} for automation events")
                return
        
        latest_csv = max(csv_files, key=os.path.getmtime)
        self._debug(f"Graph: Loading automation events from {latest_csv}")
        
        # Automation columns to check
        automation_columns = [
            "automation_trigger",
            "automation_action",
            "automation_sequence",
            "automation_image",
        ]
        
        try:
            events_loaded = 0
            first_timestamp = None
            
            with open(latest_csv, 'r', newline='') as csvfile:
                reader = csv.DictReader(csvfile)
                
                for row in reader:
                    # Check if this row has any automation data
                    if not any(row.get(col) for col in automation_columns):
                        continue
                    
                    try:
                        # Get timestamp
                        timestamp = float(row.get('timestamp', 0))
                        if first_timestamp is None:
                            first_timestamp = timestamp
                        
                        # Get automation data
                        trigger = row.get("automation_trigger", "").strip()
                        action = row.get("automation_action", "").strip()
                        sequence = row.get("automation_sequence", "").strip()
                        image = row.get("automation_image", "").strip()
                        
                        # Only create event if there's actual content (not just empty strings)
                        if not (trigger or action or sequence):
                            continue
                        
                        # Create event marker
                        event = {
                            "timestamp": timestamp,
                            "type": "replay_event",
                            "sequence_name": sequence,
                            "trigger_description": trigger,
                            "action_description": action,
                            "image_path": image,
                        }
                        
                        self._debug(f"Graph: Loading event from CSV: timestamp={timestamp}, trigger='{trigger}', action='{action}', sequence='{sequence}'")
                        
                        # Add event marker directly (synchronously) when loading from CSV
                        # This ensures events are stored before we try to add them to the graph
                        self._add_event_marker_ui(event)
                        events_loaded += 1
                        
                    except (ValueError, TypeError) as e:
                        # Skip rows with invalid timestamp
                        continue
            
            self._debug(f"Graph: Loaded {events_loaded} automation events from CSV")
            print(f"DEBUG: load_automation_events_from_csv: Loaded {events_loaded} events from CSV")
            
            # Verify events were stored
            stored_count = len(self._get_event_markers_snapshot())
            print(f"DEBUG: load_automation_events_from_csv: {stored_count} events now stored in event_markers")
            
            # If we loaded events and should add markers immediately, update the graph
            if add_markers_immediately and events_loaded > 0 and first_timestamp is not None:
                # Update dashboard graph if it exists
                if self.dashboard_graph_widget:
                    self._add_event_markers_to_graph(
                        self.dashboard_graph_widget, 
                        first_timestamp, 
                        force=self.show_automation_markers
                    )
                
                # Update main graph if it exists
                if hasattr(self.main_window, 'graph_widget') and self.main_window.graph_widget:
                    self._add_event_markers_to_graph(
                        self.main_window.graph_widget,
                        first_timestamp,
                        force=self.show_automation_markers
                    )
                    
        except Exception as e:
            self._warn(f"Graph: Error loading automation events from CSV: {e}")
    
    def _add_event_markers_to_graph(self, graph_widget, start_time=None, force=False):
        """
        Add vertical lines and labels for automation events to a graph
        
        Args:
            graph_widget: The pyqtgraph widget to add markers to
            start_time: Start time of the data collection (for relative time calculation)
        """
        # Clear existing markers to avoid duplicates
        self._clear_event_markers_for_widget(graph_widget)

        if not self.show_automation_markers and not force:
            self._debug("Graph: Skipping marker add (disabled and not forced)")
            return
        markers = self._get_event_markers_snapshot()
        print(f"DEBUG: _add_event_markers_to_graph: Found {len(markers)} stored event markers")
        if not markers:
            self._debug("Graph: No stored event markers to add")
            print("DEBUG: _add_event_markers_to_graph: No markers to add, returning early")
            return
        
        if start_time is None:
            # Prefer dashboard start, then data collection start.
            if self.dashboard_start_time:
                start_time = self.dashboard_start_time
            elif hasattr(self.main_window, "data_collection_controller"):
                start_time = getattr(self.main_window.data_collection_controller, "start_time", None)
            # If still missing and forced, fall back to earliest event or now.
            if start_time is None and force:
                if self.event_markers:
                    start_time = min(e.get("timestamp", time.time()) for e in self.event_markers)
                else:
                    start_time = time.time()
            if start_time is None:
                self._debug("Graph: No start_time available for markers; skip drawing until start_time is set")
                return
        self._debug(
            f"Graph: _add_event_markers_to_graph start "
            f"show={self.show_automation_markers} force={force} "
            f"events={len(markers)} start_time={start_time}"
        )
        
        added = 0
        # Get current view range to only add visible markers (optimization)
        try:
            vb = graph_widget.getViewBox()
            view_range = vb.viewRange()[0] if vb else None
        except Exception:
            view_range = None

        # Calculate relative times for events
        for event in markers:
            event_timestamp = event.get('timestamp', 0)
            relative_time = event_timestamp - start_time if start_time else 0

            # If we have a view range, skip markers far outside of it
            if view_range is not None:
                # Add a small buffer to avoid flickering at edges
                buffer = (view_range[1] - view_range[0]) * 0.1
                if relative_time < view_range[0] - buffer or relative_time > view_range[1] + buffer:
                    continue

            self._add_single_event_marker(graph_widget, event, start_time, force=True)
            added += 1

        self._debug(f"Graph: Re-added {added} automation markers (force={force}, start_time={start_time})")
    
    def _add_single_event_marker(self, graph_widget, event, start_time, force=False):
        """
        Add a single event marker to a graph widget immediately
        
        Args:
            graph_widget: The pyqtgraph widget to add marker to
            event: Event dictionary
            start_time: Start time of data collection for relative time calculation
        """
        if not graph_widget:
            self._debug(f"Graph: Cannot add event marker - graph_widget missing")
            return

        # Fallback start_time logic: use provided, else controller start, else earliest event time, else now (only if forced)
        if not start_time:
            if hasattr(self.main_window, "data_collection_controller"):
                start_time = getattr(self.main_window.data_collection_controller, "start_time", None)
            if start_time is None and hasattr(self, "event_markers") and self.event_markers:
                start_time = min(e.get("timestamp", time.time()) for e in self.event_markers)
            if start_time is None and force:
                start_time = time.time()
            if start_time is None:
                self._debug("Graph: Cannot add marker - no start_time available")
                return

        if not self.show_automation_markers and not force:
            return
        
        event_timestamp = event.get('timestamp', time.time())
        relative_time = event_timestamp - start_time
        
        # --- Safety check: Don't add NaN/Inf markers as they crash pyqtgraph ---
        if not np.isfinite(relative_time):
            self._debug(f"Graph: Skipping invalid relative time for marker: {relative_time}")
            return
        # ---------------------------------------------------------------------

        self._debug(
            f"Graph: Adding event marker - event_time={event_timestamp:.3f}, "
            f"start_time={start_time:.3f}, relative_time={relative_time:.3f}, force={force}"
        )
        
        # Never drop markers because of negative drift; clamp to zero
        if relative_time < 0:
            self._debug(f"Graph: Clamping negative relative time ({relative_time:.3f}s) to 0")
            relative_time = 0
            
        # --- Safety check: Limit total number of markers on graph ---
        if graph_widget not in self._event_marker_items:
            self._event_marker_items[graph_widget] = []
            
        current_markers = self._event_marker_items[graph_widget]
        if len(current_markers) > 500:
            # Remove oldest marker to stay within limit
            oldest = current_markers.pop(0)
            try:
                graph_widget.removeItem(oldest)
            except Exception:
                pass
        # ------------------------------------------------------------
        
        # Determine color based on event type and build a descriptive label
        event_type = event.get('type')
        trigger_desc = event.get('trigger_description') or ""
        action_desc = event.get('action_description') or ""
        generic_desc = event.get('description') or ""

        # Prefer a meaningful description even for replay events
        best_desc = trigger_desc or action_desc or generic_desc or "Event"

        if event_type == 'trigger':
            color = '#FF6B6B'  # Red for triggers
            label = f"Trigger: {best_desc}"
        elif event_type == 'action':
            color = '#4ECDC4'  # Teal for actions
            label = f"Action: {best_desc}"
        else:
            color = '#95A5A6'  # Gray for unknown/replay/misc
            label = best_desc

        # Add sequence name if available
        sequence_name = event.get('sequence_name', '')
        if sequence_name:
            label = f"{sequence_name}: {label}"
        
        # Check if there's an image associated with this event
        image_path = event.get('image_path')
        if image_path:
            label += " 📸" # Add camera emoji to label if image exists
        
        # Create vertical line
        line = pg.InfiniteLine(
            pos=relative_time,
            angle=90,
            pen=pg.mkPen(color=color, width=2, style=pg.QtCore.Qt.PenStyle.DashLine),
            label=label,
            labelOpts={'position': 0.95, 'color': color} # Simplified label options
        )
        
        # Attach image path if it exists and make clickable
        if image_path:
            line.image_path = image_path
            # Make it slightly more interactive
            line.setHoverPen(pg.mkPen(color='#FFFFFF', width=3))
            # Connect click signal
            line.sigClicked.connect(lambda obj: self._handle_marker_clicked(obj))
            
        graph_widget.addItem(line)
        self._event_marker_items[graph_widget].append(line)

    def _handle_marker_clicked(self, marker):
        """Handle clicking on a graph marker (open associated image if any)"""
        image_path = getattr(marker, 'image_path', None)
        if not image_path:
            return
            
        # If it's a semicolon-separated list of paths (multiple snapshots at once), 
        # just open the first one for now or handle them.
        if ';' in image_path:
            image_path = image_path.split(';')[0].strip()
            
        if image_path and os.path.exists(image_path):
            self._debug(f"Graph: Opening image: {image_path}")
            # Use the system default image viewer
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(image_path)))
        else:
            self._warn(f"Graph: Associated image not found at: {image_path}")
            # Show a tooltip or message in status bar?
            if hasattr(self.main_window, 'statusBar'):
                self.main_window.statusBar().showMessage(f"Snapshot file not found: {os.path.basename(image_path)}", 3000)