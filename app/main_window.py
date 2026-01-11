import sys
import os
import re
import datetime
import time
from PyQt6.QtWidgets import QMainWindow, QMessageBox, QFileDialog, QTableWidgetItem, QDialog, QVBoxLayout, QGridLayout, QLabel, QComboBox, QDoubleSpinBox, QPushButton, QGroupBox, QLineEdit, QHBoxLayout, QSpinBox, QSlider, QCheckBox, QTextEdit, QDialogButtonBox, QTabWidget, QScrollArea, QSizePolicy, QFrame, QListWidget, QFormLayout, QTableWidget, QAbstractItemView, QColorDialog, QApplication
from PyQt6.QtCore import Qt, QTimer, QSettings, QCoreApplication, QEvent, QUrl, QFileInfo, QTime, QPoint, QSize, QDateTime, QDir, pyqtSignal, QObject, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QIcon, QDesktopServices, QColor, QPixmap
from enum import Enum, auto
import traceback
import pathlib
import json
import shutil
from copy import deepcopy

# Import common types
from app.utils.common_types import StatusState

# Import UI module
from app.ui.ui_setup import setup_ui, update_device_connection_status

# Import controllers
from app.controllers.project_controller import ProjectController
from app.controllers.sensor_controller import SensorController
from app.controllers.camera_controller import CameraController
from app.controllers.graph_controller import GraphController
from app.controllers.automation_controller import AutomationController
from app.controllers.data_collection_controller import DataCollectionController
from app.controllers.export_controller import ExportController
from app.controllers.notes_controller import NotesController
from app.controllers.control_run_controller import ControlRunController
from app.controllers.data_flow_controller import DataFlowController
from app.controllers.data_replay_controller import DataReplayController

# Import models
from app.models.settings_model import SettingsModel
from app.models.sensor_model import SensorModel

# Import core components
from app.core.logger import Logger
from app.utils.config_loader import load_config, save_config

# Import plotting library
import pyqtgraph as pg
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

# Import dialogs
from app.ui.dialogs.other_sensors_dialog import OtherSensorsDialog
from app.ui.dialogs.interface_config_dialog import InterfaceConfigDialog
from app.core.interfaces.interface_registry import InterfaceRegistry

# Import theme system
from app.ui.theme import (
    COLORS, ConnectionStyles, StatusIndicator, StatusText,
    GroupBoxStyles, get_status_color, DialogStyles, CardStyles,
    InputStyles, ButtonStyles
)

VIRTUAL_SENSORS_FILENAME = "virtual_sensors.json"
VIRTUAL_SENSORS_PATH = VIRTUAL_SENSORS_FILENAME  # Store in current directory as fallback

class ZoomableImageLabel(QLabel):
    """A label that displays a pixmap and supports mouse wheel zooming and scaling"""
    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self.original_pixmap = pixmap
        self.zoom_factor = 1.0
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMouseTracking(True)
        
        # Panning state
        self.is_panning = False
        self.last_mouse_pos = QPoint()
        
        self.update_pixmap()

    def update_pixmap(self):
        if self.original_pixmap.isNull():
            return
        
        # Calculate new size based on zoom factor
        new_width = int(self.original_pixmap.width() * self.zoom_factor)
        new_height = int(self.original_pixmap.height() * self.zoom_factor)
        
        # Scale pixmap with smooth transformation
        scaled_pixmap = self.original_pixmap.scaled(
            new_width, new_height, 
            Qt.AspectRatioMode.KeepAspectRatio, 
            Qt.TransformationMode.SmoothTransformation
        )
        super().setPixmap(scaled_pixmap)
        # Adjust size to match the scaled pixmap so the scroll area can work
        self.resize(scaled_pixmap.size())

    def fit_in_view(self, width, height):
        if self.original_pixmap.isNull():
            return
        
        # Calculate factors to fit the pixmap into the given dimensions
        # Use a small margin (e.g. 20px) to avoid scrollbars if possible
        available_w = max(10, width - 20)
        available_h = max(10, height - 20)
        
        w_factor = available_w / self.original_pixmap.width()
        h_factor = available_h / self.original_pixmap.height()
        
        # Fit but don't upscale beyond 100% initially unless it's very small
        self.zoom_factor = min(w_factor, h_factor)
        if self.zoom_factor > 1.0:
            self.zoom_factor = 1.0
            
        self.update_pixmap()

    def wheelEvent(self, event):
        # Zoom in/out with mouse wheel
        angle = event.angleDelta().y()
        if angle > 0:
            self.zoom_factor *= 1.1
        else:
            self.zoom_factor /= 1.1
            
        # Limit zoom factor to reasonable levels (5% to 2000%)
        self.zoom_factor = max(0.05, min(self.zoom_factor, 20.0))
        
        self.update_pixmap()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_panning = True
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self.is_panning:
            # Calculate how much the mouse has moved
            delta = event.pos() - self.last_mouse_pos
            
            # Find the scroll area parent
            parent = self.parent()
            while parent and not isinstance(parent, QScrollArea):
                parent = parent.parent()
            
            if parent:
                # Update scrollbars of the parent QScrollArea
                h_bar = parent.horizontalScrollBar()
                v_bar = parent.verticalScrollBar()
                
                h_bar.setValue(h_bar.value() - delta.x())
                v_bar.setValue(v_bar.value() - delta.y())
                
                # Update last mouse position for next move event
                self.last_mouse_pos = event.pos()
            
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()

