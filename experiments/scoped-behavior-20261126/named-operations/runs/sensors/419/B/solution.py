def sensor_values(readings):
    result = {}
    for sensor, value in readings:
        if sensor in result and result[sensor] != value:
            continue
        result[sensor] = value
    return result
