import os
import importlib
import inspect
import logging
from app.core.interfaces.base_interface import BaseInterface

logger = logging.getLogger(__name__)

class InterfaceRegistry:
    """
    Registry for hardware interfaces. 
    Discovers and manages both built-in and custom plugin interfaces.
    """
    _interfaces = {}  # {display_name: class}
    _initialized = False

    @classmethod
    def initialize(cls):
        """Discover and register all available interfaces."""
        if cls._initialized:
            return
        
        # 1. Register built-in interfaces from app.core.interfaces
        cls._discover_in_package("app.core.interfaces")
        
        # 2. Register custom interfaces from a 'plugins' directory
        # Use sys.executable to find directory when running as compiled .exe
        import sys
        if getattr(sys, 'frozen', False):
            # Running in a bundle (PyInstaller)
            base_dir = os.path.dirname(sys.executable)
        else:
            # Running in normal Python environment
            base_dir = os.getcwd()
            
        plugin_dir = os.path.join(base_dir, "plugins")
        
        if not os.path.exists(plugin_dir):
            try:
                os.makedirs(plugin_dir)
                # Create a README to explain how to add plugins
                with open(os.path.join(plugin_dir, "README.txt"), "w") as f:
                    f.write("Place your custom interface Python files here.\n")
                    f.write("They must inherit from app.core.interfaces.base_interface.BaseInterface\n")
            except Exception as e:
                logger.error(f"Could not create plugins directory: {e}")
        
        cls._discover_in_filesystem(plugin_dir)
        cls._initialized = True

    @classmethod
    def _discover_in_package(cls, package_name):
        """Discover interfaces in a python package."""
        try:
            package = importlib.import_module(package_name)
            pkg_path = os.path.dirname(package.__file__)
            
            for filename in os.listdir(pkg_path):
                if filename.endswith(".py") and filename != "__init__.py" and filename != "base_interface.py":
                    module_name = f"{package_name}.{filename[:-3]}"
                    cls._load_module(module_name)
        except Exception as e:
            logger.error(f"Error discovering interfaces in {package_name}: {e}")

    @classmethod
    def _discover_in_filesystem(cls, directory):
        """Discover interfaces in a specific filesystem directory."""
        if not os.path.exists(directory):
            return

        import sys
        if directory not in sys.path:
            sys.path.append(directory)

        for filename in os.listdir(directory):
            if filename.endswith(".py") and filename != "__init__.py":
                module_name = filename[:-3]
                try:
                    # Clear from sys.modules if it was already loaded (to allow hot-reloading if needed)
                    if module_name in sys.modules:
                        del sys.modules[module_name]
                    cls._load_module(module_name)
                except Exception as e:
                    logger.error(f"Error loading plugin {filename}: {e}")

    @classmethod
    def _load_module(cls, module_name):
        """Load a module and register any BaseInterface subclasses."""
        try:
            module = importlib.import_module(module_name)
            for name, obj in inspect.getmembers(module):
                # Ensure it's a class, inherits from BaseInterface, 
                # is not the base class itself, and is not abstract
                if (inspect.isclass(obj) and 
                    issubclass(obj, BaseInterface) and 
                    obj is not BaseInterface and 
                    not inspect.isabstract(obj)):
                    
                    # Register the class
                    cls.register(obj)
        except Exception as e:
            # logger.error(f"Failed to load module {module_name}: {e}")
            pass # Some modules might fail due to missing dependencies, which is expected for optional interfaces

    @classmethod
    def register(cls, interface_class):
        """Explicitly register an interface class."""
        display_name = getattr(interface_class, "DISPLAY_NAME", interface_class.__name__)
        if display_name in cls._interfaces:
            logger.warning(f"Interface '{display_name}' is already registered and will be overwritten.")
        
        cls._interfaces[display_name] = interface_class
        logger.info(f"Registered interface: {display_name}")

    @classmethod
    def get_interfaces(cls):
        """Get all registered interfaces."""
        if not cls._initialized:
            cls.initialize()
        return cls._interfaces

    @classmethod
    def get_interface_class(cls, display_name):
        """Get a specific interface class by its display name."""
        if not cls._initialized:
            cls.initialize()
        return cls._interfaces.get(display_name)
