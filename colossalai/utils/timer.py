#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import time
from typing import Tuple
from .cuda import synchronize


class Timer:
    """A timer object which helps to log the execution times, and provides different tools to assess the times.
    """

    def __init__(self):
        self._started = False
        self._start_time = time.time()
        self._elapsed = 0
        self._history = []

    @property
    def has_history(self):
        return len(self._history) != 0

    @property
    def current_time(self) -> float:
        synchronize()
        return time.time()

    def start(self):
        """Fisrtly synchronize cuda, reset the clock and then start the timer.
        """
        self._elapsed = 0
        synchronize()
        self._start_time = time.time()
        self._started = True

    def lap(self):
        """lap time and return elapsed time
        """
        return self.current_time - self._start_time

    def stop(self, keep_in_history: bool = False):
        """Stop the timer and record the start-stop time interval.

        :param keep_in_history: Whether does it record into history each start-stop interval, defaults to False
        :type keep_in_history: bool, optional
        :return: Start-stop interval
        :rtype: int
        """
        synchronize()
        end_time = time.time()
        elapsed = end_time - self._start_time
        if keep_in_history:
            self._history.append(elapsed)
        self._elapsed = elapsed
        self._started = False
        return elapsed

    def get_history_mean(self):
        """Mean of all history start-stop time intervals.

        :return: Mean of time intervals
        :rtype: int
        """
        return sum(self._history) / len(self._history)

    def get_history_sum(self):
        """Add up all the start-stop time intervals.

        :return: Sum of time intervals
        :rtype: int
        """
        return sum(self._history)

    def get_elapsed_time(self):
        """Return the last start-stop time interval.

        .. note:: Use it only when timer is not in progress

        :return: The last time interval
        :rtype: int
        """
        assert not self._started, 'Timer is still in progress'
        return self._elapsed

    def reset(self):
        """Clear up the timer and its history
        """
        self._history = []
        self._started = False
        self._elapsed = 0


class MultiTimer:
    """An object contains multiple timers

    :param on: Whether the timer is enabled. Default is True
    :type on: bool, optional
    """

    def __init__(self, on: bool = True):
        self._on = on
        self._timers = dict()

    def start(self, name: str):
        """Start namely one of the timers

        :param name: Timer's key
        :type name: str
        """
        if self._on:
            if name not in self._timers:
                self._timers[name] = Timer()
            return self._timers[name].start()

    def stop(self, name: str, keep_in_history: bool):
        """Stop namely one of the timers.

        :param name: Timer's key
        :type name: str
        :param keep_in_history: Whether does it record into history each start-stop interval
        :type keep_in_history: bool
        """
        if self._on:
            return self._timers[name].stop(keep_in_history)
        else:
            return None

    def get_timer(self, name):
        """Get timer by its name (from multitimer)

        :param name: Timer's key
        :return: Timer with the name you give correctly
        :rtype: Timer
        """
        return self._timers[name]

    def reset(self, name=None):
        """Reset timers.

        :param name: If name is designated, the named timer will be reset and others will not, defaults to None
        :type name: optional
        """
        if self._on:
            if name is not None:
                self._timers[name].reset()
            else:
                for timer in self._timers:
                    timer.reset()

    def is_on(self):
        return self._on

    def set_status(self, mode: bool):
        self._on = mode

    def __iter__(self) -> Tuple[str, Timer]:
        for name, timer in self._timers.items():
            yield name, timer
