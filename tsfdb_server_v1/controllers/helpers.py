import fdb
import fdb.tuple
from datetime import datetime, timedelta
import dateparser
import re
import numpy as np
import logging
import os

from tsfdb_server_v1.models.error import Error  # noqa: E501
from line_protocol_parser import parse_line

fdb.api_version(620)

log = logging.getLogger(__name__)

aggregate_minute = os.getenv('AGGREGATE_MINUTE', 1)
aggregate_hour = os.getenv('AGGREGATE_HOUR', 1)
aggregate_day = os.getenv('AGGREGATE_DAY', 1)

#aggregate_minute = 1
#aggregate_hour = 2
#aggregate_day = 2


def print_aggregate_options():
    print(("aggregate_minute: %s" % aggregate_minute))
    print(("aggregate_hour: %s" % aggregate_hour))
    print(("aggregate_day: %s" % aggregate_day))


def key_tuple_second(dt, machine, metric):
    return key_tuple_minute(dt, machine, metric) + (dt.second,)


def key_tuple_minute(dt, machine, metric):
    return key_tuple_hour(dt, machine, metric) + (dt.minute,)


def key_tuple_hour(dt, machine, metric):
    return key_tuple_day(dt, machine, metric) + (dt.hour,)


def key_tuple_day(dt, machine, metric):
    return (
        machine,
        metric,
        dt.year,
        dt.month,
        dt.day,
    )


def round_base(x, precision, base):
    return round(base * round(float(x)/base), precision)


def roundX(data, precision=0, base=1):
    if not isinstance(data, dict) or not data:
        return {}
    for metric, datapoints in data.items():
        data[metric] = [
            [round_base(x, precision, base), y]
            for x, y in datapoints
        ]
    return data


def roundY(data, precision=0, base=1):
    if not isinstance(data, dict) or not data:
        return {}
    for metric, datapoints in data.items():
        data[metric] = [
            [x, round_base(y, precision, base)]
            for x, y in datapoints
        ]
    return data


def open_db():
    db = fdb.open()
    db.options.set_transaction_retry_limit(3)
    db.options.set_transaction_timeout(1000)
    return db


def error(code, error_msg):
    log.error(error_msg)
    return Error(code, error_msg)


def start_stop_key_tuples(
    db, time_range_in_hours, monitoring, machine, metric, start, stop
):
    # if time range is less than an hour, we create the keys for getting the
    # datapoints per second
    if time_range_in_hours <= 1:
        # delta compensates for the range function of foundationdb which
        # for start, stop returns keys in [start, stop). We convert it to
        # the range [start, stop]
        delta = timedelta(seconds=1)
        return [
            monitoring.pack(key_tuple_second(start, machine, metric)),
            monitoring.pack(key_tuple_second(
                stop + delta, machine, metric)),
        ]
    # if time range is less than 2 days, we create the keys for getting the
    # summarizeddatapoints per minute
    elif time_range_in_hours <= 48:
        delta = timedelta(minutes=1)
        if monitoring.exists(db, "metric_per_minute"):
            monitoring_sum = monitoring.open(db, ("metric_per_minute",))
        else:
            error_msg = "metric_per_minute directory doesn't exist."
            return error(503, error_msg)
        return [
            monitoring_sum.pack(
                key_tuple_minute(start, machine, metric)
            ),
            monitoring_sum.pack(
                key_tuple_minute(stop + delta, machine, metric)
            ),
        ]
    # if time range is less than 2 months, we create the keys for getting
    # the summarized datapoints per hour
    elif time_range_in_hours <= 1440:
        delta = timedelta(hours=1)
        if monitoring.exists(db, "metric_per_hour"):
            monitoring_sum = monitoring.open(db, ("metric_per_hour",))
        else:
            error_msg = "metric_per_hour directory doesn't exist."
            return error(503, error_msg)
        return [
            monitoring_sum.pack(
                key_tuple_hour(start, machine, metric)
            ),
            monitoring_sum.pack(
                key_tuple_hour(stop + delta, machine, metric)
            ),
        ]
    # if time range is more than 2 months, we create the keys for getting
    # the summarized datapoints per day
    else:
        delta = timedelta(hours=24)
        if monitoring.exists(db, "metric_per_day"):
            monitoring_sum = monitoring.open(db, ("metric_per_day",))
        else:
            error_msg = "metric_per_day directory doesn't exist."
            return error(503, error_msg)
        return [
            monitoring_sum.pack(
                key_tuple_day(start, machine, metric)
            ),
            monitoring_sum.pack(
                key_tuple_day(stop + delta, machine, metric)
            ),
        ]


