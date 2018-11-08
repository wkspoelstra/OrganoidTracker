from typing import Optional, Iterable, List, Tuple, Union, Set, Dict, Any

import cv2
import numpy
from matplotlib.backend_bases import KeyEvent, MouseEvent
from matplotlib.colors import Colormap
from networkx import Graph
from numpy import ndarray
from tifffile import tifffile

from autotrack import core
from autotrack.core import TimePoint, shape
from autotrack.core.experiment import Experiment
from autotrack.core.particles import Particle
from autotrack.gui import launch_window, Window, dialog
from autotrack.gui.dialog import popup_figure, prompt_int, popup_error
from autotrack.linking import particle_flow
from autotrack.visualizer import Visualizer, activate, DisplaySettings


def show(experiment: Experiment):
    """Creates a standard visualizer for an experiment."""
    window = launch_window(experiment)
    visualizer = StandardImageVisualizer(window)
    activate(visualizer)


class AbstractImageVisualizer(Visualizer):
    """A generic image visualizer."""

    MAX_Z_DISTANCE: int = 3
    DEFAULT_SIZE = (30, 500, 500)

    _time_point: TimePoint = None
    _time_point_images: ndarray = None
    _z: int
    __particles_near_visible_layer: List[Particle]
    _display_settings: DisplaySettings

    # The color map should typically not be transferred when switching to another viewer, so it is not part of the
    # display_settings property
    _color_map: Union[str, Colormap] = "gray"

    def __init__(self, window: Window, time_point_number: Optional[int] = None, z: int = 14,
                 display_settings: DisplaySettings = None):
        super().__init__(window)

        self._display_settings = DisplaySettings() if display_settings is None else display_settings
        if time_point_number is None:
            time_point_number = window.get_experiment().first_time_point_number()
        self._z = int(z)
        self._load_time_point(TimePoint(time_point_number))
        self.__particles_near_visible_layer = []

    def _load_time_point(self, time_point: TimePoint):
        """Loads the images and other data of the time point."""
        if self._display_settings.show_images:
            if self._display_settings.show_reconstruction:
                time_point_images = self.reconstruct_image(time_point, self._guess_image_size(time_point))
            else:
                time_point_images = self.load_image(time_point, self._display_settings.show_next_time_point)
        else:
            time_point_images = None

        self._time_point = time_point
        self._time_point_images = time_point_images
        self._clamp_z()

    def _export_images(self):
        if self._time_point_images is None:
            raise core.UserError("No images loaded", "Saving images failed: there are no images loaded")
        file = dialog.prompt_save_file("Save 3D file as...", [("TIF file", "*.tif")])
        if file is None:
            return
        flat_image = self._time_point_images.ravel()

        image_shape = self._time_point_images.shape
        if len(image_shape) == 3 and isinstance(self._color_map, Colormap):
            # Convert grayscale image to colored using the stored color map
            images: ndarray = self._color_map(flat_image, bytes=True)[:, 0:3]
            new_shape = (image_shape[0], image_shape[1], image_shape[2], 3)
            images = images.reshape(new_shape)
        else:
            images = cv2.convertScaleAbs(self._time_point_images, alpha=256 / self._time_point_images.max(), beta=0)
        tifffile.imsave(file, images)

    def _guess_image_size(self, time_point):
        images_for_size = self._time_point_images
        if images_for_size is None:
            images_for_size = self.load_image(time_point, show_next_time_point=False)
        size = images_for_size.shape if images_for_size is not None else self.DEFAULT_SIZE
        return size

    def draw_view(self):
        self._clear_axis()
        self.__particles_near_visible_layer.clear()
        self._draw_image()
        errors = self._draw_particles()
        self._draw_path()
        self._draw_extra()
        self._window.set_figure_title(self._get_figure_title(errors))

        self._fig.canvas.draw()

    def _draw_image(self):
        if self._time_point_images is not None:
            self._ax.imshow(self._time_point_images[self._z], cmap=self._color_map)

    def _get_figure_title(self, errors: int) -> str:
        title = "Time point " + str(self._time_point.time_point_number()) + "    (z=" + str(self._z) + ")"
        if errors != 0:
            title += " (changes: " + str(errors) + ")"
        return title

    def _must_show_other_time_points(self) -> bool:
        return True

    def _draw_extra(self):
        pass  # Subclasses can override this

    def _draw_particles(self) -> int:
        """Draws particles and links. Returns the amount of non-equal links in the image"""

        link_changes = 0

        # Next time point
        can_show_other_time_points = self._must_show_other_time_points() and self._experiment.links.has_links()
        if self._display_settings.show_next_time_point or can_show_other_time_points:
            # Only draw particles of next/previous time point if there is linking data, or if we're forced to
            try:
                link_changes += self._draw_particles_of_time_point(
                    self._experiment.get_next_time_point(self._time_point), color='red')
            except ValueError:
                pass  # There is no next time point, ignore

        # Previous time point
        if not self._display_settings.show_next_time_point and can_show_other_time_points:
            try:
                link_changes += self._draw_particles_of_time_point(
                    self._experiment.get_previous_time_point(self._time_point), color='blue')
            except ValueError:
                pass  # There is no previous time point, ignore

        # Current time point
        link_changes += self._draw_particles_of_time_point(self._time_point)

        return link_changes

    def _draw_particles_of_time_point(self, time_point: TimePoint, color: str = core.COLOR_CELL_CURRENT) -> int:
        link_changes = 0
        dt = time_point.time_point_number() - self._time_point.time_point_number()
        for particle in self._experiment.particles.of_time_point(time_point):
            dz = self._z - round(particle.z)

            # Draw the particle itself (as a square or circle, depending on its depth)
            link_changes += self._draw_particle(particle, color, dz, dt)
        return link_changes

    def _draw_particle(self, particle: Particle, color: str, dz: int, dt: int) -> int:
        if abs(dz) <= self.MAX_Z_DISTANCE:
            # Draw error marker
            graph = self._experiment.links.get_scratch_else_baseline()
            if graph is not None and particle in graph and "error" in graph.nodes[particle]:
                self._draw_error(particle, dz)

            # Make particle selectable
            self.__particles_near_visible_layer.append(particle)

        # Draw links
        link_changes = self._draw_links(particle)

        # Draw particle
        if self._display_settings.show_reconstruction:  # Showing a 3D reconstruction, so don't display a 2D one too
            shape.draw_marker_2d(particle.x, particle.y, dz, dt, self._ax, color)
        else:
            self._experiment.particles.get_shape(particle).draw2d(particle.x, particle.y, dz, dt, self._ax, color)
        return link_changes

    def _draw_error(self, particle: Particle, dz: int):
        self._ax.plot(particle.x, particle.y, 'X', color='black', markeredgecolor='white',
                      markersize=19 - abs(dz), markeredgewidth=2)

    def _draw_links(self, particle: Particle) -> int:
        """Draws links between the particles. Returns 1 if there is 1 error: the baseline links don't match the actual
        links.
        """
        links_normal = self._get_links(self._experiment.links.scratch, particle)
        links_base = self._get_links(self._experiment.links.baseline, particle)
        if particle.time_point_number() > self._time_point.time_point_number():
            # Draw links that go to past
            links_normal = [p for p in links_normal if p.time_point_number() < particle.time_point_number()]
            links_base = [p for p in links_base if p.time_point_number() < particle.time_point_number()]
        elif particle.time_point_number() < self._time_point.time_point_number():
            # Draw links that go to future
            links_normal = [p for p in links_normal if p.time_point_number() > particle.time_point_number()]
            links_base = [p for p in links_base if p.time_point_number() > particle.time_point_number()]
        else:
            # Only draw links that go multiple steps into the past or future. Links that go one step into the past
            # or future are already drawn by the above functions
            links_normal = [p for p in links_normal if abs(p.time_point_number() - particle.time_point_number()) >= 2]
            links_base = [p for p in links_base if abs(p.time_point_number() - particle.time_point_number()) >= 2]

        self._draw_given_links(particle, links_normal, line_style='dotted', line_width=3)
        self._draw_given_links(particle, links_base)

        # Check for errors
        if self._experiment.links.can_compare_links():
            if links_base != links_normal:
                return 1
        return 0

    def _draw_given_links(self, particle, links, line_style='solid', line_width=1):
        particle_dt = numpy.sign(particle.time_point_number() - self._time_point.time_point_number())
        for linked_particle in links:
            linked_particle_dt = numpy.sign(linked_particle.time_point_number() - self._time_point.time_point_number())
            # link_dt is negative when drawing to past, positive when drawing to the future and 0 when drawing from the
            # past to the future (so it is skipping this time point)
            link_dt = particle_dt + linked_particle_dt

            min_display_z = min(linked_particle.z, particle.z) - self.MAX_Z_DISTANCE
            max_display_z = max(linked_particle.z, particle.z) + self.MAX_Z_DISTANCE
            if self._z < min_display_z or self._z > max_display_z:
                continue
            if link_dt < 0:
                # Drawing to past
                if not self._display_settings.show_next_time_point:
                    self._ax.plot([particle.x, linked_particle.x], [particle.y, linked_particle.y], linestyle=line_style,
                                  color=core.COLOR_CELL_PREVIOUS, linewidth=line_width)
            elif link_dt > 0:
                # Drawing to future
                self._ax.plot([particle.x, linked_particle.x], [particle.y, linked_particle.y], linestyle=line_style,
                              color=core.COLOR_CELL_NEXT, linewidth=line_width)
            else:
                # Drawing from past to future, skipping this time point
                self._ax.plot([particle.x, linked_particle.x], [particle.y, linked_particle.y], linestyle=line_style,
                              color=core.COLOR_CELL_CURRENT, linewidth=line_width)

    def _get_links(self, network: Optional[Graph], particle: Particle) -> Iterable[Particle]:
        if network is None:
            return []
        try:
            return network[particle]
        except KeyError:
            return []

    def _draw_path(self):
        """Draws the path, which is usually the crypt axis."""
        path = self._experiment.paths.of_time_point(self._time_point)
        if path is None:
            return

        dz = abs(path.get_z() - self._z)
        marker = path.get_direction_marker()
        linewidth = 3 if dz == 0 else 1
        self._ax.plot(*path.get_interpolation_2d(), color=core.COLOR_CELL_CURRENT, linewidth=linewidth)
        self._ax.plot(*path.get_points_2d(), linewidth=0, marker=marker, markerfacecolor=core.COLOR_CELL_CURRENT,
                      markeredgecolor="black", markersize=max(7, 12 - dz))

    def _get_particle_at(self, x: Optional[int], y: Optional[int]) -> Optional[Particle]:
        """Wrapper of get_closest_particle that makes use of the fact that we can lookup all particles ourselves."""
        return self.get_closest_particle(self.__particles_near_visible_layer, x, y, None, max_distance=5)

    def get_extra_menu_options(self) -> Dict[str, Any]:
        def time_point_prompt():
            min_str = str(self._experiment.first_time_point_number())
            max_str = str(self._experiment.last_time_point_number())
            given = prompt_int("Time point", "Which time point do you want to go to? (" + min_str + "-" + max_str
                               + ", inclusive)")
            if given is None:
                return
            if not self._move_to_time(given):
                popup_error("Out of range", "Oops, time point " + str(given) + " is outside the range " + min_str + "-"
                            + max_str + ".")
        return {
            **super().get_extra_menu_options(),
            "File/Export-Export image...": self._export_images,
            "View/Toggle-Toggle showing two time points (" + DisplaySettings.KEY_SHOW_NEXT_IMAGE_ON_TOP.upper() + ")":
                self._toggle_showing_next_time_point,
            "View/Toggle-Toggle showing images (" + DisplaySettings.KEY_SHOW_IMAGES.upper() + ")":
                self._toggle_showing_images,
            "View/Toggle-Toggle showing reconstruction (" + DisplaySettings.KEY_SHOW_RECONSTRUCTION.upper() + ")":
                self._toggle_showing_reconstruction,
            "Navigate/Layer-Above layer (Up)": lambda: self._move_in_z(1),
            "Navigate/Layer-Below layer (Down)": lambda: self._move_in_z(-1),
            "Navigate/Time-Next time point (Right)": lambda: self._move_in_time(1),
            "Navigate/Time-Previous time point (Left)": lambda: self._move_in_time(-1),
            "Navigate/Time-Other time point... (/t*)": time_point_prompt
        }

    def _on_key_press(self, event: KeyEvent):
        if event.key == "up":
            self._move_in_z(1)
        elif event.key == "down":
            self._move_in_z(-1)
        elif event.key == "left":
            self._move_in_time(-1)
        elif event.key == "right":
            self._move_in_time(1)
        elif event.key == DisplaySettings.KEY_SHOW_NEXT_IMAGE_ON_TOP:
            self._toggle_showing_next_time_point()
        elif event.key == DisplaySettings.KEY_SHOW_IMAGES:
            self._toggle_showing_images()
        elif event.key == DisplaySettings.KEY_SHOW_RECONSTRUCTION:
            self._toggle_showing_reconstruction()

    def _on_command(self, command: str) -> bool:
        if len(command) > 0 and command[0] == "t":
            time_point_str = command[1:]
            try:
                new_time_point_number = int(time_point_str.strip())
                self._move_to_time(new_time_point_number)
            except ValueError:
                self.update_status("Cannot read number: " + time_point_str)
            return True
        if command == "help":
            self.update_status("/t20: Jump to time point 20 (also works for other time points)")
            return True
        return False

    def _toggle_showing_next_time_point(self):
        self._display_settings.show_next_time_point = not self._display_settings.show_next_time_point
        self.refresh_view()

    def _toggle_showing_images(self):
        self._display_settings.show_images = not self._display_settings.show_images
        self.refresh_view()

    def _toggle_showing_reconstruction(self):
        self._display_settings.show_reconstruction = not self._display_settings.show_reconstruction
        self.refresh_view()

    def _move_in_z(self, dz: int):
        old_z = self._z
        self._z += dz

        self._clamp_z()

        if self._z != old_z:
            self.draw_view()

    def _clamp_z(self):
        if self._z < 0:
            self._z = 0
        if self._time_point_images is not None and self._z >= len(self._time_point_images):
            self._z = len(self._time_point_images) - 1

    def _move_to_time(self, new_time_point_number: int) -> bool:
        try:
            self._load_time_point(TimePoint(new_time_point_number))
            self.draw_view()
            self.update_status("Moved to time point " + str(new_time_point_number) + "!")
            return True
        except ValueError:
            self.update_status("Unknown time point: " + str(new_time_point_number) + " (range is "
                               + str(self._experiment.first_time_point_number()) + " to "
                               + str(self._experiment.last_time_point_number()) + ", inclusive)")
            return False

    def _move_in_time(self, dt: int):
        self._color_map = AbstractImageVisualizer._color_map

        old_time_point_number = self._time_point.time_point_number()
        new_time_point_number = old_time_point_number + dt
        try:
            self._load_time_point(TimePoint(new_time_point_number))
            self.draw_view()
            self.update_status(self.get_default_status())
        except ValueError:
            pass

    def refresh_view(self):
        self._move_in_time(0)  # This makes the viewer reload the image


