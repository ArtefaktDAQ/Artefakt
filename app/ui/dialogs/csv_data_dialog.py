import os
import csv
import re
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QMessageBox, QFileDialog, QComboBox, QCheckBox, QWidget, QDialogButtonBox,
    QScrollArea, QDoubleSpinBox
)
from PyQt6.QtCore import Qt, QTimer
from app.ui.theme import DialogStyles, ButtonStyles, TableStyles, COLORS, GroupBoxStyles

class AddEditCSVMappingDialog(QDialog):
    """Dialog for adding or editing a column mapping to a sensor."""
    def __init__(self, parent=None, mapping=None, headers=None):
        super().__init__(parent)
        self.setWindowTitle("Add Sensor Mapping" if mapping is None else "Edit Sensor Mapping")
        self.resize(400, 300)
        self.setStyleSheet(DialogStyles.dark_dialog())
        self.mapping = mapping.copy() if mapping else {
            "column": "", 
            "sensor_name": "", 
            "extract_rule": ""
        }
        self.headers = headers or []
        self.setup_ui()

    def setup_ui(self):
        layout = QFormLayout(self)
        layout.setSpacing(10)

        # Column selection
        self.column_combo = QComboBox()
        if self.headers:
            self.column_combo.addItems(self.headers)
            if self.mapping["column"] in self.headers:
                self.column_combo.setCurrentText(self.mapping["column"])
        else:
            # If no headers, allow manual index entry
            self.column_combo.setEditable(True)
            self.column_combo.setPlaceholderText("Enter column index (0, 1, ...)")
            if self.mapping["column"]:
                self.column_combo.setCurrentText(str(self.mapping["column"]))

        layout.addRow("CSV Column:", self.column_combo)

        # Sensor Name
        self.name_edit = QLineEdit(self.mapping.get("sensor_name", ""))
        self.name_edit.setPlaceholderText("e.g. Temperature")
        layout.addRow("Sensor Name:", self.name_edit)

        # Extraction Rule (Regex)
        self.rule_edit = QLineEdit(self.mapping.get("extract_rule", ""))
        self.rule_edit.setPlaceholderText("Regex, e.g. ([-+]?[0-9.]+)")
        layout.addRow("Extraction Rule:", self.rule_edit)
        
        help_label = QLabel("Tip: ([-+]?[0-9.]+) extracts negative or positive numbers.")
        help_label.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-size: 10px;")
        layout.addRow("", help_label)

        # Buttons
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setStyleSheet(ButtonStyles.success("medium"))
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(ButtonStyles.secondary("medium"))
        
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addRow(btn_layout)

    def get_mapping(self):
        col = self.column_combo.currentText()
        if col.isdigit():
            col = int(col)
        return {
            "column": col,
            "sensor_name": self.name_edit.text().strip(),
            "extract_rule": self.rule_edit.text().strip()
        }

