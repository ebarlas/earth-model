from skyfield import api
from skyfield import almanac

EVENT_VERNAL_EQUINOX = 0
EVENT_SUMMER_SOLSTICE = 1
EVENT_AUTUMNAL_EQUINOX = 2
EVENT_WINTER_SOLSTICE = 3

timescale = api.load.timescale()
ephemeris = api.load('de421.bsp')
greenwich = api.Topos('51.48 N', '0 W')


class Event:
    """
    Class composed of an event value and an event label string.
    """

    def __init__(self, value, label):
        self.value = value
        self.label = label

    def __repr__(self):
        return self.label


class EventTime:
    """
    Class composed of an Event object and a Skyfield Time object.
    """

    def __init__(self, event, time):
        self.event = event
        self.time = time

    def __repr__(self):
        return '{} at {}'.format(self.event, self.time.utc_strftime('%Y-%m-%d %H:%M:%S'))


class EarthModel:
    """
    Class composed of earth orbit degrees [0-180] and earth rotation degrees [0-360].
    These values are intended to serve as input to a physical model with the following configuration.
    The earth orbit reference point is Northern Hemisphere winter solstice, when the north pole has
    its maximum tilt away from the sun. The earth rotation reference point is Greenwich. Taken together, the
    physical model base position is solar noon in Greenwich at Northern Hemisphere winter solstice.
    As a result, the physical model ought to apply these values as follows.
    Rotate lower motor with fixed earth on its axial tilt by orbit degrees.
    Rotate upper motor that spins the earth on its axis by rotation degrees minus orbit degrees.
    Consider the following examples.
    Given orbit degrees of 0 and rotation degrees of 0, earth remains at solar noon in Greenwich on winter solstice.
    Given orbit degrees of 90 and rotation degrees of 270, earth is at solar noon in Greenwich on spring equinox.
    Given orbit degrees of 180 and rotation degree of 0, earth is at nadir in Greenwich on summer solstice.
    Given orbit degrees of 180 and rotation degree of 90, earth is at sunrise in Greenwich on summer solstice.
    """

    def __init__(self, orbit_degrees, rotation_degrees):
        self.orbit_degrees = orbit_degrees
        self.rotation_degrees = rotation_degrees


def season_event_times(start, end):
    """
    Computes season event times between start and end.
    Returns list of EventTime objects.
    """
    t, y = almanac.find_discrete(start, end, almanac.seasons(ephemeris))
    return [EventTime(Event(event, almanac.SEASON_EVENTS[event]), time) for time, event in zip(t, y)]


def rise_set_event_times(start, end):
    """
    Computes sunrise and sunset times between start and end.
    Returns list of EventTime objects.
    """
    t, y = almanac.find_discrete(start, end, almanac.sunrise_sunset(ephemeris, greenwich))
    return [EventTime(Event(rise, 'Sunrise' if rise else 'Sunset'), time) for time, rise in zip(t, y)]


def noon_nadir_event_times(start, end):
    """
    Computes solar noon and nadir event times as midpoints between sunrise and sunset events.
    Returns list of EventTime objects.
    """
    result = []
    rs_event_times = rise_set_event_times(start, end)
    for x, y in zip(rs_event_times, rs_event_times[1:]):
        delta = y.time - x.time
        midpoint = timescale.tt_jd(x.time.tt + delta / 2)
        result.append(EventTime(Event(x.event.value, 'Solor noon' if x.event.value else 'Nadir'), midpoint))
    return result


def find_surrounding_events(events, time):
    """
    Locates the event times that straddle the input time.
    Returns tuple of EventTime objects.
    """
    for x, y in zip(events, events[1:]):
        if x.time.tt < time.tt < y.time.tt:
            return x, y


def surrounding_events(time, julian_time, events_func):
    """
    Locates the event times that straddle the input time.
    Returns tuple of objects provided by the input function.
    """
    t0 = timescale.tt_jd(time.tt - julian_time)
    t1 = timescale.tt_jd(time.tt + julian_time)
    sets = events_func(t0, t1)
    return find_surrounding_events(sets, time)


def relative_to_absolute_orbit_degrees(season, degrees):
    """
    Convert relative seasonal degrees to absolute degrees on specialized scale.
    Scale goes from 0-180 between winter solstice and summer solstice
    and back down from 180-0 between summer solstice and winter solstice.
    Equinoxes are both 90.
    """
    if season == EVENT_SUMMER_SOLSTICE:
        return 180 - degrees
    if season == EVENT_AUTUMNAL_EQUINOX:
        return 90 - degrees
    if season == EVENT_WINTER_SOLSTICE:
        return degrees
    return 90 + degrees


def position_as_percent(events, time):
    # total time separating pair of events
    range = events[1].time - events[0].time

    # position within range [0, range]
    position = time - events[0].time

    # convert position to fractional value [0.0, 1.0]
    return position / range


def orbit_degrees_from_winter_solstice(time):
    """
    Computes earth orbit degrees of the input time relative to winter solstice on specialized scale.
    Scale goes from 0-180 between winter solstice and summer solstice
    and back down from 180-0 between summer solstice and winter solstice.
    Equinoxes are both 90.
    """
    # determine pair of straddling season events
    evts = surrounding_events(time, 100, season_event_times)

    # convert fractional value to seasonal degrees offset [0, 90]
    degrees = position_as_percent(evts, time) * 90

    # adjust for the 180-degree spectrum, starting from winter solstice
    return relative_to_absolute_orbit_degrees(evts[0].event.value, degrees)


def rotation_degrees_from_solar_noon(time):
    """
    Computes earth rotation degrees of the input time relative to last solar noon.
    Scale goes from 0-360 between solar noon on the previous day and the next day.
    """
    # determine pair of solar noon/nadir events
    evts = surrounding_events(time, 1, noon_nadir_event_times)

    # convert fractional value to degrees offset [0, 180]
    degrees = position_as_percent(evts, time) * 180

    # add 180 degrees is prior event is nadir
    return degrees if evts[0].event.value else degrees + 180


def earth_model(time):
    orbit_degrees = orbit_degrees_from_winter_solstice(time)
    rotation_degrees = rotation_degrees_from_solar_noon(time)
    rotation_degrees = rotation_degrees - orbit_degrees
    if rotation_degrees < 0:
        rotation_degrees = rotation_degrees + 360
    return EarthModel(orbit_degrees, rotation_degrees)


def earth_model_now():
    return earth_model(timescale.now())


def main():
    now = timescale.now()
    em = earth_model(now)
    d = {
        'time': now.utc_strftime('%Y-%m-%d %H:%M:%S '),
        'orbit': em.orbit_degrees,
        'rotation': em.rotation_degrees,
        'effective': (em.rotation_degrees + em.orbit_degrees) % 360.0
    }
    print(d)


if __name__ == '__main__':
    main()
