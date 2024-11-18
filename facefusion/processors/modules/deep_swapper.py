from argparse import ArgumentParser
from typing import List, Tuple

import cv2
import numpy

import facefusion.jobs.job_manager
import facefusion.jobs.job_store
import facefusion.processors.core as processors
from facefusion import config, content_analyser, face_classifier, face_detector, face_landmarker, face_masker, face_recognizer, inference_manager, logger, process_manager, state_manager, wording
from facefusion.common_helper import create_int_metavar
from facefusion.download import conditional_download_hashes, conditional_download_sources, resolve_download_url_by_provider
from facefusion.face_analyser import get_many_faces, get_one_face
from facefusion.face_helper import paste_back, warp_face_by_face_landmark_5
from facefusion.face_masker import create_occlusion_mask, create_static_box_mask
from facefusion.face_selector import find_similar_faces, sort_and_filter_faces
from facefusion.face_store import get_reference_faces
from facefusion.filesystem import in_directory, is_image, is_video, resolve_relative_path, same_file_extension
from facefusion.processors import choices as processors_choices
from facefusion.processors.typing import DeepSwapperInputs, DeepSwapperMorph
from facefusion.program_helper import find_argument_group
from facefusion.thread_helper import thread_semaphore
from facefusion.typing import ApplyStateItem, Args, Face, InferencePool, Mask, ModelOptions, ModelSet, ProcessMode, QueuePayload, UpdateProgress, VisionFrame
from facefusion.vision import conditional_match_frame_color, read_image, read_static_image, write_image


def create_model_set() -> ModelSet:
	model_config =\
	[
		('iperov', 'alexandra_daddario_224', (224, 224)),
		('iperov', 'alexei_navalny_224', (224, 224)),
		('iperov', 'amber_heard_224', (224, 224)),
		('iperov', 'dilraba_dilmurat_224', (224, 224)),
		('iperov', 'elon_musk_224', (224, 224)),
		('iperov', 'emilia_clarke_224', (224, 224)),
		('iperov', 'emma_watson_224', (224, 224)),
		('iperov', 'erin_moriarty_224', (224, 224)),
		('iperov', 'jackie_chan_224', (224, 224)),
		('iperov', 'james_carrey_224', (224, 224)),
		('iperov', 'jason_statham_320', (320, 320)),
		('iperov', 'jessica_alba_224', (224, 224)),
		('iperov', 'keanu_reeves_320', (320, 320)),
		('iperov', 'lucy_liu_224', (224, 224)),
		('iperov', 'margot_robbie_224', (224, 224)),
		('iperov', 'meghan_markle_224', (224, 224)),
		('iperov', 'natalie_dormer_224', (224, 224)),
		('iperov', 'natalie_portman_224', (224, 224)),
		('iperov', 'nicolas_coppola_224', (224, 224)),
		('iperov', 'robert_downey_224', (224, 224)),
		('iperov', 'rowan_atkinson_224', (224, 224)),
		('iperov', 'ryan_reynolds_224', (224, 224)),
		('iperov', 'scarlett_johansson_224', (224, 224)),
		('iperov', 'sylvester_stallone_224', (224, 224)),
		('iperov', 'taylor_swift_224', (224, 224)),
		('iperov', 'thomas_cruise_224', (224, 224)),
		('iperov', 'thomas_holland_224', (224, 224)),
		('iperov', 'vin_diesel_224', (224, 224)),
		('iperov', 'vladimir_putin_224', (224, 224)),
		('mats', 'alica_schmidt_320', (320, 320)),
		('mats', 'ashley_alexiss_224', (224, 224)),
		('mats', 'billie_eilish_224', (224, 224)),
		('mats', 'brie_larson_224', (224, 224)),
		('mats', 'cara_delevingne_224', (224, 224)),
		('mats', 'carolin_kebekus_224', (224, 224)),
		('mats', 'chelsea_clinton_224', (224, 224)),
		('mats', 'claire_boucher_224', (224, 224)),
		('mats', 'corinna_kopf_224', (224, 224)),
		('mats', 'florence_pugh_224', (224, 224)),
		('mats', 'hillary_clinton_224', (224, 224)),
		('mats', 'jenna_fischer_224', (224, 224)),
		('mats', 'kim_jisoo_320', (320, 320)),
		('mats', 'mica_suarez_320', (320, 320)),
		('mats', 'shailene_woodley_224', (224, 224)),
		('mats', 'shraddha_kapoor_320', (320, 320)),
		('mats', 'yu_jimin_352', (352, 352))
	]
	model_set : ModelSet = {}

	for model_creator, model_name, model_size in model_config:
		model_id = '/'.join([ model_creator, model_name ])

		model_set[model_id] =\
		{
			'hashes':
			{
				'deep_swapper':
				{
					'url': resolve_download_url_by_provider('huggingface', 'deepfacelive-models-' + model_creator, model_name + '.hash'),
					'path': resolve_relative_path('../.assets/models/' + model_creator + '/' + model_name + '.hash')
				}
			},
			'sources':
			{
				'deep_swapper':
				{
					'url': resolve_download_url_by_provider('huggingface', 'deepfacelive-models-' + model_creator, model_name + '.dfm'),
					'path': resolve_relative_path('../.assets/models/' + model_creator + '/' + model_name + '.dfm')
				}
			},
			'template': 'dfl_whole_face',
			'size': model_size
		}

	return model_set