class DAQApp(QMainWindow):
    """Main application window"""
    def __init__(self, sound_player=None):
        """Initialize the main window"""
        super().__init__()
        
        # Set sound player
        self.sound_player = sound_player
        
        # Initialize virtual sensor lists early so they can be populated by load_settings
        self.other_sensors = []
        self.other_sequences = []
        self.csv_configs = []
        
        # Set application settings
        self.settings = QSettings("Artefakt", "DAQ")
        self.settings_model = SettingsModel(self.settings)
        
        # Load application configuration
        self.config = load_config()
        
        # Initialize logger
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"daq_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        # Set log level based on debug_mode setting
        debug_mode = self.settings.value("debug_mode", "false").lower() == "true"
        log_level = "DEBUG" if debug_mode else "ERROR"
        self.logger = Logger("UI", log_file=log_file, log_level=log_level)
        self.logger.log("Application started", "INFO")
        
        # Initialize data structures
        self.recording = False
        self.running = False
        self.start_time = None # To store the start time for relative plotting
        
        # Track connection status for all interfaces (used for sensor status)
        self.interface_connections = {}
        self.dragging_overlay = None
        
        # Initialize theme
        self.theme = "dark"  # Default theme
        
        # Add status variables
        self.project_status = StatusState.ERROR # Default to error until checked
        self.sensor_status = StatusState.ERROR
        self.camera_status = StatusState.OPTIONAL # Default camera to optional/inactive
        self.automation_status = StatusState.OPTIONAL # Default automation to optional/inactive
        
        # Initialize attributes for timelapse settings persistence
        self.timelapse_source_folder = QLineEdit()
        self.timelapse_output_file = QLineEdit()
        self.timelapse_duration = QSpinBox()
        self.timelapse_duration.setRange(1, 300) # Default range from timelapse_utils
        self.timelapse_duration.setValue(30)    # Default value
        self.timelapse_fps = QSpinBox()
        self.timelapse_fps.setRange(10, 60)     # Default range
        self.timelapse_fps.setValue(30)        # Default value
        self.timelapse_format = QComboBox()
        self.timelapse_format.addItems(["MP4 (H.264)", "AVI (MJPG)", "AVI (XVID)"]) # Default formats
        
        # Set up the UI
        print(f"MAIN_WINDOW: Calling setup_ui on win (id={id(self)})")
        setup_ui(self)
        print(f"MAIN_WINDOW: setup_ui complete. self.camera_id type: {type(getattr(self, 'camera_id', None))}")
        
        # Connect help button directly
        if hasattr(self, 'project_help_btn'):
            self.project_help_btn.clicked.connect(self.show_project_help)

        # Install event filters for specific widgets
        if hasattr(self, 'dashboard_snapshot_label'):
            self.dashboard_snapshot_label.installEventFilter(self)

        # Connect signals for various UI elements
        # These will be initialized in ui_setup.py

        # Initialize shared media players for video playback (live/replay - up to 4 slots)
        self.media_audio_outputs = []
        self.media_players = []
        
        for i in range(4):
            player = QMediaPlayer()
            audio_output = None
            try:
                audio_output = QAudioOutput()
                player.setAudioOutput(audio_output)
                
                # Connect signals for all players
                player.durationChanged.connect(self._on_media_duration_changed)
                player.mediaStatusChanged.connect(self._on_media_status_changed)
                player.errorOccurred.connect(lambda error, error_str, p_idx=i: self._on_media_error(error, error_str, p_idx))
                
                if i == 0: # Compatibility: track master for main sync logic if needed
                    pass
            except Exception:
                pass
            
            self.media_players.append(player)
            self.media_audio_outputs.append(audio_output)
            
        # Compatibility attribute for existing code
        self.media_player = self.media_players[0]
        self.media_audio_output = self.media_audio_outputs[0]
        
        # Default video target: dedicated video tab display if available
        self.video_player = None
        if hasattr(self, "video_display") and isinstance(self.video_display, QVideoWidget):
            self.media_players[0].setVideoOutput(self.video_display)
            self.video_player = self.video_display
        elif hasattr(self, "dashboard_video_widgets") and self.dashboard_video_widgets:
            for i, vw in enumerate(self.dashboard_video_widgets):
                if i < len(self.media_players):
                    self.media_players[i].setVideoOutput(vw)
            self.video_player = self.dashboard_video_widgets[0]
        elif hasattr(self, "dashboard_video_widget"):
            self.media_players[0].setVideoOutput(self.dashboard_video_widget)
            self.video_player = self.dashboard_video_widget
        
        # Replay state (dashboard playback)
        self.replay_mode_enabled = False
        self.replay_is_playing = False
        self.replay_current_time = 0.0
        self.replay_duration = 0.0
        self.replay_data_duration = 0.0
        self.replay_video_duration = 0.0  # seconds, from media metadata
        self.replay_video_offsets = [0.0] * 4
        self.replay_video_segments = []
        self.replay_active_video_paths = [None] * 4
        self.replay_active_video_path = None # Compatibility
        self.replay_video_drift_threshold_ms = 150  # seek if drift exceeds 150 ms
        self.replay_speed_factor = 1.0
        self.replay_last_tick = None  # monotonic timestamp for drift-free dt
        self._is_syncing_replay_frame = False # Guard against recursion
        self.replay_timer = QTimer()
        self.replay_timer.setInterval(50)  # 20 FPS updates for slider/video sync
        self.replay_timer.timeout.connect(self._tick_replay)
        # Replay automation table state (simulated during replay)
        self.automation_replay_active = False
        self.replay_automation_events = []
        self.replay_automation_events_by_seq = {}

        # Snapshot preview state
        self.snapshot_paths = []
        self.snapshot_data = []
        self.current_snapshot_index = -1
        self.last_sync_snapshot_index = -1

        # Initialize controllers
        print(f"MAIN_WINDOW: Initializing controllers for win (id={id(self)})")
        self.init_controllers()
        print(f"MAIN_WINDOW: Controller init complete. self.camera_id type: {type(getattr(self, 'camera_id', None))}")
        
        # Initialize timers after controllers are created
        self.init_timers()

        # Ensure controller signals are connected once (graphs/metrics/data flow)
        try:
            if not getattr(self, "_controller_signals_connected", False):
                print("[INIT] Connecting controller signals...")
                self.connect_controller_signals()
                self._controller_signals_connected = True
                print("[INIT] Controller signals connected successfully")
            else:
                print("[INIT] Controller signals already connected")
        except Exception as e:
            self.logger.log(f"Failed to connect controller signals: {e}", "ERROR")
            print(f"[INIT ERROR] Failed to connect controller signals: {e}")
            import traceback
            traceback.print_exc()

        # Initialize media volume UI from settings if present
        try:
            saved_vol = float(self.settings.value("media_volume", "100"))
            saved_vol = max(0.0, min(100.0, saved_vol))
            saved_muted = str(self.settings.value("media_muted", "false")).lower() == "true"
            if hasattr(self, "video_volume_slider"):
                self.video_volume_slider.setValue(int(saved_vol))
            if hasattr(self, "video_mute_checkbox"):
                self.video_mute_checkbox.setChecked(saved_muted)
            if hasattr(self, "camera_volume_slider"):
                self.camera_volume_slider.setValue(int(saved_vol))
            if hasattr(self, "camera_mute_checkbox"):
                self.camera_mute_checkbox.setChecked(saved_muted)
            if hasattr(self, "dashboard_volume_slider"):
                self.dashboard_volume_slider.setValue(int(saved_vol))
            if hasattr(self, "dashboard_mute_checkbox"):
                self.dashboard_mute_checkbox.setChecked(saved_muted)
            if self.media_audio_output:
                self.media_audio_output.setVolume(saved_vol / 100.0)
                self.media_audio_output.setMuted(saved_muted)
        except Exception:
            pass
        # Ensure controls are enabled by default
        self._set_media_controls_enabled(True)

        # Initialize status LED update timer
        self.dashboard_metric_cards = {}
        
        # Connect signals
        self.connect_signals()
        
        # Load settings
        self.load_settings()
        
        # Set window properties
        self.setWindowTitle("Artefakt")
        # Set window size to 1337x840, but clamp to available screen to avoid overflow
        screen = QApplication.primaryScreen()
        if screen:
            avail_geo = screen.availableGeometry()
            target_width = min(1337, avail_geo.width())
            target_height = min(840, avail_geo.height())
            self.resize(target_width, target_height)
            # Center within available area
            self.move(
                avail_geo.x() + (avail_geo.width() - target_width) // 2,
                avail_geo.y() + (avail_geo.height() - target_height) // 2,
            )
        else:
            self.resize(1337, 840)
        
        # Set icon if available
        icon_path = os.path.join("assets", "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        # Show startup message
        self.logger.log("Application initialized", "INFO")
        self.statusBar().showMessage("Ready")
        self.update_run_context_text()
        
        # Initial status update
        self.update_status_indicators() # Perform an initial check
        
        # Show dashboard as default tab
        self.stacked_widget.setCurrentIndex(0)  # Show Projects tab by default
        
        # Set default dashboard graph timeframe
        if hasattr(self, 'dashboard_timespan'):
             # Find the index for "All" and set it
            all_index = self.dashboard_timespan.findText("All")
            if all_index != -1:
                self.dashboard_timespan.setCurrentIndex(all_index)
            else:
                # If "All" is not found, add it and set it as current
                self.dashboard_timespan.insertItem(0, "All")
                self.dashboard_timespan.setCurrentIndex(0)
                self.logger.log("Added 'All' to dashboard timespan.", "INFO")

        # Harmonized Auto-connect is now handled by sensor_controller.initialize() 
        # and main_window._connect_virtual_sensors().
        # No need for old-style manual auto-connects here.

        # Ensure the graph live update checkbox state is properly handled after all initialization
        # This fixes the issue where the checkbox is checked but the graph doesn't refresh on startup
        if hasattr(self, 'graph_controller'):
            self.graph_controller.ensure_main_graph_live_update()

    def init_timers(self):
        """Initialize application timers"""
        # UI update timer
        self.ui_timer = QTimer()
        self.ui_timer.timeout.connect(self.update_ui)
        self.ui_timer.start(100) # Update status less frequently maybe? 10 FPS
        
        # Blink timer for recording indicator
        self.blink_timer = QTimer()
        self.blink_timer.setInterval(1000)  # 1Hz
        self.blink_visible = True
        self.blink_timer.timeout.connect(self.update_running_text)

    def connect_signals(self):
        """Connect signals for UI elements to event handlers"""
        # Connect main buttons
        # NOTE: toggle_btn.clicked is already connected in ui_setup.py, don't duplicate!
        # self.toggle_btn.clicked.connect(self.on_toggle_clicked)
        
        # Connect project import/export buttons
        if hasattr(self, 'import_project_btn') and hasattr(self, 'project_controller'):
            self.import_project_btn.clicked.connect(self.project_controller.import_project)
            
        if hasattr(self, 'export_project_btn') and hasattr(self, 'project_controller'):
            self.export_project_btn.clicked.connect(self.project_controller.export_project)
            
        if hasattr(self, 'load_project_btn') and hasattr(self, 'project_controller'):
            self.load_project_btn.clicked.connect(self.project_controller.on_load_run_clicked)
        
        if hasattr(self, 'delete_run_btn') and hasattr(self, 'project_controller'):
            self.delete_run_btn.clicked.connect(self.project_controller.on_delete_run_clicked)
        
        # Connect browse base directory button
        if hasattr(self, 'browse_base_dir_btn') and hasattr(self, 'project_controller'):
            # Disconnect any existing connections first to avoid duplicates
            try:
                self.browse_base_dir_btn.clicked.disconnect()
            except:
                pass
            # Connect to the correct method in project_controller
            self.browse_base_dir_btn.clicked.connect(self.project_controller.on_load_dir_clicked)
            self.logger.log("Connected browse button for base directory", "INFO")

        # Dashboard Header Action buttons
        if hasattr(self, 'dash_snapshot_btn'):
            self.dash_snapshot_btn.clicked.connect(self.take_snapshot)
        if hasattr(self, 'dash_note_btn'):
            self.dash_note_btn.clicked.connect(self.add_quick_note)
        if hasattr(self, 'dash_settings_btn'):
            self.dash_settings_btn.clicked.connect(self.show_dashboard_settings)
            
        # Replay controls
        if hasattr(self, 'replay_play_btn'):
            self.replay_play_btn.clicked.connect(self.on_replay_play_toggle)
        if hasattr(self, 'replay_coarse'):
            self.replay_coarse.valueChanged.connect(self.on_replay_slider_changed)
        if hasattr(self, 'replay_speed'):
            self.replay_speed.currentIndexChanged.connect(self.on_replay_speed_changed)
        if hasattr(self, 'video_volume_slider'):
            self.video_volume_slider.valueChanged.connect(self.on_video_volume_changed)
        if hasattr(self, 'video_mute_checkbox'):
            self.video_mute_checkbox.toggled.connect(self.on_video_mute_toggled)
        if hasattr(self, 'camera_volume_slider'):
            self.camera_volume_slider.valueChanged.connect(self.on_video_volume_changed)
        if hasattr(self, 'camera_mute_checkbox'):
            self.camera_mute_checkbox.toggled.connect(self.on_video_mute_toggled)
        if hasattr(self, 'dashboard_volume_slider'):
            self.dashboard_volume_slider.valueChanged.connect(self.on_video_volume_changed)
        if hasattr(self, 'dashboard_mute_checkbox'):
            self.dashboard_mute_checkbox.toggled.connect(self.on_video_mute_toggled)
        
        # Snapshot navigation
        if hasattr(self, 'snapshot_back_btn'):
            self.snapshot_back_btn.clicked.connect(self.prev_snapshot)
        if hasattr(self, 'snapshot_view_btn'):
            self.snapshot_view_btn.clicked.connect(self.view_snapshot_popup)
        if hasattr(self, 'snapshot_next_btn'):
            self.snapshot_next_btn.clicked.connect(self.next_snapshot)
        
        # NOTE: The controller signals (data flow, graphs, metrics) are now connected 
        # exclusively in connect_controller_signals() to avoid redundant updates.
        
        # Connect sensor controller signals
        if hasattr(self, 'sensor_controller'):
            # Connect status change signal
            self.sensor_controller.status_changed.connect(self.update_status_indicators)
            self.sensor_controller.connect_signals()
            
            # DO NOT connect buttons directly here - this creates conflicts
            # Buttons are connected properly in setup_sensor_tab_signals() 
            # These direct connections can cause conflicts
            # Instead, setup_sensor_tab_signals connects the buttons to main window methods
            # which then call the controller methods

        if hasattr(self, 'camera_controller'):
            self.camera_controller.status_changed.connect(self.update_status_indicators)
            self.camera_controller.status_changed.connect(self.refresh_dashboard_camera_sources) # Auto-refresh dashboard sources
            self.camera_controller.snapshot_taken.connect(self.on_snapshot_taken)
            self.camera_controller.connect_signals()
            
        if hasattr(self, 'automation_controller'):
            self.automation_controller.status_changed.connect(self.update_status_indicators)
            # Connect UI buttons to controller methods

        
        # Connect dashboard camera sources
        self.refresh_dashboard_camera_sources()
        
        # Force initial hide of rows and labels
        self._update_row_visibilities()
        
        # Connect navigation buttons
        for i, btn in enumerate(self.nav_buttons):
            btn.clicked.connect(lambda checked, index=i: self.stacked_widget.setCurrentIndex(index))
        
        # Connect tab change signal to handle tab-specific initialization
        self.stacked_widget.currentChanged.connect(self.on_tab_changed)
        
        # Connect settings-related signals
        self.apply_settings_btn.clicked.connect(self.apply_settings)
        
        # Connect project browser tree view
        if hasattr(self, 'project_tree') and hasattr(self, 'project_controller'):
            self.project_tree.clicked.connect(self.project_controller.on_project_tree_clicked)

        # Connect interface status signal to update device status display
        if hasattr(self, 'data_collection_controller'):
            self.data_collection_controller.interface_status_signal.connect(self.handle_interface_status)
            # Connect data received signal to graph controller ONLY if live plotting is NOT active for the main graph
            # Live plotting is handled separately by plot_new_data connected to combined_data_signal
            # if hasattr(self, 'graph_controller'):
            #      self.data_collection_controller.data_received_signal.connect(self.graph_controller.plot_new_data) # Use correct signal name

        # Connect graph live update checkbox
        if hasattr(self, 'graph_live_update_checkbox'):
            self.graph_live_update_checkbox.stateChanged.connect(self.handle_graph_live_update_toggle)

        # Connect graph controls
        if hasattr(self, 'graph_type_combo') and hasattr(self, 'graph_controller'):
            self.graph_type_combo.currentIndexChanged.connect(self.graph_controller.on_graph_type_changed)
            self.graph_primary_sensor.currentIndexChanged.connect(self.graph_controller.update_graph)
            self.graph_secondary_sensor.currentIndexChanged.connect(self.graph_controller.update_graph)
            self.graph_timespan.currentIndexChanged.connect(self.graph_controller.on_timespan_changed)
            self.dashboard_timespan.currentIndexChanged.connect(self.graph_controller.on_dashboard_timespan_changed)
            # Connect graph controller signals (including context menu setup)
            self.graph_controller.connect_signals()
            # Connect multi-sensor list changes to update the graph immediately
            if hasattr(self, 'multi_sensor_list'):
                self.multi_sensor_list.itemChanged.connect(self.graph_controller.update_graph)
        
        # Connect control run controls
        if hasattr(self, 'control_run_selector') and hasattr(self, 'control_run_controller'):
            self.control_run_selector.currentIndexChanged.connect(self.on_control_run_selected)
            self.control_run_time_offset.valueChanged.connect(self.on_control_run_time_offset_changed)
            # Connect to update both graph and sensor dropdowns when control run changes
            self.control_run_controller.control_run_changed.connect(self.on_control_run_changed_update)
            # Populate control run selector on startup
            self.populate_control_run_selector()
        
        # Setup status bar click for data flow page access
        self.setup_status_bar_click()

    def on_tab_changed(self, index):
        """Handle tab change event"""
        # Get reference to the current widget
        current_widget = self.stacked_widget.widget(index)
        
        # Update specific tab content based on widget references instead of names/indices
        if hasattr(self, 'dashboard_tab') and current_widget == self.dashboard_tab:
            if hasattr(self, 'graph_controller'):
                self.graph_controller.update_dashboard_graph()
            
            # Update the dashboard snapshot image
            self._update_snapshot_display()
            
            # Ensure row visibilities are correct
            self._update_row_visibilities()
            
            # Update the dashboard camera preview
            if hasattr(self, 'dashboard_camera_labels'):
                for lbl in self.dashboard_camera_labels:
                    if lbl.isVisible():
                        lbl.update()
                    
        elif hasattr(self, 'graphs_tab') and current_widget == self.graphs_tab:
            # When switching to graphs tab, update the graph display
            if hasattr(self, 'graph_controller'):
                self.graph_controller.update_graph()
                
        elif hasattr(self, 'notes_tab') and current_widget == self.notes_tab:
            # When switching to notes tab, load the note content
            if hasattr(self, 'notes_controller'):
                # Only reload from disk if content hasn't been loaded yet
                if not self.notes_controller.document_loaded:
                    self.notes_controller.load_note()
        
        # Save notes when moving away from Notes tab
        previous_index = getattr(self, 'previous_tab_index', -1)
        if previous_index != -1:
            previous_widget = self.stacked_widget.widget(previous_index)
            if hasattr(self, 'notes_tab') and previous_widget == self.notes_tab:
                if hasattr(self, 'notes_controller'):
                    self.notes_controller.autosave_note()
                
        # Store the current tab index for next time
        self.previous_tab_index = index

    def show_project_help(self):
        """Show a detailed explanation of the project-driven data management"""
        help_text = """
        <h3>Project-Driven Approach</h3>
        <p>In <b>Artefakt DAQ</b>, data is organized in a hierarchy: <b>Project > Test Series > Run</b>.</p>
        
        <p><b>Startup & Active Context:</b></p>
        <ul>
            <li><b>Automatic Restoration:</b> On startup, the app restores your <b>last active run</b> so you can continue where you left off.</li>
            <li><b>Global Settings Persistence:</b> When the app starts up, it automatically applies your <b>latest global settings</b> (like sampling rate, testers, and automation sequences) over the loaded run. This ensures your most recent changes (e.g. to the 'Testers' field) are preserved even if they weren't saved to a run yet.</li>
            <li><b>Manual Loading:</b> If you manually select and load an old run from the project tree, the <b>original settings</b> from that specific run folder are loaded, giving you a true historical view.</li>
        </ul>

        <p><b>How Data Saving Works:</b></p>
        <ul>
            <li><b>Configuration:</b> Any changes you make to <b>Sensors, Virtual Sensors, Cameras, or Automations</b> are saved to the 
                <b>global configuration</b>. These settings become the template for your <i>next</i> new run.</li>
            <li><b>Notes:</b> The <b>Notes</b> tab is run-specific. Edits there are saved directly into the 
                active run folder.</li>
            <li><b>New Runs:</b> Clicking 'Start' creates a <b>fresh Run folder</b> and copies your 
                current global setup into it, preserving the history of every experiment.</li>
        </ul>
        
        <p><b>Recommendations:</b></p>
        <ul>
            <li><b>Templates:</b> To use an old run as a template, simply load it. Its settings will be adopted as 
                your current configuration. When you click 'Start', these will be saved into the new run.</li>
            <li><b>New Setups:</b> For fundamental changes to sensor or automation logic, it is recommended to create a <b>new Test Series</b>.</li>
        </ul>
        """
        msg = QMessageBox(self)
        msg.setWindowTitle("Project Management Help")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(help_text)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.setStyleSheet(DialogStyles.dark_dialog())
        msg.exec()

    def update_ui(self):
        """Update UI elements"""
        # Call the status update function periodically
        self.update_status_indicators()
        # Any other periodic UI updates can go here

    def show_dashboard_settings(self):
        """Show a popup to configure dashboard settings like trend smoothing"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QSpinBox, QDialogButtonBox
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Dashboard Settings")
        dialog.setMinimumWidth(300)
        dialog.setStyleSheet(DialogStyles.dark_dialog())
        
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        
        # Trend Window Size
        window_spin = QSpinBox()
        window_spin.setRange(1, 100)
        current_window = self.config.get("dash_trend_window", 5)
        window_spin.setValue(current_window)
        window_spin.setStyleSheet(InputStyles.default())
        form.addRow("Trend Window Size (samples):", window_spin)
        
        # Graph Simplification (Downsampling)
        downsampling_check = QCheckBox("Enable Graph Simplification")
        downsampling_check.setToolTip("Reduces data points displayed on graphs for better performance. Disable to see every detail.")
        # Use SettingsModel for this value as it's a global graph setting
        is_enabled = self.settings_model.get_bool("graph_downsampling", True)
        downsampling_check.setChecked(is_enabled)
        form.addRow("Performance:", downsampling_check)
        
        layout.addLayout(form)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_window = window_spin.value()
            self.config["dash_trend_window"] = new_window
            self.save_config()
            
            # Save downsampling setting
            self.settings_model.set_value("graph_downsampling", downsampling_check.isChecked())
            
            # Update Graphs tab checkbox if it exists
            if hasattr(self, 'graph_downsampling_checkbox'):
                self.graph_downsampling_checkbox.blockSignals(True)
                self.graph_downsampling_checkbox.setChecked(downsampling_check.isChecked())
                self.graph_downsampling_checkbox.blockSignals(False)
            
            # Update existing cards
            if hasattr(self, 'dashboard_metric_cards'):
                for card in self.dashboard_metric_cards.values():
                    card.set_window_size(new_window)
            
            # Refresh dashboard graph with new settings
            if hasattr(self, 'graph_controller'):
                # Apply new setting to live graph if it's active
                self.graph_controller.apply_plot_formatting()
            
            self.add_dashboard_event(f"Dashboard settings updated (Trend: {new_window}, Simplification: {'ON' if downsampling_check.isChecked() else 'OFF'})", "INFO")

    def clear_dashboard_events(self):
        """Clear all events from the dashboard events list"""
        if hasattr(self, 'dash_events_list'):
            self.dash_events_list.clear()
    
    def add_dashboard_event(self, message, level="INFO", log_to_csv=True):
        """Add a system event to the dashboard events list"""
        if not hasattr(self, 'dash_events_list'):
            return
            
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        item_text = f"[{timestamp}] {message}"
        
        from PyQt6.QtWidgets import QListWidgetItem
        from PyQt6.QtGui import QColor
        
        item = QListWidgetItem(item_text)
        
        # Color code based on level
        if level == "ERROR":
            item.setForeground(QColor(COLORS.ERROR))
        elif level == "WARNING":
            item.setForeground(QColor(COLORS.WARNING))
        elif level == "SUCCESS":
            item.setForeground(QColor(COLORS.SUCCESS))
        else:
            item.setForeground(QColor(COLORS.TEXT_SECONDARY))
            
        self.dash_events_list.insertItem(0, item)
        
        # Keep only the last 50 events
        if self.dash_events_list.count() > 50:
            self.dash_events_list.takeItem(self.dash_events_list.count() - 1)

        # Record this event for replay if we're currently collecting data
        if log_to_csv and getattr(self, 'running', False) and hasattr(self, 'data_collection_controller'):
            try:
                event = {
                    'type': 'action', # Treat as action for CSV recording
                    'timestamp': time.time(),
                    'action_description': message,
                    'level': level
                }
                self.data_collection_controller.handle_automation_event(event)
            except Exception:
                pass

    def update_dashboard_metrics(self, data):
        """Update the live metric cards on the dashboard"""
        if not data:
            return
            
        # Determine source of data
        source = data.get('_source')
        
        # Live data source - only update if actively collecting (recording)
        is_collecting = False
        if hasattr(self, 'data_collection_controller'):
            is_collecting = self.data_collection_controller.collecting_data
            
        is_replaying = getattr(self, "replay_mode_enabled", False)
        
        # Determine if we should allow the update
        allow_update = False
        if source == 'replay':
            # Always allow updates from explicit replay source (slider/playback/preload)
            allow_update = True
        elif is_collecting:
            # Allow live updates ONLY if actively collecting
            allow_update = True
            
        if not allow_update:
            return

        if not hasattr(self, 'metrics_grid'):
            return
            
        if not hasattr(self, 'dashboard_metric_cards'):
            self.dashboard_metric_cards = {}
            
        # Get list of enabled sensors that should be shown
        if not hasattr(self, 'sensor_controller'):
            return
            
        # 1. Track which sensors are actually in the system
        active_sensor_keys = set()
        
        for sensor in self.sensor_controller.sensors:
            # ONLY show enabled sensors that are marked for graphing
            if not getattr(sensor, 'enabled', True) or not getattr(sensor, 'show_in_graph', True):
                continue
                
            # Get the official historical key for this sensor
            sensor_key = self.sensor_controller.get_historical_buffer_key(sensor)
            if not sensor_key:
                continue
            
            active_sensor_keys.add(sensor_key)
            
            # Create card if it doesn't exist
            if sensor_key not in self.dashboard_metric_cards:
                from app.ui.ui_setup import DashMetricCard
                card = DashMetricCard(sensor.name, sensor.unit, sensor.color)
                # Set initial window size from config
                window_size = self.config.get("dash_trend_window", 5)
                card.set_window_size(window_size)
                
                # Add to cards dictionary and rearrange
                self.dashboard_metric_cards[sensor_key] = card
                self.rearrange_dashboard_metrics()
                
            # Update card value
            val = None
            
            # If in replay mode or source is replay, prioritize data dict values
            if is_replaying or source == 'replay':
                val = data.get(sensor_key)
                if val is None:
                    # Try case-insensitive matching if direct key fails
                    for k, v in data.items():
                        if k.lower() == sensor_key.lower():
                            val = v
                            break
                    
                if val is None:
                    # Try unprefixed name as a fallback (splitting only once from the left)
                    unprefixed = sensor_key.split('_', 1)[1] if '_' in sensor_key else None
                    if unprefixed:
                        val = data.get(unprefixed)
                    
                    # If still None, try matching by the sensor name itself
                    if val is None:
                        val = data.get(sensor.name)
            else:
                # In live mode, prioritize current_value from sensor model
                # as it's already corrected and filtered by the controllers
                
                # Check for staleness first
                is_stale = False
                if hasattr(self, 'data_collection_controller'):
                    dcc = self.data_collection_controller
                    if sensor_key in dcc._last_sensor_update:
                        last_ts = dcc._last_sensor_update[sensor_key]
                        timeout_val = dcc._get_stale_timeout_for_key(sensor_key)
                        if time.time() - last_ts > timeout_val:
                            is_stale = True
                    else:
                        # If no update yet but has value, check if it's a CSV sensor
                        if getattr(sensor, 'interface_type', '') == "CSV":
                             is_stale = False
                
                if is_stale:
                    val = None # Mark as None to show as empty/stale on card
                else:
                    val = getattr(sensor, 'current_value', None)
                
                # If current_value is None, try to find it in the provided data dict
                if val is None and not is_stale:
                    val = data.get(sensor_key)
                    if val is None:
                        unprefixed = sensor_key.split('_', 1)[1] if '_' in sensor_key else None
                        if unprefixed:
                            val = data.get(unprefixed)
                if val is None:
                    val = data.get(sensor.name)
                
            # Always call update_value to ensure the card clears itself when a sensor becomes stale
            self.dashboard_metric_cards[sensor_key].update_value(val)
            
        # 2. Cleanup orphaned cards (sensors that were deleted or disabled)
        keys_to_remove = []
        for key in list(self.dashboard_metric_cards.keys()):
            if key not in active_sensor_keys:
                keys_to_remove.append(key)
                
        for key in keys_to_remove:
            card = self.dashboard_metric_cards.pop(key)
            self.metrics_grid.removeWidget(card)
            card.deleteLater()
            
        if keys_to_remove:
            self.rearrange_dashboard_metrics()
                
    def rearrange_dashboard_metrics(self):
        """Rearrange metric cards in the grid based on available width"""
        if not hasattr(self, 'metrics_grid') or not hasattr(self, 'dashboard_metric_cards'):
            return
            
        if not self.dashboard_metric_cards:
            return
            
        # Determine number of columns based on width
        # The container width tells us how much space we have in the splitter
        container_width = self.metrics_container.width()
        
        # Calculate number of columns based on width
        # Each card is now fixed at 130px wide + 8px spacing = 138px
        if container_width > 966:
            num_cols = 7
        elif container_width > 828:
            num_cols = 6
        elif container_width > 690:
            num_cols = 5
        elif container_width > 552:
            num_cols = 4
        elif container_width > 414:
            num_cols = 3
        elif container_width > 276:
            num_cols = 2
        else:
            num_cols = 1
        
        # Get sorted list of keys to maintain consistent order
        # We sort by the sensor name for a logical display
        sorted_keys = sorted(
            self.dashboard_metric_cards.keys(),
            key=lambda k: getattr(self.dashboard_metric_cards[k], 'sensor_name', k)
        )
        
        # Remove all widgets from the layout without deleting them
        while self.metrics_grid.count():
            item = self.metrics_grid.takeAt(0)
            # No need to do anything with the item, it's just a layout item
        
        # Re-add in the new grid positions
        for i, key in enumerate(sorted_keys):
            card = self.dashboard_metric_cards[key]
            row = i // num_cols
            col = i % num_cols
            # Use alignment to prevent the card from stretching to fill the grid cell
            self.metrics_grid.addWidget(card, row, col, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            
        # Clear any old row/column stretches
        for r in range(self.metrics_grid.rowCount() + 1):
            self.metrics_grid.setRowStretch(r, 0)
        for c in range(self.metrics_grid.columnCount() + 1):
            self.metrics_grid.setColumnStretch(c, 0)
            
        # Add a stretch to the right and bottom to keep cards packed at the top-left
        self.metrics_grid.setColumnStretch(num_cols, 1)
        self.metrics_grid.setRowStretch(self.metrics_grid.rowCount(), 1)

    def update_dashboard_header(self):
        """Update project and run info in the dashboard header"""
        try:
            # Project Info
            if hasattr(self, 'project_selector'):
                project_name = self.project_selector.currentText() or "---"
                if hasattr(self, 'dash_project_val'):
                    self.dash_project_val.setText(project_name)
                    
            if hasattr(self, 'test_series_selector'):
                series_name = self.test_series_selector.currentText() or "---"
                if hasattr(self, 'dash_series_val'):
                    self.dash_series_val.setText(series_name)
                    
            if hasattr(self, 'project_controller'):
                # Try to get run count or description
                run_text = "---"
                if getattr(self.project_controller, 'current_run', None):
                    run_text = self.project_controller.current_run
                elif getattr(self, 'running', False):
                    run_text = "Acquiring..."
                elif hasattr(self, 'run_context_label'):
                     # Fallback to run context label
                     ctx = self.run_context_label.text()
                     if ":" in ctx:
                         run_text = ctx.split(": ", 1)[1]
                
                if hasattr(self, 'dash_run_val'):
                    self.dash_run_val.setText(run_text)
            
            # Duration
            if self.running and self.start_time:
                elapsed = time.time() - self.start_time
                hrs = int(elapsed // 3600)
                mins = int((elapsed % 3600) // 60)
                secs = int(elapsed % 60)
                if hasattr(self, 'dash_duration_val'):
                    self.dash_duration_val.setText(f"{hrs:02d}:{mins:02d}:{secs:02d}")
            elif not self.running:
                if hasattr(self, 'dash_duration_val'):
                    self.dash_duration_val.setText("00:00:00")
                    
        except Exception as e:
            # self.logger.log(f"Error updating dashboard header: {e}", "DEBUG")
            pass

    def add_quick_note(self):
        """Add a quick timestamped note to the current run"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox, QLabel
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Quick Note")
        dialog.setMinimumSize(500, 300)
        dialog.setStyleSheet(DialogStyles.dark_dialog())
        
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Enter your note below:"))
        
        note_edit = QTextEdit()
        note_edit.setPlaceholderText("Type note content here...")
        note_edit.setStyleSheet(InputStyles.default())
        layout.addWidget(note_edit)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            text = note_edit.toPlainText().strip()
            if text:
                timestamp = "---"
                if self.running and self.start_time:
                    elapsed = time.time() - self.start_time
                    hrs = int(elapsed // 3600)
                    mins = int((elapsed % 3600) // 60)
                    secs = int(elapsed % 60)
                    timestamp = f"{hrs:02d}:{mins:02d}:{secs:02d}"
                
                note_entry = f"<br/><p><b>[{timestamp}] Dashboard Note:</b> {text}</p>"
                if hasattr(self, 'notes_controller'):
                    self.notes_controller.append_to_note(note_entry)
                    self.add_dashboard_event(f"Note added: {text[:20]}...", "INFO")
                    self.logger.log(f"Quick note added from dashboard: {text}", "INFO")

    def update_status_indicators(self):
        """Update the status indicators for each component"""
        # Update dashboard LEDs
        if hasattr(self, 'led_daq'):
            daq_ok = (self.sensor_status == StatusState.READY)
            self.led_daq.setStyleSheet(StatusIndicator.online(12) if daq_ok else StatusIndicator.offline(12))
        
        if hasattr(self, 'led_recording'):
            is_rec = getattr(self, 'running', False)
            self.led_recording.setStyleSheet(StatusIndicator.online(12) if is_rec else StatusIndicator.inactive(12))
            
        if hasattr(self, 'led_automation'):
            auto_active = False
            if hasattr(self, 'automation_controller'):
                auto_active = self.automation_controller.is_running()
            self.led_automation.setStyleSheet(StatusIndicator.online(12) if auto_active else StatusIndicator.inactive(12))
            
        # Update dashboard header info
        self.update_dashboard_header()

        # Update outbound plugins status
        if hasattr(self, 'data_collection_controller'):
            for plugin in self.data_collection_controller.outbound_plugins:
                name = getattr(plugin, 'name', '')
                is_connected = plugin.is_connected()
                self.update_generic_interface_status(name, is_connected)

        # Get status for each controller
        try:
            if hasattr(self, 'project_controller'):
                self.project_status, project_tooltip = self.project_controller.get_status()
            else:
                self.project_status, project_tooltip = StatusState.ERROR, "Project Controller not ready"
        except AttributeError:
            self.project_status, project_tooltip = StatusState.ERROR, "Project Controller not ready"

        try:
            if hasattr(self, 'sensor_controller'):
                sensor_status_info = self.sensor_controller.get_status()
                sensor_count = sensor_status_info["sensor_count"]
                
                # Dynamic sensor connection tracking
                active_sensor_count = 0
                connected_parts = {} # {interface_name: count}
                missing_parts = {}   # {interface_name: count}
                
                if hasattr(self.sensor_controller, 'sensors'):
                    for s in self.sensor_controller.sensors:
                        if getattr(s, 'show_in_graph', False) and getattr(s, 'enabled', True):
                            active_sensor_count += 1
                            interface_name = getattr(s, 'interface_type', 'Unknown')
                            interface_key = interface_name.lower()
                            
                            # Determine if this specific interface is connected
                            is_connected = False
                            
                            # 1. Check our tracked interface connections
                            if hasattr(self, 'interface_connections') and interface_key in self.interface_connections:
                                is_connected = self.interface_connections[interface_key]
                            # 2. Fallback to specialized checks if not in dict yet
                            elif interface_key == 'arduino':
                                is_connected = getattr(self.data_collection_controller, 'arduino_connected', False) if hasattr(self, 'data_collection_controller') else False
                            elif interface_key == 'labjack':
                                is_connected = getattr(self.data_collection_controller, 'labjack_connected', False) if hasattr(self, 'data_collection_controller') else False
                                if not is_connected and hasattr(self.sensor_controller, 'labjack_connected'):
                                    is_connected = self.sensor_controller.labjack_connected
                            elif interface_key in ['audiosensor', 'audio_sensor']:
                                # We check this dynamically in update_audio_sensor_status, but for now use the count
                                # This is a bit recursive, but should work if update_audio_sensor_status was called
                                is_connected = self.interface_connections.get('audiosensor', False)
                            elif interface_key in ['opticalsensor', 'optical_sensor']:
                                is_connected = self.interface_connections.get('opticalsensor', False)
                            elif interface_key in ['otherserial', 'other_serial']:
                                is_connected = getattr(self.data_collection_controller, 'other_serial_connected', False) if hasattr(self, 'data_collection_controller') else False
                            elif interface_key == 'mqtt':
                                is_connected = getattr(self.data_collection_controller, 'mqtt_connected', False) if hasattr(self, 'data_collection_controller') else False
                            elif interface_key == 'csv':
                                is_connected = self.interface_connections.get('csv', False)
                            
                            # Record status
                            if is_connected:
                                connected_parts[interface_name] = connected_parts.get(interface_name, 0) + 1
                            else:
                                missing_parts[interface_name] = missing_parts.get(interface_name, 0) + 1

                # Determine status based on ACTIVE sensors AND hardware connection
                if sensor_count == 0:
                    self.sensor_status = StatusState.OPTIONAL
                    sensor_tooltip = "No sensors configured (Optional)"
                elif active_sensor_count == 0:
                    self.sensor_status = StatusState.OPTIONAL
                    sensor_tooltip = f"{sensor_count} sensor(s) configured, but none active (enable 'Use')"
                else:
                    if connected_parts:
                        # At least one active sensor type is connected - status is READY (green)
                        self.sensor_status = StatusState.READY
                        
                        parts = []
                        for name, count in connected_parts.items():
                            parts.append(f"{name} ({count})")
                        
                        sensor_tooltip = f"{active_sensor_count} active sensor(s): " + ", ".join(parts) + " connected"
                        
                        if missing_parts:
                            missing_list = [f"{name}" for name in missing_parts.keys()]
                            sensor_tooltip += f"\nMissing: " + ", ".join(missing_list)
                            
                        if sensor_status_info.get("acquisition_running", False):
                            sensor_tooltip += "\nData acquisition in progress"
                    else:
                        # No active sensors are connected
                        self.sensor_status = StatusState.OPTIONAL
                        missing_list = [f"{name} ({count} sensor(s))" for name, count in missing_parts.items()]
                        sensor_tooltip = f"{active_sensor_count} active sensor(s), but hardware not connected:\n• " + "\n• ".join(missing_list)
                
                # Ensure sensors are never ERROR (red), only OPTIONAL (yellow/orange) or READY (green)
                if self.sensor_status == StatusState.ERROR:
                    self.sensor_status = StatusState.OPTIONAL
                    sensor_tooltip = "No sensors defined (optional but recommended)"
            else:
                self.sensor_status, sensor_tooltip = StatusState.OPTIONAL, "Sensor Controller not ready"
        except Exception as e:
            print(f"Error getting sensor status: {str(e)}")
            self.sensor_status, sensor_tooltip = StatusState.OPTIONAL, "Sensor Controller not ready"

        try:
            if hasattr(self, 'camera_controller'):
                self.camera_status, camera_tooltip = self.camera_controller.get_status()
            else:
                self.camera_status, camera_tooltip = StatusState.OPTIONAL, "Camera Controller not ready"
        except AttributeError:
            self.camera_status, camera_tooltip = StatusState.OPTIONAL, "Camera Controller not ready"

        try:
            if hasattr(self, 'automation_controller'):
                self.automation_status, automation_tooltip = self.automation_controller.get_status()
            else:
                self.automation_status, automation_tooltip = StatusState.OPTIONAL, "Automation Controller not ready"
        except AttributeError:
            self.automation_status, automation_tooltip = StatusState.OPTIONAL, "Automation Controller not ready"

        # Update device-specific status displays (Audio, Optical, etc.)
        if hasattr(self, 'update_audio_sensor_status'):
            self.update_audio_sensor_status()
        if hasattr(self, 'update_optical_sensor_status'):
            self.update_optical_sensor_status()

        # --- 2. Update Button Icons and Tooltips ---
        # This assumes you have SVG files named like: Projects_green.svg, Projects_red.svg, etc.
        # And that self.nav_buttons indices correspond correctly. **Verify these indices.**
        button_map = {
             # Map component status to button index and base icon name - updated to match new order
             "project": (0, "Projects"), # nav_buttons[0] is Project button
             "sensors": (3, "Sensors"),  # nav_buttons[3] is Sensors button
             "camera": (2, "Camera"),    # nav_buttons[2] is Camera button
             "automation": (4, "Automation") # nav_buttons[4] is Automation button
        }

        status_color_map = {
            StatusState.READY: "green",
            StatusState.OPTIONAL: "yellow",
            StatusState.ERROR: "red",
            StatusState.RUNNING: "green", # Add mapping for RUNNING state
        }

        statuses = {
            "project": (self.project_status, project_tooltip),
            "sensors": (self.sensor_status, sensor_tooltip),
            "camera": (self.camera_status, camera_tooltip),
            "automation": (self.automation_status, automation_tooltip),
        }

        # Path to icons - adjust if they are elsewhere
        icon_base_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "ui")

        for component, (index, base_name) in button_map.items():
            if index < len(self.nav_buttons): # Check index bounds
                status, tooltip = statuses[component]
                color = status_color_map.get(status, "red") # Default to red if status unknown

                # Handle yellow state - project is never yellow, others are optional
                if status == StatusState.OPTIONAL:
                     if component == "project": # Project cannot be optional/yellow
                          color = "red" # Treat optional project as error
                          tooltip = "Project details must be completed." # Override tooltip
                     else:
                          tooltip = f"{base_name}: Not active (Optional)" # Default yellow tooltip

                # Construct icon path
                icon_path = os.path.join(icon_base_path, f"{base_name}_{color}.svg")

                # Check if icon file exists, otherwise use a default or log error
                if not os.path.exists(icon_path):
                     self.logger.log(f"Icon file not found: {icon_path}", "WARN")
                     # Try to use the default icon without color
                     default_icon_path = os.path.join(icon_base_path, f"{base_name}.svg")
                     if os.path.exists(default_icon_path):
                         self.nav_buttons[index].setIcon(QIcon(default_icon_path))
                     # Skip this iteration if no icon found
                     continue

                # Set the colored icon
                self.nav_buttons[index].setIcon(QIcon(icon_path))

                # Set tooltip
                self.nav_buttons[index].setToolTip(tooltip)
            else:
                self.logger.log(f"Button index {index} for {component} out of range.", "WARN")


        # --- 3. Update Start/Stop Button State ---
        # Determine overall readiness
        project_ready = self.project_status == StatusState.READY
        
        # Check if run description is empty
        run_description_empty = False
        if hasattr(self, 'run_description'):
            run_description_text = self.run_description.toPlainText().strip()
            run_description_empty = not run_description_text
                
        # Modified: User should be able to start a run with just sensors
        # Mark system as ready if either sensors or camera are ready, or automation is ready/optional
        optional_ready = (self.sensor_status == StatusState.READY or 
                         self.camera_status == StatusState.READY or 
                         self.automation_status in [StatusState.READY, StatusState.OPTIONAL])

        can_start = project_ready and optional_ready

        # Get original button styles (preserve the styles that were set during UI setup)
        start_btn_original_style = self.start_btn_style
        stop_btn_original_style = self.stop_btn_style
        
        # Check if sidebar is collapsed to use icons instead of text
        is_collapsed = getattr(self, 'sidebar_collapsed', False)
        start_text = "▶" if is_collapsed else "Start"
        stop_text = "■" if is_collapsed else "Stop"
        
        # Adjust styles for collapsed mode if necessary
        if is_collapsed:
            collapsed_padding = "QPushButton { padding: 12px 2px; }"
            start_btn_original_style += collapsed_padding
            stop_btn_original_style += collapsed_padding
        
        # Disabled style - maintains shape and size but adds gray overlay
        padding_val = "12px 2px" if is_collapsed else "8px 15px"
        disabled_style = f"""
        QPushButton {{
            background: #CCCCCC;
            color: #777777;
            border: none;
            padding: {padding_val};
            border-radius: 5px;
            font-weight: bold;
            font-size: 16px;
            border-bottom: 2px solid #AAAAAA;
        }}
        """

        # If we're running, ensure the button stays in Stop mode and status stays as "Running..."
        if self.running:
            self.toggle_btn.setEnabled(True)
            self.toggle_btn.setText(stop_text)
            self.toggle_btn.setStyleSheet(stop_btn_original_style)
            # Don't change the status text when running - it's managed by update_running_text()
            if hasattr(self, 'sidebar_ready_status'):
                # Only update if it's not already set to "Running..." (to avoid interfering with blink effect)
                current_text = self.sidebar_ready_status.text()
                if current_text not in ["Running...", ""]:
                    self.sidebar_ready_status.setText("Running...")
                    self.sidebar_ready_status.setStyleSheet("color: #2ECC40;") # Green
            return
        
        # Only update the button state if we're not already running
        # This prevents the method from changing the button text/style during operation
        if can_start:
            if run_description_empty:
                # Gray out button if run description is empty (system not ready for new test)
                self.toggle_btn.setEnabled(False)
                self.toggle_btn.setStyleSheet(disabled_style)
                self.sidebar_ready_status.setText("Enter Run Description")
                self.sidebar_ready_status.setStyleSheet("color: #FF4136;") # Red
            else:
                # Enable button if everything is ready including run description
                self.toggle_btn.setEnabled(True)
                self.toggle_btn.setStyleSheet(start_btn_original_style)
                self.toggle_btn.setText(start_text)
                self.sidebar_ready_status.setText("Ready")
                self.sidebar_ready_status.setStyleSheet("color: #2ECC40;") # Green
        else:
            self.toggle_btn.setEnabled(False)
            self.toggle_btn.setStyleSheet(disabled_style)
            self.toggle_btn.setText(start_text)
            self.sidebar_ready_status.setText("Not Ready")
            self.sidebar_ready_status.setStyleSheet("color: #FF4136;") # Red
        
        self.update_run_context_text()

    def update_csv_interfaces(self, configs):
        """Update the CSV interfaces when configurations change."""
        self.csv_configs = configs
        if hasattr(self, 'data_collection_controller'):
            self.data_collection_controller.update_csv_interfaces(configs)
        self.update_csv_status()
        self._update_csv_virtual_sensors()
        self.save_virtual_sensors()

    def update_run_context_text(self, mode=None, run_name=None):
        """Update the status bar run context label to show what the user is viewing."""
        if not hasattr(self, "run_context_label"):
            return
        
        # Resolve run name from controller if not provided
        if run_name is None and hasattr(self, "project_controller"):
            run_name = getattr(self.project_controller, "current_run", "") or ""
        
        # Pick a default mode if none supplied
        if mode is None:
            if getattr(self, "running", False):
                mode = "Running"
            elif getattr(self, "replay_mode_enabled", False):
                mode = "Showing the previous run"
            elif run_name:
                mode = "Loaded run"
            else:
                mode = "No run loaded"
        
        # Build display text
        if run_name:
            text = f"{mode}: {run_name}"
        else:
            text = mode
        
        self.run_context_label.setText(text)

    def on_toggle_clicked(self):
        """Handle toggle button click - simulate checkbox toggle"""
        print(f"\n[TOGGLE] ===== on_toggle_clicked called, current state: running={self.running} =====")
        import traceback
        print("[TOGGLE] Called from:")
        for line in traceback.format_stack()[:-1]:
            if 'EvoLabs DAQ PY' in line:
                print(line.rstrip())
        
        # Add a simple debounce to prevent rapid toggling
        if hasattr(self, '_toggle_last_click'):
            now = datetime.datetime.now()
            if (now - self._toggle_last_click).total_seconds() < 0.5:
                print(f"[TOGGLE] Ignoring rapid toggle click, last click: {self._toggle_last_click}")
                self.logger.log("Ignoring rapid toggle click (debounce protection)", "DEBUG")
                return
        self._toggle_last_click = datetime.datetime.now()
        
        # Use self.running state instead of button text
        if self.running:
            # We're running, so stop
            print("[TOGGLE] Stopping acquisition (called from on_toggle_clicked)")
            print(f"[TOGGLE] Stop called with running={self.running}, start_time={self.start_time}")
            self.logger.log("Stopping acquisition", "DEBUG")
            
            # Save testers value to config before stopping
            if hasattr(self, 'run_testers') and hasattr(self, 'config'):
                testers = self.run_testers.text().strip()
                if testers:
                    self.config["last_testers"] = testers
                    self.save_config()
            
            # Update state
            self.running = False
            self.start_time = None # Reset start time
            
            # Update button UI
            if getattr(self, 'sidebar_collapsed', False):
                self.toggle_btn.setText("▶")
            else:
                self.toggle_btn.setText("Start")
            self.toggle_btn.setStyleSheet(self.start_btn_style)
            
            # Stop the blink timer
            if self.blink_timer.isActive():
                self.blink_timer.stop()
            self.update_running_text() # Ensure indicator is cleared
                
            # Reset record button if it exists
            if hasattr(self, 'record_btn'):
                self.record_btn.setEnabled(True)
                self.record_btn.setText("Record")
                self.record_btn.setStyleSheet("background-color: #4CAF50; color: white;")
            
            # --- ADDED: Stop graph updates ---
            # Stop live graph updates
            if hasattr(self, 'graph_controller'):
                print("[TOGGLE] Stopping live dashboard graph updates...")
                self.graph_controller.stop_live_dashboard_update()

            # Stop data collection and acquisition
            if hasattr(self, 'data_collection_controller'):
                print("[TOGGLE] Stopping data collection...")
                self.data_collection_controller.stop_data_collection()
                
            if hasattr(self, 'sensor_controller'):
                print("[TOGGLE] Stopping sensor acquisition...")
                self.sensor_controller.stop_acquisition()
                self.logger.log("Stopped data acquisition")
                
            # Stop video recording if active
            if hasattr(self, 'camera_controller'):
                is_recording = False
                if isinstance(self.camera_controller.is_recording, list):
                    is_recording = any(self.camera_controller.is_recording)
                else:
                    is_recording = self.camera_controller.is_recording
                
                if is_recording:
                    print("[TOGGLE] Stopping video recording...")
                    self.camera_controller.stop_recording()
                    self.logger.log("Stopped video recording")
            
            # --- ADDED: Stop all automation sequences ---
            if hasattr(self, 'automation_controller'):
                print("[TOGGLE] Stopping all automation sequences...")
                self.automation_controller.stop_all_automation()
                self.logger.log("Stopped all automation sequences")

            # Update status message
            self.statusBar().showMessage("Stopped recording")
            print("[TOGGLE] Data acquisition stopped successfully")
            
            # Update status indicators immediately to refresh LEDs
            self.update_status_indicators()
            
            # Clear run description after run is complete - ONLY after stopping
            if hasattr(self, 'run_description'):
                print("[TOGGLE] Clearing run description")
                self.run_description.clear()
                if hasattr(self, 'project_controller'):
                    self.project_controller.run_description = ""
            
            # Update status indicators and UI state
            self.update_status_indicators()
        else:
            # We're not running, so start
            print("[TOGGLE] Button shows 'Start', starting acquisition")
            self.logger.log("Starting acquisition", "DEBUG")
            
            # Ensure controller signals are connected (idempotent safeguard)
            try:
                if not getattr(self, "_controller_signals_connected", False):
                    print("[TOGGLE] Connecting controller signals (was not connected)...")
                    self.connect_controller_signals()
                    self._controller_signals_connected = True
                    print("[TOGGLE] Controller signals connected")
                else:
                    print("[TOGGLE] Controller signals already connected")
            except Exception as e:
                self.logger.log(f"Failed to connect controller signals before start: {e}", "ERROR")
                print(f"[TOGGLE ERROR] Failed to connect signals: {e}")
                import traceback
                traceback.print_exc()
            
            # Verify that run description is not empty before starting
            if hasattr(self, 'run_description'):
                run_description_text = self.run_description.toPlainText().strip()
                if not run_description_text:
                    self.logger.log("Cannot start acquisition - run description is empty", "ERROR")
                    print("[TOGGLE] Cannot start - run description is empty")
                    self.statusBar().showMessage("Please enter a run description")
                    return
            
            if not self.project_controller.validate_run_settings():
                self.logger.log("Run settings validation failed, cannot start acquisition", "ERROR")
                print("[TOGGLE] Run settings validation failed")
                return
                
            # Create a run directory with timestamp before starting acquisition
            run_dir = self.project_controller.prepare_run_directory()
            if not run_dir:
                self.logger.log("Failed to create run directory, cannot start acquisition", "ERROR")
                print("[TOGGLE] Failed to create run directory")
                return
            
            # Exit replay mode when a new run starts
            self._init_replay_ui()
                
            # Initialize the notes template for this run
            if hasattr(self, 'notes_controller'):
                # Create a new note from the template (this will check if notes.html exists)
                self.notes_controller.document_loaded = False  # Reset to force loading from template
                self.notes_controller.load_note()
                self.logger.log("Notes template initialized for this run", "DEBUG")
                
            # Apply global sampling rate from UI before starting data collection
            if hasattr(self, 'sampling_rate_spinbox') and hasattr(self, 'data_collection_controller'):
                sampling_rate_hz = self.sampling_rate_spinbox.value()
                self.data_collection_controller.set_sampling_rate(sampling_rate_hz)
                # Save the rate in Hz to settings
                self.settings.setValue("global_sampling_rate", sampling_rate_hz)
                self.logger.log(f"Applied sampling rate: {sampling_rate_hz:.2f} Hz")
                
            # Update button first
            if getattr(self, 'sidebar_collapsed', False):
                self.toggle_btn.setText("■")
            else:
                self.toggle_btn.setText("Stop")
            self.toggle_btn.setStyleSheet(self.stop_btn_style)
            self.running = True
            self.start_time = time.time() # Record start time for relative plotting
            self.update_run_context_text("Running", getattr(self.project_controller, "current_run", ""))
            
            # Update status to "Running..." immediately
            if hasattr(self, 'sidebar_ready_status'):
                self.sidebar_ready_status.setText("Running...")
                self.sidebar_ready_status.setStyleSheet("color: #2ECC40;") # Green
            
            # Start the blink timer
            self.blink_timer.start()
            self.update_running_text() # Initial update
            
            print(f"[TOGGLE] Created run directory: {run_dir}")
            
            # Clear dashboard events for new run
            self.clear_dashboard_events()
            
            # Start data collection in the data collection controller
            if hasattr(self, 'data_collection_controller'):
                print("[TOGGLE] Starting data collection...")
                self.data_collection_controller.start_data_collection(run_dir)
            
            # --- START GRAPH UPDATES AFTER DATA COLLECTION IS READY ---
            # This ensures that clear_graphs (called in start_data_collection) 
            # doesn't immediately deactivate the live plotting we're about to start.
            if hasattr(self, 'graph_controller'):
                 print("[TOGGLE] Starting live dashboard graph updates...")
                 self.graph_controller.start_live_dashboard_update(self.start_time)
                 # Ensure main graph live update is started if checkbox is checked
                 self.graph_controller.ensure_main_graph_live_update()

            # Start data acquisition and recording if configured
            if hasattr(self, 'sensor_controller'):
                print("[TOGGLE] Starting sensor acquisition...")
                self.sensor_controller.start_acquisition()
            
            # Log start event
            self.logger.log("Data acquisition started")
            print("[TOGGLE] Data acquisition started successfully")
            self.statusBar().showMessage("Acquisition started...")
            
            # Start video recording if any camera is set to record
            if hasattr(self, 'camera_controller'):
                # Check if at least one connected camera has recording enabled in its config
                any_ready_to_record = False
                for i in range(4):
                    if self.camera_controller.is_connected[i] and self.camera_controller.camera_configs[i].get("record_video", True):
                        any_ready_to_record = True
                        break
                
                if any_ready_to_record:
                    if not any(self.camera_controller.is_recording):
                        print("[TOGGLE] Starting recording for enabled cameras...")
                        self.camera_controller.start_recording()
                        self.logger.log("Started video recording")
                    else:
                        print("[TOGGLE] Camera already recording, skipping duplicate start")
                else:
                    print("[TOGGLE] No cameras connected or set to record, skipping recording start")

            # --- ADDED: Start checked automation sequences ---
            if hasattr(self, 'automation_controller'):
                print("[TOGGLE] Starting checked automation sequences...")
                self.automation_controller.start_checked_sequences()
                self.logger.log("Attempted to start checked automation sequences")

            # Update status message
            self.statusBar().showMessage("Recording started")
            print("[TOGGLE] Data acquisition started successfully")
            print(f"[TOGGLE] Final state: running={self.running}, start_time={self.start_time}")
            
            # Update status indicators immediately to refresh LEDs
            self.update_status_indicators()
            
            print("[TOGGLE] Start sequence completed, acquisition should be running now")

    def update_running_text(self):
        """Update the running text with blink effect"""
        if not hasattr(self, 'sidebar_ready_status'):
            return
            
        self.blink_visible = not self.blink_visible
        
        if self.running:
            if self.blink_visible:
                self.sidebar_ready_status.setText("Running...")
                self.sidebar_ready_status.setStyleSheet("color: #2ECC40;") # Green
            else:
                self.sidebar_ready_status.setText("")
        else:
            self.sidebar_ready_status.setText("Ready")
            self.sidebar_ready_status.setStyleSheet("color: #2ECC40;") # Green

    def on_start_clicked(self):
        """Legacy handler that redirects to start_acquisition"""
        self.start_acquisition()
        
    def on_stop_clicked(self):
        """Legacy handler that redirects to stop_acquisition"""
        self.stop_acquisition()

    def toggle_theme(self):
        """Toggle between light and dark theme"""
        if self.theme == "dark":
            # Switch to light theme
            self.theme = "light"
            if hasattr(self, 'theme_switch_btn'):
                self.theme_switch_btn.setText("Switch to Dark Mode")
            # Apply light theme styling
        else:
            # Switch to dark theme
            self.theme = "dark"
            if hasattr(self, 'theme_switch_btn'):
                self.theme_switch_btn.setText("Switch to Light Mode")
            # Apply dark theme styling

    def toggle_log_visibility(self, state):
        """Toggle log panel visibility"""
        if hasattr(self, 'log_text'):
            self.log_text.setVisible(state)
            self.settings.setValue("show_log", "true" if state else "false")

    def load_settings(self, is_startup_load=False):
        """Load application settings"""
        # Load from QSettings first for compatibility
        debug_mode = self.settings.value("debug_mode", "false").lower() == "true"
        show_log = self.settings.value("show_log", "true").lower() == "true"
        
        # Set the log visible or hidden
        if hasattr(self, 'log_panel'):
            self.log_panel.setVisible(show_log)
        
        # Update the theme
        self.theme = self.settings.value("theme", "dark")
        
        # Check for and load base directory from QSettings or config
        base_dir = self.settings.value("base_directory", "")
        
        # If no base directory in QSettings, check the config file
        if not base_dir and hasattr(self, 'config'):
            base_dir = self.config.get("default_project_dir", "")
        
        # If we have a valid base directory, update the UI
        if base_dir and os.path.exists(base_dir) and hasattr(self, 'project_base_dir'):
            self.project_base_dir.setText(base_dir)
            self.logger.log(f"Loaded base directory: {base_dir}")
            
            # Make sure both settings and config have this value
            self.settings.setValue("base_directory", base_dir)
            if hasattr(self, 'config'):
                self.config["default_project_dir"] = base_dir
                self.save_config()
        
        # Load other settings as usual
        self.other_sensors_autoconnect = self.settings.value("other_sensors_autoconnect", "true") == "true"
        
        # Load the global sampling rate setting if it exists
        if hasattr(self, 'sampling_rate_spinbox'):
            # Load sampling rate in Hz (default 1.0 Hz)
            val = self.settings.value("global_sampling_rate", 1.0)
            try:
                saved_rate = float(val) if str(val).lower() != 'none' else 1.0
            except (ValueError, TypeError):
                saved_rate = 1.0
            self.sampling_rate_spinbox.setValue(saved_rate)
            
            # If we have the data collection controller, update it
            if hasattr(self, 'data_collection_controller'):
                self.data_collection_controller.set_sampling_rate(saved_rate)
        
        # Load previous testers if the field exists
        if hasattr(self, 'run_testers') and hasattr(self, 'config'):
            if "last_testers" in self.config:
                testers = self.config.get("last_testers", "")
                if testers:
                    self.run_testers.setText(testers)
        
        # Load application settings from settings model
        self.settings_model.load_settings()

        # Load virtual sensors and sequences first (required for sensor_controller.initialize)
        self.load_virtual_sensors(is_startup_load=is_startup_load)

        # Now perform comprehensive sensor initialization and auto-connection
        if hasattr(self, 'sensor_controller'):
            # This loads sensors.json and handles auto-connect for ALL interface types
            self.sensor_controller.initialize()
            self.logger.log("Sensor controller initialized and auto-connected", "INFO")
        
        # Load automation sequences if the controller is available
        if hasattr(self, 'automation_controller') and is_startup_load:
            self.automation_controller.load_sequences(is_startup_load=True)

        # Handle camera auto-connect if enabled
        if hasattr(self, 'camera_controller') and is_startup_load:
            camera_auto_connect = self.settings.value("camera_auto_connect", "false") == "true"
            if camera_auto_connect:
                self.logger.log("Auto-connecting camera...", "INFO")
                # Use a small delay to ensure UI is fully ready and video outputs are set
                QTimer.singleShot(1500, lambda: self.camera_controller.connect_camera(0))

        # Load plot formatting settings
        if hasattr(self, 'plot_style_preset'):
            style_preset = self.settings_model.get_value("plot_style_preset", "High Contrast")
            preset_items = ["Standard", "Solarized", "Dark", "High Contrast", "Pastel", "Colorful"]
            if style_preset in preset_items:
                self.plot_style_preset.setCurrentIndex(preset_items.index(style_preset))

        if hasattr(self, 'plot_line_width'):
            line_width = self.settings_model.get_int("plot_line_width", 2)
            self.plot_line_width.setValue(line_width)
            # Also update the cached value used by graph controller
            self.plot_line_width_value = line_width

        # Apply plot formatting with loaded settings
        if hasattr(self, 'apply_plot_formatting'):
            self.apply_plot_formatting()

        # Apply loaded settings
        if hasattr(self, 'show_log_cb'):
            self.show_log_cb.setChecked(show_log)
        if hasattr(self, 'log_text'):
            self.log_text.setVisible(show_log)
        # Log panel and theme settings have been removed

    def apply_settings(self):
        """Apply settings from UI to the application"""
        try:
            # Check if we have access to the data collection controller
            if hasattr(self, 'data_collection_controller'):
                # Apply global sampling rate from UI
                if hasattr(self, 'sampling_rate_spinbox'):
                    sampling_rate_hz = self.sampling_rate_spinbox.value()
                    self.data_collection_controller.set_sampling_rate(sampling_rate_hz)
                    
                    # Also update the UI sensor table timer interval
                    if hasattr(self, 'sensor_values_timer'):
                        update_interval = max(int(1000 / sampling_rate_hz), 100)
                        self.sensor_values_timer.setInterval(update_interval)
                        print(f"DEBUG MainWindow: Updated sensor table refresh interval to {update_interval}ms ({sampling_rate_hz}Hz)")
                    
                    # Save the rate in Hz to settings
                    self.settings.setValue("global_sampling_rate", sampling_rate_hz)
                    self.logger.log(f"Applied sampling rate: {sampling_rate_hz:.2f} Hz")
                
                # Update Arduino settings
                if hasattr(self, 'arduino_port_combo') and hasattr(self, 'arduino_baud_combo'):
                    arduino_port = self.arduino_port_combo.currentText()
                    arduino_baud = int(self.arduino_baud_combo.currentText())
                    
                    # Connect to Arduino with the global sampling rate
                    if arduino_port and arduino_port != "Select port":
                        self.data_collection_controller.connect_arduino(arduino_port, arduino_baud)
                
                # Update LabJack settings
                if hasattr(self, 'labjack_device_combo') and hasattr(self, 'labjack_connection_combo'):
                    labjack_device = self.labjack_device_combo.currentText()
                    labjack_connection = self.labjack_connection_combo.currentText()
                    
                    # Connect to LabJack with the global sampling rate
                    if labjack_device and labjack_device != "Select device":
                        self.data_collection_controller.connect_labjack(labjack_device, labjack_connection)
                
                # Update debug mode setting for logger
                if hasattr(self, 'debug_mode_cb'):
                    debug_mode = self.debug_mode_cb.isChecked()
                    self.settings.setValue("debug_mode", "true" if debug_mode else "false")
                    self.logger.log_level = "DEBUG" if debug_mode else "INFO"
                    self.logger.log(f"Debug mode {'enabled' if debug_mode else 'disabled'}")
                        
                # Show a status message
                self.statusBar().showMessage("Settings applied successfully", 3000)
                
        except Exception as e:
            # Log the error
            self.logger.log(f"Error applying settings: {str(e)}", "ERROR")
            # Show an error message in the status bar
            self.statusBar().showMessage(f"Error: {str(e)}", 5000)
    
    def update_graph_ui_elements(self):
        """Update graph UI elements based on selected graph type"""
        # Temporary implementation - will be moved to GraphController in the future
        if hasattr(self, 'graph_type_combo') and hasattr(self, 'secondary_sensor_label'):
            graph_type = self.graph_type_combo.currentText()
            
            # Show/hide multi-sensor list based on graph type
            if hasattr(self, 'multi_sensor_group'):
                self.multi_sensor_group.setVisible(graph_type == "Standard Time Series")
                # Select all additional sensors by default when Standard Time Series is selected
                if graph_type == "Standard Time Series" and hasattr(self, 'multi_sensor_list'):
                    # Select all items in the multi-sensor list
                    for i in range(self.multi_sensor_list.count()):
                        self.multi_sensor_list.item(i).setSelected(True)
            
            # Show/hide secondary sensor based on graph type
            secondary_visible = graph_type in ["Temperature Difference", "Correlation Analysis"]
            if hasattr(self, 'secondary_sensor_label'):
                self.secondary_sensor_label.setVisible(secondary_visible)
            if hasattr(self, 'graph_secondary_sensor'):
                self.graph_secondary_sensor.setVisible(secondary_visible)
            
            # Show/hide window size for moving average
            window_size_visible = graph_type == "Moving Average"
            if hasattr(self, 'window_size_label'):
                self.window_size_label.setVisible(window_size_visible)
            if hasattr(self, 'window_size_spinbox'):
                self.window_size_spinbox.setVisible(window_size_visible)
            
            # Show/hide histogram bins
            histogram_bins_visible = graph_type == "Histogram"
            if hasattr(self, 'graph_histogram_bins_label'):
                self.graph_histogram_bins_label.setVisible(histogram_bins_visible)
            if hasattr(self, 'histogram_bins_spinbox'):
                self.histogram_bins_spinbox.setVisible(histogram_bins_visible)
            
            # Box Plot specific: Hide Secondary Sensor, Window Size, Histogram Bins
            if graph_type == "Box Plot":
                if hasattr(self, 'secondary_sensor_label'): self.secondary_sensor_label.setVisible(False)
                if hasattr(self, 'graph_secondary_sensor'): self.graph_secondary_sensor.setVisible(False)
                if hasattr(self, 'window_size_label'): self.window_size_label.setVisible(False)
                if hasattr(self, 'window_size_spinbox'): self.window_size_spinbox.setVisible(False)
                if hasattr(self, 'graph_histogram_bins_label'): self.graph_histogram_bins_label.setVisible(False)
                if hasattr(self, 'histogram_bins_spinbox'): self.histogram_bins_spinbox.setVisible(False)
    
    def on_timespan_changed(self, graph_widget, is_main_graph=False):
        """Handle timespan change for graphs"""
        # Delegate to graph controller
        if is_main_graph:
            self.graph_controller.on_timespan_changed()
        else:
            self.graph_controller.on_dashboard_timespan_changed()
        
    # Camera mouse event handlers - temporary stubs that will delegate to camera controller
    def camera_mouse_press(self, event):
        """Handle mouse press events on the camera display"""
        # Forward to camera controller
        self.camera_controller.camera_mouse_press(event)
        
    def camera_mouse_release(self, event):
        """Handle mouse release events on the camera display"""
        # Forward to camera controller
        self.camera_controller.camera_mouse_release(event)
        
    def camera_mouse_move(self, event):
        """Handle mouse move events on the camera display"""
        # Forward to camera controller
        self.camera_controller.camera_mouse_move(event)

    def closeEvent(self, event: QCloseEvent):
        """Handle window close event"""
        # Cleanup and shutdown operations
        self.logger.log("Application shutting down...")
        
        # Save notes if the notes controller is available
        if hasattr(self, 'notes_controller'):
            self.notes_controller.save_note()
            self.logger.log("Saved notes before shutdown")
        
        # Save project data if the project controller is available
        if hasattr(self, 'project_controller'):
            # Save the current project and test series
            if self.project_controller.current_project:
                # Save to project metadata and project_state.json
                self.project_controller.save_project()
                self.project_controller.save_state_to_json()
                
                # Save current project and test series to config
                if hasattr(self, 'config'):
                    if self.project_controller.current_project:
                        self.config["last_project"] = self.project_controller.current_project
                    if self.project_controller.current_test_series:
                        self.config["last_test_series"] = self.project_controller.current_test_series
                    if self.project_controller.current_run:
                        self.config["last_run"] = self.project_controller.current_run
                
                self.logger.log(f"Saved project data for: {self.project_controller.current_project}")
        
        # Save base directory settings explicitly to ensure they're not lost
        if hasattr(self, 'project_base_dir'):
            base_dir = self.project_base_dir.text()
            if base_dir and os.path.exists(base_dir):
                # Save to both QSettings and config
                self.settings.setValue("base_directory", base_dir)
                self.settings.sync()  # Force settings to disk
                
                if hasattr(self, 'config'):
                    self.config["default_project_dir"] = base_dir
                    save_config(self.config)  # Direct call to save_config function
        
        # Disconnect audio and optical sensors before shutdown
        if hasattr(self, 'sensor_controller'):
            # Disconnect all audio sensors
            for sensor in self.sensor_controller.sensors:
                if hasattr(sensor, 'interface_type'):
                    if sensor.interface_type == 'AudioSensor':
                        try:
                            self.sensor_controller.disconnect_audio_sensor(sensor)
                        except Exception as e:
                            self.logger.log(f"Error disconnecting audio sensor {sensor.name}: {e}", "WARN")
                    elif sensor.interface_type == 'OpticalSensor':
                        try:
                            self.sensor_controller.disconnect_optical_sensor(sensor)
                        except Exception as e:
                            self.logger.log(f"Error disconnecting optical sensor {sensor.name}: {e}", "WARN")
        
        # Shutdown controllers
        if hasattr(self, 'data_collection_controller'):
            self.data_collection_controller.shutdown()
        
        if hasattr(self, 'camera_controller') and self.camera_controller:
            self.camera_controller.close_camera()
            
        # Save any unsaved settings
        self.save_settings()
        
        # Log application shutdown
        self.logger.log("Application shutdown complete")
        event.accept()
        
        self.save_virtual_sensors()
        
    def save_settings(self):
        """Save application settings"""
        if hasattr(self, 'settings_model'):
            self.settings_model.save_settings()
            self.logger.log("Settings saved")
        else:
            self.logger.log("Settings model not available to save settings", "WARN")
            
        # Save project state if project controller exists
        if hasattr(self, 'project_controller'):
            self.save_project_state()
            
        # Save configuration
        if hasattr(self, 'config'):
            self.save_config()

    # Camera-related methods
    def connect_camera(self):
        """Connect to a camera"""
        if not hasattr(self, 'camera_controller'):
            return
            
        # Forward to the controller
        if self.camera_connect_btn.text() == "Connect":
            # Check if replay is active with video - if so, stop replay video first
            if hasattr(self, 'replay_mode_enabled') and self.replay_mode_enabled:
                if hasattr(self, 'replay_active_video_path') and self.replay_active_video_path:
                    # Replay video is active - clear it before connecting camera
                    self._clear_replay_video()
                    if hasattr(self, 'logger'):
                        self.logger.log("Replay video stopped because camera is being connected", "INFO")
            
            # Get settings from the camera tab
            camera_id = self.camera_id.currentIndex()
            
            # Get resolution and framerate from settings instead of UI elements (which were removed)
            resolution = self.settings.value("camera/resolution", "1280x720")
            fps = int(self.settings.value("camera/fps", "30"))
            
            # Update the settings values
            self.settings.setValue("camera/default_camera", str(camera_id))
            # Resolution and framerate are already set via the settings popup
            
            # Connect to the camera
            self.camera_controller.toggle_camera()
            
            # Apply focus and exposure settings after connection
            if self.camera_controller.is_connected:
                self.apply_camera_focus_exposure()
        else:
            # Disconnect the camera using the force_disconnect method for reliability
            print("Using force_disconnect for more reliable camera disconnection")
            self.camera_controller.force_disconnect()
        
    def take_snapshot(self):
        """Take a camera snapshot"""
        self.camera_controller.take_snapshot()
        
    def toggle_recording(self):
        """Start or stop video recording"""
        self.camera_controller.toggle_recording()
        # Update dashboard button state immediately
        self.update_dashboard_header()
        
        # Add event to dashboard
        status = "STARTED" if self.recording else "STOPPED"
        level = "SUCCESS" if self.recording else "WARNING"
        self.add_dashboard_event(f"Run {status}", level)
        
    def add_overlay(self):
        """Add a new overlay to the camera feed"""
        self.camera_controller.add_overlay()
        
    def apply_overlay_settings(self):
        """Apply settings to the selected overlay"""
        self.camera_controller.apply_overlay_settings()
        
    def remove_overlay(self):
        """Remove the selected overlay"""
        self.camera_controller.remove_overlay()
        
    def choose_text_color(self):
        """Choose text color for overlay"""
        self.camera_controller.choose_text_color()
        
    def choose_bg_color(self):
        """Choose background color for overlay"""
        self.camera_controller.choose_bg_color()
        
    def apply_camera_settings(self):
        """Apply camera settings"""
        self.camera_controller.apply_camera_settings()
    
    # Sensor-related methods
    def add_sensor(self):
        """Show the add sensor dialog"""
        try:
            print("add_sensor method in main_window called")
            if hasattr(self, 'sensor_controller') and self.sensor_controller:
                print("Calling sensor_controller.add_sensor()")
                # Call the controller method
                success = self.sensor_controller.add_sensor()
                
                if success:
                    self.add_dashboard_event("New sensor added", "SUCCESS")
                
                # Removed incorrect fallback logic that caused double popups
            else:
                print("Error: sensor_controller not found")
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Error", "Sensor controller not available")
        except Exception as e:
            print(f"Error in add_sensor: {e}")
            import traceback
            traceback.print_exc()
    
    def edit_sensor(self):
        """Edit the selected sensor"""
        try:
            print("edit_sensor method in main_window called")
            if hasattr(self, 'sensor_controller') and self.sensor_controller:
                print("Calling sensor_controller.edit_sensor()")
                # Call the controller method
                self.sensor_controller.edit_sensor()
            else:
                print("Error: sensor_controller not found")
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Error", "Sensor controller not available")
        except Exception as e:
            print(f"Error in edit_sensor: {e}")
            import traceback
            traceback.print_exc()
    
    def remove_sensor(self):
        """Remove the selected sensor"""
        self.sensor_controller.remove_sensor()
        self.add_dashboard_event("Sensor removed", "WARNING")
    
    # Arduino-related methods
    def detect_arduino(self):
        """Detect available Arduino ports"""
        if not hasattr(self, 'data_collection_controller'):
            self.logger.log("Data collection controller not initialized", "ERROR")
            return
            
        # Get available Arduino ports
        available_ports = self.data_collection_controller.get_arduino_ports()
        
        if not available_ports:
            QMessageBox.information(self, "Arduino Detection", "No Arduino devices found.")
            return
            
        # Clear the port combobox
        self.arduino_port.clear()
        
        # Add available ports
        for port in available_ports:
            self.arduino_port.addItem(port)
            
        # Select the first port
        if len(available_ports) > 0:
            self.arduino_port.setCurrentText(available_ports[0])
            
        self.logger.log(f"Found {len(available_ports)} Arduino ports: {', '.join(available_ports)}")
        QMessageBox.information(self, "Arduino Detection", 
                               f"Found {len(available_ports)} Arduino port(s):\n{', '.join(available_ports)}")
        
    def connect_arduino(self):
        """Connect to Arduino"""
        if not hasattr(self, 'data_collection_controller'):
            self.logger.log("Data collection controller not initialized", "ERROR")
            return
            
        # Get Arduino settings from UI
        port = self.arduino_port.currentText()
        baud_rate = int(self.arduino_baud.currentText())
        poll_interval = self.arduino_poll_interval.value()
        
        # Check if already connected
        if 'arduino' in self.data_collection_controller.interfaces and \
           self.data_collection_controller.interfaces['arduino']['connected']:
            # Disconnect
            self.data_collection_controller.disconnect_arduino()
            self.update_arduino_connected_status(False)
            return
            
        # Connect to Arduino
        success = self.data_collection_controller.connect_arduino(port, baud_rate, poll_interval)
        
        # Update UI based on connection result
        if success:
            # Save settings
            self.settings.setValue("arduino_port", port)
            self.settings.setValue("arduino_baud", baud_rate)
            self.settings.setValue("arduino_poll_interval", poll_interval)
            self.update_arduino_connected_status(True)
        else:
            QMessageBox.warning(self, "Arduino Connection", 
                               "Failed to connect to Arduino. Check the port and settings.")
            self.update_arduino_connected_status(False)
    
    def test_arduino(self):
        """Test Arduino connection - Deprecated, kept for backwards compatibility"""
        pass
    
    def update_command_ui(self):
        """Update the command UI based on selected command type"""
        if not hasattr(self, 'arduino_command_type') or not hasattr(self, 'arduino_custom_command'):
            return
            
        # Get the selected command type
        command_type = self.arduino_command_type.currentText()
        
        # Show/hide custom command field based on selected type
        if command_type == "CUSTOM":
            self.arduino_custom_command_label.setVisible(True)
            self.arduino_custom_command.setVisible(True)
            
            # Disable normal fields
            self.arduino_device_id.setEnabled(False)
            self.arduino_command_value.setEnabled(False)
        else:
            self.arduino_custom_command_label.setVisible(False)
            self.arduino_custom_command.setVisible(False)
            
            # Enable normal fields
            self.arduino_device_id.setEnabled(True)
            self.arduino_command_value.setEnabled(True)
            
            # Set default values based on command type
            if command_type == "LED" or command_type == "RELAY":
                self.arduino_command_value.setText("ON")
            elif command_type == "MOTOR":
                self.arduino_command_value.setText("100")
            elif command_type == "SERVO":
                self.arduino_command_value.setText("90")
    
    def send_arduino_command(self):
        """Send command to Arduino from the UI"""
        if not hasattr(self, 'data_collection_controller'):
            self.logger.log("Data collection controller not initialized", "ERROR")
            return
            
        # Check if Arduino is connected
        if 'arduino' not in self.data_collection_controller.interfaces or \
           not self.data_collection_controller.interfaces['arduino']['connected']:
            QMessageBox.warning(self, "Arduino Command", "Arduino is not connected")
            return
            
        try:
            # Get the command parameters from the UI
            command_type = self.arduino_command_type.currentText()
            
            if command_type == "CUSTOM":
                # Send custom command directly
                custom_cmd = self.arduino_custom_command.text().strip()
                if not custom_cmd:
                    QMessageBox.warning(self, "Arduino Command", "Please enter a custom command")
                    return
                    
                # Parse the custom command
                cmd_parts = custom_cmd.split(':')
                if len(cmd_parts) == 1:
                    # Command only
                    success = self.data_collection_controller.send_arduino_command(cmd_parts[0])
                elif len(cmd_parts) == 2:
                    # Command and device/value
                    cmd = cmd_parts[0]
                    
                    # Check if there's a value
                    if '=' in cmd_parts[1]:
                        dev_val = cmd_parts[1].split('=')
                        device = dev_val[0]
                        value = dev_val[1].rstrip(';')
                        success = self.data_collection_controller.send_arduino_command(cmd, device, value)
                    else:
                        # Just command and device
                        device = cmd_parts[1].rstrip(';')
                        success = self.data_collection_controller.send_arduino_command(cmd, device)
                else:
                    QMessageBox.warning(self, "Arduino Command", "Invalid custom command format")
                    return
            else:
                # Use structured command
                device_id = self.arduino_device_id.text().strip()
                value = self.arduino_command_value.text().strip()
                
                # Send through the controller
                success = self.data_collection_controller.control_device(command_type, device_id, value)
                
            # Show result
            if success:
                self.statusBar().showMessage("Command sent successfully", 2000)
            else:
                QMessageBox.warning(self, "Arduino Command", "Failed to send command")
                
        except Exception as e:
            self.logger.log(f"Error sending Arduino command: {str(e)}", "ERROR")
            QMessageBox.warning(self, "Arduino Command", f"Error: {str(e)}")
    
    # LabJack-related methods
    def connect_labjack(self):
        """Connect to the LabJack T7 Pro device"""
        try:
            # Get the device connection parameter
            device_identifier = self.device_identifier_combobox.currentText().strip()
            
            # Connect to the LabJack device
            success = self.sensor_controller.connect_labjack(device_identifier)
            
            if not success:
                # The sensor_controller should have already logged/shown an error if it failed,
                # but we need to stop here so we don't update the UI to "connected" state
                return False
            
            # Update device info fields
            device_info = {}
            device_info["serial"] = self.sensor_controller.get_labjack_info("serial", "Unknown")
            device_info["name"] = self.sensor_controller.get_labjack_info("name", "Unknown")
            device_info["firmware"] = self.sensor_controller.get_labjack_info("firmware", "Unknown")
            device_info["hardware"] = self.sensor_controller.get_labjack_info("hardware", "Unknown")
            
            # Force update status in all UI places
            self.sensor_controller.force_update_labjack_status()
            
            # Update the button and connection status UI
            self.labjack_connect_button.setText("Disconnect")
            self.labjack_connect_button.setStyleSheet("color: green; font-weight: bold;")
            self.update_device_connection_status_ui('labjack', True)
            
            # Show a message to the user
            self.show_status_message(f"LabJack {device_info['name']} connected successfully", "success")
            
            # Refresh the UI to ensure everything is updated
            QApplication.processEvents()
            
            return True
        except Exception as e:
            self.show_status_message(f"Failed to connect to LabJack: {str(e)}", "error")
            return False
    
    def test_labjack(self):
        """Test LabJack connection"""
        self.sensor_controller.test_labjack()
    
    # Control Run related methods
    def populate_control_run_selector(self):
        """Populate the control run selector with available runs"""
        if not hasattr(self, 'control_run_selector') or not hasattr(self, 'control_run_controller'):
            return
            
        # Save current selection
        current_text = self.control_run_selector.currentText()
        
        # Clear and repopulate
        self.control_run_selector.clear()
        self.control_run_selector.addItem("None")
        
        # Get available runs
        available_runs = self.control_run_controller.get_available_runs()
        
        for run_path, run_display_name in available_runs:
            self.control_run_selector.addItem(run_display_name, run_path)
            
        # Restore selection if it still exists
        index = self.control_run_selector.findText(current_text)
        if index >= 0:
            self.control_run_selector.setCurrentIndex(index)
        
        if hasattr(self, 'logger'):
            self.logger.log(f"Populated control run selector with {len(available_runs)} runs", "INFO")
    
    def on_control_run_selected(self, index):
        """Handle control run selection change"""
        if not hasattr(self, 'control_run_selector') or not hasattr(self, 'control_run_controller'):
            return
            
        if index == 0:  # "None" selected
            self.control_run_controller.clear_control_run()
        else:
            run_path = self.control_run_selector.currentData()
            run_name = self.control_run_selector.currentText()
            if run_path:
                self.control_run_controller.set_control_run(run_path, run_name)
    
    def on_control_run_time_offset_changed(self, value):
        """Handle time offset change for control run"""
        if not hasattr(self, 'control_run_controller'):
            return
            
        self.control_run_controller.set_time_offset(value)
    
    def on_control_run_changed_update(self):
        """Handle control run change - update sensor dropdowns and graph"""
        # Update sensor dropdowns to include/exclude control run sensors
        if hasattr(self, 'sensor_controller'):
            self.sensor_controller.update_graph_sensor_dropdowns()
        
        # Update graph
        self.update_graph()
    
    def on_show_control_run_changed(self, state):
        """Handle show control run checkbox change"""
        # Update sensor dropdowns to add/remove control sensors based on checkbox state
        if hasattr(self, 'sensor_controller'):
            self.sensor_controller.update_graph_sensor_dropdowns()
        
        # Update graph to show/hide control run data
        self.update_graph()

    def on_show_automation_markers_changed(self, state):
        """Handle toggling automation event markers on graphs."""
        if hasattr(self, 'logger'):
            self.logger.debug(f"UI: Show automation markers changed -> {state}")
        try:
            print(f"[AUTOMATION MARKERS] UI checkbox state={state}")
        except Exception:
            pass
        enabled = state != Qt.CheckState.Unchecked
        # PyQt6 passes int; fallback to truthy check in case enums behave differently
        if isinstance(state, int):
            enabled = state != 0
        if hasattr(self, 'graph_controller'):
            self.graph_controller.set_show_automation_markers(enabled)
        # Force refresh so markers update immediately after toggling
        if hasattr(self, 'update_graph'):
            self.update_graph()
        if hasattr(self, 'update_dashboard_graph'):
            self.update_dashboard_graph()
    
    # Graph-related methods
    def update_graph(self):
        """Update the main analysis graph based on UI selections."""
        if hasattr(self, 'logger'):
            self.logger.debug("Gathering parameters to update main graph")

        if not hasattr(self, 'graph_controller') or not hasattr(self, 'graph_widget') or not hasattr(self, 'sensor_controller'):
            if hasattr(self, 'logger'):
                self.logger.error("Graph controller, graph widget, or sensor controller not initialized.")
            return
            
        # Ensure UI elements exist before accessing them
        required_attrs = [
            'graph_type_combo', 'graph_primary_sensor', 'graph_secondary_sensor',
            'graph_timespan', 'multi_sensor_list', 'window_size_spinbox',
            'histogram_bins_spinbox'
        ]
        for attr in required_attrs:
            if not hasattr(self, attr):
                if hasattr(self, 'logger'):
                    self.logger.error(f"Graph UI element '{attr}' not found in main window.")
                return

        # Get parameters from UI
        graph_type = self.graph_type_combo.currentText()
        # Get the HISTORICAL KEY from the selected item's userData
        primary_sensor_key = self.graph_primary_sensor.currentData()
        secondary_sensor_key = self.graph_secondary_sensor.currentData() if self.graph_secondary_sensor.isVisible() else None
        timespan = self.graph_timespan.currentText()
        
        # Get list of selected additional sensor HISTORICAL KEYS from multi_sensor_list userData
        multi_sensor_keys = []
        if self.multi_sensor_list.isVisible():
            selected_items = self.multi_sensor_list.selectedItems()
            multi_sensor_keys = [item.data(Qt.ItemDataRole.UserRole) for item in selected_items if item.data(Qt.ItemDataRole.UserRole) is not None]
        
        # Check if we need to load control run data
        # Load if: checkbox is checked OR any selected sensor has _ctrl suffix
        show_control_run = False
        control_run_data = None
        
        # Collect all selected sensor keys
        all_selected_keys = [primary_sensor_key, secondary_sensor_key] + multi_sensor_keys
        all_selected_keys = [k for k in all_selected_keys if k is not None]
        
        # Check if any selected sensor is a control sensor (ends with _ctrl)
        has_control_sensors = any(key.endswith('_ctrl') for key in all_selected_keys)
        
        # Load control run data if checkbox is checked OR control sensors are selected
        if hasattr(self, 'show_control_run_checkbox') and self.show_control_run_checkbox.isChecked():
            show_control_run = True
            
        if show_control_run or has_control_sensors:
            if hasattr(self, 'logger'):
                if show_control_run:
                    self.logger.debug("Control run checkbox is checked, loading control run data")
                if has_control_sensors:
                    self.logger.debug(f"Control sensors selected, loading control run data")
            
            # Get control run data from control run controller
            if hasattr(self, 'control_run_controller'):
                try:
                    control_run_data = self.control_run_controller.load_control_run_data()
                    if hasattr(self, 'logger'):
                        self.logger.debug(f"Retrieved control run data for {len(control_run_data)} sensors with offset {self.control_run_controller.time_offset}s")
                except Exception as e:
                    if hasattr(self, 'logger'):
                        self.logger.error(f"Error retrieving control run data: {e}")
                    control_run_data = None

        # Get specific parameters based on graph type
        window_size = self.window_size_spinbox.value() if self.window_size_spinbox.isVisible() else None
        histogram_bins = self.histogram_bins_spinbox.value() if self.histogram_bins_spinbox.isVisible() else None
        
        # Log the keys being sent
        if hasattr(self, 'logger'):
             self.logger.debug(f"Calling update_specific_graph with: type={graph_type}, primary_key={primary_sensor_key}, secondary_key={secondary_sensor_key}, multi_keys={multi_sensor_keys}, timespan={timespan}, show_control_run={show_control_run}")

        # Delegate plotting to the GraphController using historical keys
        self.graph_controller.update_specific_graph(
            graph_widget=self.graph_widget,
            primary_sensor_key=primary_sensor_key, # Pass key
            secondary_sensor_key=secondary_sensor_key, # Pass key
            timespan=timespan,
            graph_type=graph_type,
            multi_sensor_keys=multi_sensor_keys, # Pass keys
            window_size=window_size,
            histogram_bins=histogram_bins,
            is_main_graph=True, # Indicate this is for the main analysis graph
            show_control_run=show_control_run,
            control_run_data=control_run_data
        )

    def update_dashboard_graph(self):
        """Update the dashboard graph"""
        self.graph_controller.update_dashboard_graph()
        
    def handle_new_sensor_data(self, data):
        """Update sensor values with data received from hardware interfaces"""
        try:
            if not data or not hasattr(self, 'sensor_controller'):
                return
                
            # Forward to sensor controller to update sensor data
            self.sensor_controller.update_sensor_data(data)
            
            # Also update the automation context if we have both controllers
            if hasattr(self, 'sensor_controller') and hasattr(self, 'automation_controller'):
                self.sensor_controller.update_automation_context()
        except Exception as e:
            # Don't log every error to avoid spam, but print it
            print(f"Error in handle_new_sensor_data: {e}")

    def apply_plot_formatting(self):
        """Apply formatting to plots"""
        self.graph_controller.apply_plot_formatting()

    # Motion detection methods
    def handle_motion_detection_state(self, state):
        """Handle motion detection state changes"""
        # Store motion detection state
        self.motion_detection_enabled = state
        
        # If camera controller exists, notify it
        if hasattr(self, 'camera_controller') and self.camera_controller is not None:
            self.camera_controller.handle_motion_detection_state(state)
        
        # Enable/disable motion detection controls (do this regardless of controller)
        if hasattr(self, 'motion_detection_sensitivity'):
            self.motion_detection_sensitivity.setEnabled(state)
            
        if hasattr(self, 'motion_detection_min_area'):
            self.motion_detection_min_area.setEnabled(state)

    # NDI methods
    def init_ndi(self):
        """Initialize NDI streaming"""
        self.camera_controller.init_ndi()
        
    def browse_ffmpeg_path(self):
        """Open file dialog to browse for FFmpeg executable"""
        file_filter = "Executable files (*.exe);;All files (*)" if sys.platform == "win32" else "All files (*)"
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select FFmpeg Executable", "", file_filter
        )
        
        if file_path:
            # Update the text field with the selected path
            self.ffmpeg_binary_path.setText(file_path)
            
            # Save to settings
            self.settings.setValue("ffmpeg_binary", file_path)
            
            # Log the change
            self.logger.log(f"FFmpeg path set to: {file_path}")
            
            # Show a confirmation message
            QMessageBox.information(
                self, 
                "FFmpeg Path Updated", 
                f"FFmpeg path set to:\n{file_path}\n\nThis will be used for all future video encoding."
            ) 

    def resizeEvent(self, event):
        """Handle window resize events"""
        super().resizeEvent(event)
        # Print window size after resize
        size = self.size()
        print(f"Window resized to: {size.width()}x{size.height()}")
        # Update dashboard snapshot image scaling if currently visible
        if hasattr(self, 'stacked_widget') and hasattr(self, 'dashboard_tab'):
            if self.stacked_widget.currentWidget() == self.dashboard_tab:
                # Use a small delay or timer if performance is an issue, 
                # but for one image it should be fine to do directly
                self._update_snapshot_display()

    def eventFilter(self, source, event):
        """Handle specific widget events (like resize of the snapshot label)"""
        if event.type() == QEvent.Type.Resize:
            if hasattr(self, 'dashboard_snapshot_label') and source == self.dashboard_snapshot_label:
                # Update the snapshot scaling when its container label resizes
                # (e.g. via splitter movement or window resize)
                self._update_snapshot_display()
            elif hasattr(self, 'metrics_container') and source == self.metrics_container:
                # Update the metrics grid layout (1 or 2 columns) when its container resizes
                self.rearrange_dashboard_metrics()
        
        return super().eventFilter(source, event)
        
    # Add methods for JSON persistence
    def save_project_state(self):
        """Saves the current project/test/run details to project_state.json in the project dir."""
        # Delegate to project controller
        if hasattr(self, 'project_controller'):
            self.project_controller.save_state_to_json()
        else:
            self.logger.log("Project controller not available to save state.", "WARN")

    def load_project_state(self, project_path):
        """Loads project/test/run details from project_state.json for the given project path."""
        # Delegate to project controller
        if hasattr(self, 'project_controller'):
            self.project_controller.load_state_from_json(project_path)
            self.update_status_indicators() # Update status after loading
            
            # Add dashboard event
            proj_name = os.path.basename(project_path)
            self.add_dashboard_event(f"Project '{proj_name}' loaded", "SUCCESS")
        else:
            self.logger.log("Project controller not available to load state.", "WARN")
        
    def save_config(self):
        """Save the application configuration"""
        try:
            # Save to config.json
            save_config(self.config)
            
            # Ensure that the base directory is correctly saved in both storage locations
            if hasattr(self, 'project_base_dir'):
                base_dir = self.project_base_dir.text()
                if base_dir and os.path.exists(base_dir):
                    # Save to QSettings
                    self.settings.setValue("base_directory", base_dir)
                    self.settings.sync()  # Force sync to disk
                    
                    # Make sure config has it too
                    self.config["default_project_dir"] = base_dir
                    
                    # Log the save
                    self.logger.log(f"Saved base directory to config: {base_dir}")
    
        except Exception as e:
            self.logger.log(f"Error saving config: {str(e)}", "ERROR")
            import traceback
            traceback.print_exc()
        
    def update_project_group_box_colors(self):
        """Update the group box border colors based on form completion
        - Orange (warning): Default/Incomplete
        - Green (success): Complete with valid data
        """
        # Get relevant data
        base_dir = self.project_base_dir.text().strip()
        project_name = self.project_selector.currentText().strip()
        series_name = self.test_series_selector.currentText().strip()
        run_description = self.run_description.toPlainText().strip()
        run_testers = self.run_testers.text().strip()
        
        # GroupBox styles using theme system - use WARNING (orange) for incomplete
        incomplete_style = GroupBoxStyles.with_status("warning")
        complete_style = GroupBoxStyles.with_status("success")
        
        # Check project group box completion - only if the attribute exists
        if hasattr(self, 'project_group'):
            if base_dir and os.path.exists(base_dir) and project_name:
                self.project_group.setStyleSheet(complete_style)
            else:
                self.project_group.setStyleSheet(incomplete_style)
            
        # Check test series group box completion - only if the attribute exists
        if hasattr(self, 'test_series_group'):
            if series_name:
                self.test_series_group.setStyleSheet(complete_style)
            else:
                self.test_series_group.setStyleSheet(incomplete_style)
            
        # Check run group box completion - only if the attribute exists
        if hasattr(self, 'run_group'):
            # Show green only if both description and testers are filled
            if run_description and run_testers:
                self.run_group.setStyleSheet(complete_style)
            else:
                self.run_group.setStyleSheet(incomplete_style)

    def init_controllers(self):
        """Initialize all application controllers"""
        self.logger.log("Initializing controllers...", "INFO")
        
        # Initialize Project Controller
        self.project_controller = ProjectController(self)
        
        # Initialize Settings Model (already done in __init__, but ensure it's accessible)
        # self.settings_model = SettingsModel(self.settings)
        
        # Initialize Sensor Controller
        self.sensor_controller = SensorController(self, self.settings_model)

        # Initialize Camera Controller
        # Make sure to pass the settings model
        self.camera_controller = CameraController(self, self.settings_model, self.project_controller) # Pass project_controller

        # Initialize Graph Controller
        self.graph_controller = GraphController(self, self.sensor_controller, self.settings_model) # Pass settings model

        # Initialize Automation Controller
        self.automation_controller = AutomationController(self, self.config)

        # Initialize Data Collection Controller
        self.data_collection_controller = DataCollectionController(self)

        # Initialize Export Controller
        self.export_controller = ExportController(self, self.settings_model)
        
        # Initialize Notes Controller
        self.notes_controller = NotesController(self)
        
        # Initialize Control Run Controller
        self.control_run_controller = ControlRunController(self)
        self.logger.log("Control run controller initialized", "INFO")

        # Initialize Stream Controller
        try:
            from app.controllers.stream_controller import StreamController
            self.stream_controller = StreamController(self)
            self.logger.log("Stream controller initialized", "INFO")
        except ImportError as e:
            self.logger.log(f"Failed to initialize stream controller: {e}", "WARNING")
            self.stream_controller = None

        # Initialize Remote Control Controller
        try:
            from app.controllers.remote_control_controller import RemoteControlController
            self.remote_control_controller = RemoteControlController(self)
            self.logger.log("Remote control controller initialized", "INFO")
        except ImportError as e:
            self.logger.log(f"Failed to initialize remote control controller: {e}", "WARNING")
            self.remote_control_controller = None

        # Initialize Data Flow Controller
        self.data_flow_controller = DataFlowController(self)
        # Connect data flow widget to controller
        if hasattr(self, 'data_flow_widget'):
            self.data_flow_widget.set_controller(self.data_flow_controller)
        self.logger.log("Data flow controller initialized", "INFO")

        # Initialize Data Replay Controller (offline playback)
        self.data_replay_controller = DataReplayController(self)
        self.logger.log("Data replay controller initialized", "INFO")

        # Initialize replay UI defaults
        self._init_replay_ui()

        # Initialize the data collection controller to set up timers
        # We pass load_historical=False because we will perform a comprehensive startup load
        self.data_collection_controller.initialize(load_historical=False)
        
        # Setup the sensor tab UI components
        self.setup_sensor_tab()

        # Perform startup load for project and last run with a short delay
        # to ensure UI is fully ready and signals are connected.
        if hasattr(self, 'project_controller'):
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(500, self.project_controller.startup_load)
            self.logger.log("Scheduled project controller startup load", "INFO")

        # Log initialization
        self.logger.log("Controllers initialized successfully", "INFO")
    
    @property
    def is_replay_mode(self):
        """Return True if we are viewing a completed run (not currently acquiring data)"""
        return (hasattr(self, 'project_controller') and 
                self.project_controller.current_run is not None and 
                not self.running)

    def connect_controller_signals(self):
        """Connect controller-specific signals"""
        # Connect data collection signals if available
        if hasattr(self, 'data_collection_controller'):
            # Connect data received signal to update sensor values
            self.data_collection_controller.data_received_signal.connect(
                self.handle_new_sensor_data)
            
            # Connect status update signal to logger
            self.data_collection_controller.status_update_signal.connect(
                lambda msg, level: self.logger.log(msg, level))
            
            # Connect combined data signal to graph controller for synchronized updates
            if hasattr(self, 'graph_controller'):
                # Disconnect the old signal if it was connected
                try:
                    self.data_collection_controller.data_received_signal.disconnect(
                        self.graph_controller.plot_new_data)
                except:
                    # If it wasn't connected, just proceed
                    pass
                    
                # Connect the combined data signal for synchronized graph updates
                self.data_collection_controller.combined_data_signal.connect(
                    self.graph_controller.plot_new_data)
                self.data_collection_controller.combined_data_signal.connect(
                    self.update_dashboard_metrics)
                self.data_collection_controller.combined_data_signal.connect(
                    self.sensor_controller.update_from_combined_data)
                self.logger.log("Connected combined data signal to graph controller, dashboard metrics, and sensor controller", "INFO")
        
        # Connect sensor controller signals
        if hasattr(self, 'sensor_controller'):
            # Connect status change signal
            self.sensor_controller.status_changed.connect(self.update_status_indicators)
            
            # DO NOT connect buttons directly here - this creates conflicts
            # Buttons are connected properly in setup_sensor_tab_signals() 
            # These direct connections can cause conflicts
            # Instead, setup_sensor_tab_signals connects the buttons to main window methods
            # which then call the controller methods

        # Connect automation controller signals
        if hasattr(self, 'automation_controller'):
            # Connect status change signal
            self.automation_controller.status_changed.connect(self.update_status_indicators)
            # Connect UI buttons to controller methods


    def handle_interface_status(self, interface_type, is_connected):
        """Handle interface status updates
        
        Args:
            interface_type (str): Type of interface ('arduino', 'labjack', 'other')
            is_connected (bool): Whether the interface is connected
        """
        # Debug
        print(f"DEBUG HW STATUS: {interface_type} is_connected={is_connected}")
        
        # Update device connection status in UI
        # Guard against recursion: update_device_connection_status_ui() may (optionally) call back into
        # controller disconnect methods when the UI requests a disconnect. When the controller itself
        # emits a status update, we must not call disconnect again.
        self._in_controller_status_update = True
        try:
            self.update_device_connection_status_ui(interface_type, is_connected)
        finally:
            self._in_controller_status_update = False

    def update_device_connection_status_ui(self, device_type, is_connected):
        """Update the connection status UI indicators for a specific device type
        
        Args:
            device_type (str): Type of device ('arduino', 'labjack', 'other', etc.)
            is_connected (bool): Whether the device is connected
        """
        print(f"update_device_connection_status_ui: type={device_type}, connected={is_connected}")
        
        # If this is a disconnect request from a dialog/UI, make sure the controller actually disconnects
        # This prevents auto-reconnect loops if the interface instance was disconnected but the thread is still running
        if (not is_connected
            and hasattr(self, 'data_collection_controller')
            and not getattr(self, '_in_controller_status_update', False)):
            dcc = self.data_collection_controller
            if device_type.lower() == 'arduino' and dcc.arduino_connected:
                print(f"DEBUG: Dialog requested disconnect for {device_type}, calling controller.disconnect_arduino()")
                dcc.disconnect_arduino()
            elif device_type.lower() == 'labjack' and dcc.labjack_connected:
                print(f"DEBUG: Dialog requested disconnect for {device_type}, calling controller.disconnect_labjack()")
                dcc.disconnect_labjack()
            elif device_type.lower() == 'mqtt' and 'mqtt' in dcc.interfaces and dcc.interfaces['mqtt']['connected']:
                print(f"DEBUG: Dialog requested disconnect for {device_type}, calling controller.disconnect_mqtt()")
                dcc.disconnect_mqtt()
            elif (device_type.lower() == 'other' or device_type.lower() == 'serial') and 'other_serial' in dcc.interfaces and dcc.interfaces['other_serial']['connected']:
                print(f"DEBUG: Dialog requested disconnect for {device_type}, calling controller.disconnect_other_serial_all()")
                dcc.disconnect_other_serial_all()
            elif device_type in dcc.interfaces and dcc.interfaces[device_type].get('connected', False):
                # Generic plugin interface
                print(f"DEBUG: Dialog requested disconnect for plugin {device_type}, calling controller.disconnect_plugin_interface()")
                dcc.disconnect_plugin_interface(device_type)

        # Add dashboard event
        status_str = "connected" if is_connected else "disconnected"
        level = "SUCCESS" if is_connected else "ERROR"
        self.add_dashboard_event(f"Hardware {device_type} {status_str}", level)

        # Update the corresponding method based on device type
        if device_type.lower() == 'arduino':
            self.update_arduino_connected_status(is_connected)
        elif device_type.lower() == 'labjack':
            self.update_labjack_connected_status(is_connected)
        elif device_type.lower() == 'other':
            # Directly call our specialized other sensors method
            self.update_other_connected_status(is_connected)
        elif device_type.lower() == 'mqtt':
            self.update_mqtt_connected_status(is_connected)
            # Subscribe to topics when connected
            if is_connected and hasattr(self, 'sensor_controller'):
                self.sensor_controller.subscribe_all_mqtt_topics()
        else:
            # Generic handler for new plugin interfaces
            self.update_generic_interface_status(device_type, is_connected)
            
        # Also update the interfaces dictionary directly to ensure consistency
        if hasattr(self, 'data_collection_controller') and hasattr(self.data_collection_controller, 'interfaces'):
            if device_type.lower() == 'arduino' and 'arduino' in self.data_collection_controller.interfaces:
                if isinstance(self.data_collection_controller.interfaces['arduino'], dict):
                    self.data_collection_controller.interfaces['arduino']['connected'] = is_connected
                    print(f"DEBUG: Directly updated 'arduino' connected status to {is_connected} in interfaces dict")
            elif device_type.lower() == 'labjack' and 'labjack' in self.data_collection_controller.interfaces:
                if isinstance(self.data_collection_controller.interfaces['labjack'], dict):
                    self.data_collection_controller.interfaces['labjack']['connected'] = is_connected
                    print(f"DEBUG: Directly updated 'labjack' connected status to {is_connected} in interfaces dict")
            elif device_type.lower() == 'other' and 'other_serial' in self.data_collection_controller.interfaces:
                if isinstance(self.data_collection_controller.interfaces['other_serial'], dict):
                    self.data_collection_controller.interfaces['other_serial']['connected'] = is_connected
                    print(f"DEBUG: Directly updated 'other_serial' connected status to {is_connected} in interfaces dict")
                    
        # If we have an "other" device, also update the data collection controller's state directly
        if device_type.lower() == 'other' and hasattr(self, 'data_collection_controller'):
            if 'other_serial' not in self.data_collection_controller.interfaces:
                self.data_collection_controller.interfaces['other_serial'] = {'connected': is_connected, 'type': 'other_serial'}
                print(f"DEBUG: Created 'other_serial' entry with connected={is_connected} in interfaces dict")
        
        # Force application to process events immediately
        from PyQt6.QtCore import QCoreApplication
        QCoreApplication.processEvents()

    def init_device_status(self):
        """Initialize device status indicators in the UI"""
        try:
            # Arduino status
            self.arduino_status_indicator = QLabel()
            self.arduino_status_indicator.setFixedSize(16, 16)
            self.arduino_status_indicator.setStyleSheet("background-color: #F44336; border-radius: 8px;")
            self.arduino_status_indicator.setToolTip("Arduino Connection Status")
            
            self.arduino_status_label = QLabel("Disconnected")
            self.arduino_status_label.setStyleSheet("color: #F44336;")
            
            # LabJack status
            self.labjack_status_indicator = QLabel()
            self.labjack_status_indicator.setFixedSize(16, 16)
            self.labjack_status_indicator.setStyleSheet("background-color: #F44336; border-radius: 8px;")
            self.labjack_status_indicator.setToolTip("LabJack Connection Status")
            
            self.labjack_status_label = QLabel("Disconnected")
            self.labjack_status_label.setStyleSheet("color: #F44336;")
            
            # Serial Devices status
            self.other_status_indicator = QLabel()
            self.other_status_indicator.setFixedSize(16, 16)
            self.other_status_indicator.setStyleSheet("background-color: #F44336; border-radius: 8px;")
            self.other_status_indicator.setToolTip("Serial Devices Connection Status")
            
            self.other_status_label = QLabel("Disconnected")
            self.other_status_label.setStyleSheet("color: #F44336;")
            
            print("Device status indicators successfully initialized")
        except Exception as e:
            print(f"Error initializing device status indicators: {e}")

    def _device_card_style(self, is_connected: bool) -> str:
        """Return the frame style for device cards based on connection state."""
        return CardStyles.device_card(is_connected)

    def update_arduino_connected_status(self, is_connected):
        """Update the Arduino connection status display
        
        Args:
            is_connected (bool): Whether the Arduino is connected
        """
        print(f"Direct Arduino status update: is_connected={is_connected}")
        
        # Track connection status
        self.interface_connections['arduino'] = is_connected
        
        # First try to update the button if it exists
        if hasattr(self, 'arduino_connect_btn'):
            self.arduino_connect_btn.setText("Disconnect" if is_connected else "Connect")
            
            # Apply appropriate button style using theme system
            if is_connected:
                self.arduino_connect_btn.setStyleSheet(ConnectionStyles.disconnected())
            else:
                self.arduino_connect_btn.setStyleSheet(ConnectionStyles.connected())
            
            self.arduino_connect_btn.repaint()
        
        # Set the text and color directly on the arduino_status label if it exists
        if hasattr(self, 'arduino_status'):
            status_text = "Connected" if is_connected else "Not connected"
            status_color = COLORS.SUCCESS_TEXT if is_connected else COLORS.TEXT_MUTED
            print(f"Directly updating arduino_status label to '{status_text}' with color '{status_color}'")
            self.arduino_status.setText(status_text)
            self.arduino_status.setStyleSheet(f"color: {status_color}; font-size: 9px; background-color: transparent; border: none;")
            self.arduino_status.repaint()
            # Update the surrounding device card to reflect connection state
            arduino_container = self.arduino_status.parent()
            if arduino_container and hasattr(arduino_container, 'setStyleSheet'):
                arduino_container.setStyleSheet(self._device_card_style(is_connected))
                arduino_container.update()
        
        # Log the status change
        status_str = "connected" if is_connected else "disconnected"
        if hasattr(self, 'logger'):
            self.logger.log(f"Arduino {status_str}", "INFO")

    def update_mqtt_connected_status(self, is_connected):
        """Update the MQTT connection status display
        
        Args:
            is_connected (bool): Whether MQTT is connected
        """
        print(f"Direct MQTT status update: is_connected={is_connected}")
        
        # Track connection status
        self.interface_connections['mqtt'] = is_connected
        
        # Set the text and color directly on the mqtt_status label if it exists
        if hasattr(self, 'mqtt_status'):
            status_text = "Connected" if is_connected else "Not connected"
            status_color = "green" if is_connected else "grey"
            print(f"Directly updating mqtt_status label to '{status_text}' with color '{status_color}'")
            self.mqtt_status.setText(status_text)
            self.mqtt_status.setStyleSheet(f"color: {status_color}; font-size: 9px; background-color: transparent; border: none;")
            self.mqtt_status.repaint()
            # Update the surrounding device card to reflect connection state
            mqtt_container = self.mqtt_status.parent()
            if mqtt_container and hasattr(mqtt_container, 'setStyleSheet'):
                mqtt_container.setStyleSheet(self._device_card_style(is_connected))
                mqtt_container.update()
        
        # Force application to process events immediately
        from PyQt6.QtCore import QCoreApplication
        QCoreApplication.processEvents()
        
        # Log the status change
        status_str = "connected" if is_connected else "disconnected"
        if hasattr(self, 'logger'):
            self.logger.log(f"MQTT {status_str}", "INFO")

    def update_generic_interface_status(self, device_type, is_connected):
        """Generic handler to update connection status for any registered interface."""
        from app.ui.theme import COLORS, CardStyles
        # print(f"DEBUG: update_generic_interface_status for '{device_type}' connected={is_connected}")
        
        # Track connection status
        self.interface_connections[device_type.lower()] = is_connected
        
        # Find the status label from our registry in ui_setup
        if hasattr(self, 'interface_status_labels'):
            # Try exact match first
            label = self.interface_status_labels.get(device_type)
            
            # If not found, try case-insensitive or normalized match
            if not label:
                for key, val in self.interface_status_labels.items():
                    if key.lower() == device_type.lower():
                        label = val
                        break
            
            if label:
                status_text = "Connected" if is_connected else "Not connected"
                
                # Check if it's a plugin card or outbound card
                container = label.parent()
                is_plugin = container.property("is_plugin") if container else False
                is_outbound = container.property("is_outbound") if container else False
                
                if is_connected:
                    status_color = COLORS.SUCCESS_TEXT
                    if is_outbound: status_text = "Active"
                elif is_outbound:
                    status_color = "#A855F7" # Purple
                    status_text = "Ready"
                elif is_plugin:
                    status_color = COLORS.INFO
                else:
                    status_color = COLORS.TEXT_MUTED
                
                label.setText(status_text)
                label.setStyleSheet(f"color: {status_color}; font-size: 9px; background-color: transparent; border: none;")
                label.repaint()
                
                # Update the surrounding device card background
                if container and hasattr(container, 'setStyleSheet'):
                    if is_outbound:
                        container.setStyleSheet(CardStyles.outbound_plugin_card(is_connected))
                    elif is_plugin:
                        container.setStyleSheet(CardStyles.plugin_card(is_connected))
                    else:
                        container.setStyleSheet(CardStyles.device_card(is_connected))
                    container.update()
            else:
                print(f"DEBUG: '{device_type}' not found in interface_status_labels (keys: {list(self.interface_status_labels.keys())})")

    def show_arduino_settings_popup(self):
        """Show Arduino settings in a popup dialog (Harmonized)"""
        InterfaceRegistry.initialize()
        interface_class = InterfaceRegistry.get_interface_class("Arduino")
        if not interface_class:
            QMessageBox.critical(self, "Error", "Arduino interface not found in registry.")
            return
            
        # Get current config
        config = {
            "port": self.settings.value("arduino_port", "COM3"),
            "baud_rate": str(self.settings.value("arduino_baud", "9600")),
            "mode": self.settings.value("arduino_mode", "polled"),
            "poll_interval": float(self.settings.value("arduino_poll_interval", "1.0")),
            "auto_connect": self.settings.value("arduino_auto_connect", "false") == "true",
            "enabled": self.settings.value("arduino_enabled", "true") == "true"
        }
        
        instance = None
        if hasattr(self, 'data_collection_controller'):
            instance = self.data_collection_controller.arduino_thread
            
        dialog = InterfaceConfigDialog(self, interface_class=interface_class, interface_instance=instance, config=config)
        dialog.connection_status_changed.connect(self.update_device_connection_status_ui)
        
        # Add the existing help text to the dialog if it exists in the interface
        if not hasattr(interface_class, "HELP_TEXT"):
            interface_class.HELP_TEXT = """
            <h3>Arduino Interface</h3>
            <p>Handles communication with Arduino devices over Serial.</p>
            <p><b>How to use:</b></p>
            <ol>
                <li>Upload the provided Arduino example code to your board.</li>
                <li>Connect via USB and select the correct COM port and baud rate.</li>
                <li>Data format: <code>SensorName1:value;SensorName2:value;...</code></li>
            </ol>
            """
            
        if dialog.exec():
            new_config = dialog.get_config()
            
            # Save settings
            self.settings.setValue("arduino_port", new_config.get("port"))
            self.settings.setValue("arduino_baud", new_config.get("baud_rate"))
            self.settings.setValue("arduino_mode", new_config.get("mode"))
            self.settings.setValue("arduino_poll_interval", str(new_config.get("poll_interval")))
            self.settings.setValue("arduino_auto_connect", "true" if new_config.get("auto_connect") else "false")
            self.settings.setValue("arduino_enabled", "true" if new_config.get("enabled") else "false")
            
            # Update instance if it exists
            if instance:
                instance.port = new_config.get("port")
                try:
                    instance.baud_rate = int(new_config.get("baud_rate"))
                except (ValueError, TypeError):
                    pass
                instance.mode = new_config.get("mode")
                try:
                    instance.poll_interval = float(new_config.get("poll_interval"))
                except (ValueError, TypeError):
                    pass
            
            # Update UI elements in main window if they exist
            if hasattr(self, 'arduino_port'):
                self.arduino_port.setCurrentText(new_config.get("port"))
            if hasattr(self, 'arduino_baud'):
                self.arduino_baud.setCurrentText(new_config.get("baud_rate"))
                
            self.logger.log(f"Arduino settings updated: Port={new_config.get('port')}, Baud={new_config.get('baud_rate')}", "INFO")

    def show_mqtt_settings_popup(self):
        """Show MQTT settings in a popup dialog (Harmonized)"""
        InterfaceRegistry.initialize()
        interface_class = InterfaceRegistry.get_interface_class("MQTT")
        if not interface_class:
            QMessageBox.critical(self, "Error", "MQTT interface not found in registry.")
            return
            
        # Get current config
        config = {
            "broker": self.settings.value("mqtt_broker", "localhost"),
            "port": int(self.settings.value("mqtt_port", 1883)),
            "client_id": self.settings.value("mqtt_client_id", f"ArtefaktDAQ_{int(time.time())}"),
            "username": self.settings.value("mqtt_username", ""),
            "password": self.settings.value("mqtt_password", ""),
            "auto_connect": self.settings.value("mqtt_auto_connect", "false") == "true",
            "enabled": self.settings.value("mqtt_enabled", "true") == "true"
        }
        
        instance = None
        if hasattr(self, 'data_collection_controller'):
            if hasattr(self.data_collection_controller, 'mqtt_thread'):
                instance = self.data_collection_controller.mqtt_thread
            
        dialog = InterfaceConfigDialog(self, interface_class=interface_class, interface_instance=instance, config=config)
        dialog.connection_status_changed.connect(self.update_device_connection_status_ui)
        
        if not hasattr(interface_class, "HELP_TEXT"):
            interface_class.HELP_TEXT = """
            <h3>MQTT Interface</h3>
            <p>Connects to an MQTT broker to receive sensor data.</p>
            <p><b>How to use:</b></p>
            <ol>
                <li>Enter your broker address and port.</li>
                <li>Set a unique Client ID.</li>
                <li>Add sensors with interface type 'MQTT' and set the 'Topic' as the sensor name/port.</li>
            </ol>
            """
            
        if dialog.exec():
            new_config = dialog.get_config()
            
            # Save settings
            self.settings.setValue("mqtt_broker", new_config.get("broker"))
            self.settings.setValue("mqtt_port", new_config.get("port"))
            self.settings.setValue("mqtt_client_id", new_config.get("client_id"))
            self.settings.setValue("mqtt_username", new_config.get("username"))
            self.settings.setValue("mqtt_password", new_config.get("password"))
            self.settings.setValue("mqtt_auto_connect", "true" if new_config.get("auto_connect") else "false")
            self.settings.setValue("mqtt_enabled", "true" if new_config.get("enabled") else "false")
            
            self.logger.log(f"MQTT settings updated: Broker={new_config.get('broker')}", "INFO")

    def show_labjack_settings_popup(self):
        """Show LabJack settings in a popup dialog (Harmonized)"""
        InterfaceRegistry.initialize()
        interface_class = InterfaceRegistry.get_interface_class("LabJack")
        if not interface_class:
            QMessageBox.critical(self, "Error", "LabJack interface not found in registry.")
            return
            
        # Get current config
        labjack_rate_val = self.settings.value("labjack_internal_rate", "100.0")
        try:
            labjack_rate = float(labjack_rate_val) if str(labjack_rate_val).lower() != 'none' else 100.0
        except (ValueError, TypeError):
            labjack_rate = 100.0

        config = {
            "device_type": self.settings.value("labjack_type", "T7"),
            "connection_type": self.settings.value("labjack_connection", "ANY"),
            "port": self.settings.value("labjack_port", "ANY"),
            "auto_reconnect": self.settings.value("labjack_auto_reconnect", "false") == "true",
            "sampling_rate": labjack_rate,
            "auto_connect": self.settings.value("labjack_auto_connect", "false") == "true",
            "enabled": self.settings.value("labjack_enabled", "true") == "true"
        }
        
        instance = None
        if hasattr(self, 'data_collection_controller'):
            # First try the thread object which always contains the interface instance
            if hasattr(self.data_collection_controller, 'labjack_thread'):
                instance = self.data_collection_controller.labjack_thread
            # Fallback to the interfaces dictionary
            if not instance:
                instance = self.data_collection_controller.interfaces.get('labjack', {}).get('interface')
            
        dialog = InterfaceConfigDialog(self, interface_class=interface_class, interface_instance=instance, config=config)
        dialog.connection_status_changed.connect(self.update_device_connection_status_ui)
        
        if not hasattr(interface_class, "HELP_TEXT"):
            interface_class.HELP_TEXT = """
            <h3>LabJack Interface</h3>
            <p>Handles communication with LabJack T-series devices (T4, T7).</p>
            <p><b>How to use:</b></p>
            <ol>
                <li>Select your device type (T4, T7, or ANY).</li>
                <li>Select connection type (USB, TCP, etc.).</li>
                <li>Set the identifier (Serial Number or IP address) or use 'ANY'.</li>
                <li>Once connected, AIN0-AIN3 and any configured EF channels will be available.</li>
            </ol>
            """
            
        if dialog.exec():
            new_config = dialog.get_config()
            
            # Save settings
            self.settings.setValue("labjack_type", new_config.get("device_type"))
            self.settings.setValue("labjack_connection", new_config.get("connection_type"))
            self.settings.setValue("labjack_port", new_config.get("port"))
            self.settings.setValue("labjack_auto_reconnect", "true" if new_config.get("auto_reconnect") else "false")
            self.settings.setValue("labjack_internal_rate", str(new_config.get("sampling_rate")))
            self.settings.setValue("labjack_auto_connect", "true" if new_config.get("auto_connect") else "false")
            self.settings.setValue("labjack_enabled", "true" if new_config.get("enabled") else "false")
            
            # Update internal rate if instance exists
            if instance and hasattr(instance, 'set_sampling_rate'):
                instance.set_sampling_rate(new_config.get("sampling_rate"))
                
            self.logger.log(f"LabJack settings updated: Type={new_config.get('device_type')}, Rate={new_config.get('sampling_rate')}", "INFO")

    def apply_camera_focus_exposure(self):
        """DEPRECATED: Now handled in camera_controller.py"""
        pass

    def update_focus_value_label(self):
        """DEPRECATED: Now handled in camera_controller.py"""
        pass

    def update_exposure_value_label(self):
        """DEPRECATED: Now handled in camera_controller.py"""
        pass
        
    def show_camera_settings_popup(self):
        """Show camera settings in a popup dialog"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Camera Settings")
        dialog.setMinimumWidth(700)  # Increased width for two columns
        dialog.setMinimumHeight(600)
        dialog.setStyleSheet(DialogStyles.dark_dialog())
        
        # Create main layout for the dialog
        main_layout = QVBoxLayout(dialog)
        
        # Create a horizontal layout for two columns
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(20)  # Space between columns
        
        # Create left column
        left_column = QVBoxLayout()
        
        # Create right column
        right_column = QVBoxLayout()
        
        # --- Group 1: Global Recording Settings ---
        recording_settings_group = QGroupBox("Global Recording Settings")
        recording_settings_group.setStyleSheet(GroupBoxStyles.default())
        recording_settings_layout = QGridLayout(recording_settings_group)
        
        # Include overlays in recording
        record_with_overlays = QCheckBox("Include overlays in recording")
        record_with_overlays.setChecked(self.settings.value("record_with_overlays", "true") == "true")
        recording_settings_layout.addWidget(record_with_overlays, 0, 0, 1, 2)
        
        # Video Quality slider
        recording_settings_layout.addWidget(QLabel("Video Quality:"), 1, 0)
        video_quality_slider = QSlider(Qt.Orientation.Horizontal)
        video_quality_slider.setMinimum(20); video_quality_slider.setMaximum(100)
        quality_value = self.settings_model.get_int("video_quality", 70)
        video_quality_slider.setValue(quality_value)
        video_quality_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        video_quality_slider.setTickInterval(10)
        recording_settings_layout.addWidget(video_quality_slider, 1, 1)
        
        video_quality_label = QLabel(f"{quality_value}%")
        video_quality_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        recording_settings_layout.addWidget(video_quality_label, 2, 1)
        video_quality_slider.valueChanged.connect(lambda v: video_quality_label.setText(f"{v}%"))

        # Recording format
        recording_settings_layout.addWidget(QLabel("Format:"), 3, 0)
        recording_format = QComboBox()
        recording_format.addItems(["MP4 (H.264)", "AVI (MJPG)", "AVI (XVID)"])
        recording_format.setCurrentText(self.settings_model.get_value("recording_format", "MP4 (H.264)"))
        recording_settings_layout.addWidget(recording_format, 3, 1)

        left_column.addWidget(recording_settings_group)
        
        # --- Group 2: Audio Settings ---
        audio_settings_group = QGroupBox("Global Audio Settings")
        audio_settings_group.setStyleSheet(GroupBoxStyles.default())
        audio_settings_layout = QGridLayout(audio_settings_group)
        
        # Audio controls for replay/streaming
        audio_settings_layout.addWidget(QLabel("Media Volume:"), 0, 0)
        media_volume = QSlider(Qt.Orientation.Horizontal)
        media_volume.setRange(0, 100); media_volume.setValue(int(self.settings.value("media_volume", "100")))
        audio_settings_layout.addWidget(media_volume, 0, 1)
        
        left_column.addWidget(audio_settings_group)
        left_column.addStretch()

        # --- Group 3: NDI Output Settings ---
        ndi_group = QGroupBox("NDI Output Settings")
        ndi_group.setStyleSheet(GroupBoxStyles.default())
        ndi_layout = QGridLayout(ndi_group)
        
        enable_ndi = QCheckBox("Enable NDI Output")
        enable_ndi.setChecked(self.settings.value("enable_ndi", "false") == "true")
        ndi_layout.addWidget(enable_ndi, 0, 0, 1, 2)
        
        ndi_layout.addWidget(QLabel("Source Name:"), 1, 0)
        ndi_source_name = QLineEdit(self.settings.value("ndi_source_name", "Artefakt DAQ"))
        ndi_layout.addWidget(ndi_source_name, 1, 1)
        
        ndi_with_overlays = QCheckBox("Include overlays in NDI output")
        ndi_with_overlays.setChecked(self.settings.value("ndi_with_overlays", "true") == "true")
        ndi_layout.addWidget(ndi_with_overlays, 2, 0, 1, 2)
        
        right_column.addWidget(ndi_group)

        # --- Group 4: Performance & Hardware ---
        perf_group = QGroupBox("Performance & Hardware")
        perf_group.setStyleSheet(GroupBoxStyles.default())
        perf_layout = QVBoxLayout(perf_group)
        
        use_direct_streaming = QCheckBox("Use Direct Streaming (Required for >1 min)")
        use_direct_streaming.setToolTip("Saves video directly to disk. Disabling this uses RAM (Burst Mode), which will crash the app for recordings longer than a minute.")
        use_direct_streaming.setChecked(self.settings_model.get_bool("use_direct_streaming", True))
        perf_layout.addWidget(use_direct_streaming)
        
        use_hw_accel = QCheckBox("Enable Hardware Acceleration (GPU)")
        use_hw_accel.setToolTip("Uses your Graphics Card (Nvidia, Intel, or AMD) to reduce CPU load during recording.")
        use_hw_accel.setChecked(self.settings_model.get_bool("use_hw_accel", True))
        perf_layout.addWidget(use_hw_accel)
        
        # Camera Auto-connect
        camera_auto_connect = QCheckBox("Auto-connect Camera on Startup")
        camera_auto_connect.setToolTip("Automatically connect to the selected camera source when the application starts.")
        camera_auto_connect.setChecked(self.settings.value("camera_auto_connect", "false") == "true")
        perf_layout.addWidget(camera_auto_connect)
        
        right_column.addWidget(perf_group)
        
        right_column.addStretch()
        
        # Add both columns to the columns layout
        columns_layout.addLayout(left_column)
        columns_layout.addLayout(right_column)
        
        main_layout.addLayout(columns_layout)
        
        # Add buttons to save/cancel
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(lambda: self.apply_camera_settings_from_popup(
            record_with_overlays.isChecked(),
            recording_format.currentText(),
            video_quality_slider.value(),
            media_volume.value(),
            enable_ndi.isChecked(),
            ndi_source_name.text(),
            ndi_with_overlays.isChecked(),
            use_direct_streaming.isChecked(),
            use_hw_accel.isChecked(),
            camera_auto_connect.isChecked(),
            dialog
        ))
        button_box.rejected.connect(dialog.reject)
        main_layout.addWidget(button_box)
        
        dialog.exec()

    def show_camera_config_dialog(self, slot_idx):
        """Show a modeless dialog for camera-specific configuration"""
        if hasattr(self, 'camera_config_dialog') and self.camera_config_dialog.isVisible():
            self.camera_config_dialog.setWindowTitle(f"Configure Camera {slot_idx + 1}")
            self.camera_config_dialog.raise_()
            self.camera_config_dialog.activateWindow()
            return

        dialog = QDialog(self)
        self.camera_config_dialog = dialog
        dialog.setObjectName("camera_config_dialog")
        dialog.setWindowTitle(f"Configure Camera {slot_idx + 1}")
        dialog.setMinimumWidth(450)
        dialog.setMinimumHeight(600)
        dialog.setStyleSheet(DialogStyles.dark_dialog())
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Move the tabs into the dialog
        if hasattr(self, 'camera_side_tabs'):
            # Reparent to dialog
            self.camera_side_tabs.setParent(dialog)
            layout.addWidget(self.camera_side_tabs)
            self.camera_side_tabs.setVisible(True)
            
        def on_dialog_finished(result):
            if hasattr(self, 'camera_side_tabs') and hasattr(self, 'camera_side_tabs_container'):
                # Reparent back to hidden container in main window
                self.camera_side_tabs.setParent(self.camera_side_tabs_container)
                if self.camera_side_tabs_container.layout():
                    self.camera_side_tabs_container.layout().addWidget(self.camera_side_tabs)
                self.camera_side_tabs.setVisible(False)

        dialog.finished.connect(on_dialog_finished)
        
        # Make it modeless
        dialog.setModal(False)
        dialog.show()
        
    def apply_camera_settings_from_popup(self, record_with_overlays, 
                                        recording_format, video_quality, media_volume,
                                        enable_ndi, ndi_source_name, ndi_with_overlays,
                                        use_direct_streaming, use_hw_accel, 
                                        camera_auto_connect, dialog):
        """Apply camera settings from the popup dialog"""
        # Update settings
        self.settings.setValue("record_with_overlays", "true" if record_with_overlays else "false")
        self.settings.setValue("recording_format", recording_format)
        self.settings.setValue("video_quality", str(video_quality))
        self.settings.setValue("media_volume", str(media_volume))
        
        # Update NDI and performance settings
        self.settings.setValue("enable_ndi", "true" if enable_ndi else "false")
        self.settings.setValue("ndi_source_name", ndi_source_name)
        self.settings.setValue("ndi_with_overlays", "true" if ndi_with_overlays else "false")
        self.settings.setValue("use_direct_streaming", "true" if use_direct_streaming else "false")
        self.settings.setValue("use_hw_accel", "true" if use_hw_accel else "false")
        self.settings.setValue("camera_auto_connect", "true" if camera_auto_connect else "false")

        dialog.accept()
        if hasattr(self, 'record_with_overlays'):
            self.record_with_overlays.setChecked(record_with_overlays)
        if hasattr(self, 'recording_format'):
            self.recording_format.setCurrentText(recording_format)
        if hasattr(self, 'video_quality_slider'):
            self.video_quality_slider.setValue(video_quality)
            
        # Update UI elements if they exist
        if hasattr(self, 'enable_ndi'):
            self.enable_ndi.setChecked(enable_ndi)
        if hasattr(self, 'ndi_source_name'):
            self.ndi_source_name.setText(ndi_source_name)
        if hasattr(self, 'ndi_with_overlays'):
            self.ndi_with_overlays.setChecked(ndi_with_overlays)
        if hasattr(self, 'use_direct_streaming'):
            self.use_direct_streaming.setChecked(use_direct_streaming)
        if hasattr(self, 'use_hw_accel'):
            self.use_hw_accel.setChecked(use_hw_accel)
            
        # Apply settings to camera controller if connected
        if hasattr(self, 'camera_controller'):
            # Trigger refresh of NDI if it changed
            if enable_ndi:
                self.camera_controller.init_ndi()
            
        # Close the dialog
        dialog.accept()
        
    def start_acquisition(self):
        """Start data acquisition"""
        # Clear snapshots immediately
        if hasattr(self, "load_snapshots_for_run"):
            self.load_snapshots_for_run(None)
            
        # Set the acquisition flag
        self.is_acquiring = True
        self.paused = False
        
        print("DEBUG MainWindow: start_acquisition called")
        
        # Get the run directory
        run_dir = self.get_current_run_dir()
        if run_dir:
            # Create the run directory if it doesn't exist
            os.makedirs(run_dir, exist_ok=True)
            
            # Move virtual_sensors.json to the run directory if it exists in current directory
            virtual_sensors_fallback_path = VIRTUAL_SENSORS_PATH
            virtual_sensors_run_path = os.path.join(run_dir, VIRTUAL_SENSORS_FILENAME)
            if os.path.exists(virtual_sensors_fallback_path) and not os.path.exists(virtual_sensors_run_path):
                try:
                    shutil.copy2(virtual_sensors_fallback_path, virtual_sensors_run_path)
                    self.logger.log(f"Copied virtual sensors config to run directory")
                except Exception as e:
                    self.logger.log(f"Failed to copy virtual sensors to run: {str(e)}", "ERROR")
            
            # Start data collection
            self.data_collection_controller.start_data_collection(run_dir)
            
            # Start the sensor controller
            if hasattr(self, 'sensor_controller'):
                print("DEBUG MainWindow: Calling sensor_controller.start_acquisition()")
                self.sensor_controller.start_acquisition()
            
            # Check if we have OtherSerial sensors and verify they're connected
            has_virtual_sensors = len(getattr(self, 'other_sensors', [])) > 0
            if has_virtual_sensors:
                print(f"DEBUG MainWindow: Has {len(self.other_sensors)} virtual sensors")
                # Check if other_serial interface is connected in the controller
                if hasattr(self.data_collection_controller, 'interfaces'):
                    other_serial_connected = 'other_serial' in self.data_collection_controller.interfaces and self.data_collection_controller.interfaces['other_serial'].get('connected', False)
                    print(f"DEBUG MainWindow: OtherSerial interface connected = {other_serial_connected}")
                    
            # Update the UI states
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
            
            # Change the status LED
            self.animation_status.setStyleSheet("background-color: green; border-radius: 10px;")
            
            # Log the acquisition start
            self.logger.log(f"Started data acquisition to {run_dir}")
            
            # Update other UI elements to indicate acquisition has started
            # ...
            
        else:
            # Show an error message
            QMessageBox.warning(
                self,
                "Data Acquisition",
                "Cannot start data acquisition - no run directory available",
                QMessageBox.StandardButton.Ok
            )
        
    def stop_acquisition(self):
        """Stop data acquisition"""
        print(f"[STOP] stop_acquisition called (redirecting to toggle)")
        self.logger.log("stop_acquisition called", "DEBUG")
        
        # Force button to Stop first
        self.toggle_btn.setText("Stop")
        
        # Then trigger the toggle
        self.on_toggle_clicked()
        
    def _apply_csv_configs(self):
        """Apply the current CSV configurations to the controller and UI."""
        if hasattr(self, 'data_collection_controller'):
            self.data_collection_controller.update_csv_interfaces(self.csv_configs)
        
        self.update_csv_status()
        
        # Also ensure virtual sensors are correctly populated in sensor table
        if hasattr(self, '_update_csv_virtual_sensors'):
            self._update_csv_virtual_sensors()

    def show_csv_settings_popup(self):
        """Show the popup for managing CSV data interfaces"""
        from app.ui.dialogs.csv_data_dialog import CSVDataDialog
        
        # Get existing configuration
        configs = deepcopy(getattr(self, 'csv_configs', []))
        
        # Get global sampling rate
        global_rate = 10.0
        if hasattr(self, 'data_collection_controller'):
            global_rate = self.data_collection_controller.sampling_rate
        
        # Show the dialog
        dialog = CSVDataDialog(self, configs=configs, global_rate=global_rate)
        
        if dialog.exec():
            # Update configs via the new centralized method
            self.update_csv_interfaces(dialog.configs)
            
            # Update the sensor table
            if hasattr(self, 'sensor_controller'):
                self.sensor_controller.update_sensor_table()
            
            # Reinitialize the dashboard graph if data collection is active to show new sensors
            if (hasattr(self, 'data_collection_controller') and 
                getattr(self.data_collection_controller, 'collecting_data', False)):
                
                if (hasattr(self, 'graph_controller') and 
                    getattr(self.graph_controller, 'live_plotting_active', False)):
                    
                    print("DEBUG: Reinitializing dashboard graph due to CSV config change")
                    start_time = self.data_collection_controller.start_time
                    if start_time is not None:
                        self.graph_controller.start_live_dashboard_update(start_time)
    
    def _update_csv_virtual_sensors(self):
        """Create, update or remove virtual sensors based on CSV mappings."""
        if not hasattr(self, 'sensor_controller'):
            return
            
        # Collect all current CSV sensor names from mapping configs that are ENABLED
        active_csv_sensors = []
        for cfg in self.csv_configs:
            # Check if this CSV interface is enabled
            if not cfg.get('enabled', True):
                continue
            for mapping in cfg.get('mappings', []):
                active_csv_sensors.append(mapping['sensor_name'])
        
        # 1. Remove sensors that are no longer in the active CSV configs but have interface_type="CSV"
        sensors_to_remove = []
        for sensor in self.sensor_controller.sensors:
            if getattr(sensor, 'interface_type', '') == "CSV":
                if sensor.name not in active_csv_sensors:
                    sensors_to_remove.append(sensor)
        
        for sensor in sensors_to_remove:
            print(f"DEBUG: Removing orphaned/disabled CSV sensor: {sensor.name}")
            self.sensor_controller.sensors.remove(sensor)
        
        # 2. Add new sensors or update existing ones for active mappings
        for name in active_csv_sensors:
            # Check if sensor already exists
            existing = next((s for s in self.sensor_controller.sensors if s.name == name), None)
            
            if not existing:
                from app.models.sensor_model import SensorModel
                new_sensor = SensorModel(
                    name=name,
                    interface_type="CSV",
                    port=f"csv_{name}", # Use port field to store the prefixed key for matching
                    enabled=True,
                    show_in_graph=True,
                    color="#00FF00", # Default green for CSV
                    stale_timeout_factor=5.0 # Set stale factor to 5x sampling interval (default)
                )
                self.sensor_controller.add_sensor_to_list(new_sensor)
            else:
                # Ensure interface type and port are set correctly
                existing.interface_type = "CSV"
                existing.port = f"csv_{name}"
                # Set stale factor to 5x sampling interval
                existing.stale_timeout_factor = 5.0
                # Ensure it's enabled by default when configured
                if not hasattr(existing, 'enabled') or existing.enabled is None:
                    existing.enabled = True

    def update_csv_status(self):
        """Update the CSV status label and device frame style"""
        if not hasattr(self, 'csv_status'):
            return
            
        configs = getattr(self, 'csv_configs', [])
        enabled_count = sum(1 for c in configs if c.get('enabled', True))
        
        if not configs:
            self.csv_status.setText("Not configured")
            self.csv_status.setStyleSheet("color: grey; font-size: 9px; background-color: transparent; border: none;")
            is_connected = False
        elif enabled_count > 0:
            self.csv_status.setText(f"{enabled_count} active")
            self.csv_status.setStyleSheet("color: #4CAF50; font-size: 9px; background-color: transparent; border: none;")
            is_connected = True
        else:
            self.csv_status.setText(f"{len(configs)} disabled")
            self.csv_status.setStyleSheet("color: orange; font-size: 9px; background-color: transparent; border: none;")
            is_connected = False
            
        # Track connection status
        self.interface_connections['csv'] = is_connected
        
        # Update card style
        csv_container = self.csv_status.parent()
        if csv_container and hasattr(csv_container, 'setStyleSheet'):
            csv_container.setStyleSheet(self._device_card_style(is_connected))

    def show_other_settings_popup(self):
        """Show the popup for managing COM port polling sequences"""
        # Create a dialog for managing sequences
        from app.ui.dialogs.other_sensors_dialog import OtherSensorsDialog
        
        # Get existing configuration (if any)
        sensors = deepcopy(getattr(self, 'other_sensors', []))
        sequences = deepcopy(getattr(self, 'other_sequences', []))
        
        # Check if any Serial Sensors are currently connected
        other_sensors_connected = False
        if hasattr(self, 'data_collection_controller'):
            data_controller = self.data_collection_controller
            if hasattr(data_controller, 'interfaces') and 'other_serial' in data_controller.interfaces:
                other_serial_interfaces = data_controller.interfaces['other_serial']
                
                # Check if other_serial_interfaces is a dictionary with a 'connected' key directly
                if isinstance(other_serial_interfaces, dict) and 'connected' in other_serial_interfaces:
                    other_sensors_connected = other_serial_interfaces['connected']
                # Safely iterate through values only when they are dictionaries
                elif isinstance(other_serial_interfaces, dict):
                    other_sensors_connected = any(
                        isinstance(conn, dict) and conn.get('connected', False) 
                        for conn in other_serial_interfaces.values()
                    )
                
                if other_sensors_connected:
                    self.logger.log("Serial Sensors connection detected", "INFO")
        
        # Show the dialog
        dialog = OtherSensorsDialog(self, sensors=sensors, sequences=sequences)
        
        # If we already have a connection, make sure the UI reflects this state
        if other_sensors_connected and hasattr(self, 'update_device_connection_status_ui'):
            self.update_device_connection_status_ui('other', True)
        
        # Execute the dialog and handle the result
        if dialog.exec():
            # Only update sequences as sensors are now managed in the main sensor table
            self.other_sequences = dialog.sequences
            
            # Keep the existing sensors reference for backward compatibility
            self.other_sensors = dialog.sensors
            
            # Save the configurations
            self.save_virtual_sensors()
            
            # Reconnect all configured sequences with their associated virtual sensors
            if hasattr(self, 'sensor_controller'):
                # Try to use the dedicated method if available
                if hasattr(self.sensor_controller, 'reinitialize_other_serial_connections'):
                    self.logger.log("Reconnecting virtual sensors after configuration change...")
                    self.sensor_controller.reinitialize_other_serial_connections()
                elif hasattr(self.sensor_controller, 'initialize_other_serial_connections'):
                    self.logger.log("Reconnecting virtual sensors after configuration change...")
                    self.sensor_controller.initialize_other_serial_connections()
                else:
                    # Use the built-in method
                    self._connect_virtual_sensors()
            else:
                # Fallback to the basic connection method
                self._connect_virtual_sensors()
            
            # Update the sensor table to reflect any changes
            if hasattr(self, 'sensor_controller'):
                self.sensor_controller.update_sensor_table()

    def show_optical_sensor_popup(self):
        """Show the popup for managing Optical Sensors (camera-based sensors)"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem, QMessageBox
        from app.ui.theme import ButtonStyles, COLORS, GroupBoxStyles, DialogStyles
        
        # Create dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Optical Sensor Management")
        dialog.setMinimumSize(500, 400)
        dialog.setStyleSheet(DialogStyles.dark_dialog())
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Header
        header = QLabel("🎥 Optical Sensors")
        header.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {COLORS.TEXT_PRIMARY};")
        layout.addWidget(header)
        
        # Description
        desc = QLabel(
            "Optical Sensors use cameras to detect light events, measure brightness, "
            "track colors/positions, count particles, or detect fill levels.\n\n"
            "⚠️ Note: A camera used as an optical sensor cannot be used for video recording."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(desc)
        
        # List of optical sensors
        sensor_list = QListWidget()
        sensor_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS.BG_CARD};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 8px;
                padding: 5px;
            }}
            QListWidget::item {{
                padding: 10px;
                border-radius: 4px;
            }}
            QListWidget::item:selected {{
                background-color: rgba(108, 92, 231, 0.45);
            }}
        """)
        
        # Populate list with optical sensors
        optical_sensors = []
        if hasattr(self, 'sensor_controller'):
            optical_sensors = self.sensor_controller.get_optical_sensors()
            for sensor in optical_sensors:
                mode = "Unknown"
                if hasattr(sensor, 'optical_config') and sensor.optical_config:
                    mode = sensor.optical_config.get('mode', 'light_events')
                item = QListWidgetItem(f"🎥 {sensor.name} - Mode: {mode}")
                item.setData(256, sensor)  # Store sensor in item data
                sensor_list.addItem(item)
        
        if not optical_sensors:
            empty_item = QListWidgetItem("No optical sensors configured")
            empty_item.setFlags(empty_item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            sensor_list.addItem(empty_item)
        
        layout.addWidget(sensor_list)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        add_btn = QPushButton("➕ Add Optical Sensor")
        add_btn.setStyleSheet(ButtonStyles.success("medium"))
        
        config_btn = QPushButton("⚙️ Configure")
        config_btn.setStyleSheet(ButtonStyles.primary("medium"))
        config_btn.setEnabled(False)
        
        connect_btn = QPushButton("🔌 Connect")
        connect_btn.setStyleSheet(ButtonStyles.info("medium"))
        connect_btn.setEnabled(False)
        
        disconnect_btn = QPushButton("❌ Disconnect")
        disconnect_btn.setStyleSheet(ButtonStyles.secondary("medium"))
        disconnect_btn.setEnabled(False)
        
        remove_btn = QPushButton("🗑️ Remove")
        remove_btn.setStyleSheet(ButtonStyles.danger("medium"))
        remove_btn.setEnabled(False)
        
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(config_btn)
        btn_layout.addWidget(connect_btn)
        btn_layout.addWidget(disconnect_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(remove_btn)
        
        layout.addLayout(btn_layout)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(ButtonStyles.secondary("medium"))
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        
        # Update button states based on selection
        def on_selection_changed():
            selected = sensor_list.currentItem()
            has_selection = selected is not None and selected.data(256) is not None
            config_btn.setEnabled(has_selection)
            remove_btn.setEnabled(has_selection)
            
            if has_selection:
                sensor = selected.data(256)
                is_connected = False
                if hasattr(self, 'sensor_controller') and hasattr(self.sensor_controller, 'optical_sensor_interfaces'):
                    if sensor.name in self.sensor_controller.optical_sensor_interfaces:
                        interface = self.sensor_controller.optical_sensor_interfaces[sensor.name]
                        is_connected = getattr(interface, 'connected', False)
                connect_btn.setEnabled(not is_connected)
                disconnect_btn.setEnabled(is_connected)
        
        sensor_list.itemSelectionChanged.connect(on_selection_changed)
        
        # Auto-select first sensor if available so buttons become active
        if sensor_list.count() > 0 and optical_sensors:
            sensor_list.setCurrentRow(0)
            # Use QTimer to ensure selection is processed after dialog is shown
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, on_selection_changed)
        
        # Button handlers
        def add_sensor():
            if hasattr(self, 'sensor_controller'):
                self.sensor_controller._show_add_optical_sensor_dialog()
                dialog.accept()  # Close and reopen to refresh
                self.show_optical_sensor_popup()
        
        def configure_sensor():
            selected = sensor_list.currentItem()
            if selected and selected.data(256):
                sensor = selected.data(256)
                if hasattr(self, 'sensor_controller'):
                    self.sensor_controller.show_optical_sensor_config(sensor)
                    # Refresh button states after configuration
                    on_selection_changed()
        
        def connect_sensor():
            selected = sensor_list.currentItem()
            if selected and selected.data(256):
                sensor = selected.data(256)
                if hasattr(self, 'sensor_controller'):
                    if self.sensor_controller.connect_optical_sensor(sensor):
                        self.logger.log(f"Connected Optical Sensor: {sensor.name}")
                        self.update_optical_sensor_status()
                        on_selection_changed()
        
        def disconnect_sensor():
            selected = sensor_list.currentItem()
            if selected and selected.data(256):
                sensor = selected.data(256)
                if hasattr(self, 'sensor_controller'):
                    if self.sensor_controller.disconnect_optical_sensor(sensor):
                        self.logger.log(f"Disconnected Optical Sensor: {sensor.name}")
                        self.update_optical_sensor_status()
                        on_selection_changed()
        
        def remove_sensor():
            selected = sensor_list.currentItem()
            if selected and selected.data(256):
                sensor = selected.data(256)
                result = QMessageBox.question(
                    dialog, "Remove Sensor",
                    f"Are you sure you want to remove '{sensor.name}'?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if result == QMessageBox.StandardButton.Yes:
                    # Disconnect first
                    if hasattr(self, 'sensor_controller'):
                        self.sensor_controller.disconnect_optical_sensor(sensor)
                        # Remove from sensor list
                        self.sensor_controller.sensors.remove(sensor)
                        self.sensor_controller.update_sensor_table()
                        self.sensor_controller.save_sensors()
                    dialog.accept()
                    self.show_optical_sensor_popup()
        
        add_btn.clicked.connect(add_sensor)
        config_btn.clicked.connect(configure_sensor)
        connect_btn.clicked.connect(connect_sensor)
        disconnect_btn.clicked.connect(disconnect_sensor)
        remove_btn.clicked.connect(remove_sensor)
        
        # Double-click to configure
        sensor_list.itemDoubleClicked.connect(lambda: configure_sensor())
        
        dialog.exec()
    
    def update_optical_sensor_status(self):
        """Update the optical sensor status label and device button frame"""
        if not hasattr(self, 'optical_status'):
            return
        
        # Count optical sensors
        optical_sensors = []
        connected_count = 0
        
        if hasattr(self, 'sensor_controller'):
            optical_sensors = self.sensor_controller.get_optical_sensors()
            if hasattr(self.sensor_controller, 'optical_sensor_interfaces') and self.sensor_controller.optical_sensor_interfaces:
                # Count only actually connected sensors
                for sensor in optical_sensors:
                    if sensor.name in self.sensor_controller.optical_sensor_interfaces:
                        interface = self.sensor_controller.optical_sensor_interfaces[sensor.name]
                        if interface:
                            # Check connected status - can be attribute or property
                            is_interface_connected = False
                            if hasattr(interface, 'connected'):
                                is_interface_connected = bool(interface.connected)
                            elif hasattr(interface, 'is_connected'):
                                is_interface_connected = bool(interface.is_connected())
                            
                            if is_interface_connected:
                                connected_count += 1
        
        # Update status label
        if len(optical_sensors) == 0:
            self.optical_status.setText("Not configured")
            self.optical_status.setStyleSheet("color: grey; font-size: 9px; background-color: transparent; border: none;")
            is_connected = False
        elif connected_count > 0:
            self.optical_status.setText(f"{connected_count} connected")
            self.optical_status.setStyleSheet("color: #4CAF50; font-size: 9px; background-color: transparent; border: none;")
            is_connected = True
        else:
            self.optical_status.setText(f"{len(optical_sensors)} configured")
            self.optical_status.setStyleSheet("color: orange; font-size: 9px; background-color: transparent; border: none;")
            is_connected = False
            
        # Track connection status
        self.interface_connections['opticalsensor'] = is_connected
        self.interface_connections['optical_sensor'] = is_connected
        
        # Update device button frame style (like Arduino/LabJack)
        if hasattr(self, 'optical_status'):
            optical_container = self.optical_status.parent()
            if optical_container and hasattr(optical_container, 'setStyleSheet'):
                optical_container.setStyleSheet(self._device_card_style(is_connected))
                optical_container.update()

    def show_audio_sensor_popup(self):
        """Show the popup for managing Audio Sensors (microphone-based sensors)"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem, QMessageBox
        from app.ui.theme import ButtonStyles, COLORS, GroupBoxStyles, DialogStyles
        
        # Create dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Audio Sensor Management")
        dialog.setMinimumSize(500, 400)
        dialog.setStyleSheet(DialogStyles.dark_dialog())
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Header
        header = QLabel("🎤 Audio Sensors")
        header.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {COLORS.TEXT_PRIMARY};")
        layout.addWidget(header)
        
        # Description
        desc = QLabel(
            "Audio Sensors use microphones to measure sound properties like:\n"
            "• RMS Level (loudness)\n"
            "• Peak Amplitude\n"
            "• Dominant Frequency\n"
            "• dB Level\n\n"
            "These derived values can be graphed like any other sensor."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(desc)
        
        # List of audio sensors
        sensor_list = QListWidget()
        sensor_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS.BG_CARD};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 8px;
                padding: 5px;
            }}
            QListWidget::item {{
                padding: 10px;
                border-radius: 4px;
            }}
            QListWidget::item:selected {{
                background-color: rgba(108, 92, 231, 0.45);
            }}
        """)
        
        # Populate list with audio sensors
        audio_sensors = []
        if hasattr(self, 'sensor_controller'):
            audio_sensors = self.sensor_controller.get_audio_sensors()
            for sensor in audio_sensors:
                mode = "rms"
                if hasattr(sensor, 'audio_config') and sensor.audio_config:
                    mode = sensor.audio_config.get('mode', 'rms')
                item = QListWidgetItem(f"🎤 {sensor.name} - Mode: {mode}")
                item.setData(256, sensor)  # Store sensor in item data
                sensor_list.addItem(item)
        
        if not audio_sensors:
            empty_item = QListWidgetItem("No audio sensors configured")
            empty_item.setFlags(empty_item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            sensor_list.addItem(empty_item)
        
        layout.addWidget(sensor_list)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        add_btn = QPushButton("➕ Add Audio Sensor")
        add_btn.setStyleSheet(ButtonStyles.success("medium"))
        
        config_btn = QPushButton("⚙️ Configure")
        config_btn.setStyleSheet(ButtonStyles.primary("medium"))
        config_btn.setEnabled(False)
        
        connect_btn = QPushButton("🔌 Connect")
        connect_btn.setStyleSheet(ButtonStyles.info("medium"))
        connect_btn.setEnabled(False)
        
        disconnect_btn = QPushButton("❌ Disconnect")
        disconnect_btn.setStyleSheet(ButtonStyles.secondary("medium"))
        disconnect_btn.setEnabled(False)
        
        remove_btn = QPushButton("🗑️ Remove")
        remove_btn.setStyleSheet(ButtonStyles.danger("medium"))
        remove_btn.setEnabled(False)
        
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(config_btn)
        btn_layout.addWidget(connect_btn)
        btn_layout.addWidget(disconnect_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(remove_btn)
        
        layout.addLayout(btn_layout)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(ButtonStyles.secondary("medium"))
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        
        # Update button states based on selection
        def on_selection_changed():
            selected = sensor_list.currentItem()
            has_selection = selected is not None and selected.data(256) is not None
            config_btn.setEnabled(has_selection)
            remove_btn.setEnabled(has_selection)
            
            if has_selection:
                sensor = selected.data(256)
                is_connected = False
                if hasattr(self, 'sensor_controller') and hasattr(self.sensor_controller, 'audio_sensor_interfaces'):
                    if sensor.name in self.sensor_controller.audio_sensor_interfaces:
                        interface = self.sensor_controller.audio_sensor_interfaces[sensor.name]
                        is_connected = getattr(interface, 'connected', False)
                connect_btn.setEnabled(not is_connected)
                disconnect_btn.setEnabled(is_connected)
        
        sensor_list.itemSelectionChanged.connect(on_selection_changed)
        
        # Auto-select first sensor if available so buttons become active
        if sensor_list.count() > 0 and audio_sensors:
            sensor_list.setCurrentRow(0)
            # Use QTimer to ensure selection is processed after dialog is shown
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, on_selection_changed)
        
        # Button handlers
        def add_sensor():
            if hasattr(self, 'sensor_controller'):
                self.sensor_controller._show_add_audio_sensor_dialog()
                dialog.accept()  # Close and reopen to refresh
                self.show_audio_sensor_popup()
        
        def configure_sensor():
            selected = sensor_list.currentItem()
            if selected and selected.data(256):
                sensor = selected.data(256)
                if hasattr(self, 'sensor_controller'):
                    self.sensor_controller.show_audio_sensor_config(sensor)
                    # Refresh button states after configuration
                    on_selection_changed()
        
        def connect_sensor():
            selected = sensor_list.currentItem()
            if selected and selected.data(256):
                sensor = selected.data(256)
                if hasattr(self, 'sensor_controller'):
                    if self.sensor_controller.connect_audio_sensor(sensor):
                        self.logger.log(f"Connected Audio Sensor: {sensor.name}")
                        self.update_audio_sensor_status()
                        on_selection_changed()
        
        def disconnect_sensor():
            selected = sensor_list.currentItem()
            if selected and selected.data(256):
                sensor = selected.data(256)
                if hasattr(self, 'sensor_controller'):
                    if self.sensor_controller.disconnect_audio_sensor(sensor):
                        self.logger.log(f"Disconnected Audio Sensor: {sensor.name}")
                        self.update_audio_sensor_status()
                        on_selection_changed()
        
        def remove_sensor():
            selected = sensor_list.currentItem()
            if selected and selected.data(256):
                sensor = selected.data(256)
                result = QMessageBox.question(
                    dialog, "Remove Sensor",
                    f"Are you sure you want to remove '{sensor.name}'?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if result == QMessageBox.StandardButton.Yes:
                    # Disconnect first
                    if hasattr(self, 'sensor_controller'):
                        self.sensor_controller.disconnect_audio_sensor(sensor)
                        # Remove from sensor list
                        self.sensor_controller.sensors.remove(sensor)
                        self.sensor_controller.update_sensor_table()
                        self.sensor_controller.save_sensors()
                    dialog.accept()
                    self.show_audio_sensor_popup()
        
        add_btn.clicked.connect(add_sensor)
        config_btn.clicked.connect(configure_sensor)
        connect_btn.clicked.connect(connect_sensor)
        disconnect_btn.clicked.connect(disconnect_sensor)
        remove_btn.clicked.connect(remove_sensor)
        
        # Double-click to configure
        sensor_list.itemDoubleClicked.connect(lambda: configure_sensor())
        
        dialog.exec()
    
    def update_audio_sensor_status(self):
        """Update the audio sensor status label and device button frame"""
        if not hasattr(self, 'audio_status'):
            return
        
        # Count audio sensors
        audio_sensors = []
        connected_count = 0
        
        if hasattr(self, 'sensor_controller'):
            audio_sensors = self.sensor_controller.get_audio_sensors()
            if hasattr(self.sensor_controller, 'audio_sensor_interfaces'):
                # Count only actually connected sensors
                for sensor in audio_sensors:
                    if sensor.name in self.sensor_controller.audio_sensor_interfaces:
                        interface = self.sensor_controller.audio_sensor_interfaces[sensor.name]
                        if interface and getattr(interface, 'connected', False):
                            connected_count += 1
        
        # Update status label
        if len(audio_sensors) == 0:
            self.audio_status.setText("Not configured")
            self.audio_status.setStyleSheet("color: grey; font-size: 9px; background-color: transparent; border: none;")
            is_connected = False
        elif connected_count > 0:
            self.audio_status.setText(f"{connected_count} connected")
            self.audio_status.setStyleSheet("color: #4CAF50; font-size: 9px; background-color: transparent; border: none;")
            is_connected = True
        else:
            self.audio_status.setText(f"{len(audio_sensors)} configured")
            self.audio_status.setStyleSheet("color: orange; font-size: 9px; background-color: transparent; border: none;")
            is_connected = False
        
        # Track connection status
        self.interface_connections['audiosensor'] = is_connected
        self.interface_connections['audio_sensor'] = is_connected
        
        # Update device button frame style (like Arduino/LabJack)
        if hasattr(self, 'audio_status'):
            audio_container = self.audio_status.parent()
            if audio_container and hasattr(audio_container, 'setStyleSheet'):
                audio_container.setStyleSheet(self._device_card_style(is_connected))
                audio_container.update()

    def refresh_dashboard_camera_sources(self):
        """Refresh dashboard camera checkboxes based on controller state"""
        if not hasattr(self, 'dashboard_camera_checkboxes') or not hasattr(self, 'camera_controller'):
            return
            
        for i, cb in enumerate(self.dashboard_camera_checkboxes):
            cb.blockSignals(True)
            # Check if camera i is active in any slot
            is_active = i in self.camera_controller.dashboard_slots
            cb.setChecked(is_active)
            cb.blockSignals(False)
            
        # Trigger visibility update
        for i in range(4):
            self.switch_dashboard_camera_source(i)
        
        # Ensure row visibilities are updated
        self._update_row_visibilities()

    def switch_dashboard_camera_source(self, slot_idx):
        """Switch the camera visibility based on checkbox state"""
        if not hasattr(self, 'dashboard_camera_checkboxes') or slot_idx >= len(self.dashboard_camera_checkboxes):
            return
            
        cb = self.dashboard_camera_checkboxes[slot_idx]
        is_on = cb.isChecked()
        
        # Get label and video widget for this slot
        label = self.dashboard_camera_labels[slot_idx] if hasattr(self, 'dashboard_camera_labels') else None
        
        if not is_on:
            if label: 
                label.hide()
                label.setText("No camera selected") # Reset text
            # Update controller
            if hasattr(self, 'camera_controller'):
                if isinstance(self.camera_controller.dashboard_slots, list):
                    self.camera_controller.dashboard_slots[slot_idx] = -1
        else:
            if label: 
                label.show()
                # If not connected, it will show its default "No camera connected"
            # Update controller
            if hasattr(self, 'camera_controller'):
                if isinstance(self.camera_controller.dashboard_slots, list):
                    # For simple 1:1 mapping if not otherwise set
                    if self.camera_controller.dashboard_slots[slot_idx] == -1:
                         self.camera_controller.dashboard_slots[slot_idx] = slot_idx
                # Ensure dashboard display is enabled
                self.camera_controller.set_dashboard_display(True)
        
        # Manage row visibility directly for faster response
        row_idx = slot_idx // 2
        if hasattr(self, 'dashboard_camera_row_widgets') and hasattr(self, 'dashboard_camera_checkboxes'):
            row_checked = any(self.dashboard_camera_checkboxes[i].isChecked() 
                            for i in range(row_idx*2, min((row_idx+1)*2, len(self.dashboard_camera_labels))))
            self.dashboard_camera_row_widgets[row_idx].setVisible(row_checked)
        
        self._update_row_visibilities()

    def _update_row_visibilities(self):
        """Collapse or show rows based on active widgets and manage placeholder visibility"""
        is_replay = getattr(self, "replay_mode_enabled", False)
        
        any_live_visible = False
        # Live View Rows
        if hasattr(self, 'dashboard_camera_row_widgets') and hasattr(self, 'dashboard_camera_labels') and hasattr(self, 'dashboard_camera_checkboxes'):
            for row_idx in range(2):
                row_checked = False
                for i in range(row_idx*2, min((row_idx+1)*2, len(self.dashboard_camera_labels))):
                    checked = self.dashboard_camera_checkboxes[i].isChecked()
                    # In replay mode, labels are visible if checked. 
                    # They will be hidden manually if a video segment is successfully loaded for the slot.
                    label_should_be_visible = checked
                    self.dashboard_camera_labels[i].setVisible(label_should_be_visible)
                    if checked: row_checked = True
                
                # If we are in live mode, row visibility depends on checkboxes
                if not is_replay:
                    self.dashboard_camera_row_widgets[row_idx].setVisible(row_checked)
                    if row_checked: 
                        any_live_visible = True
                        # Ensure row widget is shown if a camera is checked
                        self.dashboard_camera_row_widgets[row_idx].show()
                else:
                    # In replay mode, handled by video widgets or "No video available" labels
                    self.dashboard_camera_row_widgets[row_idx].setVisible(False)
        
        any_video_visible = False
        # Replay View Rows
        if hasattr(self, 'dashboard_video_row_widgets') and hasattr(self, 'dashboard_video_widgets'):
            for row_idx in range(2):
                row_has_video = False
                for i in range(row_idx*2, min((row_idx+1)*2, len(self.dashboard_video_widgets))):
                    # In replay mode, video is active if path exists AND checkbox is checked
                    path_active = self.replay_active_video_paths[i] is not None
                    checkbox_checked = False
                    if hasattr(self, 'dashboard_camera_checkboxes'):
                        checkbox_checked = self.dashboard_camera_checkboxes[i].isChecked()
                    
                    is_visible = path_active and checkbox_checked
                    self.dashboard_video_widgets[i].setVisible(is_visible)
                    if is_visible: 
                        row_has_video = True
                        # Force widget update to prevent black screens
                        self.dashboard_video_widgets[i].update()
                
                if is_replay:
                    row_visible = row_has_video
                    # Also check for "No video available" labels
                    for i in range(row_idx*2, min((row_idx+1)*2, len(self.dashboard_camera_labels))):
                        if self.dashboard_camera_labels[i].isVisible():
                            row_visible = True
                            break
                    
                    self.dashboard_video_row_widgets[row_idx].setVisible(row_has_video)
                    if hasattr(self, 'dashboard_camera_row_widgets'):
                        self.dashboard_camera_row_widgets[row_idx].setVisible(not row_has_video and row_visible)
                    
                    if row_visible: any_video_visible = True
                else:
                    self.dashboard_video_row_widgets[row_idx].setVisible(False)

        # Placeholder visibility
        if hasattr(self, 'dashboard_camera_placeholder'):
            any_checked = False
            if hasattr(self, 'dashboard_camera_checkboxes'):
                any_checked = any(cb.isChecked() for cb in self.dashboard_camera_checkboxes)
            
            show_placeholder = not any_checked
            self.dashboard_camera_placeholder.setVisible(show_placeholder)
            
            if show_placeholder:
                self.dashboard_camera_placeholder.setText("No camera selected")
                if hasattr(self, 'dashboard_camera_row_widgets'):
                    for rw in self.dashboard_camera_row_widgets: 
                        rw.hide()
                if hasattr(self, 'dashboard_video_row_widgets'):
                    for rw in self.dashboard_video_row_widgets: 
                        rw.hide()
            else:
                # If any checked, ensure the placeholder is hidden
                self.dashboard_camera_placeholder.hide()
        
    def _display_optical_sensor_in_dashboard_slot(self, sensor_name, slot_idx):
        """Display an optical sensor's camera feed in a specific dashboard slot"""
        if not hasattr(self, 'sensor_controller') or not hasattr(self, 'dashboard_camera_labels'):
            return
            
        label = self.dashboard_camera_labels[slot_idx]
        
        # Check if the optical sensor is connected
        if not hasattr(self.sensor_controller, 'optical_sensor_interfaces'):
            label.setText(f"Optical Sensor '{sensor_name}' not connected")
            return
            
        if sensor_name not in self.sensor_controller.optical_sensor_interfaces:
            label.setText(f"Optical Sensor '{sensor_name}' not connected.\nConnect it in the Sensors tab first.")
            return
            
        # Get the interface and connect its frame signal to this slot
        interface = self.sensor_controller.optical_sensor_interfaces[sensor_name]
        if hasattr(interface, 'sensor_thread') and interface.sensor_thread:
            # Connect optical sensor frames to dashboard with slot context
            try:
                # We need to disconnect any previous connections to this slot or from this sensor to dashboard
                # For simplicity, we'll use a wrapper that knows its slot
                interface.sensor_thread.frame_for_display.connect(
                    lambda frame_data, s=slot_idx: self._update_dashboard_slot_from_optical(frame_data, s)
                )
                self.logger.log(f"Dashboard Slot {slot_idx+1}: Switched to optical sensor '{sensor_name}'", "INFO")
            except Exception as e:
                self.logger.log(f"Failed to connect optical sensor to slot {slot_idx+1}: {e}", "ERROR")

    def _update_dashboard_slot_from_optical(self, frame_data, slot_idx):
        """Update a specific dashboard slot from optical sensor frame"""
        try:
            import cv2
            from PyQt6.QtGui import QImage, QPixmap
            
            frame = frame_data.get('frame')
            if frame is None:
                return
                
            # Convert BGR to RGB
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, channel = rgb_frame.shape
            bytes_per_line = 3 * width
            q_img = QImage(rgb_frame.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
            
            # Scale to fit dashboard label
            if hasattr(self, 'dashboard_camera_labels') and slot_idx < len(self.dashboard_camera_labels):
                lbl = self.dashboard_camera_labels[slot_idx]
                if not lbl.isVisible(): return
                
                pixmap = QPixmap.fromImage(q_img)
                scaled_pixmap = pixmap.scaled(
                    lbl.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                lbl.setPixmap(scaled_pixmap)
        except Exception as e:
            print(f"Error updating dashboard slot {slot_idx} from optical sensor: {e}")

    def handle_labjack_connect_button(self):
        """Handle clicking the LabJack connect button"""
        print("DEBUG MAIN_WINDOW: handle_labjack_connect_button called") # <<< ADDED
        try:
            print("LabJack connect button clicked")
            
            # Get the current button text
            button_text = ""
            if hasattr(self, 'labjack_connect_btn') and self.labjack_connect_btn is not None:
                button_text = self.labjack_connect_btn.text()
                
            # Check if we should connect or disconnect
            if button_text == "Connect":
                # Show the LabJack connection dialog
                print("DEBUG MAIN_WINDOW: Calling show_connect_labjack_dialog()") # <<< ADDED
                self.show_connect_labjack_dialog()
            else:
                # Disconnect using the controller's method
                print("DEBUG MAIN_WINDOW: Disconnecting LabJack via sensor_controller") # <<< ADDED
                if hasattr(self, 'sensor_controller') and self.sensor_controller is not None:
                    # Use the new disconnect method that properly cleans up resources
                    self.sensor_controller.disconnect_labjack()
                    
                # Update button state using our dedicated method
                self.update_labjack_connected_status(False)
                
                # Log the disconnection
                if hasattr(self, 'logger') and self.logger is not None:
                    self.logger.log("Disconnected from LabJack")
        except Exception as e:
            print(f"Error in handle_labjack_connect_button: {e}")
            if hasattr(self, 'logger') and self.logger is not None:
                self.logger.log(f"Error in handle_labjack_connect_button: {e}", "ERROR")

    def setup_sensor_tab(self):
        """Set up the sensor tab UI and functionality"""
        try:
            print("Setting up sensor tab UI...")
            
            # Set up table
            if hasattr(self, 'data_table'):
                self.data_table.setColumnCount(6)  # Change from 5 to 6 columns to include color
                self.data_table.setHorizontalHeaderLabels(["Use", "Sensor", "Value", "Interface", "Offset/Unit", "Color"])
                self.data_table.setColumnWidth(0, 50)   # Show column is narrow
                self.data_table.setColumnWidth(1, 150)  # Sensor name
                self.data_table.setColumnWidth(2, 120)  # Value
                self.data_table.setColumnWidth(3, 100)  # Interface type
                self.data_table.setColumnWidth(4, 100)  # Offset/Unit
                self.data_table.setColumnWidth(5, 80)   # Color
                
                # Enable selection
                self.data_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
                self.data_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
                
                # Set table properties
                self.data_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
                self.data_table.setAlternatingRowColors(True)
                self.data_table.setSortingEnabled(False)
                
                print("Sensor table set up")
            else:
                print("Warning: data_table widget not found")
            
            # Configure buttons - Keep them enabled
            if hasattr(self, 'edit_sensor_btn'):
                print("Edit sensor button found")
            if hasattr(self, 'remove_sensor_btn'):
                print("Remove sensor button found")
            
            # If we have a sensor controller, update the table with any existing sensors
            if hasattr(self, 'sensor_controller'):
                self.sensor_controller.update_sensor_table()
                print("Sensor table populated with existing sensors")
            
            # Set up the values update timer
            # Get the sampling rate from settings (default to 1.0Hz if not set)
            val = self.settings.value("global_sampling_rate", "1.0")
            try:
                sampling_rate = float(val) if str(val).lower() != 'none' else 1.0
            except (ValueError, TypeError):
                sampling_rate = 1.0
            
            # Calculate update interval in milliseconds (minimum 100ms for UI responsiveness)
            update_interval = max(int(1000 / sampling_rate), 100)
            
            self.sensor_values_timer = QTimer(self)
            
            # Create dummy data for the timer callback
            # Without this, the update_sensor_values method won't update automation context
            dummy_data = {'dummy': 0, 'timestamp': time.time()}
            
            # Connect timer to the update_sensor_values method
            # This method will update the table AND the automation context
            self.sensor_values_timer.timeout.connect(self.update_sensor_values)
            
            # --- RE-ENABLE TABLE UPDATE TIMER --- 
            print(f"DEBUG MAIN_WINDOW: Sensor values timer setup AND STARTING. Interval: {update_interval}ms")
            self.sensor_values_timer.start(update_interval)
            # -----------------------------------
                
            # Connect signals - this is where the buttons get connected to methods
            self.setup_sensor_tab_signals()
            
            # Add stream button if stream controller is available
            if hasattr(self, 'stream_controller') and self.stream_controller:
                self.stream_controller.add_stream_button_to_ui()
            
            print("Sensor tab UI setup complete")
        except Exception as e:
            print(f"Error in setup_sensor_tab: {e}")
            import traceback
            traceback.print_exc()

    def setup_sensor_tab_signals(self):
        """Connect signals for the sensor tab buttons."""
        try:
            if hasattr(self, 'add_sensor_btn'):
                self.add_sensor_btn.clicked.connect(self.add_sensor)
                print("Connected add_sensor_btn")
            else:
                print("Warning: add_sensor_btn not found")

            if hasattr(self, 'edit_sensor_btn'):
                self.edit_sensor_btn.clicked.connect(self.edit_sensor)
                print("Connected edit_sensor_btn")
            else:
                print("Warning: edit_sensor_btn not found")

            if hasattr(self, 'remove_sensor_btn'):
                self.remove_sensor_btn.clicked.connect(self.remove_sensor)
                print("Connected remove_sensor_btn")
            else:
                print("Warning: remove_sensor_btn not found")
                
            # Connect cell clicked signal for selection/color change
            if hasattr(self, 'data_table'):
                 self.data_table.cellClicked.connect(self.sensor_cell_clicked)
                 print("Connected data_table cellClicked")

        except Exception as e:
            print(f"Error connecting sensor tab signals: {e}")
            import traceback
            traceback.print_exc()

    def show_add_sensor_dialog(self):
        """Show the add sensor dialog directly"""
        print("show_add_sensor_dialog called")
        
        # Try different approaches to show the dialog
        if hasattr(self, 'sensor_controller') and self.sensor_controller:
            print("Using sensor_controller to show dialog")
            self.sensor_controller.add_sensor()
        else:
            print("No sensor_controller found, trying direct approach")
            # Creating a basic dialog as a fallback
            from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, 
                                        QPushButton, QMessageBox)
            
            # Create a simple error dialog
            dialog = QDialog(self)
            dialog.setWindowTitle("Add Sensor")
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel("Error: Sensor controller not initialized."))
            layout.addWidget(QLabel("Please make sure the application is properly initialized."))
            
            # Add a button to close the dialog
            button = QPushButton("OK")
            button.clicked.connect(dialog.accept)
            layout.addWidget(button)
            
            # Show the dialog
            dialog.exec()

    def update_sensor_values(self):
        """Update sensor values periodically - called by the sensor timer"""
        try:
            # Check if sensor controller exists
            if hasattr(self, 'sensor_controller') and self.sensor_controller:
                # Let the sensor controller do the update (updates the table)
                self.sensor_controller.update_sensor_values()
        except Exception as e:
            print(f"Error in update_sensor_values: {e}")
            # Don't print the full stack trace every time to avoid log spam

    def select_sensor(self, row, column):
        """Handle sensor selection in the table
        
        Args:
            row: The row index
            column: The column index
        """
        print(f"SELECT_SENSOR CALLED with row={row}, column={column}")
        
        try:
            # Enable the buttons directly - no complex checks
            if hasattr(self, 'edit_sensor_btn'):
                self.edit_sensor_btn.setEnabled(True)
                print("Successfully enabled edit_sensor_btn")
                
            if hasattr(self, 'remove_sensor_btn'):
                self.remove_sensor_btn.setEnabled(True)
                print("Successfully enabled remove_sensor_btn")
                
        except Exception as e:
            print(f"Error in select_sensor: {e}")
            import traceback
            traceback.print_exc()

    def sensor_cell_clicked(self, row, column):
        """Handle click on a sensor table cell"""
        try:
            # Check if the click was on the color column (column 5)
            if column == 5:
                # Get the sensor
                if hasattr(self, 'sensor_controller') and self.sensor_controller:
                    if row < len(self.sensor_controller.sensors):
                        sensor = self.sensor_controller.sensors[row]
                        
                        # Open color picker dialog
                        from PyQt6.QtGui import QColor
                        
                        # Ensure we start with a valid color
                        try:
                            current_color = QColor(sensor.color)
                            if not current_color.isValid():
                                current_color = QColor("#FFFFFF")  # Default to white if invalid
                        except:
                            current_color = QColor("#FFFFFF")  # Default to white on error
                            
                        color = QColorDialog.getColor(current_color, self, "Choose Sensor Color")
                        if color.isValid():
                            # Update sensor color with the color name
                            sensor.color = color.name()
                            
                            # Immediately force the color in the table cell
                            if hasattr(self, 'data_table'):
                                item = self.data_table.item(row, column)
                                if item:
                                    item.setBackground(color)
                                    item.setText(color.name())
                                    text_color = "black" if color.lightness() > 128 else "white"
                                    item.setForeground(QColor(text_color))
                            
                            # Update the table 
                            self.sensor_controller.update_sensor_table()
                            
                            # Update dashboard if it exists
                            if hasattr(self, '_tools_window') and self._tools_window:
                                if hasattr(self._tools_window, 'statistics_dashboard'):
                                    self._tools_window.statistics_dashboard.update_sensor_color(sensor)
                            elif hasattr(self, 'tools_window') and self.tools_window:
                                if hasattr(self.tools_window, 'statistics_dashboard'):
                                    self.tools_window.statistics_dashboard.update_sensor_color(sensor)
                            
                            # Log the change
                            if hasattr(self, 'logger'):
                                self.logger.log(f"Changed color for sensor {sensor.name} to {sensor.color}")
        except Exception as e:
            print(f"Error in sensor_cell_clicked: {e}")
            import traceback
            traceback.print_exc()

    def update_labjack_connected_status(self, is_connected):
        """Update the LabJack connection status display
        
        Args:
            is_connected (bool): Whether the LabJack is connected
        """
        print(f"Direct LabJack status update: is_connected={is_connected}")
        
        # Track connection status
        self.interface_connections['labjack'] = is_connected
        
        # First try to update the button if it exists
        if hasattr(self, 'labjack_connect_btn'):
            self.labjack_connect_btn.setText("Disconnect" if is_connected else "Connect")
            
            # Apply appropriate button style using theme system
            if is_connected:
                self.labjack_connect_btn.setStyleSheet(ConnectionStyles.disconnected())
            else:
                self.labjack_connect_btn.setStyleSheet(ConnectionStyles.connected())
            
            self.labjack_connect_btn.repaint()
        
        # Set the text and color directly on the labjack_status label if it exists
        if hasattr(self, 'labjack_status'):
            status_text = "Connected" if is_connected else "Not connected"
            status_color = get_status_color("connected") if is_connected else get_status_color("inactive")
            print(f"Directly updating labjack_status label to '{status_text}' with color '{status_color}'")
            self.labjack_status.setText(status_text)
            self.labjack_status.setStyleSheet(f"color: {status_color}; font-size: 9px; background-color: transparent; border: none;")
            self.labjack_status.repaint()
            labjack_container = self.labjack_status.parent()
            if labjack_container and hasattr(labjack_container, 'setStyleSheet'):
                labjack_container.setStyleSheet(self._device_card_style(is_connected))
                labjack_container.update()
        
        # Force application to process events immediately
        from PyQt6.QtCore import QCoreApplication
        QCoreApplication.processEvents()
        
        # Log the status change
        status_str = "connected" if is_connected else "disconnected"
        if hasattr(self, 'logger'):
            self.logger.log(f"LabJack {status_str}", "INFO")

    def update_other_connected_status(self, is_connected):
        """Update the Serial Sensors connection status display
        
        Args:
            is_connected (bool): Whether Serial Sensors are connected
        """
        print(f"Direct Serial Sensors status update: is_connected={is_connected}")
        
        # Track connection status
        self.interface_connections['otherserial'] = is_connected
        self.interface_connections['other_serial'] = is_connected
        
        # Set the text and color directly on the other_status label if it exists
        if hasattr(self, 'other_status'):
            status_text = "Connected" if is_connected else "Not connected"
            status_color = "green" if is_connected else "grey"
            print(f"Directly updating other_status label to '{status_text}' with color '{status_color}'")
            self.other_status.setText(status_text)
            self.other_status.setStyleSheet(f"color: {status_color}; font-size: 9px; background-color: transparent; border: none;")
            self.other_status.repaint()
            other_container = self.other_status.parent()
            if other_container and hasattr(other_container, 'setStyleSheet'):
                other_container.setStyleSheet(self._device_card_style(is_connected))
                other_container.update()
        
        # Force application to process events immediately
        from PyQt6.QtCore import QCoreApplication
        QCoreApplication.processEvents()
        
        # Log the status change
        status_str = "connected" if is_connected else "disconnected"
        if hasattr(self, 'logger'):
            self.logger.log(f"Serial Sensors {status_str}", "INFO")

    @pyqtSlot(int)
    def handle_graph_live_update_toggle(self, state):
        """Handles the live update checkbox toggle on the graph tab."""
        is_checked = (state == Qt.CheckState.Checked.value) # Convert int state to boolean
        print(f"DEBUG: Graph live update toggled: {is_checked} (state={state})")
        
        # Only control graph updates without affecting data collection
        if hasattr(self, 'graph_controller'):
            # Call the correct start/stop methods for the MAIN graph live update
            if is_checked:
                print("DEBUG: Starting main graph live update...")
                # Check if data collection is active before starting
                if hasattr(self, 'data_collection_controller') and self.data_collection_controller.collecting_data:
                    self.graph_controller.start_main_graph_live_update()
                else:
                    print("DEBUG: Data collection not active, not starting graph live update")
            else:
                print("DEBUG: Stopping main graph live update...")
                self.graph_controller.stop_main_graph_live_update()
        else:
            print("Warning: graph_controller not found when toggling live update.")

    def log(self, message, level="INFO"):
        """Log messages using the application logger"""
        if hasattr(self, 'logger'):
            self.logger.log(message, level)
        else:
            print(f"[{level}] {message}") # Fallback if logger not initialized

    def load_run_video(self, file_path):
        """Load a specified video file into the video player"""
        if not hasattr(self, 'video_player') or not hasattr(self, 'media_player'):
            self.log("Video player components not found.", "ERROR")
            QMessageBox.warning(self, "Error", "Video player not available in the UI.")
            return

        if not os.path.exists(file_path):
            self.log(f"Video file not found: {file_path}", "ERROR")
            QMessageBox.warning(self, "Error", f"Video file not found:\n{file_path}")
            return

        try:
            self.media_player.setSource(QUrl.fromLocalFile(file_path))
            # Ensure the Automation tab is selected to show the video player
            # Find the index for Automation tab
            automation_index = -1
            nav_button_names = [btn.text() for btn in self.nav_buttons]
            try:
                automation_index = nav_button_names.index("Automation")
            except ValueError:
                self.log("Automation tab not found in nav buttons.", "ERROR")
                QMessageBox.warning(self, "Error", "Could not switch to Automation tab to show video.")
                return

            if automation_index != -1:
                self.stacked_widget.setCurrentIndex(automation_index)
                self.nav_buttons[automation_index].setChecked(True) # Ensure button state matches

            self.log(f"Loaded video: {file_path}", "INFO")
            # Make sure audio is unmuted and at a sensible level
            if hasattr(self, "media_audio_output") and self.media_audio_output:
                try:
                    # Sync with saved UI state if available
                    vol = float(self.settings.value("media_volume", "100"))
                    vol = max(0.0, min(100.0, vol))
                    muted = str(self.settings.value("media_muted", "false")).lower() == "true"
                    self.media_audio_output.setVolume(vol / 100.0)
                    self.media_audio_output.setMuted(muted)
                    if hasattr(self, "video_volume_slider"):
                        self.video_volume_slider.blockSignals(True)
                        self.video_volume_slider.setValue(int(vol))
                        self.video_volume_slider.blockSignals(False)
                    if hasattr(self, "video_mute_checkbox"):
                        self.video_mute_checkbox.blockSignals(True)
                        self.video_mute_checkbox.setChecked(muted)
                        self.video_mute_checkbox.blockSignals(False)
                except Exception:
                    pass
            self.media_player.play() # Optionally start playing immediately

        except Exception as e:
            self.log(f"Error loading video '{file_path}': {e}", "ERROR")
            QMessageBox.critical(self, "Error", f"Could not load video:\n{e}")

    def load_virtual_sensors(self, is_startup_load=False):
        """Load virtual sensors and sequences from JSON file. Priority: current run dir > last run > data dir."""
        def get_last_run_virtual_sensors_path():
            try:
                # Try to load from settings.json (not QSettings)
                settings_path = os.path.join(os.getcwd(), "settings.json")
                if not os.path.exists(settings_path):
                    return None
                with open(settings_path, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                default_project_dir = settings.get("default_project_dir")
                last_project = settings.get("last_project")
                last_test_series = settings.get("last_test_series")
                if not (default_project_dir and last_project and last_test_series):
                    return None
                series_dir = os.path.join(default_project_dir, last_project, last_test_series)
                if not os.path.isdir(series_dir):
                    return None
                # Find newest run folder
                run_folders = [d for d in os.listdir(series_dir) if os.path.isdir(os.path.join(series_dir, d)) and d.lower().startswith("run_")]
                if not run_folders:
                    return None
                # Sort by timestamp in folder name (format: Run_YYYY-MM-DD_HH-MM-SS)
                def run_folder_key(name):
                    m = re.match(r"Run_(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})", name)
                    if not m:
                        return ""
                    return m.group(1) + "_" + m.group(2)
                run_folders.sort(key=run_folder_key, reverse=True)
                newest_run = run_folders[0]
                run_path = os.path.join(series_dir, newest_run)
                vs_path = os.path.join(run_path, VIRTUAL_SENSORS_FILENAME)
                if os.path.exists(vs_path):
                    return vs_path
                return None
            except Exception as e:
                if hasattr(self, 'logger'):
                    self.logger.log(f"Error finding last run's virtual_sensors.json: {e}", "ERROR")
                return None

        # Priority 1: Try to load from current run directory first
        current_run_path = self.get_virtual_sensors_path()
        if current_run_path != VIRTUAL_SENSORS_PATH and os.path.exists(current_run_path):
            try:
                with open(current_run_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.other_sensors = data.get("sensors", [])
                self.other_sequences = data.get("sequences", [])
                self.csv_configs = data.get("csv_configs", [])
                self.logger.log(f"Loaded virtual sensors from current run: {current_run_path}")
                self._apply_csv_configs()
                self._connect_virtual_sensors()
                
                # Invalidate the DCC sensor cache after loading to ensure new sensors are mapped correctly
                if hasattr(self, 'data_collection_controller'):
                    self.data_collection_controller.invalidate_sensor_cache()
                return
            except Exception as e:
                self.logger.log(f"Error loading virtual sensors from current run: {e}", "ERROR")

        # Priority 2: Try to load from newest run folder (only on first load)
        if is_startup_load:
            last_run_path = get_last_run_virtual_sensors_path()
            if last_run_path:
                try:
                    with open(last_run_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self.other_sensors = data.get("sensors", [])
                    self.other_sequences = data.get("sequences", [])
                    self.csv_configs = data.get("csv_configs", [])
                    self.logger.log(f"Loaded virtual sensors from last run: {last_run_path}")
                    self._apply_csv_configs()
                    self._connect_virtual_sensors()
                    
                    # Invalidate the DCC sensor cache after loading to ensure new sensors are mapped correctly
                    if hasattr(self, 'data_collection_controller'):
                        self.data_collection_controller.invalidate_sensor_cache()
                    return
                except Exception as e:
                    self.logger.log(f"Error loading virtual sensors from last run: {e}", "ERROR")

        # Priority 3: Fallback to current directory
        if os.path.exists(VIRTUAL_SENSORS_PATH):
            try:
                with open(VIRTUAL_SENSORS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                # Load and deduplicate sensors to prevent triplication
                loaded_sensors = data.get("sensors", [])
                seen_configs = set()
                unique_sensors = []
                for cfg in loaded_sensors:
                    config_id = (cfg.get('name'), cfg.get('type'))
                    if config_id not in seen_configs:
                        seen_configs.add(config_id)
                        unique_sensors.append(cfg)
                self.other_sensors = unique_sensors
                
                self.other_sequences = data.get("sequences", [])
                self.csv_configs = data.get("csv_configs", [])
                self.logger.log(f"Loaded {len(self.other_sensors)} virtual sensors from fallback location: {VIRTUAL_SENSORS_PATH}")
                self._apply_csv_configs()
                self._connect_virtual_sensors()
                
                # Invalidate the DCC sensor cache after loading to ensure new sensors are mapped correctly
                if hasattr(self, 'data_collection_controller'):
                    self.data_collection_controller.invalidate_sensor_cache()
            except Exception as e:
                self.logger.log(f"Error loading virtual sensors from fallback location: {e}", "ERROR")
                self.other_sensors = []
                self.other_sequences = []
                self.csv_configs = []
        else:
            # No virtual sensors file found anywhere
            self.other_sensors = []
            self.other_sequences = []
            self.csv_configs = []
            self.logger.log("No virtual sensors file found, starting with empty configuration")

    def _connect_virtual_sensors(self):
        """Connect to virtual sensors based on configured sequences and plugins.
        Following the blueprint for interface discovery and persistence.
        """
        def _as_bool(val, default: bool = False) -> bool:
            """Normalize config values that may come from JSON/QSettings into a real bool."""
            if val is None:
                return default
            if isinstance(val, bool):
                return val
            if isinstance(val, (int, float)):
                return bool(val)
            if isinstance(val, str):
                v = val.strip().lower()
                if v in ("1", "true", "yes", "y", "on", "checked"):
                    return True
                if v in ("0", "false", "no", "n", "off", "unchecked", ""):
                    return False
                # Unknown string -> fall back to default (NOT truthiness)
                return default
            return default

        success = False
        if not hasattr(self, 'other_sensors') or not self.other_sensors:
            return False
            
        for config in self.other_sensors:
            # 1. Handle legacy Serial/Sequence sensors (which use 'mapping' with a colon)
            if config.get("mapping") and ":" in config.get("mapping", ""):
                seq_name, var_name = config.get("mapping").split(":", 1)
                # Find the sequence by name
                for sequence in getattr(self, "other_sequences", []):
                    if sequence.get("name") == seq_name:
                        # Connect the sequence if it has a port
                        port = sequence.get("port", "")
                        if not port:
                            print(f"DEBUG MainWindow: Sequence {seq_name} has no port, cannot connect.")
                            continue

                        # Check if this port is already managed or if we should skip due to manual disconnect
                        if hasattr(self, 'data_collection_controller'):
                            dcc = self.data_collection_controller
                            if dcc.other_serial_manually_disconnected:
                                print(f"DEBUG MainWindow: Other serial manually disconnected, skipping auto-connect for sequence {seq_name} on port {port}")
                                if hasattr(self, 'logger'): self.logger.log(f"Skipping auto-connection of OtherSerial sequence {seq_name} - manually disconnected.", "INFO")
                                continue 

                        print(f"DEBUG MainWindow: Attempting to connect sequence {seq_name} on port {port}")
                        
                        # Pass False for is_explicit_reconnect if we are in an auto-connect scenario
                        # to respect the manual disconnect flag.
                        if self.sensor_controller.reinitialize_other_serial_connections(is_explicit_reconnect=False):
                            print(f"DEBUG MainWindow: Successfully reinitialized (or confirmed) connection for sequence {seq_name}")
                            if hasattr(self, 'logger'): self.logger.log(f"Virtual sensor for sequence {seq_name} (port {port}) connected.", "INFO")
                            success = True
                        else:
                            print(f"DEBUG MainWindow: Failed to reinitialize connection for sequence {seq_name} on port {port}")
                        break
            
            # 2. Handle generic plugins or newer unified sensor configs
            else:
                device_type = config.get("type")
                # 2a. Handle harmonized Serial sensors (type="Serial") with auto_connect=True
                if device_type in ("Serial", "OtherSerial"):
                    enabled = _as_bool(config.get("enabled", True), default=True)
                    # Serial/OtherSerial should default to True for auto_connect if enabled,
                    # because the actual connection is further filtered by sequence auto_connect flags.
                    auto_connect = _as_bool(config.get("auto_connect", True), default=True)
                    if not enabled or not auto_connect:
                        continue
                    if hasattr(self, 'data_collection_controller'):
                        dcc = self.data_collection_controller
                        if dcc.other_serial_manually_disconnected:
                            print("DEBUG MainWindow: Other serial manually disconnected, skipping auto-connect for Serial sensors")
                            continue
                    try:
                        if hasattr(self, 'sensor_controller'):
                            print("DEBUG MainWindow: Auto-connecting Serial sensors via reinitialize_other_serial_connections()")
                            if self.sensor_controller.reinitialize_other_serial_connections(is_explicit_reconnect=False):
                                success = True
                    except Exception as e:
                        if hasattr(self, 'logger'):
                            self.logger.log(f"Error auto-connecting Serial sensors: {e}", "ERROR")
                # 2b. Handle plugins
                elif device_type and device_type not in ["Arduino", "LabJack", "Serial", "Read CSV", "OtherSerial"]:
                    # This is likely a plugin sensor
                    if hasattr(self, 'data_collection_controller'):
                        # Check if it's a known plugin
                        from app.core.interfaces.interface_registry import InterfaceRegistry
                        if InterfaceRegistry.get_interface_class(device_type):
                            enabled = _as_bool(config.get("enabled", True), default=True)
                            auto_connect = _as_bool(config.get("auto_connect", False), default=False)

                            # --- Robust Auto-connect Check (Harmonized) ---
                            # For plugin/virtual sensors, we check BOTH the individual config 
                            # AND the global QSettings for this interface type.
                            settings_key = device_type.lower().replace(" ", "_")
                            global_auto_connect = self.settings.value(f"{settings_key}_auto_connect", "false") == "true"
                            global_enabled = self.settings.value(f"{settings_key}_enabled", "true") == "true"
                            
                            # Global settings take precedence for interface-wide behavior
                            auto_connect = auto_connect or global_auto_connect
                            enabled = enabled and global_enabled

                            if not enabled:
                                print(f"DEBUG MainWindow: Skipping plugin sensor '{config.get('name')}' because enabled is False")
                                continue
                            if not auto_connect:
                                print(f"DEBUG MainWindow: Skipping auto-connect for plugin sensor '{config.get('name')}' because auto_connect is False")
                                continue
                                
                            print(f"DEBUG MainWindow: Auto-connecting plugin sensor '{config.get('name')}' of type '{device_type}'")
                            # Call add_sensor_from_config but don't re-persist since we are loading it
                            if self.data_collection_controller.add_sensor_from_config(config, persist=False):
                                success = True
        
        return success

    def save_virtual_sensors(self):
        """Save virtual sensors and sequences to JSON file."""
        # 1. Determine current run-specific path
        path = self.get_virtual_sensors_path()
        
        # Data to save
        save_data = {
            "sensors": self.other_sensors, 
            "sequences": getattr(self, "other_sequences", []),
            "csv_configs": getattr(self, "csv_configs", [])
        }
        
        # 2. Always save to the fallback/root path first to ensure persistence across restarts
        try:
            with open(VIRTUAL_SENSORS_PATH, "w", encoding="utf-8") as f:
                json.dump(save_data, f, indent=2)
            self.logger.log(f"Saved virtual sensors to root: {VIRTUAL_SENSORS_PATH}")
        except Exception as e:
            self.logger.log(f"Error saving virtual sensors to root: {e}", "ERROR")

        # 3. If we are in a run directory, also save there for run-specific documentation
        if path != VIRTUAL_SENSORS_PATH:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(save_data, f, indent=2)
                self.logger.log(f"Saved virtual sensors to run dir: {path}")
            except Exception as e:
                self.logger.log(f"Error saving virtual sensors to run dir: {e}", "ERROR")

    def get_virtual_sensors_path(self):
        """Return the path to the virtual_sensors.json file (run dir if active, else current dir)."""
        run_dir = self.get_current_run_dir()
        if run_dir and os.path.isdir(run_dir):
            return os.path.join(run_dir, VIRTUAL_SENSORS_FILENAME)
        return VIRTUAL_SENSORS_PATH

    def move_virtual_sensors_to_run(self):
        """Move virtual_sensors.json to the run directory if a run is active."""
        run_dir = self.get_current_run_dir()
        if run_dir and os.path.isdir(run_dir):
            src = VIRTUAL_SENSORS_PATH
            dst = os.path.join(run_dir, VIRTUAL_SENSORS_FILENAME)
            if os.path.exists(src):
                try:
                    import shutil
                    shutil.move(src, dst)
                    self.logger.log(f"Moved virtual sensors config to run dir: {dst}")
                except Exception as e:
                    self.logger.log(f"Error moving virtual sensors config: {e}", "ERROR")

    def get_current_run_dir(self):
        """Get the current run directory from the project controller"""
        if hasattr(self, 'project_controller'):
            return self.project_controller.get_current_run_directory()
        return None

    # ---------------- Replay helpers ----------------
    def _init_replay_ui(self):
        """Initialize default UI state for replay controls."""
        # Reset replay state
        self.replay_mode_enabled = False
        self.replay_is_playing = False
        self.replay_video_offset = None
        self.replay_video_duration = 0.0
        self.replay_video_segments = []
        self.replay_active_video_path = None
        self.replay_data_duration = 0.0
        self.automation_replay_active = False
        self.replay_automation_events = []
        self.replay_automation_events_by_seq = {}
        
        # Clear snapshots
        if hasattr(self, "load_snapshots_for_run"):
            self.load_snapshots_for_run(None)
            
        if hasattr(self, "dashboard_automation_table"):
            try:
                self.dashboard_automation_table.setRowCount(0)
            except Exception:
                pass
        if hasattr(self, "replay_time_label"):
            self.replay_time_label.setText("00:00.0 / 00:00.0")
        for slider_name in ["replay_coarse"]:
            slider = getattr(self, slider_name, None)
            if slider:
                slider.blockSignals(True)
                slider.setValue(0)
                slider.blockSignals(False)
                slider.setEnabled(False)
        if hasattr(self, "replay_play_btn"):
            self.replay_play_btn.setText("Play")
            self.replay_play_btn.setChecked(False)
            self.replay_play_btn.setEnabled(False)

        # Default to live camera preview visible
        self._toggle_replay_video_surface(False)
        self._set_media_controls_enabled(True)
        if hasattr(self, "media_player"):
            try:
                self.media_player.pause()
            except Exception:
                pass
        
        self.update_run_context_text()

    def _toggle_replay_video_surface(self, show_video: bool):
        """Swap dashboard camera preview between live labels and replay video widgets."""
        if hasattr(self, "dashboard_camera_labels"):
            for i, lbl in enumerate(self.dashboard_camera_labels):
                if not show_video:
                    # Show live label if checkbox is checked
                    if hasattr(self, 'dashboard_camera_checkboxes'):
                        is_on = self.dashboard_camera_checkboxes[i].isChecked()
                        lbl.setVisible(is_on)
                else:
                    lbl.hide()
                    
        if hasattr(self, "dashboard_video_widgets"):
            for i, vw in enumerate(self.dashboard_video_widgets):
                if show_video:
                    # Show video widget if it has an active path
                    is_active = self.replay_active_video_paths[i] is not None
                    vw.setVisible(is_active)
                else:
                    vw.hide()
        
        self._update_row_visibilities()

    def _clear_replay_video_slot(self, slot_idx: int):
        """Clear a specific replay video slot."""
        if slot_idx < len(self.media_players):
            try:
                self.media_players[slot_idx].stop()
                self.media_players[slot_idx].setSource(QUrl())
            except Exception: pass
            
            self.replay_active_video_paths[slot_idx] = None
            if hasattr(self, "dashboard_video_widgets") and slot_idx < len(self.dashboard_video_widgets):
                self.dashboard_video_widgets[slot_idx].hide()

            # If we're still in replay mode, we might want to show the label again
            if getattr(self, "replay_mode_enabled", False):
                if hasattr(self, "dashboard_camera_labels") and slot_idx < len(self.dashboard_camera_labels):
                    # ONLY show if checkbox is checked AND not connected to live camera
                    is_checked = False
                    if hasattr(self, 'dashboard_camera_checkboxes'):
                        is_checked = self.dashboard_camera_checkboxes[slot_idx].isChecked()
                    
                    camera_active = False
                    if hasattr(self, 'camera_controller') and self.camera_controller:
                        camera_active = self.camera_controller.is_connected[slot_idx]
                        
                    if is_checked and not camera_active:
                        lbl = self.dashboard_camera_labels[slot_idx]
                        lbl.show()
                        lbl.setText("No video available")
                        from PyQt6.QtGui import QPixmap
                        lbl.setPixmap(QPixmap())
                    else:
                        if hasattr(self, "dashboard_camera_labels") and slot_idx < len(self.dashboard_camera_labels):
                            self.dashboard_camera_labels[slot_idx].hide()
            
            self._update_row_visibilities()

    def _clear_replay_video(self):
        """Clear all current replay videos from the dashboard players."""
        try:
            for i in range(len(self.media_players)):
                self._clear_replay_video_slot(i)
            self.replay_active_video_path = None
            self.replay_active_video_paths = [None] * 4
        except Exception as e:
            if hasattr(self, "logger"):
                self.logger.log(f"Error clearing replay video: {e}", "WARN")

    def _select_replay_segment_for_time(self, rel_time: float, force_load: bool = False):
        """Choose the correct video segments for all cameras for the given replay time and load them if needed."""
        if not getattr(self, "replay_video_segments", None):
            # No segments available - clear video display
            self._clear_replay_video()
            return

        try:
            rel_time = float(rel_time)
        except (TypeError, ValueError):
            rel_time = 0.0

        # Group segments by camera_index
        cameras_segments = {}
        for seg in self.replay_video_segments:
            cam_idx = seg.get("camera_index", 0)
            if cam_idx not in cameras_segments:
                cameras_segments[cam_idx] = []
            cameras_segments[cam_idx].append(seg)

        # For each camera, find the best segment for the current time
        chosen_segments = {}
        for cam_idx, segments in cameras_segments.items():
            # Sort by start_rel DESCENDING so we check the latest segments first if there are overlaps
            segments = sorted(segments, key=lambda s: float(s.get("start_rel", 0.0)), reverse=True)
            chosen = None
            for seg in segments:
                try:
                    start_rel = float(seg.get("start_rel", 0.0) or 0.0)
                    end_rel = seg.get("end_rel")
                    
                    if end_rel is not None:
                        end_rel = float(end_rel)
                        if start_rel <= rel_time <= end_rel:
                            chosen = seg
                            break
                    elif rel_time >= start_rel:
                        # If no end_rel, it matches anything after start_rel
                        # Since we are checking DESCENDING start_rel, this is the most recent segment that started before rel_time
                        chosen = seg
                        break
                except (TypeError, ValueError):
                    continue
            
            if chosen:
                chosen_segments[cam_idx] = chosen

        # Update each slot
        for cam_idx in range(4):
            chosen = chosen_segments.get(cam_idx)
            current_path = self.replay_active_video_paths[cam_idx]
            chosen_path = chosen.get("path") if chosen else None
            
            if not chosen:
                self._clear_replay_video_slot(cam_idx)
                continue
                
            if (
                not force_load
                and current_path
                and chosen_path
                and os.path.abspath(current_path) == os.path.abspath(chosen_path)
            ):
                self.replay_video_offsets[cam_idx] = float(chosen.get("start_rel", 0.0) or 0.0)
                continue

            self._activate_replay_segment_in_slot(chosen, cam_idx, seek_rel_time=rel_time)

    def _activate_replay_segment_in_slot(self, segment: dict, slot_idx: int, seek_rel_time: float | None = None):
        """Load a specific video segment into a specific media player slot and seek to the desired time."""
        if slot_idx >= len(self.media_players):
            return

        player = self.media_players[slot_idx]
        
        path = segment.get("path")
        if not path or not os.path.exists(path):
            self._clear_replay_video_slot(slot_idx)
            return

        try:
            self.replay_active_video_paths[slot_idx] = path
            # Compatibility attribute update
            if slot_idx == 0: self.replay_active_video_path = path
            
            self.replay_video_offsets[slot_idx] = float(segment.get("start_rel", 0.0) or 0.0)
            
            # Ensure audio output
            self._ensure_media_audio_output()
            
            # Video output is already linked in __init__ for dashboard_video_widgets
            # But let's re-verify it to be sure (some backends need this "bump")
            if hasattr(self, "dashboard_video_widgets") and slot_idx < len(self.dashboard_video_widgets):
                vw = self.dashboard_video_widgets[slot_idx]
                player.setVideoOutput(vw)
            
            player.setSource(QUrl.fromLocalFile(path))
            
            # Show the video widget and hide the camera label
            if hasattr(self, "dashboard_video_widgets") and slot_idx < len(self.dashboard_video_widgets):
                # Ensure the widget is properly initialized
                self.dashboard_video_widgets[slot_idx].show()
                self.dashboard_video_widgets[slot_idx].update()
                self.dashboard_video_widgets[slot_idx].repaint()

            if hasattr(self, "dashboard_camera_labels") and slot_idx < len(self.dashboard_camera_labels):
                self.dashboard_camera_labels[slot_idx].hide()
            
            self._update_row_visibilities()

            self._set_media_playback_rate()
            self._apply_media_audio_state()

            # Seek to the requested replay time within this segment
            if seek_rel_time is None:
                seek_rel_time = self.replay_current_time
            self._sync_replay_video_slot(slot_idx, seek_rel_time, force_seek=True)

            # Handle playback state
            if getattr(self, "replay_is_playing", False):
                player.play()
            else:
                # To avoid black frames on start, we play briefly then pause.
                # Hardware accelerated videos might need a bit more "encouragement" to show the first frame.
                player.play()
                
                # We use a sequence of pauses to ensure it sticks after the first frame is rendered
                def ensure_pause(p=player, attempt=1):
                    if not getattr(self, "replay_is_playing", False):
                        p.pause()
                        # For hardware videos, sometimes seeking to 1ms forces a render
                        if attempt == 1:
                            p.setPosition(1)
                        elif attempt == 2:
                            # Re-sync to actual requested time
                            self._sync_replay_video_slot(slot_idx, seek_rel_time, force_seek=True)
                        
                        # If it's still not LoadedMedia, we might need to check again later
                        if attempt < 4:
                            QTimer.singleShot(200, lambda: ensure_pause(p, attempt + 1))
                
                QTimer.singleShot(200, ensure_pause)

        except Exception as e:
            self.logger.log(f"Could not load replay video for slot {slot_idx+1}: {e}", "WARN")

    def _activate_replay_segment(self, segment: dict, seek_rel_time: float | None = None):
        """Compatibility wrapper: Load a specific video segment into slot 0."""
        self._activate_replay_segment_in_slot(segment, 0, seek_rel_time)

    def _set_media_controls_enabled(self, enabled: bool):
        """Enable/disable all media volume/mute controls."""
        for widget_name in [
            "video_volume_slider",
            "video_mute_checkbox",
            "camera_volume_slider",
            "camera_mute_checkbox",
            "dashboard_volume_slider",
            "dashboard_mute_checkbox",
        ]:
            widget = getattr(self, widget_name, None)
            if widget:
                try:
                    widget.setEnabled(enabled)
                except Exception:
                    pass

    def _refresh_media_duration(self):
        """Fetch current media duration from all active slots and apply the longest to replay timeline."""
        try:
            if not hasattr(self, "media_players"):
                return
            max_dur_ms = 0
            for player in self.media_players:
                try:
                    dur = player.duration()
                    if dur > max_dur_ms:
                        max_dur_ms = dur
                except Exception:
                    pass
            if max_dur_ms > 0:
                self._on_media_duration_changed(max_dur_ms)
        except Exception:
            pass

    def _on_media_duration_changed(self, duration_ms: int):
        """
        Track media duration so replay timeline covers the full video length.
        Useful when the video outlasts the recorded data.
        """
        try:
            dur_s = max(0.0, float(duration_ms) / 1000.0)
            self.replay_video_duration = dur_s
            if self.replay_mode_enabled:
                # Recalculate total duration based on data duration and video duration
                # This ensures the duration updates correctly when a shorter video is loaded after a longer one
                new_total = max(self.replay_data_duration, dur_s)
                if abs(new_total - self.replay_duration) > 0.05: # Only if change is significant
                    self.replay_duration = new_total
                    # Keep current time within bounds
                    self.replay_current_time = min(self.replay_current_time, self.replay_duration)
                    
                    # Update labels and sliders directly instead of full frame sync to avoid loops
                    if hasattr(self, "replay_time_label"):
                        self.replay_time_label.setText(f"{self._format_time(self.replay_current_time)} / {self._format_time(self.replay_duration)}")
                    
                    for slider_name in ["replay_coarse"]:
                        slider = getattr(self, slider_name, None)
                        if slider and slider.maximum() > 0:
                            slider.blockSignals(True)
                            slider.setValue(int((self.replay_current_time / self.replay_duration) * slider.maximum()))
                            slider.blockSignals(False)
                # If playback was stopped only because we hit a too-short duration, resume
                if getattr(self, "replay_is_playing", False) and hasattr(self, "replay_timer") and not self.replay_timer.isActive():
                    try:
                        self.replay_timer.start()
                    except Exception:
                        pass
        except Exception as e:
            try:
                if hasattr(self, "logger"):
                    self.logger.log(f"Failed to handle media duration change: {e}", "WARN")
            except Exception:
                pass

    def _on_media_error(self, error, error_str, slot_idx):
        """Log media errors for debugging."""
        try:
            self.logger.log(f"Media error in slot {slot_idx+1}: {error_str} (code: {error})", "ERROR")
        except:
            print(f"Media error in slot {slot_idx+1}: {error_str} (code: {error})")

    def _on_media_status_changed(self, status):
        """
        Media status callback to refresh duration once media is buffered/loaded.
        """
        try:
            from PyQt6.QtMultimedia import QMediaPlayer
            
            # Identify which player triggered the status change
            sender = self.sender()
            slot_idx = -1
            if hasattr(self, "media_players"):
                try:
                    slot_idx = self.media_players.index(sender)
                except ValueError: pass

            if status in (
                QMediaPlayer.MediaStatus.BufferedMedia,
                QMediaPlayer.MediaStatus.LoadedMedia,
                QMediaPlayer.MediaStatus.Buffered,
                QMediaPlayer.MediaStatus.Loaded,
                QMediaPlayer.MediaStatus.StalledMedia,
            ):
                self._refresh_media_duration()
                # Apply playback rate again when media is loaded, as some backends reset it
                self._set_media_playback_rate()
                
                # If we are in replay mode, force a sync for this slot or all slots
                if getattr(self, "replay_mode_enabled", False):
                    try:
                        if slot_idx != -1:
                            self._sync_replay_video_slot(slot_idx, self.replay_current_time, force_seek=True)
                        else:
                            self._sync_replay_video(self.replay_current_time, force_seek=True)
                    except Exception:
                        pass
        except Exception:
            pass

    def _current_media_duration_seconds(self) -> float:
        """Return current media duration in seconds if available."""
        try:
            if hasattr(self, "media_player"):
                dur_ms = self.media_player.duration()
                if dur_ms and dur_ms > 0:
                    return float(dur_ms) / 1000.0
        except Exception:
            pass
        return 0.0

    def _compute_replay_total(self, candidate_time: float = None) -> float:
        """
        Determine the total replay span combining data and video durations.

        If the video duration is not yet known, allow the candidate_time (e.g.,
        an upcoming playhead position) to extend the provisional total so we
        don't prematurely clamp or stop playback while metadata is still loading.
        """
        media_dur = self._current_media_duration_seconds()
        if media_dur > 0 and media_dur > self.replay_video_duration:
            self.replay_video_duration = media_dur

        effective_total = max(
            self.replay_data_duration or 0.0,
            self.replay_duration,
            self.replay_video_duration or 0.0,
            media_dur,
        )

        # If we still do not know the media duration, keep the total at least as
        # large as the requested playhead to avoid early stops.
        if candidate_time is not None and self.replay_video_duration == 0.0 and media_dur == 0.0:
            effective_total = max(effective_total, candidate_time)

        if effective_total != self.replay_duration:
            self.replay_duration = effective_total

        return effective_total

    def _ensure_media_audio_output(self):
        """
        Ensure QAudioOutputs are attached to all media players.
        """
        try:
            if not hasattr(self, "media_audio_outputs") or not self.media_audio_outputs:
                self.media_audio_outputs = [None] * 4
                
            from PyQt6.QtMultimedia import QMediaDevices
            default_device = QMediaDevices.defaultAudioOutput()
            
            for i in range(4):
                if self.media_audio_outputs[i] is None:
                    output = QAudioOutput()
                    if default_device:
                        output.setDevice(default_device)
                    self.media_audio_outputs[i] = output
                    
                    if i < len(self.media_players):
                        self.media_players[i].setAudioOutput(output)
            
            # Compatibility
            self.media_audio_output = self.media_audio_outputs[0]
            
            return True
        except Exception as e:
            try:
                if hasattr(self, "logger"):
                    self.logger.log(f"Failed to create media audio outputs: {e}", "WARN")
            except Exception:
                pass
            return False

    def _set_media_playback_rate(self):
        """Apply the current replay speed to all media players."""
        if not hasattr(self, "media_players"):
            return
        try:
            rate = float(getattr(self, "replay_speed_factor", 1.0))
            for player in self.media_players:
                try:
                    player.setPlaybackRate(rate)
                except Exception:
                    pass
        except Exception:
            pass

    def _set_dashboard_header(self, text: str):
        """Set the dashboard header label if it exists."""
        if hasattr(self, "dashboard_header_label"):
            self.dashboard_header_label.setText(text)

    def _update_dashboard_header_for_run(self, run_dir=None, mode_label: str = "Dashboard"):
        """Update dashboard header with project/series/run context."""
        if not hasattr(self, "project_controller"):
            self._set_dashboard_header(mode_label)
            return

        project = getattr(self.project_controller, "current_project", "") or ""
        series = getattr(self.project_controller, "current_test_series", "") or ""
        run_name = getattr(self.project_controller, "current_run", "") or ""

        # Derive names from run_dir if missing
        if run_dir and os.path.isdir(run_dir):
            if not run_name:
                run_name = os.path.basename(run_dir)
            if not series:
                series = os.path.basename(os.path.dirname(run_dir))
            if not project:
                project = os.path.basename(os.path.dirname(os.path.dirname(run_dir)))

        parts = [p for p in [project, series, run_name] if p]
        header = mode_label if not parts else f"{mode_label}: " + " / ".join(parts)
        self._set_dashboard_header(header)

    def _format_time(self, seconds: float) -> str:
        """Return mm:ss.t representation."""
        seconds = max(0.0, float(seconds))
        m, s = divmod(seconds, 60)
        return f"{int(m):02d}:{s:04.1f}"

    def on_replay_load_clicked(self):
        """Load replay data from the current run directory."""
        # Clear any previous replay automation overlay
        self.automation_replay_active = False
        self.replay_automation_events = []
        self.replay_automation_events_by_seq = {}
        
        # Clear snapshots immediately
        if hasattr(self, "load_snapshots_for_run"):
            self.load_snapshots_for_run(None)
            
        if hasattr(self, 'dash_events_list'):
            self.dash_events_list.clear()
        run_dir = None
        if hasattr(self, "project_controller"):
            run_dir = self.project_controller.get_current_run_directory()
        if not run_dir:
            self.logger.log("No run directory selected for replay.", "WARN")
            return

        if not hasattr(self, "data_replay_controller"):
            self.logger.log("Data replay controller not available.", "ERROR")
            return

        if not self.data_replay_controller.load_run(run_dir):
            self.logger.log("Failed to load replay data.", "ERROR")
            return

        # Prepare automation replay data for the dashboard status table
        self.automation_replay_active = True
        self.replay_mode_enabled = True
        self._prepare_replay_automation_events()

        # Load snapshots for the run (after automation events prepped, in case we need start_ts)
        self.load_snapshots_for_run(run_dir)

        # Prepare graph for replay plotting
        if hasattr(self, "graph_controller"):
            start_ts = getattr(self.data_replay_controller, "start_ts", None) or time.time()
            self.graph_controller.start_live_dashboard_update(start_ts)
            try:
                self.graph_controller.load_replay_dataset(
                    getattr(self.data_replay_controller, "rows", []),
                    getattr(self.data_replay_controller, "automation_columns", []),
                )
            except Exception as e:
                self.logger.log(f"Replay dataset load failed: {e}", "WARN")

        # Reset video duration before calculating total duration to avoid using old video duration
        self.replay_video_duration = 0.0
        
        # Duration setup
        _, end_rel = self.data_replay_controller.get_time_bounds()
        self.replay_data_duration = end_rel
        self.replay_duration = end_rel
        self.replay_current_time = 0.0
        self.last_sync_snapshot_index = -1
        self.replay_is_playing = False
        self.replay_timer.stop()
        self._set_media_controls_enabled(True)
        # Update dashboard header to reflect review context
        self._update_dashboard_header_for_run(run_dir, mode_label="Review")
        run_label = ""
        if hasattr(self, "project_controller"):
            run_label = getattr(self.project_controller, "current_run", "") or ""
        if not run_label and run_dir:
            run_label = os.path.basename(run_dir)
        self.update_run_context_text("Showing the previous run", run_label)
        if hasattr(self, "replay_play_btn"):
            self.replay_play_btn.setEnabled(True)
            self.replay_play_btn.setChecked(False)
            self.replay_play_btn.setText("Play")

        for slider_name in ["replay_coarse"]:
            slider = getattr(self, slider_name, None)
            if slider:
                slider.blockSignals(True)
                slider.setValue(0)
                slider.setEnabled(True)
                slider.blockSignals(False)

        # Check if camera is active before loading replay video
        # We now allow loading replay video even if camera is active, as they are in separate widgets
        # and live labels are hidden anyway during replay.
        camera_active = False
        if hasattr(self, 'camera_controller') and self.camera_controller:
            camera_active = any(getattr(self.camera_controller, 'is_connected', [False]))
        
        # Load metadata and sync first frame
        self._load_replay_video_metadata(run_dir)
        self._update_replay_frame(0.0, update_sliders=True, force_video_seek=True)
        
        # Ensure audio UI is in sync after loading
        self._apply_media_audio_state()

    def _load_replay_video_metadata(self, run_dir):
        """Load video metadata (path, start/end) for replay syncing."""
        self.replay_video_offset = None
        self.replay_video_duration = 0.0
        self.replay_video_segments = []
        self.replay_active_video_path = None
        if not hasattr(self, "project_controller") or not hasattr(self, "data_replay_controller"):
            return
        meta = self.project_controller.get_run_metadata(run_dir) or {}
        data_start = getattr(self.data_replay_controller, "start_ts", None)

        # Build segment list from new schema or legacy fields
        videos = meta.get("videos") or []
        if not videos:
            # Legacy single-video fields
            videos = [
                {
                    "path": meta.get("video_path"),
                    "start_epoch": meta.get("video_start_epoch"),
                    "end_epoch": meta.get("video_end_epoch"),
                    "duration_sec": meta.get("video_duration_sec"),
                    "format": meta.get("video_format"),
                }
            ]

        segments = []
        for entry in videos:
            path = entry.get("path") or entry.get("video_path")
            if not path:
                continue
            
            # Ensure path is absolute for QMediaPlayer stability
            if not os.path.isabs(path) and run_dir:
                path = os.path.abspath(os.path.join(run_dir, path))

            if not os.path.exists(path):
                # If the absolute path is missing, try to find the same filename in the run directory
                candidate = os.path.join(run_dir, os.path.basename(path)) if run_dir else None
                if candidate and os.path.exists(candidate):
                    path = candidate
                else:
                    continue

            try:
                start_epoch = float(entry.get("start_epoch") or entry.get("video_start_epoch") or 0.0)
            except (TypeError, ValueError):
                start_epoch = 0.0

            end_epoch = entry.get("end_epoch") or entry.get("video_end_epoch")
            try:
                end_epoch_val = float(end_epoch) if end_epoch is not None else None
            except (TypeError, ValueError):
                end_epoch_val = None

            duration_val = entry.get("duration_sec") or entry.get("video_duration_sec")
            try:
                duration_val = float(duration_val) if duration_val is not None else None
            except (TypeError, ValueError):
                duration_val = None

            start_rel = (start_epoch - data_start) if data_start else 0.0
            end_rel = None
            if end_epoch_val is not None:
                end_rel = (end_epoch_val - data_start) if data_start else None
            elif duration_val is not None:
                end_rel = start_rel + duration_val

            segments.append(
                {
                    "path": path,
                    "camera_index": entry.get("camera_index", 0),
                    "start_epoch": start_epoch,
                    "end_epoch": end_epoch_val,
                    "duration_sec": duration_val,
                    "start_rel": start_rel,
                    "end_rel": end_rel,
                    "format": entry.get("format") or entry.get("video_format"),
                }
            )

        # Fallback to newest file in run dir if nothing found
        if not segments and run_dir and os.path.isdir(run_dir):
            import glob

            candidates = []
            for ext in ("*.mp4", "*.avi", "*.mkv", "*.mov"):
                candidates.extend(glob.glob(os.path.join(run_dir, ext)))
            if candidates:
                newest = max(candidates, key=os.path.getmtime)
                segments.append(
                    {
                        "path": newest,
                        "start_epoch": data_start or 0.0,
                        "end_epoch": None,
                        "duration_sec": None,
                        "start_rel": 0.0,
                        "end_rel": None,
                        "format": None,
                    }
                )

        # Sort and store segments
        segments = sorted(segments, key=lambda s: float(s.get("start_rel", 0.0) or 0.0))
        self.replay_video_segments = segments
        if segments:
            max_end = max(
                (
                    seg.get("end_rel")
                    if seg.get("end_rel") is not None
                    else float(seg.get("start_rel", 0.0) or 0.0)
                )
                for seg in segments
            )
            try:
                max_end = float(max_end)
            except (TypeError, ValueError):
                max_end = 0.0
            self.replay_video_duration = max(self.replay_video_duration, max_end)
            # Ensure overall replay duration covers video span
            self.replay_duration = max(self.replay_duration, self.replay_video_duration)

        # Activate the correct segment for the current replay time
        self._select_replay_segment_for_time(self.replay_current_time, force_load=True)

    def on_replay_play_toggle(self):
        """Toggle play/pause for all synchronized replay slots."""
        if not self.replay_mode_enabled:
            self.on_replay_load_clicked()
            if not self.replay_mode_enabled:
                return
        self.replay_is_playing = not self.replay_is_playing
        # If duration is zero, stop immediately
        if self.replay_duration <= 0:
            self.replay_is_playing = False
            if hasattr(self, "replay_play_btn"):
                self.replay_play_btn.setText("Play")
                self.replay_play_btn.setChecked(False)
            return
        if self.replay_is_playing:
            # Refresh duration now that playback is starting
            self._refresh_media_duration()
            try:
                QTimer.singleShot(200, self._refresh_media_duration)
            except Exception:
                pass
            self.replay_last_tick = time.monotonic()
            self.replay_timer.start()
            if hasattr(self, "media_players"):
                self._set_media_playback_rate()
                # Ensure audio output is aligned with UI state
                self._apply_media_audio_state()
                
                for player in self.media_players:
                    try:
                        player.play()
                    except Exception:
                        pass
                # Re-apply playback rate after play starts
                self._set_media_playback_rate()
            if hasattr(self, "replay_play_btn"):
                self.replay_play_btn.setText("Pause")
                self.replay_play_btn.setChecked(True)
        else:
            self.replay_timer.stop()
            self.replay_last_tick = None
            if hasattr(self, "media_players"):
                for player in self.media_players:
                    try:
                        player.pause()
                    except Exception:
                        pass
            if hasattr(self, "replay_play_btn"):
                self.replay_play_btn.setText("Play")
                self.replay_play_btn.setChecked(False)

    def on_replay_speed_changed(self):
        """Update speed factor from dropdown."""
        if not hasattr(self, "replay_speed"):
            return
        text = self.replay_speed.currentText().replace("x", "")
        try:
            self.replay_speed_factor = float(text)
        except ValueError:
            self.replay_speed_factor = 1.0
        # Apply the rate immediately to media playback
        self._set_media_playback_rate()

    def on_replay_slider_changed(self):
        """Handle coarse/fine slider move to set replay position."""
        if not self.replay_mode_enabled or self.replay_duration <= 0:
            return
        sender = self.sender()
        if not sender:
            return
        max_val = sender.maximum()
        if max_val <= 0:
            return
        total = self._compute_replay_total()
        rel_time = (sender.value() / max_val) * total if total > 0 else 0.0
        self._update_replay_frame(rel_time, update_sliders=False, force_video_seek=True)

    def _tick_replay(self):
        """Advance replay clock while playing."""
        if not (self.replay_mode_enabled and self.replay_is_playing):
            return
        # Keep duration up to date in case media duration arrives late; avoid spamming once known
        if self.replay_video_duration <= 0.0:
            self._refresh_media_duration()
        now = time.monotonic()
        if self.replay_last_tick is None:
            self.replay_last_tick = now
        dt = (now - self.replay_last_tick) * self.replay_speed_factor
        self.replay_last_tick = now
        new_time = self.replay_current_time + dt
        media_dur = self._current_media_duration_seconds()
        
        # Check if any video slot is active
        has_video = any(p is not None for p in self.replay_active_video_paths) or (self.replay_video_duration > 0.0) or media_dur > 0.0
        
        effective_total = self._compute_replay_total(candidate_time=new_time)

        # Stop only when we know we're at the end (data-only replay or media reports duration/end)
        should_stop = False
        try:
            from PyQt6.QtMultimedia import QMediaPlayer
            
            # Check status of master player (slot 0)
            status = self.media_players[0].mediaStatus() if hasattr(self, "media_players") and self.media_players else None
            
            if new_time >= effective_total:
                if not has_video:
                    should_stop = True
                elif (
                    self.replay_video_duration > 0.0
                    or media_dur > 0.0
                    or status == QMediaPlayer.MediaStatus.EndOfMedia
                ):
                    should_stop = True
        except Exception:
            if new_time >= effective_total:
                should_stop = True

        if should_stop:
            new_time = effective_total
            self.replay_is_playing = False
            self.replay_timer.stop()
            if hasattr(self, "media_players"):
                for p in self.media_players:
                    p.pause()
            if hasattr(self, "replay_play_btn"):
                self.replay_play_btn.setText("Play")
                self.replay_play_btn.setChecked(False)
        self._update_replay_frame(new_time, update_sliders=True)

    def _update_replay_frame(self, rel_time: float, update_sliders: bool = True, force_video_seek: bool = False):
        """Set replay position, update graphs and video."""
        if getattr(self, "_is_syncing_replay_frame", False):
            return
        
        self._is_syncing_replay_frame = True
        try:
            effective_total = self._compute_replay_total(candidate_time=rel_time)
            rel_time = max(0.0, min(rel_time, effective_total))
            self.replay_current_time = rel_time

            if hasattr(self, "graph_controller"):
                # Ensure dashboard live plotting is active for replay data
                self.graph_controller.live_plotting_active = True
                try:
                    self.graph_controller.update_replay_position(rel_time)
                except Exception as e:
                    if hasattr(self, "logger"):
                        self.logger.log(f"Replay plot update error: {e}", "WARN")

            # Update simulated automation dashboard view based on replay timeline
            self._update_replay_automation_table(rel_time)

            # Update metrics and system events for replay
            if hasattr(self, "data_replay_controller"):
                row = self.data_replay_controller.get_row_at(rel_time)
                if row:
                    # Enrich the row with source tag so it passes the idle gating
                    row_data = self._row_to_data_dict(row)
                    self.update_dashboard_metrics(row_data)
            
            self._update_replay_events_list(rel_time)

            # Update snapshots based on replay time
            self._sync_snapshots_to_replay(rel_time)

            # Ensure the correct video segment is active for this timestamp
            self._select_replay_segment_for_time(rel_time)

            # Keep video position in sync with current replay time
            self._sync_replay_video(rel_time, force_seek=force_video_seek)

            if update_sliders and self.replay_duration > 0:
                for slider_name in ["replay_coarse"]:
                    slider = getattr(self, slider_name, None)
                    if slider and slider.maximum() > 0:
                        slider.blockSignals(True)
                        slider.setValue(int((rel_time / self.replay_duration) * slider.maximum()))
                        slider.blockSignals(False)

            if hasattr(self, "replay_time_label"):
                self.replay_time_label.setText(f"{self._format_time(rel_time)} / {self._format_time(self.replay_duration)}")
        finally:
            self._is_syncing_replay_frame = False

    def _row_to_data_dict(self, row: dict) -> dict:
        """Convert CSV row to the dict format expected by graph_controller."""
        data = {}
        timestamp = row.get("_timestamp")
        if timestamp is None and hasattr(self, "data_replay_controller"):
            timestamp = getattr(self.data_replay_controller, "start_ts", time.time()) + self.replay_current_time
        data["timestamp"] = timestamp
        # Mark this payload as replay data so live collection is ignored while reviewing
        data["_source"] = "replay"

        for key, val in row.items():
            if key in ("timestamp", "_timestamp", "_rel_time"):
                continue
            # Filter out all timestamp columns (arduino_timestamp, labjack_timestamp, etc.)
            if key.endswith("_timestamp"):
                continue
            if key in getattr(self.data_replay_controller, "automation_columns", []):
                # automation markers handled separately
                continue
            try:
                data[key] = float(val)
            except (TypeError, ValueError):
                data[key] = val
        return data

    def _maybe_add_replay_event(self, row: dict):
        """Add automation markers from replay rows to graphs."""
        if not hasattr(self, "graph_controller"):
            return
        has_marker = False
        event = {
            "timestamp": row.get("_timestamp", time.time()),
            "type": "replay_event",
            "sequence_name": "",
            "trigger_description": row.get("automation_trigger", ""),
            "action_description": row.get("automation_action", ""),
        }
        if row.get("automation_trigger") or row.get("automation_action") or row.get("automation_sequence"):
            event["sequence_name"] = row.get("automation_sequence", "")
            has_marker = True
        if has_marker:
            try:
                self.graph_controller.add_event_marker(event)
            except Exception:
                pass

    def _prepare_replay_automation_events(self):
        """Precompute automation events so the dashboard table can be simulated during replay."""
        self.replay_automation_events = []
        self.replay_automation_events_by_seq = {}

        if not hasattr(self, "data_replay_controller"):
            return

        rows = getattr(self.data_replay_controller, "rows", []) or []
        columns = getattr(self.data_replay_controller, "automation_columns", [])
        if not rows or not columns:
            return

        # Use a dictionary to deduplicate events by (rel_time, sequence, action) key
        # Round rel_time to nearest 0.1 seconds to handle floating point precision issues
        # This ensures events at the same time (within 0.1s) with the same sequence and action are deduplicated
        events_dict = {}

        for row in rows:
            if not any(row.get(col) for col in columns):
                continue

            try:
                rel_time = float(row.get("_rel_time", 0.0) or 0.0)
                # Round to nearest 0.1 seconds to handle floating point precision
                rel_time = round(rel_time, 1)
            except (TypeError, ValueError):
                rel_time = 0.0

            trigger_raw = str(row.get("automation_trigger", "") or "").strip()
            action_raw = str(row.get("automation_action", "") or "").strip()
            seq_raw = str(row.get("automation_sequence", "") or "").strip()
            
            # --- Smart Split Sequences ---
            # Sequence names can contain semicolons, but multiple sequences are also separated by semicolons.
            # We check against known sequences to avoid splitting a single sequence name.
            known_sequence_names = []
            if hasattr(self, 'automation_controller') and self.automation_controller.manager:
                known_sequence_names = [s.name for s in self.automation_controller.manager.sequences]
            
            if not seq_raw:
                sequences = ["Automation"]
            elif seq_raw in known_sequence_names:
                # Direct match for the whole string (even if it contains semicolons)
                sequences = [seq_raw]
            else:
                # Not a direct match, so we split by semicolon
                parts = [p.strip() for p in seq_raw.split(';') if p.strip()]
                sequences = []
                
                # Try to re-group parts that might belong to a single sequence name
                # Example: seq_raw="AIN2 >= 30; 31; 32; AnotherSeq" 
                # where "AIN2 >= 30; 31; 32" is one sequence and "AnotherSeq" is another.
                i = 0
                while i < len(parts):
                    matched = False
                    # Try longest possible combinations first
                    for j in range(len(parts), i, -1):
                        combined = "; ".join(parts[i:j])
                        if combined in known_sequence_names:
                            sequences.append(combined)
                            i = j
                            matched = True
                            break
                    
                    if not matched:
                        # Fallback: just add the single part if no match found
                        sequences.append(parts[i])
                        i += 1

            if not sequences:
                sequences = ["Automation"]

            # Skip events that only have trigger but no action (to match live behavior)
            # Only show events that have an action
            if not action_raw:
                continue

            # --- Smart Split Triggers/Actions ---
            # If multiple components are joined by semicolon, try to separate them
            trigger_parts = [t.strip() for t in trigger_raw.split(';') if t.strip()]
            action_parts = [a.strip() for a in action_raw.split(';') if a.strip()]
            
            # If we have multiple components, create separate events for each sequence/step pair.
            # The number of events is determined by the maximum number of components found.
            num_events = max(len(sequences), len(trigger_parts), len(action_parts))
            
            seen_in_row = set()
            for k in range(num_events):
                # Map parts to this event, cycling if necessary
                seq = sequences[k % len(sequences)] if sequences else "Automation"
                trig = trigger_parts[k % len(trigger_parts)] if trigger_parts else trigger_raw
                act = action_parts[k % len(action_parts)] if action_parts else action_raw
                
                # Deduplicate identical events within the same row (often caused by 
                # dashboard events being logged alongside automation events)
                if (seq, trig, act) in seen_in_row:
                    continue
                seen_in_row.add((seq, trig, act))
                
                # Add a tiny offset to rel_time for each subsequent event in the same row
                # to maintain order and allow the UI to step through them if they occurred in one logging interval
                offset_rel_time = rel_time + (k * 0.001)
                
                # Use a more unique key: (rel_time, sequence, action) to properly deduplicate
                # This ensures the same event (same time, sequence, and action) only appears once
                key = (round(offset_rel_time, 3), seq, act)
                
                # If we already have an event at this timestamp/sequence/action, prefer the one with both trigger and action
                if key in events_dict:
                    existing = events_dict[key]
                    # Prefer event with both trigger and action
                    if trig and act and (not existing["trigger"] or not existing["action"]):
                        events_dict[key] = {
                            "sequence": seq,
                            "trigger": trig,
                            "action": act,
                            "rel_time": offset_rel_time,
                        }
                else:
                    events_dict[key] = {
                        "sequence": seq,
                        "trigger": trig,
                        "action": act,
                        "rel_time": offset_rel_time,
                    }

        # Convert dictionary to list
        self.replay_automation_events = list(events_dict.values())
        
        # Group by sequence for the by_seq dictionary
        for event in self.replay_automation_events:
            seq = event["sequence"]
            self.replay_automation_events_by_seq.setdefault(seq, []).append(event)

        # Keep events sorted for quick lookup
        for seq in self.replay_automation_events_by_seq:
            self.replay_automation_events_by_seq[seq].sort(key=lambda e: e["rel_time"])
        self.replay_automation_events.sort(key=lambda e: e["rel_time"])

    def _update_replay_events_list(self, rel_time: float):
        """Update the system events list with events that happened up to rel_time."""
        if not hasattr(self, 'dash_events_list') or not hasattr(self, 'replay_automation_events'):
            return

        # Clear existing list
        self.dash_events_list.clear()

        # Find all events up to rel_time, sorted by rel_time descending (newest at top)
        past_events = [e for e in self.replay_automation_events if e.get('rel_time', 0.0) <= rel_time]
        past_events.sort(key=lambda e: e.get('rel_time', 0.0), reverse=True)

        # Deduplicate events by (rel_time, trigger, action) to ensure each unique event appears only once
        # Using a time-window approach to catch duplicates that might span across logging intervals
        unique_events = []
        last_event_info = None # (rel_time, trigger, action)
        
        for event in past_events:
            rel_t = event.get('rel_time', 0.0)
            trigger = str(event.get('trigger', '')).strip()
            action = str(event.get('action', '')).strip()
            
            is_duplicate = False
            if last_event_info:
                last_t, last_trig, last_act = last_event_info
                # If events are very close in time and have same content, they are likely duplicates
                # We use a 0.2s window to catch duplicates in adjacent rows (logging is usually 0.1s)
                if abs(rel_t - last_t) < 0.2 and trigger == last_trig and action == last_act:
                    is_duplicate = True
            
            if not is_duplicate:
                unique_events.append(event)
                last_event_info = (rel_t, trigger, action)

        # Show only last 50 unique events
        from PyQt6.QtWidgets import QListWidgetItem
        from PyQt6.QtGui import QColor
        for event in unique_events[:50]:
            # Use same format as add_dashboard_event
            rel_t = event.get('rel_time', 0.0)
            mins = int(rel_t // 60)
            secs = int(rel_t % 60)
            timestamp = f"{mins:02d}:{secs:02d}"
            
            trigger = event.get('trigger', '')
            action = event.get('action', '')
            
            message = ""
            if trigger and action:
                message = f"{trigger} -> {action}"
            else:
                message = action or trigger
                
            if not message:
                continue
                
            item_text = f"[{timestamp}] {message}"
            item = QListWidgetItem(item_text)
            item.setForeground(QColor(COLORS.TEXT_SECONDARY))
            self.dash_events_list.addItem(item)

    def _update_replay_automation_table(self, rel_time: float):
        """Update the Automation Status table using recorded replay events."""
        if not getattr(self, "automation_replay_active", False):
            return

        table = getattr(self, "dashboard_automation_table", None)
        if table is None:
            return

        events_by_seq = getattr(self, "replay_automation_events_by_seq", {}) or {}
        if not events_by_seq:
            table.setRowCount(1)
            table.setItem(0, 0, QTableWidgetItem("No automation events in replay"))
            for col in range(1, 5):
                table.setItem(0, col, QTableWidgetItem("-"))
            # REMOVED: table.resizeColumnsToContents() - prevents manual resizing
            table.viewport().update()
            return

        try:
            rel_time = float(rel_time)
        except (TypeError, ValueError):
            rel_time = 0.0

        sequences = sorted(events_by_seq.keys(), key=lambda s: s.lower())
        table.setRowCount(len(sequences))

        def _format_step(event) -> str:
            if not event:
                return "-"
            trigger = event.get("trigger", "")
            action = event.get("action", "")
            if trigger and action:
                return f"{trigger} -> {action}"
            return action or trigger or "-"

        for row_idx, seq in enumerate(sequences):
            seq_events = events_by_seq.get(seq, [])
            current = None
            upcoming = None
            for ev in seq_events:
                if ev.get("rel_time", 0.0) <= rel_time:
                    current = ev
                elif ev.get("rel_time", 0.0) > rel_time and upcoming is None:
                    upcoming = ev
                    break

            if current and upcoming:
                status = "Active"
            elif current and not upcoming:
                status = "Completed"
            elif upcoming and not current:
                status = "Upcoming"
            else:
                status = "Pending"

            table.setItem(row_idx, 0, QTableWidgetItem(seq or "Automation"))
            table.setItem(row_idx, 1, QTableWidgetItem(status))
            table.setItem(row_idx, 2, QTableWidgetItem(_format_step(current)))
            table.setItem(row_idx, 3, QTableWidgetItem(_format_step(upcoming)))

            time_text = "-"
            if current:
                time_text = self._format_time(current.get("rel_time", 0.0))
            elif upcoming:
                time_text = f"Next @ {self._format_time(upcoming.get('rel_time', 0.0))}"
            table.setItem(row_idx, 4, QTableWidgetItem(time_text))

        # REMOVED: table.resizeColumnsToContents() - prevents manual resizing
        table.viewport().update()
        self.update()

    def _sync_replay_video_slot(self, slot_idx: int, rel_time: float, force_seek: bool = False):
        """Seek a specific video slot to match replay timeline if metadata is available."""
        if slot_idx >= len(self.replay_video_offsets) or slot_idx >= len(self.media_players):
            return
            
        offset = self.replay_video_offsets[slot_idx]
        player = self.media_players[slot_idx]
        
        try:
            target_ms = max(0.0, (rel_time - offset) * 1000.0)
            current_ms = 0.0
            try:
                current_ms = float(player.position())
            except Exception:
                pass

            is_playing = bool(getattr(self, "replay_is_playing", False))
            drift_ms = abs(target_ms - current_ms)
            threshold_ms = getattr(self, "replay_video_drift_threshold_ms", 150)

            if is_playing and abs(getattr(self, "replay_speed_factor", 1.0) - 1.0) > 0.1:
                threshold_ms = max(threshold_ms, 500)

            should_seek = force_seek or not is_playing or (drift_ms > threshold_ms)

            if should_seek:
                player.setPosition(int(target_ms))
        except Exception:
            pass

    def _sync_replay_video(self, rel_time: float, force_seek: bool = False):
        """Seek all video slots to match replay timeline."""
        for i in range(len(self.media_players)):
            self._sync_replay_video_slot(i, rel_time, force_seek)

    def _apply_media_audio_state(self, source_widget=None):
        """Apply current UI/settings volume and mute to all media outputs."""
        if not hasattr(self, "media_players"):
            return
        try:
            # Recreate audio output if needed
            if not self._ensure_media_audio_output():
                return
                
            # Allow caller to specify the originating widget; fall back to sender
            if source_widget is None:
                try:
                    source_widget = self.sender()
                except Exception:
                    source_widget = None

            vol = None
            muted = None

            # Build ordered candidates for volume
            volume_candidates = []
            if isinstance(source_widget, QSlider):
                volume_candidates.append(source_widget)
            for name in ["camera_volume_slider", "dashboard_volume_slider", "video_volume_slider"]:
                widget = getattr(self, name, None)
                if widget and widget not in volume_candidates:
                    volume_candidates.append(widget)

            for widget in volume_candidates:
                try:
                    if widget is source_widget or widget.isVisible():
                        vol = float(widget.value())
                        break
                except Exception:
                    continue
            if vol is None:
                vol = float(self.settings.value("media_volume", "100"))
            vol = max(0.0, min(100.0, vol))

            # Build ordered candidates for mute
            mute_candidates = []
            if isinstance(source_widget, QCheckBox):
                mute_candidates.append(source_widget)
            for name in ["camera_mute_checkbox", "dashboard_mute_checkbox", "video_mute_checkbox"]:
                widget = getattr(self, name, None)
                if widget and widget not in mute_candidates:
                    mute_candidates.append(widget)

            for widget in mute_candidates:
                try:
                    if widget is source_widget or widget.isVisible():
                        muted = bool(widget.isChecked())
                        break
                except Exception:
                    continue
            if muted is None:
                muted = str(self.settings.value("media_muted", "false")).lower() == "true"

            # Apply to all audio outputs
            if hasattr(self, "media_audio_outputs"):
                for output in self.media_audio_outputs:
                    if output:
                        try:
                            output.setVolume(vol / 100.0)
                            output.setMuted(muted)
                        except Exception:
                            pass

            # Persist settings
            self.settings.setValue("media_volume", str(int(vol)))
            self.settings.setValue("media_muted", "true" if muted else "false")

            # Keep all UI sliders/checkboxes in sync
            for widget_name in ["video_volume_slider", "camera_volume_slider", "dashboard_volume_slider"]:
                widget = getattr(self, widget_name, None)
                if widget:
                    try:
                        widget.blockSignals(True)
                        widget.setValue(int(vol))
                        widget.blockSignals(False)
                    except Exception:
                        pass
            for widget_name in ["video_mute_checkbox", "camera_mute_checkbox", "dashboard_mute_checkbox"]:
                widget = getattr(self, widget_name, None)
                if widget:
                    try:
                        widget.blockSignals(True)
                        widget.setChecked(muted)
                        widget.blockSignals(False)
                    except Exception:
                        pass
        except Exception as e:
            print(f"Error applying media audio state: {e}")
            try:
                if hasattr(self, "logger"):
                    self.logger.log(f"Failed to apply media audio state: {e}", "WARN")
            except Exception:
                pass

    def on_video_volume_changed(self, value: int):
        """Handle volume slider changes."""
        try:
            # If user drags to >0, unmute checkbox for convenience
            if value > 0:
                for widget_name in ["video_mute_checkbox", "camera_mute_checkbox", "dashboard_mute_checkbox"]:
                    widget = getattr(self, widget_name, None)
                    if widget:
                        widget.blockSignals(True)
                        widget.setChecked(False)
                        widget.blockSignals(False)
            self._apply_media_audio_state(source_widget=self.sender())
        except Exception:
            pass

    def on_video_mute_toggled(self, checked: bool):
        """Handle mute checkbox toggles."""
        try:
            self._apply_media_audio_state(source_widget=self.sender())
        except Exception:
            pass
    
    def keyPressEvent(self, event):
        """Handle keyboard shortcuts"""
        from PyQt6.QtCore import Qt
        
        # Ctrl+Shift+D: Toggle Data Flow Monitor
        if (event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier) 
            and event.key() == Qt.Key.Key_D):
            self.toggle_data_flow_page()
            event.accept()
            return
        
        # Ctrl+Shift+T: Toggle Tools Window
        if (event.modifiers() == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier) 
            and event.key() == Qt.Key.Key_T):
            self.toggle_tools_window()
            event.accept()
            return
        
        # Escape: Return to previous page if on data flow page
        if event.key() == Qt.Key.Key_Escape:
            if hasattr(self, 'data_flow_page_index') and hasattr(self, '_previous_page_index'):
                if self.stacked_widget.currentIndex() == self.data_flow_page_index:
                    self.stacked_widget.setCurrentIndex(self._previous_page_index)
                    event.accept()
                    return
        
        # Call parent implementation
        super().keyPressEvent(event)
    
    def toggle_data_flow_page(self):
        """Toggle between data flow page and previous page"""
        if not hasattr(self, 'data_flow_page_index'):
            self.logger.log("Data flow page not available", "WARNING")
            return
        
        current_index = self.stacked_widget.currentIndex()
        
        if current_index == self.data_flow_page_index:
            # Return to previous page
            if hasattr(self, '_previous_page_index'):
                self.stacked_widget.setCurrentIndex(self._previous_page_index)
            else:
                self.stacked_widget.setCurrentIndex(0)  # Default to Projects
        else:
            # Store current page and switch to data flow
            self._previous_page_index = current_index
            self.stacked_widget.setCurrentIndex(self.data_flow_page_index)
            
            # Load any existing commands
            if hasattr(self, 'data_flow_widget'):
                self.data_flow_widget.load_existing_commands()
    
    def on_snapshot_taken(self, path):
        """Called when a snapshot is taken."""
        if not path:
            return

        # Check if the file exists (it should, as we now emit the signal after saving)
        if not os.path.exists(path):
            # If it doesn't exist yet, we might have a slight race condition or it failed to save
            if hasattr(self, 'logger'):
                self.logger.log(f"Snapshot path received but file not found: {path}", "WARNING")
        
        # Add to the list if not already there
        if path not in self.snapshot_paths:
            self.snapshot_paths.append(path)
            
            # Also update snapshot_data for consistency (used for replay sync)
            if not hasattr(self, 'snapshot_data'):
                self.snapshot_data = []
            
            # Estimate relative time from run start
            run_start_ts = 0.0
            if hasattr(self, 'data_replay_controller') and self.data_replay_controller.start_ts:
                run_start_ts = self.data_replay_controller.start_ts
            
            try:
                mtime = os.path.getmtime(path)
                rel_time = max(0.0, mtime - run_start_ts) if run_start_ts > 0 else 0.0
            except:
                rel_time = 0.0
                
            self.snapshot_data.append({"path": path, "rel_time": rel_time})
            
        # Update the current index to show this snapshot and refresh display
        self.current_snapshot_index = self.snapshot_paths.index(path)
        self._update_snapshot_display()
            
        if hasattr(self, 'logger'):
            self.logger.log(f"Dashboard updated with snapshot: {os.path.basename(path)}", "DEBUG")

    def load_snapshots_for_run(self, run_dir):
        """Load all snapshots from the run directory's Snapshots subfolder."""
        if not run_dir or not os.path.exists(run_dir):
            self.snapshot_paths = []
            self.snapshot_data = []
            self.current_snapshot_index = -1
            self.last_sync_snapshot_index = -1
            self._update_snapshot_display()
            return

        snapshots_dir = os.path.join(run_dir, "Snapshots")
        if not os.path.exists(snapshots_dir):
            self.snapshot_paths = []
            self.snapshot_data = []
            self.current_snapshot_index = -1
            self.last_sync_snapshot_index = -1
            self._update_snapshot_display()
            return

        # Get run start time for relative sync
        run_start_ts = 0.0
        if hasattr(self, 'data_replay_controller') and self.data_replay_controller.start_ts:
            run_start_ts = self.data_replay_controller.start_ts

        # Get all png and jpg files
        try:
            files_data = []
            for f in os.listdir(snapshots_dir):
                if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                    path = os.path.join(snapshots_dir, f)
                    mtime = os.path.getmtime(path)
                    # Estimate relative time from run start
                    rel_time = max(0.0, mtime - run_start_ts) if run_start_ts > 0 else 0.0
                    files_data.append({"path": path, "rel_time": rel_time})
            
            # Sort by relative time (chronological)
            files_data.sort(key=lambda x: x["rel_time"])
            self.snapshot_data = files_data
            self.snapshot_paths = [x["path"] for x in files_data]
            
            if self.snapshot_paths:
                self.current_snapshot_index = len(self.snapshot_paths) - 1 # Show latest by default
            else:
                self.current_snapshot_index = -1
            
            self.last_sync_snapshot_index = -1
            self._update_snapshot_display()
        except Exception as e:
            if hasattr(self, 'logger'):
                self.logger.log(f"Error loading snapshots: {e}", "ERROR")

    def _sync_snapshots_to_replay(self, rel_time):
        """Automatically switch snapshots based on replay playhead time."""
        if not hasattr(self, "snapshot_data") or not self.snapshot_data:
            return

        # Find the latest snapshot that was taken before or at rel_time
        # Since snapshot_data is sorted by rel_time, we can just iterate
        found_index = -1
        for i, snap in enumerate(self.snapshot_data):
            if snap["rel_time"] <= rel_time:
                found_index = i
            else:
                break
        
        # If the snapshot has changed and we found one, update the display
        if found_index != -1 and found_index != self.last_sync_snapshot_index:
            self.current_snapshot_index = found_index
            self.last_sync_snapshot_index = found_index
            self._update_snapshot_display()

    def _update_snapshot_display(self):
        """Update the snapshot label with the current image."""
        if not hasattr(self, 'dashboard_snapshot_label'):
            return

        if 0 <= self.current_snapshot_index < len(self.snapshot_paths):
            path = self.snapshot_paths[self.current_snapshot_index]
            
            # Cache the pixmap to avoid repeated disk reads during resize events
            if not hasattr(self, '_current_snapshot_pixmap_cache') or \
               getattr(self, '_current_snapshot_path_cache', None) != path:
                self._current_snapshot_pixmap_cache = QPixmap(path)
                self._current_snapshot_path_cache = path
                
            pixmap = self._current_snapshot_pixmap_cache
            
            if pixmap and not pixmap.isNull():
                # Scale pixmap to fit the ACTUAL label size while maintaining aspect ratio.
                available_size = self.dashboard_snapshot_label.size()
                
                # If the widget hasn't been shown yet or is hidden, size might be small.
                if available_size.width() < 50 or available_size.height() < 50:
                    if hasattr(self, 'dashboard_snapshot_group'):
                        available_size = QSize(
                            max(50, self.dashboard_snapshot_group.width() - 30),
                            max(50, self.dashboard_snapshot_group.height() - 80)
                        )
                    else:
                        available_size = QSize(400, 300)
                
                scaled_pixmap = pixmap.scaled(
                    available_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.dashboard_snapshot_label.setPixmap(scaled_pixmap)
                self.dashboard_snapshot_label.setToolTip(os.path.basename(path))
                # Update title/text
                if hasattr(self, 'dashboard_snapshot_group'):
                    self.dashboard_snapshot_group.setTitle(f"Image ({self.current_snapshot_index + 1}/{len(self.snapshot_paths)})")
            else:
                self.dashboard_snapshot_label.setText("Error loading image")
                self.dashboard_snapshot_label.setPixmap(QPixmap())
                self._current_snapshot_pixmap_cache = None
        else:
            self.dashboard_snapshot_label.setText("No image available")
            self.dashboard_snapshot_label.setPixmap(QPixmap())
            self._current_snapshot_pixmap_cache = None
            if hasattr(self, 'dashboard_snapshot_group'):
                self.dashboard_snapshot_group.setTitle("Last Images")

    def prev_snapshot(self):
        """Show the previous snapshot."""
        if hasattr(self, "snapshot_paths") and self.snapshot_paths and self.current_snapshot_index > 0:
            self.current_snapshot_index -= 1
            # Reset last sync index so automatic sync can take over again if playing
            self.last_sync_snapshot_index = -1 
            self._update_snapshot_display()

    def next_snapshot(self):
        """Show the next snapshot."""
        if hasattr(self, "snapshot_paths") and self.snapshot_paths and self.current_snapshot_index < len(self.snapshot_paths) - 1:
            self.current_snapshot_index += 1
            # Reset last sync index so automatic sync can take over again if playing
            self.last_sync_snapshot_index = -1
            self._update_snapshot_display()

    def view_snapshot_popup(self):
        """View the current image in a popup window with zoom functionality."""
        if not hasattr(self, "snapshot_paths") or not (0 <= self.current_snapshot_index < len(self.snapshot_paths)):
            return
        
        path = self.snapshot_paths[self.current_snapshot_index]
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return

        # Create a simple dialog for zoomable view
        popup = QDialog(self)
        popup.setWindowTitle(f"Image View: {os.path.basename(path)}")
        popup.resize(1000, 800)
        
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(0, 0, 0, 0)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setStyleSheet("background-color: #1e1e1e; border: none;")
        
        # Use our custom zoomable label
        label = ZoomableImageLabel(pixmap)
        label.fit_in_view(1000, 800) # Initial fit
        
        scroll.setWidget(label)
        layout.addWidget(scroll)
        
        popup.exec()

    def setup_status_bar_click(self):
        """Setup status bar with Data Flow and Tools buttons on the right"""
        from PyQt6.QtWidgets import QPushButton
        
        # Common button style
        status_btn_style = """
            QPushButton {
                background-color: transparent;
                color: #888888;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
                margin: 2px;
            }
            QPushButton:hover {
                background-color: rgba(100, 100, 100, 0.3);
                color: #CCCCCC;
                border-color: #777777;
            }
            QPushButton:pressed {
                background-color: rgba(100, 100, 100, 0.5);
            }
        """
        
        # Label to display which run is active/loaded
        self.run_context_label = QLabel("No run loaded")
        self.run_context_label.setStyleSheet("color: #CCCCCC; font-size: 11px; margin-left: 6px;")
        self.run_context_label.setMinimumWidth(220)
        self.statusBar().addPermanentWidget(self.run_context_label, 1)
        
        # Create Tools button for the status bar
        self.tools_btn = QPushButton("🧰 Tools")
        self.tools_btn.setFlat(True)
        self.tools_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tools_btn.setStyleSheet(status_btn_style)
        self.tools_btn.setToolTip("Open Analysis Tools (Ctrl+Shift+T)")
        self.tools_btn.clicked.connect(self.toggle_tools_window)
        
        # Add the Tools button as a permanent widget on the right side of the status bar
        self.statusBar().addPermanentWidget(self.tools_btn)
        
        # Create a clickable Data Flow button for the status bar
        self.data_flow_btn = QPushButton("📊 Data Flow")
        self.data_flow_btn.setFlat(True)
        self.data_flow_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.data_flow_btn.setStyleSheet(status_btn_style)
        self.data_flow_btn.setToolTip("Open Data Flow Monitor (Ctrl+Shift+D)")
        self.data_flow_btn.clicked.connect(self.toggle_data_flow_page)
        
        # Add the button as a permanent widget on the right side of the status bar
        self.statusBar().addPermanentWidget(self.data_flow_btn)
        
        # Initialize tools window reference
        self._tools_window = None
    
    def toggle_tools_window(self):
        """Toggle the Tools window (open/close)"""
        # Lazy load the tools window
        if self._tools_window is None:
            from app.ui.tools import ToolsWindow
            self._tools_window = ToolsWindow(main_window=self)
            self._tools_window.closed.connect(self._on_tools_window_closed)
        
        if self._tools_window.isVisible():
            self._tools_window.hide()
        else:
            self._tools_window.show()
            self._tools_window.raise_()
            self._tools_window.activateWindow()
    
    def _on_tools_window_closed(self):
        """Handle tools window closed signal"""
        # The window is hidden, not destroyed, so we don't need to do much
        pass
