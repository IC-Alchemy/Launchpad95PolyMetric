"""Polymetric sequencer: each parameter lane (gate, pitch, octave, velocity, length)
loops at its own cycle length, creating interlocking phrases from one clip."""

import re
import time

from _Framework.ButtonElement import ButtonElement

from .ScaleComponent import MUSICAL_MODES, KEY_NAMES
from .StepSequencerComponent import QUANTIZATION_NAMES
from .StepSequencerComponent2 import StepSequencerComponent2, MelodicNoteEditorComponent


try:
	xrange
except NameError:
	xrange = range


POLY_MODE_GATE = 0
POLY_MODE_LENGTH = 1
POLY_MODE_OCTAVE = 2
POLY_MODE_VELOCITY = 3
POLY_MODE_PITCH = 4
POLY_MODE_LANE_LENGTH = 20  # utility page for choosing a lane's cycle length

LANE_GATE = "gate"
LANE_LENGTH = "length"
LANE_OCTAVE = "octave"
LANE_VELOCITY = "velocity"
LANE_PITCH = "pitch"

LANE_ORDER = [LANE_GATE, LANE_LENGTH, LANE_OCTAVE, LANE_VELOCITY, LANE_PITCH]
LANE_MODE = {
	LANE_GATE: POLY_MODE_GATE,
	LANE_LENGTH: POLY_MODE_LENGTH,
	LANE_OCTAVE: POLY_MODE_OCTAVE,
	LANE_VELOCITY: POLY_MODE_VELOCITY,
	LANE_PITCH: POLY_MODE_PITCH
}
MODE_LANE = dict((value, key) for key, value in LANE_MODE.items())

# Lane cycle lengths are persisted as a clip-name token: [poly:g1,p2,o3,v4,l5]
METADATA_RE = re.compile(r"\s*\[poly:g(\d+),p(\d+),o(\d+),v(\d+),l(\d+)\]\s*")
MAX_POLY_STEPS = 128


