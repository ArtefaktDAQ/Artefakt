#!/usr/bin/env python3
"""
Setup script for generating protobuf files from .proto definitions.
Run this script to generate the necessary gRPC files for the distributed DAQ system.
"""

import os
import subprocess
import sys

def generate_protobuf_files():
    """Generate protobuf files from .proto definitions"""
    
    # Check if protobuf file exists
    proto_file = "app/proto/daq_service.proto"
    if not os.path.exists(proto_file):
        print(f"Error: Proto file not found: {proto_file}")
        return False
    
    # Create output directory
    output_dir = "app/proto"
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        # Generate gRPC files
        cmd = [
            sys.executable, "-m", "grpc_tools.protoc",
            f"--proto_path={os.path.dirname(proto_file)}",
            f"--python_out={output_dir}",
            f"--grpc_python_out={output_dir}",
            proto_file
        ]
        
        print("Generating protobuf files...")
        print(f"Command: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("[OK] Protobuf files generated successfully!")
            print(f"Generated files in: {output_dir}")
            
            # List generated files
            generated_files = [
                "daq_service_pb2.py",
                "daq_service_pb2_grpc.py"
            ]
            
            for file in generated_files:
                file_path = os.path.join(output_dir, file)
                if os.path.exists(file_path):
                    print(f"  [OK] {file}")
                else:
                    print(f"  [ERROR] {file} (not found)")
            
            return True
        else:
            print("[ERROR] Failed to generate protobuf files")
            print(f"Error: {result.stderr}")
            return False
            
    except FileNotFoundError:
        print("[ERROR] grpc_tools.protoc not found")
        print("Please install grpcio-tools: pip install grpcio-tools")
        return False
    except Exception as e:
        print(f"[ERROR] Error generating protobuf files: {e}")
        return False

def check_dependencies():
    """Check if required dependencies are installed"""
    required_packages = {
        "grpcio": "grpc",
        "grpcio-tools": "grpc_tools",
        "protobuf": "google.protobuf"
    }
    
    missing_packages = []
    
    for package_name, import_name in required_packages.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(package_name)
    
    if missing_packages:
        print("[ERROR] Missing required packages:")
        for package in missing_packages:
            print(f"  - {package}")
        print("\nInstall missing packages with:")
        print(f"pip install {' '.join(missing_packages)}")
        return False
    
    print("[OK] All required packages are installed")
    return True

def main():
    """Main setup function"""
    print("Setting up distributed DAQ protobuf files...")
    print("=" * 50)
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    # Generate protobuf files
    if generate_protobuf_files():
        print("\nSetup completed successfully!")
        print("\nYou can now use the distributed DAQ features:")
        print("  - Start streaming as master")
        print("  - Connect to remote streams as client")
        print("  - Remote control with security features")
    else:
        print("\nSetup failed!")
        sys.exit(1)

if __name__ == "__main__":
    main() 