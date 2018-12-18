import unittest

from autotrack.core.positions import Position
from autotrack.linking.nearby_position_finder import find_closest_n_positions


class TestFindNearestFew(unittest.TestCase):

    def test_find_three_positions(self):
        system = [Position(0,0,0), Position(0,7,0), Position(0,2,0), Position(0,1,0), Position(0,3,0)]
        self.assertEquals(
            {Position(0,0,0), Position(0,2,0), Position(0,1,0)},
            find_closest_n_positions(system, Position(0, -1, 0), 3))
