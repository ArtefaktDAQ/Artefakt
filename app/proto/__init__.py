# Proto module initialization

# Import protobuf generated files
from . import daq_service_pb2
from . import daq_service_pb2_grpc

# Expose the main classes
__all__ = ['daq_service_pb2', 'daq_service_pb2_grpc']