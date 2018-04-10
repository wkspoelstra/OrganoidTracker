"""Images and positions of particles (biological cells in our case)"""
from operator import itemgetter
from typing import List, Iterable, Optional, Dict, Set, Any, ItemsView

from networkx import Graph
from numpy import ndarray

from imaging import image_cache

COLOR_CELL_NEXT = "red"
COLOR_CELL_PREVIOUS = "blue"
COLOR_CELL_CURRENT = "lime"
KEY_SHOW_NEXT_IMAGE_ON_TOP = "n"


class Particle:

    x: float
    y: float
    z: float
    _time_point_number: Optional[int]

    def __init__(self, x: float, y: float, z: float):
        self.x = x
        self.y = y
        self.z = z
        self._time_point_number = None

    def distance_squared(self, other: "Particle", z_factor: float = 5) -> float:
        """Gets the squared distance. Working with squared distances instead of normal ones gives a much better
        performance, as the expensive sqrt(..) function can be avoided."""
        return (self.x - other.x) ** 2 + (self.y - other.y) ** 2 + ((self.z - other.z) * z_factor) ** 2

    def time_point_number(self):
        return self._time_point_number

    def with_time_point_number(self, time_point_number: int):
        if self._time_point_number is not None:
            raise ValueError("time_point_number was already set")
        self._time_point_number = int(time_point_number)
        return self

    def __repr__(self):
        string = "Particle(" + ("%.2f" % self.x) + ", " + ("%.2f" % self.y) + ", " + ("%.0f" % self.z) + ")"
        if self._time_point_number is not None:
            string += ".with_time_point_number(" + str(self._time_point_number) + ")"
        return string

    def __str__(self):
        string = "cell at (" + ("%.2f" % self.x) + ", " + ("%.2f" % self.y) + ", " + ("%.0f" % self.z) + ")"
        if self._time_point_number is not None:
            string += " at time point " + str(self._time_point_number)
        return string

    def __hash__(self):
        return hash(int(self.x)) ^ hash(int(self.y)) ^ hash(int(self.z)) ^ hash(int(self._time_point_number))

    def __eq__(self, other):
        return isinstance(other, self.__class__) \
               and abs(self.x - other.x) < 0.00001 and abs(self.x - other.x) < 0.00001 and abs(self.z - other.z) < 0.00001 \
               and self._time_point_number == other._time_point_number


class Score:
    """Represents a score, calculated from the individual elements. Usage:

        score = Score()
        score.foo = 4
        score.bar = 3.1
        # Results in score.total() == 7.1
    """

    def __init__(self, **kwargs):
        self.__dict__["scores"] = kwargs.copy()

    def __setattr__(self, key, value):
        self.__dict__["scores"][key] = value

    def __getattr__(self, item):
        return self.__dict__["scores"][item]

    def __delattr__(self, item):
        del self.__dict__["scores"][item]

    def total(self):
        score = 0
        for name, value in self.__dict__["scores"].items():
            score += value
        return score

    def keys(self) -> List[str]:
        keylist = list(self.__dict__["scores"].keys())
        keylist.sort()
        return keylist

    def get(self, key: str) -> float:
        """Gets the specified score, or 0 if it does not exist"""
        try:
            return self.__dict__["scores"][key]
        except KeyError:
            return 0.0

    def dict(self) -> Dict[str, float]:
        """Gets the underlying score dictionary"""
        return self.__dict__["scores"]

    def __str__(self):
        return str(self.total()) + " (based on " + str(self.__dict__["scores"]) + ")"

    def __repr__(self):
        return "Score(**" + repr(self.__dict__["scores"]) + ")"


