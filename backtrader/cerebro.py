#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
###############################################################################
#
# Copyright (C) 2015-2020 Daniel Rodriguez
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import collections
import itertools
import multiprocessing
import gc

import backtrader as bt
from .utils.py3 import (map, range, zip, with_metaclass, string_types,
                        integer_types)

from . import linebuffer
from . import indicator
from .brokers_or_exchanges import BackBroker
from .metabase import MetaParams
from . import observers
from .writer import WriterFile
from .utils import OrderedDict, tzparse, num2date, date2num
from .strategy import Strategy, SignalStrategy
from .tradingcal import (TradingCalendarBase, TradingCalendar,
                         PandasMarketCalendar)
from .timer import Timer
from copy import deepcopy

# Defined here to make it pickable. Ideally it could be defined inside Cerebro


class OptReturn(object):
    def __init__(self, params, **kwargs):
        self.p = self.params = params
        for k, v in kwargs.items():
            setattr(self, k, v)


class Cerebro(with_metaclass(MetaParams, object)):
    '''Params:

      - ``preload`` (default: ``True``)

        Whether to preload the different ``data feeds`` passed to cerebro for
        the Strategies

      - ``runonce`` (default: ``True``)

        Run ``Indicators`` in vectorized mode to speed up the entire system.
        Strategies and Observers will always be run on an event based basis

      - ``live`` (default: ``False``)

        If no data has reported itself as *live* (via the data's ``is_live``
        method but the end user still want to run in ``live`` mode, this
        parameter can be set to true

        This will simultaneously deactivate ``preload`` and ``runonce``. It
        will have no effect on memory saving schemes.

        Run ``Indicators`` in vectorized mode to speed up the entire system.
        Strategies and Observers will always be run on an event based basis

      - ``maxcpus`` (default: None -> all available cores)

         How many cores to use simultaneously for optimization

      - ``stdstats`` (default: ``True``)

        If True default Observers will be added: Broker_or_Exchange (Cash and Value),
        Trades and Buy_and_Sell

      - ``oldbuysell`` (default: ``False``)

        If ``stdstats`` is ``True`` and observers are getting automatically
        added, this switch controls the main behavior of the ``Buy_and_Sell``
        observer

        - ``False``: use the modern behavior in which the buy / sell signals
          are plotted below / above the low / high prices respectively to avoid
          cluttering the plot

        - ``True``: use the deprecated behavior in which the buy / sell signals
          are plotted where the average price of the order executions for the
          given moment in time is. This will of course be on top of an OHLC bar
          or on a Line on Cloe bar, difficulting the recognition of the plot.

      - ``oldtrades`` (default: ``False``)

        If ``stdstats`` is ``True`` and observers are getting automatically
        added, this switch controls the main behavior of the ``Trades``
        observer

        - ``False``: use the modern behavior in which trades for all datas are
          plotted with different markers

        - ``True``: use the old Trades observer which plots the trades with the
          same markers, differentiating only if they are positive or negative

      - ``exactbars`` (default: ``False``)

        With the default value each and every value stored in a line is kept in
        memory

        Possible values:
          - ``True`` or ``1``: all "lines" objects reduce memory usage to the
            automatically calculated minimum period.

            If a Simple Moving Average has a period of 30, the underlying data
            will have always a running buffer of 30 bars to allow the
            calculation of the Simple Moving Average

            - This setting will deactivate ``preload`` and ``runonce``
            - Using this setting also deactivates **plotting**

          - ``-1``: datafreeds and indicators/operations at strategy level will
            keep all data in memory.

            For example: a ``RSI`` internally uses the indicator ``UpDay`` to
            make calculations. This subindicator will not keep all data in
            memory

            - This allows to keep ``plotting`` and ``preloading`` active.

            - ``runonce`` will be deactivated

          - ``-2``: data feeds and indicators kept as attributes of the
            strategy will keep all points in memory.

            For example: a ``RSI`` internally uses the indicator ``UpDay`` to
            make calculations. This subindicator will not keep all data in
            memory

            If in the ``__init__`` something like
            ``a = self.datafeed.close - self.datafeed.high`` is defined, then ``a``
            will not keep all data in memory

            - This allows to keep ``plotting`` and ``preloading`` active.

            - ``runonce`` will be deactivated

      - ``objcache`` (default: ``False``)

        Experimental option to implement a cache of lines objects and reduce
        the amount of them. Example from UltimateOscillator::

          bp = self.datafeed.close - TrueLow(self.datafeed)
          tr = TrueRange(self.datafeed)  # -> creates another TrueLow(self.datafeed)

        If this is ``True`` the 2nd ``TrueLow(self.datafeed)`` inside ``TrueRange``
        matches the signature of the one in the ``bp`` calculation. It will be
        reused.

        Corner cases may happen in which this drives a line object off its
        minimum period and breaks things and it is therefore disabled.

      - ``writer`` (default: ``False``)

        If set to ``True`` a default WriterFile will be created which will
        print to stdout. It will be added to the strategy (in addition to any
        other writers added by the user code)

      - ``tradehistory`` (default: ``False``)

        If set to ``True``, it will activate update event logging in each trade
        for all strategies. This can also be accomplished on a per strategy
        basis with the strategy method ``set_tradehistory``

      - ``optdatas`` (default: ``True``)

        If ``True`` and optimizing (and the system can ``preload`` and use
        ``runonce``, data preloading will be done only once in the main process
        to save time and resources.

        The tests show an approximate ``20%`` speed-up moving from a sample
        execution in ``83`` seconds to ``66``

      - ``optreturn`` (default: ``True``)

        If ``True`` the optimization results will not be full ``Strategy``
        objects (and all *datas*, *indicators*, *observers* ...) but and object
        with the following attributes (same as in ``Strategy``):

          - ``params`` (or ``p``) the strategy had for the execution
          - ``analyzers`` the strategy has executed

        In most occassions, only the *analyzers* and with which *params* are
        the things needed to evaluate a the performance of a strategy. If
        detailed analysis of the generated values for (for example)
        *indicators* is needed, turn this off

        The tests show a ``13% - 15%`` improvement in execution time. Combined
        with ``optdatas`` the total gain increases to a total speed-up of
        ``32%`` in an optimization run.

      - ``oldsync`` (default: ``False``)

        Starting with release 1.9.0.99 the synchronization of multiple datas
        (same or different timeframes) has been changed to allow datas of
        different lengths.

        If the old behavior with datafeed0 as the master of the system is wished,
        set this parameter to true

      - ``tz`` (default: ``None``)

        Adds a global timezone for strategies. The argument ``tz`` can be

          - ``None``: in this case the datetime displayed by strategies will be
            in UTC, which has been always the standard behavior

          - ``pytz`` instance. It will be used as such to convert UTC times to
            the chosen timezone

          - ``string``. Instantiating a ``pytz`` instance will be attempted.

          - ``integer``. Use, for the strategy, the same timezone as the
            corresponding ``data`` in the ``self.datas`` iterable (``0`` would
            use the timezone from ``datafeed0``)

      - ``cheat_on_open`` (default: ``False``)

        The ``next_open`` method of strategies will be called. This happens
        before ``next`` and before the broker_or_exchange has had a chance to evaluate
        orders. The indicators have not yet been recalculated. This allows
        issuing an orde which takes into account the indicators of the previous
        day but uses the ``open`` price for stake calculations

        For cheat_on_open order execution, it is also necessary to make the
        call ``cerebro.broker_or_exchange.set_coo(True)`` or instantite a broker_or_exchange with
        ``BackBroker(coo=True)`` (where *coo* stands for cheat-on-open) or set
        the ``broker_coo`` parameter to ``True``. Cerebro will do it
        automatically unless disabled below.

      - ``broker_coo`` (default: ``True``)

        This will automatically invoke the ``set_coo`` method of the broker_or_exchange
        with ``True`` to activate ``cheat_on_open`` execution. Will only do it
        if ``cheat_on_open`` is also ``True``

      - ``quicknotify`` (default: ``False``)

        Broker_or_Exchange notifications are delivered right before the delivery of the
        *next* prices. For backtesting this has no implications, but with live
        brokers a notification can take place long before the bar is
        delivered. When set to ``True`` notifications will be delivered as soon
        as possible (see ``qcheck`` in live feeds)

        Set to ``False`` for compatibility. May be changed to ``True``

    '''

    params = (
        ('preload', True),
        ('runonce', True),
        ('maxcpus', None),
        ('stdstats', True),
        ('oldbuysell', False),
        ('oldtrades', False),
        ('lookahead', 0),
        ('exactbars', False),
        ('optdatas', True),
        ('optreturn', True),
        ('objcache', False),
        ('live', False),
        ('writer', False),
        ('tradehistory', False),
        ('oldsync', False),
        ('tz', None),
        ('cheat_on_open', False),
        ('broker_coo', True),
        ('quicknotify', False),
    )

    def __init__(self):
        self._do_live = False
        self._do_replay = False
        self._do_optimization = False
        self.accounts_or_stores = list()
        self.backend_feeds = list()
        self.datafeeds = list()
        self.datafeeds_by_name = collections.OrderedDict()
        self.strategies = list()
        self.optcbs = list()  # holds a list of callbacks for opt strategies
        self.observers = list()
        self.analyzers = list()
        self.indicators = list()
        self.sizers = dict()
        self.writers = list()
        self.storecbs = list()
        self.datacbs = list()
        self.signals = list()
        self._signal_strat = (None, None, None)
        self._signal_concurrent = False
        self._signal_accumulate = False

        self._datafeed_id = itertools.count(1)

        self._broker_or_exchange = BackBroker()
        self._broker_or_exchange.cerebro = self

        self._tradingcal = None  # TradingCalendar()

        self._pretimers = list()
        self._ohistory = list()
        self._fhistory = None

    @staticmethod
    def iterize(iterable):
        '''Handy function which turns things into things that can be iterated upon
        including iterables
        '''
        niterable = list()
        for elem in iterable:
            if isinstance(elem, string_types):
                elem = (elem,)
            elif not isinstance(elem, collections.abc.Iterable):
                elem = (elem,)

            niterable.append(elem)

        return niterable

    def set_fund_history(self, fund):
        '''
        Add a history of orders to be directly executed in the broker_or_exchange for
        performance evaluation

          - ``fund``: is an iterable (ex: list, tuple, iterator, generator)
            in which each element will be also an iterable (with length) with
            the following sub-elements (2 formats are possible)

            ``[datetime, share_value, net asset value]``

            **Note**: it must be sorted (or produce sorted elements) by
              datetime ascending

            where:

              - ``datetime`` is a python ``date/datetime`` instance or a string
                with format YYYY-MM-DD[THH:MM:SS[.us]] where the elements in
                brackets are optional
              - ``share_value`` is an float/integer
              - ``net_asset_value`` is a float/integer
        '''
        self._fhistory = fund

    def add_order_history(self, orders, notify=True):
        '''
        Add a history of orders to be directly executed in the broker_or_exchange for
        performance evaluation

          - ``orders``: is an iterable (ex: list, tuple, iterator, generator)
            in which each element will be also an iterable (with length) with
            the following sub-elements (2 formats are possible)

            ``[datetime, size, price]`` or ``[datetime, size, price, data]``

            **Note**: it must be sorted (or produce sorted elements) by
              datetime ascending

            where:

              - ``datetime`` is a python ``date/datetime`` instance or a string
                with format YYYY-MM-DD[THH:MM:SS[.us]] where the elements in
                brackets are optional
              - ``size`` is an integer (positive to *buy*, negative to *sell*)
              - ``price`` is a float/integer
              - ``data`` if present can take any of the following values

                - *None* - The 1st data feed will be used as target
                - *integer* - The data with that index (insertion order in
                  **Cerebro**) will be used
                - *string* - a data with that name, assigned for example with
                  ``cerebro.addata(data, name=value)``, will be the target

          - ``notify`` (default: *True*)

            If ``True`` the 1st strategy inserted in the system will be
            notified of the artificial orders created following the information
            from each order in ``orders``

        **Note**: Implicit in the description is the need to add a data feed
          which is the target of the orders. This is for example needed by
          analyzers which track for example the returns
        '''
        self._ohistory.append((orders, notify))

    def get_orders(self):
        return self._broker_or_exchange.get_orders()

    def notify_timer(self, timer, when, *args, **kwargs):
        '''Receives a timer notification where ``timer`` is the timer which was
        returned by ``add_timer``, and ``when`` is the calling time. ``args``
        and ``kwargs`` are any additional arguments passed to ``add_timer``

        The actual ``when`` time can be later, but the system may have not be
        able to call the timer before. This value is the timer value and no the
        system time.
        '''
        pass

    def _add_timer(self, owner, when,
                   offset=datetime.timedelta(), repeat=datetime.timedelta(),
                   weekdays=[], weekcarry=False,
                   monthdays=[], monthcarry=True,
                   allow=None,
                   tzdata=None, strats=False, cheat=False,
                   *args, **kwargs):
        '''Internal method to really create the timer (not started yet) which
        can be called by cerebro instances or other objects which can access
        cerebro'''

        timer = Timer(
            tid=len(self._pretimers),
            owner=owner, strats=strats,
            when=when, offset=offset, repeat=repeat,
            weekdays=weekdays, weekcarry=weekcarry,
            monthdays=monthdays, monthcarry=monthcarry,
            allow=allow,
            tzdata=tzdata, cheat=cheat,
            *args, **kwargs
        )

        self._pretimers.append(timer)
        return timer

    def add_timer(self, when,
                  offset=datetime.timedelta(), repeat=datetime.timedelta(),
                  weekdays=[], weekcarry=False,
                  monthdays=[], monthcarry=True,
                  allow=None,
                  tzdata=None, strats=False, cheat=False,
                  *args, **kwargs):
        '''
        Schedules a timer to invoke ``notify_timer``

        Arguments:

          - ``when``: can be

            - ``datetime.time`` instance (see below ``tzdata``)
            - ``bt.timer.SESSION_START`` to reference a session start
            - ``bt.timer.SESSION_END`` to reference a session end

         - ``offset`` which must be a ``datetime.timedelta`` instance

           Used to offset the value ``when``. It has a meaningful use in
           combination with ``SESSION_START`` and ``SESSION_END``, to indicated
           things like a timer being called ``15 minutes`` after the session
           start.

          - ``repeat`` which must be a ``datetime.timedelta`` instance

            Indicates if after a 1st call, further calls will be scheduled
            within the same session at the scheduled ``repeat`` delta

            Once the timer goes over the end of the session it is reset to the
            original value for ``when``

          - ``weekdays``: a **sorted** iterable with integers indicating on
            which days (iso codes, Monday is 1, Sunday is 7) the timers can
            be actually invoked

            If not specified, the timer will be active on all days

          - ``weekcarry`` (default: ``False``). If ``True`` and the weekday was
            not seen (ex: trading holiday), the timer will be executed on the
            next day (even if in a new week)

          - ``monthdays``: a **sorted** iterable with integers indicating on
            which days of the month a timer has to be executed. For example
            always on day *15* of the month

            If not specified, the timer will be active on all days

          - ``monthcarry`` (default: ``True``). If the day was not seen
            (weekend, trading holiday), the timer will be executed on the next
            available day.

          - ``allow`` (default: ``None``). A callback which receives a
            `datetime.date`` instance and returns ``True`` if the date is
            allowed for timers or else returns ``False``

          - ``tzdata`` which can be either ``None`` (default), a ``pytz``
            instance or a ``data feed`` instance.

            ``None``: ``when`` is interpreted at face value (which translates
            to handling it as if it where UTC even if it's not)

            ``pytz`` instance: ``when`` will be interpreted as being specified
            in the local time specified by the timezone instance.

            ``data feed`` instance: ``when`` will be interpreted as being
            specified in the local time specified by the ``tz`` parameter of
            the data feed instance.

            **Note**: If ``when`` is either ``SESSION_START`` or
              ``SESSION_END`` and ``tzdata`` is ``None``, the 1st *data feed*
              in the system (aka ``self.datafeed0``) will be used as the reference
              to find out the session times.

          - ``strats`` (default: ``False``) call also the ``notify_timer`` of
            strategies

          - ``cheat`` (default ``False``) if ``True`` the timer will be called
            before the broker_or_exchange has a chance to evaluate the orders. This opens
            the chance to issue orders based on opening price for example right
            before the session starts
          - ``*args``: any extra args will be passed to ``notify_timer``

          - ``**kwargs``: any extra kwargs will be passed to ``notify_timer``

        Return Value:

          - The created timer

        '''
        return self._add_timer(
            owner=self, when=when, offset=offset, repeat=repeat,
            weekdays=weekdays, weekcarry=weekcarry,
            monthdays=monthdays, monthcarry=monthcarry,
            allow=allow,
            tzdata=tzdata, strats=strats, cheat=cheat,
            *args, **kwargs)

    def add_timezone(self, tz):
        '''
        This can also be done with the parameter ``tz``

        Adds a global timezone for strategies. The argument ``tz`` can be

          - ``None``: in this case the datetime displayed by strategies will be
            in UTC, which has been always the standard behavior

          - ``pytz`` instance. It will be used as such to convert UTC times to
            the chosen timezone

          - ``string``. Instantiating a ``pytz`` instance will be attempted.

          - ``integer``. Use, for the strategy, the same timezone as the
            corresponding ``data`` in the ``self.datas`` iterable (``0`` would
            use the timezone from ``datafeed0``)

        '''
        self.p.tz = tz

    def add_calendar(self, cal):
        '''Adds a global trading calendar to the system. Individual data feeds
        may have separate calendars which override the global one

        ``cal`` can be an instance of ``TradingCalendar`` a string or an
        instance of ``pandas_market_calendars``. A string will be will be
        instantiated as a ``PandasMarketCalendar`` (which needs the module
        ``pandas_market_calendar`` installed in the system.

        If a subclass of `TradingCalendarBase` is passed (not an instance) it
        will be instantiated
        '''
        if isinstance(cal, string_types):
            cal = PandasMarketCalendar(calendar=cal)
        elif hasattr(cal, 'valid_days'):
            cal = PandasMarketCalendar(calendar=cal)

        else:
            try:
                if issubclass(cal, TradingCalendarBase):
                    cal = cal()
            except TypeError:  # already an instance
                pass

        self._tradingcal = cal

    def add_signal(self, sigtype, sigcls, *sigargs, **sigkwargs):
        '''Adds a signal to the system which will be later added to a
        ``SignalStrategy``'''
        self.signals.append((sigtype, sigcls, sigargs, sigkwargs))

    def signal_strategy(self, stratcls, *args, **kwargs):
        '''Adds a SignalStrategy subclass which can accept signals'''
        self._signal_strat = (stratcls, args, kwargs)

    def signal_concurrent(self, onoff):
        '''If signals are added to the system and the ``concurrent`` value is
        set to True, concurrent orders will be allowed'''
        self._signal_concurrent = onoff

    def signal_accumulate(self, onoff):
        '''If signals are added to the system and the ``accumulate`` value is
        set to True, entering the market when already in the market, will be
        allowed to increase a position'''
        self._signal_accumulate = onoff

    def add_account_store(self, store):
        '''Adds an ``Account Store`` instance to the if not already present'''
        if store not in self.accounts_or_stores:
            self.accounts_or_stores.append(store)

    def add_writer(self, wrtcls, *args, **kwargs):
        '''Adds an ``Writer`` class to the mix. Instantiation will be done at
        ``run`` time in cerebro
        '''
        self.writers.append((wrtcls, args, kwargs))

    def add_sizer(self, sizercls, *args, **kwargs):
        '''Adds a ``Sizer`` class (and args) which is the default sizer for any
        strategy added to cerebro
        '''
        self.sizers[None] = (sizercls, args, kwargs)

    def add_sizer_by_idx(self, idx, sizercls, *args, **kwargs):
        '''Adds a ``Sizer`` class by idx. This idx is a reference compatible to
        the one returned by ``add_strategy``. Only the strategy referenced by
        ``idx`` will receive this size
        '''
        self.sizers[idx] = (sizercls, args, kwargs)

    def add_indicator(self, indcls, *args, **kwargs):
        '''
        Adds an ``Indicator`` class to the mix. Instantiation will be done at
        ``run`` time in the passed strategies
        '''
        self.indicators.append((indcls, args, kwargs))

    def add_analyzer(self, ancls, *args, **kwargs):
        '''
        Adds an ``Analyzer`` class to the mix. Instantiation will be done at
        ``run`` time
        '''
        self.analyzers.append((ancls, args, kwargs))

    def add_system_wide_observer(self, obscls, *args, **kwargs):
        '''
        Adds an ``Observer`` class to the mix. Instantiation will be done at
        ``run`` time
        '''
        self.observers.append((False, obscls, args, kwargs))

    def add_per_datafeed_observer(self, obscls, *args, **kwargs):
        '''
        Adds an ``Observer`` class to the mix. Instantiation will be done at
        ``run`` time

        It will be added once per "data" in the system. A use case is a
        buy/sell observer which observes individual datas.

        A counter-example is the CashValue, which observes system-wide values
        '''
        self.observers.append((True, obscls, args, kwargs))

    def add_account_store_callback(self, callback):
        '''Adds a callback to get messages which would be handled by the
        notify_account_or_store method

        The signature of the callback must support the following:

          - callback(msg, \*args, \*\*kwargs)

        The actual ``msg``, ``*args`` and ``**kwargs`` received are
        implementation defined (depend entirely on the *data/broker_or_exchange/store*) but
        in general one should expect them to be *printable* to allow for
        reception and experimentation.
        '''
        self.storecbs.append(callback)

    def _notify_account_or_store_with_callback(self, msg, *args, **kwargs):
        for callback in self.storecbs:
            callback(msg, *args, **kwargs)

        self.notify_account_or_store(msg, *args, **kwargs)

    def notify_account_or_store(self, msg, *args, **kwargs):
        '''Receive store notifications in cerebro

        This method can be overridden in ``Cerebro`` subclasses

        The actual ``msg``, ``*args`` and ``**kwargs`` received are
        implementation defined (depend entirely on the *data/broker_or_exchange/store*) but
        in general one should expect them to be *printable* to allow for
        reception and experimentation.
        '''
        pass

    def _notify_account_or_store(self):
        for store in self.accounts_or_stores:
            for notif in store.get_notifications():
                msg, args, kwargs = notif

                self._notify_account_or_store_with_callback(
                    msg, *args, **kwargs)
                for strat in self.runningstrats:
                    strat.notify_account_or_store(msg, *args, **kwargs)

    def add_datafeed_callback(self, callback):
        '''Adds a callback to get messages which would be handled by the
        datafeed_notification method

        The signature of the callback must support the following:

          - callback(data, status, \*args, \*\*kwargs)

        The actual ``*args`` and ``**kwargs`` received are implementation
        defined (depend entirely on the *data/broker_or_exchange/store*) but in general one
        should expect them to be *printable* to allow for reception and
        experimentation.
        '''
        self.datacbs.append(callback)

    def _datafeed_notification(self):
        for datafeed in self.datafeeds:
            for notif in datafeed.get_notifications():
                status, args, kwargs = notif
                self._datafeed_callback_notification(
                    datafeed, status, *args, **kwargs)
                for strat in self.runningstrats:
                    strat.datafeed_notification(
                        datafeed, status, *args, **kwargs)

    def _datafeed_callback_notification(self, datafeed, status, *args, **kwargs):
        for callback in self.datacbs:
            callback(datafeed, status, *args, **kwargs)

        self.datafeed_notification(datafeed, status, *args, **kwargs)

    def datafeed_notification(self, datafeed, status, *args, **kwargs):
        '''Receive data notifications in cerebro

        This method can be overridden in ``Cerebro`` subclasses

        The actual ``*args`` and ``**kwargs`` received are
        implementation defined (depend entirely on the *data/broker_or_exchange/store*) but
        in general one should expect them to be *printable* to allow for
        reception and experimentation.
        '''
        pass

    def add_datafeed(self, datafeed, name=None):
        '''
        Adds a ``datafeed`` instance to the mix.

        If ``name`` is not None it will be put into ``datafeed._name`` which is
        meant for decoration/plotting purposes.
        '''
        if name is not None:
            datafeed._name = name
        else:
            print(
                "WARNING: No name has been assigned for add_datafeed datafeed in cerebro")

        datafeed._id = next(self._datafeed_id)
        datafeed.setenvironment(self)

        self.datafeeds.append(datafeed)
        self.datafeeds_by_name[datafeed._name] = datafeed
        feed = datafeed.get_backend_datafeed()
        if feed and feed not in self.backend_feeds:
            self.backend_feeds.append(feed)

        if datafeed.is_live():
            self._do_live = True

        return datafeed

    def chain_datafeed(self, *args, **kwargs):
        '''
        Chains several datafeeds into one

        If ``name`` is passed as named argument and is not None it will be put
        into ``datafeed._name`` which is meant for decoration/plotting purposes.

        If ``None``, then the name of the 1st data will be used
        '''
        dname = kwargs.pop('name', None)
        if dname is None:
            dname = args[0]._dataname
        d = bt.feeds.Chainer(dataname=dname, *args)
        self.add_datafeed(d, name=dname)

        return d

    def clone(self):
        obj = deepcopy(self)
        return obj

    def roll_over_datafeed(self, *args, **kwargs):
        '''Chains several data feeds into one

        If ``name`` is passed as named argument and is not None it will be put
        into ``datafeed._name`` which is meant for decoration/plotting purposes.

        If ``None``, then the name of the 1st data will be used

        Any other kwargs will be passed to the RollOver class

        '''
        dname = kwargs.pop('name', None)
        if dname is None:
            dname = args[0]._dataname
        d = bt.feeds.RollOver(dataname=dname, *args, **kwargs)
        self.add_datafeed(d, name=dname)

        return d

    def replay_datafeed(self, dataname, name=None, **kwargs):
        '''
        Adds a ``Data Feed`` to be replayed by the system

        If ``name`` is not None it will be put into ``datafeed._name`` which is
        meant for decoration/plotting purposes.

        Any other kwargs like ``timeframe``, ``compression``, ``todate`` which
        are supported by the replay filter will be passed transparently
        '''
        if any(dataname is x for x in self.datafeeds):
            dataname = dataname.clone()

        dataname.replay(**kwargs)
        self.add_datafeed(dataname, name=name)
        self._do_replay = True

        return dataname

    def resample_datafeed(self, dataname, name=None, **kwargs):
        '''
        Adds a ``Data Feed`` to be resample by the system

        If ``name`` is not None it will be put into ``datafeed._name`` which is
        meant for decoration/plotting purposes.

        Any other kwargs like ``timeframe``, ``compression``, ``todate`` which
        are supported by the resample filter will be passed transparently
        '''
        if any(dataname is x for x in self.datafeeds):
            dataname = dataname.clone()

        dataname.resample(**kwargs)
        self.add_datafeed(dataname, name=name)
        self._do_replay = True

        return dataname

    def optcallback(self, cb):
        '''
        Adds a *callback* to the list of callbacks that will be called with the
        optimizations when each of the strategies has been run

        The signature: cb(strategy)
        '''
        self.optcbs.append(cb)

    def optimize_strategy(self, strategy, *args, **kwargs):
        '''
        Adds a ``Strategy`` class to the mix for optimization. Instantiation
        will happen during ``run`` time.

        args and kwargs MUST BE iterables which hold the values to check.

        Example: if a Strategy accepts a parameter ``period``, for optimization
        purposes the call to ``optimize_strategy`` looks like:

          - cerebro.optimize_strategy(MyStrategy, period=(15, 25))

        This will execute an optimization for values 15 and 25. Whereas

          - cerebro.optimize_strategy(MyStrategy, period=range(15, 25))

        will execute MyStrategy with ``period`` values 15 -> 25 (25 not
        included, because ranges are semi-open in Python)

        If a parameter is passed but shall not be optimized the call looks
        like:

          - cerebro.optimize_strategy(MyStrategy, period=(15,))

        Notice that ``period`` is still passed as an iterable ... of just 1
        element

        ``backtrader`` will anyhow try to identify situations like:

          - cerebro.optimize_strategy(MyStrategy, period=15)

        and will create an internal pseudo-iterable if possible
        '''
        self._do_optimization = True
        args = self.iterize(args)
        optargs = itertools.product(*args)

        optkeys = list(kwargs)

        vals = self.iterize(kwargs.values())
        optvals = itertools.product(*vals)

        okwargs1 = map(zip, itertools.repeat(optkeys), optvals)

        optkwargs = map(dict, okwargs1)

        it = itertools.product([strategy], optargs, optkwargs)
        self.strategies.append(it)

    def add_strategy(self, strategy, *args, **kwargs):
        '''
        Adds a ``Strategy`` class to the mix for a single pass run.
        Instantiation will happen during ``run`` time.

        args and kwargs will be passed to the strategy as they are during
        instantiation.

        Returns the index with which addition of other objects (like sizers)
        can be referenced
        '''
        self.strategies.append([(strategy, args, kwargs)])
        return len(self.strategies) - 1

    def set_broker_or_exchange(self, broker_or_exchange):
        '''
        Sets a specific ``broker_or_exchange or exchange`` instance for this strategy, replacing the
        one inherited from cerebro.
        '''
        self._broker_or_exchange = broker_or_exchange
        broker_or_exchange.cerebro = self
        return broker_or_exchange

    def get_broker_or_exchange(self):
        '''
        Returns the broker_or_exchange or exchange instance.

        This is also available as a ``property`` by the name ``broker_or_exchange or exchange``
        '''
        return self._broker_or_exchange

    broker_or_exchange = property(
        get_broker_or_exchange, set_broker_or_exchange)

    def plot(self, plotter=None, numfigs=1, iplot=True, start=None, end=None,
             width=16, height=9, dpi=300, tight=True, backend=None, **kwargs):
        '''
        Plots the strategies inside cerebro

        If ``plotter`` is None a default ``Plot`` instance is created and
        ``kwargs`` are passed to it during instantiation.

        ``numfigs`` split the plot in the indicated number of charts reducing
        chart density if wished

        ``iplot``: if ``True`` and running in a ``notebook`` the charts will be
        displayed inline

        ``backend``: set it to the name of the desired matplotlib backend. It will
        take precedence over ``iplot``

        ``start``: An index to the datetime line array of the strategy or a
        ``datetime.date``, ``datetime.datetime`` instance indicating the start
        of the plot

        ``end``: An index to the datetime line array of the strategy or a
        ``datetime.date``, ``datetime.datetime`` instance indicating the end
        of the plot

        ``width``: in inches of the saved figure

        ``height``: in inches of the saved figure

        ``dpi``: quality in dots per inches of the saved figure

        ``tight``: only save actual content and not the frame of the figure
        '''
        if self._exactbars > 0:
            return

        if not plotter:
            from . import plot
            if self.p.oldsync:
                plotter = plot.Plot_OldSync(**kwargs)
            else:
                plotter = plot.Plot(**kwargs)

        # pfillers = {self.datas[i]: self._plotfillers[i]
        # for i, x in enumerate(self._plotfillers)}

        # pfillers2 = {self.datas[i]: self._plotfillers2[i]
        # for i, x in enumerate(self._plotfillers2)}

        figs = []
        bufs = []
        for stratlist in self.runstrats:
            for si, strat in enumerate(stratlist):
                rfig = plotter.plot(strat, figid=si * 100,
                                    numfigs=numfigs, iplot=iplot,
                                    start=start, end=end, backend=backend)
                # pfillers=pfillers2)

                figs.append(rfig)

            buf = plotter.show()
            bufs.append(buf)

        return figs, bufs

    def __call__(self, iterstrat):
        '''
        Used during optimization to pass the cerebro over the multiprocesing
        module without complains
        '''

        predata = self.p.optdatas and self._dopreload and self._dorunonce
        return self.run_strategies(iterstrat, predata=predata)

    def __getstate__(self):
        '''
        Used during optimization to prevent optimization result `runstrats`
        from being pickled to subprocesses
        '''

        rv = vars(self).copy()
        if 'runstrats' in rv:
            del (rv['runstrats'])
        return rv

    def stop_running(self):
        '''If invoked from inside a strategy or anywhere else, including other
        threads the execution will stop as soon as possible.'''
        self._event_stop = True  # signal a stop has been requested

    def run(self, **kwargs):
        '''The core method to perform backtesting. Any ``kwargs`` passed to it
        will affect the value of the standard parameters ``Cerebro`` was
        instantiated with.

        If ``cerebro`` has not datas the method will immediately bail out.

        It has different return values:

          - For No Optimization: a list contanining instances of the Strategy
            classes added with ``add_strategy``

          - For Optimization: a list of lists which contain instances of the
            Strategy classes added with ``add_strategy``
        '''
        self._event_stop = False  # Stop is requested

        if not self.datafeeds:
            return []  # nothing can be run

        pkeys = self.params._getkeys()
        for key, val in kwargs.items():
            if key in pkeys:
                setattr(self.params, key, val)

        # Manage activate/deactivate object cache
        linebuffer.LineActions.cleancache()  # clean cache
        indicator.Indicator.cleancache()  # clean cache

        linebuffer.LineActions.usecache(self.p.objcache)
        indicator.Indicator.usecache(self.p.objcache)

        self._dorunonce = self.p.runonce
        self._dopreload = self.p.preload
        self._exactbars = int(self.p.exactbars)

        if self._exactbars:
            self._dorunonce = False  # something is saving memory, no runonce
            self._dopreload = self._dopreload and self._exactbars < 1

        self._do_replay = self._do_replay or any(
            x.replaying for x in self.datafeeds)
        if self._do_replay:
            # preloading is not supported with replay. full timeframe bars
            # are constructed in realtime
            self._dopreload = False

        if self._do_live or self.p.live:
            # in this case both preload and runonce must be off
            self._dorunonce = False
            self._dopreload = False

        self.runwriters = list()

        # Add the system default writer if requested
        if self.p.writer is True:
            wr = WriterFile()
            self.runwriters.append(wr)

        # Instantiate any other writers
        for wrcls, wrargs, wrkwargs in self.writers:
            wr = wrcls(*wrargs, **wrkwargs)
            self.runwriters.append(wr)

        # Write down if any writer wants the full csv output
        self.writers_csv = any(map(lambda x: x.p.csv, self.runwriters))

        self.runstrats = list()

        if self.signals:  # allow processing of signals
            signalst, sargs, skwargs = self._signal_strat
            if signalst is None:
                # Try to see if the 1st regular strategy is a signal strategy
                try:
                    signalst, sargs, skwargs = self.strategies.pop(0)
                except IndexError:
                    pass  # Nothing there
                else:
                    if not isinstance(signalst, SignalStrategy):
                        # no signal ... reinsert at the beginning
                        self.strategies.insert(0, (signalst, sargs, skwargs))
                        signalst = None  # flag as not presetn

            if signalst is None:  # recheck
                # Still None, create a default one
                signalst, sargs, skwargs = SignalStrategy, tuple(), dict()

            # Add the signal strategy
            self.add_strategy(signalst,
                              _accumulate=self._signal_accumulate,
                              _concurrent=self._signal_concurrent,
                              signals=self.signals,
                              *sargs,
                              **skwargs)

        if not self.strategies:  # Datas are present, add a strategy
            self.add_strategy(Strategy)

        iterstrats = itertools.product(*self.strategies)
        if not self._do_optimization or self.p.maxcpus == 1:
            # If no optimmization is wished ... or 1 core is to be used
            # let's skip process "spawning"
            for iterstrat in iterstrats:
                runstrat = self.run_strategies(iterstrat)
                self.runstrats.append(runstrat)
                if self._do_optimization:
                    for cb in self.optcbs:
                        cb(runstrat)  # callback receives finished strategy
        else:
            if self.p.optdatas and self._dopreload and self._dorunonce:
                for datafeed in self.datafeeds:
                    datafeed.reset()
                    if self._exactbars < 1:  # datas can be full length
                        datafeed.extend(size=self.params.lookahead)
                    datafeed._start()
                    if self._dopreload:
                        datafeed.preload()

            pool = multiprocessing.Pool(self.p.maxcpus or None)
            for r in pool.imap(self, iterstrats):
                self.runstrats.append(r)
                for cb in self.optcbs:
                    cb(r)  # callback receives finished strategy
                    # Force GC to run
                    gc.collect()
                # Force GC to run
                gc.collect()

            pool.close()

            if self.p.optdatas and self._dopreload and self._dorunonce:
                for datafeed in self.datafeeds:
                    datafeed.stop()

        if not self._do_optimization:
            # avoid a list of list for regular cases
            return self.runstrats[0]

        return self.runstrats

    def _init_stcount(self):
        self.stcount = itertools.count(0)

    def _next_stid(self):
        return next(self.stcount)

    def run_strategies(self, iterstrat, predata=False):
        '''
        Internal method invoked by ``run``` to run a set of strategies
        '''
        self._init_stcount()

        self.runningstrats = runstrats = list()
        for store in self.accounts_or_stores:
            store.start()

        if self.p.cheat_on_open and self.p.broker_coo:
            # try to activate in broker_or_exchange
            if hasattr(self._broker_or_exchange, 'set_coo'):
                self._broker_or_exchange.set_coo(True)

        if self._fhistory is not None:
            self._broker_or_exchange.set_fund_history(self._fhistory)

        for orders, onotify in self._ohistory:
            self._broker_or_exchange.add_order_history(orders, onotify)

        self._broker_or_exchange.start()

        for feed in self.backend_feeds:
            feed.start()

        if self.writers_csv:
            wheaders = list()
            for datafeed in self.datafeeds:
                if datafeed.csv:
                    wheaders.extend(datafeed.getwriterheaders())

            for writer in self.runwriters:
                if writer.p.csv:
                    writer.addheaders(wheaders)

        # self._plotfillers = [list() for d in self.datas]
        # self._plotfillers2 = [list() for d in self.datas]

        if not predata:
            for datafeed in self.datafeeds:
                datafeed.reset()
                if self._exactbars < 1:  # datas can be full length
                    datafeed.extend(size=self.params.lookahead)
                datafeed._start()
                if self._dopreload:
                    datafeed.preload()

        for stratcls, sargs, skwargs in iterstrat:
            sargs = self.datafeeds + list(sargs)
            try:
                strat = stratcls(*sargs, **skwargs)
            except bt.errors.StrategySkipError:
                continue  # do not add strategy to the mix

            if self.p.oldsync:
                strat._oldsync = True  # tell strategy to use old clock update
            if self.p.tradehistory:
                strat.set_tradehistory()
            runstrats.append(strat)

        tz = self.p.tz
        if isinstance(tz, integer_types):
            tz = self.datafeeds[tz]._tz
        else:
            tz = tzparse(tz)

        if runstrats:
            # loop separated for clarity
            defaultsizer = self.sizers.get(None, (None, None, None))
            for idx, strat in enumerate(runstrats):
                if self.p.stdstats:
                    strat._add_observer(False, observers.Broker_or_Exchange)
                    if self.p.oldbuysell:
                        strat._add_observer(True, observers.Buy_and_Sell)
                    else:
                        strat._add_observer(True, observers.Buy_and_Sell,
                                            barplot=True)

                    if self.p.oldtrades or len(self.datafeeds) == 1:
                        strat._add_observer(False, observers.Trades)
                    else:
                        strat._add_observer(False, observers.DataTrades)

                for multi, obscls, obsargs, obskwargs in self.observers:
                    strat._add_observer(multi, obscls, *obsargs, **obskwargs)

                for indcls, indargs, indkwargs in self.indicators:
                    strat._add_indicator(indcls, *indargs, **indkwargs)

                for ancls, anargs, ankwargs in self.analyzers:
                    strat._add_analyzer(ancls, *anargs, **ankwargs)

                sizer, sargs, skwargs = self.sizers.get(idx, defaultsizer)
                if sizer is not None:
                    strat._addsizer(sizer, *sargs, **skwargs)

                strat._settz(tz)
                strat._start()

                for writer in self.runwriters:
                    if writer.p.csv:
                        writer.addheaders(strat.getwriterheaders())

            if not predata:
                for strat in runstrats:
                    strat.qbuffer(self._exactbars, replaying=self._do_replay)

            for writer in self.runwriters:
                writer.start()

            # Prepare timers
            self._timers = []
            self._timerscheat = []
            for timer in self._pretimers:
                # preprocess tzdata if needed
                timer.start(self.datafeeds[0])

                if timer.params.cheat:
                    self._timerscheat.append(timer)
                else:
                    self._timers.append(timer)

            if self._dopreload and self._dorunonce:
                if self.p.oldsync:
                    self._runonce_old(runstrats)
                else:
                    self._run_once(runstrats)
            else:
                if self.p.oldsync:
                    self._runnext_old(runstrats)
                else:
                    self._runnext(runstrats)

            for strat in runstrats:
                strat._stop()

        self._broker_or_exchange.stop()

        if not predata:
            for datafeed in self.datafeeds:
                datafeed.stop()

        for feed in self.backend_feeds:
            feed.stop()

        for store in self.accounts_or_stores:
            store.stop()

        self.stop_writers(runstrats)

        if self._do_optimization and self.p.optreturn:
            # Results can be optimized
            results = list()
            for strat in runstrats:
                for a in strat.analyzers:
                    a.strategy = None
                    a._parent = None
                    for attrname in dir(a):
                        if attrname.startswith('datafeed'):
                            setattr(a, attrname, None)

                oreturn = OptReturn(
                    strat.params, analyzers=strat.analyzers, strategycls=type(strat))
                results.append(oreturn)

            return results

        return runstrats

    def stop_writers(self, runstrats):
        cerebroinfo = OrderedDict()
        datainfos = OrderedDict()

        for i, datafeed in enumerate(self.datafeeds):
            datainfos['Data%d' % i] = datafeed.getwriterinfo()

        cerebroinfo['Datas'] = datainfos

        stratinfos = dict()
        for strat in runstrats:
            stname = strat.__class__.__name__
            stratinfos[stname] = strat.getwriterinfo()

        cerebroinfo['Strategies'] = stratinfos

        for writer in self.runwriters:
            writer.writedict(dict(Cerebro=cerebroinfo))
            writer.stop()

    def _broker_or_echange_notification(self):
        '''
        Internal method which kicks the broker_or_exchange and delivers any broker_or_exchange
        notification to the strategy
        '''
        self._broker_or_exchange.next()
        while True:
            order = self._broker_or_exchange.get_notification()
            if order is None:
                break

            owner = order.owner
            if owner is None:
                owner = self.runningstrats[0]  # default

            owner._add_notification(order, quicknotify=self.p.quicknotify)

    def _runnext_old(self, runstrats):
        '''
        Actual implementation of run in full next mode. All objects have its
        ``next`` method invoke on each data arrival
        '''
        datafeed0 = self.datafeeds[0]
        d0ret = True
        while d0ret or d0ret is None:
            lastret = False
            # Notify anything from the store even before moving datas
            # because datas may not move due to an error reported by the store
            self._notify_account_or_store()
            if self._event_stop:  # stop if requested
                return
            self._datafeed_notification()
            if self._event_stop:  # stop if requested
                return

            d0ret = datafeed0.next()
            if d0ret:
                for datafeed in self.datafeeds[1:]:
                    if not datafeed.next(datamaster=datafeed0):  # no delivery
                        # check forcing output
                        datafeed._check(forcedata=datafeed0)
                        datafeed.next(datamaster=datafeed0)  # retry

            elif d0ret is None:
                # meant for things like live feeds which may not produce a bar
                # at the moment but need the loop to run for notifications and
                # getting resample and others to produce timely bars
                datafeed0._check()
                for datafeed in self.datafeeds[1:]:
                    datafeed._check()
            else:
                lastret = datafeed0._last()
                for data in self.datafeeds[1:]:
                    lastret += data._last(datamaster=datafeed0)

                if not lastret:
                    # Only go extra round if something was changed by "lasts"
                    break

            # Datas may have generated a new notification after next
            self._datafeed_notification()
            if self._event_stop:  # stop if requested
                return

            self._broker_or_echange_notification()
            if self._event_stop:  # stop if requested
                return

            if d0ret or lastret:  # bars produced by data or filters
                for strat in runstrats:
                    strat._next()
                    if self._event_stop:  # stop if requested
                        return

                    self._next_writers(runstrats)

        # Last notification chance before stopping
        self._datafeed_notification()
        if self._event_stop:  # stop if requested
            return
        self._notify_account_or_store()
        if self._event_stop:  # stop if requested
            return

    def _runonce_old(self, runstrats):
        '''
        Actual implementation of run in vector mode.
        Strategies are still invoked on a pseudo-event mode in which ``next``
        is called for each data arrival
        '''
        for strat in runstrats:
            strat._once()

        # The default once for strategies does nothing and therefore
        # has not moved forward all datas/indicators/observers that
        # were homed before calling once, Hence no "need" to do it
        # here again, because pointers are at 0
        datafeed0 = self.datafeeds[0]
        datafeeds = self.datafeeds[1:]
        for i in range(datafeed0.buflen()):
            datafeed0.advance()
            for datafeed in datafeeds:
                datafeed.advance(datamaster=datafeed0)

            self._broker_or_echange_notification()
            if self._event_stop:  # stop if requested
                return

            for strat in runstrats:
                # datafeed0.datetime[0] for compat. w/ new strategy's oncepost
                strat._oncepost(datafeed0.datetime[0])
                if self._event_stop:  # stop if requested
                    return

                self._next_writers(runstrats)

    def _next_writers(self, runstrats):
        if not self.runwriters:
            return

        if self.writers_csv:
            wvalues = list()
            for datafeed in self.datafeeds:
                if datafeed.csv:
                    wvalues.extend(datafeed.getwritervalues())

            for strat in runstrats:
                wvalues.extend(strat.getwritervalues())

            for writer in self.runwriters:
                if writer.p.csv:
                    writer.addvalues(wvalues)

                    writer.next()

    def _disable_runonce(self):
        '''API for lineiterators to disable runonce (see HeikinAshi)'''
        self._dorunonce = False

    def _runnext(self, runstrats):
        '''
        Actual implementation of run in full next mode. All objects have its
        ``next`` method invoke on each data arrival
        '''
        datafeeds = sorted(self.datafeeds,
                           key=lambda x: (x._timeframe, x._compression))
        datas1 = datafeeds[1:]
        datafeed0 = datafeeds[0]
        d0ret = True

        rs = [i for i, x in enumerate(datafeeds) if x.resampling]
        rp = [i for i, x in enumerate(datafeeds) if x.replaying]
        rsonly = [i for i, x in enumerate(datafeeds)
                  if x.resampling and not x.replaying]
        onlyresample = len(datafeeds) == len(rsonly)
        noresample = not rsonly

        clonecount = sum(d._clone for d in datafeeds)
        ldatas = len(datafeeds)
        ldatas_noclones = ldatas - clonecount
        lastqcheck = False
        dt0 = date2num(datetime.datetime.max) - 2  # default at max
        while d0ret or d0ret is None:
            # if any has live data in the buffer, no data will wait anything
            newqcheck = not any(d.has_live_data() for d in datafeeds)
            if not newqcheck:
                # If no data has reached the live status or all, wait for
                # the next incoming data
                livecount = sum(d._laststatus == d.LIVE for d in datafeeds)
                newqcheck = not livecount or livecount == ldatas_noclones

            lastret = False
            # Notify anything from the store even before moving datafeeds
            # because datafeeds may not move due to an error reported by the store
            self._notify_account_or_store()
            if self._event_stop:  # stop if requested
                return
            self._datafeed_notification()
            if self._event_stop:  # stop if requested
                return

            # record starting time and tell feeds to discount the elapsed time
            # from the qcheck value
            drets = []
            qstart = datetime.datetime.utcnow()
            for d in datafeeds:
                qlapse = datetime.datetime.utcnow() - qstart
                d.do_qcheck(newqcheck, qlapse.total_seconds())
                drets.append(d.next(ticks=False))

            d0ret = any((dret for dret in drets))
            if not d0ret and any((dret is None for dret in drets)):
                d0ret = None

            if d0ret:
                dts = []
                for i, ret in enumerate(drets):
                    dts.append(datafeeds[i].datetime[0] if ret else None)

                # Get index to minimum datetime
                if onlyresample or noresample:
                    dt0 = min((d for d in dts if d is not None))
                else:
                    dt0 = min((d for i, d in enumerate(dts)
                               if d is not None and i not in rsonly))

                dmaster = datafeeds[dts.index(dt0)]  # and timemaster
                self._dtmaster = dmaster.num2date(dt0)
                self._udtmaster = num2date(dt0)

                # slen = len(runstrats[0])
                # Try to get something for those that didn't return
                for i, ret in enumerate(drets):
                    if ret:  # dts already contains a valid datetime for this i
                        continue

                    # try to get a data by checking with a master
                    d = datafeeds[i]
                    d._check(forcedata=dmaster)  # check to force output
                    if d.next(datamaster=dmaster, ticks=False):  # retry
                        dts[i] = d.datetime[0]  # good -> store
                        # self._plotfillers2[i].append(slen)  # mark as fill
                    else:
                        # self._plotfillers[i].append(slen)  # mark as empty
                        pass

                # make sure only those at dmaster level end up delivering
                for i, dti in enumerate(dts):
                    if dti is not None:
                        di = datafeeds[i]
                        rpi = False and di.replaying   # to check behavior
                        if dti > dt0:
                            if not rpi:  # must see all ticks ...
                                di.rewind()  # cannot deliver yet
                            # self._plotfillers[i].append(slen)
                        elif not di.replaying:
                            # Replay forces tick fill, else force here
                            di._tick_fill(force=True)

                        # self._plotfillers2[i].append(slen)  # mark as fill

            elif d0ret is None:
                # meant for things like live feeds which may not produce a bar
                # at the moment but need the loop to run for notifications and
                # getting resample and others to produce timely bars
                for datafeed in datafeeds:
                    datafeed._check()
            else:
                lastret = datafeed0._last()
                for data in datas1:
                    lastret += data._last(datamaster=datafeed0)

                if not lastret:
                    # Only go extra round if something was changed by "lasts"
                    break

            # Datas may have generated a new notification after next
            self._datafeed_notification()
            if self._event_stop:  # stop if requested
                return

            if d0ret or lastret:  # if any bar, check timers before broker_or_exchange
                self._check_timers(runstrats, dt0, cheat=True)
                if self.p.cheat_on_open:
                    for strat in runstrats:
                        strat._next_open()
                        if self._event_stop:  # stop if requested
                            return

            self._broker_or_echange_notification()
            if self._event_stop:  # stop if requested
                return

            if d0ret or lastret:  # bars produced by data or filters
                self._check_timers(runstrats, dt0, cheat=False)
                for strat in runstrats:
                    try:
                        strat._next(None, None)
                    except TypeError:
                        strat._next()
                    if self._event_stop:  # stop if requested
                        return

                    self._next_writers(runstrats)

        # Last notification chance before stopping
        self._datafeed_notification()
        if self._event_stop:  # stop if requested
            return
        self._notify_account_or_store()
        if self._event_stop:  # stop if requested
            return

    def _run_once(self, runstrats):
        '''
        Actual implementation of run in vector mode.

        Strategies are still invoked on a pseudo-event mode in which ``next``
        is called for each data arrival
        '''
        for strat in runstrats:
            strat._once()
            strat.reset()  # strat called next by next - reset lines

        # The default once for strategies does nothing and therefore
        # has not moved forward all datafeeds/indicators/observers that
        # were homed before calling once, Hence no "need" to do it
        # here again, because pointers are at 0
        datafeeds = sorted(self.datafeeds,
                           key=lambda x: (x._timeframe, x._compression))

        while True:
            # Check next incoming date in the datafeeds
            dts = [datafeed.advance_peek() for datafeed in datafeeds]
            dt0 = min(dts)
            if dt0 == float('inf'):
                break  # no data delivers anything

            # Timemaster if needed be
            # dmaster = datafeeds[dts.index(dt0)]  # and timemaster
            slen = len(runstrats[0])
            for i, dti in enumerate(dts):
                if dti <= dt0:
                    datafeeds[i].advance()
                    # self._plotfillers2[i].append(slen)  # mark as fill
                else:
                    # self._plotfillers[i].append(slen)
                    pass

            self._check_timers(runstrats, dt0, cheat=True)

            if self.p.cheat_on_open:
                for strat in runstrats:
                    strat._oncepost_open()
                    if self._event_stop:  # stop if requested
                        return

            self._broker_or_echange_notification()
            if self._event_stop:  # stop if requested
                return

            self._check_timers(runstrats, dt0, cheat=False)

            for strat in runstrats:
                strat._oncepost(dt0)
                if self._event_stop:  # stop if requested
                    return

                self._next_writers(runstrats)

    def _check_timers(self, runstrats, dt0, cheat=False):
        timers = self._timers if not cheat else self._timerscheat
        for t in timers:
            if not t.check(dt0):
                continue

            t.params.owner.notify_timer(t, t.lastwhen, *t.args, **t.kwargs)

            if t.params.strategies:
                for strat in runstrats:
                    strat.notify_timer(t, t.lastwhen, *t.args, **t.kwargs)
