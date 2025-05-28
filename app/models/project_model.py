"""
Project Model

Represents a project and its properties.
"""

import os
import json
import datetime


class ProjectModel:
    """Model for a project"""
    
    def __init__(self, name="", description="", base_dir="", created_date=None):
        """
        Initialize a project model
        
        Args:
            name: Project name
            description: Project description
            base_dir: Base directory for the project
            created_date: Date when the project was created
        """
        self.name = name
        self.description = description
        self.base_dir = base_dir
        self.created_date = created_date if created_date else datetime.datetime.now()
        self.test_series = []
        self.current_series = None
        
    def add_test_series(self, series):
        """
        Add a test series to the project
        
        Args:
            series: TestSeries instance
        """
        self.test_series.append(series)
        
    def get_series_by_name(self, name):
        """
        Get a test series by name
        
        Args:
            name: Name of the test series
            
        Returns:
            TestSeries instance or None if not found
        """
        for series in self.test_series:
            if series.name == name:
                return series
        return None
    
    def to_dict(self):
        """
        Convert the project to a dictionary for serialization
        
        Returns:
            Dictionary representation of the project
        """
        return {
            "name": self.name,
            "description": self.description,
            "base_dir": self.base_dir,
            "created_date": self.created_date.isoformat(),
            "test_series": [series.to_dict() for series in self.test_series]
        }
    
    @classmethod
    def from_dict(cls, data):
        """
        Create a project from a dictionary
        
        Args:
            data: Dictionary with project properties
        
        Returns:
            A ProjectModel instance
        """
        project = cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            base_dir=data.get("base_dir", ""),
            created_date=datetime.datetime.fromisoformat(data.get("created_date", datetime.datetime.now().isoformat()))
        )
        
        # Add test series
        for series_data in data.get("test_series", []):
            project.add_test_series(TestSeries.from_dict(series_data))
            
        return project
    
    def save(self):
        """
        Save the project to a file
        
        Returns:
            True if successful, False otherwise
        """
        if not self.base_dir or not self.name:
            return False
            
        # Create project directory
        project_dir = os.path.join(self.base_dir, self.name)
        os.makedirs(project_dir, exist_ok=True)
        
        # Save project metadata
        metadata_file = os.path.join(project_dir, "project.json")
        with open(metadata_file, "w") as f:
            json.dump(self.to_dict(), f, indent=4)
            
        return True
    
    @classmethod
    def load(cls, project_dir):
        """
        Load a project from a directory
        
        Args:
            project_dir: Directory containing the project
            
        Returns:
            A ProjectModel instance or None if not found
        """
        metadata_file = os.path.join(project_dir, "project.json")
        if not os.path.exists(metadata_file):
            return None
            
        try:
            with open(metadata_file, "r") as f:
                data = json.load(f)
                return cls.from_dict(data)
        except Exception as e:
            print(f"Error loading project: {e}")
            return None


class TestSeries:
    """Model for a test series"""
    
    def __init__(self, name="", description="", created_date=None):
        """
        Initialize a test series model
        
        Args:
            name: Test series name
            description: Test series description
            created_date: Date when the test series was created
        """
        self.name = name
        self.description = description
        self.created_date = created_date if created_date else datetime.datetime.now()
        self.runs = []
        
    def add_run(self, run):
        """
        Add a run to the test series
        
        Args:
            run: Run instance
        """
        self.runs.append(run)
        
    def to_dict(self):
        """
        Convert the test series to a dictionary for serialization
        
        Returns:
            Dictionary representation of the test series
        """
        return {
            "name": self.name,
            "description": self.description,
            "created_date": self.created_date.isoformat(),
            "runs": [run.to_dict() for run in self.runs]
        }
    
    @classmethod
    def from_dict(cls, data):
        """
        Create a test series from a dictionary
        
        Args:
            data: Dictionary with test series properties
        
        Returns:
            A TestSeries instance
        """
        series = cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            created_date=datetime.datetime.fromisoformat(data.get("created_date", datetime.datetime.now().isoformat()))
        )
        
        # Add runs
        for run_data in data.get("runs", []):
            series.add_run(Run.from_dict(run_data))
            
        return series


class Run:
    """Model for a test run"""
    
    def __init__(self, name="", description="", created_date=None, data_file=None, video_file=None):
        """
        Initialize a run model
        
        Args:
            name: Run name
            description: Run description
            created_date: Date when the run was created
            data_file: Path to the data file
            video_file: Path to the video file
        """
        self.name = name
        self.description = description
        self.created_date = created_date if created_date else datetime.datetime.now()
        self.data_file = data_file
        self.video_file = video_file
        self.sensor_settings = []
        self.camera_settings = {}
        
    def to_dict(self):
        """
        Convert the run to a dictionary for serialization
        
        Returns:
            Dictionary representation of the run
        """
        return {
            "name": self.name,
            "description": self.description,
            "created_date": self.created_date.isoformat(),
            "data_file": self.data_file,
            "video_file": self.video_file,
            "sensor_settings": self.sensor_settings,
            "camera_settings": self.camera_settings
        }
    
    @classmethod
    def from_dict(cls, data):
        """
        Create a run from a dictionary
        
        Args:
            data: Dictionary with run properties
        
        Returns:
            A Run instance
        """
        run = cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            created_date=datetime.datetime.fromisoformat(data.get("created_date", datetime.datetime.now().isoformat())),
            data_file=data.get("data_file"),
            video_file=data.get("video_file")
        )
        
        run.sensor_settings = data.get("sensor_settings", [])
        run.camera_settings = data.get("camera_settings", {})
        
        return run 