class Family:
    """A mother cell with two daughter cells."""
    mother: Particle
    daughters: Set[Particle]

    def __init__(self, mother: Particle, daughter1: Particle, daughter2: Particle):
        self.mother = mother
        self.daughters = {daughter1, daughter2}

    @staticmethod
    def _pos_str(particle: Particle) -> str:
        return "(" + ("%.2f" % particle.x) + ", " + ("%.2f" % particle.y) + ", " + ("%.0f" % particle.z) + ")"

    def __str__(self):
        return self._pos_str(self.mother) + " " + str(self.mother.time_point_number()) + "---> " \
               + " and ".join([self._pos_str(daughter) for daughter in self.daughters])

    def __repr__(self):
        return "Family(" + repr(self.mother) + ", " +  ", ".join([repr(daughter) for daughter in self.daughters]) + ")"

    def __hash__(self):
        hash_code = hash(self.mother)
        for daughter in self.daughters:
            hash_code += hash(daughter)
        return hash_code

    def __eq__(self, other):
        return isinstance(other, self.__class__) \
            and other.mother == self.mother \
            and other.daughters == self.daughters


class ScoredFamily:
    """A family with a score attached. The higher the score, the higher the chance that this family actually exists."""
    family: Family
    score: Score

    def __init__(self, family: Family, score: Score):
        self.family = family
        self.score = score

    def __repr__(self):
        return "<" + str(self.family) + " scored " + str(self.score) + ">"


class TimePoint:
    """A single point in time."""

    _time_point_number: int
    _particles: List[Particle]
    _mother_scores: Dict[Family, Score]
    _image_loader: Any

    def __init__(self, time_point_number: int):
        self._time_point_number = time_point_number
        self._particles = []
        self._mother_scores = dict()
        self._image_loader = None

    def time_point_number(self) -> int:
        return self._time_point_number

    def particles(self) -> List[Particle]:
        return self._particles

    def mother_score(self, family: Family, score: Optional[Score] = None) -> Score:
        """Gets or sets the mother score of the given particle. Returns None if the cell has no score set. Raises
        KeyError if no score has been set for this particle."""
        if family.mother.time_point_number() != self._time_point_number:
            raise KeyError("Family belongs to another time point")
        if score is not None:
            self._mother_scores[family] = score
            return score
        return self._mother_scores[family]

    def add_particles(self, particles: Iterable[Particle]) -> None:
        """Adds all particles in the list to this time_point. Throws ValueError if the particles were already assigned to
        a time_point."""
        for particle in particles:
            particle.with_time_point_number(self._time_point_number)
            self._particles.append(particle)

    def set_image_loader(self, loader):
        """Sets the image loader. The image loader must ba a function with no args, that returns a numpy
        multidimensional array. Each element in the array is another array that forms an image.
        """
        self._image_loader = loader

    def load_images(self, allow_cache=True) -> ndarray:
        if allow_cache:
            images = image_cache.get_from_cache(self._time_point_number)
            if images is not None:
                return images

        # Cache miss
        images = self._load_images_uncached()
        if allow_cache:
            image_cache.add_to_cache(self._time_point_number, images)
        return images

    def _load_images_uncached(self):
        image_loader = self._image_loader
        if self._image_loader is None:
            return None
        return image_loader()

    def mother_scores(self, mother: Optional[Particle] = None) -> Iterable[ScoredFamily]:
        """Gets all mother scores of either all putative mothers, or just the given mother (if any)."""
        for family, score in self._mother_scores.items():
            if mother is not None:
                if family.mother != mother:
                    continue
            yield ScoredFamily(family, score)