class PolymetricNoteEditorComponent(MelodicNoteEditorComponent):
	"""Edit one clip as independent looping parameter lanes."""

	def __init__(self, step_sequencer, matrix, side_buttons, control_surface):
		# Side button 3 ("random" in the melodic editor) is repurposed as gate page.
		self._gate_button = None
		self._last_side_press_times = {}
		super(PolymetricNoteEditorComponent, self).__init__(step_sequencer, matrix, side_buttons, control_surface)
		self._mode = POLY_MODE_PITCH
		self._selected_length_lane = LANE_GATE
		self._set_default_lane_lengths()
		self.set_gate_button(self._side_buttons[3])

	def disconnect(self):
		self._gate_button = None
		super(PolymetricNoteEditorComponent, self).disconnect()

	def _init_data(self):
		super(PolymetricNoteEditorComponent, self)._init_data()
		self._notes_gates = [0] * MAX_POLY_STEPS
		self._set_default_lane_lengths()

	def _set_default_lane_lengths(self):
		# Short equal defaults; replaced by clip-loop length or stored metadata when a clip opens.
		self._lane_lengths = {
			LANE_GATE: 8,
			LANE_PITCH: 8,
			LANE_OCTAVE: 8,
			LANE_VELOCITY: 8,
			LANE_LENGTH: 8
		}

	def set_clip(self, clip):
		# Rebuild lane state from stored metadata when the clip changes.
		if self._clip != clip:
			self._init_data()
			self._clip = clip
			self._parse_metadata()

	def set_mode(self, mode):
		# Track which lane was active so long-press knows whose length to edit.
		if mode != POLY_MODE_LANE_LENGTH:
			self._selected_length_lane = MODE_LANE.get(mode, self._selected_length_lane)
		self._mode = mode
		self._force_update = True
		self.update()

	def set_key_indexes(self, key_indexes):
		# Reharmonize on scale change: normalise pitches, then rewrite clip.
		if self._key_indexes != key_indexes:
			self._key_indexes = key_indexes
			self._normalize_pitch_indexes()
			self._update_clip_notes()

	def _normalize_pitch_indexes(self):
		# Gate may be on before a pitch is chosen; ensure every step has a valid pitch degree.
		for step in xrange(MAX_POLY_STEPS):
			has_pitch = False
			for note_index in xrange(7):
				if self._notes_pitches[step * 7 + note_index] == 1:
					has_pitch = True
			if not has_pitch:
				self._notes_pitches[step * 7] = 0

	def _default_length_from_clip(self):
		# Default lane length = clip loop length in quantized steps.
		if self._clip == None:
			return 8
		try:
			steps = int((self._clip.loop_end - self._clip.loop_start) / self._quantization)
		except (RuntimeError, ZeroDivisionError):
			steps = 8
		return max(1, min(MAX_POLY_STEPS, steps))

	def _parse_metadata(self):
		# Restore lane lengths from clip-name token; fall back to clip-loop length.
		default_length = self._default_length_from_clip()
		for lane in LANE_ORDER:
			self._lane_lengths[lane] = default_length

		if self._clip == None:
			return
		name = self._clip.name or ""
		match = METADATA_RE.search(name)
		if match == None:
			return
		values = {
			LANE_GATE: int(match.group(1)),
			LANE_PITCH: int(match.group(2)),
			LANE_OCTAVE: int(match.group(3)),
			LANE_VELOCITY: int(match.group(4)),
			LANE_LENGTH: int(match.group(5))
		}
		for lane, value in values.items():
			self._lane_lengths[lane] = max(1, min(MAX_POLY_STEPS, value))

	def _write_metadata(self):
		# Write lane lengths into clip-name token so they survive reload.
		if self._clip == None:
			return
		try:
			# Strip old token first so repeated edits don't pile up.
			name = self._clip.name or ""
			base_name = METADATA_RE.sub("", name).strip()
			token = "[poly:g%d,p%d,o%d,v%d,l%d]" % (
				self._lane_lengths[LANE_GATE],
				self._lane_lengths[LANE_PITCH],
				self._lane_lengths[LANE_OCTAVE],
				self._lane_lengths[LANE_VELOCITY],
				self._lane_lengths[LANE_LENGTH]
			)
			self._clip.name = ("%s %s" % (base_name, token)).strip()
		except RuntimeError:
			pass

	def _parse_notes(self):
		# First note at a step defines gate, velocity, octave, length.
		# Additional notes become chord tones when polyphonic.
		for index in xrange(len(self._notes_pitches)):
			self._notes_pitches[index] = 0
		for index in xrange(MAX_POLY_STEPS):
			self._notes_gates[index] = 0
			self._notes_velocities[index] = 4
			self._notes_octaves[index] = 2
			self._notes_lengths[index] = 3

		first_note = [True] * MAX_POLY_STEPS
		for note in self._note_cache:
			note_position = note[1]
			note_key = note[0]
			note_length = note[2]
			note_velocity = note[3]
			note_muted = note[4]
			step = int(note_position / self._quantization)
			if note_muted or step < 0 or step >= MAX_POLY_STEPS:
				continue

			if first_note[step]:
				first_note[step] = False
				self._notes_gates[step] = 1

				for value_index in xrange(7):
					if note_velocity >= self._velocity_map[value_index]:
						self._notes_velocities[step] = value_index

				for value_index in xrange(7):
					if note_length * 4 >= self._length_map[value_index] * self._quantization:
						self._notes_lengths[step] = value_index

				self._store_pitch_for_note(step, note_key, None)
			elif not self._is_monophonic:
				self._store_pitch_for_note(step, note_key, self._notes_octaves[step])

		self._normalize_pitch_indexes()
		self._update_matrix()

	def _store_pitch_for_note(self, step, note_key, preferred_octave):
		found = False
		for note_index in xrange(min(7, len(self._key_indexes))):
			octave_range = [preferred_octave] if preferred_octave != None else xrange(7)
			for octave in octave_range:
				if note_key == self._key_indexes[note_index] + 12 * (octave - 2) and not found:
					found = True
					self._notes_octaves[step] = octave
					self._notes_pitches[step * 7 + note_index] = 1
		if not found:
			self._notes_pitches[step * 7] = 0

	def _lane_value_step(self, step, lane):
		# Core polymetric rule: each lane advances modulo its own cycle length.
		return step % self._lane_lengths[lane]

	def _pitch_indexes_for_step(self, step):
		pitch_step = self._lane_value_step(step, LANE_PITCH)
		pitch_indexes = []
		for note_index in xrange(7):
			if self._notes_pitches[pitch_step * 7 + note_index] == 1:
				pitch_indexes.append(note_index)
		return pitch_indexes

	def _prune_polyphonic_pitches(self):
		for step in xrange(MAX_POLY_STEPS):
			kept_pitch = False
			for note_index in xrange(7):
				index = step * 7 + note_index
				if self._notes_pitches[index] == 1:
					if kept_pitch:
						self._notes_pitches[index] = 0
					else:
						kept_pitch = True

	def _update_clip_notes(self):
		# Resolve each lane independently through its modulo cycle, emit as plain MIDI notes.
		if self._clip != None and self._step_sequencer.is_enabled():
			note_cache = []
			try:
				start = int(self._clip.loop_start / self._quantization)
				end = int(self._clip.loop_end / self._quantization)
			except (RuntimeError, ZeroDivisionError):
				start = 0
				end = MAX_POLY_STEPS
			start = max(0, min(MAX_POLY_STEPS, start))
			end = max(start, min(MAX_POLY_STEPS, end))

			for step in xrange(start, end):
				gate_step = self._lane_value_step(step, LANE_GATE)
				if self._notes_gates[gate_step] != 1:
					continue

				octave_step = self._lane_value_step(step, LANE_OCTAVE)
				velocity_step = self._lane_value_step(step, LANE_VELOCITY)
				length_step = self._lane_value_step(step, LANE_LENGTH)
				pitch_indexes = self._pitch_indexes_for_step(step)

				time_value = step * self._quantization
				velocity = self._velocity_map[self._notes_velocities[velocity_step]]
				length = self._length_map[self._notes_lengths[length_step]] * self._quantization / 4.0
				for pitch_index in pitch_indexes:
					pitch = self._key_indexes[pitch_index] + 12 * (self._notes_octaves[octave_step] - 2)
					if pitch >= 0 and pitch < 128 and velocity >= 0 and velocity < 128 and length >= 0:
						note_cache.append([pitch, time_value, length, velocity, False])

			self._write_metadata()
			self._clip.select_all_notes()
			self._clip.replace_selected_notes(tuple(note_cache))

	def _active_lane(self):
		return MODE_LANE.get(self._mode, self._selected_length_lane)

	def _active_lane_length(self):
		return self._lane_lengths[self._selected_length_lane]

	def _playhead_step_for_lane(self, lane):
		if self._playhead == None:
			return None
		# Playhead follows the active lane's own cycle, not the clip page.
		return int(self._playhead / self.quantization) % self._lane_lengths[lane]

	def _update_matrix(self):
		if self.is_enabled() and self._matrix != None:
			for x in xrange(8):
				for y in xrange(8):
					self._grid_back_buffer[x][y] = 0

			if self._clip != None:
				if self._mode == POLY_MODE_LANE_LENGTH:
					self._render_lane_length()
				else:
					self._render_parameter_page()
			else:
				for x in xrange(8):
					for y in xrange(8):
						self._grid_back_buffer[x][y] = "DefaultButton.Disabled"

			for x in xrange(8):
				for y in xrange(8):
					if self._grid_back_buffer[x][y] != self._grid_buffer[x][y] or self._force_update:
						self._grid_buffer[x][y] = self._grid_back_buffer[x][y]
						self._matrix.get_button(x, y).set_light(self._grid_buffer[x][y])

			self._force_update = False

	def _render_parameter_page(self):
		lane = self._active_lane()
		playhead_step = self._playhead_step_for_lane(lane)
		for x in xrange(8):
			step = x + 8 * self._page
			gate_on = self._notes_gates[self._lane_value_step(step, LANE_GATE)] == 1
			has_note = gate_on
			# Columns repeat when a lane is shorter than the visible page — that's the polymetric visual.
			for y in xrange(7):
				if self._mode == POLY_MODE_PITCH:
					value_step = self._lane_value_step(step, LANE_PITCH)
					color = "PolymetricSequencer.NoteOn" if self._notes_pitches[value_step * 7 + 6 - y] == 1 else "PolymetricSequencer.NoteOff"
				elif self._mode == POLY_MODE_OCTAVE:
					value_step = self._lane_value_step(step, LANE_OCTAVE)
					color = self._value_color(self._notes_octaves[value_step] == 6 - y, has_note)
				elif self._mode == POLY_MODE_VELOCITY:
					value_step = self._lane_value_step(step, LANE_VELOCITY)
					color = self._value_color(self._notes_velocities[value_step] >= 6 - y, has_note)
				elif self._mode == POLY_MODE_LENGTH:
					value_step = self._lane_value_step(step, LANE_LENGTH)
					color = self._value_color(self._notes_lengths[value_step] >= 6 - y, has_note)
				else:
					value_step = self._lane_value_step(step, LANE_GATE)
					if self._notes_gates[value_step] == 1 and y == 3:
						color = "PolymetricSequencer.NoteOn"
					elif self._notes_gates[value_step] == 1:
						color = "PolymetricSequencer.NoteDim"
					else:
						color = "PolymetricSequencer.NoteOff"
				self._grid_back_buffer[x][y] = color

			if playhead_step != None and playhead_step == (step % self._lane_lengths[lane]):
				self._grid_back_buffer[x][7] = "PolymetricSequencer.Playhead1"
			else:
				self._grid_back_buffer[x][7] = "PolymetricSequencer.PageMarker"

	def _value_color(self, enabled, has_note):
		if enabled:
			if has_note:
				return "PolymetricSequencer.FaderOn"
			return "PolymetricSequencer.FaderDim"
		return "PolymetricSequencer.FaderOff"

	def _render_lane_length(self):
		# Full 8x8 grid as a length picker (0–63 per page), so long cycles fit on one screen.
		selected_length = self._active_lane_length()
		base_step = self._page * 64
		for y in xrange(8):
			for x in xrange(8):
				step = base_step + y * 8 + x
				if step >= MAX_POLY_STEPS:
					self._grid_back_buffer[x][y] = "PolymetricSequencer.Blank"
				elif step == selected_length - 1:
					self._grid_back_buffer[x][y] = "PolymetricSequencer.LengthSelected"
				elif step < selected_length:
					self._grid_back_buffer[x][y] = "PolymetricSequencer.LengthOn"
				else:
					self._grid_back_buffer[x][y] = "PolymetricSequencer.LengthOff"

	def _length_step_from_grid(self, x, y):
		return self._page * 64 + y * 8 + x

	def _parameter_step_from_grid(self, x):
		return x + 8 * self._page

	def _matrix_value(self, value, x, y, is_momentary):
		if self.is_enabled() and self._matrix != None:
			if self._clip == None:
				self._step_sequencer.create_clip()
			elif ((value != 0) or (not is_momentary)):
				# Parameter pages use columns as steps; length edit uses the full grid.
				step = self._length_step_from_grid(x, y) if self._mode == POLY_MODE_LANE_LENGTH else self._parameter_step_from_grid(x)
				if step < 0 or step >= MAX_POLY_STEPS:
					return
				if self._mode == POLY_MODE_LANE_LENGTH:
					self._lane_lengths[self._selected_length_lane] = step + 1
					self._write_metadata()
				elif y < 7:
					self._handle_parameter_press(step, y)
				self._force_update = True
				self._update_matrix()
				self._update_clip_notes()

	def _handle_parameter_press(self, step, y):
		if self._mode == POLY_MODE_PITCH:
			value_step = self._lane_value_step(step, LANE_PITCH)
			pitch_index = value_step * 7 + 6 - y
			if self._is_monophonic:
				selected = self._notes_pitches[pitch_index] == 1
				for yy in xrange(7):
					self._notes_pitches[value_step * 7 + yy] = 0
				if not selected:
					self._notes_pitches[pitch_index] = 1
					# Auto-gate: choosing a pitch creates a step so it's immediately audible.
					self._notes_gates[self._lane_value_step(step, LANE_GATE)] = 1
			else:
				self._notes_pitches[pitch_index] = 0 if self._notes_pitches[pitch_index] == 1 else 1
				if self._notes_pitches[pitch_index] == 1:
					self._notes_gates[self._lane_value_step(step, LANE_GATE)] = 1
		elif self._mode == POLY_MODE_OCTAVE:
			self._notes_octaves[self._lane_value_step(step, LANE_OCTAVE)] = 6 - y
		elif self._mode == POLY_MODE_VELOCITY:
			self._notes_velocities[self._lane_value_step(step, LANE_VELOCITY)] = 6 - y
		elif self._mode == POLY_MODE_LENGTH:
			self._notes_lengths[self._lane_value_step(step, LANE_LENGTH)] = 6 - y
		elif self._mode == POLY_MODE_GATE:
			value_step = self._lane_value_step(step, LANE_GATE)
			self._notes_gates[value_step] = 0 if self._notes_gates[value_step] == 1 else 1

	def _button_released_as_length_edit(self, sender, lane):
		# Hold > 0.4s on a lane button = edit that lane's cycle length.
		press_time = self._last_side_press_times.pop(sender, None)
		if press_time == None:
			return False
		if time.time() - press_time > 0.4:
			self._selected_length_lane = lane
			self.set_mode(POLY_MODE_LANE_LENGTH)
			self._control_surface.show_message("%s length" % lane)
			self._step_sequencer._update_OSD()
			return True
		return False

	def _update_random_button(self):
		self._update_gate_button()

	def set_random_button(self, button):
		# Parent constructor calls this; rebind to gate instead of random.
		self.set_gate_button(button)

	def set_gate_button(self, button):
		assert isinstance(button, (ButtonElement, type(None)))
		current_button = getattr(self, "_gate_button", None)
		if current_button != button:
			if current_button != None:
				current_button.remove_value_listener(self._gate_button_value)
			self._gate_button = button
			if self._gate_button != None:
				self._gate_button.add_value_listener(self._gate_button_value, identify_sender=True)

	def _update_gate_button(self):
		if self.is_enabled() and self._gate_button != None:
			if self._clip != None:
				if self._mode == POLY_MODE_LANE_LENGTH and self._selected_length_lane == LANE_GATE:
					self._gate_button.set_light("PolymetricSequencer.SideLength")
				else:
					self._gate_button.set_on_off_values("PolymetricSequencer.SideOn", "PolymetricSequencer.SideOff")
					if self._mode == POLY_MODE_GATE:
						self._gate_button.turn_on()
					else:
						self._gate_button.turn_off()
			else:
				self._gate_button.set_light("DefaultButton.Disabled")

	def _gate_button_value(self, value, sender):
		if self.is_enabled() and self._clip != None:
			if value != 0 or not sender.is_momentary():
				self._last_side_press_times[sender] = time.time()
			else:
				if not self._button_released_as_length_edit(sender, LANE_GATE):
					self.set_mode(POLY_MODE_GATE)
					self._control_surface.show_message("gate")
					self._step_sequencer._update_OSD()

	def _update_mode_notes_pitches_button(self):
		self._update_lane_button(self._mode_notes_pitches_button, POLY_MODE_PITCH, LANE_PITCH, "StepSequencer2.Pitch.On", "StepSequencer2.Pitch.Dim")

	def _update_mode_notes_octaves_button(self):
		self._update_lane_button(self._mode_notes_octaves_button, POLY_MODE_OCTAVE, LANE_OCTAVE, "StepSequencer2.Octave.On", "StepSequencer2.Octave.Dim")

	def _update_mode_notes_velocities_button(self):
		self._update_lane_button(self._mode_notes_velocities_button, POLY_MODE_VELOCITY, LANE_VELOCITY, "StepSequencer2.Velocity.On", "StepSequencer2.Velocity.Dim")

	def _update_mode_notes_lengths_button(self):
		self._update_lane_button(self._mode_notes_lengths_button, POLY_MODE_LENGTH, LANE_LENGTH, "StepSequencer2.Length.On", "StepSequencer2.Length.Dim")

	def _update_lane_button(self, button, mode, lane, on_color, off_color):
		if self.is_enabled() and button != None:
			if self._clip != None:
				if self._mode == POLY_MODE_LANE_LENGTH and self._selected_length_lane == lane:
					button.set_light("PolymetricSequencer.SideLength")
				else:
					button.set_on_off_values(on_color, off_color)
					if self._mode == mode:
						button.turn_on()
					else:
						button.turn_off()
			else:
				button.set_light("DefaultButton.Disabled")

	def _mode_button_notes_pitches_value(self, value, sender):
		if self.is_enabled() and self._clip != None:
			if value != 0 or not sender.is_momentary():
				self._last_side_press_times[sender] = time.time()
			else:
				if self._button_released_as_length_edit(sender, LANE_PITCH):
					return
				if time.time() - self._last_notes_pitches_button_press < 0.5:
					self._is_monophonic = not self._is_monophonic
					if self._is_monophonic:
						self._prune_polyphonic_pitches()
					self._update_clip_notes()
					self._control_surface.show_message("mono" if self._is_monophonic else "poly")
				else:
					self.set_mode(POLY_MODE_PITCH)
					self._control_surface.show_message("pitch")
				self._last_notes_pitches_button_press = time.time()
				self._step_sequencer._update_OSD()

	def _mode_button_notes_octaves_value(self, value, sender):
		self._lane_button_value(value, sender, LANE_OCTAVE, POLY_MODE_OCTAVE, "octave")

	def _mode_button_notes_velocities_value(self, value, sender):
		self._lane_button_value(value, sender, LANE_VELOCITY, POLY_MODE_VELOCITY, "velocity")

	def _mode_button_notes_lengths_value(self, value, sender):
		self._lane_button_value(value, sender, LANE_LENGTH, POLY_MODE_LENGTH, "length")

	def _lane_button_value(self, value, sender, lane, mode, message):
		if self.is_enabled() and self._clip != None:
			if value != 0 or not sender.is_momentary():
				self._last_side_press_times[sender] = time.time()
			else:
				if not self._button_released_as_length_edit(sender, lane):
					self.set_mode(mode)
					self._control_surface.show_message(message)
					self._step_sequencer._update_OSD()


