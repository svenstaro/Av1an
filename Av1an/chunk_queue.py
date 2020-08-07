import json
from pathlib import Path
from typing import List

from .arg_parse import Args
from .chunk import Chunk
from .compose import get_file_extension_for_encoder
from .ffmpeg import frame_probe
from .logger import log
from .resume import read_done_data
from .split import segment
from .utils import terminate


def save_chunk_queue(temp: Path, chunk_queue: List[Chunk]) -> None:
    """
    Writes the chunk queue to the chunks.json file

    :param temp: the temp directory
    :param chunk_queue: the chunk queue
    :return: None
    """
    chunk_dicts = [c.to_dict() for c in chunk_queue]
    with open(temp / 'chunks.json', 'w') as file:
        json.dump(chunk_dicts, file)


def read_chunk_queue(temp: Path) -> List[Chunk]:
    """
    Reads the chunk queue from the chunks.json file

    :param temp: the temp directory
    :return: the chunk queue
    """
    with open(temp / 'chunks.json', 'r') as file:
        chunk_dicts = json.load(file)
    return [Chunk.create_from_dict(cd, temp) for cd in chunk_dicts]


def load_or_gen_chunk_queue(args: Args, resuming: bool, split_locations: List[int]) -> List[Chunk]:
    """
    If resuming, loads the chunk queue and removes already done chunks or
    creates a chunk queue and saves it for resuming later.

    :param args: the Args
    :param resuming: if we are resuming
    :param split_locations: a list of frames to split on
    :return: A chunk queue (list of chunks)
    """
    # if resuming, read chunks from file and remove those already done
    if resuming:
        chunk_queue = read_chunk_queue(args.temp)
        done_chunk_names = read_done_data(args.temp)['done'].keys()
        chunk_queue = [c for c in chunk_queue if c.name not in done_chunk_names]
        return chunk_queue

    # create and save
    chunk_queue = create_encoding_queue(args, split_locations)
    save_chunk_queue(args.temp, chunk_queue)

    return chunk_queue


def create_encoding_queue(args: Args, split_locations: List[int]) -> List[Chunk]:
    """
    Creates a list of chunks using the cli option specified

    :param args: Args
    :param split_locations: a list of frames to split on
    :return: A list of chunks
    """
    chunk_queue = create_video_queue_segment(args, split_locations)

    # Sort largest first so chunks that take a long time to encode start first
    chunk_queue.sort(key=lambda c: c.size, reverse=True)
    return chunk_queue


def create_video_queue_segment(args: Args, split_locations: List[int]) -> List[Chunk]:
    """
    Create a list of chunks using segmented files

    :param args: Args
    :param split_locations: a list of frames to split on
    :return: A list of chunks
    """

    # segment into separate files
    segment(args.input, args.temp, split_locations)

    # get the names of all the split files
    source_path = args.temp / 'split'
    queue_files = [x for x in source_path.iterdir() if x.suffix == '.mkv']
    queue_files.sort(key=lambda p: p.stem)

    if len(queue_files) == 0:
        er = 'Error: No files found in temp/split, probably splitting not working'
        print(er)
        log(er)
        terminate()

    chunk_queue = [create_chunk_from_segment(args, index, file) for index, file in enumerate(queue_files)]

    return chunk_queue


def create_chunk_from_segment(args: Args, index: int, file: Path) -> Chunk:
    """
    Creates a Chunk object from a segment file generated by ffmpeg

    :param args: the Args
    :param index: the index of the chunk
    :param file: the segmented file
    :return: A Chunk
    """
    ffmpeg_gen_cmd = f'ffmpeg -y -hide_banner -loglevel error -i {file.as_posix()} {args.pix_format} -bufsize 50000K -f yuv4mpegpipe -'
    file_size = file.stat().st_size
    frames = frame_probe(file)
    extension = get_file_extension_for_encoder(args.encoder)

    chunk = Chunk(args.temp, index, ffmpeg_gen_cmd, extension, file_size, frames)
    chunk.generate_pass_cmds(args)

    return chunk