class Experiment:
    """A complete experiment, with many stacks of images collected over time. This class records the images, particle
     positions and particle trajectories."""

    _time_points: Dict[str, TimePoint]
    _particle_links: Optional[Graph]
    _particle_links_baseline: Optional[Graph] # Links that are assumed to be correct
    _first_time_point_number: Optional[int]
    _last_time_point_number: Optional[int]

    def __init__(self):
        self._time_points = {}
        self._particle_links = None
        self._particle_links_baseline = None
        self._last_time_point_number = None
        self._first_time_point_number = None

    def add_particles(self, time_point_number: int, raw_particles) -> None:
        """Adds particles to a time_point."""
        particles = []
        for raw_particle in raw_particles:
            particles.append(Particle(raw_particle[0], raw_particle[1], raw_particle[2]))
        time_point = self._get_or_add_time_point(time_point_number)
        time_point.add_particles(particles)

    def add_particle(self, x: float, y: float, z: float, time_point_number: int):
        """Adds a single particle to the experiment, creating the time point if it does not exist yet."""
        time_point = self._get_or_add_time_point(time_point_number)
        time_point.add_particles([Particle(x, y, z)])

    def add_image_loader(self, time_point_number: int, image_loader) -> None:
        time_point = self._get_or_add_time_point(time_point_number)
        time_point.set_image_loader(image_loader)

    def get_time_point(self, time_point_number: int) -> TimePoint:
        """Gets the time_point with the given number. Throws KeyError if no such time_point exists."""
        return self._time_points[str(time_point_number)]

    def _get_or_add_time_point(self, time_point_number: int) -> TimePoint:
        try:
            return self._time_points[str(time_point_number)]
        except KeyError:
            time_point = TimePoint(time_point_number)
            self._time_points[str(time_point_number)] = time_point
            self._update_time_point_statistics(time_point_number)
            return time_point

    def _update_time_point_statistics(self, new_time_point_number: int):
        if self._first_time_point_number is None or self._first_time_point_number > new_time_point_number:
            self._first_time_point_number = new_time_point_number
        if self._last_time_point_number is None or self._last_time_point_number < new_time_point_number:
            self._last_time_point_number = new_time_point_number

    def first_time_point_number(self):
        if self._first_time_point_number is None:
            raise ValueError("No time_points exist")
        return self._first_time_point_number

    def last_time_point_number(self):
        if self._last_time_point_number is None:
            raise ValueError("No time_points exist")
        return self._last_time_point_number

    def get_previous_time_point(self, time_point: TimePoint) -> TimePoint:
        """Gets the time_point directly before the given time_point, or KeyError if the given time_point is the first time_point."""
        return self.get_time_point(time_point.time_point_number() - 1)

    def get_next_time_point(self, time_point: TimePoint) -> TimePoint:
        """Gets the time_point directly after the given time_point, or KeyError if the given time_point is the last time_point."""
        return self.get_time_point(time_point.time_point_number() + 1)

    def particle_links_scratch(self, network: Optional[Graph] = None) -> Optional[Graph]:
        """Gets or sets the particle linking results. It is not possible to replace exising results."""
        if network is not None:
            self._particle_links = network
        return self._particle_links

    def particle_links(self, network: Optional[Graph] = None) -> Optional[Graph]:
        """Gets or sets a particle linking result **that is known to be correct**."""
        if network is not None:
            self._particle_links_baseline = network
        return self._particle_links_baseline

    def time_points(self) -> Iterable[TimePoint]:
        first_number = self.first_time_point_number()
        last_number = self.last_time_point_number()
        current_number = first_number
        while current_number <= last_number:
            yield self.get_time_point(current_number)
            current_number += 1


def get_closest_particle(particles: Iterable[Particle], search_position: Particle,
                         ignore_z: bool = False, max_distance: int = 100000) -> Optional[Particle]:
    """Gets the particle closest ot the given position."""
    closest_particle = None
    closest_distance_squared = max_distance ** 2

    for particle in particles:
        if ignore_z:
            search_position.z = particle.z # Make search ignore z
        distance = particle.distance_squared(search_position)
        if distance < closest_distance_squared:
            closest_distance_squared = distance
            closest_particle = particle

    return closest_particle


def get_closest_n_particles(particles: Iterable[Particle], search_position: Particle, amount: int,
                            max_distance: int = 100000) -> Set[Particle]:
    max_distance_squared = max_distance ** 2
    closest_particles = []

    for particle in particles:
        distance_squared = particle.distance_squared(search_position)
        if distance_squared > max_distance_squared:
            continue
        if len(closest_particles) < amount or closest_particles[-1][0] > distance_squared:
            # Found closer particle
            closest_particles.append((distance_squared, particle))
            closest_particles.sort(key=itemgetter(0))
            if len(closest_particles) > amount:
                # List too long, remove furthest
                del closest_particles[-1]

    return_value = set()
    for distance_squared, particle in closest_particles:
        return_value.add(particle)
    return return_value