class StandardImageVisualizer(AbstractImageVisualizer):
    """Cell and image viewer

    Moving: left/right moves in time, up/down in the z-direction and type '/t30' + ENTER to jump to time point 30
    Press F to show the detected particle flow, press V to view the detected particle volume"""

    def __init__(self, window: Window, time_point_number: Optional[int] = None, z: int = 14,
                 display_settings: Optional[DisplaySettings] = None):
        super().__init__(window, time_point_number=time_point_number, z=z, display_settings=display_settings)

    def _on_mouse_click(self, event: MouseEvent):
        if event.dblclick and event.button == 1:
            particle = self._get_particle_at(event.xdata, event.ydata)
            if particle is not None:
                self.__display_cell_division_scores(particle)
        else:
            super()._on_mouse_click(event)

    def __display_cell_division_scores(self, particle):
        cell_divisions = list(self._experiment.scores.of_mother(particle))
        cell_divisions.sort(key=lambda d: d.score.total(), reverse=True)
        displayed_items = 0
        text = ""
        for scored_family in cell_divisions:
            if displayed_items >= 2:
                text += "... and " + str(len(cell_divisions) - displayed_items) + " more"
                break
            text += str(displayed_items + 1) + ". " + str(scored_family.family) + ", score: " \
                    + str(scored_family.score).replace(",", ",\n\t") + "\n"
            displayed_items += 1
        if text:
            self.update_status("Possible cell division scores:\n" + text)
        else:
            self.update_status("No cell division scores found")

    def get_extra_menu_options(self):
        return {
            **super().get_extra_menu_options(),
            "Edit/Manual-Manually change data... (C)": self._show_data_editor,
            "Edit/Automatic-Cell detection...": self._show_cell_detector,
            "View/Linking-Linking differences (D)": self._show_linking_differences,
            "View/Linking-Linking errors and warnings (E)": self._show_linking_errors,
            "View/Linking-Lineage errors and warnings (L)": self._show_lineage_errors,
            "View/Cell-Cell divisions (M)": self._show_mother_cells,
            "View/Cell-Track ends and cell deaths (/deaths)": self._show_dead_cells
        }

    def _on_key_press(self, event: KeyEvent):
        if event.key == "t":
            particle = self._get_particle_at(event.xdata, event.ydata)
            if particle is not None:
                from autotrack.visualizer.track_visualizer import TrackVisualizer
                track_visualizer = TrackVisualizer(self._window, particle)
                activate(track_visualizer)
        elif event.key == "e":
            particle = self._get_particle_at(event.xdata, event.ydata)
            self._show_linking_errors(particle)
        elif event.key == "d":
            particle = self._get_particle_at(event.xdata, event.ydata)
            self._show_linking_differences(particle)
        elif event.key == "m":
            self._show_mother_cells()
        elif event.key == "c":
            self._show_data_editor()
        elif event.key == "l":
            self._show_lineage_errors()
        elif event.key == "v":  # show volume info
            particle = self._get_particle_at(event.xdata, event.ydata)
            if particle is None:
                self.update_status("No particle at mouse position")
                return
            shape = self._experiment.particles.get_shape(particle)
            try:
                self.update_status(f"Volume of {particle} is {shape.volume():.2f} px3")
            except NotImplementedError:
                self.update_status(f"The {particle} has no volume information stored")
        elif event.key == "f":  # show flow info
            particle = self._get_particle_at(event.xdata, event.ydata)
            particles_of_time_point = self._experiment.particles.of_time_point(self._time_point)
            links = self._experiment.links.get_scratch_else_baseline()
            if particle is not None and links is not None:
                self.update_status("Flow toward previous frame: " +
                                   str(particle_flow.get_flow_to_previous(links, particles_of_time_point, particle)) +
                                   "\nFlow towards next frame: " +
                                   str(particle_flow.get_flow_to_next(links, particles_of_time_point, particle)))
        else:
            super()._on_key_press(event)

    def _show_cell_detector(self):
        if self._experiment.get_image_stack(self._time_point) is None:
            dialog.popup_error("No images", "There are no images loaded, so we cannot detect cells.")
            return
        from autotrack.visualizer.detection_visualizer import DetectionVisualizer
        activate(DetectionVisualizer(self._window, self._time_point.time_point_number(), self._z,
                                     self._display_settings))

    def _show_mother_cells(self):
        from autotrack.visualizer.cell_division_visualizer import CellDivisionVisualizer
        track_visualizer = CellDivisionVisualizer(self._window)
        activate(track_visualizer)

    def _show_linking_errors(self, particle: Optional[Particle] = None):
        from autotrack.visualizer.errors_visualizer import ErrorsVisualizer
        warnings_visualizer = ErrorsVisualizer(self._window, particle)
        activate(warnings_visualizer)

    def _show_linking_differences(self, particle: Optional[Particle] = None):
        from autotrack.visualizer.differences_visualizer import DifferencesVisualizer
        differences_visualizer = DifferencesVisualizer(self._window, particle)
        activate(differences_visualizer)

    def _show_data_editor(self):
        from autotrack.visualizer.link_and_position_editor import LinkAndPositionEditor
        editor = LinkAndPositionEditor(self._window, time_point_number=self._time_point.time_point_number(),
                                       z=self._z)
        activate(editor)

    def _show_lineage_errors(self):
        from autotrack.visualizer.lineages_visualizer import LineageErrorsVisualizer
        editor = LineageErrorsVisualizer(self._window, time_point_number=self._time_point.time_point_number(),
                                         z=self._z)
        activate(editor)

    def _on_command(self, command: str) -> bool:
        if command == "deaths":
            self._show_dead_cells()
            return True
        if command == "divisions":
            self._show_mother_cells()
            return True
        if command == "help":
            self.update_status("Available commands:\n"
                               "/deaths - views cell deaths.\n"
                               "/divisions - views cell divisions.\n"
                               "/t20 - jumps to time point 20 (also works for other time points")
            return True
        return super()._on_command(command)

    def _show_dead_cells(self):
        from autotrack.visualizer.cell_death_visualizer import CellTrackEndVisualizer
        activate(CellTrackEndVisualizer(self._window, None))


