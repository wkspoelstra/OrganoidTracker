import math
from collections import namedtuple
from typing import List, Dict, Optional, Tuple, Iterable

import numpy
from scipy import interpolate

from autotrack.core import TimePoint
from autotrack.core.particles import Particle

PathPosition = namedtuple("PathPosition", ["path", "pos", "distance"])


class Path:
    """A curve (curved line) trough the particles. This can be used to measure how far the particles are along this
     curve."""

    _x_list: List[float]
    _y_list: List[float]
    _z: Optional[int]

    _interpolation: Optional[Tuple[List[float], List[float]]]
    _offset: float

    def __init__(self):
        self._x_list = []
        self._y_list = []
        self._z = None
        self._interpolation = None
        self._offset = 0

    def add_point(self, x: float, y: float, z: float):
        """Adds a new point to the path."""
        if self._z is None:
            self._z = int(z)
        self._x_list.append(float(x))
        self._y_list.append(float(y))

        self._interpolation = None  # Invalidate previous interpolation

    def get_points_2d(self) -> Tuple[List[float], List[float]]:
        """Gets all explicitly added points (no interpolation) without the z coord."""
        return self._x_list, self._y_list

    def get_z(self) -> int:
        """Gets the Z coord of this path. Raises ValueError if the path has no points."""
        if self._z is None:
            raise ValueError("Empty path, so no z is set")
        return self._z

    def get_interpolation_2d(self) -> Tuple[List[float], List[float]]:
        """Returns a (cached) list of x and y values that are used for interpolation."""
        if self._interpolation is None:
            self._interpolation = self._calculate_interpolation()
        return self._interpolation

    def _calculate_interpolation(self) -> Tuple[List[float], List[float]]:
        if len(self._x_list) <= 1:
            # Not possible to interpolate
            return self._x_list, self._y_list

        k = 3 if len(self._x_list) > 3 else 1
        # noinspection PyTupleAssignmentBalance
        spline, _ = interpolate.splprep([self._x_list, self._y_list], k=k)
        points = interpolate.splev(numpy.arange(0, 1.01, 0.05), spline)
        x_values = points[0]
        y_values = points[1]
        return x_values, y_values

    def get_path_position_2d(self, particle: Particle) -> Optional[PathPosition]:
        """Gets the closest position on the path and the distance to the path, both in pixels. Returns None if the path
        has fewer than 2 points."""
        x_values, y_values = self.get_interpolation_2d()
        if len(x_values) < 2:
            return None

        # Find out which line segment is closest by
        min_distance_to_line_squared = None
        closest_line_index = None  # 1 for the first line, etc. Line 1 is from point 0 to point 1.
        for i in range(1, len(x_values)):
            line_x1 = x_values[i - 1]
            line_y1 = y_values[i - 1]
            line_x2 = x_values[i]
            line_y2 = y_values[i]
            distance_squared = _distance_to_line_segment_squared(line_x1, line_y1, line_x2, line_y2, particle.x, particle.y)
            if min_distance_to_line_squared is None or distance_squared < min_distance_to_line_squared:
                min_distance_to_line_squared = distance_squared
                closest_line_index = i

        # Calculate length to beginning of line segment
        combined_length_of_previous_lines = 0
        for i in range(1, closest_line_index):
            combined_length_of_previous_lines += _distance(x_values[i], y_values[i], x_values[i - 1], y_values[i - 1])

        # Calculate length on line segment
        distance_to_start_of_line_squared = _distance_squared(x_values[closest_line_index - 1], y_values[closest_line_index - 1],
                                              particle.x, particle.y)
        distance_on_line = numpy.sqrt(distance_to_start_of_line_squared - min_distance_to_line_squared)

        raw_path_position = combined_length_of_previous_lines + distance_on_line
        return PathPosition(self, raw_path_position - self._offset, math.sqrt(min_distance_to_line_squared))

    def path_position_to_xy(self, path_position: float) -> Optional[Tuple[float, float]]:
        """Given a path position, this returns the corresponding x and y coordinates. Returns None for positions outside
        of the line."""
        if len(self._x_list) < 2:
            return None
        raw_path_position = path_position + self._offset
        if raw_path_position < 0:
            return None
        line_index = 1
        x_values, y_values = self.get_interpolation_2d()

        while True:
            line_length = _distance(x_values[line_index - 1], y_values[line_index - 1],
                                    x_values[line_index], y_values[line_index])
            if raw_path_position < line_length:
                line_dx = x_values[line_index] - x_values[line_index - 1]
                line_dy = y_values[line_index] - y_values[line_index - 1]
                travelled_fraction = raw_path_position / line_length
                return x_values[line_index - 1] + line_dx * travelled_fraction, \
                       y_values[line_index - 1] + line_dy * travelled_fraction

            raw_path_position -= line_length
            line_index += 1
            if line_index >= len(x_values):
                return None

    def get_direction_marker(self) -> str:
        """Returns a char thar represents the general direction of this path: ">", "<", "^" or "v". The (0,0) coord
        is assumed to be in the top left."""
        if len(self._x_list) < 2:
            return ">"
        dx = self._x_list[-1] - self._x_list[0]
        dy = self._y_list[-1] - self._y_list[0]
        if abs(dx) > abs(dy):
            # More horizontal movement
            return "<" if dx < 0 else ">"
        else:
            # More vertical movement
            return "^" if dy < 0 else "v"

    def update_offset_for_particles(self, particles: Iterable[Particle]):
        """Updates the offset of this crypt axis such that the lowest path position that is ever returned by
        get_path_position_2d is exactly 0.
        """
        if len(self._x_list) < 2:
            return  # Too small path to update

        current_lowest_position = None
        for particle in particles:
            path_position = self.get_path_position_2d(particle).pos
            if current_lowest_position is None or path_position < current_lowest_position:
                current_lowest_position = path_position
        if current_lowest_position is not None:  # Don't do anything if the list of particles was empty
            self._offset += current_lowest_position
    
    def __eq__(self, other):
        # Paths are only equal if they are the same instence
        return other is self

    def copy(self) -> "Path":
        """Returns a copy of this path. Changes to this path will not affect the copy and vice versa."""
        copy = Path()
        for i in range(len(self._x_list)):
            copy.add_point(self._x_list[i], self._y_list[i], self._z)
        return copy

    def remove_point(self, x: float, y: float):
        """Removes the point that is (within 1 px) at the given coords. Does nothing if there is no such point."""
        for i in range(len(self._x_list)):
            if abs(self._x_list[i] - x) < 1 and abs(self._y_list[i] - y) < 1:
                del self._x_list[i]
                del self._y_list[i]
                self._interpolation = None  # Interpolation is now outdated
                return


