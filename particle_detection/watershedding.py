import random
from typing import Tuple, Collection

import cv2
import mahotas
import matplotlib.cm
import matplotlib.colors
import numpy
from numpy import ndarray
from scipy.ndimage import morphology

from core import Particle


def _create_colormap():
    many_colors = []
    many_colors += map(matplotlib.cm.get_cmap("prism"), range(256))
    many_colors += map(matplotlib.cm.get_cmap("cool"), range(256))
    many_colors += map(matplotlib.cm.get_cmap("summer"), range(256))
    many_colors += map(matplotlib.cm.get_cmap("spring"), range(256))
    many_colors += map(matplotlib.cm.get_cmap("autumn"), range(256))
    many_colors += map(matplotlib.cm.get_cmap("PiYG"), range(256))
    many_colors += map(matplotlib.cm.get_cmap("Spectral"), range(256))
    random.shuffle(many_colors)
    many_colors[0] = (0., 0., 0., 1.)  # We want a black background
    return matplotlib.colors.ListedColormap(many_colors, name="random", N=2000)


COLOR_MAP = _create_colormap()


def distance_transform(threshold: ndarray, out: ndarray, sampling: Tuple[float, float, float]):
    """Performs a 3D distance transform: all white pixels in the threshold are replaced by intensities representing the
    distance from black pixels.
    threshold: binary uint8 image
    out: float64 image of same size
    sampling: resolution of the image in arbitrary units in the z,y,x axis.
    """
    # noinspection PyTypeChecker
    morphology.distance_transform_edt(threshold, sampling=sampling, distances=out)


def watershed_maxima(threshold: ndarray, intensities: ndarray, minimal_size: Tuple[int, int, int]
                     ) -> Tuple[ndarray, ndarray]:
    """Performs a watershed transformation on the intensity image, using its regional maxima as seeds and flowing
    towards lower intensities."""
    kernel = numpy.ones(minimal_size)
    maxima = mahotas.morph.regmax(intensities, Bc=kernel)
    spots, n_spots = mahotas.label(maxima, Bc=kernel)
    print("Found " + str(n_spots) + " particles")
    surface = (intensities.max() - intensities)
    return watershed_labels(threshold, surface, spots)


def create_labels(particles: Collection[Particle], output: ndarray):
    """Creates a label image using the given labels. This image can be used for a watershed transform, for example.
    particles: list of particles, must have x/y/z in range of the output image
    output: integer image, which will contain the labels"""
    i = 1
    for particle in particles:
        try:
            output[int(particle.z), int(particle.y), int(particle.x)] = i
            i += 1
        except IndexError:
            raise ValueError("The images do not match the cells: " + str(particle) + " is outside the image of size " +
                             str((output.shape[2], output.shape[1], output.shape[0])) + ".")


def watershed_labels(threshold: ndarray, surface: ndarray, label_image: ndarray) -> Tuple[ndarray, ndarray]:
    """Performs a watershed on the given surface, using the labels in label_image. Pixels that fall outside the given
    threshold are removed afterwards."""
    # label_image: 0 is background, others are labels.
    areas, lines = mahotas.cwatershed(surface, label_image, return_lines=True)
    areas[threshold == 0] = 0
    areas[:, 0, 0] = areas.max()
    return areas, lines


def remove_big_labels(labeled: ndarray):
    """Removes all labels 10x larger than the average."""
    sizes = mahotas.labeled.labeled_size(labeled)
    too_big = numpy.where(sizes > numpy.median(sizes) * 10)
    labeled[:] = mahotas.labeled.remove_regions(labeled, too_big, inplace=False)


def smooth(image_stack: ndarray, distance_transform_smooth_size: int):
    temp = numpy.empty_like(image_stack[0])
    for z in range(image_stack.shape[0]):
        cv2.GaussianBlur(image_stack[z], (distance_transform_smooth_size, distance_transform_smooth_size), 0, dst=temp)
        image_stack[z] = temp