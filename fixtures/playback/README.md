# Browser playback fixtures

Tiny generated fixtures for native media playback and video sampling tests. No
Provider or remote media is involved. `scripts/generate_playback_fixtures.py`
runs with the backend quality image's locked Pillow and FFmpeg dependencies.

- `red-tone.mp4`: 160 × 90 red H.264 video, approximately 0.8 seconds, AAC 440 Hz tone.
- `blue-tone.mp4`: same duration and dimensions, blue video with a 660 Hz tone.
- `tone.wav`: 1.2-second 440 Hz PCM audio for linked voice playback.
- `blue-frame.png`: 160 × 90 static image.
- `red-start.png` and `red-end.png`: the MP4's frames sampled by the production
  `extract_video_samples` implementation.

Tests assert decoding, media time, planned cut duration, native mute state, and
sample availability. They do not evaluate visual quality or synthesize audio.