def get_inference_pool() -> InferencePool:
	model_sources = get_model_options().get('sources')
	model_context = __name__ + '.' + state_manager.get_item('deep_swapper_model')
	return inference_manager.get_inference_pool(model_context, model_sources)


def clear_inference_pool() -> None:
	model_context = __name__ + '.' + state_manager.get_item('deep_swapper_model')
	inference_manager.clear_inference_pool(model_context)


def get_model_options() -> ModelOptions:
	deep_swapper_model = state_manager.get_item('deep_swapper_model')
	return create_model_set().get(deep_swapper_model)


def register_args(program : ArgumentParser) -> None:
	group_processors = find_argument_group(program, 'processors')
	if group_processors:
		group_processors.add_argument('--deep-swapper-model', help = wording.get('help.deep_swapper_model'), default = config.get_str_value('processors.deep_swapper_model', 'iperov/elon_musk_224'), choices = processors_choices.deep_swapper_models)
		group_processors.add_argument('--deep-swapper-morph', help = wording.get('help.deep_swapper_morph'), type = int, default = config.get_int_value('processors.deep_swapper_morph', '80'), choices = processors_choices.deep_swapper_morph_range, metavar = create_int_metavar(processors_choices.deep_swapper_morph_range))
		facefusion.jobs.job_store.register_step_keys([ 'deep_swapper_model', 'deep_swapper_morph' ])


def apply_args(args : Args, apply_state_item : ApplyStateItem) -> None:
	apply_state_item('deep_swapper_model', args.get('deep_swapper_model'))
	apply_state_item('deep_swapper_morph', args.get('deep_swapper_morph'))


def pre_check() -> bool:
	model_hashes = get_model_options().get('hashes')
	model_sources = get_model_options().get('sources')

	return conditional_download_hashes(model_hashes) and conditional_download_sources(model_sources)


def pre_process(mode : ProcessMode) -> bool:
	if mode in [ 'output', 'preview' ] and not is_image(state_manager.get_item('target_path')) and not is_video(state_manager.get_item('target_path')):
		logger.error(wording.get('choose_image_or_video_target') + wording.get('exclamation_mark'), __name__)
		return False
	if mode == 'output' and not in_directory(state_manager.get_item('output_path')):
		logger.error(wording.get('specify_image_or_video_output') + wording.get('exclamation_mark'), __name__)
		return False
	if mode == 'output' and not same_file_extension([ state_manager.get_item('target_path'), state_manager.get_item('output_path') ]):
		logger.error(wording.get('match_target_and_output_extension') + wording.get('exclamation_mark'), __name__)
		return False
	return True


def post_process() -> None:
	read_static_image.cache_clear()
	if state_manager.get_item('video_memory_strategy') in [ 'strict', 'moderate' ]:
		clear_inference_pool()
	if state_manager.get_item('video_memory_strategy') == 'strict':
		content_analyser.clear_inference_pool()
		face_classifier.clear_inference_pool()
		face_detector.clear_inference_pool()
		face_landmarker.clear_inference_pool()
		face_masker.clear_inference_pool()
		face_recognizer.clear_inference_pool()


def swap_face(target_face : Face, temp_vision_frame : VisionFrame) -> VisionFrame:
	model_template = get_model_options().get('template')
	model_size = get_model_options().get('size')
	crop_vision_frame, affine_matrix = warp_face_by_face_landmark_5(temp_vision_frame, target_face.landmark_set.get('5/68'), model_template, model_size)
	crop_vision_frame_raw = crop_vision_frame.copy()
	box_mask = create_static_box_mask(crop_vision_frame.shape[:2][::-1], state_manager.get_item('face_mask_blur'), state_manager.get_item('face_mask_padding'))
	crop_masks =\
	[
		box_mask
	]

	if 'occlusion' in state_manager.get_item('face_mask_types'):
		occlusion_mask = create_occlusion_mask(crop_vision_frame)
		crop_masks.append(occlusion_mask)

	crop_vision_frame = prepare_crop_frame(crop_vision_frame)
	deep_swapper_morph = numpy.array([ numpy.interp(state_manager.get_item('deep_swapper_morph'), [ 0, 100 ], [ 0, 1 ]) ]).astype(numpy.float32)
	crop_vision_frame, crop_source_mask, crop_target_mask = forward(crop_vision_frame, deep_swapper_morph)
	crop_vision_frame = normalize_crop_frame(crop_vision_frame)
	crop_vision_frame = conditional_match_frame_color(crop_vision_frame_raw, crop_vision_frame)
	crop_masks.append(prepare_crop_mask(crop_source_mask, crop_target_mask))
	crop_mask = numpy.minimum.reduce(crop_masks).clip(0, 1)
	paste_vision_frame = paste_back(temp_vision_frame, crop_vision_frame, crop_mask, affine_matrix)
	return paste_vision_frame


