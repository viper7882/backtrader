import datetime

from time import time as timer

# Refer to https://docs.python.org/3/library/datetime.html#strftime-and-strptime-format-codes
DEFAULT_DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT_WITH_MS_PRECISION = "%H:%M:%S.%f"
DATE_TIME_FORMAT_WITH_MS_PRECISION = DEFAULT_DATE_FORMAT + " " + TIME_FORMAT_WITH_MS_PRECISION

def print_timestamp_checkpoint(function, lineno, comment="Checkpoint timestamp", start=None):
    # Convert datetime to string
    timestamp_str = get_strftime(datetime.datetime.now(), DATE_TIME_FORMAT_WITH_MS_PRECISION)
    if start:
        minutes, seconds, milliseconds = get_ms_time_diff(start)
        print("{} Line: {}: {}: {}, Delta: {}m:{}s.{}ms".format(
            function, lineno, comment, timestamp_str, minutes, seconds, milliseconds,
        ))
    else:
        print("{} Line: {}: {}: {}".format(
            function, lineno, comment, timestamp_str,
        ))


def get_ms_time_diff(start):
    prog_time_diff = timer() - start
    _, rem = divmod(prog_time_diff, 3600)
    minutes, seconds = divmod(rem, 60)
    minutes = int(minutes)
    fraction_of_seconds = seconds - int(seconds)
    seconds = int(seconds)
    milliseconds = fraction_of_seconds * 1000
    milliseconds = int(milliseconds)
    return minutes, seconds, milliseconds


def get_strftime(dt, date_format):
    # Convert datetime to string
    return str(dt.strftime(date_format))