def tuple_to_timestamp(time_range_in_hours, tuple_key):
    # if time range is less than an hour, we create the timestamp per second
    # The last 6 items of the tuple contain the date up to the second
    # (year, month, day, hour, minute, second)
    if time_range_in_hours <= 1:
        return int(datetime(*tuple_key[-6:]).timestamp())
    # if time range is less than 2 days, we create the timestamp per minute
    # The last 5 items of the tuple contain the date up to the minute
    # (year, month, day, hour, minute)
    if time_range_in_hours <= 48:
        return int(datetime(*tuple_key[-5:]).timestamp())
    # if time range is less than 2 months, we create the timestamp per hour
    # The last 4 items of the tuple contain the date up to the hour
    # (year, month, day, hour)
    if time_range_in_hours <= 1440:
        return int(datetime(*tuple_key[-4:]).timestamp())
    # if time range is more than 2 months, we create the timestamp per day
    # The last 3 items of the tuple contain the date up to the day
    # (year, month, day)
    return int(datetime(*tuple_key[-3:]).timestamp())


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


def tuple_to_datapoint(time_range_in_hours, tuple_value, tuple_key):
    timestamp = tuple_to_timestamp(time_range_in_hours, tuple_key)
    # if the range is less than an hour, we create the appropriate
    # datapoint [value, timestamp]
    if time_range_in_hours <= 1:
        return [tuple_value[0], timestamp]
    # else we need to use the summarized values [sum, count, min, max]
    # and convert them to a datapoint [value, timestamp]
    sum_values = tuple_value[0]
    count = tuple_value[1]
    return [sum_values / count, timestamp]


def is_regex(string):
    return not bool(re.match("^[a-zA-Z0-9.]+$", string))


@fdb.transactional
def find_metrics_from_db(tr, available_metrics, resource):
    metrics = {}
    for k, v in tr[available_metrics[resource].range()]:
        data_tuple = available_metrics[resource].unpack(k)
        metrics.update(metric_to_dict(data_tuple[1]))

    return metrics


def find_metrics(resource):
    try:
        db = open_db()
        if fdb.directory.exists(db, ('monitoring', 'available_metrics')):
            available_metrics = fdb.directory.open(
                db, ('monitoring', 'available_metrics'))
        else:
            error_msg = "Monitoring directory doesn't exist."
            return error(503, error_msg)

        return find_metrics_from_db(db, available_metrics, resource)
    except fdb.FDBError as err:
        return error(503, str(err.description, 'utf-8'))


@fdb.transactional
def find_resources_from_db(tr, monitoring, regex_resources):
    resources = []
    for k, v in tr[monitoring["available_resources"].range()]:
        candidate = monitoring["available_resources"].unpack(k)
        if re.match("^%s$" % regex_resources, candidate):
            resources.append(k)

    return resources


def find_resources(regex_resources):
    try:
        db = open_db()
        if fdb.directory.exists(db, "monitoring"):
            monitoring = fdb.directory.open(db, "monitoring")
            return find_resources_from_db(db, monitoring, regex_resources)

        else:
            error_msg = "Monitoring directory doesn't exist."
            return error(503, error_msg)
    except fdb.FDBError as err:
        return error(503, str(err.description, 'utf-8'))


@fdb.transactional
def find_datapoints_from_db(tr, start, stop, time_range_in_hours):
    datapoints = []
    for k, v in tr[start:stop]:

        tuple_key = list(fdb.tuple.unpack(k))
        tuple_value = list(fdb.tuple.unpack(v))

        datapoints.append(
            tuple_to_datapoint(
                time_range_in_hours, tuple_value, tuple_key
            )
        )
    return datapoints


