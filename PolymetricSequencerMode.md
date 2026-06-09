# Launchpad95 Progress

## Goal
Port Pico2Seq-style sequencer behavior into Launchpad95 as a new User2 mode.

# 6/7/2026

## Current Status
- The custom script now loads successfully when using `Launchpad X` instead of `Launchpad Pro`.
- Most existing Launchpad95 functionality works.
- The new polymetric sequencer mode is visible and selectable.
- LEDs/lights update correctly in that mode, but the actual sequencer behavior is not correct yet.

- The polymetric sequencer now works on Launchpad X (manual testing confirms playback and editing).

## What Has Been Implemented
- Added a new `PolymetricSequencerComponent`.
- Wired `polymetric stepseq` into `Settings.py`.
- Wired the new mode into `MainSelectorComponent.py`.
- Added skin entries for the new mode in `SkinMK1.py` and `SkinMK2.py`.
- Fixed a skin indentation issue.
- Added Launchpad Pro mk1 identity handling in `Launchpad.py`.
- Extended RGB/session handling so the Pro path can initialize.

## Testing Notes
- Launchpad X works as the device profile that allows the script to initialize properly.
- With Launchpad X, mode switching works and the polymetric mode can be entered.
- The mode lights respond, so the mode hookup is alive.
- The remaining issue is functional: the polymetric sequencer needs a fundamental redesign or correction.

## Key Observation
The current polymetric sequencer implementation is not yet aligned with the actual Launchpad95 control-surface patterns. The mode exists and renders, but the editing/behavior model needs to be rethought.

## Next Step
Rework the polymetric sequencer architecture rather than only patching small behavior details.

# 6/8/2026

## Implementation Update
- Replaced the realtime four-voice polymetric engine with a clip-backed sequencer based on the melodic step sequencer architecture.
- The polymetric mode now targets one selected MIDI clip, one voice, and the full 8x8 grid.
- Added independent polymetric lane lengths for gate, pitch, octave, velocity, and note length.
- Lane lengths persist in the MIDI clip name with a `[poly:g...,p...,o...,v...,l...]` metadata token.
- Removed the realtime MIDI voice/channel/CC model from the polymetric component.

## Current Focus
- Manual Ableton testing is still needed for clip creation, mode switching, lane-length editing, clip-name metadata persistence, and playback playhead display.