def _distance(x1, y1, x2, y2):
    """Distance between two points."""
    return numpy.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


def _distance_squared(vx, vy, wx, wy):
    return (vx - wx)**2 + (vy - wy)**2


def _distance_to_line_segment_squared(line_x1, line_y1, line_x2, line_y2, point_x, point_y):
    """Distance from point to a line defined by the points (line_x1, line_y1) and (line_x2, line_y2)."""
    l2 = _distance_squared(line_x1, line_y1, line_x2, line_y2)
    if l2 == 0:
         return _distance_squared(point_x, point_y, line_x1, line_y1)
    t = ((point_x - line_x1) * (line_x2 - line_x1) + (point_y - line_y1) * (line_y2 - line_y1)) / l2
    t = max(0, min(1, t))
    return _distance_squared(point_x, point_y,
                             line_x1 + t * (line_x2 - line_x1), line_y1 + t * (line_y2 - line_y1))


class PathCollection:
    """Holds the paths of all time points in an experiment."""

    _paths: Dict[TimePoint, List[Path]]

    def __init__(self):
        self._paths = dict()

    def of_time_point(self, time_point: TimePoint) -> Iterable[Path]:
        """Gets the paths of the time point, or an empty collection if that time point has no paths defined."""
        paths = self._paths.get(time_point)
        if paths is None:
            return []
        return paths

    def get_path_position_2d(self, particle: Particle) -> Optional[PathPosition]:
        """Gets the position of the particle along the closest axis."""
        paths = self._paths.get(particle.time_point())
        if paths is None:
            return None

        # Find the closest path, return position on that path
        lowest_distance_position = None
        for path in paths:
            position = path.get_path_position_2d(particle)
            if lowest_distance_position is None or position.distance < lowest_distance_position.distance:
                lowest_distance_position = position
        return lowest_distance_position

    def add_path(self, time_point: TimePoint, path: Path):
        """Adds a new path to the given time point. Existing paths are left untouched."""
        existing_paths = self._paths.get(time_point)
        if existing_paths is None:
            self._paths[time_point] = [path]
        else:
            existing_paths.append(path)

    def remove_path(self, time_point: TimePoint, path: Path):
        """Removes the given path from the given time point. Does nothing if the path is not used for the given time
         point."""
        existing_paths = self._paths.get(time_point)
        if existing_paths is None:
            return
        try:
            existing_paths.remove(path)
        except ValueError:
            pass  # Ignore, path is not in list

    def exists(self, path: Path, time_point: TimePoint) -> bool:
        """Returns True if the path exists in this path collection at the given time point, False otherwise."""
        paths = self._paths.get(time_point)
        if paths is None:
            return False
        return path in paths