def find_datapoints(resource, start, stop, metrics):
    try:
        db = open_db()
        data = {}
        # Open the monitoring directory if it exists
        if fdb.directory.exists(db, "monitoring"):
            monitoring = fdb.directory.open(db, ("monitoring",))
        else:
            error_msg = "Monitoring directory doesn't exist."
            return error(503, error_msg)

        start, stop = parse_start_stop_params(start, stop)
        time_range = stop - start
        time_range_in_hours = round(time_range.total_seconds() / 3600, 2)

        for metric in metrics:
            tuples = start_stop_key_tuples(
                db, time_range_in_hours, monitoring,
                resource, metric, start, stop
            )

            if isinstance(tuples, Error):
                return tuples

            key_timestamp_start, key_timestamp_stop = tuples

            datapoints = find_datapoints_from_db(
                db, key_timestamp_start, key_timestamp_stop,
                time_range_in_hours)

            data.update({("%s.%s" % (resource, metric)): datapoints})

        return data
    except fdb.FDBError as err:
        return error(503, str(err.description, 'utf-8'))


def fetch(resources_and_metrics, start="", stop="", step=""):
    # We take for granted that all metrics start with the id and that
    # it ends on the first occurence of a dot, e.g id.system.load1
    data = {}
    resources, metrics = resources_and_metrics.split(".", 1)
    if is_regex(resources):
        # At the moment we ignore the cases where the resource is a regex
        # resources = find_resources(resources)
        return {}
    else:
        resources = [resources]

    for resource in resources:
        if is_regex(metrics):
            regex_metric = metrics
            metrics = []
            all_metrics = find_metrics(resource)
            if isinstance(all_metrics, Error):
                return all_metrics
            if regex_metric == "*":
                metrics = [candidate for candidate in all_metrics]
            else:
                for candidate in all_metrics:
                    if re.match("^%s$" % regex_metric, candidate):
                        metrics.append(candidate)
            if len(metrics) == 0:
                error_msg = (
                    "No metrics for regex: \"%s\" where found" % regex_metric
                )
                return error(400, error_msg)
        else:
            metrics = [metrics]
        current_data = find_datapoints(resource, start, stop, metrics)
        if isinstance(current_data, Error):
            return current_data
        data.update(current_data)

    return data


def deriv(data):
    if not isinstance(data, dict) or not data:
        return {}
    for metric, datapoints in data.items():
        if not datapoints or len(datapoints) < 2:
            data[metric] = []
            continue
        values = np.asarray([value for value, _ in datapoints])
        timestamps = np.asarray([timestamp for _, timestamp in datapoints])
        values_deriv = np.gradient(values, timestamps)
        data[metric] = [
            [value_deriv.tolist(), timestamp.tolist()]
            for value_deriv, timestamp in zip(
                np.nditer(values_deriv), np.nditer(timestamps)
            )
        ]
    return data


def write_tuple(tr, monitoring, key, value):
    if not tr[monitoring.pack(key)].present():
        tr[monitoring.pack(key)] = fdb.tuple.pack((value,))
        return True
    saved_value = fdb.tuple.unpack(tr[monitoring.pack(key)])[0]
    if saved_value != value:
        log.error("key: %s already exists with a different value" % str(key))
    else:
        log.warning("key: %s already exists with the same value" % str(key))
    return False


def update_metric(tr, available_metrics, metric):
    if not tr[available_metrics.pack(metric)].present():
        tr[available_metrics.pack(metric)] = fdb.tuple.pack(("",))


def time_aggregate_tuple(machine, metric, dt, resolution):
    if resolution == "minute":
        return key_tuple_minute(dt, machine, metric)
    elif resolution == "hour":
        return key_tuple_hour(dt, machine, metric)
    return key_tuple_day(dt, machine, metric)


