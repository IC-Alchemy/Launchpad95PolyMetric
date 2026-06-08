import time
from random import randrange

from _Framework.ButtonElement import ButtonElement
from _Framework.ButtonMatrixElement import ButtonMatrixElement
from _Framework.ControlSurfaceComponent import ControlSurfaceComponent

from .ScaleComponent import KEY_NAMES, MUSICAL_MODES


try:
    xrange
except NameError:
    xrange = range


MODE_STEP = "step"
MODE_NOTE = "note"
MODE_LENGTH = "length"

PARAMETERS = [
    "note",
    "velocity",
    "octave",
    "gate_length",
    "cc1",
    "cc2",
    "cc3",
    "cc4"
]

PARAMETER_LABELS = {
    "note": "Note",
    "velocity": "Velocity",
    "octave": "Octave",
    "gate_length": "Gate",
    "cc1": "CC 1",
    "cc2": "CC 2",
    "cc3": "CC 3",
    "cc4": "CC 4"
}

MAX_STEPS = 16
STEPS_PER_PAGE = 8
LONG_PRESS = 0.4
DEFAULT_NOTE = 60
DEFAULT_VELOCITY_INDEX = 4
DEFAULT_OCTAVE_INDEX = 3
DEFAULT_GATE_LENGTH_INDEX = 3
DEFAULT_CC_INDEX = 0
DEFAULT_QUANTIZATION = 0.25
NOTE_EDITOR_BASE_OCTAVE = 3

VELOCITY_VALUES = [0, 30, 60, 80, 100, 115, 127]
OCTAVE_VALUES = [-3, -2, -1, 0, 1, 2, 3]
GATE_LENGTH_VALUES = [0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 1.0]
CC_VALUES = [0, 21, 42, 63, 84, 106, 127]
CC_NUMBERS = [1, 2, 3, 4]
VOICE_CHANNELS = [0, 1, 2, 3]

SCALE_INTERVALS = dict((MUSICAL_MODES[index], MUSICAL_MODES[index + 1]) for index in xrange(0, len(MUSICAL_MODES), 2))
DEFAULT_SCALE_INTERVALS = [0, 2, 4, 5, 7, 9, 11]

STEP_ON_COLORS = [
    "PolymetricSequencer.StepOn1",
    "PolymetricSequencer.StepOn2",
    "PolymetricSequencer.StepOn3",
    "PolymetricSequencer.StepOn4"
]

PLAYHEAD_COLORS = [
    "PolymetricSequencer.Playhead1",
    "PolymetricSequencer.Playhead2",
    "PolymetricSequencer.Playhead3",
    "PolymetricSequencer.Playhead4"
]


class ParameterTrack(object):

    def __init__(self, default_value):
        self.default_value = default_value
        self.values = [default_value for _ in xrange(MAX_STEPS)]
        self.step_count = MAX_STEPS

    def get_value(self, step_index):
        return self.values[step_index % self.step_count]

    def set_value(self, step_index, value):
        self.values[step_index % MAX_STEPS] = value

    def reset(self):
        for index in xrange(MAX_STEPS):
            self.values[index] = self.default_value
        self.step_count = MAX_STEPS

    def randomize(self, minimum, maximum):
        for index in xrange(MAX_STEPS):
            self.values[index] = randrange(minimum, maximum + 1)


class VoiceState(object):

    def __init__(self):
        self.tracks = {
            "note": ParameterTrack(DEFAULT_NOTE),
            "velocity": ParameterTrack(DEFAULT_VELOCITY_INDEX),
            "octave": ParameterTrack(DEFAULT_OCTAVE_INDEX),
            "gate_length": ParameterTrack(DEFAULT_GATE_LENGTH_INDEX),
            "cc1": ParameterTrack(DEFAULT_CC_INDEX),
            "cc2": ParameterTrack(DEFAULT_CC_INDEX),
            "cc3": ParameterTrack(DEFAULT_CC_INDEX),
            "cc4": ParameterTrack(DEFAULT_CC_INDEX),
            "gate": ParameterTrack(0)
        }