def forward(crop_vision_frame : VisionFrame, deep_swapper_morph : DeepSwapperMorph) -> Tuple[VisionFrame, Mask, Mask]:
	deep_swapper = get_inference_pool().get('deep_swapper')
	deep_swapper_inputs = {}

	for deep_swapper_input in deep_swapper.get_inputs():
		if deep_swapper_input.name == 'in_face:0':
			deep_swapper_inputs[deep_swapper_input.name] = crop_vision_frame
		if deep_swapper_input.name == 'morph_value:0':
			deep_swapper_inputs[deep_swapper_input.name] = deep_swapper_morph

	with thread_semaphore():
		crop_target_mask, crop_vision_frame, crop_source_mask = deep_swapper.run(None, deep_swapper_inputs)

	return crop_vision_frame[0], crop_source_mask[0], crop_target_mask[0]


def has_morph_input() -> bool:
	deep_swapper = get_inference_pool().get('deep_swapper')

	for deep_swapper_input in deep_swapper.get_inputs():
		if deep_swapper_input.name == 'morph_value:0':
			return True
	return False


def prepare_crop_frame(crop_vision_frame : VisionFrame) -> VisionFrame:
	crop_vision_frame = cv2.addWeighted(crop_vision_frame, 1.75, cv2.GaussianBlur(crop_vision_frame, (0, 0), 2), -0.75, 0)
	crop_vision_frame = crop_vision_frame / 255.0
	crop_vision_frame = numpy.expand_dims(crop_vision_frame, axis = 0).astype(numpy.float32)
	return crop_vision_frame


def normalize_crop_frame(crop_vision_frame : VisionFrame) -> VisionFrame:
	crop_vision_frame = (crop_vision_frame * 255.0).clip(0, 255)
	crop_vision_frame = crop_vision_frame.astype(numpy.uint8)
	return crop_vision_frame


def prepare_crop_mask(crop_source_mask : Mask, crop_target_mask : Mask) -> Mask:
	model_size = get_model_options().get('size')
	blur_size = 6.25
	kernel_size = 3
	crop_mask = numpy.minimum.reduce([ crop_source_mask, crop_target_mask ])
	crop_mask = crop_mask.reshape(model_size).clip(0, 1)
	crop_mask = cv2.erode(crop_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)), iterations = 2)
	crop_mask = cv2.GaussianBlur(crop_mask, (0, 0), blur_size)
	return crop_mask


def get_reference_frame(source_face : Face, target_face : Face, temp_vision_frame : VisionFrame) -> VisionFrame:
	return swap_face(target_face, temp_vision_frame)


def process_frame(inputs : DeepSwapperInputs) -> VisionFrame:
	reference_faces = inputs.get('reference_faces')
	target_vision_frame = inputs.get('target_vision_frame')
	many_faces = sort_and_filter_faces(get_many_faces([ target_vision_frame ]))

	if state_manager.get_item('face_selector_mode') == 'many':
		if many_faces:
			for target_face in many_faces:
				target_vision_frame = swap_face(target_face, target_vision_frame)
	if state_manager.get_item('face_selector_mode') == 'one':
		target_face = get_one_face(many_faces)
		if target_face:
			target_vision_frame = swap_face(target_face, target_vision_frame)
	if state_manager.get_item('face_selector_mode') == 'reference':
		similar_faces = find_similar_faces(many_faces, reference_faces, state_manager.get_item('reference_face_distance'))
		if similar_faces:
			for similar_face in similar_faces:
				target_vision_frame = swap_face(similar_face, target_vision_frame)
	return target_vision_frame


def process_frames(source_path : List[str], queue_payloads : List[QueuePayload], update_progress : UpdateProgress) -> None:
	reference_faces = get_reference_faces() if 'reference' in state_manager.get_item('face_selector_mode') else None

	for queue_payload in process_manager.manage(queue_payloads):
		target_vision_path = queue_payload['frame_path']
		target_vision_frame = read_image(target_vision_path)
		output_vision_frame = process_frame(
		{
			'reference_faces': reference_faces,
			'target_vision_frame': target_vision_frame
		})
		write_image(target_vision_path, output_vision_frame)
		update_progress(1)


def process_image(source_path : str, target_path : str, output_path : str) -> None:
	reference_faces = get_reference_faces() if 'reference' in state_manager.get_item('face_selector_mode') else None
	target_vision_frame = read_static_image(target_path)
	output_vision_frame = process_frame(
	{
		'reference_faces': reference_faces,
		'target_vision_frame': target_vision_frame
	})
	write_image(output_path, output_vision_frame)


def process_video(source_paths : List[str], temp_frame_paths : List[str]) -> None:
	processors.multi_process_frames(None, temp_frame_paths, process_frames)
