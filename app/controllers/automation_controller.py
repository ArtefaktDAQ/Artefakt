"""
Automation Controller

Manages automation sequences and rules, interacting with the UI and the AutomationManager.
"""
import traceback
import os
import json
import shutil
from PyQt6.QtCore import QObject, pyqtSignal, Qt, QTimer
from PyQt6.QtWidgets import QMessageBox, QTableWidgetItem, QHeaderView, QAbstractItemView, QLabel

from app.models.automation import AutomationManager, AutomationSequence
from app.ui.dialogs.automation_dialogs import SequenceDialog
from app.utils.common_types import StatusState

# Import trigger types for status messages
from app.models.automation import TimeDurationTrigger, TimeSpecificTrigger, SensorValueTrigger, EventTrigger
import time

class AutomationController(QObject):
    """Controls automation sequences and rules"""
    
    # Signal that will be emitted when the overall automation status changes (for main status bar)
    status_changed = pyqtSignal() # Renamed from controller_status_changed for clarity

    def __init__(self, main_window, config):
        """
        Initialize the automation controller
        
        Args:
            main_window: Main application window instance.
            config: Application configuration object.
        """
        super().__init__()
        self.main_window = main_window
        self.config = config

        # --- Setup Automation Manager ---
        # Build the initial context to pass to the manager
        # The manager needs access to interfaces and potentially the main window
        # for executing system actions.
        initial_context = {
            'main_window': self.main_window,
            'interfaces': getattr(self.main_window, 'interfaces', {}),
            'data_logger': getattr(self.main_window, 'data_logger', None),
            'sound_player': getattr(self.main_window, 'sound_player', None),
            'sensor_controller': getattr(self.main_window, 'sensor_controller', None),
            'events': set(),  # Initialize events dictionary for system events (motion, recording, etc.)
            # Add other necessary components here
        }
        
        # Define where sequences are saved, prioritizing the current run folder
        # Use the path from config if available, otherwise use default
        if isinstance(self.config, dict) and 'automation_sequences_path' in self.config:
            self.default_sequences_path = self.config['automation_sequences_path']
        else:
            self.default_sequences_path = "data/automation_sequences.json"
            
        sequences_file_path = self.default_sequences_path
        try:
            if hasattr(self.config, 'current_run_folder'):
                current_run_folder = self.config.current_run_folder
                if current_run_folder and os.path.isdir(current_run_folder):
                    sequences_file_path = os.path.join(current_run_folder, "automation_sequences.json")
                    print(f"Automation sequences will be loaded/saved to: {sequences_file_path}")
                else:
                    print(f"Warning: config.current_run_folder is invalid ('{current_run_folder}'). Using default sequences path.")
            elif isinstance(self.config, dict) and "current_run_folder" in self.config:
                 current_run_folder = self.config["current_run_folder"]
                 if current_run_folder and os.path.isdir(current_run_folder):
                    sequences_file_path = os.path.join(current_run_folder, "automation_sequences.json")
                    print(f"Automation sequences will be loaded/saved to: {sequences_file_path}")
                 else:
                    print(f"Warning: config['current_run_folder'] is invalid ('{current_run_folder}'). Using default sequences path.")
            else:
                print("Warning: Could not determine run folder from config. Using default sequences path.")
        except Exception as e:
            print(f"Error determining sequence path from config: {e}. Using default.")
            
        # Ensure the directory exists
        directory = os.path.dirname(sequences_file_path)
        if directory and not os.path.exists(directory):
            try:
                os.makedirs(directory, exist_ok=True)
                print(f"Created automation sequences directory: {directory}")
            except Exception as e:
                print(f"Error creating automation sequences directory: {e}")
        
        # Initialize the manager with both current and master paths
        self.manager = AutomationManager(
            sequences_file=sequences_file_path, 
            app_context=initial_context,
            master_file=self.default_sequences_path
        )

        # --- ADDED --- Timer for updating the dashboard table (for live countdowns)
        self.dashboard_update_timer = QTimer(self)
        self.dashboard_update_timer.setInterval(1000) # Update every second
        self.dashboard_update_timer.timeout.connect(self._update_dashboard_automation_table)
        # Make sure the timer is active
        if not self.dashboard_update_timer.isActive():
            print("Starting dashboard update timer")
            self.dashboard_update_timer.start()
        else:
            print("Dashboard update timer already running")

        # --- Store UI State ---
        # REMOVE: self.checked_sequence_names = set() # Keep track of checked sequences

        # --- Connect Manager Signals ---
        self.manager.sequences_changed.connect(self.update_sequences_table)
        self.manager.status_changed.connect(self._update_dashboard_automation_table)
        self.manager.status_changed.connect(self.update_sequences_table) # Ensure main table status also updates
        self.manager.status_changed.connect(self.status_changed) # Notify main window status
        
        # Connect signals for sequence execution progress (if UI elements exist)
        self.manager.sequence_started.connect(self.on_sequence_started)
        self.manager.sequence_stopped.connect(self.on_sequence_stopped)
        self.manager.sequence_completed.connect(self.on_sequence_completed)
        self.manager.sequence_step_changed.connect(self.on_sequence_step_changed)
        self.manager.sequence_error.connect(self.on_sequence_error)

        # --- UI Initialization ---
        self.setup_sequences_table() # Initial setup of the table
        self.update_sequences_table() # Load initial data
        self._update_dashboard_automation_table() # Initial population of dashboard table
        self.update_button_states() # Set initial button enabled/disabled state
        self.update_automation_status_display() # Set initial status display
        self.connect_signals() # Connect UI signals
        self._setup_predefined_automations() # Initialize templates
        
        # Enable context menu for dashboard table
        if hasattr(self.main_window, 'dashboard_automation_table'):
            self.main_window.dashboard_automation_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.main_window.dashboard_automation_table.customContextMenuRequested.connect(self.show_dashboard_context_menu)

    def setup_sequences_table(self):
        """Configure the appearance of the sequences table in the main UI."""
        if hasattr(self.main_window, 'sequences_table'):
            table = self.main_window.sequences_table
            # Add "Run" column for checkboxes at index 0
            table.setColumnCount(5) # Run, Name, Status, Current Step, Loop
            table.setHorizontalHeaderLabels(["Run", "Name", "Status", "Current Step", "Loop"])
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) # Checkbox column
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch) # Name column
            table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents) # Status column
            table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents) # Step column
            table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents) # Loop column            
            # Fix for PyQt6 compatibility - use QAbstractItemView instead of QTableWidgetItem
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection) # Keep single selection for edit/remove
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            # Connect selection change to update button states (for edit/remove)
            table.itemSelectionChanged.connect(self.update_button_states)
            # Connect item changed (for checkbox toggles) to update button states (for start/stop)
            # Connect to a dedicated handler to manage the checked state set
            table.itemChanged.connect(self._handle_item_changed)
            # Connect double-click to edit sequence
            table.cellDoubleClicked.connect(self._on_sequence_double_clicked)
        else:
            print("Warning: Main window does not have 'sequences_table' attribute.")

    def connect_signals(self):
        """Connect UI signals (buttons etc.) to controller methods"""
        # Assumes buttons exist on the main_window with these object names
        if hasattr(self.main_window, 'add_sequence_btn'):
            self.main_window.add_sequence_btn.clicked.connect(self.add_sequence)
            
        if hasattr(self.main_window, 'edit_sequence_btn'):
            self.main_window.edit_sequence_btn.clicked.connect(self.edit_sequence)
            
        if hasattr(self.main_window, 'remove_sequence_btn'):
            self.main_window.remove_sequence_btn.clicked.connect(self.remove_sequence)
            
        if hasattr(self.main_window, 'start_sequence_btn'):
             self.main_window.start_sequence_btn.clicked.connect(self.handle_start_button)

        if hasattr(self.main_window, 'stop_sequence_btn'):
             self.main_window.stop_sequence_btn.clicked.connect(self.handle_stop_button)

        # Optional: Connect an enable/disable checkbox if needed
        # if hasattr(self.main_window, 'automation_enable_cb'):
        #     self.main_window.automation_enable_cb.stateChanged.connect(self.toggle_automation_enabled)
        
        # Connect context menu actions if they exist
        if hasattr(self.main_window, 'action_start_sequence'):
            self.main_window.action_start_sequence.triggered.connect(self.start_selected_sequence)
        if hasattr(self.main_window, 'action_stop_sequence'):
            self.main_window.action_stop_sequence.triggered.connect(self.stop_selected_sequence)
        if hasattr(self.main_window, 'action_edit_sequence'):
             self.main_window.action_edit_sequence.triggered.connect(self.edit_sequence)
        if hasattr(self.main_window, 'action_remove_sequence'):
            self.main_window.action_remove_sequence.triggered.connect(self.remove_sequence)

    def update_context(self, updates):
        """Update the context shared with the automation manager."""
        self.manager.update_context(updates)
        
    # --- Sequence Management Methods ---

    def update_sequences_table(self):
        """Update the sequences table in the UI with data from the manager."""
        if not hasattr(self.main_window, 'sequences_table'):
            return

        table = self.main_window.sequences_table
        current_selection_data = self.get_selected_sequence() # Preserve selection based on sequence object

        table.blockSignals(True) # Avoid triggering signals during update
        table.setRowCount(len(self.manager.sequences))

        new_selected_row = -1 # Track the row index of the previously selected sequence

        for i, seq in enumerate(self.manager.sequences):
            # --- Column 0: Checkbox ---
            checkbox_item = QTableWidgetItem()
            checkbox_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            # Restore check state from sequence object
            checkbox_item.setCheckState(Qt.CheckState.Checked if seq.checked else Qt.CheckState.Unchecked)
            # Store sequence object in the checkbox item's data for easy retrieval
            checkbox_item.setData(Qt.ItemDataRole.UserRole, seq)
            table.setItem(i, 0, checkbox_item)

            # --- Column 1: Name ---
            name_item = QTableWidgetItem(seq.name)
            # Remove redundant data storage
            # name_item.setData(Qt.ItemDataRole.UserRole, seq) 
            table.setItem(i, 1, name_item)

            # --- Column 2: Status & Column 3: Current Step ---
            status_text = "Stopped"
            step_text = "-"
            if seq in self.manager.active_sequences:
                status_text = "Running"
                if seq.current_step_index >= 0 and seq.current_step_index < len(seq.steps):
                     step_text = f"{seq.current_step_index + 1}/{len(seq.steps)}"
                else:
                     step_text = "-" # Handle edge case where index might be invalid briefly
            elif seq._current_step_failed: # Check if last run failed
                 status_text = "Failed"

            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(i, 2, status_item)

            step_item = QTableWidgetItem(step_text)
            step_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(i, 3, step_item)

            # --- Column 4: Loop ---
            loop_item = QTableWidgetItem("Yes" if seq.loop else "No")
            loop_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(i, 4, loop_item)
            
            # Check if this row corresponds to the previously selected sequence
            if seq == current_selection_data:
                new_selected_row = i


        table.blockSignals(False)

        # Restore selection if the sequence still exists
        if new_selected_row != -1:
             # Select the entire row corresponding to the checkbo item
             table.selectRow(new_selected_row)
        # else:
        #      # If previous selection is now invalid or no selection existed, clear selection
        #      table.clearSelection() # Keep selection cleared if nothing was selected before


        self.update_button_states() # Update buttons after table change

    def get_selected_sequence(self):
        """Get the AutomationSequence object for the currently selected row in any active table."""
        # 1. Try dashboard table first (if it has focus or selection)
        if hasattr(self.main_window, 'dashboard_automation_table'):
            seq = self.get_selected_dashboard_sequence()
            if seq:
                return seq
                
        # 2. Try main sequences table
        if not hasattr(self.main_window, 'sequences_table'):
            return None
            
        table = self.main_window.sequences_table
        selected_row = self.get_selected_row_index() # Get the selected row index

        if selected_row is not None:
            # Get the item from the first column (checkbox column) of the selected row
            checkbox_item = table.item(selected_row, 0)
            if checkbox_item:
                # Retrieve the sequence object stored in the checkbox item's data
                return checkbox_item.data(Qt.ItemDataRole.UserRole)
        return None
        
    def get_selected_row_index(self):
         """Get the index of the currently selected row in the main sequences table."""
         if not hasattr(self.main_window, 'sequences_table'):
            return None
         table = self.main_window.sequences_table
         selected_ranges = table.selectedRanges()
         if selected_ranges:
              return selected_ranges[0].topRow()
         return None

    def get_selected_dashboard_sequence(self):
        """Get the AutomationSequence object for the currently selected row in the dashboard table."""
        if not hasattr(self.main_window, 'dashboard_automation_table'):
            return None
            
        table = self.main_window.dashboard_automation_table
        selected_ranges = table.selectedRanges()
        if not selected_ranges:
            return None
            
        row = selected_ranges[0].topRow()
        # Find the sequence in the manager based on the name in the first column
        name_item = table.item(row, 0)
        if name_item:
            name = name_item.text()
            for seq in self.manager.sequences:
                if seq.name == name:
                    return seq
        return None

    def show_dashboard_context_menu(self, pos):
        """Show context menu for the dashboard automation table."""
        sequence = self.get_selected_dashboard_sequence()
        if not sequence:
            return
            
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        
        menu = QMenu(self.main_window)
        
        is_running = sequence in self.manager.active_sequences
        
        start_action = QAction("Start Sequence", self.main_window)
        start_action.setEnabled(not is_running)
        start_action.triggered.connect(lambda: self.manager.start_sequence(sequence))
        menu.addAction(start_action)
        
        stop_action = QAction("Stop Sequence", self.main_window)
        stop_action.setEnabled(is_running)
        stop_action.triggered.connect(lambda: self.manager.stop_sequence(sequence))
        menu.addAction(stop_action)
        
        menu.exec(self.main_window.dashboard_automation_table.viewport().mapToGlobal(pos))

    def add_sequence(self):
        """Open dialog to add a new automation sequence."""
        try:
            # Gather context needed for the dialog
            sensors = self.manager.get_available_sensor_objects()
            ports = self.manager.get_available_serial_ports()
            # Pass the manager's context which includes interfaces etc.
            context = self.manager.app_context 
            
            dialog = SequenceDialog(self.main_window, None, sensors, ports, context)
            if dialog.exec():
                new_sequence = dialog.get_sequence()
                if new_sequence:
                    # Verify that we got a valid AutomationSequence object
                    if not isinstance(new_sequence, AutomationSequence):
                        print(f"Error: dialog.get_sequence() returned a {type(new_sequence)} instead of AutomationSequence")
                        QMessageBox.critical(self.main_window, "Error", f"Failed to create valid sequence")
                        return
                    
                    # Add the sequence and update UI
                    print(f"Adding new sequence: {new_sequence.name}")
                    self.manager.add_sequence(new_sequence)
                    
                    # Select the newly added sequence
                    new_row_index = -1
                    for i in range(self.main_window.sequences_table.rowCount()):
                        item = self.main_window.sequences_table.item(i, 0)
                        if item and item.data(Qt.ItemDataRole.UserRole) == new_sequence:
                             new_row_index = i
                             break
                    if new_row_index != -1:
                         self.main_window.sequences_table.selectRow(new_row_index)

        except Exception as e:
             print(f"Error adding sequence: {e}")
             traceback.print_exc()
             QMessageBox.critical(self.main_window, "Error", f"Failed to add sequence: {e}")
    
    def edit_sequence(self):
        """Open dialog to edit the selected automation sequence."""
        selected_sequence = self.get_selected_sequence()
        if not selected_sequence:
            QMessageBox.warning(self.main_window, "Select Sequence", "Please select a sequence to edit.")
            return

        try:
            # Gather context for the dialog
            sensors = self.manager.get_available_sensor_objects()
            ports = self.manager.get_available_serial_ports()
            context = self.manager.app_context

            # Pass the *original* sequence object to the dialog
            dialog = SequenceDialog(self.main_window, selected_sequence, sensors, ports, context)
            
            if dialog.exec():
                # The dialog modifies the original sequence object in place if OK is clicked
                updated_sequence = dialog.get_sequence() 
                if updated_sequence: 
                    # Verify that we got a valid AutomationSequence object
                    if not isinstance(updated_sequence, AutomationSequence):
                        print(f"Error: dialog.get_sequence() returned a {type(updated_sequence)} instead of AutomationSequence")
                        QMessageBox.critical(self.main_window, "Error", f"Failed to update sequence")
                        return
                        
                    # Update the sequence and save
                    print(f"Updating sequence: {updated_sequence.name}")
                    self.manager.update_sequence(selected_sequence, updated_sequence)
                else:
                    print("Dialog.get_sequence() returned None or False")
            else:
                 print("User cancelled sequence edit")
                 
        except Exception as e:
             print(f"Error editing sequence: {e}")
             traceback.print_exc()
             QMessageBox.critical(self.main_window, "Error", f"Failed to edit sequence '{selected_sequence.name}': {e}")

    
    def remove_sequence(self):
        """Remove the selected automation sequence."""
        selected_sequence = self.get_selected_sequence()
        if not selected_sequence:
            QMessageBox.warning(self.main_window, "Select Sequence", "Please select a sequence to remove.")
            return
            
        reply = QMessageBox.question(self.main_window, "Confirm Remove", 
                                     f"Are you sure you want to remove the sequence '{selected_sequence.name}'?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
                                     
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.manager.remove_sequence(selected_sequence)
                # update_sequences_table called automatically via signal
            except Exception as e:
                 print(f"Error removing sequence: {e}")
                 traceback.print_exc()
                 QMessageBox.critical(self.main_window, "Error", f"Failed to remove sequence '{selected_sequence.name}': {e}")

    def start_selected_sequence(self):
         """Start the selected automation sequence."""
         selected_sequence = self.get_selected_sequence()
         if not selected_sequence:
             QMessageBox.warning(self.main_window, "Select Sequence", "Please select a sequence to start.")
             return
            
         try:
             self.manager.start_sequence(selected_sequence)
             # UI update (status column) will happen via signals
         except Exception as e:
             print(f"Error starting sequence: {e}")
             traceback.print_exc()
             QMessageBox.critical(self.main_window, "Error", f"Failed to start sequence '{selected_sequence.name}': {e}")

    def stop_selected_sequence(self):
         """Stop the selected automation sequence."""
         selected_sequence = self.get_selected_sequence()
         if not selected_sequence:
             # Maybe try to stop any running sequence? Or just require selection.
             # Let's require selection for now.
             QMessageBox.warning(self.main_window, "Select Sequence", "Please select a running sequence to stop.")
             return
            
         if selected_sequence not in self.manager.active_sequences:
              QMessageBox.information(self.main_window, "Sequence Not Running", f"Sequence '{selected_sequence.name}' is not currently running.")
              return
             
         try:
             self.manager.stop_sequence(selected_sequence)
             # UI update will happen via signals
         except Exception as e:
             print(f"Error stopping sequence: {e}")
             traceback.print_exc()
             QMessageBox.critical(self.main_window, "Error", f"Failed to stop sequence '{selected_sequence.name}': {e}")

    # def toggle_automation_enabled(self, state):
    #     """Handle the global enable/disable state (optional)."""
    #     if state:
    #         # Logic to enable automation (e.g., allow starting sequences)
    #         print("Automation enabled")
    #     else:
    #         # Logic to disable automation (e.g., stop all sequences)
    #         print("Automation disabled - stopping all sequences.")
    #         self.manager.stop_all_sequences()
    #     self.update_button_states()
    #     self.status_changed.emit() # Notify main status

    # --- Signal Handlers from AutomationManager ---

    def _ensure_dashboard_timer_active(self):
        """Helper method to make sure the dashboard timer is running."""
        if hasattr(self, 'dashboard_update_timer'):
            if not self.dashboard_update_timer.isActive():
                print("Reactivating dashboard update timer which was stopped")
                self.dashboard_update_timer.start()
                return True
        return False
    
    def on_sequence_started(self, sequence):
        """Handler for sequence started signal (from manager)"""
        print(f"Sequence '{sequence.name}' started.")
        # Hide any previous error message when a sequence starts
        if hasattr(self.main_window, 'automation_error_label'):
            self.main_window.automation_error_label.setVisible(False)
        # Ensure timer is running when a sequence starts
        self._ensure_dashboard_timer_active()
        
    def on_sequence_stopped(self, sequence):
        """Handler for sequence stopped signal (from manager)"""
        print(f"Sequence '{sequence.name}' stopped.")
        # Ensure timer continues running
        self._ensure_dashboard_timer_active()
        
    def on_sequence_completed(self, sequence):
        """Handler for sequence completed signal (from manager)"""
        print(f"Sequence '{sequence.name}' completed.")
        # Ensure timer continues running 
        self._ensure_dashboard_timer_active()
        # Show completion notification
        QMessageBox.information(self.main_window, "Sequence Complete", f"Automation sequence '{sequence.name}' finished successfully.")

    def on_sequence_step_changed(self, sequence, step_index):
         # This signal is crucial for updating step info promptly
         self._update_dashboard_automation_table() # Update dashboard table specifically
         # Also update the main sequences table step column
         self.update_sequences_table() # Refresh main table (redundant if status_changed also fires, but safe)

    def on_sequence_error(self, sequence, error_message):
        """Handle sequence errors, updating the table and potentially the dashboard."""
        print(f"Error in sequence '{sequence.name}': {error_message}")
        
        # Display error in the automation error label
        if hasattr(self.main_window, 'automation_error_label'):
            error_text = f"⚠ Sequence '{sequence.name}' failed: {error_message}"
            self.main_window.automation_error_label.setText(error_text)
            self.main_window.automation_error_label.setVisible(True)
        
        # No direct call to update dashboard needed, status_changed signal handles it

    def update_button_states(self):
        """Enable/disable UI buttons based on selection, checks, and sequence state."""
        selected_sequence = self.get_selected_sequence()
        checked_sequences = self.get_checked_sequences()

        has_selection = selected_sequence is not None
        is_selected_running = has_selection and selected_sequence in self.manager.active_sequences

        can_start_checked = False
        can_stop_checked = False
        for seq in checked_sequences:
            if seq not in self.manager.active_sequences:
                can_start_checked = True
            if seq in self.manager.active_sequences:
                can_stop_checked = True
            # If we can both start some and stop some, break early
            if can_start_checked and can_stop_checked:
                break

        # Edit/Remove/Context Menu still based on *selection*
        if hasattr(self.main_window, 'edit_sequence_btn'):
             self.main_window.edit_sequence_btn.setEnabled(has_selection and not is_selected_running)
        if hasattr(self.main_window, 'remove_sequence_btn'):
             self.main_window.remove_sequence_btn.setEnabled(has_selection and not is_selected_running)
        if hasattr(self.main_window, 'action_edit_sequence'):
             self.main_window.action_edit_sequence.setEnabled(has_selection and not is_selected_running)
        if hasattr(self.main_window, 'action_remove_sequence'):
             self.main_window.action_remove_sequence.setEnabled(has_selection and not is_selected_running)
        if hasattr(self.main_window, 'action_start_sequence'):
             self.main_window.action_start_sequence.setEnabled(has_selection and not is_selected_running)
        if hasattr(self.main_window, 'action_stop_sequence'):
             self.main_window.action_stop_sequence.setEnabled(has_selection and is_selected_running)

        # Main Start/Stop buttons based on selection OR checked
        can_start = can_start_checked
        can_stop = can_stop_checked
        
        if has_selection:
            if not is_selected_running:
                can_start = True
            else:
                can_stop = True

        if hasattr(self.main_window, 'start_sequence_btn'):
             self.main_window.start_sequence_btn.setEnabled(can_start)
        if hasattr(self.main_window, 'stop_sequence_btn'):
             self.main_window.stop_sequence_btn.setEnabled(can_stop)

    def update_automation_status_display(self):
        """General update method called when automation status changes.
           Currently only used to potentially update the main status bar via get_status().
           The dashboard table update is handled separately.
        """
        # This method might be used for other general status updates in the future.
        # print("AutomationController: update_automation_status_display called")
        pass # Keep this simple, specific updates handled by dedicated slots/signals

    def is_running(self):
        """Check if any automation sequence is currently running."""
        return len(self.manager.active_sequences) > 0

    def get_status(self):
        """
        Get the overall status of the automation component for the main status bar.
        
        Returns:
            tuple: (StatusState, tooltip_string)
        """
        num_sequences = len(self.manager.sequences)
        num_active = len(self.manager.active_sequences)
        
        if num_active > 0:
            state = StatusState.RUNNING
            tooltip = f"{num_active}/{num_sequences} sequence(s) running."
        elif num_sequences > 0:
            # Check if any existing sequence is checked or (redundantly) active
            is_any_sequence_ready = any(seq.checked or seq in self.manager.active_sequences for seq in self.manager.sequences)
            if is_any_sequence_ready:
                 num_checked = sum(1 for seq in self.manager.sequences if seq.checked)
                 state = StatusState.READY
                 tooltip = f"{num_sequences} sequence(s) defined. {num_checked} checked, {num_active} running."
            else:
                 # Sequences exist, but none are checked or running
                 state = StatusState.OPTIONAL 
                 tooltip = f"{num_sequences} sequence(s) defined, but none checked to run."
        else:
            state = StatusState.OPTIONAL # No sequences defined
            tooltip = "No automation sequences defined."
            
        return (state, tooltip) 
        
    def stop_all_automation(self, is_exiting=False):
         """Called when the application is closing or needs to stop everything."""
         if hasattr(self, 'dashboard_update_timer') and self.dashboard_update_timer.isActive():
             if is_exiting:
                 print("Stopping dashboard update timer for exit")
                 self.dashboard_update_timer.stop()
             else:
                 print("Temporarily stopping dashboard updates")
                 self.dashboard_update_timer.stop() 
         
         self.manager.stop_all_sequences()
         
         # Restart the timer if we're not fully closing the application
         # This is needed because stop_all_automation might be called
         # in situations other than application exit
         if not is_exiting and hasattr(self, 'dashboard_update_timer'):
             if not self.dashboard_update_timer.isActive():
                 print("Restarting dashboard update timer")
                 self.dashboard_update_timer.start()
             else:
                 print("Dashboard timer already active")

    def stop_run_linked_automations(self):
        """Stop all automations that are linked to the data collection run."""
        print("Stopping run-linked automation sequences...")
        for seq in list(self.manager.active_sequences):
            if getattr(seq, 'run_linked', False):
                print(f"Stopping run-linked sequence: {seq.name}")
                self.manager.stop_sequence(seq)

    def get_checked_sequences(self):
        """Get a list of AutomationSequence objects whose checkboxes are checked."""
        checked_sequences = []
        if not hasattr(self.manager, 'sequences'):
            return checked_sequences
            
        # Iterate through manager's sequences
        for seq in self.manager.sequences:
            if seq.checked:
                checked_sequences.append(seq)
        return checked_sequences

    def handle_start_button(self):
        """Start the selected sequence, or all checked ones if none selected."""
        selected = self.get_selected_sequence()
        if selected and selected not in self.manager.active_sequences:
            self.manager.start_sequence(selected)
        else:
            # Fallback to starting all checked sequences
            self.start_checked_sequences()

    def handle_stop_button(self):
        """Stop the selected sequence, or all checked ones if none selected."""
        selected = self.get_selected_sequence()
        if selected and selected in self.manager.active_sequences:
            self.manager.stop_sequence(selected)
        else:
            # Fallback to stopping all checked sequences
            self.stop_checked_sequences()

    def start_checked_sequences(self):
        """Start all automation sequences that are currently checked."""
        checked_sequences = self.get_checked_sequences()
        if not checked_sequences:
            # Don't show warning when no sequences are checked
            # This allows users to run without any automation sequences
            print("No automation sequences checked - continuing without automation")
            return

        # Clear stale sensor data and events before starting NEW sequences
        # This prevents immediate triggering from values left over from a previous run
        # ONLY do this if no sequences are already running to avoid interrupting them
        if not self.manager.active_sequences:
            self.manager.update_context({'sensors': {}, 'events': set()})
            self.manager.variables = {} # Reset shared variables for a fresh start
            print("[Automation] Context and variables reset for new run")

        started_count = 0
        error_messages = []
        for seq in checked_sequences:
            if seq not in self.manager.active_sequences:
                try:
                    self.manager.start_sequence(seq)
                    started_count += 1
                except Exception as e:
                    msg = f"Failed to start sequence '{seq.name}': {e}"
                    print(msg)
                    traceback.print_exc()
                    error_messages.append(msg)
            else:
                print(f"Sequence '{seq.name}' is already running.")

        if started_count > 0:
            print(f"Started {started_count} sequence(s).")
        if error_messages:
            QMessageBox.critical(self.main_window, "Error Starting Sequences", "\n".join(error_messages))
        # UI updates happen via signals

    def stop_checked_sequences(self):
        print("DEBUG: stop_checked_sequences called.")
        checked_sequences = self.get_checked_sequences()
        print(f"DEBUG: Checked sequences: {[s.name for s in checked_sequences]}")
        active_seq_names = [s.name for s in self.manager.active_sequences] if hasattr(self.manager, 'active_sequences') else "N/A"
        print(f"DEBUG: Manager active sequences: {active_seq_names}")
        
        if not checked_sequences:
            QMessageBox.information(self.main_window, "Stop Sequences", "No sequences are checked.")
            return

        sequences_to_stop = []
        for seq in checked_sequences:
            if seq in self.manager.active_sequences:
                sequences_to_stop.append(seq)

        print(f"DEBUG: Sequences identified to stop: {[s.name for s in sequences_to_stop]}")
        if not sequences_to_stop:
            QMessageBox.warning(self.main_window, "Stop Sequences", "None of the checked sequences were running.")
            return

        reply = QMessageBox.question(self.main_window, "Confirm Stop", 
                                     f"Are you sure you want to stop {len(sequences_to_stop)} sequence(s)?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
                                     
        if reply == QMessageBox.StandardButton.Yes:
            for seq in sequences_to_stop:
                print(f"DEBUG: Calling manager.stop_sequence for {seq.name}")
                self.manager.stop_sequence(seq)
            print(f"Requested stop for {len(sequences_to_stop)} sequence(s).")

    def _handle_item_changed(self, item):
        """Handle changes to items in the table, specifically checkbox toggles."""
        if item.column() == 0: # Checkbox column
            sequence = item.data(Qt.ItemDataRole.UserRole)
            if sequence:
                is_checked = item.checkState() == Qt.CheckState.Checked
                if sequence.checked != is_checked:
                    sequence.checked = is_checked # Update the model attribute
                    print(f"Sequence '{sequence.name}' checked state set to: {sequence.checked}")
                    
                    # If unchecked, stop it if it's running
                    if not is_checked and sequence in self.manager.active_sequences:
                        print(f"Sequence '{sequence.name}' was unchecked while running - stopping it.")
                        self.manager.stop_sequence(sequence)
                        
                    # Trigger a save to persist the change
                    self.manager.save_sequences()
                    # Now update button states based on the new check state
                    self.update_button_states()
                    # Also emit general status changed for main status bar update
                    self.status_changed.emit()

        # Add any other necessary handling for other column changes if needed
        # ... (rest of the method remains unchanged)

        # ... (rest of the method remains unchanged) 

    def _on_sequence_double_clicked(self, row, column):
        """Handle double-click on a sequence row to open it in edit mode."""
        # Get the sequence from the checkbox column (column 0)
        if not hasattr(self.main_window, 'sequences_table'):
            return
            
        table = self.main_window.sequences_table
        checkbox_item = table.item(row, 0)
        if checkbox_item:
            sequence = checkbox_item.data(Qt.ItemDataRole.UserRole)
            if sequence:
                # Only edit if sequence is not running
                if sequence not in self.manager.active_sequences:
                    # Select the row first to ensure get_selected_sequence() works
                    table.selectRow(row)
                    self.edit_sequence()
                else:
                    QMessageBox.information(
                        self.main_window, 
                        "Cannot Edit", 
                        f"Cannot edit sequence '{sequence.name}' while it is running."
                    )

    def load_sequences(self, is_startup_load=False):
        """Reload sequences from file. If is_startup_load is True, load from global master file."""
        if is_startup_load:
            # Revert to global master sequences on startup load
            # This ensures that any sequences created/modified globally between runs are loaded
            self.manager.set_sequences_file(self.default_sequences_path)
        
        try:
            self.manager.load_sequences()
            self.main_window.logger.log(f"Automation sequences loaded (startup={is_startup_load})", "INFO")
        except Exception as e:
            self.main_window.logger.log(f"Error loading automation sequences: {e}", "ERROR")

    def update_sequence_path(self, new_run_folder):
        """Updates the path for saving/loading sequences based on the run folder."""
        if not new_run_folder or not os.path.isdir(new_run_folder):
            print(f"Error: Invalid run folder provided for automation sequences: {new_run_folder}")
            return

        new_sequences_file_path = os.path.join(new_run_folder, "automation_sequences.json")
        old_sequences_file_path = self.manager.sequences_file if hasattr(self.manager, 'sequences_file') else None

        if old_sequences_file_path == new_sequences_file_path:
            print("Automation sequence path is already up-to-date.")
            return
            
        print(f"Updating automation sequence path from '{old_sequences_file_path}' to: {new_sequences_file_path}")
        
        # --- Logic to copy existing sequences to new run folder --- 
        try:
             if not os.path.exists(new_sequences_file_path) and old_sequences_file_path and os.path.exists(old_sequences_file_path):
                 print(f"New path doesn't exist, copying sequences from {old_sequences_file_path}...")
                 # Ensure target directory exists before copying
                 new_directory = os.path.dirname(new_sequences_file_path)
                 if new_directory:
                     os.makedirs(new_directory, exist_ok=True)
                 shutil.copy2(old_sequences_file_path, new_sequences_file_path) # copy2 preserves metadata
                 print(f"Copied sequences to {new_sequences_file_path}")
             elif os.path.exists(new_sequences_file_path):
                  print(f"Existing sequence file found at {new_sequences_file_path}. Loading from it.")
             # Else: New path doesn't exist, old path doesn't exist - start fresh, do nothing here.
        except Exception as e:
             print(f"Error copying sequence file from {old_sequences_file_path} to {new_sequences_file_path}: {e}")
             # Proceed with setting path, but loading might fail or be empty.
        
        # Ensure the target directory exists (redundant if copy succeeded, but safe)
        directory = os.path.dirname(new_sequences_file_path)
        if directory and not os.path.exists(directory):
            try:
                os.makedirs(directory, exist_ok=True)
                print(f"Created automation sequences directory: {directory}")
            except Exception as e:
                print(f"Error creating new automation sequences directory: {e}")
                # Decide how to handle this - maybe prevent path change?
                # For now, proceed but loading/saving might fail.

        # Update the manager's path
        try:
            self.manager.set_sequences_file(new_sequences_file_path)
            
            # ONLY reload if no sequences are active.
            # If sequences are active, we just want to change the save location
            # without interrupting the current execution.
            if not self.manager.active_sequences:
                print("[Automation] No active sequences, reloading from new path.")
                self.manager.load_sequences()
            else:
                print(f"[Automation] {len(self.manager.active_sequences)} sequences active. Skipping reload to prevent interruption.")
                # We still want to emit a signal so the UI knows the path changed (e.g. for display)
                self.manager.sequences_changed.emit()
        except Exception as e:
            print(f"Error updating sequence path: {e}")
            traceback.print_exc()
            QMessageBox.critical(self.main_window, "Error", f"Failed to load automation sequences from {new_sequences_file_path}: {e}") 

    # --- ADDED --- New Dashboard Table Update Method ---
    def _format_seconds_mm_ss(self, total_seconds):
        """Formats seconds into MM:SS string."""
        if total_seconds is None or total_seconds < 0:
            return "--:--"
        total_seconds = int(total_seconds)
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    def _update_dashboard_automation_table(self):
        """Updates the automation table in the dashboard view."""
        # Skip live updates when a replay automation overlay is active (unless collecting live data)
        if getattr(self.main_window, "automation_replay_active", False):
            collecting = False
            try:
                collecting = bool(getattr(getattr(self.main_window, "data_collection_controller", None), "collecting_data", False))
            except Exception:
                collecting = False
            if not collecting:
                return
        # Prevent recursive calls during update
        if hasattr(self, '_updating_dashboard_table') and self._updating_dashboard_table:
            return
        self._updating_dashboard_table = True
        
        try:
            # Check if table exists
            if not hasattr(self.main_window, 'dashboard_automation_table'):
                print("Warning: dashboard_automation_table not found in main_window")
                return
            
            table = self.main_window.dashboard_automation_table
            if table is None:
                print("Warning: dashboard_automation_table is None")
                return
            
            # --- Preserve Selection ---
            selected_sequence = None
            selected_name = None
            try:
                selected_sequence = self.get_selected_dashboard_sequence()
                if selected_sequence:
                    selected_name = getattr(selected_sequence, 'name', None)
            except Exception as e:
                print(f"Error getting selected sequence: {e}")
                selected_name = None
            
            table.setRowCount(0) # Clear existing rows

            # Get sequences (both running and stopped)
            all_sequences = self.manager.sequences # CORRECTED: Use public attribute
            active_sequences = self.manager.active_sequences # CORRECTED: Use public attribute

            # Log current update for debugging
            print(f"Updating dashboard table - {len(active_sequences)}/{len(all_sequences)} sequences active")

            # Combine and sort: running first, then by name
            # Use safe name access to avoid recursion errors
            def sort_key(seq):
                try:
                    is_active = seq in active_sequences
                    # Safely get name as string
                    name = getattr(seq, 'name', 'Unnamed')
                    if not isinstance(name, str):
                        name = str(name) if name is not None else 'Unnamed'
                    name_lower = name.lower() if name else ''
                    return (not is_active, name_lower) # Sort active first (False comes before True)
                except (RecursionError, AttributeError, TypeError) as e:
                    # Fallback if there's any error accessing the name
                    print(f"Error in sort_key for sequence: {e}")
                    return (True, '') # Put problematic sequences at the end

            try:
                sorted_sequences = sorted(all_sequences, key=sort_key)
            except Exception as e:
                print(f"Error sorting sequences: {e}")
                traceback.print_exc()
                # Fallback: use sequences as-is without sorting
                sorted_sequences = list(all_sequences)

            # If no sequences, show a message
            if not sorted_sequences:
                table.setRowCount(1)
                table.setItem(0, 0, QTableWidgetItem("No automation sequences defined"))
                for col in range(1, 5):
                    table.setItem(0, col, QTableWidgetItem("-"))
                table.viewport().update()
                return

            for row, sequence in enumerate(sorted_sequences):
                table.insertRow(row)

                # Sequence Name - safe access to avoid recursion errors
                try:
                    seq_name = getattr(sequence, 'name', 'Unnamed')
                    if not isinstance(seq_name, str):
                        seq_name = str(seq_name) if seq_name is not None else 'Unnamed'
                except (RecursionError, AttributeError, TypeError) as e:
                    print(f"Error accessing sequence name: {e}")
                    seq_name = 'Unnamed'
                
                name_item = QTableWidgetItem(seq_name)
                table.setItem(row, 0, name_item)

                # Status
                if sequence in active_sequences:
                    status = "Running"
                    status_item = QTableWidgetItem(status)
                elif getattr(sequence, '_current_step_failed', False):
                    status = "Failed"
                    status_item = QTableWidgetItem(status)
                    status_item.setForeground(Qt.GlobalColor.red)
                else:
                    status = "Stopped"
                    status_item = QTableWidgetItem(status)
                table.setItem(row, 1, status_item)

                # Current Step (if running)
                step_text = ""
                next_step_text = ""
                time_trigger_text = ""
                if sequence in active_sequences and hasattr(sequence, 'current_step_index') and 0 <= sequence.current_step_index < len(sequence.steps):
                    step_idx = sequence.current_step_index
                    step = sequence.steps[step_idx]
                    trigger_desc = getattr(step.trigger, 'description', 'Unnamed Trigger')
                    action_desc = getattr(step.action, 'description', 'Unnamed Action')
                    step_text = f"Step {step_idx + 1}: {trigger_desc} -> {action_desc}"

                    # Next Step
                    if step_idx + 1 < len(sequence.steps):
                        next_step = sequence.steps[step_idx + 1]
                        next_trigger_desc = getattr(next_step.trigger, 'description', 'Unnamed Trigger')
                        next_action_desc = getattr(next_step.action, 'description', 'Unnamed Action')
                        next_step_text = f"Step {step_idx + 2}: {next_trigger_desc} -> {next_action_desc}"
                    else:
                        next_step_text = "-"

                    # Time/Trigger: countdown for time-based triggers
                    if (hasattr(step, 'trigger') and 
                        isinstance(step.trigger, TimeDurationTrigger) and 
                        hasattr(step.trigger, 'start_time') and 
                        step.trigger.start_time is not None):
                        
                        # Calculate remaining time
                        elapsed = time.monotonic() - step.trigger.start_time
                        remaining = max(0, step.trigger.duration - elapsed)
                        mins = int(remaining // 60)
                        secs = int(remaining % 60)
                        time_trigger_text = f"{mins:02d}:{secs:02d} left"
                        
                        # Debug info for the timer countdown - use safe name access
                        if active_sequences and sequence == next(iter(active_sequences)):
                            try:
                                safe_name = getattr(sequence, 'name', 'Unknown')
                                if not isinstance(safe_name, str):
                                    safe_name = str(safe_name) if safe_name is not None else 'Unknown'
                                print(f"Timer update for {safe_name}: {mins:02d}:{secs:02d} left (elapsed={elapsed:.1f}s, duration={step.trigger.duration}s)")
                            except:
                                pass  # Skip debug print if name access fails
                    else:
                        # Fallback to trigger description
                        time_trigger_text = trigger_desc
                else:
                    step_text = "-"
                    next_step_text = "-"
                    time_trigger_text = "-"

                step_item = QTableWidgetItem(step_text)
                table.setItem(row, 2, step_item)

                next_step_item = QTableWidgetItem(next_step_text)
                table.setItem(row, 3, next_step_item)

                time_trigger_item = QTableWidgetItem(time_trigger_text)
                table.setItem(row, 4, time_trigger_item)
                
                # Restore selection if this is the sequence that was selected
                if selected_name and seq_name == selected_name:
                    table.selectRow(row)

            # Make sure table refreshes
            # REMOVED: table.resizeColumnsToContents() - prevents manual resizing
            table.viewport().update() # Force viewport update
            self.main_window.update() # Force main window update
            
        except Exception as e:
            # Log any errors that occur during update
            print(f"Error updating dashboard automation table: {e}")
            traceback.print_exc()
            # Try to show a message in the table if possible
            try:
                if hasattr(self.main_window, 'dashboard_automation_table'):
                    table = self.main_window.dashboard_automation_table
                    if table is not None:
                        table.setRowCount(1)
                        table.setItem(0, 0, QTableWidgetItem(f"Error: {str(e)}"))
                        for col in range(1, 5):
                            table.setItem(0, col, QTableWidgetItem("-"))
            except:
                pass  # If we can't even show the error, just skip it
        finally:
            # Always clear the flag, even if an error occurred
            self._updating_dashboard_table = False 

    def _setup_predefined_automations(self):
        """Initialize the list of predefined automation templates."""
        if not hasattr(self.main_window, 'predefined_list'):
            return
            
        self.templates = {
            "📸 Snapshot Every 1m": {
                "name": "Periodic Snapshot (1m)",
                "loop": True,
                "steps": [
                    {
                        "trigger": {"type": "TIME_DURATION", "name": "Wait 1 min", "minutes": 1, "seconds": 0},
                        "action": {"type": "SYSTEM_ACTION", "name": "Take Snapshot", "specific_action_type": "take_snapshot", "parameters": {}},
                        "enabled": True
                    }
                ]
            },
            "🎥 Periodic Recording": {
                "name": "Record 30s every 5m",
                "loop": True,
                "steps": [
                    {
                        "trigger": {"type": "TIME_DURATION", "name": "Wait 5 min", "minutes": 5, "seconds": 0},
                        "action": {"type": "SYSTEM_ACTION", "name": "Start Recording", "specific_action_type": "start_recording", "parameters": {}},
                        "enabled": True
                    },
                    {
                        "trigger": {"type": "TIME_DURATION", "name": "Recording duration", "minutes": 0, "seconds": 30},
                        "action": {"type": "SYSTEM_ACTION", "name": "Stop Recording", "specific_action_type": "stop_recording", "parameters": {}},
                        "enabled": True
                    }
                ]
            },
            "🛡️ Snapshot + Alert": {
                "name": "Snap (1m) & Record on High Temp",
                "loop": True,
                "steps": [
                    {
                        "trigger": {"type": "TIME_DURATION", "name": "1 min interval", "minutes": 1, "seconds": 0},
                        "action": {"type": "SYSTEM_ACTION", "name": "Log Snapshot", "specific_action_type": "take_snapshot", "parameters": {}},
                        "enabled": True
                    },
                    {
                        "trigger": {"type": "TIME_DURATION", "name": "Instant Check", "minutes": 0, "seconds": 0},
                        "action": {
                            "type": "CONDITION", 
                            "name": "Is Temperature High?", 
                            "condition_expression": "{Temperature} > 50", 
                            "if_true_step": 2,  
                            "if_false_step": 0  
                        },
                        "enabled": True
                    },
                    {
                        "trigger": {"type": "TIME_DURATION", "name": "Triggered", "minutes": 0, "seconds": 0},
                        "action": {"type": "SYSTEM_ACTION", "name": "Start Video", "specific_action_type": "start_recording", "parameters": {}},
                        "enabled": True
                    }
                ]
            },
            "⏰ Daily 8AM-9AM Run": {
                "name": "Daily Scheduled Run",
                "loop": True,
                "steps": [
                    {
                        "trigger": {"type": "TIME_DURATION", "name": "Check Status", "minutes": 0, "seconds": 0},
                        "action": {
                            "type": "CONDITION", 
                            "name": "Already running?", 
                            "condition_expression": "{is_running} == True", 
                            "if_true_step": 3, # Jump to Stop Timer
                            "if_false_step": 1 # Continue to Start Timer
                        },
                        "enabled": True
                    },
                    {
                        "trigger": {"type": "TIME_SPECIFIC", "name": "Wait for 8:00 AM", "hour": 8, "minute": 0},
                        "action": {"type": "SYSTEM_ACTION", "name": "Start Acquisition", "specific_action_type": "start_acquisition", "parameters": {}},
                        "enabled": True
                    },
                    {
                        "trigger": {"type": "TIME_DURATION", "name": "Stabilization", "minutes": 0, "seconds": 1},
                        "action": {"type": "INFO_MARKER", "name": "Log Start", "marker_text": "Scheduled run started"},
                        "enabled": True
                    },
                    {
                        "trigger": {"type": "TIME_SPECIFIC", "name": "Wait for 9:00 AM", "hour": 9, "minute": 0},
                        "action": {"type": "SYSTEM_ACTION", "name": "Stop Acquisition", "specific_action_type": "stop_acquisition", "parameters": {}},
                        "enabled": True
                    }
                ]
            },
                "🚀 Test (10s Run)": {
                    "name": "Quick Start/Stop Test",
                    "loop": False,
                    "steps": [
                        {
                            "trigger": {"type": "TIME_DURATION", "name": "Stabilize (1s)", "minutes": 0, "seconds": 1},
                            "action": {"type": "SYSTEM_ACTION", "name": "Start Run", "specific_action_type": "start_acquisition", "parameters": {}},
                            "enabled": True
                        },
                        {
                            "trigger": {"type": "TIME_DURATION", "name": "Wait 10s", "minutes": 0, "seconds": 10},
                            "action": {"type": "SYSTEM_ACTION", "name": "Stop Run", "specific_action_type": "stop_acquisition", "parameters": {}},
                            "enabled": True
                        }
                    ]
                },
            "🏃 Motion Snapshot": {
                "name": "Capture Motion",
                "loop": True,
                "steps": [
                    {
                        "trigger": {"type": "EVENT", "name": "Motion detected", "event_type": "motion_detected"},
                        "action": {"type": "SYSTEM_ACTION", "name": "Snapshot", "specific_action_type": "take_snapshot", "parameters": {}},
                        "enabled": True
                    }
                ]
            },
            "🚨 Sensor Alert": {
                "name": "High Value Alarm",
                "loop": True,
                "steps": [
                    {
                        "trigger": {
                            "type": "SENSOR_VALUE", 
                            "name": "Check A0 > 4.5V", 
                            "sensor_name": "A0", 
                            "operator": ">", 
                            "threshold": 4.5,
                            "hysteresis": 0.1
                        },
                        "action": {"type": "SYSTEM_ACTION", "name": "Play Alert", "specific_action_type": "play_sound", "parameters": {"sound": "beep"}},
                        "enabled": True
                    },
                    {
                        "trigger": {"type": "TIME_DURATION", "name": "Cooldown", "minutes": 0, "seconds": 5},
                        "action": {"type": "INFO_MARKER", "name": "Log Marker", "marker_text": "High sensor value detected on A0!"},
                        "enabled": True
                    }
                ]
            },
            "🔥 Emergency Stop": {
                "name": "Stop on Overheat",
                "loop": True,
                "steps": [
                    {
                        "trigger": {
                            "type": "SENSOR_VALUE", 
                            "name": "Temp > 75°C", 
                            "sensor_name": "Temperature", 
                            "operator": ">", 
                            "threshold": 75.0,
                            "hysteresis": 2.0
                        },
                        "action": {"type": "SYSTEM_ACTION", "name": "Stop Everything", "specific_action_type": "stop_acquisition", "parameters": {}},
                        "enabled": True
                    },
                    {
                        "trigger": {"type": "TIME_DURATION", "name": "Instant", "minutes": 0, "seconds": 0},
                        "action": {"type": "SYSTEM_ACTION", "name": "Alert User", "specific_action_type": "display_message", "parameters": {"title": "SAFETY ALERT", "message": "Acquisition stopped due to high temperature!"}},
                        "enabled": True
                    }
                ]
            },
            "🎤 Acoustic Snap": {
                "name": "Snapshot on Loud Noise",
                "loop": True,
                "steps": [
                    {
                        "trigger": {
                            "type": "AUDIO_EVENT", 
                            "name": "Loud Noise", 
                            "sensor_name": "Microphone", 
                            "event_type": "rms_above", 
                            "threshold": 0.6
                        },
                        "action": {"type": "SYSTEM_ACTION", "name": "Snap", "specific_action_type": "take_snapshot", "parameters": {}},
                        "enabled": True
                    }
                ]
            },
            "📡 MQTT Heartbeat": {
                "name": "Periodic Status Update",
                "loop": True,
                "steps": [
                    {
                        "trigger": {"type": "TIME_DURATION", "name": "5 Min Interval", "minutes": 5, "seconds": 0},
                        "action": {
                            "type": "MQTT_PUBLISH", 
                            "name": "Send Heartbeat", 
                            "topic": "daq/heartbeat", 
                            "payload": "State: {is_running} | Rec: {is_recording}"
                        },
                        "enabled": True
                    }
                ]
            },
            "☀ Auto-Daylight": {
                "name": "Run when Bright",
                "loop": True,
                "steps": [
                    {
                        "trigger": {
                            "type": "OPTICAL_EVENT", 
                            "name": "Sunrise/Lights On", 
                            "sensor_name": "Camera1", 
                            "event_type": "brightness_above", 
                            "threshold": 150
                        },
                        "action": {"type": "SYSTEM_ACTION", "name": "Start", "specific_action_type": "start_acquisition", "parameters": {}},
                        "enabled": True
                    },
                    {
                        "trigger": {
                            "type": "OPTICAL_EVENT", 
                            "name": "Sunset/Lights Off", 
                            "sensor_name": "Camera1", 
                            "event_type": "brightness_below", 
                            "threshold": 50
                        },
                        "action": {"type": "SYSTEM_ACTION", "name": "Stop", "specific_action_type": "stop_acquisition", "parameters": {}},
                        "enabled": True
                    }
                ]
            },
            "📊 Smart Burst": {
                "name": "Record on Spike",
                "loop": True,
                "steps": [
                    {
                        "trigger": {
                            "type": "SENSOR_VALUE", 
                            "name": "Value Spike", 
                            "sensor_name": "A0", 
                            "operator": ">", 
                            "threshold": 4.0
                        },
                        "action": {"type": "SYSTEM_ACTION", "name": "Start Recording", "specific_action_type": "start_recording", "parameters": {}},
                        "enabled": True
                    },
                    {
                        "trigger": {"type": "TIME_DURATION", "name": "10s Burst", "minutes": 0, "seconds": 10},
                        "action": {"type": "SYSTEM_ACTION", "name": "Stop Recording", "specific_action_type": "stop_recording", "parameters": {}},
                        "enabled": True
                    }
                ]
            }
        }
        
        self.main_window.predefined_list.clear()
        for name in self.templates.keys():
            self.main_window.predefined_list.addItem(name)
            
        # Connect double-click signal
        self.main_window.predefined_list.itemDoubleClicked.connect(self._on_template_selected)

    def _on_template_selected(self, item):
        """Load the selected template into the automation manager and save it."""
        template_data = self.templates.get(item.text())
        if not template_data:
            return
            
        try:
            # Create a new sequence from the template data
            new_sequence = AutomationSequence.from_dict(template_data)
            
            # Ensure the name is unique
            base_name = new_sequence.name
            counter = 1
            while any(s.name == new_sequence.name for s in self.manager.sequences):
                new_sequence.name = f"{base_name} ({counter})"
                counter += 1
            
            # Add to manager (this will also trigger a save)
            self.manager.add_sequence(new_sequence)
            
            # Provide feedback
            if hasattr(self.main_window, 'statusBar') and self.main_window.statusBar():
                self.main_window.statusBar().showMessage(f"Loaded template: {new_sequence.name}", 3000)
            
            # Select the newly added sequence in the table
            self.update_sequences_table()
            
        except Exception as e:
            print(f"Error loading template: {e}")
            traceback.print_exc()
            QMessageBox.critical(self.main_window, "Error", f"Failed to load template: {e}")