class PolymetricSequencerComponent(ControlSurfaceComponent):

    def __init__(self, matrix, side_buttons, top_buttons, control_surface):
        ControlSurfaceComponent.__init__(self)
        assert isinstance(matrix, ButtonMatrixElement)
        assert isinstance(side_buttons, tuple)
        assert isinstance(top_buttons, tuple)

        self._control_surface = control_surface
        self._matrix = None
        self._side_buttons = side_buttons
        self._top_buttons = top_buttons
        self._osd = None

        self._voices = [VoiceState() for _ in xrange(4)]
        self._selected_voice_pair = 0
        self._selected_voice = 0
        self._selected_step = 0
        self._selected_param = PARAMETERS[0]
        self._edit_mode = MODE_STEP
        self._current_page = 0
        self._quantization = DEFAULT_QUANTIZATION

        self._playheads = [0 for _ in xrange(4)]
        self._param_playheads = dict((parameter, [0 for _ in xrange(4)]) for parameter in PARAMETERS + ["gate"])
        self._active_notes = [None for _ in xrange(4)]
        self._pending_note_offs = []
        self._last_global_step = -1
        self._last_blink = -1

        self._grid_buffer = [[None for _ in xrange(8)] for _ in xrange(8)]
        self._grid_back_buffer = [[None for _ in xrange(8)] for _ in xrange(8)]
        self._force_update = True

        self._matrix_press_times = {}
        self._side_press_times = {}
        self._top_press_times = {}
        self._timer_registered = False

        self._register_button_listeners()
        self.set_matrix(matrix)
        self.set_enabled(False)

    def disconnect(self):
        self._unregister_timer()
        self._stop_all_notes()
        if self._matrix is not None:
            try:
                self._matrix.remove_value_listener(self._matrix_value)
            except RuntimeError:
                pass

        for button in self._side_buttons:
            if button is not None:
                try:
                    button.remove_value_listener(self._side_value)
                except RuntimeError:
                    pass

        for button in self._top_buttons:
            if button is not None:
                try:
                    button.remove_value_listener(self._top_value)
                except RuntimeError:
                    pass

        self._matrix = None
        self._side_buttons = None
        self._top_buttons = None
        self._voices = None
        self._pending_note_offs = None
        self._active_notes = None

    def set_osd(self, osd):
        self._osd = osd

    def set_matrix(self, matrix):
        assert isinstance(matrix, (ButtonMatrixElement, type(None)))
        if self._matrix is not None:
            try:
                self._matrix.remove_value_listener(self._matrix_value)
            except RuntimeError:
                pass

        self._matrix = matrix
        if self._matrix is not None:
            self._matrix.add_value_listener(self._matrix_value)
        self._force_update = True

    def set_enabled(self, enabled):
        ControlSurfaceComponent.set_enabled(self, enabled)
        if enabled:
            self._register_timer()
            self._force_update = True
            self.update()
        else:
            self._unregister_timer()
            self._stop_all_notes()

    def update(self):
        if not self.is_enabled():
            return
        self._update_osd()
        self._update_buttons()
        self._update_matrix()

    def _register_button_listeners(self):
        for button in self._side_buttons:
            assert isinstance(button, ButtonElement)
            button.add_value_listener(self._side_value, identify_sender=True)

        for button in self._top_buttons:
            assert isinstance(button, ButtonElement)
            button.add_value_listener(self._top_value, identify_sender=True)

    def _register_timer(self):
        if not self._timer_registered and hasattr(self._control_surface, "_register_timer_callback"):
            self._control_surface._register_timer_callback(self._on_timer)
            self._timer_registered = True

    def _unregister_timer(self):
        if self._timer_registered and hasattr(self._control_surface, "_unregister_timer_callback"):
            try:
                self._control_surface._unregister_timer_callback(self._on_timer)
            except RuntimeError:
                pass
            self._timer_registered = False

    def _on_timer(self):
        if not self.is_enabled():
            return

        song_time = self._song_time()
        self._flush_note_offs(song_time)

        if self.song().is_playing:
            global_step = int(song_time / self._quantization)
            if global_step != self._last_global_step:
                self._last_global_step = global_step
                self._process_step(global_step, song_time)
                self._force_update = True
        else:
            if self._last_global_step != -1:
                self._last_global_step = -1
                self._stop_all_notes()
                self._force_update = True

        blink_state = int(time.time() * 2)
        if blink_state != self._last_blink:
            self._last_blink = blink_state
            self._force_update = True

        if self._force_update:
            self.update()

    def _song_time(self):
        try:
            return self.song().current_song_time
        except RuntimeError:
            return 0.0

    def _process_step(self, global_step, song_time):
        for voice_index in xrange(4):
            voice = self._voices[voice_index]
            self._playheads[voice_index] = global_step % voice.tracks["gate"].step_count
            for parameter in PARAMETERS + ["gate"]:
                self._param_playheads[parameter][voice_index] = global_step % voice.tracks[parameter].step_count

            if voice.tracks["gate"].get_value(global_step) <= 0:
                continue

            note_value = int(voice.tracks["note"].get_value(global_step))
            velocity_index = int(voice.tracks["velocity"].get_value(global_step))
            octave_index = int(voice.tracks["octave"].get_value(global_step))
            gate_length_index = int(voice.tracks["gate_length"].get_value(global_step))

            if note_value < 0:
                note_value = 0
            elif note_value > 127:
                note_value = 127

            pitch = note_value + (12 * OCTAVE_VALUES[max(0, min(6, octave_index))])
            pitch = max(0, min(127, pitch))
            velocity = VELOCITY_VALUES[max(0, min(6, velocity_index))]
            channel = VOICE_CHANNELS[voice_index]

            self._send_voice_ccs(voice_index, global_step)
            self._send_note_on(voice_index, channel, pitch, velocity)

            gate_fraction = GATE_LENGTH_VALUES[max(0, min(6, gate_length_index))]
            self._pending_note_offs.append({
                "voice": voice_index,
                "channel": channel,
                "pitch": pitch,
                "time": song_time + (self._quantization * gate_fraction)
            })

    def _send_voice_ccs(self, voice_index, global_step):
        voice = self._voices[voice_index]
        channel = VOICE_CHANNELS[voice_index]
        for cc_offset, parameter in enumerate(("cc1", "cc2", "cc3", "cc4")):
            value_index = int(voice.tracks[parameter].get_value(global_step))
            value_index = max(0, min(6, value_index))
            self._send_cc(channel, CC_NUMBERS[cc_offset], CC_VALUES[value_index])

    def _send_note_on(self, voice_index, channel, pitch, velocity):
        self._cancel_note_offs_for_voice(voice_index)
        if self._active_notes[voice_index] is not None:
            self._send_note_off(channel, self._active_notes[voice_index])
        self._active_notes[voice_index] = pitch
        self._send_midi((144 + channel, pitch, velocity))

    def _send_note_off(self, channel, pitch):
        self._send_midi((128 + channel, pitch, 0))

    def _send_cc(self, channel, cc_number, cc_value):
        self._send_midi((176 + channel, cc_number, cc_value))

    def _send_midi(self, message):
        try:
            self._control_surface._send_midi(message)
        except RuntimeError:
            pass

    def _flush_note_offs(self, song_time):
        remaining = []
        for event in self._pending_note_offs:
            if song_time >= event["time"]:
                self._send_note_off(event["channel"], event["pitch"])
                if self._active_notes[event["voice"]] == event["pitch"]:
                    self._active_notes[event["voice"]] = None
            else:
                remaining.append(event)
        self._pending_note_offs = remaining

    def _cancel_note_offs_for_voice(self, voice_index):
        self._pending_note_offs = [event for event in self._pending_note_offs if event["voice"] != voice_index]

    def _stop_all_notes(self):
        for voice_index, note_value in enumerate(self._active_notes):
            if note_value is not None:
                self._send_note_off(VOICE_CHANNELS[voice_index], note_value)
                self._active_notes[voice_index] = None
        self._pending_note_offs = []

    def _matrix_value(self, value, x, y, is_momentary):
        if not self.is_enabled() or self._matrix is None:
            return

        key = (x, y)
        if value != 0:
            self._matrix_press_times[key] = time.time()
            self._handle_matrix_press(x, y)
            return

        press_time = self._matrix_press_times.pop(key, None)
        if press_time is None:
            return

        self._handle_matrix_release(x, y, time.time() - press_time)

    def _handle_matrix_press(self, x, y):
        if self._edit_mode == MODE_NOTE:
            self._handle_note_press(x, y)
        elif self._edit_mode == MODE_LENGTH:
            self._handle_length_press(x, y)
        elif self._edit_mode != MODE_STEP:
            self._handle_fader_press(x, y)

    def _handle_matrix_release(self, x, y, duration):
        if self._edit_mode != MODE_STEP:
            return
        if y >= 4:
            return

        voice_index = self._selected_voice_pair * 2 + (y // 2)
        step_index = x + ((y % 2) * 8)
        self._selected_voice = voice_index
        self._selected_step = step_index

        if duration >= LONG_PRESS:
            self._selected_param = "note"
            self._edit_mode = MODE_NOTE
            self._current_page = 0 if step_index < 8 else 1
        else:
            gate_track = self._voices[voice_index].tracks["gate"]
            gate_value = gate_track.values[step_index]
            gate_track.values[step_index] = 0 if gate_value > 0 else 1
        self._force_update = True

    def _handle_note_press(self, x, y):
        if y >= 7:
            return

        step_index = (self._current_page * STEPS_PER_PAGE) + x
        voice = self._voices[self._selected_voice]
        if voice.tracks["gate"].values[step_index] <= 0:
            return

        voice.tracks["note"].values[step_index] = self._note_value_for_row(y)
        self._selected_step = step_index
        self._force_update = True

    def _handle_fader_press(self, x, y):
        if y >= 7:
            return

        step_index = (self._current_page * STEPS_PER_PAGE) + x
        value_index = 6 - y
        voice = self._voices[self._selected_voice]
        voice.tracks[self._selected_param].values[step_index] = value_index
        self._selected_step = step_index
        self._force_update = True

    def _handle_length_press(self, x, y):
        if y >= 4:
            return

        step_index = x + ((y % 2) * 8)
        self._voices[self._selected_voice].tracks[self._selected_param].step_count = step_index + 1
        self._selected_step = step_index
        self._force_update = True

    def _side_value(self, value, sender):
        if not self.is_enabled():
            return

        index = self._side_buttons.index(sender)
        parameter = PARAMETERS[index]
        if value != 0:
            self._side_press_times[sender] = time.time()
            return

        press_time = self._side_press_times.pop(sender, None)
        if press_time is None:
            return

        duration = time.time() - press_time
        self._selected_param = parameter
        if duration >= LONG_PRESS:
            self._edit_mode = MODE_LENGTH
        elif parameter == "note":
            self._edit_mode = MODE_STEP if self._edit_mode == MODE_NOTE else MODE_NOTE
        else:
            self._edit_mode = MODE_STEP if (self._edit_mode == parameter) else parameter
        self._force_update = True

    def _top_value(self, value, sender):
        if not self.is_enabled():
            return

        index = self._top_buttons.index(sender)
        if value != 0:
            self._top_press_times[sender] = time.time()
            if index == 0:
                self._toggle_selected_voice()
            elif index == 1:
                self._toggle_voice_pair()
            elif index == 2:
                self._current_page = 1 - self._current_page
            self._force_update = True
            return

        press_time = self._top_press_times.pop(sender, None)
        if press_time is None:
            return

        duration = time.time() - press_time
        if index == 3:
            if duration >= LONG_PRESS:
                self._reset_voice(self._selected_voice)
            else:
                self._randomize_voice(self._selected_voice)
            self._force_update = True

    def _toggle_selected_voice(self):
        pair_start = self._selected_voice_pair * 2
        self._selected_voice = pair_start + (1 - (self._selected_voice - pair_start))

    def _toggle_voice_pair(self):
        offset = self._selected_voice % 2
        self._selected_voice_pair = 1 - self._selected_voice_pair
        self._selected_voice = (self._selected_voice_pair * 2) + offset

    def _reset_voice(self, voice_index):
        voice = self._voices[voice_index]
        for parameter in PARAMETERS + ["gate"]:
            voice.tracks[parameter].reset()
        self._control_surface.show_message("POLYMETRIC VOICE %d RESET" % (voice_index + 1))

    def _randomize_voice(self, voice_index):
        voice = self._voices[voice_index]
        for step_index in xrange(MAX_STEPS):
            voice.tracks["gate"].values[step_index] = 1 if randrange(0, 100) < (70 if step_index % 2 == 0 else 45) else 0
            voice.tracks["note"].values[step_index] = self._note_value_for_row(randrange(0, 7))
            voice.tracks["velocity"].values[step_index] = randrange(0, 7)
            voice.tracks["octave"].values[step_index] = randrange(0, 7)
            voice.tracks["gate_length"].values[step_index] = randrange(0, 7)
            voice.tracks["cc1"].values[step_index] = randrange(0, 7)
            voice.tracks["cc2"].values[step_index] = randrange(0, 7)
            voice.tracks["cc3"].values[step_index] = randrange(0, 7)
            voice.tracks["cc4"].values[step_index] = randrange(0, 7)
        self._control_surface.show_message("POLYMETRIC VOICE %d RANDOMIZED" % (voice_index + 1))

    def _update_buttons(self):
        for index, button in enumerate(self._side_buttons):
            parameter = PARAMETERS[index]
            if self._edit_mode == MODE_LENGTH and parameter == self._selected_param:
                button.set_light("PolymetricSequencer.SideLength")
            elif (parameter == "note" and self._edit_mode == MODE_NOTE) or self._edit_mode == parameter:
                button.set_light("PolymetricSequencer.SideOn")
            else:
                button.set_light("PolymetricSequencer.SideOff")

        for index, button in enumerate(self._top_buttons):
            if index == 0:
                button.set_light("PolymetricSequencer.TopVoiceB" if (self._selected_voice % 2) else "PolymetricSequencer.TopVoiceA")
            elif index == 1:
                button.set_light("PolymetricSequencer.TopPairB" if self._selected_voice_pair else "PolymetricSequencer.TopPairA")
            elif index == 2:
                button.set_light("PolymetricSequencer.TopPageB" if self._current_page else "PolymetricSequencer.TopPageA")
            else:
                button.set_light("PolymetricSequencer.TopRandom")

    def _update_matrix(self):
        if self._matrix is None:
            return

        for x in xrange(8):
            for y in xrange(8):
                self._grid_back_buffer[x][y] = "PolymetricSequencer.Blank"

        if self._edit_mode == MODE_STEP:
            self._render_step_grid()
        elif self._edit_mode == MODE_NOTE:
            self._render_note_grid()
        elif self._edit_mode == MODE_LENGTH:
            self._render_length_grid()
        else:
            self._render_fader_grid()

        for x in xrange(8):
            for y in xrange(8):
                if self._grid_back_buffer[x][y] != self._grid_buffer[x][y] or self._force_update:
                    self._grid_buffer[x][y] = self._grid_back_buffer[x][y]
                    self._matrix.get_button(x, y).set_light(self._grid_buffer[x][y])

        self._force_update = False

    def _render_step_grid(self):
        pair_start = self._selected_voice_pair * 2
        blink_on = self._last_blink % 2 == 0
        for visible_voice in xrange(2):
            voice_index = pair_start + visible_voice
            base_row = visible_voice * 2
            gate_track = self._voices[voice_index].tracks["gate"]
            playhead = self._playheads[voice_index]
            for step_index in xrange(MAX_STEPS):
                x = step_index % 8
                y = base_row + (step_index // 8)
                color = "PolymetricSequencer.StepOff"
                if gate_track.values[step_index] > 0:
                    color = STEP_ON_COLORS[voice_index]
                if step_index == playhead:
                    color = PLAYHEAD_COLORS[voice_index]
                if voice_index == self._selected_voice and step_index == self._selected_step and blink_on:
                    color = "PolymetricSequencer.StepSelected"
                self._grid_back_buffer[x][y] = color

    def _render_note_grid(self):
        voice = self._voices[self._selected_voice]
        playhead = self._param_playheads["note"][self._selected_voice]
        for x in xrange(8):
            step_index = (self._current_page * STEPS_PER_PAGE) + x
            note_value = voice.tracks["note"].values[step_index]
            gate_on = voice.tracks["gate"].values[step_index] > 0
            for y in xrange(7):
                row_note = self._note_value_for_row(y)
                if note_value == row_note:
                    if gate_on:
                        color = "PolymetricSequencer.NoteOn"
                    else:
                        color = "PolymetricSequencer.NoteDim"
                else:
                    color = "PolymetricSequencer.NoteOff"
                self._grid_back_buffer[x][y] = color
            if (playhead // STEPS_PER_PAGE) == self._current_page and (playhead % STEPS_PER_PAGE) == x:
                self._grid_back_buffer[x][7] = PLAYHEAD_COLORS[self._selected_voice]
            else:
                self._grid_back_buffer[x][7] = "PolymetricSequencer.PageMarker"

    def _render_fader_grid(self):
        voice = self._voices[self._selected_voice]
        playhead = self._param_playheads[self._selected_param][self._selected_voice]
        bar_mode = self._selected_param != "octave"
        for x in xrange(8):
            step_index = (self._current_page * STEPS_PER_PAGE) + x
            value = int(voice.tracks[self._selected_param].values[step_index])
            gate_on = voice.tracks["gate"].values[step_index] > 0
            for y in xrange(7):
                row_value = 6 - y
                if bar_mode:
                    enabled = value >= row_value
                else:
                    enabled = value == row_value

                if enabled:
                    if gate_on:
                        color = "PolymetricSequencer.FaderOn"
                    else:
                        color = "PolymetricSequencer.FaderDim"
                else:
                    color = "PolymetricSequencer.FaderOff"
                self._grid_back_buffer[x][y] = color

            if (playhead // STEPS_PER_PAGE) == self._current_page and (playhead % STEPS_PER_PAGE) == x:
                self._grid_back_buffer[x][7] = PLAYHEAD_COLORS[self._selected_voice]
            else:
                self._grid_back_buffer[x][7] = "PolymetricSequencer.PageMarker"

    def _render_length_grid(self):
        pair_start = self._selected_voice_pair * 2
        selected_row_offset = self._selected_voice - pair_start
        if selected_row_offset < 0 or selected_row_offset > 1:
            selected_row_offset = 0
        base_row = selected_row_offset * 2
        track_length = self._voices[self._selected_voice].tracks[self._selected_param].step_count
        for step_index in xrange(MAX_STEPS):
            x = step_index % 8
            y = base_row + (step_index // 8)
            if step_index == (track_length - 1):
                color = "PolymetricSequencer.LengthSelected"
            elif step_index < track_length:
                color = "PolymetricSequencer.LengthOn"
            else:
                color = "PolymetricSequencer.LengthOff"
            self._grid_back_buffer[x][y] = color

    def _update_osd(self):
        if self._osd is None:
            return

        self._osd.set_mode("Polymetric Step Sequencer")
        self._osd.attributes[0] = PARAMETER_LABELS[self._selected_param]
        self._osd.attribute_names[0] = "Parameter"
        self._osd.attributes[1] = str(self._selected_voice + 1)
        self._osd.attribute_names[1] = "Voice"
        self._osd.attributes[2] = str(self._selected_voice_pair + 1)
        self._osd.attribute_names[2] = "Pair"
        self._osd.attributes[3] = str(self._current_page + 1)
        self._osd.attribute_names[3] = "Page"
        self._osd.attributes[4] = KEY_NAMES[self.song().root_note % 12]
        self._osd.attribute_names[4] = "Root"
        self._osd.attributes[5] = self.song().scale_name
        self._osd.attribute_names[5] = "Scale"
        self._osd.attributes[6] = self._edit_mode.title()
        self._osd.attribute_names[6] = "View"
        self._osd.attributes[7] = "1/16"
        self._osd.attribute_names[7] = "Rate"

        selected_track = self.song().view.selected_track
        self._osd.info[0] = "track : %s" % selected_track.name if selected_track is not None else "track : none"
        self._osd.info[1] = "channels : 1-4 / cc : 1-4"
        self._osd.update()

    def _note_value_for_row(self, row):
        scale_name = self.song().scale_name
        intervals = SCALE_INTERVALS.get(scale_name, DEFAULT_SCALE_INTERVALS)
        expanded = []
        octave = 0
        while len(expanded) < 7:
            for interval in intervals:
                expanded.append(interval + (12 * octave))
                if len(expanded) >= 7:
                    break
            octave += 1

        row_index = 6 - row
        return self.song().root_note + (12 * NOTE_EDITOR_BASE_OCTAVE) + expanded[row_index]