class AddEditCSVConfigDialog(QDialog):
    """Dialog for adding or editing a CSV file configuration."""
    def __init__(self, parent=None, config=None, global_rate=10.0):
        super().__init__(parent)
        self.setWindowTitle("CSV Configuration")
        self.resize(600, 500)
        self.setStyleSheet(DialogStyles.dark_dialog())
        
        self.global_rate = global_rate
        self.config = config.copy() if config else {
            "file": "", 
            "poll": 1.0 / global_rate, 
            "enabled": True, 
            "mappings": [],
            "delimiter": "Auto",
            "decimal_separator": "."
        }
        self.headers = []
        self.setup_ui()
        if self.config["file"]:
            self._load_headers()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        form_group = QGroupBox("File Settings")
        form_group.setStyleSheet(GroupBoxStyles.elevated())
        form_layout = QFormLayout(form_group)
        
        # File path selection
        file_layout = QHBoxLayout()
        self.file_edit = QLineEdit(self.config["file"])
        self.file_edit.setReadOnly(True)
        browse_btn = QPushButton("Browse...")
        browse_btn.setStyleSheet(ButtonStyles.secondary("small"))
        browse_btn.clicked.connect(self._browse_file)
        file_layout.addWidget(self.file_edit)
        file_layout.addWidget(browse_btn)
        form_layout.addRow("CSV File:", file_layout)
        
        # Poll interval (Hz) - Styled like Projects Tab
        poll_layout = QHBoxLayout()
        poll_layout.setSpacing(8)
        
        self.poll_spin = QDoubleSpinBox()
        self.poll_spin.setRange(0.001, 1000.0)
        self.poll_spin.setDecimals(3)
        # Initialize with current poll value (Hz)
        current_interval = float(self.config.get("poll", 1.0 / self.global_rate))
        current_hz = 1.0 / current_interval if current_interval > 0 else self.global_rate
        self.poll_spin.setValue(current_hz)
        self.poll_spin.setToolTip(f"The global sampling rate is {self.global_rate} Hz.")
        
        poll_layout.addWidget(self.poll_spin)
        poll_unit_label = QLabel("Hz")
        poll_layout.addWidget(poll_unit_label)
        poll_layout.addStretch(1)
        
        form_layout.addRow("Poll Rate:", poll_layout)
        
        rate_info = QLabel(f"Global rate: {self.global_rate:.3f} Hz. Override if CSV updates slower.")
        rate_info.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY}; font-size: 10px;")
        form_layout.addRow("", rate_info)
        
        # CSV Format Settings
        self.delimiter_combo = QComboBox()
        self.delimiter_combo.addItems(["Auto", ",", ";", "\\t (Tab)", "|", "Space"])
        self.delimiter_combo.setEditable(True)
        delim = self.config.get("delimiter", "Auto")
        if delim == "\t": self.delimiter_combo.setCurrentText("\\t (Tab)")
        elif delim == " ": self.delimiter_combo.setCurrentText("Space")
        else: self.delimiter_combo.setCurrentText(str(delim))
        form_layout.addRow("Delimiter:", self.delimiter_combo)

        self.decimal_combo = QComboBox()
        self.decimal_combo.addItems([". (Dot)", ", (Comma)"])
        self.decimal_combo.setCurrentIndex(1 if self.config.get("decimal_separator") == "," else 0)
        form_layout.addRow("Decimal Point:", self.decimal_combo)

        self.enabled_check = QCheckBox("Enabled")
        self.enabled_check.setChecked(self.config.get("enabled", True))
        form_layout.addRow(self.enabled_check)
        
        layout.addWidget(form_group)
        
        # Mappings section
        mappings_group = QGroupBox("Sensor Mappings")
        mappings_group.setStyleSheet(GroupBoxStyles.elevated())
        mappings_layout = QVBoxLayout(mappings_group)
        
        self.mappings_table = QTableWidget(0, 3)
        self.mappings_table.setHorizontalHeaderLabels(["Column", "Sensor Name", "Extraction"])
        self.mappings_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.mappings_table.setStyleSheet(TableStyles.default())
        self.mappings_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        mappings_layout.addWidget(self.mappings_table)
        
        # Buttons for mappings
        mapping_btns = QHBoxLayout()
        add_btn = QPushButton("Add Mapping")
        add_btn.setStyleSheet(ButtonStyles.secondary("small"))
        add_btn.clicked.connect(self._add_mapping)
        
        edit_btn = QPushButton("Edit")
        edit_btn.setStyleSheet(ButtonStyles.secondary("small"))
        edit_btn.clicked.connect(self._edit_mapping)
        
        remove_btn = QPushButton("Remove")
        remove_btn.setStyleSheet(ButtonStyles.secondary("small"))
        remove_btn.clicked.connect(self._remove_mapping)
        
        mapping_btns.addWidget(add_btn)
        mapping_btns.addWidget(edit_btn)
        mapping_btns.addWidget(remove_btn)
        mapping_btns.addStretch()
        mappings_layout.addLayout(mapping_btns)
        
        layout.addWidget(mappings_group)
        
        # Preview Section
        preview_group = QGroupBox("Live Preview")
        preview_group.setStyleSheet(GroupBoxStyles.elevated())
        preview_layout = QVBoxLayout(preview_group)
        self.preview_label = QLabel("Waiting for data...")
        self.preview_label.setStyleSheet(f"color: {COLORS.SUCCESS}; font-family: monospace; font-size: 10px;")
        self.preview_label.setWordWrap(True)
        preview_layout.addWidget(self.preview_label)
        layout.addWidget(preview_group)
        
        # Bottom buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self._update_mappings_table()
        
        # Start preview timer
        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._update_preview)
        self.preview_timer.start(1000)

    def closeEvent(self, event):
        if hasattr(self, 'preview_timer') and self.preview_timer:
            self.preview_timer.stop()
        super().closeEvent(event)

    def reject(self):
        if hasattr(self, 'preview_timer') and self.preview_timer:
            self.preview_timer.stop()
        super().reject()

    def _validate_config(self):
        file_path = self.file_edit.text().strip()
        if not file_path:
            QMessageBox.warning(self, "Validation Error", "Please select a CSV file.")
            return False
        for mapping in self.config.get("mappings", []):
            if not mapping.get("sensor_name", "").strip():
                QMessageBox.warning(self, "Validation Error", "Each mapping must have a sensor name.")
                return False
            rule = mapping.get("extract_rule", "").strip()
            if rule:
                try:
                    re.compile(rule)
                except re.error as e:
                    QMessageBox.warning(self, "Validation Error", f"Invalid extraction regex: {e}")
                    return False
        return True

    def accept(self):
        if not self._validate_config():
            return
        super().accept()

    def _update_preview(self):
        file_path = self.file_edit.text()
        if not file_path or not os.path.exists(file_path):
            self.preview_label.setText("No file selected or file missing.")
            return
            
        try:
            with open(file_path, 'r', newline='', encoding='utf-8') as f:
                f.seek(0, os.SEEK_END)
                pos = f.tell()
                if pos == 0:
                    self.preview_label.setText("File is empty.")
                    return
                    
                buffer = ""
                # Read last 4KB
                search_limit = max(0, pos - 4096)
                while pos > search_limit:
                    pos -= 1
                    f.seek(pos)
                    char = f.read(1)
                    if char == '\n' and buffer: break
                    if char not in ('\r', '\n'): buffer = char + buffer
                
                if not buffer:
                    self.preview_label.setText("Could not find data line.")
                    return
                
                # Get current format settings
                delim = self.delimiter_combo.currentText()
                if delim == "Auto":
                    try:
                        # Try to sniff from the buffer or start of file
                        dialect = csv.Sniffer().sniff(buffer, delimiters=',;\t| ')
                        delim = dialect.delimiter
                    except Exception:
                        delim = ',' # Fallback
                elif delim == "\\t (Tab)": delim = "\t"
                elif delim == "Space": delim = " "
                
                dec_sep = "," if self.decimal_combo.currentIndex() == 1 else "."

                reader = csv.reader([buffer], delimiter=delim)
                row = next(reader, None)
                if not row:
                    self.preview_label.setText("Row is empty.")
                    return
                
                preview_text = f"Last line (delim='{delim}'): {delim.join(row)}\n\n"
                preview_text += "Parsing Results:\n"
                
                for m in self.config["mappings"]:
                    col_key = m["column"]
                    idx = -1
                    if isinstance(col_key, int):
                        idx = col_key
                    elif self.headers:
                        try:
                            idx = self.headers.index(col_key)
                        except ValueError:
                            if str(col_key).isdigit(): idx = int(col_key)
                    
                    if 0 <= idx < len(row):
                        raw_val = row[idx]
                        extracted = raw_val
                        rule = m.get("extract_rule")
                        if rule:
                            try:
                                match = re.search(rule, raw_val)
                                if match:
                                    extracted = match.group(1) if match.groups() else match.group(0)
                                else:
                                    extracted = "[No Match]"
                            except Exception as e:
                                extracted = f"[Regex Error: {e}]"
                        
                        # Clean numerical
                        try:
                            clean_text = str(extracted).strip()
                            # Handle decimal separator
                            if dec_sep != '.' and dec_sep in clean_text:
                                clean_text = clean_text.replace(dec_sep, '.')
                            
                            num_match = re.search(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', clean_text)
                            if num_match:
                                final_val = float(num_match.group(0))
                                status = "✅"
                            else:
                                final_val = "NaN"
                                status = "❌"
                        except Exception as e:
                            final_val = f"Err: {str(e)}"
                            status = "❌"
                            
                        preview_text += f"• {m['sensor_name']}: {raw_val} -> {extracted} ({final_val}) {status}\n"
                    else:
                        preview_text += f"• {m['sensor_name']}: Column index {idx} out of range\n"
                
                self.preview_label.setText(preview_text)
        except Exception as e:
            self.preview_label.setText(f"Error reading file: {e}")

    def _browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select CSV File", "", "CSV Files (*.csv);;All Files (*)")
        if file_path:
            self.file_edit.setText(file_path)
            self.config["file"] = file_path
            self._load_headers()

    def _load_headers(self):
        if not os.path.exists(self.config["file"]):
            return
        
        delim = self.delimiter_combo.currentText()
        if delim == "Auto":
            try:
                with open(self.config["file"], 'r', encoding='utf-8') as f:
                    sample = f.read(2048)
                    dialect = csv.Sniffer().sniff(sample, delimiters=',;\t| ')
                    delim = dialect.delimiter
            except Exception:
                delim = ',' # Fallback
        elif delim == "\\t (Tab)": delim = "\t"
        elif delim == "Space": delim = " "

        try:
            with open(self.config["file"], 'r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f, delimiter=delim)
                self.headers = next(reader, [])
        except Exception:
            self.headers = []

    def _update_mappings_table(self):
        self.mappings_table.setRowCount(0)
        for i, m in enumerate(self.config["mappings"]):
            self.mappings_table.insertRow(i)
            self.mappings_table.setItem(i, 0, QTableWidgetItem(str(m["column"])))
            self.mappings_table.setItem(i, 1, QTableWidgetItem(m["sensor_name"]))
            self.mappings_table.setItem(i, 2, QTableWidgetItem(m["extract_rule"]))

    def _add_mapping(self):
        dialog = AddEditCSVMappingDialog(self, headers=self.headers)
        if dialog.exec():
            self.config["mappings"].append(dialog.get_mapping())
            self._update_mappings_table()

    def _edit_mapping(self):
        row = self.mappings_table.currentRow()
        if row < 0: return
        dialog = AddEditCSVMappingDialog(self, mapping=self.config["mappings"][row], headers=self.headers)
        if dialog.exec():
            self.config["mappings"][row] = dialog.get_mapping()
            self._update_mappings_table()

    def _remove_mapping(self):
        row = self.mappings_table.currentRow()
        if row < 0: return
        del self.config["mappings"][row]
        self._update_mappings_table()

    def get_config(self):
        file_path = self.file_edit.text().strip()
        if not file_path:
            raise ValueError("Please select a CSV file.")
        for mapping in self.config.get("mappings", []):
            if not mapping.get("sensor_name", "").strip():
                raise ValueError("Each mapping must have a sensor name.")
            rule = mapping.get("extract_rule", "").strip()
            if rule:
                re.compile(rule)

        # Convert Hz to interval (seconds) for internal storage
        hz = self.poll_spin.value()
        interval = 1.0 / hz if hz > 0 else 1.0
        
        delim = self.delimiter_combo.currentText()
        if delim == "\\t (Tab)": delim = "\t"
        elif delim == "Space": delim = " "
        
        dec_sep = "," if self.decimal_combo.currentIndex() == 1 else "."

        return {
            "file": file_path,
            "poll": interval,
            "enabled": self.enabled_check.isChecked(),
            "mappings": self.config["mappings"],
            "delimiter": delim,
            "decimal_separator": dec_sep
        }

class CSVDataDialog(QDialog):
    """Main dialog for managing all CSV file configurations."""
    def __init__(self, parent=None, configs=None, global_rate=10.0):
        super().__init__(parent)
        self.setWindowTitle("CSV Data Interface Management")
        self.resize(700, 500)
        self.setStyleSheet(DialogStyles.dark_dialog())
        
        self.configs = configs or []
        self.global_rate = global_rate
        self.setup_ui()
        self._update_table()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        header = QLabel("📄 CSV Data Interfaces")
        header.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {COLORS.TEXT_PRIMARY};")
        layout.addWidget(header)
        
        desc = QLabel("Configure the application to read values from external CSV files. For each file, you can map columns to virtual sensors.")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS.TEXT_SECONDARY};")
        layout.addWidget(desc)
        
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["File", "Mappings", "Enabled"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setStyleSheet(TableStyles.default())
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("Add CSV File")
        add_btn.setStyleSheet(ButtonStyles.success("medium"))
        add_btn.clicked.connect(self._add_config)
        
        edit_btn = QPushButton("Edit")
        edit_btn.setStyleSheet(ButtonStyles.primary("medium"))
        edit_btn.clicked.connect(self._edit_config)
        
        remove_btn = QPushButton("Remove")
        remove_btn.setStyleSheet(ButtonStyles.danger("medium"))
        remove_btn.clicked.connect(self._remove_config)
        
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(remove_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        for i, cfg in enumerate(self.configs):
            file_path = cfg.get("file", "").strip()
            if not file_path:
                QMessageBox.warning(self, "Validation Error", f"Configuration #{i + 1} is missing a CSV file path.")
                return
            for mapping in cfg.get("mappings", []):
                if not mapping.get("sensor_name", "").strip():
                    QMessageBox.warning(
                        self, "Validation Error",
                        f"Configuration #{i + 1} has a mapping without a sensor name."
                    )
                    return
                rule = mapping.get("extract_rule", "").strip()
                if rule:
                    try:
                        re.compile(rule)
                    except re.error as e:
                        QMessageBox.warning(
                            self, "Validation Error",
                            f"Configuration #{i + 1} has an invalid regex: {e}"
                        )
                        return
        super().accept()

    def _update_table(self):
        self.table.setRowCount(0)
        for i, cfg in enumerate(self.configs):
            self.table.insertRow(i)
            self.table.setItem(i, 0, QTableWidgetItem(os.path.basename(cfg["file"])))
            self.table.setItem(i, 1, QTableWidgetItem(f"{len(cfg['mappings'])} sensors"))
            self.table.setItem(i, 2, QTableWidgetItem("Yes" if cfg["enabled"] else "No"))

    def _add_config(self):
        dialog = AddEditCSVConfigDialog(self, global_rate=self.global_rate)
        if dialog.exec():
            self.configs.append(dialog.get_config())
            self._update_table()

    def _edit_config(self):
        row = self.table.currentRow()
        if row < 0: return
        dialog = AddEditCSVConfigDialog(self, config=self.configs[row], global_rate=self.global_rate)
        if dialog.exec():
            self.configs[row] = dialog.get_config()
            self._update_table()

    def _remove_config(self):
        row = self.table.currentRow()
        if row < 0: return
        del self.configs[row]
        self._update_table()

