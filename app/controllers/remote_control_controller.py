"""
Remote Control Controller

Manages remote control permissions and commands with security features.
Provides user-friendly interface for granting and managing remote access.
"""

import time
import secrets
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                            QPushButton, QLineEdit, QTextEdit, QMessageBox,
                            QCheckBox, QComboBox, QGroupBox, QFormLayout,
                            QTableWidget, QTableWidgetItem, QHeaderView)
from PyQt6.QtGui import QColor, QFont

from app.core.logger import Logger

class RemoteControlController(QObject):
    """Manages remote control permissions and commands with security features"""
    
    # Signals
    control_request_received = pyqtSignal(str, str, str)  # client_id, permission, reason
    remote_command_received = pyqtSignal(str, dict)       # command_type, parameters
    permission_granted = pyqtSignal(str, int)             # client_id, permission_level
    permission_revoked = pyqtSignal(str)                  # client_id
    
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.logger = Logger("RemoteControlController")
        
        # Security state
        self.authorized_clients = {}  # {client_id: permission_data}
        self.pending_requests = []    # List of control requests
        self.access_tokens = {}       # {token: token_data}
        self.security_enabled = True
        
        # Permission levels
        self.permission_levels = {
            "view": 1,      # View data only
            "control": 2,   # Control camera/automation
            "admin": 3      # Change settings
        }
        
        # UI elements
        self.setup_ui()
        
        # Security timer for token cleanup
        self.security_timer = QTimer()
        self.security_timer.timeout.connect(self.cleanup_expired_tokens)
        self.security_timer.start(60000)  # Check every minute
        
        self.logger.log("Remote control controller initialized", "INFO")
    
    def setup_ui(self):
        """Setup UI elements for remote control management"""
        # Add remote control button to main window
        if hasattr(self.main_window, 'automation_tab'):
            self.remote_control_btn = QPushButton("🔐 Remote Control Manager")
            self.remote_control_btn.setStyleSheet("""
                QPushButton {
                    background-color: #FF9800;
                    color: white;
                    border: none;
                    padding: 10px;
                    font-size: 14px;
                    border-radius: 6px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #F57C00;
                }
            """)
            self.remote_control_btn.clicked.connect(self.show_remote_control_dialog)
            
            # Add to automation tab if available
            if hasattr(self.main_window, 'automation_layout'):
                self.main_window.automation_layout.addWidget(self.remote_control_btn)
    
    def show_remote_control_dialog(self):
        """Show the remote control management dialog"""
        dialog = RemoteControlDialog(self)
        dialog.exec()
    
    def handle_control_request(self, client_id, permission, reason):
        """Handle incoming remote control request"""
        self.logger.log(f"Control request from {client_id}: {permission}", "INFO")
        
        # Add to pending requests
        request = {
            "client_id": client_id,
            "permission": permission,
            "reason": reason,
            "timestamp": time.time(),
            "status": "pending"
        }
        self.pending_requests.append(request)
        
        # Show confirmation dialog
        dialog = RemoteControlRequestDialog(client_id, permission, reason, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.authorize_client(client_id, dialog.permission_level, dialog.duration_hours)
        else:
            self.reject_control_request(client_id)
    
    def authorize_client(self, client_id, permission_level, duration_hours=1):
        """Authorize a client for remote control"""
        # Generate access token
        access_token = self.generate_access_token(client_id, permission_level, duration_hours)
        
        # Store authorization
        self.authorized_clients[client_id] = {
            "permission_level": permission_level,
            "access_token": access_token,
            "authorized_at": time.time(),
            "expires_at": time.time() + (duration_hours * 3600),
            "last_activity": time.time()
        }
        
        # Update pending request
        for request in self.pending_requests:
            if request["client_id"] == client_id:
                request["status"] = "approved"
                request["permission_level"] = permission_level
                break
        
        self.logger.log(f"Authorized {client_id} with level {permission_level}", "INFO")
        self.permission_granted.emit(client_id, permission_level)
        
        QMessageBox.information(
            self.main_window, 
            "Remote Control Granted", 
            f"Client {client_id} has been granted remote control access (Level {permission_level})"
        )
    
    def reject_control_request(self, client_id):
        """Reject a remote control request"""
        # Update pending request
        for request in self.pending_requests:
            if request["client_id"] == client_id:
                request["status"] = "rejected"
                break
        
        self.logger.log(f"Rejected control request from {client_id}", "INFO")
        
        QMessageBox.information(
            self.main_window,
            "Request Rejected",
            f"Remote control request from {client_id} has been rejected."
        )
    
    def validate_remote_command(self, client_id, command):
        """Validate remote command based on permissions"""
        if client_id not in self.authorized_clients:
            return False, "Client not authorized"
        
        client_data = self.authorized_clients[client_id]
        permission_level = client_data["permission_level"]
        
        # Check if token is expired
        if time.time() > client_data["expires_at"]:
            self.revoke_client_permission(client_id)
            return False, "Access token expired"
        
        # Update last activity
        client_data["last_activity"] = time.time()
        
        # Security rules based on command type
        command_type = command.get("command_type", "")
        
        if command_type == "automation" and permission_level < 2:
            return False, "Insufficient permission for automation control"
        
        if command_type == "settings" and permission_level < 3:
            return False, "Insufficient permission for settings control"
        
        if command_type == "camera_control" and permission_level < 2:
            return False, "Insufficient permission for camera control"
        
        # Log command for security
        self.logger.log(f"Remote command from {client_id}: {command_type}", "INFO")
        
        return True, "Command authorized"
    
    def generate_access_token(self, client_id, permission_level, duration_hours):
        """Generate a secure access token"""
        token = secrets.token_urlsafe(32)
        
        self.access_tokens[token] = {
            "client_id": client_id,
            "permission_level": permission_level,
            "created_at": time.time(),
            "expires_at": time.time() + (duration_hours * 3600)
        }
        
        return token
    
    def validate_token(self, token):
        """Validate an access token"""
        if token not in self.access_tokens:
            return False, None
        
        token_data = self.access_tokens[token]
        if time.time() > token_data["expires_at"]:
            del self.access_tokens[token]
            return False, None
        
        return True, token_data
    
    def revoke_client_permission(self, client_id):
        """Revoke remote control permission for a client"""
        if client_id in self.authorized_clients:
            # Remove access token
            access_token = self.authorized_clients[client_id]["access_token"]
            if access_token in self.access_tokens:
                del self.access_tokens[access_token]
            
            # Remove client
            del self.authorized_clients[client_id]
            
            self.logger.log(f"Revoked permissions for {client_id}", "INFO")
            self.permission_revoked.emit(client_id)
    
    def cleanup_expired_tokens(self):
        """Clean up expired access tokens"""
        current_time = time.time()
        
        # Clean expired tokens
        expired_tokens = [
            token for token, data in self.access_tokens.items()
            if current_time > data["expires_at"]
        ]
        
        for token in expired_tokens:
            del self.access_tokens[token]
        
        # Clean expired client authorizations
        expired_clients = [
            client_id for client_id, data in self.authorized_clients.items()
            if current_time > data["expires_at"]
        ]
        
        for client_id in expired_clients:
            self.revoke_client_permission(client_id)
        
        if expired_tokens or expired_clients:
            self.logger.log(f"Cleaned up {len(expired_tokens)} tokens and {len(expired_clients)} clients", "INFO")
    
    def get_authorized_clients(self):
        """Get list of currently authorized clients"""
        return self.authorized_clients.copy()
    
    def get_pending_requests(self):
        """Get list of pending control requests"""
        return self.pending_requests.copy()


class RemoteControlRequestDialog(QDialog):
    """Dialog for handling remote control requests"""
    
    def __init__(self, client_id, permission, reason, controller):
        super().__init__()
        self.client_id = client_id
        self.permission = permission
        self.reason = reason
        self.controller = controller
        self.permission_level = 1
        self.duration_hours = 1
        
        self.setWindowTitle("Remote Control Request")
        self.setModal(True)
        self.resize(500, 300)
        
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the dialog UI"""
        layout = QVBoxLayout()
        
        # Header
        header_label = QLabel("🔐 Remote Control Request")
        header_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #FF9800;")
        layout.addWidget(header_label)
        
        # Client information
        info_group = QGroupBox("Request Information")
        info_layout = QFormLayout()
        
        info_layout.addRow("Client ID:", QLabel(self.client_id))
        info_layout.addRow("Requested Permission:", QLabel(self.permission))
        info_layout.addRow("Reason:", QLabel(self.reason))
        
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        
        # Permission settings
        permission_group = QGroupBox("Grant Permission")
        permission_layout = QFormLayout()
        
        self.permission_combo = QComboBox()
        self.permission_combo.addItems([
            "View Only (Level 1)",
            "Control (Level 2)", 
            "Admin (Level 3)"
        ])
        self.permission_combo.currentIndexChanged.connect(self.on_permission_changed)
        permission_layout.addRow("Permission Level:", self.permission_combo)
        
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 24)
        self.duration_spin.setValue(1)
        self.duration_spin.setSuffix(" hours")
        self.duration_spin.valueChanged.connect(self.on_duration_changed)
        permission_layout.addRow("Duration:", self.duration_spin)
        
        permission_group.setLayout(permission_layout)
        layout.addWidget(permission_group)
        
        # Warning
        warning_label = QLabel("⚠️ Warning: Granting remote control allows others to control your DAQ system!")
        warning_label.setStyleSheet("color: #f44336; font-weight: bold; padding: 10px;")
        layout.addWidget(warning_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        accept_btn = QPushButton("✅ Accept")
        accept_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 10px 20px;
                font-size: 14px;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        accept_btn.clicked.connect(self.accept)
        
        reject_btn = QPushButton("❌ Reject")
        reject_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                padding: 10px 20px;
                font-size: 14px;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)
        reject_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(accept_btn)
        button_layout.addWidget(reject_btn)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def on_permission_changed(self, index):
        """Handle permission level change"""
        self.permission_level = index + 1
    
    def on_duration_changed(self, value):
        """Handle duration change"""
        self.duration_hours = value


class RemoteControlDialog(QDialog):
    """Dialog for managing remote control permissions"""
    
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Remote Control Manager")
        self.setModal(True)
        self.resize(700, 500)
        
        self.setup_ui()
        self.refresh_data()
    
    def setup_ui(self):
        """Setup the dialog UI"""
        layout = QVBoxLayout()
        
        # Header
        header_label = QLabel("🔐 Remote Control Manager")
        header_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #FF9800;")
        layout.addWidget(header_label)
        
        # Create tab widget
        tab_widget = QTabWidget()
        
        # Authorized clients tab
        authorized_tab = self.create_authorized_clients_tab()
        tab_widget.addTab(authorized_tab, "✅ Authorized Clients")
        
        # Pending requests tab
        pending_tab = self.create_pending_requests_tab()
        tab_widget.addTab(pending_tab, "⏳ Pending Requests")
        
        # Security settings tab
        settings_tab = self.create_security_settings_tab()
        tab_widget.addTab(settings_tab, "⚙️ Security Settings")
        
        # Help tab
        help_tab = self.create_help_tab()
        tab_widget.addTab(help_tab, "❓ Help")
        
        layout.addWidget(tab_widget)
        
        # Refresh button
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self.refresh_data)
        layout.addWidget(refresh_btn)
        
        self.setLayout(layout)
    
    def create_authorized_clients_tab(self):
        """Create the authorized clients tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Table for authorized clients
        self.authorized_table = QTableWidget()
        self.authorized_table.setColumnCount(5)
        self.authorized_table.setHorizontalHeaderLabels([
            "Client ID", "Permission Level", "Authorized At", "Expires At", "Actions"
        ])
        
        header = self.authorized_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        
        layout.addWidget(self.authorized_table)
        
        widget.setLayout(layout)
        return widget
    
    def create_pending_requests_tab(self):
        """Create the pending requests tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Table for pending requests
        self.pending_table = QTableWidget()
        self.pending_table.setColumnCount(5)
        self.pending_table.setHorizontalHeaderLabels([
            "Client ID", "Permission", "Reason", "Status", "Actions"
        ])
        
        header = self.pending_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        
        layout.addWidget(self.pending_table)
        
        widget.setLayout(layout)
        return widget
    
    def create_security_settings_tab(self):
        """Create the security settings tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Security options
        security_group = QGroupBox("Security Options")
        security_layout = QFormLayout()
        
        self.enable_security_check = QCheckBox("Enable Remote Control Security")
        self.enable_security_check.setChecked(self.controller.security_enabled)
        self.enable_security_check.toggled.connect(self.on_security_toggled)
        security_layout.addRow(self.enable_security_check)
        
        self.auto_expire_check = QCheckBox("Auto-expire permissions after inactivity")
        self.auto_expire_check.setChecked(True)
        security_layout.addRow(self.auto_expire_check)
        
        security_group.setLayout(security_layout)
        layout.addWidget(security_group)
        
        # Statistics
        stats_group = QGroupBox("Statistics")
        stats_layout = QFormLayout()
        
        self.total_requests_label = QLabel("0")
        stats_layout.addRow("Total Requests:", self.total_requests_label)
        
        self.active_clients_label = QLabel("0")
        stats_layout.addRow("Active Clients:", self.active_clients_label)
        
        self.expired_tokens_label = QLabel("0")
        stats_layout.addRow("Expired Tokens:", self.expired_tokens_label)
        
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def create_help_tab(self):
        """Create the help tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        help_text = QTextEdit()
        help_text.setReadOnly(True)
        help_text.setHtml("""
        <h2>🔐 Remote Control Security Help</h2>
        
        <h3>Permission Levels</h3>
        <ul>
            <li><b>Level 1 - View Only:</b> Can view sensor data and video</li>
            <li><b>Level 2 - Control:</b> Can control camera and automation</li>
            <li><b>Level 3 - Admin:</b> Can change settings and full control</li>
        </ul>
        
        <h3>Security Features</h3>
        <ul>
            <li><b>Password Protection:</b> All streams require passwords</li>
            <li><b>Time-limited Access:</b> Permissions expire automatically</li>
            <li><b>Activity Monitoring:</b> Track all remote commands</li>
            <li><b>Manual Approval:</b> You must approve each control request</li>
        </ul>
        
        <h3>Best Practices</h3>
        <ul>
            <li>Use strong passwords for your streams</li>
            <li>Grant minimum necessary permissions</li>
            <li>Regularly review authorized clients</li>
            <li>Revoke access when no longer needed</li>
            <li>Monitor activity logs for suspicious behavior</li>
        </ul>
        
        <h3>⚠️ Security Warnings</h3>
        <ul>
            <li>Remote control gives others access to your system</li>
            <li>Only grant access to trusted users</li>
            <li>Be cautious with admin-level permissions</li>
            <li>Monitor system activity during remote sessions</li>
        </ul>
        """)
        
        layout.addWidget(help_text)
        widget.setLayout(layout)
        return widget
    
    def refresh_data(self):
        """Refresh the displayed data"""
        self.refresh_authorized_clients()
        self.refresh_pending_requests()
        self.update_statistics()
    
    def refresh_authorized_clients(self):
        """Refresh the authorized clients table"""
        self.authorized_table.setRowCount(0)
        
        authorized_clients = self.controller.get_authorized_clients()
        
        for row, (client_id, data) in enumerate(authorized_clients.items()):
            self.authorized_table.insertRow(row)
            
            # Client ID
            self.authorized_table.setItem(row, 0, QTableWidgetItem(client_id))
            
            # Permission Level
            level_text = f"Level {data['permission_level']}"
            if data['permission_level'] == 1:
                level_text += " (View)"
            elif data['permission_level'] == 2:
                level_text += " (Control)"
            elif data['permission_level'] == 3:
                level_text += " (Admin)"
            
            self.authorized_table.setItem(row, 1, QTableWidgetItem(level_text))
            
            # Authorized At
            auth_time = time.strftime("%H:%M:%S", time.localtime(data['authorized_at']))
            self.authorized_table.setItem(row, 2, QTableWidgetItem(auth_time))
            
            # Expires At
            expires_time = time.strftime("%H:%M:%S", time.localtime(data['expires_at']))
            self.authorized_table.setItem(row, 3, QTableWidgetItem(expires_time))
            
            # Actions
            revoke_btn = QPushButton("Revoke")
            revoke_btn.clicked.connect(lambda checked, cid=client_id: self.revoke_client(cid))
            self.authorized_table.setCellWidget(row, 4, revoke_btn)
    
    def refresh_pending_requests(self):
        """Refresh the pending requests table"""
        self.pending_table.setRowCount(0)
        
        pending_requests = self.controller.get_pending_requests()
        
        for row, request in enumerate(pending_requests):
            self.pending_table.insertRow(row)
            
            # Client ID
            self.pending_table.setItem(row, 0, QTableWidgetItem(request['client_id']))
            
            # Permission
            self.pending_table.setItem(row, 1, QTableWidgetItem(request['permission']))
            
            # Reason
            self.pending_table.setItem(row, 2, QTableWidgetItem(request['reason']))
            
            # Status
            status_item = QTableWidgetItem(request['status'].title())
            if request['status'] == 'pending':
                status_item.setBackground(QColor(255, 255, 0, 100))  # Yellow
            elif request['status'] == 'approved':
                status_item.setBackground(QColor(0, 255, 0, 100))    # Green
            elif request['status'] == 'rejected':
                status_item.setBackground(QColor(255, 0, 0, 100))    # Red
            
            self.pending_table.setItem(row, 3, status_item)
            
            # Actions (only for pending requests)
            if request['status'] == 'pending':
                approve_btn = QPushButton("Approve")
                approve_btn.clicked.connect(lambda checked, r=request: self.approve_request(r))
                self.pending_table.setCellWidget(row, 4, approve_btn)
    
    def update_statistics(self):
        """Update the statistics display"""
        authorized_clients = self.controller.get_authorized_clients()
        pending_requests = self.controller.get_pending_requests()
        
        self.active_clients_label.setText(str(len(authorized_clients)))
        self.total_requests_label.setText(str(len(pending_requests)))
        
        # Count expired tokens
        expired_count = 0
        current_time = time.time()
        for token_data in self.controller.access_tokens.values():
            if current_time > token_data['expires_at']:
                expired_count += 1
        
        self.expired_tokens_label.setText(str(expired_count))
    
    def revoke_client(self, client_id):
        """Revoke client permissions"""
        reply = QMessageBox.question(
            self, 
            "Revoke Permissions", 
            f"Are you sure you want to revoke permissions for {client_id}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.controller.revoke_client_permission(client_id)
            self.refresh_data()
    
    def approve_request(self, request):
        """Approve a pending request"""
        dialog = RemoteControlRequestDialog(
            request['client_id'], 
            request['permission'], 
            request['reason'], 
            self.controller
        )
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.controller.authorize_client(
                request['client_id'], 
                dialog.permission_level, 
                dialog.duration_hours
            )
            self.refresh_data()
    
    def on_security_toggled(self, enabled):
        """Handle security toggle"""
        self.controller.security_enabled = enabled
        if enabled:
            self.controller.logger.log("Remote control security enabled", "INFO")
        else:
            self.controller.logger.log("Remote control security disabled", "WARNING") 