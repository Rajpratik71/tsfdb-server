import dateparser
import re
from datetime import datetime, timedelta
from tsfdb_server_v1.models.error import Error  # noqa: E501


def round_base(x, precision, base):
    return round(base * round(float(x)/base), precision)


def error(code, error_msg, log):
    log.error(error_msg)
    return Error(code, error_msg)


def metric_to_dict(metric):
    return {
        metric: {
            "id": metric,
            "name": metric,
            "column": metric,
            "measurement": metric,
            "max_value": None,
            "min_value": None,
            "priority": 0,
            "unit": "",
        }
    }


def parse_start_stop_params(start, stop):
    """Helper method which parses the start/stop params
       from relative values(sec,min,hour, etc..) to datetime
       and returns them in an array.
    """

    #  set start/stop params if they do not exist
    if not start:
        start = datetime.now() - timedelta(minutes=10)
    else:
        # Convert "y" to "years" since dateparser doesn't support it
        # e.g. -2y => -2years
        start = re.sub("y$", "years", start)
        start = dateparser.parse(start)

    if not stop:
        stop = datetime.now()
    else:
        stop = re.sub("y$", "years", stop)
        stop = dateparser.parse(stop)

    #  round down start and stop time
    start = start.replace(second=0, microsecond=0)
    stop = stop.replace(second=0, microsecond=0)

    return start, stop


def is_regex(string):
    return not bool(re.match("^[a-zA-Z0-9.]+$", string))


def decrement_time(dt, resolution):
    if resolution == "minute":
        return dt - timedelta(minutes=1)
    elif resolution == "hour":
        return dt - timedelta(hours=1)
    return dt - timedelta(days=1)


def generate_metric(tags, measurement):
    del tags["machine_id"], tags["host"]
    metric = measurement
    # First sort the tags in alphanumeric order
    tags = sorted(tags.items())
    # Then promote the tags which have the same name as the measurement
    tags = sorted(tags, key=lambda item: item[0] == measurement, reverse=True)
    for tag, value in tags:
        processed_tag = tag.replace(measurement, '')
        processed_value = value.replace(measurement, '')
        # Ignore the tag if it is empty
        if processed_tag:
            metric += (".%s" % processed_tag)
        # Ignore the value if it is empty
        if processed_value and processed_tag:
            metric += ("-%s" % processed_value)
        # Accomodate for the possibility
        # that there is a value with an empty tag
        elif processed_value:
            metric += (".%s" % processed_value)

    metric = metric.replace('/', '-')
    metric = metric.replace('.-', '.')
    metric = re.sub(r'\.+', ".", metric)
    return metric
