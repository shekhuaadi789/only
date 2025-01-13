from shutil import which

from facefusion import ffmpeg_builder
from facefusion.ffmpeg_builder import chain, run, select_frame_range, set_audio_quality, set_audio_sample_size, set_stream_mode


def test_run() -> None:
	assert run([]) == [ which('ffmpeg'), '-loglevel', 'error' ]


def test_chain() -> None:
	commands = chain(
		ffmpeg_builder.set_progress()
	)

	assert commands == [ '-progress' ]


def test_stream_mode() -> None:
	assert set_stream_mode('udp') == [ '-f', 'mpegts' ]
	assert set_stream_mode('v4l2') == [ '-f', 'v4l2' ]


def test_select_frame_range() -> None:
	assert select_frame_range(0, None, 30) == [ '-vf', 'trim=start_frame=0,fps=30' ]
	assert select_frame_range(None, 100, 30) == [ '-vf', 'trim=end_frame=100,fps=30' ]
	assert select_frame_range(0, 100, 30) == [ '-vf', 'trim=start_frame=0:end_frame=100,fps=30' ]
	assert select_frame_range(None, None, 30) == [ '-vf', 'fps=30' ]


def test_audio_sample_size() -> None:
	assert set_audio_sample_size(16) == [ '-f', 's16le', '-acodec', 'pcm_s16le' ]
	assert set_audio_sample_size(32) == [ '-f', 's32le', '-acodec', 'pcm_s32le' ]


def test_set_audio_quality() -> None:
	assert set_audio_quality('aac', 0) == [ '-q:a', '2.0' ]
	assert set_audio_quality('aac', 50) == [ '-q:a', '1.1' ]
	assert set_audio_quality('aac', 100) == [ '-q:a', '0.1' ]
	assert set_audio_quality('libmp3lame', 0) == [ '-q:a', '9' ]
	assert set_audio_quality('libmp3lame', 50) == [ '-q:a', '4' ]
	assert set_audio_quality('libmp3lame', 100) == [ '-q:a', '0' ]
	assert set_audio_quality('libopus', 0) == [ '-b:a', '64k' ]
	assert set_audio_quality('libopus', 50) == [ '-b:a', '192k' ]
	assert set_audio_quality('libopus', 100) == [ '-b:a', '320k' ]
	assert set_audio_quality('libvorbis', 0) == [ '-q:a', '-1.0' ]
	assert set_audio_quality('libvorbis', 50) == [ '-q:a', '4.5' ]
	assert set_audio_quality('libvorbis', 100) == [ '-q:a', '10.0' ]
