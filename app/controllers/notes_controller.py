"""
Notes Controller

Manages the notes editor functionality and operations.
"""
import os
import base64
import datetime
import shutil
import html
import re
import json
import copy
import hashlib
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QTimer, QByteArray, QBuffer, QIODevice, QUrl
from PyQt6.QtGui import (QFont, QColor, QTextCharFormat, QTextListFormat, 
                         QPixmap, QIcon, QImage, QAction, QTextImageFormat, 
                         QTextCursor, QGuiApplication)
from PyQt6.QtWidgets import (QColorDialog, QFontDialog, QMenu, QPushButton, 
                             QToolBar, QToolButton, QComboBox, QDialog, QWidget,
                             QVBoxLayout, QHBoxLayout, QLabel, QDialogButtonBox, 
                             QFileDialog, QFormLayout, QSpinBox, QCheckBox, 
                             QGroupBox, QApplication, QStyle, QProxyStyle, 
                             QStyleOptionComboBox, QMessageBox)

from app.ui.theme import COLORS

class NarrowScrollBarStyle(QProxyStyle):
    """Custom style to provide narrow scrollbars for combo boxes"""
    
    def __init__(self, style=None):
        super().__init__(style)
        
    def pixelMetric(self, metric, option=None, widget=None):
        """Override pixel metrics to set a narrow scrollbar"""
        if metric == QStyle.PixelMetric.PM_ScrollBarExtent:
            return 8  # Set scrollbar width to 8 pixels
        return super().pixelMetric(metric, option, widget)

