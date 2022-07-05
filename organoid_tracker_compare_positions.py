#!/usr/bin/env python3

"""Compares two sets of positions. Used to calculate the recall and precision."""
from organoid_tracker.comparison import positions_comparison, report_json_io
from organoid_tracker.config import ConfigFile, config_type_json_file, config_type_bool
from organoid_tracker.core.resolution import ImageResolution
from organoid_tracker.imaging import io

# PARAMETERS
print("Hi! Configuration file is stored at " + ConfigFile.FILE_NAME)
config = ConfigFile("compare_positions")
_min_time_point = int(config.get_or_default("min_time_point", str(1), store_in_defaults=True))
_max_time_point = int(config.get_or_default("max_time_point", str(9999), store_in_defaults=True))
_ground_truth_file = config.get_or_prompt("ground_truth_file", "In what file are the positions of the ground truth stored?")
_automatic_file = config.get_or_prompt("automatic_file", "In what file are the positions of the experiment stored?")
_max_distance_um = float(config.get_or_default("max_distance_um", str(5)))
_rejection_distance_um = float(config.get_or_default("rejection_distance_um", str(1_000_000)))
_output_file = config.get_or_default("output_file", "positions_comparison.json", type=config_type_json_file)
_show_graphs = config.get_or_default("show_graphs", "True", type=config_type_bool)
config.save_and_exit_if_changed()
# END OF PARAMETERS

print("Starting...")
ground_truth = io.load_data_file(_ground_truth_file, _min_time_point, _max_time_point)
automatic_data = io.load_data_file(_automatic_file, _min_time_point, _max_time_point)

print("Comparing...")
report = positions_comparison.compare_positions(ground_truth, automatic_data, max_distance_um=_max_distance_um,
                                                rejection_distance_um=_rejection_distance_um)
if _output_file:
    report_json_io.save_report(report, _output_file)
print(report)
if _show_graphs:
    report.calculate_time_detection_statistics().debug_plot()
    report.calculate_z_detection_statistics().debug_plot()

print("Done!")
