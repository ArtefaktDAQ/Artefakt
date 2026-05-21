"""
Project Controller

Manages project data and operations.
"""
import os
import json
import datetime
import shutil
from PyQt6.QtCore import QObject, pyqtSignal, Qt, QItemSelectionModel
from PyQt6.QtGui import QStandardItem
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QCheckBox, QDialog, QVBoxLayout, QLabel, QPushButton, QProgressDialog, QTextEdit, QHBoxLayout
from PyQt6.QtWidgets import QApplication
from app.utils.common_types import StatusState

class ProjectController(QObject):
    """Controls project data and operations"""
    
    # Signal that will be emitted when the project status changes
    status_changed = pyqtSignal()
    
    def __init__(self, main_window):
        """
        Initialize the project controller
        
        Args:
            main_window: Main application window
        """
        super().__init__()
        self.main_window = main_window
        self.current_project = None
        self.current_test_series = None
        self.current_run = None
        self.project_description = ""
        self.test_series_description = ""
        self.run_description = ""
        
        # For maintaining selection state independent of the tree view
        self.last_selected_type = None
        self.last_selected_project = None
        self.last_selected_series = None
        self.last_selected_run = None
        
        # Flag to prevent recursion in auto_save
        self.is_saving = False
        self.auto_save_pending = False
        
        # Find the status label in the UI
        self.ui_status_label = None
        if hasattr(self.main_window, 'project_status') and hasattr(self.main_window.project_status, 'setText'):
            self.ui_status_label = self.main_window.project_status

    def startup_load(self):
        """Load the last used project and test series on startup"""
        # Load base directory from config
        if hasattr(self.main_window, 'config') and hasattr(self.main_window, 'project_base_dir'):
            base_dir = self.main_window.config.get("default_project_dir", "")
            if base_dir and os.path.exists(base_dir):
                self.main_window.project_base_dir.setText(base_dir)
                self.main_window.logger.log(f"Loaded base directory from config: {base_dir}")
                # Update the project tree with the loaded directory and expand everything
                self.update_project_tree(expand_all=True)
                
                # Load the last used project and test series if available
                last_project = self.main_window.config.get("last_project", "")
                last_test_series = self.main_window.config.get("last_test_series", "")
                
                if last_project and os.path.exists(os.path.join(base_dir, last_project)):
                    # Set the project selector to the last used project
                    self.main_window.project_selector.setCurrentText(last_project)
                    self.current_project = last_project
                    self.main_window.logger.log(f"Loaded last used project: {last_project}")
                    
                    # Load project metadata
                    self.load_project_metadata()
                    
                    if last_test_series:
                        # First update the test series selector
                        self.update_test_series_selector()
                        
                        # Now try to set the test series
                        if self.main_window.test_series_selector.findText(last_test_series) >= 0:
                            self.main_window.test_series_selector.setCurrentText(last_test_series)
                            self.current_test_series = last_test_series
                            self.main_window.logger.log(f"Loaded last used test series: {last_test_series}")
                            
                            # Load test series metadata
                            self.load_test_series_metadata()
                            
                            # Load the last used run if available, otherwise find the newest
                            last_run = self.main_window.config.get("last_run", "")
                            run_path = os.path.join(base_dir, last_project, last_test_series, last_run) if last_run else None
                            
                            if last_run and run_path and os.path.exists(run_path):
                                self.main_window.logger.log(f"Loading last used run: {last_run}", "INFO")
                                self.load_run(
                                    project_name=last_project,
                                    series_name=last_test_series,
                                    run_name=last_run,
                                    is_startup_load=True
                                )
                            else:
                                # Find and load the newest run
                                self.load_newest_run(is_startup_load=True)
                            
                            # Update the project tree again to show highlighting for the loaded run
                            self.update_project_tree(expand_all=True)
        
        # Make sure sidebar is updated with current project and test series
        if self.current_project:
            self.main_window.sidebar_project_name.setText(self.current_project)
        else:
            self.main_window.sidebar_project_name.setText("None")
            
        if self.current_test_series:
            self.main_window.sidebar_test_series.setText(self.current_test_series)
        else:
            self.main_window.sidebar_test_series.setText("None")
        
    def connect_signals(self):
        """Connect signals for the UI elements"""
        # Connect project selector signals
        self.main_window.project_selector.currentTextChanged.connect(self.on_project_selected)
        self.main_window.test_series_selector.currentTextChanged.connect(self.on_test_series_selected)
        
        # Connect project load directory button
        self.main_window.browse_base_dir_btn.clicked.connect(self.on_load_dir_clicked)
        
        # Connect project UI signals
        self.main_window.new_project_btn.clicked.connect(self.on_create_project_clicked)
        self.main_window.new_test_series_btn.clicked.connect(self.on_create_test_series_clicked)
        self.main_window.load_project_btn.clicked.connect(self.on_load_run_clicked)
        
        # Export Data button is connected in main_window.py to avoid duplicate connections
        
        # Connect project tree click to store the selection
        self.main_window.project_tree.clicked.connect(self.on_project_tree_clicked)
        
        # Connect field changes to trigger status checks
        self.main_window.project_base_dir.textChanged.connect(self.check_project_status)
        self.main_window.project_selector.currentTextChanged.connect(self.check_project_status)
        self.main_window.test_series_selector.currentTextChanged.connect(self.check_project_status)
        self.main_window.run_description.textChanged.connect(self.check_project_status)
        self.main_window.run_testers.textChanged.connect(self.check_project_status)
        
        # Connect to the project and test series text fields
        from PyQt6.QtCore import QTimer
        self.save_timer = QTimer()
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save_project)
        
        # Connect text changed signals for automatic saving
        self.main_window.project_base_dir.textChanged.connect(self.status_changed.emit)
        self.main_window.project_base_dir.textChanged.connect(self.save_base_dir_to_config)
        
        self.main_window.project_description.textChanged.connect(
            lambda: self.auto_save_description('project'))
        self.main_window.test_series_description.textChanged.connect(
            lambda: self.auto_save_description('test_series'))
        self.main_window.run_description.textChanged.connect(
            lambda: self.auto_save_description('run'))
        self.main_window.run_testers.textChanged.connect(
            lambda: self.auto_save_description('run'))
        
    def save_base_dir_to_config(self):
        """Save the base directory to the config file"""
        base_dir = self.main_window.project_base_dir.text()
        if base_dir and os.path.exists(base_dir):
            # Save to QSettings
            if hasattr(self.main_window, 'settings'):
                self.main_window.settings.setValue("base_directory", base_dir)
                self.main_window.settings.sync()  # Force settings to be written to disk immediately
            
            # Save to config file
            if hasattr(self.main_window, 'config'):
                self.main_window.config["default_project_dir"] = base_dir
                
                # Also save current project and test series for next startup
                if self.current_project:
                    self.main_window.config["last_project"] = self.current_project
                if self.current_test_series:
                    self.main_window.config["last_test_series"] = self.current_test_series
                if self.current_run:
                    self.main_window.config["last_run"] = self.current_run
                
                # Save testers field value
                if hasattr(self.main_window, 'run_testers'):
                    testers = self.main_window.run_testers.text().strip()
                    if testers:
                        self.main_window.config["last_testers"] = testers
                    
                self.main_window.save_config()
                self.main_window.logger.log(f"Saved base directory to config: {base_dir}")
            
    def auto_save_description(self, description_type):
        """Automatically save description when changed"""
        # Don't save if we don't have a project
        if description_type in ['test_series', 'run'] and not self.current_project:
            return
            
        # Don't save test series description if we don't have a test series
        if description_type == 'run' and not self.current_test_series:
            return
            
        # If we're already saving, set the pending flag and return
        if self.is_saving:
            self.auto_save_pending = True
            return
            
        # Update the descriptions
        if description_type == 'project':
            self.project_description = self.main_window.project_description.toPlainText()
        elif description_type == 'test_series':
            self.test_series_description = self.main_window.test_series_description.toPlainText()
        elif description_type == 'run':
            self.run_description = self.main_window.run_description.toPlainText()
            
            # Also save testers value to config when run description changes
            if hasattr(self.main_window, 'run_testers') and hasattr(self.main_window, 'config'):
                testers = self.main_window.run_testers.text().strip()
                if testers:
                    self.main_window.config["last_testers"] = testers
                    self.main_window.save_config()
            
        # Update group box colors
        if hasattr(self.main_window, 'update_project_group_box_colors'):
            self.main_window.update_project_group_box_colors()
            
        # We'll still emit the status change but not trigger a full save on every keystroke
        self.status_changed.emit()
        
        # Start or restart the timer to save after a delay (1 second)
        self.save_timer.start(1000)
            
    def _format_duration(self, seconds):
        """Format seconds into H:MM:SS or M:SS"""
        if seconds is None or seconds == "":
            return "—"
        try:
            seconds = float(seconds)
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            if hours > 0:
                return f"{hours}:{minutes:02d}:{secs:02d}"
            else:
                return f"{minutes:02d}:{secs:02d}"
        except:
            return str(seconds)

    def _count_sensors(self, run_dir):
        """Count active sensors from sensors.json in run directory"""
        sensors_file = os.path.join(run_dir, "sensors.json")
        if os.path.exists(sensors_file):
            try:
                with open(sensors_file, 'r') as f:
                    sensors = json.load(f)
                    return len(sensors)
            except:
                pass
        return 0

    def _has_video(self, metadata, run_dir):
        """Check if a video was recorded for this run"""
        if metadata.get("videos") or metadata.get("video_path"):
            return "🎥 Yes"
        
        # Check filesystem as fallback
        try:
            for file in os.listdir(run_dir):
                if file.endswith(('.mp4', '.avi', '.mkv', '.mov')):
                    return "🎥 Yes"
        except:
            pass
        return "No"

    def _count_images(self, run_dir):
        """Count image files in the run directory and Snapshots subfolder"""
        image_extensions = ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.gif', '.webp')
        count = 0
        
        # Count images in the run directory
        try:
            for file in os.listdir(run_dir):
                if file.lower().endswith(image_extensions):
                    count += 1
        except:
            pass
        
        # Count images in the Snapshots subfolder
        snapshots_dir = os.path.join(run_dir, "Snapshots")
        try:
            if os.path.exists(snapshots_dir) and os.path.isdir(snapshots_dir):
                for file in os.listdir(snapshots_dir):
                    if file.lower().endswith(image_extensions):
                        count += 1
        except:
            pass
        
        return count

    def _get_run_duration(self, metadata, run_dir):
        """Get run duration from metadata or filesystem fallback"""
        # 1. Try explicit duration fields
        duration_sec = metadata.get("video_duration_sec")
        if duration_sec is None:
            duration_sec = metadata.get("duration_sec")
        
        # 2. Try start/end epoch difference
        if duration_sec is None:
            start = metadata.get("run_start_epoch")
            end = metadata.get("run_end_epoch")
            if start and end:
                try:
                    duration_sec = float(end) - float(start)
                except:
                    pass
        
        # 3. Try CSV file modification time fallback
        if duration_sec is None:
            try:
                # Find all rundata files
                csv_files = [f for f in os.listdir(run_dir) if f.startswith('rundata_') and f.endswith('.csv')]
                if csv_files:
                    # Get the latest one
                    latest_csv = max([os.path.join(run_dir, f) for f in csv_files], key=os.path.getmtime)
                    mtime = os.path.getmtime(latest_csv)
                    
                    # Get start time from metadata or file creation
                    start_epoch = metadata.get("run_start_epoch")
                    if not start_epoch:
                        # Fallback to earliest CSV's mtime or directory creation
                        earliest_csv = min([os.path.join(run_dir, f) for f in csv_files], key=os.path.getmtime)
                        start_epoch = os.path.getmtime(earliest_csv)
                    
                    if start_epoch and mtime > start_epoch:
                        duration_sec = mtime - start_epoch
            except:
                pass
                
        return duration_sec

    def update_project_tree(self, expand_all=False):
        """
        Update the project tree view with existing projects
        
        Args:
            expand_all: If True, expands all items after loading.
        """
        tree = getattr(self.main_window, "project_tree", None)
        model = getattr(self.main_window, "project_model", None)
        
        # Save expansion state: store paths like "ProjectName/SeriesName"
        expanded_paths = []
        if tree and model and not expand_all:
            for i in range(model.rowCount()):
                project_item = model.item(i, 0)
                if project_item and tree.isExpanded(project_item.index()):
                    project_name = project_item.text()
                    expanded_paths.append(project_name)
                    for j in range(project_item.rowCount()):
                        series_item = project_item.child(j, 0)
                        if series_item and tree.isExpanded(series_item.index()):
                            series_name = series_item.text()
                            expanded_paths.append(f"{project_name}/{series_name}")

        # Clear the model
        self.main_window.project_model.clear()
        self.main_window.project_model.setHorizontalHeaderLabels(["Name", "Description", "Duration", "Sensors", "Video", "Images"])
        
        # Get base directory
        base_dir = self.main_window.project_base_dir.text()
        if not base_dir or not os.path.exists(base_dir):
            self.main_window.logger.log("Base directory not set or does not exist.", "INFO")
            return
            
        # Root item for project tree
        root_item = self.main_window.project_model.invisibleRootItem()
        
        # Update selectors
        self.update_project_selector()
        
        # Scan base directory for projects
        try:
            for project_name in os.listdir(base_dir):
                project_dir = os.path.join(base_dir, project_name)
                
                # Skip files, only process directories
                if not os.path.isdir(project_dir):
                    continue
                    
                # Load metadata if exists
                project_desc = ""
                metadata_file = os.path.join(project_dir, "project_metadata.json")
                
                if os.path.exists(metadata_file):
                    try:
                        with open(metadata_file, 'r') as f:
                            metadata = json.load(f)
                            project_desc = metadata.get("description", "")
                    except Exception as e:
                        self.main_window.logger.log(f"Error reading project metadata: {str(e)}", "WARN")
                
                # Create project item
                project_item = QStandardItem(project_name)
                desc_item = QStandardItem(project_desc)
                duration_item = QStandardItem("")
                sensors_item = QStandardItem("")
                video_item = QStandardItem("")
                images_item = QStandardItem("")
                
                # Add project to root
                root_item.appendRow([project_item, desc_item, duration_item, sensors_item, video_item, images_item])
                
                # Scan for test series within project
                series_dirs = []
                try:
                    series_dirs = os.listdir(project_dir)
                except Exception as e:
                    self.main_window.logger.log(f"Error scanning test series: {str(e)}", "WARN")
                
                for series_name in series_dirs:
                    series_dir = os.path.join(project_dir, series_name)
                    
                    # Skip files, only process directories
                    if not os.path.isdir(series_dir):
                        continue
                        
                    # Load metadata if exists
                    series_desc = ""
                    series_metadata_file = os.path.join(series_dir, "series_metadata.json")
                    
                    if os.path.exists(series_metadata_file):
                        try:
                            with open(series_metadata_file, 'r') as f:
                                metadata = json.load(f)
                                series_desc = metadata.get("description", "")
                        except Exception as e:
                            self.main_window.logger.log(f"Error reading series metadata: {str(e)}", "WARN")
                    
                    # Create test series item
                    series_item = QStandardItem(series_name)
                    series_desc_item = QStandardItem(series_desc)
                    series_duration_item = QStandardItem("")
                    series_sensors_item = QStandardItem("")
                    series_video_item = QStandardItem("")
                    series_images_item = QStandardItem("")
                    
                    # Add series to project
                    project_item.appendRow([series_item, series_desc_item, series_duration_item, series_sensors_item, series_video_item, series_images_item])
                    
                    # Check for runs in the test series
                    run_dirs = []
                    try:
                        run_dirs = os.listdir(series_dir)
                    except Exception as e:
                        self.main_window.logger.log(f"Error scanning runs: {str(e)}", "WARN")
                    
                    for run_name in run_dirs:
                        run_dir = os.path.join(series_dir, run_name)
                        
                        # Skip files, only process directories
                        if not os.path.isdir(run_dir):
                            continue
                            
                        # Load metadata if exists
                        run_desc = ""
                        run_duration = ""
                        run_sensors = ""
                        run_video = ""
                        run_images = ""
                        run_metadata_file = os.path.join(run_dir, "run_metadata.json")
                        
                        metadata = {}
                        if os.path.exists(run_metadata_file):
                            try:
                                with open(run_metadata_file, 'r') as f:
                                    metadata = json.load(f)
                                    run_desc = metadata.get("description", "")
                            except Exception as e:
                                self.main_window.logger.log(f"Error reading run metadata: {str(e)}", "WARN")
                        
                        # Get duration using improved fallback logic (metadata might be empty but run_dir is valid)
                        duration_sec = self._get_run_duration(metadata, run_dir)
                        run_duration = self._format_duration(duration_sec)
                        
                        # Count sensors
                        sensor_count = self._count_sensors(run_dir)
                        run_sensors = str(sensor_count) if sensor_count > 0 else "—"
                        
                        # Check for video
                        run_video = self._has_video(metadata, run_dir)
                        
                        # Count images
                        image_count = self._count_images(run_dir)
                        run_images = str(image_count) if image_count > 0 else "—"
                        
                        # Create run item
                        run_item = QStandardItem(run_name)
                        run_desc_item = QStandardItem(run_desc)
                        run_duration_item = QStandardItem(run_duration)
                        run_sensors_item = QStandardItem(run_sensors)
                        run_video_item = QStandardItem(run_video)
                        run_images_item = QStandardItem(run_images)

                        # Highlight if it's the current run
                        if (hasattr(self, 'current_run') and self.current_run == run_name and 
                            hasattr(self, 'current_test_series') and self.current_test_series == series_name and
                            hasattr(self, 'current_project') and self.current_project == project_name):
                            # Use a light blue color for the text and make it bold
                            from PyQt6.QtGui import QColor
                            highlight_color = QColor("#3498DB") # Modern Light Blue
                            
                            row_items = [run_item, run_desc_item, run_duration_item, run_sensors_item, run_video_item, run_images_item]
                            for item in row_items:
                                item.setForeground(highlight_color)
                                font = item.font()
                                font.setBold(True)
                                item.setFont(font)
                                item.setToolTip("Currently loaded/active run")

                        # Add run to test series
                        series_item.appendRow([run_item, run_desc_item, run_duration_item, run_sensors_item, run_video_item, run_images_item])
        
        except Exception as e:
            self.main_window.logger.log(f"Error updating project tree: {str(e)}", "ERROR")
            
        # Expansion logic
        if tree:
            if expand_all:
                tree.expandAll()
            elif model and expanded_paths:
                # Restore expansion state
                for i in range(model.rowCount()):
                    project_item = model.item(i, 0)
                    if project_item:
                        project_name = project_item.text()
                        if project_name in expanded_paths:
                            tree.expand(project_item.index())
                            for j in range(project_item.rowCount()):
                                series_item = project_item.child(j, 0)
                                if series_item:
                                    series_name = series_item.text()
                                    if f"{project_name}/{series_name}" in expanded_paths:
                                        tree.expand(series_item.index())
            else:
                # Expand the tree to show the first level if no state saved
                tree.expandToDepth(0)
                
        # Auto-adjust columns to contents after loading
        if tree and model:
            for i in range(model.columnCount()):
                # We skip column 1 (Description) as it's set to Stretch in ui_setup.py
                if i != 1:
                    tree.resizeColumnToContents(i)
    
    def select_tree_item(self, project_name=None, series_name=None, run_name=None):
        """
        Expand and select an item in the project tree.
        
        Args:
            project_name: Name of the project to select.
            series_name: Optional test series name.
            run_name: Optional run name.
        """
        model = getattr(self.main_window, "project_model", None)
        tree = getattr(self.main_window, "project_tree", None)
        if not model or not tree or not project_name:
            return
        
        target_index = None
        
        for i in range(model.rowCount()):
            project_item = model.item(i, 0)
            if not project_item or project_item.text() != project_name:
                continue
            project_index = project_item.index()
            tree.expand(project_index)
            
            if not series_name:
                target_index = project_index
                break
            
            for j in range(project_item.rowCount()):
                series_item = project_item.child(j, 0)
                if not series_item or series_item.text() != series_name:
                    continue
                series_index = series_item.index()
                tree.expand(series_index)
                
                if not run_name:
                    target_index = series_index
                    break
                
                for k in range(series_item.rowCount()):
                    run_item = series_item.child(k, 0)
                    if run_item and run_item.text() == run_name:
                        target_index = run_item.index()
                        break
                break
            if target_index:
                break
        
        if target_index:
            selection_model = tree.selectionModel()
            if selection_model:
                selection_model.select(
                    target_index,
                    QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows
                )
                tree.scrollTo(target_index)
                self.on_project_tree_clicked(target_index)
    
    def update_project_selector(self):
        """Update the project selector dropdown with existing projects"""
        # Get base directory
        base_dir = self.main_window.project_base_dir.text()
        if not base_dir or not os.path.exists(base_dir):
            return
            
        # Save current selection
        current_selection = self.main_window.project_selector.currentText()
            
        # Clear the selector
        self.main_window.project_selector.clear()
            
        # Scan base directory for projects
        try:
            for project_name in os.listdir(base_dir):
                project_dir = os.path.join(base_dir, project_name)
                
                # Skip files, only process directories
                if not os.path.isdir(project_dir):
                    continue
                    
                # Add project to selector
                self.main_window.project_selector.addItem(project_name)
                
        except Exception as e:
            self.main_window.logger.log(f"Error updating project selector: {str(e)}", "ERROR")
            
        # Restore selection if it still exists
        index = self.main_window.project_selector.findText(current_selection)
        if index >= 0:
            self.main_window.project_selector.setCurrentIndex(index)
    
    def update_test_series_selector(self):
        """Update the test series selector dropdown with existing test series for the current project"""
        # Get base directory and project
        base_dir = self.main_window.project_base_dir.text()
        project_name = self.main_window.project_selector.currentText().strip()
        
        if not base_dir or not project_name:
            return
            
        # Build project path
        project_dir = os.path.join(base_dir, project_name)
        if not os.path.exists(project_dir):
            return
            
        # Save current selection
        current_selection = self.main_window.test_series_selector.currentText()
            
        # Clear the selector
        self.main_window.test_series_selector.clear()
            
        # Scan project directory for test series
        try:
            for series_name in os.listdir(project_dir):
                series_dir = os.path.join(project_dir, series_name)
                
                # Skip files, only process directories
                if not os.path.isdir(series_dir):
                    continue
                    
                # Add test series to selector
                self.main_window.test_series_selector.addItem(series_name)
                
        except Exception as e:
            self.main_window.logger.log(f"Error updating test series selector: {str(e)}", "ERROR")
            
        # Restore selection if it still exists
        index = self.main_window.test_series_selector.findText(current_selection)
        if index >= 0:
            self.main_window.test_series_selector.setCurrentIndex(index)
            
    def update_project_status(self):
        """Update the project status indicators"""
        pass
    
    def on_load_dir_clicked(self):
        """Called when the Browse button is clicked to select the project base directory"""
        # Use file dialog to select a directory
        current_dir = self.main_window.project_base_dir.text() or os.path.expanduser("~")
        directory = QFileDialog.getExistingDirectory(
            self.main_window, 
            "Select Base Directory",
            current_dir,
            QFileDialog.Option.ShowDirsOnly
        )
        
        # If a directory was selected, update the project base directory
        if directory:
            # Save to both settings and config
            self.main_window.project_base_dir.setText(directory)
            
            # Save to QSettings
            if hasattr(self.main_window, 'settings'):
                self.main_window.settings.setValue("base_directory", directory)
                self.main_window.settings.sync()  # Force settings to be written to disk immediately
            
            # Save to config file
            if hasattr(self.main_window, 'config'):
                self.main_window.config["default_project_dir"] = directory
                self.main_window.save_config()
            
            self.main_window.logger.log(f"Set project base directory to: {directory}")
            self.update_project_tree(expand_all=True)
            
            # Update group box colors
            if hasattr(self.main_window, 'update_project_group_box_colors'):
                self.main_window.update_project_group_box_colors()
            
            # Update status
            self.status_changed.emit()
    
    def on_load_run_clicked(self):
        """Called when the Load Run button is clicked to load a selected run"""
        # Check if a run is currently active
        if hasattr(self.main_window, 'running') and self.main_window.running:
            self.main_window.logger.log("Cannot load a new run while a run is currently active. Please stop the current run first.", "WARN")
            self.update_status_text("Error: Cannot load run while another run is active", "red")
            return
            
        self.load_run()
    
    def on_delete_run_clicked(self):
        """Called when the Delete Run button is clicked to remove a run"""
        # Prevent deletion while a run is active
        if getattr(self.main_window, "running", False):
            QMessageBox.warning(
                self.main_window,
                "Run Active",
                "Stop the current run before deleting a run."
            )
            return
        
        if self.last_selected_type != "run":
            QMessageBox.information(
                self.main_window,
                "Select Run",
                "Please select a run in the Project Browser to delete."
            )
            return
        
        base_dir = self.main_window.project_base_dir.text()
        if not base_dir or not os.path.exists(base_dir):
            QMessageBox.warning(
                self.main_window,
                "Missing Base Directory",
                "Please set a valid base directory before deleting runs."
            )
            return
        
        project_name = self.last_selected_project
        series_name = self.last_selected_series
        run_name = self.last_selected_run
        run_dir = os.path.join(base_dir, project_name, series_name, run_name)
        
        if not os.path.exists(run_dir):
            QMessageBox.warning(
                self.main_window,
                "Run Not Found",
                f"The run directory does not exist:\n{run_dir}"
            )
            return
        
        # Collect files within the run directory for confirmation preview
        file_paths = []
        for root, _, files in os.walk(run_dir):
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), run_dir)
                file_paths.append(rel_path)
        file_paths = sorted(file_paths)
        
        max_preview = 200
        preview_paths = file_paths[:max_preview]
        if len(file_paths) > max_preview:
            preview_paths.append(f"... and {len(file_paths) - max_preview} more files")
        
        if not preview_paths:
            preview_paths = ["(no files found in this run folder)"]
        
        # Build confirmation dialog
        dialog = QDialog(self.main_window)
        dialog.setWindowTitle("Delete Run")
        layout = QVBoxLayout(dialog)
        
        message = (
            f"Delete run '{run_name}' from test series '{series_name}' in project '{project_name}'?\n"
            "This will permanently remove the folder and the files listed below."
        )
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)
        
        files_text = QTextEdit()
        files_text.setReadOnly(True)
        files_text.setMinimumHeight(200)
        files_text.setPlainText("\n".join(preview_paths))
        layout.addWidget(files_text)
        
        button_layout = QHBoxLayout()
        confirm_btn = QPushButton("Delete")
        cancel_btn = QPushButton("Cancel")
        button_layout.addStretch(1)
        button_layout.addWidget(confirm_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        confirm_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        
        # Perform deletion
        try:
            shutil.rmtree(run_dir)
            self.main_window.logger.log(f"Deleted run directory: {run_dir}", "INFO")
        except Exception as e:
            QMessageBox.critical(
                self.main_window,
                "Delete Failed",
                f"Could not delete run:\n{str(e)}"
            )
            self.main_window.logger.log(f"Error deleting run directory: {str(e)}", "ERROR")
            return
        
        # Clear selection and refresh UI
        if hasattr(self.main_window, "project_tree"):
            self.main_window.project_tree.clearSelection()
        self.last_selected_type = None
        self.last_selected_project = None
        self.last_selected_series = None
        self.last_selected_run = None
        
        # If the deleted run was loaded, clear current run references
        if (self.current_project == project_name and
            self.current_test_series == series_name and
            self.current_run == run_name):
            self.current_run = None
            self.run_description = ""
            if hasattr(self.main_window, "run_description"):
                self.main_window.run_description.clear()
            if hasattr(self.main_window, "run_testers"):
                self.main_window.run_testers.clear()
        
        self.update_project_tree()
        self.status_changed.emit()
        
        QMessageBox.information(
            self.main_window,
            "Run Deleted",
            f"Run '{run_name}' has been deleted."
        )
    
    def browse_base_directory(self):
        """Browse for the base directory"""
        current_dir = self.main_window.project_base_dir.text() or ""
        directory = QFileDialog.getExistingDirectory(
            self.main_window,
            "Select Base Directory for Projects",
            current_dir
        )
        
        if directory:
            self.main_window.project_base_dir.setText(directory)
            self.main_window.settings.setValue("base_directory", directory)
            self.main_window.logger.log(f"Base directory set to: {directory}")
            
            # Update project tree to show existing projects
            self.update_project_tree()
            
            # Update status
            self.status_changed.emit()
    
    def update_status_text(self, text, color="black"):
        """Update the status text in the UI"""
        if hasattr(self.main_window, 'project_status') and hasattr(self.main_window.project_status, 'setText'):
            self.main_window.project_status.setText(text)
            self.main_window.project_status.setStyleSheet(f"font-weight: bold; color: {color};")
            
    def on_create_project_clicked(self):
        """Called when the New Project button is clicked"""
        self.create_new_project()
        
    def on_create_test_series_clicked(self):
        """Called when the New Test Series button is clicked"""
        self.create_new_test_series()
    
    def create_new_project(self):
        """Create a new project"""
        project_name = self.main_window.project_selector.currentText().strip()
        if not project_name:
            self.main_window.logger.log("Project name not specified.", "WARN")
            self.update_status_text("Error: Project name not specified", "red")
            return
            
        # Check if base directory is set
        base_dir = self.main_window.project_base_dir.text()
        if not base_dir or not os.path.exists(base_dir):
            self.main_window.logger.log("Base directory not set or does not exist.", "WARN")
            self.update_status_text("Error: Base directory not set", "red")
            return
            
        # Build project directory path
        project_dir = os.path.join(base_dir, project_name)
        
        # Check if project already exists
        if os.path.exists(project_dir):
            self.main_window.logger.log(f"Project '{project_name}' already exists.", "WARN")
            self.update_status_text(f"Project '{project_name}' already exists", "orange")
            self.main_window.statusBar().showMessage(f"Project '{project_name}' already exists.", 5000) # Add status bar message
            # Still allow editing of existing project
            self.current_project = project_name
            self.load_project_metadata()
            self.update_project_tree()
            return
            
        # Create project directory
        try:
            os.makedirs(project_dir, exist_ok=True)
            self.main_window.logger.log(f"Created project directory: {project_dir}")
            self.current_project = project_name
            
            # Update project description from UI
            if hasattr(self.main_window, 'project_description'):
                self.project_description = self.main_window.project_description.toPlainText()
            
            # Save project metadata
            self.save_project()
            
            # Save project state
            self.save_state_to_json()
            
            # Update UI
            self.update_status_text(f"Project '{project_name}' created successfully", "green")
            self.main_window.statusBar().showMessage(f"Project '{project_name}' created successfully.", 5000) # Add status bar message
            self.update_project_tree()
            
        except Exception as e:
            self.main_window.logger.log(f"Error creating project: {str(e)}", "ERROR")
            self.update_status_text(f"Error creating project: {str(e)}", "red")
            
    def create_new_test_series(self):
        """Create a new test series"""
        # Check if a project is selected
        if not self.current_project:
            self.main_window.logger.log("No project selected for creating test series.", "WARN")
            self.update_status_text("Error: No project selected", "red")
            return
            
        # Get test series name
        series_name = self.main_window.test_series_selector.currentText().strip()
        if not series_name:
            self.main_window.logger.log("Test series name not specified.", "WARN")
            self.update_status_text("Error: Test series name not specified", "red")
            return
            
        # Check if base directory is set
        base_dir = self.main_window.project_base_dir.text()
        if not base_dir or not os.path.exists(base_dir):
            self.main_window.logger.log("Base directory not set or does not exist.", "WARN")
            self.update_status_text("Error: Base directory not set", "red")
            return
            
        # Build test series directory path
        project_dir = os.path.join(base_dir, self.current_project)
        series_dir = os.path.join(project_dir, series_name)
        
        # Check if test series already exists
        if os.path.exists(series_dir):
            self.main_window.logger.log(f"Test series '{series_name}' already exists.", "WARN")
            self.update_status_text(f"Test series '{series_name}' already exists", "orange")
            self.main_window.statusBar().showMessage(f"Test series '{series_name}' already exists.", 5000) # Add status bar message
            # Still allow editing of existing test series
            self.current_test_series = series_name
            self.load_test_series_metadata()
            self.update_project_tree()
            return
            
        # Create test series directory
        try:
            os.makedirs(series_dir, exist_ok=True)
            self.main_window.logger.log(f"Created test series directory: {series_dir}")
            self.current_test_series = series_name
            
            # Update test series description from UI
            if hasattr(self.main_window, 'test_series_description'):
                self.test_series_description = self.main_window.test_series_description.toPlainText()
            
            # Save test series metadata
            self.save_project()
            
            # Save project state
            self.save_state_to_json()
            
            # Update UI
            self.update_status_text(f"Test series '{series_name}' created successfully", "green")
            self.main_window.statusBar().showMessage(f"Test series '{series_name}' created successfully.", 5000) # Add status bar message
            self.update_project_tree()
            
        except Exception as e:
            self.main_window.logger.log(f"Error creating test series: {str(e)}", "ERROR")
            self.update_status_text(f"Error creating test series: {str(e)}", "red")
    
    def load_project_metadata(self):
        """Load metadata for the current project"""
        if not self.current_project:
            return
            
        base_dir = self.main_window.project_base_dir.text()
        if not base_dir or not os.path.exists(base_dir):
            return
            
        project_dir = os.path.join(base_dir, self.current_project)
        if not os.path.exists(project_dir):
            return
            
        # Load project metadata
        metadata_file = os.path.join(project_dir, "project_metadata.json")
        if os.path.exists(metadata_file):
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                    self.project_description = metadata.get("description", "")
                    self.main_window.project_description.setPlainText(self.project_description)
                    self.main_window.logger.log(f"Loaded project metadata for '{self.current_project}'")
                    
                    # Find the latest test series by looking at directories
                    latest_series = self.find_latest_test_series(project_dir)
                    if latest_series:
                        self.main_window.test_series_selector.setCurrentText(latest_series["name"])
                        self.main_window.test_series_description.setPlainText(latest_series["description"])
            except Exception as e:
                self.main_window.logger.log(f"Error reading project metadata: {str(e)}", "WARN")
                
    def find_latest_test_series(self, project_dir):
        """Find the latest test series by creation date"""
        try:
            series_dirs = []
            for item in os.listdir(project_dir):
                item_path = os.path.join(project_dir, item)
                if os.path.isdir(item_path):
                    metadata_file = os.path.join(item_path, "series_metadata.json")
                    if os.path.exists(metadata_file):
                        try:
                            with open(metadata_file, 'r') as f:
                                metadata = json.load(f)
                                series_dirs.append({
                                    "name": item,
                                    "description": metadata.get("description", ""),
                                    "created_date": metadata.get("created_date", ""),
                                    "path": item_path
                                })
                        except Exception:
                            # Skip if metadata can't be read
                            pass
            
            # Sort by creation date, newest first
            if series_dirs:
                sorted_series = sorted(series_dirs, 
                                      key=lambda x: x.get("created_date", ""), 
                                      reverse=True)
                return sorted_series[0]
        except Exception as e:
            self.main_window.logger.log(f"Error finding latest test series: {str(e)}", "WARN")
        
        return None
        
    def find_latest_run(self, series_dir):
        """Find the latest run by creation date"""
        try:
            run_dirs = []
            for item in os.listdir(series_dir):
                item_path = os.path.join(series_dir, item)
                if os.path.isdir(item_path):
                    metadata_file = os.path.join(item_path, "run_metadata.json")
                    if os.path.exists(metadata_file):
                        try:
                            with open(metadata_file, 'r') as f:
                                metadata = json.load(f)
                                run_dirs.append({
                                    "name": item,
                                    "description": metadata.get("description", ""),
                                    "created_date": metadata.get("created_date", ""),
                                    "path": item_path
                                })
                        except Exception:
                            # Skip if metadata can't be read
                            pass
            
            # Sort by creation date, newest first
            if run_dirs:
                sorted_runs = sorted(run_dirs, 
                                    key=lambda x: x.get("created_date", ""), 
                                    reverse=True)
                return sorted_runs[0]
        except Exception as e:
            self.main_window.logger.log(f"Error finding latest run: {str(e)}", "WARN")
        
        return None
    
    def load_test_series_metadata(self):
        """Load metadata for the current test series"""
        if not self.current_project or not self.current_test_series:
            return
            
        base_dir = self.main_window.project_base_dir.text()
        if not base_dir or not os.path.exists(base_dir):
            return
            
        series_dir = os.path.join(base_dir, self.current_project, self.current_test_series)
        if not os.path.exists(series_dir):
            return
            
        # Load test series metadata
        series_metadata_file = os.path.join(series_dir, "series_metadata.json")
        if os.path.exists(series_metadata_file):
            try:
                with open(series_metadata_file, 'r') as f:
                    metadata = json.load(f)
                    self.test_series_description = metadata.get("description", "")
                    self.main_window.test_series_description.setPlainText(self.test_series_description)
                    self.main_window.logger.log(f"Loaded test series metadata for '{self.current_test_series}'")
            except Exception as e:
                self.main_window.logger.log(f"Error reading test series metadata: {str(e)}", "WARN")
    
    def get_current_date_string(self):
        """Get the current date as a formatted string"""
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def load_run(self, project_name=None, series_name=None, run_name=None, is_startup_load=False):
        """Load a saved run. If project/series/run names are provided, use them.
        Otherwise, use the current selection in the project tree."""
        # Clear snapshots immediately when starting to load a run
        if hasattr(self.main_window, "load_snapshots_for_run"):
            self.main_window.load_snapshots_for_run(None)
            
        # Get base directory
        base_dir = self.main_window.project_base_dir.text()
        if not base_dir or not os.path.exists(base_dir):
            self.main_window.logger.log("Base directory not set or does not exist.", "WARN")
            self.update_status_text("Error: Base directory not set", "red")
            return

        # Use provided names if available, otherwise get from selection
        if project_name is None or series_name is None or run_name is None:
            # Check if a run is selected in the project tree
            selected_indexes = self.main_window.project_tree.selectedIndexes()
            if not selected_indexes:
                self.main_window.logger.log("No run selected in the project tree.", "WARN")
                self.update_status_text("Error: No run selected", "red")
                return
                
            # Get the selected index for the name column (0)
            name_index = selected_indexes[0]
            if name_index.column() != 0:
                # Get the corresponding name index if we selected description or date column
                name_index = self.main_window.project_model.index(name_index.row(), 0, name_index.parent())
                
            # Get the selected item name
            run_name = self.main_window.project_model.data(name_index)
            
            # Get the parent item (if any)
            parent_index = name_index.parent()
            series_name = None
            if parent_index.isValid():
                # Ensure we get column 0 (name) for the parent
                parent_name_index = self.main_window.project_model.index(parent_index.row(), 0, parent_index.parent())
                series_name = self.main_window.project_model.data(parent_name_index)
                
            # Get grandparent item (if any)
            project_name = None
            if parent_index.isValid():
                grandparent_index = parent_index.parent()
                if grandparent_index and grandparent_index.isValid():
                    # Ensure we get column 0 (name) for the grandparent
                    grandparent_name_index = self.main_window.project_model.index(grandparent_index.row(), 0, grandparent_index.parent())
                    project_name = self.main_window.project_model.data(grandparent_name_index)
                    
            # Check if selection is a run (has both parent and grandparent)
            if project_name is None:
                self.main_window.logger.log("Selection is not a run. Please select a run.", "WARN")
                self.update_status_text("Error: Selected item is not a run", "red")
                return
            
        # Build run directory path
        run_dir = os.path.join(base_dir, project_name, series_name, run_name)
        if not os.path.exists(run_dir):
            self.main_window.logger.log(f"Run directory does not exist: {run_dir}", "ERROR")
            self.update_status_text("Error: Run directory not found", "red")
            return
            
        # Load run metadata
        run_metadata_file = os.path.join(run_dir, "run_metadata.json")
        if os.path.exists(run_metadata_file):
            try:
                with open(run_metadata_file, 'r') as f:
                    metadata = json.load(f)
                    self.run_description = metadata.get("description", "")
                    # Do not populate run UI fields when loading an existing run;
                    # testers/description remain visible in project browser and notes.
            except Exception as e:
                self.main_window.logger.log(f"Error reading run metadata: {str(e)}", "WARN")
                
        # Load project metadata
        project_dir = os.path.join(base_dir, project_name)
        project_metadata_file = os.path.join(project_dir, "project_metadata.json")
        if os.path.exists(project_metadata_file):
            try:
                with open(project_metadata_file, 'r') as f:
                    metadata = json.load(f)
                    self.project_description = metadata.get("description", "")
                    self.main_window.project_description.setText(self.project_description)
            except Exception as e:
                self.main_window.logger.log(f"Error reading project metadata: {str(e)}", "WARN")
                
        # Load test series metadata
        series_dir = os.path.join(base_dir, project_name, series_name)
        series_metadata_file = os.path.join(series_dir, "series_metadata.json")
        if os.path.exists(series_metadata_file):
            try:
                with open(series_metadata_file, 'r') as f:
                    metadata = json.load(f)
                    self.test_series_description = metadata.get("description", "")
                    self.main_window.test_series_description.setText(self.test_series_description)
            except Exception as e:
                self.main_window.logger.log(f"Error reading test series metadata: {str(e)}", "WARN")
                
        # Update UI selections
        if self.main_window.project_selector.findText(project_name) >= 0:
            self.main_window.project_selector.setCurrentText(project_name)
            
        if self.main_window.test_series_selector.findText(series_name) >= 0:
            self.main_window.test_series_selector.setCurrentText(series_name)
            
        # Set current values
        self.current_project = project_name
        self.current_test_series = series_name
        self.current_run = run_name
        
        # Update global configuration with the last loaded run
        if hasattr(self.main_window, 'config'):
            self.main_window.config["last_project"] = project_name
            self.main_window.config["last_test_series"] = series_name
            self.main_window.config["last_run"] = run_name
            self.main_window.save_config()
        
        # Load sensor configuration from the run directory
        self.load_sensors_from_run(run_dir)

        # Load CSV configuration from the run directory if it exists
        if hasattr(self.main_window, 'load_virtual_sensors'):
            self.main_window.load_virtual_sensors(is_run_load=True)

        # Update sidebar status
        self.main_window.sidebar_project_name.setText(project_name)
        self.main_window.sidebar_test_series.setText(series_name)
        # Only update status if not currently running
        if not (hasattr(self.main_window, 'running') and self.main_window.running):
            self.main_window.sidebar_ready_status.setText("Ready")
            self.main_window.sidebar_ready_status.setStyleSheet("color: green;")
        
        # Update status
        self.update_status_text(f"Run '{run_name}' loaded successfully", "green")
        if hasattr(self.main_window, "update_run_context_text"):
            self.main_window.update_run_context_text("Loaded run", run_name)
        
        # Update project tree to show highlighting for the loaded run
        self.update_project_tree()
        
        # Load historical graph data for this run so the Graphs tab shows the selected run
        if hasattr(self.main_window, 'data_collection_controller'):
            try:
                dc_controller = self.main_window.data_collection_controller
                dc_controller.csv_historical_data = dc_controller.read_historical_data_from_csv(run_dir)
                if dc_controller.csv_historical_data and hasattr(self.main_window, 'graph_controller'):
                    # Plot historical data using the general method (plots all sensors)
                    # Pass run_dir so automation events can be loaded
                    self.main_window.graph_controller.plot_historical_data(dc_controller.csv_historical_data, run_dir=run_dir)
                    
                    self.main_window.logger.log(f"Plotted historical graph data from {run_dir}")

                    # Update dashboard metrics with the last available data point
                    if hasattr(self.main_window, 'update_dashboard_metrics'):
                        last_row = {'_source': 'replay'}
                        for sensor_id, data in dc_controller.csv_historical_data.items():
                            if data.get('value') and len(data['value']) > 0:
                                last_row[sensor_id] = data['value'][-1]
                                if data.get('time') and len(data['time']) > 0:
                                    last_row['timestamp'] = data['time'][-1]
                        
                        # Only update if we found some sensor values
                        if len(last_row) > 1:
                            # Use QTimer to ensure UI is ready after load (slightly longer delay for startup)
                            from PyQt6.QtCore import QTimer
                            def delayed_update():
                                self.main_window.logger.log("Triggering delayed dashboard metric update for all sensors", "DEBUG")
                                self.main_window.update_dashboard_metrics(last_row)
                            
                            QTimer.singleShot(1000, delayed_update)
                            self.main_window.logger.log("Preloaded dashboard metrics from last run", "DEBUG")
                else:
                    self.main_window.logger.log(f"No historical graph data found in {run_dir}", "INFO")
            except Exception as e:
                self.main_window.logger.log(f"Error loading historical graph data: {str(e)}", "WARN")
        
        # Load control run configuration from the run directory
        if hasattr(self.main_window, 'control_run_controller'):
            try:
                if self.main_window.control_run_controller.load_control_run_config(run_dir):
                    self.main_window.logger.log(f"Control run configuration loaded from {run_dir}")
                    
                    # Update the UI with the loaded control run info
                    if hasattr(self.main_window, 'populate_control_run_selector'):
                        self.main_window.populate_control_run_selector()
                        
                    # Set the control run selector to the loaded control run
                    if hasattr(self.main_window, 'control_run_selector'):
                        control_run_name = self.main_window.control_run_controller.control_run_name
                        if control_run_name:
                            index = self.main_window.control_run_selector.findText(control_run_name)
                            if index >= 0:
                                self.main_window.control_run_selector.setCurrentIndex(index)
                                
                    # Set the time offset in the UI
                    if hasattr(self.main_window, 'control_run_time_offset'):
                        self.main_window.control_run_time_offset.setValue(
                            self.main_window.control_run_controller.time_offset
                        )
            except Exception as e:
                self.main_window.logger.log(f"Error loading control run configuration: {str(e)}", "WARN")
        
        # Call main window's load_project_state method if it exists
        if hasattr(self.main_window, 'load_project_state'):
            try:
                self.main_window.load_project_state(run_dir)
                self.main_window.logger.log(f"Project state loaded from {run_dir}")
            except Exception as e:
                self.main_window.logger.log(f"Error loading project state: {str(e)}", "ERROR")
        
        # Update Automation Controller with the new run path for sequences
        if hasattr(self.main_window, 'automation_controller'):
            try:
                self.main_window.automation_controller.update_sequence_path(run_dir)
                self.main_window.logger.log(f"Automation sequences updated for run: {run_dir}")
            except Exception as e:
                 self.main_window.logger.log(f"Error updating automation sequence path: {str(e)}", "ERROR")
        
        # Load overlays if camera controller exists
        if hasattr(self.main_window, 'camera_controller'):
            try:
                self.main_window.camera_controller.load_overlays_from_run(run_dir)
            except Exception as e:
                self.main_window.logger.log(f"Error loading overlays from run: {str(e)}", "WARN")
        
        # Update optical sensor settings with run directory
        if hasattr(self.main_window, 'sensor_controller'):
            try:
                sensor_controller = self.main_window.sensor_controller
                if hasattr(sensor_controller, 'optical_sensor_interfaces'):
                    # Update all connected optical sensors with the run directory
                    for sensor_name, interface in sensor_controller.optical_sensor_interfaces.items():
                        if interface and interface.is_connected():
                            # Get current settings and update with run directory
                            settings = {"run_directory": run_dir}
                            interface.update_settings(settings)
                    self.main_window.logger.log(f"Updated optical sensor settings with run directory: {run_dir}", "INFO")
            except Exception as e:
                self.main_window.logger.log(f"Error updating optical sensor settings: {str(e)}", "WARN")

        # Initialize dashboard replay with the loaded run so dashboard matches Graphs tab
        if hasattr(self.main_window, "on_replay_load_clicked"):
            try:
                self.main_window.on_replay_load_clicked()
            except Exception as e:
                self.main_window.logger.log(f"Error initializing replay after loading run: {str(e)}", "WARN")

        # Also trigger a refresh of the main graph based on current UI selections
        # We do this AFTER on_replay_load_clicked so dashboard_start_time is set
        if hasattr(self.main_window, 'update_graph'):
            self.main_window.update_graph()

        # Ensure notes tab reflects the loaded run
        if hasattr(self.main_window, "notes_controller"):
            try:
                # Force reload of the note for this run
                self.main_window.notes_controller.document_loaded = False
                self.main_window.notes_controller.load_note()
            except Exception as e:
                self.main_window.logger.log(f"Error loading notes for run: {str(e)}", "WARN")

        # Save the project state to JSON to ensure it's available next time
        self.save_state_to_json()

        # If this is a startup load, override with global settings from configuration
        # This prevents run-specific settings from overwriting global user preferences on startup
        if is_startup_load and hasattr(self.main_window, 'load_settings'):
            self.main_window.logger.log("Startup load: Overriding with global settings", "INFO")
            self.main_window.load_settings(is_startup_load=True, defer_hardware_init=True)

        # Emit status changed signal
        self.status_changed.emit()
    
    def save_project(self):
        """Save the current project and test series details"""
        # If in replay mode, don't overwrite metadata in the run/project folders.
        # This keeps the history of that specific experiment secure.
        if getattr(self.main_window, 'is_replay_mode', False):
            # We don't save project/series metadata here, but we could still 
            # save the "last used" state to the global config if we wanted.
            # For now, let's just return to satisfy the "impossible to change" requirement.
            return

        # Set flag to prevent recursion
        if self.is_saving:
            return
            
        self.is_saving = True
        try:
            # Get the base directory, project name and test series name
            base_dir = self.main_window.project_base_dir.text()
            project_name = self.main_window.project_selector.currentText().strip()
            series_name = self.main_window.test_series_selector.currentText().strip()
            
            if not base_dir or not os.path.exists(base_dir):
                self.main_window.logger.log("Base directory not set or does not exist.", "WARN")
                self.update_status_text("Error: Base directory not set", "red")
                return
                
            if not project_name:
                self.main_window.logger.log("Project name not set.", "WARN")
                self.update_status_text("Error: Project name not set", "red")
                return
                
            # Update current project and descriptions
            self.current_project = project_name
            self.project_description = self.main_window.project_description.toPlainText()
            
            # Build project directory path
            project_dir = os.path.join(base_dir, project_name)
            
            # Create project directory if it doesn't exist
            if not os.path.exists(project_dir):
                try:
                    os.makedirs(project_dir, exist_ok=True)
                    self.main_window.logger.log(f"Created project directory: {project_dir}")
                except Exception as e:
                    self.main_window.logger.log(f"Error creating project directory: {str(e)}", "ERROR")
                    self.update_status_text(f"Error creating project directory: {str(e)}", "red")
                    return
                    
            # Save project metadata
            try:
                metadata = {
                    "name": project_name,
                    "description": self.project_description,
                    "created_date": self.get_current_date_string(),
                    "updated_date": self.get_current_date_string()
                }
                
                with open(os.path.join(project_dir, "project_metadata.json"), 'w') as f:
                    json.dump(metadata, f, indent=4)
                    
                self.main_window.logger.log(f"Saved project metadata for '{project_name}'")
                
            except Exception as e:
                self.main_window.logger.log(f"Error saving project metadata: {str(e)}", "ERROR")
                self.update_status_text(f"Error saving project metadata: {str(e)}", "red")
                return
                
            # Handle test series if specified
            if series_name:
                # Update current test series and description
                self.current_test_series = series_name
                self.test_series_description = self.main_window.test_series_description.toPlainText()
                
                # Build test series directory path
                series_dir = os.path.join(project_dir, series_name)
                
                # Create test series directory if it doesn't exist
                if not os.path.exists(series_dir):
                    try:
                        os.makedirs(series_dir, exist_ok=True)
                        self.main_window.logger.log(f"Created test series directory: {series_dir}")
                    except Exception as e:
                        self.main_window.logger.log(f"Error creating test series directory: {str(e)}", "ERROR")
                        self.update_status_text(f"Error creating test series directory: {str(e)}", "red")
                        return
                        
                # Save test series metadata
                try:
                    metadata = {
                        "name": series_name,
                        "description": self.test_series_description,
                        "created_date": self.get_current_date_string(),
                        "updated_date": self.get_current_date_string()
                    }
                    
                    with open(os.path.join(series_dir, "series_metadata.json"), 'w') as f:
                        json.dump(metadata, f, indent=4)
                        
                    self.main_window.logger.log(f"Saved test series metadata for '{series_name}'")
                    
                except Exception as e:
                    self.main_window.logger.log(f"Error saving test series metadata: {str(e)}", "ERROR")
                    self.update_status_text(f"Error saving test series metadata: {str(e)}", "red")
                    return
                    
            # Save run description if provided
            run_description = self.main_window.run_description.toPlainText()
            if run_description:
                self.run_description = run_description
                
            # Update UI status
            self.update_status_text("Project settings saved successfully", "green")
            
            # Update sidebar status
            self.main_window.sidebar_project_name.setText(project_name)
            if series_name:
                self.main_window.sidebar_test_series.setText(series_name)
                
            # Don't trigger tree updates for auto-saves to avoid recursion
            if not self.auto_save_pending:
                # Update project tree
                self.update_project_tree()
            
            # Emit status changed signal
            self.status_changed.emit()
            
            # Save project state to JSON
            self.save_state_to_json()
            
        finally:
            # Reset flags
            self.is_saving = False
            self.auto_save_pending = False
    
    def apply_project_settings(self):
        """Apply the current project settings - updates status and validates the settings"""
        # Get the base directory, project name and test series name
        base_dir = self.main_window.project_base_dir.text()
        project_name = self.main_window.project_selector.currentText().strip()
        series_name = self.main_window.test_series_selector.currentText().strip()
        
        # Validation
        errors = []
        if not base_dir:
            errors.append("Base directory not set")
        elif not os.path.exists(base_dir):
            errors.append("Base directory does not exist")
            
        if not project_name:
            errors.append("Project name not set")
        
        if not series_name:
            errors.append("Test series not set")
            
        # Update status based on validation
        if errors:
            error_msg = ", ".join(errors)
            self.update_status_text(f"Error: {error_msg}", "red")
            self.main_window.sidebar_ready_status.setText("Not Ready")
            self.main_window.sidebar_ready_status.setStyleSheet("color: orange;")
            return False
        
        # Save the settings
        self.save_project()
        
        # Update status
        self.update_status_text("Project settings applied successfully", "green")
        # Only update status if not currently running
        if not (hasattr(self.main_window, 'running') and self.main_window.running):
            self.main_window.sidebar_ready_status.setText("Ready")
            self.main_window.sidebar_ready_status.setStyleSheet("color: green;")
        
        # Set current project and test series
        self.current_project = project_name
        self.current_test_series = series_name
        self.project_description = self.main_window.project_description.toPlainText()
        self.test_series_description = self.main_window.test_series_description.toPlainText()
        self.run_description = self.main_window.run_description.toPlainText()
        
        # Set sidebar status
        self.main_window.sidebar_project_name.setText(project_name)
        self.main_window.sidebar_test_series.setText(series_name)
        
        # Create a timestamp for the run name if it doesn't exist
        import datetime
        self.current_run = datetime.datetime.now().strftime("Run_%Y%m%d_%H%M%S")
        
        # Emit status changed signal
        self.status_changed.emit()
        
        return True
    
    def on_project_selected(self, project_name):
        """Handle project selection change"""
        self.current_project = project_name
        
        # Get base directory
        base_dir = self.main_window.project_base_dir.text()
        if not base_dir or not os.path.exists(base_dir):
            return
            
        # Load project description if project exists
        if project_name:
            project_dir = os.path.join(base_dir, project_name)
            if os.path.exists(project_dir):
                # Load project metadata
                metadata_file = os.path.join(project_dir, "project_metadata.json")
                if os.path.exists(metadata_file):
                    try:
                        with open(metadata_file, 'r') as f:
                            metadata = json.load(f)
                            self.project_description = metadata.get("description", "")
                            self.main_window.project_description.setPlainText(self.project_description)
                    except Exception as e:
                        self.main_window.logger.log(f"Error reading project metadata: {str(e)}", "WARN")
                        
                # Update sidebar status
                self.main_window.sidebar_project_name.setText(project_name)
                
                # Update test series selector
                self.update_test_series_selector()
                
                # Save to config for next startup
                if hasattr(self.main_window, 'config'):
                    self.main_window.config["last_project"] = project_name
                    self.main_window.save_config()

                # Also save to project_state.json
                self.save_state_to_json()
            
        # Update group box colors
        if hasattr(self.main_window, 'update_project_group_box_colors'):
            self.main_window.update_project_group_box_colors()
            
        # Emit status changed signal
        self.status_changed.emit()
    
    def on_test_series_selected(self, series_name):
        """Handle test series selection change"""
        self.current_test_series = series_name
        
        # Get base directory and project
        base_dir = self.main_window.project_base_dir.text()
        project_name = self.main_window.project_selector.currentText().strip()
        
        if not base_dir or not os.path.exists(base_dir) or not project_name:
            return
            
        # Load test series description if it exists
        if series_name:
            series_dir = os.path.join(base_dir, project_name, series_name)
            if os.path.exists(series_dir):
                # Load test series metadata
                metadata_file = os.path.join(series_dir, "series_metadata.json")
                if os.path.exists(metadata_file):
                    try:
                        with open(metadata_file, 'r') as f:
                            metadata = json.load(f)
                            self.test_series_description = metadata.get("description", "")
                            self.main_window.test_series_description.setPlainText(self.test_series_description)
                    except Exception as e:
                        self.main_window.logger.log(f"Error reading test series metadata: {str(e)}", "WARN")
                        
                # Update sidebar status
                self.main_window.sidebar_test_series.setText(series_name)
                
                # Save to config for next startup
                if hasattr(self.main_window, 'config'):
                    self.main_window.config["last_test_series"] = series_name
                    self.main_window.save_config()
                    
                # Also save to project_state.json
                self.save_state_to_json()
            
        # Update group box colors
        if hasattr(self.main_window, 'update_project_group_box_colors'):
            self.main_window.update_project_group_box_colors()
            
        # Emit status changed signal
        self.status_changed.emit()
    
    def get_status(self):
        """
        Get the status of the project component.
        
        Returns:
            tuple: (StatusState, tooltip_string)
                StatusState: ERROR if project settings incomplete
                            READY if project settings complete
                tooltip_string: Description of the current status
        """
        # Get the current status
        status = self.check_project_status()
        
        if status == StatusState.ERROR:
            return (StatusState.ERROR, "Project: Missing required settings")
        
        # Project is ready
        tooltip = f"Project: {self.current_project or 'None'}"
        if self.current_test_series:
            tooltip += f", Series: {self.current_test_series}"
            
        return (StatusState.READY, tooltip)
    
    def save_state_to_json(self):
        """
        Save the current project, test series, and run details to a JSON file
        in the project directory for future retrieval.
        """
        # If in replay mode, don't overwrite the project_state.json in the project folder
        # to keep the existing project hierarchy secure.
        if getattr(self.main_window, 'is_replay_mode', False):
            return

        if not self.current_project:
            self.main_window.logger.log("Cannot save project state - no active project", "WARN")
            return
            
        # Get base directory from settings
        base_dir = self.main_window.settings.value("base_directory", "")
        if not base_dir:
            self.main_window.logger.log("Cannot save project state - base directory not set", "WARN")
            return
            
        # Create project directory path
        project_dir = os.path.join(base_dir, self.current_project)
        
        # Check if project directory exists
        if not os.path.exists(project_dir):
            self.main_window.logger.log(f"Project directory does not exist: {project_dir}", "WARN")
            return
            
        # Get testers value
        run_testers = ""
        if hasattr(self.main_window, 'run_testers'):
            run_testers = self.main_window.run_testers.text().strip()
            
        # Update descriptions from UI
        if hasattr(self.main_window, 'project_description'):
            self.project_description = self.main_window.project_description.toPlainText()
            
        if hasattr(self.main_window, 'test_series_description'):
            self.test_series_description = self.main_window.test_series_description.toPlainText()
            
        if hasattr(self.main_window, 'run_description'):
            self.run_description = self.main_window.run_description.toPlainText()
            
        # Create state data dictionary
        state_data = {
            "project": {
                "name": self.current_project,
                "description": self.project_description
            },
            "test_series": {
                "name": self.current_test_series,
                "description": self.test_series_description
            },
            "run": {
                "name": self.current_run,
                "description": self.run_description,
                "testers": run_testers
            }
        }
        
        # Save to project_state.json in the project directory
        state_file = os.path.join(project_dir, "project_state.json")
        try:
            with open(state_file, 'w') as f:
                json.dump(state_data, f, indent=4)
            self.main_window.logger.log(f"Project state saved to {state_file}")
        except Exception as e:
            self.main_window.logger.log(f"Error saving project state: {str(e)}", "ERROR")
    
    def load_state_from_json(self, project_path):
        """
        Load project/test/run details from project_state.json for the given project path.
        
        Args:
            project_path: Path to the project directory
        """
        if not project_path or not os.path.exists(project_path):
            self.main_window.logger.log(f"Cannot load project state - invalid path: {project_path}", "WARN")
            return
            
        # Look for project_state.json
        state_file = os.path.join(project_path, "project_state.json")
        if not os.path.exists(state_file):
            self.main_window.logger.log(f"No saved state found at {state_file}", "INFO")
            return
            
        try:
            with open(state_file, 'r') as f:
                state_data = json.load(f)
                
            # Extract project info
            if "project" in state_data:
                self.current_project = state_data["project"].get("name", "")
                self.project_description = state_data["project"].get("description", "")
                
                # Update project selector dropdown if it exists
                if hasattr(self.main_window, 'project_selector') and self.current_project:
                    # First ensure the project selector is updated with available projects
                    self.update_project_selector()
                    
                    # Now try to set the current project
                    index = self.main_window.project_selector.findText(self.current_project)
                    if index >= 0:
                        self.main_window.project_selector.setCurrentIndex(index)
                        self.main_window.logger.log(f"Set project selector to: {self.current_project}")
                    else:
                        self.main_window.logger.log(f"Project '{self.current_project}' not found in selector", "WARN")
                
                # Update UI if fields exist
                if hasattr(self.main_window, 'project_name'):
                    self.main_window.project_name.setText(self.current_project)
                if hasattr(self.main_window, 'project_description'):
                    self.main_window.project_description.setPlainText(self.project_description)
                    
            # Extract test series info
            if "test_series" in state_data:
                self.current_test_series = state_data["test_series"].get("name", "")
                self.test_series_description = state_data["test_series"].get("description", "")
                
                # Update test series selector dropdown if it exists
                if hasattr(self.main_window, 'test_series_selector') and self.current_test_series:
                    # First update the test series selector with available series
                    self.update_test_series_selector()
                    
                    # Now try to set the current test series
                    index = self.main_window.test_series_selector.findText(self.current_test_series)
                    if index >= 0:
                        self.main_window.test_series_selector.setCurrentIndex(index)
                        self.main_window.logger.log(f"Set test series selector to: {self.current_test_series}")
                    else:
                        self.main_window.logger.log(f"Test series '{self.current_test_series}' not found in selector", "WARN")
                
                # Update UI if fields exist
                if hasattr(self.main_window, 'test_series_name'):
                    self.main_window.test_series_name.setText(self.current_test_series)
                if hasattr(self.main_window, 'test_series_description'):
                    self.main_window.test_series_description.setPlainText(self.test_series_description)
                    
            # Extract run info
            if "run" in state_data:
                self.current_run = state_data["run"].get("name", "")
                self.run_description = state_data["run"].get("description", "")
                run_testers = state_data["run"].get("testers", "")
                
                # Update UI if fields exist
                if hasattr(self.main_window, 'run_name'):
                    self.main_window.run_name.setText(self.current_run)
                if hasattr(self.main_window, 'run_description'):
                    self.main_window.run_description.setPlainText(self.run_description)
                if hasattr(self.main_window, 'run_testers'):
                    self.main_window.run_testers.setText(run_testers)
            
            if hasattr(self.main_window, "update_run_context_text"):
                self.main_window.update_run_context_text(
                    "Loaded run" if self.current_run else None,
                    self.current_run
                )
                    
            # Emit status changed signal
            self.status_changed.emit()
            
            self.main_window.logger.log(f"Project state loaded from {state_file}")
            
        except Exception as e:
            self.main_window.logger.log(f"Error loading project state: {str(e)}", "ERROR")
    
    def prepare_run_directory(self):
        """
        Prepare the run directory for data acquisition.
        Returns: the run directory path or None if failed
        """
        base_dir = self.main_window.project_base_dir.text()
        project_name = self.main_window.project_selector.currentText()
        series_name = self.main_window.test_series_selector.currentText()
        
        # Ensure values are not empty
        if not base_dir or not project_name or not series_name:
            self.main_window.logger.log("Project/series details are incomplete. Cannot create run directory.", "ERROR")
            return None
        
        # Get current run description
        run_description = self.main_window.run_description.toPlainText().strip()
        run_testers = self.main_window.run_testers.text().strip()
        
        if not run_description:
            self.main_window.logger.log("Run description is required. Please enter a description.", "ERROR")
            return None
            
        if not run_testers:
            self.main_window.logger.log("Testers are required. Please enter tester names.", "ERROR")
            return None
        
        # Update current project and test series 
        self.current_project = project_name
        self.current_test_series = series_name
        
        # Update descriptions from the UI
        if hasattr(self.main_window, 'project_description'):
            self.project_description = self.main_window.project_description.toPlainText()
            
        if hasattr(self.main_window, 'test_series_description'):
            self.test_series_description = self.main_window.test_series_description.toPlainText()
        
        # Create project directory path
        project_dir = os.path.join(base_dir, project_name)
        
        # Create project directory if it doesn't exist
        if not os.path.exists(project_dir):
            try:
                os.makedirs(project_dir, exist_ok=True)
                self.main_window.logger.log(f"Created project directory: {project_dir}")
            except Exception as e:
                self.main_window.logger.log(f"Error creating project directory: {str(e)}", "ERROR")
                return None
                
        # Save project metadata
        try:
            metadata = {
                "name": project_name,
                "description": self.project_description,
                "created_date": self.get_current_date_string(),
                "updated_date": self.get_current_date_string()
            }
            
            with open(os.path.join(project_dir, "project_metadata.json"), 'w') as f:
                json.dump(metadata, f, indent=4)
                
            self.main_window.logger.log(f"Saved project metadata for '{project_name}'")
            
        except Exception as e:
            self.main_window.logger.log(f"Error saving project metadata: {str(e)}", "ERROR")
            
        # Create test series directory path
        series_dir = os.path.join(project_dir, series_name)
        
        # Create test series directory if it doesn't exist
        if not os.path.exists(series_dir):
            try:
                os.makedirs(series_dir, exist_ok=True)
                self.main_window.logger.log(f"Created test series directory: {series_dir}")
            except Exception as e:
                self.main_window.logger.log(f"Error creating test series directory: {str(e)}", "ERROR")
                return None
                
        # Save test series metadata
        try:
            metadata = {
                "name": series_name,
                "description": self.test_series_description,
                "created_date": self.get_current_date_string(),
                "updated_date": self.get_current_date_string()
            }
            
            with open(os.path.join(series_dir, "series_metadata.json"), 'w') as f:
                json.dump(metadata, f, indent=4)
                
            self.main_window.logger.log(f"Saved test series metadata for '{series_name}'")
            
        except Exception as e:
            self.main_window.logger.log(f"Error saving test series metadata: {str(e)}", "ERROR")
        
        # Create timestamped run name
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        run_name = f"Run_{timestamp}"
        
        # Create run directory path
        run_dir = os.path.join(series_dir, run_name)
        
        # Create directory if it doesn't exist
        if not os.path.exists(run_dir):
            try:
                os.makedirs(run_dir)
                self.main_window.logger.log(f"Created run directory: {run_dir}")
            except Exception as e:
                self.main_window.logger.log(f"Error creating run directory: {str(e)}", "ERROR")
                return None
        
        # Save run metadata
        self.run_description = run_description  # Save in controller instance
        self.current_project = project_name
        self.current_test_series = series_name
        self.current_run = run_name
        
        # Save run metadata to JSON
        metadata = {
            "description": run_description,
            "timestamp": timestamp,
            "project": project_name,
            "series": series_name,
            "testers": run_testers
        }
        
        try:
            with open(os.path.join(run_dir, "run_metadata.json"), 'w') as f:
                json.dump(metadata, f, indent=4)
        except Exception as e:
            self.main_window.logger.log(f"Error saving run metadata: {str(e)}", "WARN")
        
        # Update sidebar status
        self.main_window.sidebar_project_name.setText(project_name)
        self.main_window.sidebar_test_series.setText(series_name)
        
        # Save project state to JSON
        self.save_state_to_json()
        
        # Save current sensor configuration to the run directory
        self.save_sensors_to_run(run_dir)
        
        # Save current CSV and virtual sensor configuration to the run directory
        if hasattr(self.main_window, 'save_virtual_sensors'):
             self.main_window.save_virtual_sensors()
        
        # Update Automation Controller with the new run path (copying sequences if needed)
        if hasattr(self.main_window, 'automation_controller'):
            try:
                self.main_window.automation_controller.update_sequence_path(run_dir)
                self.main_window.logger.log(f"Automation sequences context updated for new run: {run_dir}")
            except Exception as e:
                self.main_window.logger.log(f"Error updating automation controller: {str(e)}", "WARN")
        
        # Save control run configuration and copy control run data
        if hasattr(self.main_window, 'control_run_controller'):
            try:
                # Save the control run config to the new run directory
                self.main_window.control_run_controller.save_control_run_config(run_dir)
                
                # Copy the control run data CSV to the new run directory
                self.main_window.control_run_controller.copy_control_run_data_to_run(run_dir)
                
                self.main_window.logger.log(f"Control run configuration and data saved to run directory", "INFO")
            except Exception as e:
                self.main_window.logger.log(f"Error saving control run data: {str(e)}", "WARN")
        
        # Save camera overlays to the run directory
        if hasattr(self.main_window, 'camera_controller'):
            try:
                self.main_window.camera_controller.save_overlays_to_run()
            except Exception as e:
                self.main_window.logger.log(f"Error saving overlays to run: {str(e)}", "WARN")
        
        # Update optical sensor settings with run directory
        if hasattr(self.main_window, 'sensor_controller'):
            try:
                sensor_controller = self.main_window.sensor_controller
                if hasattr(sensor_controller, 'optical_sensor_interfaces'):
                    # Update all connected optical sensors with the new run directory
                    for sensor_name, interface in sensor_controller.optical_sensor_interfaces.items():
                        if interface and interface.is_connected():
                            # Get current settings and update with run directory
                            settings = {"run_directory": run_dir}
                            interface.update_settings(settings)
                    self.main_window.logger.log(f"Updated optical sensor settings with run directory: {run_dir}", "INFO")
            except Exception as e:
                self.main_window.logger.log(f"Error updating optical sensor settings: {str(e)}", "WARN")
        
        # Save current project and test series in config for next startup
        if hasattr(self.main_window, 'config'):
            self.main_window.config["last_project"] = project_name
            self.main_window.config["last_test_series"] = series_name
            self.main_window.config["last_run"] = run_name
            self.main_window.save_config()
            self.main_window.logger.log(f"Updated config with last project: {project_name}, last test series: {series_name}, last run: {run_name}")
        
        # Refresh the project browser and highlight the new run
        self.update_project_tree()
        self.select_tree_item(project_name, series_name, run_name)
                
        return run_dir
    
    def update_run_metadata(self, run_dir, updates: dict):
        """
        Merge the provided fields into a run's metadata JSON.

        Args:
            run_dir: Path to the run directory.
            updates: Dict of fields to merge into run_metadata.json.
        """
        if not run_dir or not os.path.exists(run_dir):
            self.main_window.logger.log("Cannot update run metadata - invalid run directory", "WARN")
            return

        run_metadata_file = os.path.join(run_dir, "run_metadata.json")
        try:
            current = {}
            if os.path.exists(run_metadata_file):
                with open(run_metadata_file, 'r') as f:
                    current = json.load(f)

            current.update(updates or {})
            with open(run_metadata_file, 'w') as f:
                json.dump(current, f, indent=4)

            self.main_window.logger.log(f"Updated run metadata: {run_metadata_file}", "INFO")
        except Exception as e:
            self.main_window.logger.log(f"Error updating run metadata: {str(e)}", "WARN")

    def get_run_metadata(self, run_dir=None):
        """
        Read run_metadata.json for the given run directory (or current run).

        Args:
            run_dir: Optional override for run directory.

        Returns:
            dict with metadata or {} if missing/error.
        """
        try:
            if not run_dir:
                run_dir = self.get_current_run_directory()
            if not run_dir:
                return {}
            meta_path = os.path.join(run_dir, "run_metadata.json")
            if not os.path.exists(meta_path):
                return {}
            with open(meta_path, "r") as f:
                return json.load(f) or {}
        except Exception as e:
            self.main_window.logger.log(f"Error reading run metadata: {str(e)}", "WARN")
            return {}
    
    def save_sensors_to_run(self, run_dir):
        """
        Save current sensor configuration to the run directory
        
        Args:
            run_dir: Path to the run directory
        """
        if not run_dir or not os.path.exists(run_dir):
            self.main_window.logger.log("Cannot save sensors - invalid run directory", "WARN")
            return
            
        # Call the sensor controller's save_sensors method
        # The updated method will detect the current run and save to that location
        if hasattr(self.main_window, 'sensor_controller'):
            self.main_window.logger.log(f"Saving sensor configuration to run directory: {run_dir}")
            self.main_window.sensor_controller.save_sensors()
        else:
            self.main_window.logger.log("Cannot save sensors - sensor controller not available", "WARN")
            
    def load_sensors_from_run(self, run_dir):
        """
        Load sensor configuration from a run directory
        
        Args:
            run_dir: Path to the run directory
        """
        if not run_dir or not os.path.exists(run_dir):
            self.main_window.logger.log("Cannot load sensors - invalid run directory", "WARN")
            return
            
        # Check if sensors.json exists in the run directory
        sensors_file = os.path.join(run_dir, "sensors.json")
        if not os.path.exists(sensors_file):
            self.main_window.logger.log(f"No sensor configuration found in run directory: {run_dir}", "INFO")
            return
            
        # Call the sensor controller's load_sensors method
        # The updated method will load from the run directory
        if hasattr(self.main_window, 'sensor_controller'):
            self.main_window.logger.log(f"Loading sensor configuration from run directory: {run_dir}")
            # The current_run is already set before this method is called in load_run
            # so sensors will load from the correct directory
            self.main_window.sensor_controller.load_sensors()
        else:
            self.main_window.logger.log("Cannot load sensors - sensor controller not available", "WARN")
    
    def check_project_status(self):
        """
        Check if all required project fields are filled and update status accordingly.
        Returns StatusState (ERROR, READY, or OPTIONAL)
        """
        # Get the base directory, project name and test series name
        base_dir = self.main_window.project_base_dir.text().strip()
        project_name = self.main_window.project_selector.currentText().strip()
        series_name = self.main_window.test_series_selector.currentText().strip()
        run_description = self.main_window.run_description.toPlainText().strip()
        run_testers = self.main_window.run_testers.text().strip()
        
        # Update sidebar with current project and test series names
        if project_name:
            self.main_window.sidebar_project_name.setText(project_name)
        else:
            self.main_window.sidebar_project_name.setText("None")
            
        if series_name:
            self.main_window.sidebar_test_series.setText(series_name)
        else:
            self.main_window.sidebar_test_series.setText("None")
        
        # Update group box colors
        if hasattr(self.main_window, 'update_project_group_box_colors'):
            self.main_window.update_project_group_box_colors()
        
        # Check if all fields are filled
        if not base_dir or not os.path.exists(base_dir):
            self.main_window.project_status = StatusState.ERROR
            return StatusState.ERROR
            
        if not project_name:
            self.main_window.project_status = StatusState.ERROR
            return StatusState.ERROR
            
        if not series_name:
            self.main_window.project_status = StatusState.ERROR
            return StatusState.ERROR
            
        # Only require run description if we're not currently running
        # This allows the system to be ready to start if everything else is set
        # but won't force users to enter a description immediately after stopping
        if not run_description and not self.main_window.running:
            self.main_window.project_status = StatusState.ERROR
            return StatusState.ERROR
            
        # Check if testers field is filled
        if not run_testers and not self.main_window.running:
            self.main_window.project_status = StatusState.ERROR
            return StatusState.ERROR
            
        # All fields are filled, project is ready
        self.main_window.project_status = StatusState.READY
        return StatusState.READY
    
    def validate_run_settings(self):
        """
        Validate settings before starting a run.
        Returns True if all settings are valid, False otherwise.
        """
        # Get the base directory, project name and test series name
        base_dir = self.main_window.project_base_dir.text().strip()
        project_name = self.main_window.project_selector.currentText().strip()
        series_name = self.main_window.test_series_selector.currentText().strip()
        run_description = self.main_window.run_description.toPlainText().strip()
        run_testers = self.main_window.run_testers.text().strip()
        
        # Check base directory
        if not base_dir or not os.path.exists(base_dir):
            self.main_window.statusBar().showMessage("Error: Base directory is not set or doesn't exist")
            return False
        
        # Check project name
        if not project_name:
            self.main_window.statusBar().showMessage("Error: Project name is not set")
            return False
        
        # Check series name
        if not series_name:
            self.main_window.statusBar().showMessage("Error: Test series is not set")
            return False
        
        # Check run description
        if not run_description:
            self.main_window.statusBar().showMessage("Error: Run description is required")
            return False
            
        # Check testers field
        if not run_testers:
            self.main_window.statusBar().showMessage("Error: Testers field is required")
            return False
        
        # Check if we have at least one sensor configured
        if hasattr(self.main_window, 'sensor_controller') and hasattr(self.main_window.sensor_controller, 'sensors'):
            if not self.main_window.sensor_controller.sensors:
                self.main_window.statusBar().showMessage("Error: No sensors configured")
                return False
        
        # Check if a data collection controller is available
        if not hasattr(self.main_window, 'data_collection_controller'):
            self.main_window.statusBar().showMessage("Error: Data collection controller not available")
            return False
        
        # All validation passed
        return True
    
    def export_project(self):
        """
        Export project data based on user selection.
        
        If no item is selected in the project browser, the user is prompted to select what to export.
        If an item is selected, the user is asked to confirm exporting that selection.
        
        The export includes all relevant folders and files in a compressed zip file.
        """
        # Import necessary modules at the beginning
        import shutil
        import zipfile
        from PyQt6.QtWidgets import QMessageBox, QCheckBox, QFileDialog, QDialog, QVBoxLayout, QLabel, QPushButton, QProgressDialog, QHBoxLayout
        from PyQt6.QtCore import Qt
        
        # Check if we have stored selection information
        if not self.last_selected_type or not self.last_selected_project:
            QMessageBox.information(
                self.main_window,
                "Select Item",
                "Please select a project, test series, or run in the Project Browser to export."
            )
            return
        
        # Use the stored selection information
        export_type = self.last_selected_type
        export_project = self.last_selected_project
        export_series = self.last_selected_series
        export_run = self.last_selected_run
        
        # Get base directory
        base_dir = self.main_window.project_base_dir.text()
        if not base_dir or not os.path.exists(base_dir):
            QMessageBox.warning(
                self.main_window,
                "Export Error",
                "Please set a valid base directory first."
            )
            return
            
        # Create confirmation message
        if export_type == "run":
            message = f"Export run '{export_run}' from test series '{export_series}' in project '{export_project}'?"
        elif export_type == "series":
            message = f"Export test series '{export_series}' from project '{export_project}'?"
        else:
            message = f"Export project '{export_project}'?"
            
        # Create confirm dialog with checkbox for including videos
        dialog = QDialog(self.main_window)
        dialog.setWindowTitle("Confirm Export")
        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Add confirmation message
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)
        
        # Add checkbox for videos
        include_videos_checkbox = QCheckBox("Include videos (may result in large file size)")
        include_videos_checkbox.setChecked(True)  # Default to include videos
        layout.addWidget(include_videos_checkbox)
        
        # Add buttons in horizontal layout
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        confirm_button = QPushButton("Export")
        cancel_button = QPushButton("Cancel")
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(confirm_button)
        buttons_layout.addWidget(cancel_button)
        layout.addLayout(buttons_layout)
        
        # Connect button signals
        confirm_button.clicked.connect(dialog.accept)
        cancel_button.clicked.connect(dialog.reject)
        
        # Show dialog and get result
        dialog_result = dialog.exec()
        if dialog_result != QDialog.DialogCode.Accepted:
            return
            
        # User confirmed, get inclusion flag for videos
        include_videos = include_videos_checkbox.isChecked()
        
        # Ask user for export location
        export_dir = QFileDialog.getExistingDirectory(
            self.main_window,
            "Select Export Directory",
            os.path.expanduser("~")
        )
        
        if not export_dir:
            return
            
        # Create a filename for the zip file
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if export_type == "run":
            zip_filename = f"{export_project}_{export_series}_{export_run}_{timestamp}.zip"
        elif export_type == "series":
            zip_filename = f"{export_project}_{export_series}_{timestamp}.zip"
        else:
            zip_filename = f"{export_project}_{timestamp}.zip"
            
        zip_path = os.path.join(export_dir, zip_filename)
        
        # Determine source directory
        if export_type == "run":
            source_dir = os.path.join(base_dir, export_project, export_series, export_run)
            # Keep only the project and below in the archive path
            archive_root = os.path.join(base_dir)
        elif export_type == "series":
            source_dir = os.path.join(base_dir, export_project, export_series)
            # Keep only the project and below in the archive path
            archive_root = os.path.join(base_dir)
        else:
            source_dir = os.path.join(base_dir, export_project)
            # Keep only the project folder
            archive_root = os.path.join(base_dir)
            
        # Check if source directory exists
        if not os.path.exists(source_dir):
            QMessageBox.warning(
                self.main_window,
                "Export Error",
                f"Source directory not found: {source_dir}"
            )
            return
            
        try:
            # Show a progress dialog
            progress = QProgressDialog("Preparing export...", "Cancel", 0, 100, self.main_window)
            progress.setWindowTitle("Exporting Data")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
            progress.setValue(0)
            progress.show()
            
            # Count total files for progress calculation
            total_files = 0
            files_to_process = []
            
            # First pass: count files and collect paths
            progress.setLabelText("Scanning files...")
            
            # Make sure we include the proper folder structure by adding any empty directories
            # We'll track directories we've already processed
            processed_dirs = set()
            
            # Helper function to ensure directory structure is preserved
            def ensure_directory_structure(dir_path):
                # Get relative path for the directory
                rel_path = os.path.relpath(dir_path, archive_root)
                # Skip if already processed
                if rel_path in processed_dirs:
                    return
                
                # Add this directory to the processed set
                processed_dirs.add(rel_path)
                
                # Process parent directories recursively
                parent_dir = os.path.dirname(dir_path)
                if parent_dir != archive_root and os.path.exists(parent_dir):
                    ensure_directory_structure(parent_dir)
            
            # Add parent directories' metadata files if needed
            if export_type == "run" or export_type == "series":
                # Add project metadata
                project_metadata_file = os.path.join(base_dir, export_project, "project_metadata.json")
                if os.path.exists(project_metadata_file):
                    arcname = os.path.relpath(project_metadata_file, archive_root)
                    files_to_process.append((project_metadata_file, arcname))
                    self.main_window.logger.log(f"Adding project metadata file: {arcname}", "DEBUG")
                    
                # Ensure project directory structure is preserved
                project_dir = os.path.join(base_dir, export_project)
                ensure_directory_structure(project_dir)
                    
            if export_type == "run":
                # Add series metadata
                series_metadata_file = os.path.join(base_dir, export_project, export_series, "series_metadata.json")
                if os.path.exists(series_metadata_file):
                    arcname = os.path.relpath(series_metadata_file, archive_root)
                    files_to_process.append((series_metadata_file, arcname))
                    self.main_window.logger.log(f"Adding series metadata file: {arcname}", "DEBUG")
                    
                # Ensure series directory structure is preserved
                series_dir = os.path.join(base_dir, export_project, export_series)
                ensure_directory_structure(series_dir)
                    
            # Track if control run data is found
            control_run_config_found = False
            control_run_data_found = False
            
            # Now add all files from the source directory
            for root, dirs, files in os.walk(source_dir):
                # Ensure this directory's structure is preserved
                ensure_directory_structure(root)
                
                for file in files:
                    file_path = os.path.join(root, file)
                    
                    # Track control run files
                    if file == "control_run_config.json":
                        control_run_config_found = True
                        self.main_window.logger.log("Control run configuration found in export", "INFO")
                    elif file == "control_run_data.csv":
                        control_run_data_found = True
                        self.main_window.logger.log("Control run data CSV found in export", "INFO")
                    
                    # Skip video files if not including videos
                    if not include_videos and file.lower().endswith(('.mp4', '.avi', '.mov', '.wmv')):
                        continue
                        
                    # Calculate arcname to preserve folder structure from the project level
                    # This ensures the project folder and relevant folders inside are included
                    arcname = os.path.relpath(file_path, archive_root)
                    
                    files_to_process.append((file_path, arcname))
                    total_files += 1
                    
                    # Update progress occasionally
                    if total_files % 10 == 0:
                        progress.setLabelText(f"Found {total_files} files to export...")
                        QApplication.processEvents()
                        
                    if progress.wasCanceled():
                        return
            
            # Log control run export status
            if control_run_config_found or control_run_data_found:
                self.main_window.logger.log(
                    f"Export includes control run data: config={control_run_config_found}, data={control_run_data_found}", 
                    "INFO"
                )
            
            # Create zip file
            progress.setLabelText("Creating zip file...")
            progress.setValue(10)  # Start actual export at 10%
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # First add directory entries to preserve structure
                for dir_path in processed_dirs:
                    # Skip the root entry
                    if dir_path in (".", ""):
                        continue
                    # Create directory entry (with trailing slash)
                    if not dir_path.endswith('/'):
                        dir_path += '/'
                    # Create a ZipInfo object for the directory
                    dir_info = zipfile.ZipInfo(dir_path)
                    # Set permissions
                    dir_info.external_attr = 0o755 << 16  # Permission bits for directory
                    # Write the directory entry
                    zipf.writestr(dir_info, '')
                
                # Add files to zip with progress updates
                for i, (file_path, arcname) in enumerate(files_to_process):
                    # Write the file to the zip with the proper path structure
                    zipf.write(file_path, arcname)
                    
                    # Update progress every few files
                    if i % 5 == 0 or i == len(files_to_process) - 1:
                        percent = 10 + int((i / len(files_to_process)) * 90)  # Scale to 10-100%
                        progress.setValue(percent)
                        progress.setLabelText(f"Exporting: {arcname}")
                        QApplication.processEvents()
                        
                    if progress.wasCanceled():
                        return
            
            # Complete the progress
            progress.setValue(100)
            progress.setLabelText("Export complete!")
            
            # Log export details
            self.main_window.logger.log(f"Export completed: {len(files_to_process)} files exported with proper folder structure", "INFO")
            self.main_window.logger.log(f"Source directory: {source_dir}", "DEBUG")
            self.main_window.logger.log(f"Archive root: {archive_root}", "DEBUG")
            self.main_window.logger.log(f"Export path: {zip_path}", "DEBUG")
            self.main_window.logger.log(f"Directories preserved in archive: {len(processed_dirs)}", "DEBUG")
            
            # Log metadata files included
            if export_type == "run" or export_type == "series":
                project_metadata_file = os.path.join(base_dir, export_project, "project_metadata.json")
                self.main_window.logger.log(f"Project metadata file exists: {os.path.exists(project_metadata_file)}", "DEBUG")
                
            if export_type == "run":
                series_metadata_file = os.path.join(base_dir, export_project, export_series, "series_metadata.json")
                self.main_window.logger.log(f"Series metadata file exists: {os.path.exists(series_metadata_file)}", "DEBUG")
            
            # Show success message
            QMessageBox.information(
                self.main_window,
                "Export Complete",
                f"Data exported successfully to:\n{zip_path}"
            )
            
            self.main_window.logger.log(f"Exported {export_type} data to {zip_path}", "INFO")
            
        except Exception as e:
            QMessageBox.critical(
                self.main_window,
                "Export Error",
                f"An error occurred during export:\n{str(e)}"
            )
            self.main_window.logger.log(f"Export error: {str(e)}", "ERROR")

    def import_project(self):
        """
        Import project data from a zip archive.
        The user selects a zip file, and its contents are extracted into the base directory.
        """
        from PyQt6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog
        from PyQt6.QtCore import Qt
        import zipfile
        import datetime

        # Get base directory
        base_dir = self.main_window.project_base_dir.text()
        if not base_dir or not os.path.exists(base_dir):
            QMessageBox.warning(
                self.main_window,
                "Import Error",
                "Please set a valid base directory first in the Projects tab."
            )
            return

        # Ask user for the zip file
        zip_path, _ = QFileDialog.getOpenFileName(
            self.main_window,
            "Select Project Archive",
            os.path.expanduser("~"),
            "Zip Archives (*.zip)"
        )

        if not zip_path:
            return

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Get the list of files in the zip
                file_list = zip_ref.namelist()
                
                # Identify project folders (they should be top-level directories or containing project_metadata.json)
                project_folders = set()
                for file_path in file_list:
                    parts = file_path.strip('/').split('/')
                    if len(parts) >= 1:
                        # If we see project_metadata.json, the parent is definitely a project folder
                        if "project_metadata.json" in parts:
                            idx = parts.index("project_metadata.json")
                            if idx > 0:
                                project_folders.add(parts[idx-1])
                            else:
                                # project_metadata.json is at root of zip? 
                                # This shouldn't happen with our export logic but we handle it
                                pass
                        else:
                            # Otherwise assume the first part is the project name
                            project_folders.add(parts[0])

                if not project_folders:
                    QMessageBox.warning(
                        self.main_window,
                        "Import Error",
                        "The selected archive does not appear to contain any valid project folders."
                    )
                    return

                # Notify user about the destination
                project_list_str = "\n".join([f"• {p}" for p in sorted(project_folders)])
                confirm_msg = (
                    f"The following projects were found in the archive:\n\n{project_list_str}\n\n"
                    f"These will be extracted to your base directory:\n{base_dir}\n\n"
                    "Existing files with the same names will be overwritten. Do you want to continue?"
                )
                
                reply = QMessageBox.question(
                    self.main_window,
                    "Confirm Import",
                    confirm_msg,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                
                if reply != QMessageBox.StandardButton.Yes:
                    return

                # Show progress dialog
                progress = QProgressDialog("Importing files...", "Cancel", 0, len(file_list), self.main_window)
                progress.setWindowTitle("Project Import")
                progress.setWindowModality(Qt.WindowModality.WindowModal)
                progress.setMinimumDuration(0)
                progress.show()

                # Extract files
                extracted_count = 0
                for file_info in file_list:
                    if progress.wasCanceled():
                        break
                    
                    zip_ref.extract(file_info, base_dir)
                    extracted_count += 1
                    progress.setValue(extracted_count)
                
                progress.close()

                if not progress.wasCanceled():
                    self.main_window.logger.log(f"Successfully imported project data from {zip_path}", "INFO")
                    QMessageBox.information(
                        self.main_window,
                        "Import Successful",
                        f"Successfully imported {len(project_folders)} project(s) to:\n{base_dir}"
                    )
                    
                    # Refresh the project tree and selector
                    self.update_project_list()
                    self.update_project_tree()
                    
        except Exception as e:
            QMessageBox.critical(
                self.main_window,
                "Import Error",
                f"An error occurred during import:\n{str(e)}"
            )
            self.main_window.logger.log(f"Import error: {str(e)}", "ERROR")
            import traceback
            traceback.print_exc()
    
    def on_project_tree_clicked(self, index):
        """
        Handle project tree item click - store selection info for later use.
        """
        # Get item name and parent relationships
        if not index.isValid():
            return
            
        # Get the model index for the name column (0)
        if index.column() != 0:
            name_index = self.main_window.project_model.index(index.row(), 0, index.parent())
        else:
            name_index = index
            
        item_name = self.main_window.project_model.data(name_index)
        
        # Get parent information
        parent_index = name_index.parent()
        parent_name = None
        if parent_index.isValid():
            parent_name_index = self.main_window.project_model.index(parent_index.row(), 0, parent_index.parent())
            parent_name = self.main_window.project_model.data(parent_name_index)
            
        # Get grandparent information
        grandparent_name = None
        if parent_index.isValid():
            grandparent_index = parent_index.parent()
            if grandparent_index and grandparent_index.isValid():
                # Ensure we get column 0 (name) for the grandparent
                grandparent_name_index = self.main_window.project_model.index(grandparent_index.row(), 0, grandparent_index.parent())
                grandparent_name = self.main_window.project_model.data(grandparent_name_index)
                
        # Store selection information
        if grandparent_name is not None:
            # This is a run
            self.last_selected_type = "run"
            self.last_selected_project = grandparent_name
            self.last_selected_series = parent_name
            self.last_selected_run = item_name
        elif parent_name is not None:
            # This is a test series
            self.last_selected_type = "series"
            self.last_selected_project = parent_name
            self.last_selected_series = item_name
            self.last_selected_run = None
        else:
            # This is a project
            self.last_selected_type = "project"
            self.last_selected_project = item_name
            self.last_selected_series = None
            self.last_selected_run = None
            
        self.main_window.logger.log(f"Stored selection: {self.last_selected_type} - Project: {self.last_selected_project}, Series: {self.last_selected_series}, Run: {self.last_selected_run}", "DEBUG") 

    def load_newest_run(self, is_startup_load=False):
        """Find and load the newest run in the current test series"""
        if not self.current_project or not self.current_test_series:
            return
            
        base_dir = self.main_window.project_base_dir.text()
        if not base_dir or not os.path.exists(base_dir):
            return
            
        # Build the test series path
        series_dir = os.path.join(base_dir, self.current_project, self.current_test_series)
        if not os.path.exists(series_dir):
            return
            
        # Find all run directories in the test series
        run_dirs = []
        for item in os.listdir(series_dir):
            item_path = os.path.join(series_dir, item)
            if os.path.isdir(item_path) and item.startswith("Run_"):
                # Get creation time for sorting
                try:
                    created_time = os.path.getctime(item_path)
                    run_dirs.append((item, item_path, created_time))
                except:
                    pass
                
        if not run_dirs:
            self.main_window.logger.log("No runs found in the test series", "INFO")
            return
            
        # Sort runs by creation time, newest first
        sorted_runs = sorted(run_dirs, key=lambda x: x[2], reverse=True)
        newest_run_name = sorted_runs[0][0]
        
        self.main_window.logger.log(f"Found newest run for startup load: {newest_run_name}", "INFO")
        
        # Now use the unified load_run method to perform the actual loading
        # This ensures consistency between manual and automatic loading
        self.load_run(
            project_name=self.current_project,
            series_name=self.current_test_series,
            run_name=newest_run_name,
            is_startup_load=is_startup_load
        )
            
        # Notify the user that they need to enter a new run description
        self.main_window.logger.log("Please enter a new run description before starting data acquisition", "INFO")
    
    def get_current_run_directory(self):
        """
        Get the full path to the current run directory.
        
        Returns:
            str: Path to the current run directory, or None if no run is active
        """
        if not self.current_project or not self.current_test_series or not self.current_run:
            return None
            
        base_dir = self.main_window.project_base_dir.text()
        if not base_dir or not os.path.exists(base_dir):
            return None
            
        project_dir = os.path.join(base_dir, self.current_project)
        series_dir = os.path.join(project_dir, self.current_test_series)
        run_dir = os.path.join(series_dir, self.current_run)
        
        if not os.path.exists(run_dir):
            return None
            
        return run_dir