def decrement_time(dt, resolution):
    if resolution == "minute":
        return dt - timedelta(minutes=1)
    elif resolution == "hour":
        return dt - timedelta(hours=1)
    return dt - timedelta(days=1)


def apply_time_aggregation(tr, monitoring, machine,
                           metric, dt, value, resolutions, resolutions_dirs,
                           resolutions_options):
    new_aggregation = False
    last_tuple = None
    last_dt = None
    for resolution in resolutions:
        if resolutions_options[resolution] == 0 or \
                (resolutions_options[resolution] == 2 and
                 not new_aggregation):
            continue
        if resolutions_options[resolution] == 2:
            sum_dt = last_dt
        else:
            sum_dt = dt
        monitoring_time = resolutions_dirs[resolution]
        sum_tuple = tr[monitoring_time.pack(
            time_aggregate_tuple(machine, metric, sum_dt, resolution))]
        if sum_tuple.present():
            sum_tuple = fdb.tuple.unpack(sum_tuple)
            sum_value, count, min_value, max_value = sum_tuple
            new_aggregation = False
            if resolutions_options[resolution] == 2:
                last_tuple = fdb.tuple.unpack(last_tuple)
                last_sum_value, last_count, last_min_value, last_max_value \
                    = last_tuple
                sum_value += last_sum_value
                count += last_count
                min_value = min(last_min_value, min_value)
                max_value = max(last_max_value, max_value)
            else:
                sum_value += value
                count += 1
                min_value = min(value, min_value)
                max_value = max(value, max_value)
        else:
            if resolutions_options[resolution] == 2:
                last_tuple = fdb.tuple.unpack(last_tuple)
                sum_value, count, min_value, max_value \
                    = last_tuple
            else:
                sum_value, count, min_value, max_value = value, 1, value, value
            last_dt = decrement_time(dt, resolution)
            last_tuple = tr[monitoring_time.pack(
                time_aggregate_tuple(machine, metric, last_dt, resolution))]
            new_aggregation = last_tuple.present()
        tr[monitoring_time.pack(
            time_aggregate_tuple(machine, metric, sum_dt, resolution))] \
            = fdb.tuple.pack((sum_value, count, min_value, max_value))


@fdb.transactional
def write_lines(tr, monitoring, available_metrics, lines):
    resolutions = ("minute", "hour", "day")
    resolutions_dirs = {}
    resolutions_options = {"minute": aggregate_minute,
                           "hour": aggregate_hour, "day": aggregate_day}
    # log.error(resolutions_options)
    for resolution in resolutions:
        resolutions_dirs[resolution] = monitoring.create_or_open(
            tr, ('metric_per_' + resolution,))
    metrics = {}
    for line in lines:
        dict_line = parse_line(line)
        machine = dict_line["tags"]["machine_id"]
        if not metrics.get(machine):
            machine_metrics = find_metrics_from_db(
                tr, available_metrics, machine)
            metrics[machine] = {m for m in machine_metrics.keys()}
        metric = generate_metric(dict_line["tags"], dict_line["measurement"])
        dt = datetime.fromtimestamp(int(str(dict_line["time"])[:10]))
        for field, value in dict_line["fields"].items():
            machine_metric = "%s.%s" % (metric, field)
            if write_tuple(tr, monitoring, key_tuple_second(
                    dt, machine, machine_metric), value):
                if not (machine_metric in metrics.get(machine)):
                    update_metric(tr, available_metrics, (machine, type(
                        value).__name__, machine_metric))
                apply_time_aggregation(tr, monitoring, machine,
                                       machine_metric, dt, value,
                                       resolutions, resolutions_dirs,
                                       resolutions_options)


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


def write(data):
    try:
        db = open_db()
        monitoring = fdb.directory.create_or_open(db, ('monitoring',))
        available_metrics = monitoring.create_or_open(
            db, ('available_metrics',))
        # Create a list of lines
        data = data.split('\n')
        # Get rid of all empty lines
        data = [line for line in data if line != ""]
        write_lines(db, monitoring, available_metrics, data)
    except fdb.FDBError as err:
        return error(503, str(err.description, 'utf-8'))
