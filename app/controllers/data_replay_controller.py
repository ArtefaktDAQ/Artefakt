"""
Data Replay Controller

Loads recorded CSV/event data for offline playback and exposes
time-indexed access to samples for dashboards/graphs/video sync.
"""

import os
import glob
import csv
import bisect
from PyQt6.QtCore import QObject, pyqtSignal


class DataReplayController(QObject):
    """Controller to stream recorded CSV rows in time order for replay."""

    # Emitted when a row is retrieved (optional usage by UI)
    row_emitted = pyqtSignal(dict)

    def __init__(self, main_window=None):
        super().__init__()
        self.main_window = main_window
        self.rows = []
        self.time_index = []
        self.columns = []
        self.run_dir = None
        self.start_ts = None  # absolute epoch of first row
        self.end_ts = None
        self.duration = 0.0

        # Columns in CSV that carry automation markers
        self.automation_columns = [
            "automation_trigger",
            "automation_action",
            "automation_sequence",
            "automation_image",
        ]

    # ---------- Loading ----------
    def load_run(self, run_dir=None):
        """
        Load the newest CSV for a run directory.

        Args:
            run_dir: optional explicit run directory. If None, uses the
                     current run from ProjectController (if available).
        """
        # If no explicit run_dir, use the current run only — do not silently load
        # the newest run (that mutates project selection without user intent).
        if not run_dir and self.main_window and hasattr(self.main_window, "project_controller"):
            project_controller = self.main_window.project_controller
            run_dir = project_controller.get_current_run_directory()
            if not run_dir:
                self._log(
                    "Replay load failed - no run selected. Select a run in the project tree first.",
                    "WARN",
                )
                if hasattr(self.main_window, "statusBar"):
                    try:
                        self.main_window.statusBar().showMessage(
                            "Select a run before starting replay.", 5000
                        )
                    except Exception:
                        pass
                self._reset()
                return False

        if not run_dir or not os.path.isdir(run_dir):
            self._log(f"Replay load failed - invalid run dir: {run_dir}", "ERROR")
            self._reset()
            return False

        csv_path = self._find_latest_csv(run_dir)
        if not csv_path:
            self._log(f"No CSV found in run dir: {run_dir}", "WARN")
            self._reset()
            return False

        return self.load_csv(csv_path)

    def load_csv(self, csv_path):
        """Load a specific CSV file into memory for time-indexed access."""
        if not csv_path or not os.path.exists(csv_path):
            self._log(f"Replay load failed - CSV missing: {csv_path}", "ERROR")
            self._reset()
            return False

        try:
            with open(csv_path, "r", newline="") as f:
                reader = csv.DictReader(f)
                self.columns = reader.fieldnames or []
                raw_rows = list(reader)
        except Exception as e:
            self._log(f"Replay load failed reading CSV {csv_path}: {e}", "ERROR")
            self._reset()
            return False

        if not raw_rows or "timestamp" not in self.columns:
            self._log(f"Replay load failed - no rows or timestamp column missing in {csv_path}", "ERROR")
            self._reset()
            return False

        # Detect timestamp scale (seconds vs milliseconds)
        ts_samples = []
        for row in raw_rows[:3]:
            try:
                ts_samples.append(float(row.get("timestamp", 0.0)))
            except (TypeError, ValueError):
                pass
        ts_scale = 1.0
        if ts_samples:
            ts_range = max(ts_samples) - min(ts_samples)
            if max(ts_samples) > 1e11 or ts_range > 1000.0:
                # Likely milliseconds since epoch; convert to seconds
                ts_scale = 0.001

        parsed_rows = []
        time_index = []
        first_ts = None

        for row in raw_rows:
            try:
                ts = float(row.get("timestamp", 0.0)) * ts_scale
            except (TypeError, ValueError):
                continue

            if first_ts is None:
                first_ts = ts

            rel_ts = ts - first_ts
            parsed_row = dict(row)
            parsed_row["_timestamp"] = ts
            parsed_row["_rel_time"] = rel_ts
            parsed_rows.append(parsed_row)
            time_index.append(rel_ts)

        if not parsed_rows:
            self._log(f"Replay load failed - no parsable rows in {csv_path}", "ERROR")
            self._reset()
            return False

        self.rows = parsed_rows
        self.time_index = time_index
        self.start_ts = self.rows[0]["_timestamp"]
        self.end_ts = self.rows[-1]["_timestamp"]
        self.duration = self.rows[-1]["_rel_time"]
        self.run_dir = os.path.dirname(csv_path)

        self._log(
            f"Replay loaded {len(self.rows)} rows from {os.path.basename(csv_path)} "
            f"(duration {self.duration:.2f}s)",
            "INFO",
        )
        return True

    # ---------- Access helpers ----------
    def get_time_bounds(self):
        """Return (start_relative_sec, end_relative_sec)."""
        if not self.rows:
            return (0.0, 0.0)
        return (0.0, self.duration)

    def get_row_at(self, rel_time):
        """
        Return the closest row at/after rel_time (seconds from start).
        """
        if not self.time_index:
            return None
        idx = bisect.bisect_left(self.time_index, rel_time)
        if idx >= len(self.rows):
            idx = len(self.rows) - 1
        row = self.rows[idx]
        self.row_emitted.emit(row)
        return row

    def get_slice(self, start_rel, end_rel):
        """
        Return rows within [start_rel, end_rel].
        """
        if not self.time_index:
            return []
        start_idx = bisect.bisect_left(self.time_index, start_rel)
        end_idx = bisect.bisect_right(self.time_index, end_rel)
        return self.rows[start_idx:end_idx]

    def iter_rows(self):
        """Generator over all rows in time order."""
        for row in self.rows:
            yield row

    # ---------- Private helpers ----------
    def _find_latest_csv(self, run_dir):
        csv_candidates = glob.glob(os.path.join(run_dir, "rundata_*.csv"))
        if not csv_candidates:
            csv_candidates = glob.glob(os.path.join(run_dir, "*.csv"))
        if not csv_candidates:
            return None
        return max(csv_candidates, key=os.path.getmtime)

    def _reset(self):
        self.rows = []
        self.time_index = []
        self.columns = []
        self.run_dir = None
        self.start_ts = None
        self.end_ts = None
        self.duration = 0.0

    def _log(self, message, level="INFO"):
        if self.main_window and hasattr(self.main_window, "logger"):
            self.main_window.logger.log(message, level)
        else:
            print(f"[{level}] {message}")
