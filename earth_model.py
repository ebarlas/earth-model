import sys
import time
import atexit
import hall_effect
import earth
import logging
import logging.handlers
from skyfield import api
from adafruit_motorkit import MotorKit
from adafruit_motor import stepper

logger = logging.getLogger(__name__)

ts = api.load.timescale()

STEPS_PER_REV = 200
DEGREES_PER_STEP = 360.0 / STEPS_PER_REV

kit = MotorKit()
steppers = [kit.stepper1, kit.stepper2]
sensors = [hall_effect.Sensor(27), hall_effect.Sensor(17)]


# recommended for auto-disabling motors on shutdown!
def turn_off_motors():
    for stepper in steppers:
        stepper.release()


atexit.register(turn_off_motors)


def init_logger(file_name):
    formatter = logging.Formatter('[%(asctime)s] <%(threadName)s> %(levelname)s - %(message)s')

    handler = logging.handlers.RotatingFileHandler(file_name, maxBytes=100000, backupCount=3)
    handler.setFormatter(formatter)

    log = logging.getLogger('')
    log.setLevel(logging.INFO)
    log.addHandler(handler)


def take_steps(forward, motor, steps, sleep):
    for i in range(steps):
        motor.onestep(direction=stepper.FORWARD if forward else stepper.BACKWARD)
        time.sleep(sleep)


def step_while_over_sensor(step_forward, motor, sensor, max_steps, sleep):
    steps = 0
    found = False
    while not found and steps < max_steps:
        if sensor.sensing():
            motor.onestep(direction=stepper.FORWARD if step_forward else stepper.BACKWARD)
            time.sleep(sleep)
            steps = steps + 1
        else:
            found = True
    return found, steps


def step_until_over_sensor(step_forward, motor, sensor, max_steps, sleep):
    steps = 0
    found = False
    while not found and steps < max_steps:
        if sensor.sensing():
            found = True
        else:
            motor.onestep(direction=stepper.FORWARD if step_forward else stepper.BACKWARD)
            time.sleep(sleep)
            steps = steps + 1
    return found, steps


def scan(forward, motor, sensor, max_scan_steps, max_sensor_steps, sleep):
    logger.info('scanning back off of sensor')

    found, steps = step_while_over_sensor(not forward, motor, sensor, max_sensor_steps, sleep)
    if not found:
        logger.info('scan back off of sensor failed')
        return False

    logger.info('scanned {} steps back off of sensor'.format(steps))
    logger.info('scanning forward to sensor')

    found, steps = step_until_over_sensor(forward, motor, sensor, max_scan_steps, sleep)
    if not found:
        logger.info('scan forward to sensor failed')
        return False

    logger.info('scanned {} steps forward to sensor'.format(steps))
    logger.info('scanning forward off of sensor')

    found, steps = step_while_over_sensor(forward, motor, sensor, max_sensor_steps, sleep)
    if not found:
        logger.info('scan forward off of sensor failed')
        return False

    logger.info('scanned {} steps forward off of sensor'.format(steps))
    logger.info('scanning back to midpoint')

    take_steps(not forward, motor, int(steps / 2), sleep)

    return True


def validate_orbit_degrees(degrees):
    if not 0 <= degrees <= 180:
        logger.error('unexpected orbit degrees: {}'.format(degrees))
        sys.exit(1)


def validate_rotation_degrees(degrees):
    if not 0 <= degrees <= 360:
        logger.error('unexpected rotation degrees: {}'.format(degrees))
        sys.exit(1)


def steps_and_floor(degrees):
    steps = degrees / DEGREES_PER_STEP
    floor = int(steps)
    return steps, floor


def print_earth_model(em, orbit_steps, rotation_steps):
    logger.info('orbit[degrees={:0.4f}, steps={:0.4f}], rotation[degrees={:0.4f}, steps={:0.4f}]'.format(
        em.orbit_degrees,
        orbit_steps,
        em.rotation_degrees,
        rotation_steps))


def main():
    init_logger('earth_model.log')

    sleep = 0.05

    # scan to base position on lower earth orbit motor
    # when the magnet is directly over the hall effect sensor, it's winter solstice in the northern hemisphere
    # that is the northern hemisphere is pointing away from the sun
    scan(False, steppers[0], sensors[0], 100, 50, sleep)

    # scan to base position on earth rotation motor
    # the prime meridian is aligned with the magnet
    # when the magnet is directly over the hall effect sensor, the prime meridian (0 degrees longitude) is also
    # directly over the sensor
    scan(True, steppers[1], sensors[1], 200, 50, sleep)

    # compute earth-orbit degrees and earth-rotation degrees
    em = earth.earth_model_now()
    validate_orbit_degrees(em.orbit_degrees)
    validate_rotation_degrees(em.rotation_degrees)

    orbit_steps, orbit_steps_floor = steps_and_floor(em.orbit_degrees)
    rotation_steps, rotation_steps_floor = steps_and_floor(em.rotation_degrees)
    print_earth_model(em, orbit_steps, rotation_steps)

    take_steps(True, steppers[0], orbit_steps_floor, sleep)
    take_steps(True, steppers[1], rotation_steps_floor, sleep)

    while True:
        em = earth.earth_model_now()
        validate_orbit_degrees(em.orbit_degrees)
        validate_rotation_degrees(em.rotation_degrees)

        next_orbit_steps, next_orbit_steps_floor = steps_and_floor(em.orbit_degrees)
        next_rotation_steps, next_rotation_steps_floor = steps_and_floor(em.rotation_degrees)
        print_earth_model(em, next_orbit_steps, next_rotation_steps)

        if next_orbit_steps_floor != orbit_steps_floor:
            steps = abs(next_orbit_steps_floor - orbit_steps_floor)
            take_steps(next_orbit_steps_floor > orbit_steps_floor, steppers[0], steps, sleep)
            orbit_steps_floor = next_orbit_steps_floor

        if next_rotation_steps_floor != rotation_steps_floor:
            steps = next_rotation_steps_floor - rotation_steps_floor
            # for example, jump from 199 to 0 should result in value 1 (0 - 199) + 200
            if steps < 0:
                steps = STEPS_PER_REV + steps
            take_steps(True, steppers[1], steps, sleep)
            rotation_steps_floor = next_rotation_steps_floor

        time.sleep(60)


if __name__ == '__main__':
    main()
