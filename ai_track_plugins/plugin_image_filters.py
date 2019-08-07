from typing import Dict, Any

import numpy
from numpy.core.multiarray import ndarray

from ai_track.core.image_loader import ImageFilter
from ai_track.gui import dialog
from ai_track.gui.window import Window
from ai_track.image_loading.noise_suppressing_filter import NoiseSuppressingFilter


def get_menu_items(window: Window) -> Dict[str, Any]:
    return {
        "View//Image filters-Image filters//Increase brightness...": lambda: _enhance_brightness(window),
        "View//Image filters-Image filters//Threshold (suppress noise)...": lambda: _suppress_noise(window),
        "View//Image filters-Image filters//Remove all filters": lambda: _remove_filters(window)
    }


def _suppress_noise(window: Window):
    min_value = dialog.prompt_float("Threshold", "What is the threshold for suppressing noise? (0% - 100%)"
                                    "\n\nA value of 25 removes all pixels with a value less than 25% of the maximum"
                                    " brightness in the image.", minimum=0, maximum=100, default=8)
    if min_value is None:
        return

    window.get_experiment().images.filters.append(NoiseSuppressingFilter(min_value / 100))
    window.get_gui_experiment().redraw_image_and_data()


def _enhance_brightness(window: Window):
    multiplier = dialog.prompt_float("Multiplier", "How many times would you like to increase the brightness of the"
                                     " image?", minimum=1, maximum=100)
    if multiplier is None:
        return

    window.get_experiment().images.filters.append(_IncreaseBrightnessFilter(multiplier))
    window.get_gui_experiment().redraw_image_and_data()


def _remove_filters(window: Window):
    filters = window.get_experiment().images.filters
    filters_len = len(filters)
    filters.clear()

    if filters_len == 1:
        window.set_status("Removed 1 filter.")
    else:
        window.set_status(f"Removed {filters_len} filters.")

    window.get_gui_experiment().redraw_image_and_data()


class _IncreaseBrightnessFilter(ImageFilter):
    _factor: float

    def __init__(self, factor: float):
        if factor < 0:
            raise ValueError("factor may not be negative, but was " + str(factor))
        self._factor = factor

    def filter(self, image_8bit: ndarray):
        if int(self._factor) == self._factor:
            # Easy, apply cheap integer multiplication - costs almost no RAM

            # First get rid of things that will overflow
            new_max = int(255 / self._factor)
            image_8bit[image_8bit > new_max] = new_max

            # Then do integer multiplication
            image_8bit *= int(self._factor)
            return

        # Copying required
        scaled = image_8bit * self._factor
        scaled[scaled > 255] = 255  # Prevent overflow
        image_8bit[...] = scaled.astype(numpy.uint8)

    def copy(self):
        return _IncreaseBrightnessFilter(self._factor)

    def get_name(self) -> str:
        return "Increase brightness"
