# Read CSV Interface Guide

The **Read CSV** interface periodically polls a CSV file on disk. This is useful for data from external loggers or simulations.

## Workflow

1.  **Preview**: Use `get_csv_preview(file_path="...")` to see the headers and data format.
2.  **Add Sensor**:
    -   `interface_name`: `"Read CSV"`
    -   `params`:
        -   `file`: Full path to the file.
        -   `column`: Header name or zero-based index.
        -   `extract_rule`: (Optional) Regex to extract a number from a complex string.

## Polling

The interface checks the file modification time and re-reads the last row(s) based on the `poll_interval` set for the interface.
