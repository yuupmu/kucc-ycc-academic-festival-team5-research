def sensor_values(readings):
    result = {}
    for sensor, value in readings:
        if sensor in result and result[sensor] != value:
            result[sensor] = value
        result[sensor] = value
    return result
