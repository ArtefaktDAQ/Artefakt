from PyQt6.QtCore import Qt, QParallelAnimationGroup, QPropertyAnimation, pyqtSlot
from PyQt6.QtWidgets import QWidget, QToolButton, QScrollArea, QVBoxLayout, QFrame, QSizePolicy

class CollapsibleBox(QWidget):
    """A custom collapsible box widget for PyQt6.
    
    This widget provides a header that can be clicked to expand or collapse a content area.
    """
    
    def __init__(self, title="", parent=None):
        """Initialize the collapsible box.
        
        Args:
            title (str): The title to display in the header
            parent (QWidget): The parent widget
        """
        super(CollapsibleBox, self).__init__(parent)
        
        # Create the toggle button with an arrow
        self.toggle_button = QToolButton(
            text=title, checkable=True, checked=False
        )
        self.toggle_button.setStyleSheet("""
            QToolButton { 
                border: none; 
                text-align: left;
                padding-left: 5px;
                font-weight: bold;
            }
        """)
        self.toggle_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.toggle_button.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle_button.clicked.connect(self.on_pressed)
        
        # Create the animation group for smooth expanding/collapsing
        self.toggle_animation = QParallelAnimationGroup(self)
        self.toggle_animation.finished.connect(self.animation_finished)
        
        # Create the content area that will expand/collapse
        self.content_area = QScrollArea(
            maximumHeight=0, minimumHeight=0
        )
        self.content_area.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.content_area.setFrameShape(QFrame.Shape.NoFrame)
        self.content_area.setWidgetResizable(True)
        self.content_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Set up the layout
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.content_area)
        
        # Set up the animations
        self.toggle_animation.addAnimation(
            QPropertyAnimation(self, b"minimumHeight")
        )
        self.toggle_animation.addAnimation(
            QPropertyAnimation(self, b"maximumHeight")
        )
        self.toggle_animation.addAnimation(
            QPropertyAnimation(self.content_area, b"maximumHeight")
        )
        
        # Track expanded state separately from button checked state
        self.is_expanded = False
    
    @pyqtSlot()
    def on_pressed(self):
        """Handle the toggle button press event."""
        self.is_expanded = not self.is_expanded
        
        # Set arrow direction based on expanded state (not button state)
        self.toggle_button.setArrowType(
            Qt.ArrowType.DownArrow if self.is_expanded else Qt.ArrowType.RightArrow
        )
        
        # Set animation direction based on expanded state
        self.toggle_animation.setDirection(
            QParallelAnimationGroup.Direction.Forward
            if self.is_expanded
            else QParallelAnimationGroup.Direction.Backward
        )
        
        self.toggle_animation.start()
    
    @pyqtSlot()
    def animation_finished(self):
        """Handle animation finished event to ensure button state matches expanded state."""
        # Ensure button checked state matches our expanded state
        if self.toggle_button.isChecked() != self.is_expanded:
            self.toggle_button.setChecked(self.is_expanded)
    
    def setContentLayout(self, layout):
        """Set the layout of the content area.
        
        Args:
            layout: The layout to set
        """
        # Create a container widget to hold the layout
        content_widget = QWidget()
        content_widget.setLayout(layout)
        
        # Set the widget on the scroll area
        self.content_area.setWidget(content_widget)
        
        # Calculate collapsed and expanded heights
        collapsed_height = self.sizeHint().height() - self.content_area.maximumHeight()
        
        # Get the content height with some extra room
        content_height = layout.sizeHint().height() + 15  # Add extra padding for all content
        
        # Add extra padding for nested collapsible boxes
        extra_padding = 15  # Base padding
        
        # Count nested collapsible boxes
        nested_collapsibles = 0
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), CollapsibleBox):
                nested_collapsibles += 1
        
        # Add more padding based on number of nested boxes
        if nested_collapsibles > 0:
            extra_padding += nested_collapsibles * 25
        
        expanded_height = collapsed_height + content_height + extra_padding
        
        # Configure the animations with the calculated heights
        for i in range(self.toggle_animation.animationCount() - 1):  # All except content area
            animation = self.toggle_animation.animationAt(i)
            animation.setDuration(150)  # Even faster for better responsiveness
            animation.setStartValue(collapsed_height)
            animation.setEndValue(expanded_height)
        
        # Configure the content area animation separately
        content_animation = self.toggle_animation.animationAt(
            self.toggle_animation.animationCount() - 1
        )
        content_animation.setDuration(150)
        content_animation.setStartValue(0)
        content_animation.setEndValue(content_height + extra_padding)
    
    def setExpanded(self, expanded):
        """Set the expanded state of the box.
        
        Args:
            expanded (bool): True to expand, False to collapse
        """
        if expanded != self.is_expanded:
            self.is_expanded = expanded
            self.toggle_button.setChecked(expanded)
            self.toggle_button.setArrowType(
                Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
            )
            
            # Run animation in appropriate direction
            self.toggle_animation.setDirection(
                QParallelAnimationGroup.Direction.Forward
                if expanded
                else QParallelAnimationGroup.Direction.Backward
            )
            self.toggle_animation.start() 