class NotesController(QObject):
    """Controls notes editor and related operations"""
    
    def __init__(self, main_window):
        """
        Initialize the notes controller
        
        Args:
            main_window: Main application window
        """
        super().__init__()
        self.main_window = main_window
        self.notes_editor = self.main_window.notes_text_edit
        
        # Setup custom style for narrow scrollbars
        self.custom_style = NarrowScrollBarStyle()
        
        # Template path
        self.template_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                                        "templates", "notes_template.html")
        
        # Enhance the toolbar with more formatting options
        self.setup_enhanced_toolbar()
        
        # Connect basic formatting buttons that are already in the UI
        self.connect_basic_formatting()
        
        # Enable context menu for the editor to allow image resizing
        self.notes_editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.notes_editor.customContextMenuRequested.connect(self.show_context_menu)
        
        # Keep track of the currently selected image for resize button
        self.selected_image = None
        self.notes_editor.cursorPositionChanged.connect(self.update_selected_image)
        
        # Set up autosave functionality
        self.autosave_timer = QTimer()
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.timeout.connect(self.autosave_note)
        
        # Connect text changed signal for autosave
        self.notes_editor.textChanged.connect(self.trigger_autosave)
        
        # Keep track of the current document content hash to avoid unnecessary saves
        self.last_saved_content_hash = None
        
        # Flag to track if document is loaded - prevents deletion before load
        self.document_loaded = False
        
        # Flag to track if template has been populated to avoid overwriting user edits
        self.template_populated = False
        
        # Connect to tab selection change to update template when notes tab is selected
        if hasattr(self.main_window, 'stacked_widget'):
            self.main_window.stacked_widget.currentChanged.connect(self.on_tab_changed)
        
    def append_to_note(self, html_content):
        """Append HTML content to the end of the current note"""
        if not self.notes_editor:
            return
            
        # Move cursor to absolute end of document
        cursor = self.notes_editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.notes_editor.setTextCursor(cursor)
        
        # Insert the content at the end
        self.notes_editor.insertHtml(html_content)
        
        # Move cursor to the new end to ensure proper positioning
        cursor = self.notes_editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.notes_editor.setTextCursor(cursor)
        
        # Ensure it's saved
        self.trigger_autosave()

    def on_tab_changed(self, index):
        """Called when the tab selection changes in the stacked widget"""
        # Find the notes tab index dynamically
        notes_tab_index = -1
        if hasattr(self.main_window, 'notes_tab'):
            notes_tab_index = self.main_window.stacked_widget.indexOf(self.main_window.notes_tab)
        else:
            # Fallback to hardcoded index if reference is missing
            for i in range(self.main_window.stacked_widget.count()):
                if i == 7:  # Notes tab is typically at index 7
                    notes_tab_index = i
                    break
                
        # If we've switched to the notes tab, refresh the template data
        if index == notes_tab_index:
            self.refresh_template()
            
    def refresh_template(self):
        """Refresh the template data if notes are based on the template"""
        # Check if the document is already loaded
        if not self.document_loaded:
            self.load_note()
            return
            
        # Get the HTML content
        html_content = self.notes_editor.toHtml()
        
        # Check if this looks like our template (containing key markers)
        template_markers = ["[Project Name]", "[Test Series Name]", "[Run Name]", "[Run Testers]"]
        
        is_template_based = False
        for marker in template_markers:
            if marker in html_content:
                is_template_based = True
                break
                
        # Only refresh if it's template-based and hasn't been fully populated yet
        # OR if it's explicit (we could add a button for this)
        if is_template_based:
            # It contains template markers, so we should refresh the data
            cursor = self.notes_editor.textCursor()
            cursor_pos = cursor.position()
            
            # Replace placeholders with updated data
            updated_html = self.populate_template(html_content)
            
            # Only update if there are changes to avoid resetting the editor state
            if updated_html != html_content:
                self.notes_editor.setHtml(updated_html)
                
                # Restore cursor position if possible
                cursor = self.notes_editor.textCursor()
                if cursor_pos < self.notes_editor.document().characterCount():
                    cursor.setPosition(cursor_pos)
                    self.notes_editor.setTextCursor(cursor)
                
                self.main_window.logger.log("Notes template refreshed with latest data", "DEBUG") 

    def update_selected_image(self):
        """Update the currently selected image when cursor changes"""
        cursor = self.notes_editor.textCursor()
        char_format = cursor.charFormat()
        
        if char_format.isImageFormat():
            self.selected_image = char_format.toImageFormat()
        else:
            self.selected_image = None
            
    def setup_enhanced_toolbar(self):
        """Setup enhanced formatting toolbar with more options"""
        
        # Create a proper toolbar above the existing buttons
        toolbar = QToolBar()
        
        toolbar.setStyleSheet(f"""
            QToolBar {{ 
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {COLORS.BG_ELEVATED}, stop:1 {COLORS.BG_CARD});
                border: 1px solid {COLORS.BORDER_DEFAULT}; 
                spacing: 6px; 
                padding: 4px 8px; 
                border-radius: 10px;
                margin-bottom: 8px;
                min-height: 32px;
            }}
            QToolButton {{
                background: {COLORS.BG_INPUT};
                color: {COLORS.TEXT_PRIMARY};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 5px;
                padding: 3px 6px;
                margin: 1px;
                min-width: 24px;
                min-height: 24px;
                font-weight: 500;
            }}
            QToolButton:hover {{
                background: {COLORS.BG_ELEVATED};
                border-color: {COLORS.PRIMARY};
                color: {COLORS.TEXT_PRIMARY};
            }}
            QToolButton:pressed {{
                background: {COLORS.PRIMARY_SUBTLE};
            }}
            QComboBox {{
                background: {COLORS.BG_INPUT};
                color: {COLORS.TEXT_PRIMARY};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 5px;
                padding: 2px 6px;
                min-height: 24px;
            }}
            QComboBox:hover {{
                border-color: {COLORS.PRIMARY};
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 16px;
                border-left: 1px solid {COLORS.BORDER_DEFAULT};
                border-top-right-radius: 5px;
                border-bottom-right-radius: 5px;
            }}
            QComboBox QAbstractItemView {{
                background: {COLORS.BG_ELEVATED};
                color: {COLORS.TEXT_PRIMARY};
                selection-background-color: rgba(108, 92, 231, 0.45);
                selection-color: {COLORS.TEXT_PRIMARY};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 5px;
                padding: 2px;
            }}
            QSpinBox {{
                background: {COLORS.BG_INPUT};
                color: {COLORS.TEXT_PRIMARY};
                border: 1px solid {COLORS.BORDER_DEFAULT};
                border-radius: 5px;
                padding: 2px 6px;
                min-height: 24px;
            }}
            QSpinBox:hover {{
                border-color: {COLORS.PRIMARY};
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                background: {COLORS.BG_ELEVATED};
                border: none;
                width: 14px;
            }}
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
                background: {COLORS.PRIMARY_SUBTLE};
            }}
        """)
        
        # Add font family selector
        self.font_family = QComboBox()
        self.font_family.addItems(["Arial", "Segoe UI", "Times New Roman", "Courier New", "Verdana", "Georgia"])
        self.font_family.setCurrentText("Segoe UI")
        self.font_family.setToolTip("Font Family")
        self.font_family.setStyleSheet("min-width: 120px;")
        self.font_family.currentTextChanged.connect(self.apply_font_family)
        toolbar.addWidget(self.font_family)
        
        # Add font size selector (Spinbox)
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 36) # Set range from 8 to 36
        self.font_size.setValue(14)  # Set initial value
        self.font_size.setSuffix(" pt") # Add 'pt' suffix
        self.font_size.setToolTip("Font Size")
        self.font_size.setStyleSheet("min-width: 60px; max-width: 60px;") # Set size
        self.font_size.valueChanged.connect(self.apply_font_size)
        toolbar.addWidget(self.font_size)
        
        # Text formatting buttons
        # Bold button
        bold_btn = QToolButton()
        bold_btn.setText("B")
        bold_btn.setToolTip("Bold")
        bold_btn.setStyleSheet("font-weight: bold;")
        bold_btn.clicked.connect(self.toggle_bold)
        toolbar.addWidget(bold_btn)
        
        # Italic button
        italic_btn = QToolButton()
        italic_btn.setText("I")
        italic_btn.setToolTip("Italic")
        italic_btn.setStyleSheet("font-style: italic;")
        italic_btn.clicked.connect(self.toggle_italic)
        toolbar.addWidget(italic_btn)
        
        # Underline button
        underline_btn = QToolButton()
        underline_btn.setText("U")
        underline_btn.setToolTip("Underline")
        underline_btn.setStyleSheet("text-decoration: underline;")
        underline_btn.clicked.connect(self.toggle_underline)
        toolbar.addWidget(underline_btn)
        
        toolbar.addSeparator()
        
        # Text color button
        text_color_btn = QToolButton()
        text_color_btn.setText("A")
        text_color_btn.setToolTip("Text Color")
        text_color_btn.setStyleSheet("color: #4CAF50;")
        text_color_btn.clicked.connect(self.choose_text_color)
        toolbar.addWidget(text_color_btn)
        
        # Background color button
        bg_color_btn = QToolButton()
        bg_color_btn.setText("BG")
        bg_color_btn.setToolTip("Background Color")
        bg_color_btn.setStyleSheet("background-color: #4CAF50; color: white;")
        bg_color_btn.clicked.connect(self.choose_bg_color)
        toolbar.addWidget(bg_color_btn)
        
        # Media buttons
        formula_btn = QToolButton()
        formula_btn.setText("🖼️")
        formula_btn.setToolTip("Insert Image")
        formula_btn.clicked.connect(self.insert_formula)
        toolbar.addWidget(formula_btn)
        
        # Add list formatting buttons
        toolbar.addSeparator()
        
        bullet_list_btn = QToolButton()
        bullet_list_btn.setText("•")
        bullet_list_btn.setToolTip("Bullet List")
        bullet_list_btn.clicked.connect(self.toggle_bullet_list)
        toolbar.addWidget(bullet_list_btn)
        
        number_list_btn = QToolButton()
        number_list_btn.setText("1.")
        number_list_btn.setToolTip("Numbered List")
        number_list_btn.clicked.connect(self.toggle_numbered_list)
        toolbar.addWidget(number_list_btn)
        
        # Add alignment buttons
        toolbar.addSeparator()
        
        align_left_btn = QToolButton()
        align_left_btn.setText("⇐")
        align_left_btn.setToolTip("Align Left")
        align_left_btn.clicked.connect(lambda: self.set_alignment(Qt.AlignmentFlag.AlignLeft))
        toolbar.addWidget(align_left_btn)
        
        align_center_btn = QToolButton()
        align_center_btn.setText("⇔")
        align_center_btn.setToolTip("Align Center")
        align_center_btn.clicked.connect(lambda: self.set_alignment(Qt.AlignmentFlag.AlignCenter))
        toolbar.addWidget(align_center_btn)
        
        align_right_btn = QToolButton()
        align_right_btn.setText("⇒")
        align_right_btn.setToolTip("Align Right")
        align_right_btn.clicked.connect(lambda: self.set_alignment(Qt.AlignmentFlag.AlignRight))
        toolbar.addWidget(align_right_btn)
        
        # Add additional media buttons
        toolbar.addSeparator()
        
        graph_btn = QToolButton()
        graph_btn.setText("G")
        graph_btn.setToolTip("Insert Graph")
        graph_btn.clicked.connect(self.insert_graph_image)
        toolbar.addWidget(graph_btn)
        
        video_btn = QToolButton()
        video_btn.setText("C")
        video_btn.setToolTip("Insert Camera Image")
        video_btn.clicked.connect(self.insert_video_image)
        toolbar.addWidget(video_btn)
        
        resize_img_btn = QToolButton()
        resize_img_btn.setText("⚙️")
        resize_img_btn.setToolTip("Resize Selected Image")
        resize_img_btn.clicked.connect(self.resize_selected_image)
        toolbar.addWidget(resize_img_btn)
        
        # Add clear formatting button
        clear_format_btn = QToolButton()
        clear_format_btn.setText("Clear")
        clear_format_btn.setToolTip("Clear Formatting")
        clear_format_btn.clicked.connect(self.clear_formatting)
        toolbar.addWidget(clear_format_btn)
        
        # Find the notes tab dynamically
        notes_tab = getattr(self.main_window, 'notes_tab', None)
        if notes_tab:
            notes_layout = notes_tab.layout()
            if notes_layout:
                notes_layout.insertWidget(0, toolbar)
                self.main_window.logger.log("Added advanced formatting toolbar to notes tab", "DEBUG")
        else:
            # Fallback to hardcoded index if reference is missing
            for i in range(self.main_window.stacked_widget.count()):
                if i == 7:  # Notes tab is typically at index 7
                    notes_tab = self.main_window.stacked_widget.widget(i)
                    notes_layout = notes_tab.layout()
                    
                    # Insert the toolbar at the beginning of the layout
                    if notes_layout:
                        notes_layout.insertWidget(0, toolbar)
                        self.main_window.logger.log("Added advanced formatting toolbar to notes tab (fallback)", "DEBUG")
                    break
            
    def connect_basic_formatting(self):
        """Connect basic formatting buttons to text editor"""
        # No default buttons to connect - all provided by enhanced toolbar
        pass
        
    def toggle_bold(self):
        """Toggle bold formatting"""
        cursor = self.notes_editor.textCursor()
        format = QTextCharFormat()
        if cursor.charFormat().fontWeight() == QFont.Weight.Bold:
            format.setFontWeight(QFont.Weight.Normal)
        else:
            format.setFontWeight(QFont.Weight.Bold)
        cursor.mergeCharFormat(format)
        self.notes_editor.mergeCurrentCharFormat(format)
        
    def toggle_italic(self):
        """Toggle italic formatting"""
        cursor = self.notes_editor.textCursor()
        format = QTextCharFormat()
        format.setFontItalic(not cursor.charFormat().fontItalic())
        cursor.mergeCharFormat(format)
        self.notes_editor.mergeCurrentCharFormat(format)
        
    def apply_font_family(self, family):
        """Apply font family to selected text"""
        format = QTextCharFormat()
        format.setFontFamily(family)
        self.notes_editor.textCursor().mergeCharFormat(format)
        
    def apply_font_size(self, size):
        """Apply font size to selected text"""
        format = QTextCharFormat()
        # The size is already an integer from the spinbox
        format.setFontPointSize(float(size))
        self.notes_editor.textCursor().mergeCharFormat(format)
        
    def choose_text_color(self):
        """Open color dialog to choose text color"""
        current_color = self.notes_editor.textColor()
        color = QColorDialog.getColor(current_color, self.main_window)
        if color.isValid():
            format = QTextCharFormat()
            format.setForeground(color)
            self.notes_editor.textCursor().mergeCharFormat(format)
            
    def choose_bg_color(self):
        """Open color dialog to choose background color"""
        cursor = self.notes_editor.textCursor()
        current_format = cursor.charFormat()
        current_bg = current_format.background().color()
        color = QColorDialog.getColor(current_bg, self.main_window)
        if color.isValid():
            format = QTextCharFormat()
            format.setBackground(color)
            cursor.mergeCharFormat(format)
            
    def toggle_underline(self):
        """Toggle underline formatting on selected text"""
        cursor = self.notes_editor.textCursor()
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not cursor.charFormat().fontUnderline())
        cursor.mergeCharFormat(fmt)
        
    def toggle_bullet_list(self):
        """Toggle bullet list for selected paragraphs"""
        cursor = self.notes_editor.textCursor()
        list_format = QTextListFormat()
        
        # If we already have a bullet list, remove it
        if cursor.currentList():
            # We're already in a list, so remove it
            current_list = cursor.currentList()
            for i in range(current_list.count()):
                current_list.removeItem(0)  # Remove the first item repeatedly
        else:
            # Not in a list, create one
            list_format.setStyle(QTextListFormat.Style.ListDisc)  # Bullet points
            list_format.setIndent(1)
            cursor.createList(list_format)

    def toggle_numbered_list(self):
        """Toggle numbered list for selected paragraphs"""
        cursor = self.notes_editor.textCursor()
        list_format = QTextListFormat()
        
        # If we already have a numbered list, remove it
        if cursor.currentList():
            # We're already in a list, so remove it
            current_list = cursor.currentList()
            for i in range(current_list.count()):
                current_list.removeItem(0)  # Remove the first item repeatedly
        else:
            # Not in a list, create one
            list_format.setStyle(QTextListFormat.Style.ListDecimal)  # Numbered list
            list_format.setIndent(1)
            cursor.createList(list_format)
            
    def set_alignment(self, alignment):
        """Set text alignment for selected paragraphs"""
        self.notes_editor.setAlignment(alignment)

    def insert_graph_image(self):
        """Insert current graph as image directly from the graph widget"""
        try:
            # Access the graph widget from the main window
            if hasattr(self.main_window, 'graph_widget') and self.main_window.graph_widget:
                # Store the current tab index to return to it later
                current_tab_index = -1
                graph_tab_index = -1
                
                # Find the graphs tab dynamically
                if hasattr(self.main_window, 'stacked_widget'):
                    current_tab_index = self.main_window.stacked_widget.currentIndex()
                    if hasattr(self.main_window, 'graphs_tab'):
                        graph_tab_index = self.main_window.stacked_widget.indexOf(self.main_window.graphs_tab)
                    else:
                        # Fallback to typical index
                        for i in range(self.main_window.stacked_widget.count()):
                            if i == 6:  # Graph tab is typically index 6
                                graph_tab_index = i
                                break
                
                # Temporarily switch to graph tab to ensure it's fully rendered
                if graph_tab_index != -1 and current_tab_index != graph_tab_index:
                    self.main_window.stacked_widget.setCurrentIndex(graph_tab_index)
                    # Let the UI update
                    QApplication.processEvents()
                
                # Now trigger a full graph update
                if hasattr(self.main_window, 'update_graph'):
                    self.main_window.update_graph()
                    # Give the UI time to fully process and render
                    QApplication.processEvents()
                    self.main_window.graph_widget.update()
                    QApplication.processEvents()
                
                # Take a direct screenshot of the graph widget
                graph_widget = self.main_window.graph_widget
                
                # Ensure any overlays or highlights are properly rendered
                graph_widget.update()
                QApplication.processEvents()  # Process any pending UI events
                
                # Use the basic grab method which is more stable
                pixmap = graph_widget.grab()
                
                # Switch back to the original tab if needed
                if current_tab_index != -1 and current_tab_index != graph_tab_index:
                    self.main_window.stacked_widget.setCurrentIndex(current_tab_index)
                    QApplication.processEvents()
                
                # Resize to 800px width while maintaining aspect ratio
                if pixmap.width() > 800:
                    pixmap = pixmap.scaledToWidth(800, Qt.TransformationMode.SmoothTransformation)
                
                # Insert the captured image
                self.insert_image_from_pixmap(pixmap)
                
                # Log success
                if hasattr(self.main_window, 'logger'):
                    self.main_window.logger.log("Inserted graph image into notes", "INFO")
            else:
                # No graph widget available
                QMessageBox.information(self.notes_editor, 
                                      "Insert Graph", 
                                      "No graph found. Please make sure you have a graph displayed in the Graphs tab.")
                
        except Exception as e:
            # Log the error
            if hasattr(self.main_window, 'logger'):
                self.main_window.logger.log(f"Error inserting graph image: {str(e)}", "ERROR")
            
            # Fallback to generic file insertion
            self.insert_formula()

    def insert_video_image(self):
        """Insert an image from the active camera tab"""
        try:
            # Check if we have an active camera controller
            if hasattr(self.main_window, 'camera_controller') and self.main_window.camera_controller:
                camera_controller = self.main_window.camera_controller
                
                # Check if camera is connected
                if not camera_controller.is_connected:
                    # Show error message
                    QMessageBox.information(self.notes_editor, 
                                        "Insert Camera Image", 
                                        "No active camera found. Please make sure the camera is connected in the Camera tab.")
                    return
                
                # Get the raw camera frame from the controller instead of using the displayed image
                # This avoids capturing any overlay indicators like the recording symbol
                pixmap = None
                
                # Try to get the current frame directly from the camera_controller
                if hasattr(camera_controller, 'current_frame') and camera_controller.current_frame is not None:
                    # Use the stored clean frame
                    pixmap = camera_controller.current_frame.copy()
                elif hasattr(camera_controller, 'camera_thread') and camera_controller.camera_thread:
                    # Try to get a new frame from the camera thread
                    if hasattr(camera_controller.camera_thread, 'get_current_frame'):
                        frame = camera_controller.camera_thread.get_current_frame()
                        if frame is not None:
                            # Convert OpenCV frame to QPixmap if needed
                            try:
                                # Import required libraries
                                import cv2
                                import numpy as np
                                
                                # Check if it's a numpy array (OpenCV image)
                                if isinstance(frame, np.ndarray):
                                    # Convert OpenCV BGR to RGB for Qt
                                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                                    
                                    # Convert to QImage
                                    height, width, channels = frame_rgb.shape
                                    bytes_per_line = channels * width
                                    q_image = QImage(frame_rgb.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
                                    
                                    # Convert to QPixmap
                                    pixmap = QPixmap.fromImage(q_image)
                            except ImportError:
                                # If numpy or cv2 aren't available, we'll just use the fallback method
                                pass
                
                # If we couldn't get a raw frame, fall back to the displayed image
                if pixmap is None or pixmap.isNull():
                    # Get the camera display widget as fallback
                    camera_label = getattr(self.main_window, 'camera_label', None)
                    if camera_label and camera_label.pixmap():
                        pixmap = camera_label.pixmap().copy()
                    else:
                        self.main_window.logger.log("Cannot capture camera image: No camera display available", "WARN")
                        QMessageBox.information(self.notes_editor, 
                                            "Insert Camera Image", 
                                            "Could not capture camera image. Please make sure the camera is connected and working properly.")
                        return
                
                # Resize the image if it's too large (max 800px wide)
                if pixmap.width() > 800:
                    pixmap = pixmap.scaledToWidth(800, Qt.TransformationMode.SmoothTransformation)
                
                # Get the destination directory for images
                dest_dir = self.get_images_directory()
                if not dest_dir:
                    self.main_window.logger.log("Cannot save camera image: No images directory available", "WARN")
                    # Still insert the image as base64 if we can't save it
                    cursor = self.notes_editor.textCursor()
                    image = pixmap.toImage()
                    format = QTextImageFormat()
                    format.setWidth(pixmap.width())
                    format.setHeight(pixmap.height())
                    format.setName(f"data:image/png;base64,{self.image_to_base64(image)}")
                    cursor.insertImage(format)
                    return
                
                # Create a unique filename with timestamp
                file_name = f"camera_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.png"
                dest_path = os.path.join(dest_dir, file_name)
                
                # Save the pixmap
                if pixmap.save(dest_path, "PNG"):
                    self.main_window.logger.log(f"Saved camera image to {dest_path}", "INFO")
                    
                    # Create relative path
                    rel_path = os.path.join("images", file_name).replace('\\', '/')
                    
                    # Insert with tracking attributes - use relative path for src since we have baseUrl set
                    cursor = self.notes_editor.textCursor()
                    cursor.insertHtml(f'<img src="{rel_path}" alt="Camera Image" class="evo-image" data-rel-path="{rel_path}" width="{pixmap.width()}" height="{pixmap.height()}">')
                    return
            
            # If we got here, something went wrong
            QMessageBox.information(self.notes_editor, 
                                  "Insert Camera Image", 
                                  "Could not capture camera image. Please make sure the camera is connected and working properly.")
            
        except Exception as e:
            # Log the error
            self.main_window.logger.log(f"Error inserting camera image: {str(e)}", "ERROR")
            
            # Fallback to generic file insertion
            self.insert_formula()

    def clear_formatting(self):
        """Clear all formatting from selected text"""
        cursor = self.notes_editor.textCursor()
        format = QTextCharFormat()
        font = QFont("Segoe UI", 14)
        format.setFont(font)
        format.setForeground(QColor(COLORS.TEXT_PRIMARY))
        format.setBackground(QColor(COLORS.BG_CARD))
        cursor.mergeCharFormat(format)
        self.notes_editor.mergeCurrentCharFormat(format)
        
    def get_images_directory(self):
        """Get the path to the images directory for the current project/run
        
        Returns:
            str: Path to the images directory or None if no project is active
        """
        project_controller = getattr(self.main_window, 'project_controller', None)
        dest_dir = None
        
        if project_controller and hasattr(project_controller, 'current_project'):
            base_dir = self.main_window.project_base_dir.text()
            project_dir = os.path.join(base_dir, project_controller.current_project)
            
            # If we have a test series
            if hasattr(project_controller, 'current_test_series') and project_controller.current_test_series:
                series_dir = os.path.join(project_dir, project_controller.current_test_series)
                
                # If we have a run
                if hasattr(project_controller, 'current_run') and project_controller.current_run:
                    run_dir = os.path.join(series_dir, project_controller.current_run)
                    dest_dir = os.path.join(run_dir, "images")
                else:
                    # Save to series directory
                    dest_dir = os.path.join(series_dir, "images")
            else:
                # Save to project directory
                dest_dir = os.path.join(project_dir, "images")
                
            # Create images directory if it doesn't exist
            if dest_dir:
                os.makedirs(dest_dir, exist_ok=True)
                
        return dest_dir
        
    def insert_formula(self):
        """Insert an image into the notes"""
        # Open a file dialog to select an image
        file_path, _ = QFileDialog.getOpenFileName(
            self.main_window,
            "Select Image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        
        if file_path:
            self.insert_image_from_file(file_path)
            
    def insert_image_from_file(self, file_path):
        """Insert an image from a file into the notes
        
        Args:
            file_path: Path to the image file
        """
        if not os.path.exists(file_path):
            return
            
        # Load the image
        pixmap = QPixmap(file_path)
        if pixmap.isNull():
            return
            
        # Scale the image if it's too large (max 800px wide)
        if pixmap.width() > 800:
            pixmap = pixmap.scaledToWidth(800, Qt.TransformationMode.SmoothTransformation)
            
        # Get the destination directory
        dest_dir = self.get_images_directory()
        if not dest_dir:
            # If no project is active, just insert the image directly as base64
            cursor = self.notes_editor.textCursor()
            image = pixmap.toImage()
            format = QTextImageFormat()
            format.setWidth(pixmap.width())
            format.setHeight(pixmap.height())
            format.setName(f"data:image/png;base64,{self.image_to_base64(image)}")
            cursor.insertImage(format)
            return
            
        # Copy the image to the destination directory
        file_name = os.path.basename(file_path)
        dest_path = os.path.join(dest_dir, file_name)
        
        # Copy the file, overwriting if it exists
        try:
            # Use shutil.copy2 to preserve metadata
            shutil.copy2(file_path, dest_path)
            self.main_window.logger.log(f"Copied image to {dest_path}", "DEBUG")
        except Exception as e:
            self.main_window.logger.log(f"Error copying image: {str(e)}", "ERROR")
            return
            
        # Create relative path for the image
        rel_path = os.path.join("images", file_name).replace('\\', '/')
        
        # Insert the image with tracking attributes - use relative path for src since we have baseUrl set
        cursor = self.notes_editor.textCursor()
        cursor.insertHtml(f'<img src="{rel_path}" alt="Inserted Image" class="evo-image" data-rel-path="{rel_path}" width="{pixmap.width()}" height="{pixmap.height()}">')
        
    def insert_image_from_pixmap(self, pixmap):
        """Insert a pixmap image into the notes
        
        Args:
            pixmap: QPixmap to insert
        """
        # For pixmaps (like screenshots), save to file first if we have an active project
        dest_dir = self.get_images_directory()
        if dest_dir:
            # Create a unique filename based on timestamp
            file_name = f"snapshot_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            dest_path = os.path.join(dest_dir, file_name)
            
            # Save the pixmap in a background thread to avoid blocking
            import threading
            pixmap_copy = pixmap.copy()
            
            def save_async(p, path):
                try:
                    p.save(path, "PNG")
                    if hasattr(self.main_window, 'logger'):
                        self.main_window.logger.log(f"Saved pixmap to {path}", "DEBUG")
                except Exception as e:
                    if hasattr(self.main_window, 'logger'):
                        self.main_window.logger.log(f"Error saving pixmap: {e}", "ERROR")

            # Start the save thread
            threading.Thread(target=save_async, args=(pixmap_copy, dest_path), daemon=True).start()
            
            # Continue with UI insertion immediately using the path we know will be created
            rel_path = os.path.join("images", file_name).replace('\\', '/')
            
            # Insert with tracking attributes - use relative path for src since we have baseUrl set
            cursor = self.notes_editor.textCursor()
            cursor.insertHtml(f'<img src="{rel_path}" alt="Inserted Image" class="evo-image" data-rel-path="{rel_path}" width="{pixmap.width()}" height="{pixmap.height()}">')
            return
        
        # Fallback to base64 if we can't save to file
        cursor = self.notes_editor.textCursor()
        image = pixmap.toImage()
        format = QTextImageFormat()
        format.setWidth(pixmap.width())
        format.setHeight(pixmap.height())
        format.setName(f"data:image/png;base64,{self.image_to_base64(image)}")
        cursor.insertImage(format)
        
    def image_to_base64(self, image):
        """Convert QImage to base64 string
        
        Args:
            image: QImage to convert
            
        Returns:
            str: Base64 encoded image data
        """
        # Convert QImage to bytes
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return data.toBase64().data().decode()
        
    def load_template(self):
        """Load the template file"""
        if not os.path.exists(self.template_path):
            self.main_window.logger.log(f"Template file not found: {self.template_path}", "ERROR")
            return None
            
        try:
            with open(self.template_path, 'r', encoding='utf-8') as f:
                template_html = f.read()
                return template_html
        except Exception as e:
            self.main_window.logger.log(f"Error loading template: {str(e)}", "ERROR")
            return None
            
    def populate_template(self, template_html):
        """Populate template with project data"""
        try:
            # Get project data
            project_controller = getattr(self.main_window, 'project_controller', None)
            if not project_controller:
                return template_html
                
            # Get current date
            current_date = datetime.datetime.now().strftime("%Y-%m-%d")
            
            # Get project data
            project_name = getattr(project_controller, 'current_project', "[Project Name]") or "[Project Name]"
            project_description = getattr(project_controller, 'project_description', "[Project Description]") or "[Project Description]"
            
            # Get test series data
            series_name = getattr(project_controller, 'current_test_series', "[Test Series Name]") or "[Test Series Name]"
            series_description = getattr(project_controller, 'test_series_description', "[Test Series Description]") or "[Test Series Description]"
            
            # Get run data
            run_name = getattr(project_controller, 'current_run', "[Run Name]") or "[Run Name]"
            run_description = getattr(project_controller, 'run_description', "[Run Description]") or "[Run Description]"
            
            # Get testers value from UI if available
            run_testers = "[Run Testers]"  # Default placeholder
            if hasattr(self.main_window, 'run_testers'):
                run_testers = self.main_window.run_testers.text().strip()
                if not run_testers:
                    run_testers = "[Run Testers]"  # Use placeholder if empty
            
            # Find run creation date and testers
            run_date = current_date
            if (hasattr(project_controller, 'current_project') and project_controller.current_project and 
                hasattr(project_controller, 'current_test_series') and project_controller.current_test_series and 
                hasattr(project_controller, 'current_run') and project_controller.current_run):
                try:
                    base_dir = self.main_window.project_base_dir.text()
                    project_dir = os.path.join(base_dir, project_controller.current_project)
                    series_dir = os.path.join(project_dir, project_controller.current_test_series)
                    run_dir = os.path.join(series_dir, project_controller.current_run)
                    
                    # Try both run.json (new format) and run_metadata.json (old format)
                    run_files = [
                        os.path.join(run_dir, "run.json"),
                        os.path.join(run_dir, "run_metadata.json")
                    ]
                    
                    for run_file in run_files:
                        if os.path.exists(run_file):
                            with open(run_file, 'r') as f:
                                run_data = json.load(f)
                                # Extract data based on format
                                if "timestamp" in run_data and "description" in run_data:
                                    # This is run_metadata.json format
                                    run_date = run_data.get("timestamp", "").split("_")[0]  # Keep the original format with "-"
                                    run_description = run_data.get("description", run_description)
                                    if "testers" in run_data and run_data["testers"]:
                                        run_testers = run_data["testers"]
                                    
                                    # If timestamp is ISO format
                                    if "T" in run_date:
                                        run_date = run_date.split("T")[0]
                                    
                                elif "date" in run_data and "description" in run_data:
                                    # This is run.json format
                                    run_date = run_data.get("date", "")  # Keep the original format with "-"
                                    run_description = run_data.get("description", run_description)
                                    if "testers" in run_data and run_data["testers"]:
                                        run_testers = run_data["testers"]
                                break
                except Exception as e:
                    self.main_window.logger.log(f"Error reading run data: {str(e)}", "WARN")
        except Exception as e:
            self.main_window.logger.log(f"Error populating template: {str(e)}", "ERROR")
            return template_html
            
        # Create a working copy of the template
        updated_html = template_html
        
        # Replace placeholders in template
        updated_html = updated_html.replace("[Project Name]", project_name)
        updated_html = updated_html.replace("[Project Date]", current_date)
        updated_html = updated_html.replace("[Project Description]", project_description)
        updated_html = updated_html.replace("[Test Series Name]", series_name)
        updated_html = updated_html.replace("[Test Series Date]", current_date)
        updated_html = updated_html.replace("[Test Series Description]", series_description)
        updated_html = updated_html.replace("[Run Name]", run_name)
        updated_html = updated_html.replace("[Run Date]", run_date)
        updated_html = updated_html.replace("[Run Description]", run_description)
        updated_html = updated_html.replace("[Run Testers]", run_testers)
        
        return updated_html

    def save_note(self, html_content=None, is_autosave=False):
        """Save the current note to the run directory
        
        Args:
            html_content: Optional HTML content to save. If None, will use the current editor content.
            is_autosave: Whether this is an automatic save or manual.
        """
        if not self.document_loaded:
            return
            
        # Get the run directory from the project controller
        project_controller = getattr(self.main_window, 'project_controller', None)
        if not project_controller:
            self.main_window.logger.log("Cannot save note - project controller not available", "WARN")
            return
            
        # Get the current run directory
        if (not hasattr(project_controller, 'current_project') or not project_controller.current_project or
            not hasattr(project_controller, 'current_test_series') or not project_controller.current_test_series or
            not hasattr(project_controller, 'current_run') or not project_controller.current_run):
            if not is_autosave:
                self.main_window.logger.log("Cannot save note - no active run", "WARN")
            return
            
        base_dir = self.main_window.project_base_dir.text()
        project_dir = os.path.join(base_dir, project_controller.current_project)
        series_dir = os.path.join(project_dir, project_controller.current_test_series)
        run_dir = os.path.join(series_dir, project_controller.current_run)
        
        # Check if run directory exists
        if not os.path.exists(run_dir):
            self.main_window.logger.log(f"Cannot save note - run directory not found: {run_dir}", "ERROR")
            return
            
        # Get note content
        if html_content is None:
            html_content = self.notes_editor.toHtml()
        
        # Calculate a hash of the content to avoid unnecessary saves
        content_hash = hashlib.md5(html_content.encode()).hexdigest()
        
        # Check if content has changed since last save
        if self.last_saved_content_hash == content_hash:
            return
            
        # Save the note to the run directory
        note_path = os.path.join(run_dir, "notes.html")
        try:
            with open(note_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            # Update the hash
            self.last_saved_content_hash = content_hash
            
            # Show feedback in status bar
            status_msg = f"Notes saved ({datetime.datetime.now().strftime('%H:%M:%S')})"
            if is_autosave:
                status_msg = f"Notes autosaved ({datetime.datetime.now().strftime('%H:%M:%S')})"
            
            if hasattr(self.main_window, 'statusBar'):
                self.main_window.statusBar().showMessage(status_msg, 3000)
            
            self.main_window.logger.log(f"Saved note to {note_path}", "DEBUG")
        except Exception as e:
            self.main_window.logger.log(f"Error saving note: {str(e)}", "ERROR")
            if not is_autosave:
                QMessageBox.warning(self.main_window, "Save Error", f"Could not save note: {str(e)}")
            
    def load_note(self):
        """Load the note from the run directory or template"""
        # Get the run directory from the project controller
        project_controller = getattr(self.main_window, 'project_controller', None)
        if not project_controller:
            self.main_window.logger.log("Cannot load note - project controller not available", "WARN")
            return
            
        # Get the current run directory
        if (not hasattr(project_controller, 'current_project') or not project_controller.current_project or
            not hasattr(project_controller, 'current_test_series') or not project_controller.current_test_series or
            not hasattr(project_controller, 'current_run') or not project_controller.current_run):
            self.main_window.logger.log("Cannot load note - no active run", "WARN")
            # Load empty template if no run is active
            template_html = self.load_template()
            if template_html:
                template_html = self.populate_template(template_html)
                self.notes_editor.setHtml(template_html)
                self.document_loaded = True
                # Calculate hash for the loaded content
                self.last_saved_content_hash = hashlib.md5(template_html.encode()).hexdigest()
            return
            
        base_dir = self.main_window.project_base_dir.text()
        project_dir = os.path.join(base_dir, project_controller.current_project)
        series_dir = os.path.join(project_dir, project_controller.current_test_series)
        run_dir = os.path.join(series_dir, project_controller.current_run)
        
        # Check if run directory exists
        if not os.path.exists(run_dir):
            self.main_window.logger.log(f"Cannot load note - run directory not found: {run_dir}", "WARN")
            return
            
        # Look for notes.html in the run directory
        note_path = os.path.join(run_dir, "notes.html")
        
        # Set the base URL for the document so it can find relative images
        self.notes_editor.document().setBaseUrl(QUrl.fromLocalFile(run_dir + os.sep))
        
        if os.path.exists(note_path):
            # Load existing note
            try:
                with open(note_path, 'r', encoding='utf-8') as f:
                    note_html = f.read()
                
                # Update absolute paths to relative if they match our run directory
                # This helps with portability if the project was moved
                note_html = self.convert_absolute_to_relative(note_html, run_dir)
                
                self.notes_editor.setHtml(note_html)
                self.main_window.logger.log(f"Loaded note from {note_path}", "DEBUG")
                
                # Calculate hash for the loaded content
                self.last_saved_content_hash = hashlib.md5(note_html.encode()).hexdigest()
                self.document_loaded = True
            except Exception as e:
                self.main_window.logger.log(f"Error loading note: {str(e)}", "ERROR")
        else:
            # Create a new note from the template
            self.main_window.logger.log(f"Note file not found, creating from template", "DEBUG")
            
            # Load the template
            template_html = self.load_template()
            if template_html:
                # Populate the template with project data
                template_html = self.populate_template(template_html)
                
                # Set the HTML content
                self.notes_editor.setHtml(template_html)
                
                # Calculate hash for the new content
                self.last_saved_content_hash = hashlib.md5(template_html.encode()).hexdigest()
                
                # Save the new note
                try:
                    with open(note_path, 'w', encoding='utf-8') as f:
                        f.write(template_html)
                    self.main_window.logger.log(f"Created new note from template: {note_path}", "DEBUG")
                except Exception as e:
                    self.main_window.logger.log(f"Error creating note from template: {str(e)}", "ERROR")
                    
                self.document_loaded = True
                
    def convert_absolute_to_relative(self, html_content, run_dir):
        """Convert absolute paths in HTML to relative paths based on run_dir"""
        # Normalize run_dir for comparison
        run_dir_norm = os.path.normpath(run_dir).replace('\\', '/')
        if not run_dir_norm.endswith('/'):
            run_dir_norm += '/'
            
        # Pattern to find src="C:/path/to/run/images/..."
        # We look for paths that start with our run directory
        def replace_path(match):
            full_path = match.group(1)
            norm_full_path = os.path.normpath(full_path).replace('\\', '/')
            if norm_full_path.startswith(run_dir_norm):
                rel_path = norm_full_path[len(run_dir_norm):]
                return f'src="{rel_path}"'
            return match.group(0)
            
        return re.sub(r'src="([^"]+)"', replace_path, html_content)
                
    def show_context_menu(self, position):
        """Show context menu for the editor"""
        menu = self.notes_editor.createStandardContextMenu()
        
        # Check if cursor is on an image
        cursor = self.notes_editor.cursorForPosition(position)
        char_format = cursor.charFormat()
        
        # QTextImageFormat is a subclass of QTextCharFormat used for images
        if char_format.isImageFormat():
            # Store the image format for the resize action
            self.selected_image = char_format.toImageFormat()
            
            # Add separator
            menu.addSeparator()
            
            # Add resize image action
            resize_action = menu.addAction("Resize Image...")
            resize_action.triggered.connect(self.resize_selected_image)
            
        # Add a separator for document-level options
        menu.addSeparator()
        
        # Add an action to clean up unused images
        cleanup_submenu = menu.addMenu("Image Management")
        
        # Option to show unused images
        show_unused_action = cleanup_submenu.addAction("Show Unused Images")
        show_unused_action.triggered.connect(lambda: self.show_unused_images_stats(self.notes_editor.toHtml()))
        
        # Option to clean up unused images with confirmation
        cleanup_action = cleanup_submenu.addAction("Clean Up Unused Images")
        cleanup_action.triggered.connect(lambda: self.cleanup_unused_images_with_confirmation(self.notes_editor.toHtml()))
        
        # Show the menu
        menu.exec(self.notes_editor.mapToGlobal(position))
        
    def resize_selected_image(self):
        """Open a dialog to resize the selected image"""
        if not self.selected_image:
            return
            
        # Get the current cursor
        current_cursor = self.notes_editor.textCursor()
        current_position = current_cursor.position()
        char_format = current_cursor.charFormat()
        
        # If we're not on an image, check if we have a stored selected image
        if not char_format.isImageFormat() and not self.selected_image:
            QMessageBox.information(self.main_window, "Resize Image", 
                                   "Please select an image first by clicking on it.")
            return
            
        # Use the appropriate image format
        if not char_format.isImageFormat():
            # Use the stored image format
            img_format = self.selected_image
        else:
            img_format = char_format.toImageFormat()
        
        # Create resize dialog
        dialog = QDialog(self.main_window)
        dialog.setWindowTitle("Resize Image")
        layout = QVBoxLayout(dialog)
        
        # Get current image size
        current_width = img_format.width()
        current_height = img_format.height()
        img_path = img_format.name()
        
        # Extract information about the original image
        actual_path = img_path
        original_path = None
        is_resized = False
        
        # Try to extract the actual path and check if this is already a resized image
        if 'src="' in img_path:
            # Extract the actual path from HTML
            match = re.search(r'src="([^"]+)"', img_path)
            if match:
                actual_path = match.group(1)
                
                # Check if this is already a resized image
                if '_resized_' in actual_path:
                    is_resized = True
                    
                    # Try to extract the original image path from data attributes
                    orig_match = re.search(r'data-original="([^"]+)"', img_path)
                    if orig_match:
                        original_path = orig_match.group(1)
        elif '_resized_' in img_path:
            is_resized = True
        elif img_path.startswith("data:image/"):
            # This is a base64 encoded image - we'll need to extract it
            data_prefix = "data:image/png;base64,"
            if img_path.startswith(data_prefix):
                # We'll need to use the current image as source since we don't have a file
                # data_embedded = True # Not used
                # For embedded images, we'll need to save them to a file first
                
                # Get the destination directory
                dest_dir = self.get_images_directory()
                if dest_dir:
                    # Generate a timestamp-based filename
                    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                    actual_path = os.path.join(dest_dir, f"embedded_{timestamp}.png")
                    
                    # Save the base64 data to a file
                    try:
                        base64_data = img_path[len(data_prefix):]
                        with open(actual_path, 'wb') as f:
                            f.write(base64.b64decode(base64_data))
                        self.main_window.logger.log(f"Saved embedded image to {actual_path}", "DEBUG")
                    except Exception as e:
                        self.main_window.logger.log(f"Error saving embedded image: {e}", "ERROR")
        
        # If it's a relative path from our custom HTML, try to construct the full path
        if not os.path.isabs(actual_path) and not actual_path.startswith("data:"):
            # Try to find the full path based on current project/run
            project_controller = getattr(self.main_window, 'project_controller', None)
            if project_controller and hasattr(project_controller, 'current_project') and project_controller.current_project:
                base_dir = self.main_window.project_base_dir.text()
                project_dir = os.path.join(base_dir, project_controller.current_project)
                
                # If we have a test series
                if hasattr(project_controller, 'current_test_series') and project_controller.current_test_series:
                    series_dir = os.path.join(project_dir, project_controller.current_test_series)
                    
                    # If we have a run
                    if hasattr(project_controller, 'current_run') and project_controller.current_run:
                        run_dir = os.path.join(series_dir, project_controller.current_run)
                        actual_path = os.path.normpath(os.path.join(run_dir, actual_path))
                        if original_path and not os.path.isabs(original_path):
                            original_path = os.path.normpath(os.path.join(run_dir, original_path))
        
        # Try to find the original image path if we have a resized image
        if is_resized and not original_path:
            # Try to derive the original path by removing the _resized_ part
            try:
                dir_path = os.path.dirname(actual_path)
                file_name = os.path.basename(actual_path)
                
                # Extract the original filename by removing the _resized_ part
                orig_name_match = re.search(r'(.+?)_resized_[0-9]+\.', file_name)
                if orig_name_match:
                    base_name = orig_name_match.group(1)
                    extension = file_name.split('.')[-1]
                    
                    # Try common filenames with this base
                    possible_names = [
                        f"{base_name}.{extension}",
                        f"{base_name}_original.{extension}"
                    ]
                    
                    for name in possible_names:
                        test_path = os.path.join(dir_path, name)
                        if os.path.exists(test_path):
                            original_path = test_path
                            break
            except Exception as e:
                self.main_window.logger.log(f"Error finding original path: {e}", "ERROR")
        
        # Use the original path if available, otherwise use current path
        source_path = original_path if original_path and os.path.exists(original_path) else actual_path
        
        # Try to get dimensions from the source image
        pixmap = None
        if os.path.exists(source_path):
            pixmap = QPixmap(source_path)
            if not pixmap.isNull() and (current_width <= 0 or current_height <= 0):
                current_width = pixmap.width()
                current_height = pixmap.height()
        
        # If still not valid, use defaults
        if current_width <= 0:
            current_width = 400
        if current_height <= 0:
            current_height = 300
        
        # Create form layout for inputs
        form_layout = QFormLayout()
        
        # Ensure dimensions are integers
        current_width = int(current_width)
        current_height = int(current_height)
        
        # Width input
        width_input = QSpinBox()
        width_input.setRange(10, 2000)
        width_input.setValue(current_width)
        width_input.setSuffix(" px")
        form_layout.addRow("Width:", width_input)
        
        # Height input
        height_input = QSpinBox()
        height_input.setRange(10, 2000)
        height_input.setValue(current_height)
        height_input.setSuffix(" px")
        form_layout.addRow("Height:", height_input)
        
        # Maintain aspect ratio
        maintain_ratio = QCheckBox("Maintain aspect ratio")
        maintain_ratio.setChecked(True)
        form_layout.addRow("", maintain_ratio)
        
        # Calculate the original aspect ratio
        original_ratio = current_width / current_height if current_height > 0 else 1.0
        
        # Flag to prevent recursive updates
        updating = False
        
        def update_height():
            nonlocal updating
            if updating or not maintain_ratio.isChecked():
                return
                
            try:
                updating = True
                new_width = width_input.value()
                new_height = int(new_width / original_ratio) if original_ratio > 0 else new_width
                height_input.setValue(new_height)
            finally:
                updating = False
                
        def update_width():
            nonlocal updating
            if updating or not maintain_ratio.isChecked():
                return
                
            try:
                updating = True
                new_height = height_input.value()
                new_width = int(new_height * original_ratio)
                width_input.setValue(new_width)
            finally:
                updating = False
        
        # Connect the value changed signals
        width_input.valueChanged.connect(update_height)
        height_input.valueChanged.connect(update_width)
        
        layout.addLayout(form_layout)
        
        # Add preset sizes
        presets_group = QGroupBox("Preset Sizes")
        presets_layout = QHBoxLayout(presets_group)
        
        # Helper function for preset buttons to avoid duplication
        def set_preset_size(preset_width):
            width_input.setValue(preset_width)  # This will trigger update_height
        
        small_btn = QPushButton("Small (200px)")
        small_btn.clicked.connect(lambda: set_preset_size(200))
        presets_layout.addWidget(small_btn)
        
        medium_btn = QPushButton("Medium (400px)")
        medium_btn.clicked.connect(lambda: set_preset_size(400))
        presets_layout.addWidget(medium_btn)
        
        large_btn = QPushButton("Large (800px)")
        large_btn.clicked.connect(lambda: set_preset_size(800))
        presets_layout.addWidget(large_btn)
        
        layout.addWidget(presets_group)
        
        # Show original image info
        info_label = QLabel(f"Source: {os.path.basename(source_path)}")
        if original_path and os.path.exists(original_path):
            info_label.setText(f"Using original image: {os.path.basename(original_path)}")
        layout.addWidget(info_label)
        
        # Add buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | 
                                      QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        # Show dialog
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                # Get new dimensions
                new_width = width_input.value()
                new_height = height_input.value()
                
                # 1. Get the full HTML of the document
                self.notes_editor.selectAll()
                html_content = self.notes_editor.toHtml()
                current_cursor_pos = current_cursor.position()
                
                # 2. Create a new pixmap with the image we want to resize - ALWAYS from the source/original
                resized_pixmap = None
                
                # Load from the source path (original if available)
                if os.path.exists(source_path):
                    resized_pixmap = QPixmap(source_path)
                    if not resized_pixmap.isNull():
                        resized_pixmap = resized_pixmap.scaled(
                            new_width, new_height, 
                            Qt.AspectRatioMode.IgnoreAspectRatio, 
                            Qt.TransformationMode.SmoothTransformation
                        )
                
                # 3. Generate a unique filename for the resized image
                timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                
                # Extract original filename parts
                file_basename = os.path.basename(source_path)
                filename_parts = file_basename.split('.')
                
                # Generate new filename
                if len(filename_parts) > 1:
                    file_ext = filename_parts[-1]
                    filename_base = '.'.join(filename_parts[:-1])
                    
                    # Remove any existing _resized_ part from the filename
                    filename_base = re.sub(r'_resized_[0-9]+', '', filename_base)
                    
                    new_filename = f"{filename_base}_resized_{timestamp}.{file_ext}"
                else:
                    new_filename = f"{file_basename}_resized_{timestamp}.png"
                
                # 4. Save the resized image to the appropriate location
                saved_path = None
                rel_path = None
                original_rel_path = None
                
                # Determine where to save the image (same place as original)
                dest_dir = self.get_images_directory()
                
                if dest_dir:
                    # Save to the destination directory
                    saved_path = os.path.join(dest_dir, new_filename)
                    rel_path = os.path.join("images", new_filename).replace('\\', '/')
                    
                    # Track the original path for future resizes
                    if original_path and os.path.exists(original_path):
                        # Check if original is in the images dir
                        images_dir = os.path.dirname(dest_dir)
                        if original_path.startswith(images_dir):
                            # Create a relative path from run dir to original
                            original_rel_path = os.path.relpath(original_path, images_dir).replace('\\', '/')
                    elif source_path != actual_path:  # If we have a separate source path
                        images_dir = os.path.dirname(dest_dir)
                        if source_path.startswith(images_dir):
                            original_rel_path = os.path.relpath(source_path, images_dir).replace('\\', '/')
                    
                    # If we don't have an original relative path yet, use the current source
                    if not original_rel_path and source_path:
                        # This will store the full path, which is better than nothing
                        original_rel_path = source_path
                    
                    # Create directory if it doesn't exist
                    os.makedirs(os.path.dirname(saved_path), exist_ok=True)
                    
                    # Save the image
                    if resized_pixmap and not resized_pixmap.isNull():
                        resized_pixmap.save(saved_path)
                    else:
                        # If we couldn't create a new pixmap, copy the original and resize it
                        if os.path.exists(source_path):
                            # Use PIL for high-quality resizing if available
                            try:
                                from PIL import Image
                                img = Image.open(source_path)
                                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                                img.save(saved_path)
                            except ImportError:
                                # Fallback to simple copy and other methods
                                shutil.copy2(source_path, saved_path)
                    
                    # If this is a resized version of an already resized image, try to clean up the old one
                    if is_resized and os.path.exists(actual_path) and os.path.exists(saved_path):
                        try:
                            # Don't delete if it's the original
                            if actual_path != source_path and '_resized_' in actual_path:
                                os.remove(actual_path)
                                self.main_window.logger.log(f"Cleaned up old resized image: {actual_path}", "DEBUG")
                        except Exception as e:
                            self.main_window.logger.log(f"Could not remove old resized image: {e}", "ERROR")
                
                # 5. Clear the editor and restore the HTML with our modified image tag
                if saved_path and os.path.exists(saved_path):
                    # Create modified HTML
                    # Find our image in the HTML by a combination of factors
                    
                    # Based on the selection position and format, find the most likely
                    # image tag that corresponds to our selection
                    cursor_idx = current_cursor_pos
                    
                    # First look for an img tag with the specific path or name
                    # escaped_path = re.escape(actual_path) # Too specific if paths changed
                    img_tags_pattern = r'<img[^>]*?>'
                    img_tags = list(re.finditer(img_tags_pattern, html_content))
                    
                    # Find the closest img tag to our cursor position
                    img_tag_match = None
                    closest_distance = float('inf')
                    
                    for match in img_tags:
                        start_pos = match.start()
                        end_pos = match.end()
                        
                        # Check if cursor is within this tag
                        if start_pos <= cursor_idx <= end_pos:
                            img_tag_match = match
                            break
                            
                        # Otherwise find the closest
                        distance = min(abs(start_pos - cursor_idx), abs(end_pos - cursor_idx))
                        if distance < closest_distance:
                            closest_distance = distance
                            img_tag_match = match
                    
                    if img_tag_match:
                        # Replace this img tag with our new one
                        # orig_tag = img_tag_match.group(0) # Not used
                        
                        # Create new tag with original path information for future resizes
                        data_original = f' data-original="{original_rel_path}"' if original_rel_path else ''
                        new_tag = f'<img src="{rel_path}" alt="Resized Image" class="evo-image" data-rel-path="{rel_path}"{data_original} width="{new_width}" height="{new_height}">'
                        
                        # Create new HTML by replacing just this tag
                        modified_html = html_content[:img_tag_match.start()] + new_tag + html_content[img_tag_match.end():]
                        
                        # Set the new HTML
                        self.notes_editor.setText("")  # Clear first
                        self.notes_editor.setHtml(modified_html)
                        
                        # Restore cursor position (approximately)
                        cursor = self.notes_editor.textCursor()
                        cursor.setPosition(min(current_cursor_pos, self.notes_editor.document().characterCount() - 1))
                        self.notes_editor.setTextCursor(cursor)
                        
                        # Success message
                        self.main_window.logger.log(f"Image resized to {new_width}x{new_height} from original source", "DEBUG")
                    else:
                        # Fallback: just insert a new image at the current cursor position
                        cursor = self.notes_editor.textCursor()
                        data_original = f' data-original="{original_rel_path}"' if original_rel_path else ''
                        html = f'<img src="{rel_path}" alt="Resized Image" class="evo-image" data-rel-path="{rel_path}"{data_original} width="{new_width}" height="{new_height}">'
                        cursor.insertHtml(html)
                else:
                    # Fallback for when we can't save a new image
                    cursor = self.notes_editor.textCursor()
                    html = f'<img src="{source_path}" width="{new_width}" height="{new_height}">'
                    cursor.insertHtml(html)
                
            except Exception as e:
                # Show error message
                QMessageBox.warning(self.main_window, "Resize Image Error", 
                                   f"Error resizing image: {str(e)}")
                self.main_window.logger.log(f"Error resizing image: {e}", "ERROR")
        
    def trigger_autosave(self):
        """Trigger autosave after a delay when content changes"""
        # Restart the timer to debounce rapid changes
        self.autosave_timer.stop()
        self.autosave_timer.start(2000)  # 2 second delay
        
    def autosave_note(self):
        """Automatically save the note content"""
        try:
            # Only autosave if document is loaded
            if not self.document_loaded:
                return
                
            # Get current content
            html_content = self.notes_editor.toHtml()
            
            # Replace absolute image paths with relative paths for storage
            # Find all images with our special class and replace their src with the relative path
            # while preserving width, height and other attributes
            html_content = re.sub(r'<img([^>]*?)class="evo-image"([^>]*?)data-rel-path="([^"]*)"([^>]*?)src="[^"]*"([^>]*?)>', 
                                r'<img\1class="evo-image"\2data-rel-path="\3"\4src="\3"\5>', 
                                html_content)
            
            # Call the regular save method with the modified HTML
            self.save_note(html_content, is_autosave=True)
            
        except Exception as e:
            self.main_window.logger.log(f"Error in autosave: {str(e)}", "ERROR")
        
    def get_unused_images_count(self, html_content):
        """Get count of unused image files in the images directory
        
        Args:
            html_content: HTML content to analyze
            
        Returns:
            int: Count of unused images
        """
        try:
            # Get the images directory
            images_dir = self.get_images_directory()
            if not images_dir or not os.path.exists(images_dir):
                return 0
                
            # Extract all used and original images
            used_images, original_images = self.extract_used_images(html_content)
            
            # Get all image files in the directory
            all_images = set()
            for filename in os.listdir(images_dir):
                if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                    all_images.add(filename)
            
            # Find unused images, but exclude original images that are referenced by resized versions
            unused_images = all_images - used_images - original_images
            
            # If we found unused images, log them for debugging
            if unused_images:
                self.main_window.logger.log(f"Detected unused images: {', '.join(unused_images)}", "DEBUG")
            
            return len(unused_images)
        except Exception as e:
            self.main_window.logger.log(f"Error counting unused images: {str(e)}", "ERROR")
            return 0
    
    def extract_used_images(self, html_content):
        """Extract all used and original images from the HTML content
        
        Args:
            html_content: HTML content to analyze
            
        Returns:
            tuple: (used_images, original_images) sets containing filenames
        """
        used_images = set()
        original_images = set()
            
        # First extract all data-rel-path values (our custom attribute)
        for match in re.finditer(r'data-rel-path="([^"]*)"', html_content):
            rel_path = match.group(1)
            # Remove 'images/' prefix if present
            if rel_path.startswith('images/'):
                rel_path = rel_path[7:]  # Remove 'images/' prefix
            used_images.add(rel_path)
        
        # Extract data-original attributes to identify original images used in resized versions
        for match in re.finditer(r'data-original="([^"]*)"', html_content):
            orig_path = match.group(1)
            # Handle both full paths and relative paths
            orig_filename = os.path.basename(orig_path)
            original_images.add(orig_filename)
            
            # Also look for original images based on naming patterns in used resized images
            for img_name in used_images:
                if '_resized_' in img_name:
                    try:
                        # Extract base name from resized image
                        base_name_match = re.search(r'(.+?)_resized_[0-9]+\.', img_name)
                        if base_name_match:
                            extension = img_name.split('.')[-1]
                            # Add potential original filename patterns
                            original_name = f"{base_name_match.group(1)}.{extension}"
                            original_images.add(original_name)
                    except:
                        pass
        
        # Also extract standard src attributes from img tags in case some don't have our custom attribute
        for match in re.finditer(r'<img[^>]*?src="([^"]*)"[^>]*?>', html_content):
            src_path = match.group(1)
            # Only process local file paths, not external URLs
            if not src_path.startswith(('http://', 'https://', 'data:', 'file:')):
                # Get the filename part of the path
                filename = os.path.basename(src_path)
                used_images.add(filename)
                
                # Check if this is a resized image, and if so, identify the potential original
                if '_resized_' in filename:
                    try:
                        # Extract base name from resized image
                        base_name_match = re.search(r'(.+?)_resized_[0-9]+\.', filename)
                        if base_name_match:
                            extension = filename.split('.')[-1]
                            # Add potential original filename patterns
                            original_name = f"{base_name_match.group(1)}.{extension}"
                            original_images.add(original_name)
                    except:
                        pass
        
        return used_images, original_images
    
    def show_unused_images_stats(self, html_content):
        """Show stats about unused images without deleting them
        
        Args:
            html_content: HTML content to analyze
        """
        try:
            # Get the images directory
            images_dir = self.get_images_directory()
            if not images_dir or not os.path.exists(images_dir):
                QMessageBox.information(self.main_window, "Image Stats", 
                                       "No images directory found.")
                return
                
            # Extract all used and original images
            used_images, original_images = self.extract_used_images(html_content)
            
            # Get all image files in the directory
            all_images = set()
            total_size = 0
            for filename in os.listdir(images_dir):
                if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                    all_images.add(filename)
                    file_path = os.path.join(images_dir, filename)
                    total_size += os.path.getsize(file_path)
            
            # Calculate unused images, excluding original files referenced by resized versions
            unused_images = all_images - used_images - original_images
            
            # Show detailed list of unused images if not too many
            unused_list = ""
            if unused_images and len(unused_images) <= 10:
                unused_list = "\n\nUnused images:\n" + "\n".join(sorted(unused_images))
            
            # Calculate unused size
            unused_size = 0
            for filename in unused_images:
                file_path = os.path.join(images_dir, filename)
                unused_size += os.path.getsize(file_path)
            
            # Show stats about original images being preserved
            original_list = ""
            if original_images and len(original_images) <= 5:
                original_list = "\n\nPreserved original images:\n" + "\n".join(sorted(original_images))
            
            # Format sizes for display
            def format_size(size_bytes):
                if size_bytes < 1024:
                    return f"{size_bytes} bytes"
                elif size_bytes < 1024 * 1024:
                    return f"{size_bytes / 1024:.1f} KB"
                else:
                    return f"{size_bytes / (1024 * 1024):.1f} MB"
            
            QMessageBox.information(self.main_window, "Image Stats", 
                                   f"Total images: {len(all_images)} ({format_size(total_size)})\n"
                                   f"Used directly: {len(used_images)} images\n"
                                   f"Preserved originals: {len(original_images)} images\n"
                                   f"Unused: {len(unused_images)} ({format_size(unused_size)}){unused_list}{original_list}")
        except Exception as e:
            self.main_window.logger.log(f"Error showing unused images stats: {str(e)}", "ERROR")
            QMessageBox.warning(self.main_window, "Image Stats", 
                               f"Error checking unused images: {str(e)}")
    
    def cleanup_unused_images_with_confirmation(self, html_content):
        """Clean up unused images with user confirmation
        
        Args:
            html_content: HTML content to analyze
        """
        try:
            # Get the images directory
            images_dir = self.get_images_directory()
            if not images_dir or not os.path.exists(images_dir):
                QMessageBox.information(self.main_window, "Clean Up Images", 
                                       "No images directory found.")
                return
                
            # Extract all used and original images
            used_images, original_images = self.extract_used_images(html_content)
            
            # Get all image files in the directory
            all_images = set()
            for filename in os.listdir(images_dir):
                if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                    all_images.add(filename)
            
            # Calculate unused images, excluding original files referenced by resized versions
            unused_images = all_images - used_images - original_images
            
            if not unused_images:
                QMessageBox.information(self.main_window, "Clean Up Images", 
                                       "No unused images found. Original images for resized versions are preserved.")
                return
            
            # List of unused images (if not too many)
            unused_list = ""
            if len(unused_images) <= 15:
                unused_list = "\n\n" + "\n".join(sorted(unused_images))
                
            # Get confirmation from user
            reply = QMessageBox.question(self.main_window, "Clean Up Images", 
                                        f"Found {len(unused_images)} unused images. Delete them?\nOriginal images for resized versions ({len(original_images)}) will be preserved.{unused_list}",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No)
            
            if reply == QMessageBox.StandardButton.Yes:
                # Remove unused images
                deleted_count = 0
                for filename in unused_images:
                    file_path = os.path.join(images_dir, filename)
                    try:
                        os.remove(file_path)
                        deleted_count += 1
                        self.main_window.logger.log(f"Removed unused image: {filename}", "DEBUG")
                    except Exception as e:
                        self.main_window.logger.log(f"Error removing unused image {filename}: {str(e)}", "ERROR")
                
                QMessageBox.information(self.main_window, "Clean Up Images", 
                                       f"Successfully deleted {deleted_count} unused images.\nOriginal images for resized versions were preserved.")
        except Exception as e:
            self.main_window.logger.log(f"Error cleaning up unused images: {str(e)}", "ERROR")
            QMessageBox.warning(self.main_window, "Clean Up Images", 
                               f"Error cleaning up unused images: {str(e)}")
    
    def cleanup_unused_images(self, html_content):
        """Clean up unused image files from the images directory
           This method is kept for backwards compatibility but doesn't
           automatically delete images anymore - it just shows a message.
           
        Args:
            html_content: HTML content to analyze
        """
        # Get count of unused images instead of deleting
        try:
            unused_count = self.get_unused_images_count(html_content)
            if unused_count > 0:
                self.main_window.logger.log(f"Found {unused_count} unused images. Use context menu to clean up.", "INFO")
        except Exception as e:
            self.main_window.logger.log(f"Error checking unused images: {str(e)}", "ERROR") 