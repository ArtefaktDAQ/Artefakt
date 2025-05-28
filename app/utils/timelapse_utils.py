import os
import cv2
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, 
                          QSpinBox, QComboBox, QFormLayout, QDialogButtonBox, QFileDialog,
                          QMessageBox, QProgressDialog, QApplication)
from PyQt6.QtCore import Qt

def show_timelapse_dialog(parent):
    """Show dialog with timelapse settings and create the video if confirmed"""
    # Create dialog
    dialog = QDialog(parent)
    dialog.setWindowTitle("Time-lapse Video Settings")
    dialog.setMinimumWidth(500)
    layout = QVBoxLayout(dialog)
    
    # Description
    description = QLabel("Create time-lapse videos from snapshots in the media folder. "
                        "The snapshots are sorted by timestamp in the filename.")
    description.setWordWrap(True)
    layout.addWidget(description)
    
    # Form layout for settings
    form = QFormLayout()
    
    # Source folder selection
    source_folder_layout = QHBoxLayout()
    source_folder = QLineEdit()
    source_folder.setPlaceholderText("Current run's media folder")
    source_folder.setReadOnly(True)
    if hasattr(parent, 'timelapse_source_folder'):
        source_folder.setText(parent.timelapse_source_folder.text())
    source_folder_layout.addWidget(source_folder, 1)
    
    browse_src_btn = QPushButton("Browse...")
    source_folder_layout.addWidget(browse_src_btn)
    form.addRow("Source Folder:", source_folder_layout)
    
    # Output file
    output_file_layout = QHBoxLayout()
    output_file = QLineEdit()
    output_file.setPlaceholderText("timelapse_output.mp4")
    if hasattr(parent, 'timelapse_output_file'):
        output_file.setText(parent.timelapse_output_file.text())
    output_file_layout.addWidget(output_file, 1)
    
    browse_output_btn = QPushButton("Browse...")
    output_file_layout.addWidget(browse_output_btn)
    form.addRow("Output File:", output_file_layout)
    
    # Video duration
    duration = QSpinBox()
    duration.setRange(1, 300)
    duration.setValue(30)
    duration.setSuffix(" seconds")
    if hasattr(parent, 'timelapse_duration'):
        duration.setValue(parent.timelapse_duration.value())
    form.addRow("Video Duration:", duration)
    
    # Frame rate
    fps = QSpinBox()
    fps.setRange(10, 60)
    fps.setValue(30)
    fps.setSuffix(" FPS")
    if hasattr(parent, 'timelapse_fps'):
        fps.setValue(parent.timelapse_fps.value())
    form.addRow("Frame Rate:", fps)
    
    # Video format
    format_combo = QComboBox()
    format_combo.addItems(["MP4 (H.264)", "AVI (MJPG)", "AVI (XVID)"])
    if hasattr(parent, 'timelapse_format'):
        format_combo.setCurrentIndex(parent.timelapse_format.currentIndex())
    form.addRow("Video Format:", format_combo)
    
    layout.addLayout(form)
    
    # Buttons
    button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    layout.addWidget(button_box)
    
    # Connect browse buttons
    def browse_source():
        folder_path = QFileDialog.getExistingDirectory(dialog, "Select Timelapse Source Folder", "")
        if folder_path:
            source_folder.setText(folder_path)
    
    def browse_output():
        file_path = QFileDialog.getSaveFileName(dialog, "Save Timelapse Video", "", "Video Files (*.mp4 *.avi)")[0]
        if file_path:
            output_file.setText(file_path)
    
    browse_src_btn.clicked.connect(browse_source)
    browse_output_btn.clicked.connect(browse_output)
    
    # Connect button box
    button_box.accepted.connect(dialog.accept)
    button_box.rejected.connect(dialog.reject)
    
    # Show dialog
    if dialog.exec() == QDialog.DialogCode.Accepted:
        # Update main UI fields with the values from the dialog
        if hasattr(parent, 'timelapse_source_folder'):
            parent.timelapse_source_folder.setText(source_folder.text())
        else:
            parent.timelapse_source_folder = QLineEdit()
            parent.timelapse_source_folder.setText(source_folder.text())
            
        if hasattr(parent, 'timelapse_output_file'):
            parent.timelapse_output_file.setText(output_file.text())
        else:
            parent.timelapse_output_file = QLineEdit()
            parent.timelapse_output_file.setText(output_file.text())
            
        if hasattr(parent, 'timelapse_duration'):
            parent.timelapse_duration.setValue(duration.value())
        else:
            parent.timelapse_duration = QSpinBox()
            parent.timelapse_duration.setValue(duration.value())
            
        if hasattr(parent, 'timelapse_fps'):
            parent.timelapse_fps.setValue(fps.value())
        else:
            parent.timelapse_fps = QSpinBox()
            parent.timelapse_fps.setValue(fps.value())
            
        if hasattr(parent, 'timelapse_format'):
            parent.timelapse_format.setCurrentIndex(format_combo.currentIndex())
        else:
            parent.timelapse_format = QComboBox()
            parent.timelapse_format.setCurrentIndex(format_combo.currentIndex())
        
        # Create the timelapse video
        create_timelapse_video(parent)
        return True
    return False

