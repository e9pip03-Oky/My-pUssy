import os
import re
import subprocess

import Reply


def normalize_time_part(part_str):
    part_str = part_str.strip()
    if not part_str:
        return []
    return part_str.split(":")


def calculate_seconds(parts):
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return None

    if len(parts) == 1:
        return parts[0]

    if len(parts) == 2:
        return parts[0] * 60 + parts[1]

    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]

    return None


def parse_time_part(time_str):
    time_str = time_str.strip()

    if not time_str:
        return None

    if "." in time_str:
        dot_parts = time_str.split(".")

        if len(dot_parts) != 2:
            return None

        try:
            hours = int(dot_parts[0])
        except ValueError:
            return None

        minute_second = dot_parts[1]

        if ":" in minute_second:
            parts = minute_second.split(":")

            if len(parts) != 2:
                return None

            try:
                minutes = int(parts[0])
                seconds = int(parts[1])
            except ValueError:
                return None

            return hours * 3600 + minutes * 60 + seconds

        try:
            minutes = int(minute_second)
        except ValueError:
            return None

        return hours * 3600 + minutes * 60

    parts = normalize_time_part(time_str)

    return calculate_seconds(parts)


def parse_asymmetric_times(start_raw, end_raw):
    start_raw = start_raw.strip()
    end_raw = end_raw.strip()

    if not start_raw or not end_raw:
        return "invalid_format", None, None

    start_sec = parse_time_part(start_raw)
    end_sec = parse_time_part(end_raw)

    if start_sec is None or end_sec is None:
        return "invalid_format", None, None

    if start_sec >= end_sec:
        return "invalid_range", start_sec, end_sec

    return "valid", start_sec, end_sec


def parse_trim_input(user_text):
    cleaned_text = user_text.strip()

    pattern = r"^(.*?)(?:\s+[/|-]\s+|\s+)(.*?)$"
    match = re.match(pattern, cleaned_text)

    if not match:
        return "invalid_format", None, None

    start_raw = match.group(1).strip()
    end_raw = match.group(2).strip()

    return parse_asymmetric_times(start_raw, end_raw)


def trim_audio_direct(input_path, start_sec, end_sec, output_path):
    duration_sec = end_sec - start_sec

    if duration_sec <= 0:
        return False

    command = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start_sec),
        "-i",
        input_path,
        "-t",
        str(duration_sec),
        "-c",
        "copy",
        output_path,
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    return result.returncode == 0


def is_edit_trigger(message_text):
    if not message_text:
        return False

    return Reply.EDIT_TRIGGER_TEXT in message_text.strip()


def process_audio_trim(input_path, start_sec, end_sec):
    base_name, ext = os.path.splitext(input_path)
    output_path = f"{base_name}_cut{ext}"

    success = trim_audio_direct(
        input_path,
        start_sec,
        end_sec,
        output_path,
    )

    if success and os.path.exists(output_path):
        return output_path

    return None