class PolymetricSequencerComponent(StepSequencerComponent2):
	"""Wrapper that swaps in the polymetric note editor; clip follow, scale, quantization, and nav stay standard."""

	def __init__(self, matrix, side_buttons, top_buttons, control_surface):
		super(PolymetricSequencerComponent, self).__init__(matrix, side_buttons, top_buttons, control_surface)
		self._name = "polymetric step sequencer"

	def _set_note_editor(self):
		# Everything outside the editor remains StepSequencer2: clip follow, lock, quantization, scale, loop nav, OSD.
		self._note_editor = self.register_component(PolymetricNoteEditorComponent(self, self._matrix, self._side_buttons, self._control_surface))

	def _update_OSD(self):
		if self._osd != None:
			self._osd.set_mode("Polymetric Step Sequencer")
			if self._clip != None:
				self._osd.attributes[0] = MUSICAL_MODES[self._scale_selector._modus * 2]
				self._osd.attribute_names[0] = "Scale"
				self._osd.attributes[1] = KEY_NAMES[self._scale_selector._key % 12]
				self._osd.attribute_names[1] = "Root Note"
				self._osd.attributes[2] = self._scale_selector._octave
				self._osd.attribute_names[2] = "Octave"
				self._osd.attributes[3] = QUANTIZATION_NAMES[self._quantization_index]
				self._osd.attribute_names[3] = "Quantisation"
				active_lane = self._note_editor._active_lane()
				if self._note_editor._mode == POLY_MODE_LANE_LENGTH:
					self._osd.attributes[4] = "%s %d" % (self._note_editor._selected_length_lane, self._note_editor._active_lane_length())
					self._osd.attribute_names[4] = "Seq Length"
				else:
					self._osd.attributes[4] = active_lane
					self._osd.attribute_names[4] = "Parameter"
				self._osd.attributes[5] = "%d/%d/%d/%d/%d" % (
					self._note_editor._lane_lengths[LANE_GATE],
					self._note_editor._lane_lengths[LANE_PITCH],
					self._note_editor._lane_lengths[LANE_OCTAVE],
					self._note_editor._lane_lengths[LANE_VELOCITY],
					self._note_editor._lane_lengths[LANE_LENGTH]
				)
				self._osd.attribute_names[5] = "G/P/O/V/L"
				self._osd.attributes[6] = "Mono" if self._note_editor._is_monophonic else "Poly"
				self._osd.attribute_names[6] = "Polyphony"
				self._osd.attributes[7] = " "
				self._osd.attribute_names[7] = " "
			else:
				for index in xrange(8):
					self._osd.attributes[index] = " "
					self._osd.attribute_names[index] = " "

			if self._selected_track != None:
				if self._lock_to_track and self._is_locked:
					self._osd.info[0] = "track : " + self._selected_track.name + " (locked)"
				else:
					self._osd.info[0] = "track : " + self._selected_track.name
			else:
				self._osd.info[0] = " "
			if self._clip != None:
				name = self._clip.name
				if name == "":
					name = "(unamed clip)"
				if not self._lock_to_track and self._is_locked:
					self._osd.info[1] = "clip : " + name + " (locked)"
				else:
					self._osd.info[1] = "clip : " + name
			else:
				self._osd.info[1] = "no clip selected"
			self._osd.update()