def create_timelapse_video(parent):
    """Create a timelapse video from snapshots"""
    source_folder = parent.timelapse_source_folder.text().strip()
    if not source_folder:
        # Use current run's media folder if none specified
        if hasattr(parent, 'current_run_folder') and parent.current_run_folder:
            source_folder = os.path.join(parent.current_run_folder, "media")
        else:
            QMessageBox.warning(parent, "Error", "Please select a source folder")
            return
    
    if not os.path.exists(source_folder):
        QMessageBox.warning(parent, "Error", f"Source folder does not exist: {source_folder}")
        return
    
    # Get image files from the source folder
    image_files = []
    for file in os.listdir(source_folder):
        if file.lower().endswith(('.jpg', '.jpeg', '.png')):
            image_files.append(os.path.join(source_folder, file))
    
    if not image_files:
        QMessageBox.warning(parent, "Error", "No image files found in the source folder")
        return
    
    # Sort images by filename (assuming timestamp in filename)
    image_files.sort()
    
    # Get output file
    output_file = parent.timelapse_output_file.text().strip()
    if not output_file:
        output_file = os.path.join(source_folder, "timelapse_output.mp4")
        parent.timelapse_output_file.setText(output_file)
    
    # Get video parameters
    duration = parent.timelapse_duration.value()
    fps = parent.timelapse_fps.value()
    format_index = parent.timelapse_format.currentIndex()
    
    # Calculate total frames
    total_frames = duration * fps
    
    # If we have more images than frames, we need to skip some
    if len(image_files) > total_frames:
        step = len(image_files) / total_frames
        selected_files = []
        for i in range(int(total_frames)):
            index = min(int(i * step), len(image_files) - 1)
            selected_files.append(image_files[index])
        image_files = selected_files
    
    # If we have fewer images than frames, we need to duplicate some
    elif len(image_files) < total_frames:
        # Calculate how many times each image should be repeated
        repeat = total_frames / len(image_files)
        new_files = []
        for file in image_files:
            for _ in range(int(repeat)):
                new_files.append(file)
        # Trim to exact frame count
        image_files = new_files[:int(total_frames)]
    
    # Create progress dialog
    progress = QProgressDialog("Creating timelapse video...", "Cancel", 0, len(image_files), parent)
    progress.setWindowTitle("Creating Timelapse")
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.show()
    
    try:
        # Get video format
        if format_index == 0:  # MP4 (H.264)
            fourcc = cv2.VideoWriter_fourcc(*'H264')
            if not output_file.lower().endswith('.mp4'):
                output_file += '.mp4'
        elif format_index == 1:  # AVI (MJPG)
            fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            if not output_file.lower().endswith('.avi'):
                output_file += '.avi'
        else:  # AVI (XVID)
            fourcc = cv2.VideoWriter_fourcc(*'XVID')
            if not output_file.lower().endswith('.avi'):
                output_file += '.avi'
        
        # Read first image to get dimensions
        first_image = cv2.imread(image_files[0])
        height, width, _ = first_image.shape
        
        # Create video writer
        video_writer = cv2.VideoWriter(output_file, fourcc, fps, (width, height))
        
        # Add each image to the video
        for i, image_file in enumerate(image_files):
            if progress.wasCanceled():
                break
            
            # Update progress
            progress.setValue(i)
            QApplication.processEvents()
            
            # Read image
            img = cv2.imread(image_file)
            if img is not None:
                # Add to video
                video_writer.write(img)
        
        # Release video writer
        video_writer.release()
        
        progress.setValue(len(image_files))
        
        # Show success message
        QMessageBox.information(parent, "Success", f"Timelapse video created: {output_file}")
        parent.log(f"Timelapse video created: {output_file}")

    except Exception as e:
        QMessageBox.critical(parent, "Error", f"Error creating timelapse video: {str(e)}")
        parent.log(f"Error creating timelapse video: {str(e)}")
    finally:
        progress.close() 