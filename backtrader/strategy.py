#!/usr/bin389/env python
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

import collections
import copy
import datetime
import inspect
import itertools
import operator

from .utils.py3 import (filter, keys, integer_types, iteritems, itervalues,
                        map, MAXINT, string_types, with_metaclass)

import backtrader as bt
from .lineiterator import LineIterator, StrategyBase
from .lineroot import LineSingle
from .lineseries import LineSeriesStub
from .metabase import ItemCollection, findowner
from .trade import Trade
from .utils import OrderedDict, AutoOrderedDict, AutoDictList


class MetaStrategy(StrategyBase.__class__):
    _indcol = dict()

    def __new__(meta, name, bases, dct):
        # Hack to support original method name for notify_order
        if 'notify' in dct:
            # rename 'notify' to 'notify_order'
            dct['notify_order'] = dct.pop('notify')
        if 'notify_operation' in dct:
            # rename 'notify' to 'notify_order'
            dct['notify_trade'] = dct.pop('notify_operation')

        return super(MetaStrategy, meta).__new__(meta, name, bases, dct)

    def __init__(cls, name, bases, dct):
        '''
        Class has already been created ... register subclasses
        '''
        # Initialize the class
        super(MetaStrategy, cls).__init__(name, bases, dct)

        if not cls.aliased and \
           name != 'Strategy' and not name.startswith('_'):
            cls._indcol[name] = cls

    def donew(cls, *args, **kwargs):
        _obj, args, kwargs = super(MetaStrategy, cls).donew(*args, **kwargs)

        # Find the owner and store it
        _obj.env = _obj.cerebro = cerebro = findowner(_obj, bt.Cerebro)

        # INFO: If not run from cerebro, cerebro would be None
        if _obj.cerebro:
            _obj._id = cerebro._next_stid()

        return _obj, args, kwargs

    def dopreinit(cls, _obj, *args, **kwargs):
        _obj, args, kwargs = \
            super(MetaStrategy, cls).dopreinit(_obj, *args, **kwargs)

        # INFO: If not run from cerebro, cerebro would be None
        if _obj.cerebro:
            _obj.broker_or_exchange = _obj.env.broker_or_exchange
            _obj._sizer = bt.sizers.FixedSize()
            _obj._orders = list()
            _obj._orderspending = list()
            _obj._trades = collections.defaultdict(AutoDictList)
            _obj._trades_pending = list()

            _obj.stats = _obj.observers = ItemCollection()
            _obj.analyzers = ItemCollection()
            _obj._alnames = collections.defaultdict(itertools.count)
            _obj.writers = list()

            _obj._slave_analyzers = list()

            _obj._tradehistoryon = False

        return _obj, args, kwargs

    def dopostinit(cls, _obj, *args, **kwargs):
        _obj, args, kwargs = \
            super(MetaStrategy, cls).dopostinit(_obj, *args, **kwargs)

        # INFO: If not run from cerebro, cerebro would be None
        if _obj.cerebro is not None:
            _obj._sizer.set(_obj, _obj.broker_or_exchange)

        return _obj, args, kwargs


class Strategy(with_metaclass(MetaStrategy, StrategyBase)):
    '''
    Base class to be subclassed for user defined strategies.
    '''

    _ltype = LineIterator.StratType

    csv = True
    _oldsync = False  # update clock using old methodology : datafeed 0

    # keep the latest delivered datafeed date in the line
    lines = ('datetime',)

    def qbuffer(self, savemem=0, replaying=False):
        '''Enable the memory saving schemes. Possible values for ``savemem``:

          0: No savings. Each lines object keeps in memory all values

          1: All lines objects save memory, using the strictly minimum needed

        Negative values are meant to be used when plotting is required:

          -1: Indicators at Strategy Level and Observers do not enable memory
              savings (but anything declared below it does)

          -2: Same as -1 plus activation of memory saving for any indicators
              which has declared *plotinfo.plot* as False (will not be plotted)
        '''
        if savemem < 0:
            # Get any attribute which labels itself as Indicator
            for ind in self._lineiterators[self.IndType]:
                subsave = isinstance(ind, (LineSingle,))
                if not subsave and savemem < -1:
                    subsave = not ind.plotinfo.plot
                ind.qbuffer(savemem=subsave)

        elif savemem > 0:
            for datafeed in self.datafeeds:
                datafeed.qbuffer(replaying=replaying)

            for line in self.lines:
                line.qbuffer(savemem=1)

            # Save in all object types depending on the strategy
            for itcls in self._lineiterators:
                for it in self._lineiterators[itcls]:
                    it.qbuffer(savemem=1)

    def _set_period(self):
        dataids = [id(datafeed) for datafeed in self.datafeeds]

        _dminperiods = collections.defaultdict(list)
        for lineiter in self._lineiterators[LineIterator.IndType]:
            # if multiple datafeeds are used and multiple timeframes the larger
            # timeframe may place larger time constraints in calling next.
            clk = getattr(lineiter, '_clock', None)
            if clk is None:
                clk = getattr(lineiter._owner, '_clock', None)
                if clk is None:
                    continue

            while True:
                if id(clk) in dataids:
                    break  # already top-level clock (datafeed)

                # See if the current clock has higher level clocks
                clk2 = getattr(clk, '_clock', None)
                if clk2 is None:
                    clk2 = getattr(clk._owner, '_clock', None)

                if clk2 is None:
                    break  # if no clock found, bail out

                clk = clk2  # keep the ref and try to go up the hierarchy

            if clk is None:
                continue  # no clock found, go to next

            # LineSeriesStup wraps a line and the clock is the wrapped line and
            # no the wrapper itself.
            if isinstance(clk, LineSeriesStub):
                clk = clk.lines[0]

            _dminperiods[clk].append(lineiter._min_period)

        self._min_periods = list()
        for datafeed in self.datafeeds:

            # Do not only consider the datafeed as clock but also its lines which
            # may have been individually passed as clock references and
            # discovered as clocks above

            # Initialize with datafeed min period if any
            dlminperiods = _dminperiods[datafeed]

            for l in datafeed.lines:  # search each line for min periods
                if l in _dminperiods:
                    dlminperiods += _dminperiods[l]  # found, add it

            # keep the reference to the line if any was found
            _dminperiods[datafeed] = [
                max(dlminperiods)] if dlminperiods else []

            dminperiod = max(_dminperiods[datafeed] or [datafeed._min_period])
            self._min_periods.append(dminperiod)

        # Set the minperiod
        minperiods = \
            [x._min_period for x in self._lineiterators[LineIterator.IndType]]
        self._min_period = max(minperiods or [self._min_period])

    def _addwriter(self, writer):
        '''
        Unlike the other _addxxx functions this one receives an instance
        because the writer works at cerebro level and is only passed to the
        strategy to simplify the logic
        '''
        self.writers.append(writer)

    def _add_indicator(self, indcls, *indargs, **indkwargs):
        indcls(*indargs, **indkwargs)

    def _addanalyzer_slave(self, ancls, *anargs, **ankwargs):
        '''Like _add_analyzer but meant for observers (or other entities) which
        rely on the output of an analyzer for the datafeed. These analyzers have
        not been added by the user and are kept separate from the main
        analyzers

        Returns the created analyzer
        '''
        analyzer = ancls(*anargs, **ankwargs)
        self._slave_analyzers.append(analyzer)
        return analyzer

    def _getanalyzer_slave(self, idx):
        return self._slave_analyzers.append[idx]

    def _add_analyzer(self, ancls, *anargs, **ankwargs):
        anname = ankwargs.pop('_name', '') or ancls.__name__.lower()
        nsuffix = next(self._alnames[anname])
        anname += str(nsuffix or '')  # 0 (first instance) gets no suffix
        analyzer = ancls(*anargs, **ankwargs)
        self.analyzers.append(analyzer, anname)

    def _add_observer(self, multi, obscls, *obsargs, **obskwargs):
        obsname = obskwargs.pop('obsname', '')
        if not obsname:
            obsname = obscls.__name__.lower()

        if not multi:
            newargs = list(itertools.chain(self.datafeeds, obsargs))
            obs = obscls(*newargs, **obskwargs)
            self.stats.append(obs, obsname)
            return

        setattr(self.stats, obsname, list())
        l = getattr(self.stats, obsname)

        for datafeed in self.datafeeds:
            obs = obscls(datafeed, *obsargs, **obskwargs)
            l.append(obs)

    def _get_min_per_status(self):
        # check the min period status connected to datafeeds
        dlens = map(operator.sub, self._min_periods, map(len, self.datafeeds))
        self._min_per_status = min_per_status = max(dlens)
        return min_per_status

    def prenext_open(self):
        pass

    def nextstart_open(self):
        self.next_open()

    def next_open(self):
        pass

    def _oncepost_open(self):
        min_per_status = self._min_per_status
        if min_per_status < 0:
            self.next_open()
        elif min_per_status == 0:
            self.nextstart_open()  # only called for the 1st value
        else:
            self.prenext_open()

    def _oncepost(self, dt):
        for indicator in self._lineiterators[LineIterator.IndType]:
            if len(indicator._clock) > len(indicator):
                indicator.advance()

        if self._oldsync:
            # Strategy has not been reset, the line is there
            self.advance()
        else:
            # strategy has been reset to beginning. advance step by step
            self.forward()

        self.lines.datetime[0] = dt
        self._notify()

        min_per_status = self._get_min_per_status()
        if min_per_status < 0:
            self.next()
        elif min_per_status == 0:
            self.nextstart()  # only called for the 1st value
        else:
            self.prenext()

        self._next_analyzers(min_per_status, once=True)
        self._next_observers(min_per_status, once=True)

        self.clear()

    def _clk_update(self):
        if self._oldsync:
            clk_len = super(Strategy, self)._clk_update()
            self.lines.datetime[0] = max(datafeed.datetime[0]
                                         for datafeed in self.datafeeds if len(d))
            return clk_len

        newdlens = [len(datafeed) for datafeed in self.datafeeds]
        if any(nl > l for l, nl in zip(self._dlens, newdlens)):
            self.forward()

        self.lines.datetime[0] = max(datafeed.datetime[0]
                                     for datafeed in self.datafeeds if len(datafeed))
        self._dlens = newdlens

        return len(self)

    def _next_open(self):
        min_per_status = self._min_per_status
        if min_per_status < 0:
            self.next_open()
        elif min_per_status == 0:
            self.nextstart_open()  # only called for the 1st value
        else:
            self.prenext_open()

    def _next(self, account_or_store, instrument, debug=False):
        super(Strategy, self)._next(account_or_store, instrument, debug=debug)

        min_per_status = self._get_min_per_status()
        self._next_analyzers(min_per_status)
        self._next_observers(min_per_status)

        self.clear()

    def _next_observers(self, min_per_status, once=False):
        for observer in self._lineiterators[LineIterator.ObsType]:
            for analyzer in observer._analyzers:
                if min_per_status < 0:
                    analyzer._next()
                elif min_per_status == 0:
                    analyzer._nextstart()  # only called for the 1st value
                else:
                    analyzer._prenext()

            if once:
                if len(self) > len(observer):
                    if self._oldsync:
                        observer.advance()
                    else:
                        observer.forward()

                if min_per_status < 0:
                    observer.next()
                elif min_per_status == 0:
                    observer.nextstart()  # only called for the 1st value
                elif len(observer):
                    observer.prenext()
            else:
                try:
                    observer._next(None, None)
                except TypeError:
                    observer._next()

    def _next_analyzers(self, min_per_status, once=False):
        for analyzer in self.analyzers:
            if min_per_status < 0:
                analyzer._next()
            elif min_per_status == 0:
                analyzer._nextstart()  # only called for the 1st value
            else:
                analyzer._prenext()

    def _settz(self, tz):
        self.lines.datetime._settz(tz)

    def _start(self):
        self._set_period()

        for analyzer in itertools.chain(self.analyzers, self._slave_analyzers):
            analyzer._start()

        for obs in self.observers:
            if not isinstance(obs, list):
                obs = [obs]  # support of multi-datafeed observers

            for o in obs:
                o._start()

        # change operators to stage 2
        self._stage2()

        self._dlens = [len(datafeed) for datafeed in self.datafeeds]

        self._min_per_status = MAXINT  # start in prenext

        self.start()

    def start(self):
        '''Called right before the backtesting is about to be started.'''
        pass

    def getwriterheaders(self):
        self.indobscsv = [self]

        indobs = itertools.chain(
            self.getindicators_lines(), self.getobservers())
        self.indobscsv.extend(filter(lambda x: x.csv, indobs))

        headers = list()

        # prepare the indicators/observers datafeed headers
        for iocsv in self.indobscsv:
            name = iocsv.plotinfo.plotname or iocsv.__class__.__name__
            headers.append(name)
            headers.append('len')
            headers.extend(iocsv.getlinealiases())

        return headers

    def getwritervalues(self):
        values = list()

        for iocsv in self.indobscsv:
            name = iocsv.plotinfo.plotname or iocsv.__class__.__name__
            values.append(name)
            lio = len(iocsv)
            values.append(lio)
            if lio:
                values.extend(map(lambda l: l[0], iocsv.lines.itersize()))
            else:
                values.extend([''] * iocsv.lines.size())

        return values

    def getwriterinfo(self):
        wrinfo = AutoOrderedDict()

        wrinfo['Params'] = self.p._getkwargs()

        sections = [
            ['Indicators', self.getindicators_lines()],
            ['Observers', self.getobservers()]
        ]

        for sectname, sectitems in sections:
            sinfo = wrinfo[sectname]
            for item in sectitems:
                itname = item.__class__.__name__
                sinfo[itname].Lines = item.lines.getlinealiases() or None
                sinfo[itname].Params = item.p._getkwargs() or None

        ainfo = wrinfo.Analyzers

        # Internal Value Analyzer
        ainfo.Value.Begin = self.broker_or_exchange.starting_cash
        ainfo.Value.End = self.broker_or_exchange.get_value()

        # no slave analyzers for writer
        for aname, analyzer in self.analyzers.getitems():
            ainfo[aname].Params = analyzer.p._getkwargs() or None
            ainfo[aname].Analysis = analyzer.get_analysis()

        return wrinfo

    def _stop(self):
        self.stop()

        for analyzer in itertools.chain(self.analyzers, self._slave_analyzers):
            analyzer._stop()

        # change operators back to stage 1 - allows reuse of datafeeds
        self._stage1()

    def stop(self):
        '''Called right before the backtesting is about to be stopped'''
        pass

    def set_tradehistory(self, onoff=True):
        self._tradehistoryon = onoff

    def clear(self):
        self._orders.extend(self._orderspending)
        self._orderspending = list()
        self._trades_pending = list()

    def _add_notification(self, order, quicknotify=False):
        if not order.p.simulated:
            self._orderspending.append(order)

        if quicknotify:
            qorders = [order]
            qtrades = []

        if not order.executed.size:
            if quicknotify:
                self._notify(qorders=qorders, qtrades=qtrades)
            return

        tradedata = order.datafeed._compensate
        if tradedata is None:
            tradedata = order.datafeed

        datatrades = self._trades[tradedata][order.tradeid]
        if not datatrades:
            trade = Trade(datafeed=tradedata, tradeid=order.tradeid,
                          historyon=self._tradehistoryon)
            datatrades.append(trade)
        else:
            trade = datatrades[-1]

        for execution_bit in order.executed.iterate_pending():
            if execution_bit is None:
                break

            if execution_bit.closed:
                trade.update(order,
                             execution_bit.closed,
                             execution_bit.price,
                             execution_bit.closed_value,
                             execution_bit.closed_commission,
                             execution_bit.profit_and_loss_amount,
                             commission_info=order.commission_info)

                if trade.isclosed:
                    self._trades_pending.append(copy.copy(trade))
                    if quicknotify:
                        qtrades.append(copy.copy(trade))

            # Update it if needed
            if execution_bit.opened:
                if trade.isclosed:
                    trade = Trade(datafeed=tradedata, tradeid=order.tradeid,
                                  historyon=self._tradehistoryon)
                    datatrades.append(trade)

                trade.update(order,
                             execution_bit.opened,
                             execution_bit.price,
                             execution_bit.opened_value,
                             execution_bit.opened_commission,
                             execution_bit.profit_and_loss_amount,
                             commission_info=order.commission_info)

                # This extra check covers the case in which different tradeid
                # orders have put the position down to 0 and the next order
                # "opens" a position but "closes" the trade
                if trade.isclosed:
                    self._trades_pending.append(copy.copy(trade))
                    if quicknotify:
                        qtrades.append(copy.copy(trade))

            if trade.justopened:
                self._trades_pending.append(copy.copy(trade))
                if quicknotify:
                    qtrades.append(copy.copy(trade))

        if quicknotify:
            self._notify(qorders=qorders, qtrades=qtrades)

    def _notify(self, qorders=[], qtrades=[]):
        if self.cerebro.p.quicknotify:
            # need to know if quicknotify is on, to not reprocess pendingorders
            # and pendingtrades, which have to exist for things like observers
            # which look into it
            procorders = qorders
            proctrades = qtrades
        else:
            procorders = self._orderspending
            proctrades = self._trades_pending

        for order in procorders:
            if order.execution_type != order.Historical or order.histnotify:
                self.notify_order(order)
            for analyzer in itertools.chain(self.analyzers,
                                            self._slave_analyzers):
                analyzer._notify_order(order)

        for trade in proctrades:
            self.notify_trade(trade)
            for analyzer in itertools.chain(self.analyzers,
                                            self._slave_analyzers):
                analyzer._notify_trade(trade)

        if qorders:
            return  # cash is notified on a regular basis

        cash = self.broker_or_exchange.get_cash()
        value = self.broker_or_exchange.get_value()
        fundvalue = self.broker_or_exchange.fundvalue
        fundshares = self.broker_or_exchange.fundshares

        self.notify_cashvalue(cash, value)
        self.notify_fund(cash, value, fundvalue, fundshares)
        for analyzer in itertools.chain(self.analyzers, self._slave_analyzers):
            analyzer._notify_cashvalue(cash, value)
            analyzer._notify_fund(cash, value, fundvalue, fundshares)

    def add_timer(self, when,
                  offset=datetime.timedelta(), repeat=datetime.timedelta(),
                  weekdays=[], weekcarry=False,
                  monthdays=[], monthcarry=True,
                  allow=None,
                  tzdata=None, cheat=False,
                  *args, **kwargs):
        '''
        **Note**: can be called during ``__init__`` or ``start``

        Schedules a timer to invoke either a specified callback or the
        ``notify_timer`` of one or more strategies.

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
            instance or a ``datafeed`` instance.

            ``None``: ``when`` is interpreted at face value (which translates
            to handling it as if it where UTC even if it's not)

            ``pytz`` instance: ``when`` will be interpreted as being specified
            in the local time specified by the timezone instance.

            ``datafeed`` instance: ``when`` will be interpreted as being
            specified in the local time specified by the ``tz`` parameter of
            the datafeed instance.

            **Note**: If ``when`` is either ``SESSION_START`` or
              ``SESSION_END`` and ``tzdata`` is ``None``, the 1st *datafeed*
              in the system (aka ``self.datafeed0``) will be used as the reference
              to find out the session times.

          - ``cheat`` (default ``False``) if ``True`` the timer will be called
            before the broker_or_exchange has a chance to evaluate the orders. This opens
            the chance to issue orders based on opening price for example right
            before the session starts

          - ``*args``: any extra args will be passed to ``notify_timer``

          - ``**kwargs``: any extra kwargs will be passed to ``notify_timer``

        Return Value:

          - The created timer

        '''
        return self.cerebro._add_timer(
            owner=self, when=when, offset=offset, repeat=repeat,
            weekdays=weekdays, weekcarry=weekcarry,
            monthdays=monthdays, monthcarry=monthcarry,
            allow=allow,
            tzdata=tzdata, strats=False, cheat=cheat,
            *args, **kwargs)

    def notify_timer(self, timer, when, *args, **kwargs):
        '''Receives a timer notification where ``timer`` is the timer which was
        returned by ``add_timer``, and ``when`` is the calling time. ``args``
        and ``kwargs`` are any additional arguments passed to ``add_timer``

        The actual ``when`` time can be later, but the system may have not be
        able to call the timer before. This value is the timer value and no the
        system time.
        '''
        pass

    def notify_cashvalue(self, cash, value):
        '''
        Receives the current fund value, value status of the strategy's broker_or_exchange
        '''
        pass

    def notify_fund(self, cash, value, fundvalue, shares):
        '''
        Receives the current cash, value, fundvalue and fund shares
        '''
        pass

    def notify_order(self, order):
        '''
        Receives an order whenever there has been a change in one
        '''
        pass

    def notify_trade(self, trade):
        '''
        Receives a trade whenever there has been a change in one
        '''
        pass

    def notify_account_or_store(self, msg, *args, **kwargs):
        '''Receives a notification from a store provider'''
        pass

    def datafeed_notification(self, datafeed, status, *args, **kwargs):
        '''Receives a notification from datafeed'''
        pass

    def get_datafeed_names(self):
        '''
        Returns a list of the existing datafeed names
        '''
        return keys(self.env.datafeeds_by_name)

    def get_datafeed_by_name(self, name):
        '''
        Returns a given datafeed by name using the environment (cerebro)
        '''
        return self.env.datafeeds_by_name[name]

    def cancel(self, order):
        '''Cancels the order in the broker_or_exchange'''
        self.broker_or_exchange.cancel(order)

    def buy(self, datafeed=None,
            size=None, price=None, price_limit=None,
            execution_type=None, valid=None, tradeid=0, oco=None,
            trailing_amount=None, trailing_percent=None,
            parent=None, transmit=True,
            **kwargs):
        '''Create a buy (long) order and send it to the broker_or_exchange

          - ``datafeed`` (default: ``None``)

            For which datafeed the order has to be created. If ``None`` then the
            first datafeed in the system, ``self.datafeeds[0] or self.datafeed0`` (aka
            ``self.datafeed``) will be used

          - ``size`` (default: ``None``)

            Size to use (positive) of units of datafeed to use for the order.

            If ``None`` the ``sizer`` instance retrieved via ``getsizer`` will
            be used to determine the size.

          - ``price`` (default: ``None``)

            Price to use (live brokers may place restrictions on the actual
            format if it does not comply to minimum tick size requirements)

            ``None`` is valid for ``Market`` and ``Close`` orders (the market
            determines the price)

            For ``Limit``, ``StopMarket`` and ``StopLimit`` orders this value
            determines the trigger point (in the case of ``Limit`` the trigger
            is obviously at which price the order should be matched)

          - ``price_limit`` (default: ``None``)

            Only applicable to ``StopLimit`` orders. This is the price at which
            to set the implicit *Limit* order, once the *Stop* has been
            triggered (for which ``price`` has been used)

          - ``trailing_amount`` (default: ``None``)

            If the order type is StopTrail or StopTrailLimit, this is an
            absolute amount which determines the distance to the price (below
            for a Sell order and above for a buy order) to keep the trailing
            stop

          - ``trailing_percent`` (default: ``None``)

            If the order type is StopTrail or StopTrailLimit, this is a
            percentage amount which determines the distance to the price (below
            for a Sell order and above for a buy order) to keep the trailing
            stop (if ``trailing_amount`` is also specified it will be used)

          - ``execution_type`` (default: ``None``)

            Possible values:

            - ``Order.Market`` or ``None``. A market order will be executed
              with the next available price. In backtesting it will be the
              opening price of the next bar

            - ``Order.Limit``. An order which can only be executed at the given
              ``price`` or better

            - ``Order.StopMarket``. An order which is triggered at ``price`` and
              executed like an ``Order.Market`` order

            - ``Order.StopLimit``. An order which is triggered at ``price`` and
              executed as an implicit *Limit* order with price given by
              ``pricelimit``

            - ``Order.Close``. An order which can only be executed with the
              closing price of the session (usually during a closing auction)

            - ``Order.StopTrail``. An order which is triggered at ``price``
              minus ``trailing_amount`` (or ``trailing_percent``) and which is updated
              if the price moves away from the stop

            - ``Order.StopTrailLimit``. An order which is triggered at
              ``price`` minus ``trailing_amount`` (or ``trailing_percent``) and which
              is updated if the price moves away from the stop

          - ``valid`` (default: ``None``)

            Possible values:

              - ``None``: this generates an order that will not expire (aka
                *Good till cancel*) and remain in the market until matched or
                canceled. In reality brokers tend to impose a temporal limit,
                but this is usually so far away in time to consider it as not
                expiring

              - ``datetime.datetime`` or ``datetime.date`` instance: the date
                will be used to generate an order valid until the given
                datetime (aka *good till date*)

              - ``Order.DAY`` or ``0`` or ``timedelta()``: a day valid until
                the *End of the Session* (aka *day* order) will be generated

              - ``numeric value``: This is assumed to be a value corresponding
                to a datetime in ``matplotlib`` coding (the one used by
                ``backtrader``) and will used to generate an order valid until
                that time (*good till date*)

          - ``tradeid`` (default: ``0``)

            This is an internal value applied by ``backtrader`` to keep track
            of overlapping trades on the same asset. This ``tradeid`` is sent
            back to the *strategy* when notifying changes to the status of the
            orders.

          - ``oco`` (default: ``None``)

            Another ``order`` instance. This order will become part of an OCO
            (Order Cancel Others) group. The execution of one of the orders,
            immediately cancels all others in the same group

          - ``parent`` (default: ``None``)

            Controls the relationship of a group of orders, for example a buy
            which is bracketed by a high-side limit sell and a low side stop
            sell. The high/low side orders remain inactive until the parent
            order has been either executed (they become active) or is
            canceled/expires (the children are also canceled) bracket orders
            have the same size

          - ``transmit`` (default: ``True``)

            Indicates if the order has to be **transmitted**, ie: not only
            placed in the broker_or_exchange but also issued. This is meant for example to
            control bracket orders, in which one disables the transmission for
            the parent and 1st set of children and activates it for the last
            children, which triggers the full placement of all bracket orders.

          - ``**kwargs``: additional broker_or_exchange implementations may support extra
            parameters. ``backtrader`` will pass the *kwargs* down to the
            created order objects

            Example: if the 4 order execution types directly supported by
            ``backtrader`` are not enough, in the case of for example
            *Interactive Brokers* the following could be passed as *kwargs*::

              orderType='LIT', lmtPrice=10.0, auxPrice=9.8

            This would override the settings created by ``backtrader`` and
            generate a ``LIMIT IF TOUCHED`` order with a *touched* price of 9.8
            and a *limit* price of 10.0.

        Returns:
          - the submitted order

        '''
        if isinstance(datafeed, string_types):
            datafeed = self.get_datafeed_by_name(datafeed)

        datafeed = datafeed if datafeed is not None else self.datafeeds[0]
        size = size if size is not None else self.getsizing(
            datafeed, is_buy=True)

        if size:
            return self.broker_or_exchange.buy(
                self, datafeed,
                size=abs(size), price=price, price_limit=price_limit,
                execution_type=execution_type, valid=valid, tradeid=tradeid, oco=oco,
                trailing_amount=trailing_amount, trailing_percent=trailing_percent,
                parent=parent, transmit=transmit,
                **kwargs)

        return None

    def sell(self, datafeed=None,
             size=None, price=None, price_limit=None,
             execution_type=None, valid=None, tradeid=0, oco=None,
             trailing_amount=None, trailing_percent=None,
             parent=None, transmit=True,
             **kwargs):
        '''
        To create a sell (short) order and send it to the broker_or_exchange

        See the documentation for ``buy`` for an explanation of the parameters

        Returns: the submitted order
        '''
        if isinstance(datafeed, string_types):
            datafeed = self.get_datafeed_by_name(datafeed)

        datafeed = datafeed if datafeed is not None else self.datafeeds[0]
        size = size if size is not None else self.getsizing(
            datafeed, is_buy=False)

        if size:
            return self.broker_or_exchange.sell(
                self, datafeed,
                size=abs(size), price=price, price_limit=price_limit,
                execution_type=execution_type, valid=valid, tradeid=tradeid, oco=oco,
                trailing_amount=trailing_amount, trailing_percent=trailing_percent,
                parent=parent, transmit=transmit,
                **kwargs)

        return None

    def close(self, datafeed=None, size=None, **kwargs):
        '''
        Counters a long/short position closing it

        See the documentation for ``buy`` for an explanation of the parameters

        Note:

          - ``size``: automatically calculated from the existing position if
            not provided (default: ``None``) by the caller

        Returns: the submitted order
        '''
        if isinstance(datafeed, string_types):
            datafeed = self.get_datafeed_by_name(datafeed)
        elif datafeed is None:
            datafeed = self.datafeed

        possize = self.get_position(datafeed, self.broker_or_exchange).size
        size = abs(size if size is not None else possize)

        if possize > 0:
            return self.sell(datafeed=datafeed, size=size, **kwargs)
        elif possize < 0:
            return self.buy(datafeed=datafeed, size=size, **kwargs)

        return None

    def buy_bracket(self, datafeed=None, size=None, price=None, price_limit=None,
                    execution_type=bt.Order.Limit, valid=None, tradeid=0,
                    trailing_amount=None, trailing_percent=None, oargs={},
                    stopprice=None, stopexec=bt.Order.StopMarket, stopargs={},
                    limitprice=None, limitexec=bt.Order.Limit, limitargs={},
                    **kwargs):
        '''
        Create a bracket order group (low side - buy order - high side). The
        default behavior is as follows:

          - Issue a **buy** order with execution ``Limit``

          - Issue a *low side* bracket **sell** order with execution ``Stop``

          - Issue a *high side* bracket **sell** order with execution
            ``Limit``.

        See below for the different parameters

          - ``datafeed`` (default: ``None``)

            For which datafeed the order has to be created. If ``None`` then the
            first datafeed in the system, ``self.datafeeds[0] or self.datafeed0`` (aka
            ``self.datafeed``) will be used

          - ``size`` (default: ``None``)

            Size to use (positive) of units of datafeed to use for the order.

            If ``None`` the ``sizer`` instance retrieved via ``getsizer`` will
            be used to determine the size.

            **Note**: The same size is applied to all 3 orders of the bracket

          - ``price`` (default: ``None``)

            Price to use (live brokers may place restrictions on the actual
            format if it does not comply to minimum tick size requirements)

            ``None`` is valid for ``Market`` and ``Close`` orders (the market
            determines the price)

            For ``Limit``, ``StopMarket`` and ``StopLimit`` orders this value
            determines the trigger point (in the case of ``Limit`` the trigger
            is obviously at which price the order should be matched)

          - ``price_limit`` (default: ``None``)

            Only applicable to ``StopLimit`` orders. This is the price at which
            to set the implicit *Limit* order, once the *Stop* has been
            triggered (for which ``price`` has been used)

          - ``trailing_amount`` (default: ``None``)

            If the order type is StopTrail or StopTrailLimit, this is an
            absolute amount which determines the distance to the price (below
            for a Sell order and above for a buy order) to keep the trailing
            stop

          - ``trailing_percent`` (default: ``None``)

            If the order type is StopTrail or StopTrailLimit, this is a
            percentage amount which determines the distance to the price (below
            for a Sell order and above for a buy order) to keep the trailing
            stop (if ``trailing_amount`` is also specified it will be used)

          - ``execution_type`` (default: ``bt.Order.Limit``)

            Possible values: (see the documentation for the method ``buy``

          - ``valid`` (default: ``None``)

            Possible values: (see the documentation for the method ``buy``

          - ``tradeid`` (default: ``0``)

            Possible values: (see the documentation for the method ``buy``

          - ``oargs`` (default: ``{}``)

            Specific keyword arguments (in a ``dict``) to pass to the main side
            order. Arguments from the default ``**kwargs`` will be applied on
            top of this.

          - ``**kwargs``: additional broker_or_exchange implementations may support extra
            parameters. ``backtrader`` will pass the *kwargs* down to the
            created order objects

            Possible values: (see the documentation for the method ``buy``

            **Note**: this ``kwargs`` will be applied to the 3 orders of a
            bracket. See below for specific keyword arguments for the low and
            high side orders

          - ``stopprice`` (default: ``None``)

            Specific price for the *low side* stop order

          - ``stopexec`` (default: ``bt.Order.StopMarket``)

            Specific execution type for the *low side* order

          - ``stopargs`` (default: ``{}``)

            Specific keyword arguments (in a ``dict``) to pass to the low side
            order. Arguments from the default ``**kwargs`` will be applied on
            top of this.

          - ``limitprice`` (default: ``None``)

            Specific price for the *high side* stop order

          - ``stopexec`` (default: ``bt.Order.Limit``)

            Specific execution type for the *high side* order

          - ``limitargs`` (default: ``{}``)

            Specific keyword arguments (in a ``dict``) to pass to the high side
            order. Arguments from the default ``**kwargs`` will be applied on
            top of this.

        High/Low Side orders can be suppressed by using:

          - ``limitexec=None`` to suppress the *high side*

          - ``stopexec=None`` to suppress the *low side*

        Returns:

          - A list containing the 3 orders [order, stop side, limit side]

          - If high/low orders have been suppressed the return value will still
            contain 3 orders, but those suppressed will have a value of
            ``None``
        '''

        kargs = dict(size=size,
                     datafeed=datafeed, price=price, price_limit=price_limit, execution_type=execution_type,
                     valid=valid, tradeid=tradeid,
                     trailing_amount=trailing_amount, trailing_percent=trailing_percent)
        kargs.update(oargs)
        kargs.update(kwargs)
        kargs['transmit'] = limitexec is None and stopexec is None
        o = self.buy(**kargs)

        if stopexec is not None and stopprice is not None:
            # low side / stop
            kargs = dict(datafeed=datafeed, price=stopprice, execution_type=stopexec,
                         valid=valid, tradeid=tradeid)
            kargs.update(stopargs)
            kargs.update(kwargs)
            kargs['parent'] = o
            kargs['transmit'] = limitexec is None
            kargs['size'] = o.size
            ostop = self.sell(**kargs)
        else:
            ostop = None

        if limitexec is not None and limitprice is not None:
            # high side / limit
            kargs = dict(datafeed=datafeed, price=limitprice, execution_type=limitexec,
                         valid=valid, tradeid=tradeid)
            kargs.update(limitargs)
            kargs.update(kwargs)
            kargs['parent'] = o
            kargs['transmit'] = True
            kargs['size'] = o.size
            olimit = self.sell(**kargs)
        else:
            olimit = None

        return [o, ostop, olimit]

    def sell_bracket(self, datafeed=None,
                     size=None, price=None, price_limit=None,
                     execution_type=bt.Order.Limit, valid=None, tradeid=0,
                     trailing_amount=None, trailing_percent=None,
                     oargs={},
                     stopprice=None, stopexec=bt.Order.StopMarket, stopargs={},
                     limitprice=None, limitexec=bt.Order.Limit, limitargs={},
                     **kwargs):
        '''
        Create a bracket order group (low side - buy order - high side). The
        default behavior is as follows:

          - Issue a **sell** order with execution ``Limit``

          - Issue a *high side* bracket **buy** order with execution ``Stop``

          - Issue a *low side* bracket **buy** order with execution ``Limit``.

        See ``bracket_buy`` for the meaning of the parameters

        High/Low Side orders can be suppressed by using:

          - ``stopexec=None`` to suppress the *high side*

          - ``limitexec=None`` to suppress the *low side*

        Returns:

          - A list containing the 3 orders [order, stop side, limit side]

          - If high/low orders have been suppressed the return value will still
            contain 3 orders, but those suppressed will have a value of
            ``None``
        '''

        kargs = dict(size=size,
                     datafeed=datafeed, price=price, price_limit=price_limit, execution_type=execution_type,
                     valid=valid, tradeid=tradeid,
                     trailing_amount=trailing_amount, trailing_percent=trailing_percent)
        kargs.update(oargs)
        kargs.update(kwargs)
        kargs['transmit'] = limitexec is None and stopexec is None
        o = self.sell(**kargs)

        if stopexec is not None and stopprice is not None:
            # high side / stop
            kargs = dict(datafeed=datafeed, price=stopprice, execution_type=stopexec,
                         valid=valid, tradeid=tradeid)
            kargs.update(stopargs)
            kargs.update(kwargs)
            kargs['parent'] = o
            kargs['transmit'] = limitexec is None  # transmit if last
            kargs['size'] = o.size
            ostop = self.buy(**kargs)
        else:
            ostop = None

        if limitexec is not None and limitprice is not None:
            # low side / limit
            kargs = dict(datafeed=datafeed, price=limitprice, execution_type=limitexec,
                         valid=valid, tradeid=tradeid)
            kargs.update(limitargs)
            kargs.update(kwargs)
            kargs['parent'] = o
            kargs['transmit'] = True
            kargs['size'] = o.size
            olimit = self.buy(**kargs)
        else:
            olimit = None

        return [o, ostop, olimit]

    def order_target_size(self, datafeed=None, target=0, **kwargs):
        '''
        Place an order to rebalance a position to have final size of ``target``

        The current ``position`` size is taken into account as the start point
        to achieve ``target``

          - If ``target`` > ``pos.size`` -> buy ``target - pos.size``

          - If ``target`` < ``pos.size`` -> sell ``pos.size - target``

        It returns either:

          - The generated order

          or

          - ``None`` if no order has been issued (``target == position.size``)
        '''
        if isinstance(datafeed, string_types):
            datafeed = self.get_datafeed_by_name(datafeed)
        elif datafeed is None:
            datafeed = self.datafeed

        possize = self.get_position(datafeed, self.broker_or_exchange).size
        if not target and possize:
            return self.close(datafeed=datafeed, size=possize, **kwargs)

        elif target > possize:
            return self.buy(datafeed=datafeed, size=target - possize, **kwargs)

        elif target < possize:
            return self.sell(datafeed=datafeed, size=possize - target, **kwargs)

        return None  # no execution target == possize

    def order_target_value(self, datafeed=None, target=0.0, price=None, **kwargs):
        '''
        Place an order to rebalance a position to have final value of
        ``target``

        The current ``value`` is taken into account as the start point to
        achieve ``target``

          - If no ``target`` then close postion on datafeed
          - If ``target`` > ``value`` then buy on datafeed
          - If ``target`` < ``value`` then sell on datafeed

        It returns either:

          - The generated order

          or

          - ``None`` if no order has been issued
        '''

        if isinstance(datafeed, string_types):
            datafeed = self.get_datafeed_by_name(datafeed)
        elif datafeed is None:
            datafeed = self.datafeed

        possize = self.get_position(datafeed, self.broker_or_exchange).size
        if not target and possize:  # closing a position
            return self.close(datafeed=datafeed, size=possize, price=price, **kwargs)

        else:
            value = self.broker_or_exchange.get_value(datafeed=[datafeed])
            commission_info = self.broker_or_exchange.get_commission_info(
                datafeed)

            # Make sure a price is there
            price = price if price is not None else datafeed.close[0]

            if target > value:
                size = commission_info.get_size(price, target - value)
                return self.buy(datafeed=datafeed, size=size, price=price, **kwargs)

            elif target < value:
                size = commission_info.get_size(price, value - target)
                return self.sell(datafeed=datafeed, size=size, price=price, **kwargs)

        return None  # no execution size == possize

    def order_target_percent(self, datafeed=None, target=0.0, **kwargs):
        '''
        Place an order to rebalance a position to have final value of
        ``target`` percentage of current portfolio ``value``

        ``target`` is expressed in decimal: ``0.05`` -> ``5%``

        It uses ``order_target_value`` to execute the order.

        Example:
          - ``target=0.05`` and portfolio value is ``100``

          - The ``value`` to be reached is ``0.05 * 100 = 5``

          - ``5`` is passed as the ``target`` value to ``order_target_value``

        The current ``value`` is taken into account as the start point to
        achieve ``target``

        The ``position.size`` is used to determine if a position is ``long`` /
        ``short``

          - If ``target`` > ``value``
            - buy if ``pos.size >= 0`` (Increase a long position)
            - sell if ``pos.size < 0`` (Increase a short position)

          - If ``target`` < ``value``
            - sell if ``pos.size >= 0`` (Decrease a long position)
            - buy if ``pos.size < 0`` (Decrease a short position)

        It returns either:

          - The generated order

          or

          - ``None`` if no order has been issued (``target == position.size``)
        '''
        if isinstance(datafeed, string_types):
            datafeed = self.get_datafeed_by_name(datafeed)
        elif datafeed is None:
            datafeed = self.datafeed

        possize = self.get_position(datafeed, self.broker_or_exchange).size
        target *= self.broker_or_exchange.get_value()

        return self.order_target_value(datafeed=datafeed, target=target, **kwargs)

    def get_position(self, datafeed=None, broker_or_exchange=None):
        '''
        Returns the current position for a given datafeed in a given broker_or_exchange.

        If both are None, the main datafeed and the default broker_or_exchange will be used

        A property ``position`` is also available
        '''
        datafeed = datafeed if datafeed is not None else self.datafeeds[0]
        broker_or_exchange = broker_or_exchange or self.broker_or_exchange
        return broker_or_exchange.get_position(datafeed)

    position = property(get_position)

    def getpositionbyname(self, name=None, broker_or_exchange=None):
        '''
        Returns the current position for a given name in a given broker_or_exchange.

        If both are None, the main datafeed and the default broker_or_exchange will be used

        A property ``positionbyname`` is also available
        '''
        datafeed = self.datafeeds[0] if not name else self.get_datafeed_by_name(
            name)
        broker_or_exchange = broker_or_exchange or self.broker_or_exchange
        return broker_or_exchange.get_position(datafeed)

    positionbyname = property(getpositionbyname)

    def get_positions(self, broker_or_exchange=None):
        '''
        Returns the current by positions directly from the broker_or_exchange

        If the given ``broker_or_exchange`` is None, the default broker_or_exchange will be used

        A property ``positions`` is also available
        '''
        broker_or_exchange = broker_or_exchange or self.broker_or_exchange
        return broker_or_exchange.positions

    positions = property(get_positions)

    def getpositionsbyname(self, broker_or_exchange=None):
        '''
        Returns the current by name positions directly from the broker_or_exchange

        If the given ``broker_or_exchange`` is None, the default broker_or_exchange will be used

        A property ``positionsbyname`` is also available
        '''
        broker_or_exchange = broker_or_exchange or self.broker_or_exchange
        positions = broker_or_exchange.positions

        posbyname = collections.OrderedDict()
        for name, datafeed in iteritems(self.env.datafeeds_by_name):
            posbyname[name] = positions[datafeed]

        return posbyname

    positionsbyname = property(getpositionsbyname)

    def _addsizer(self, sizer, *args, **kwargs):
        if sizer is None:
            self.setsizer(bt.sizers.FixedSize())
        else:
            self.setsizer(sizer(*args, **kwargs))

    def setsizer(self, sizer):
        '''
        Replace the default (fixed stake) sizer
        '''
        self._sizer = sizer
        sizer.set(self, self.broker_or_exchange)
        return sizer

    def getsizer(self):
        '''
        Returns the sizer which is in used if automatic stake calculation is
        used

        Also available as ``sizer``
        '''
        return self._sizer

    sizer = property(getsizer, setsizer)

    def getsizing(self, datafeed=None, is_buy=True):
        '''
        Return the stake calculated by the sizer instance for the current
        situation
        '''
        datafeed = datafeed if datafeed is not None else self.datafeeds[0]
        return self._sizer.getsizing(datafeed, is_buy=is_buy)


class MetaSigStrategy(Strategy.__class__):

    def __new__(meta, name, bases, dct):
        # map user defined next to custom to be able to call own method before
        if 'next' in dct:
            dct['_next_custom'] = dct.pop('next')

        cls = super(MetaSigStrategy, meta).__new__(meta, name, bases, dct)

        # after class creation remap _next_catch to be next
        cls.next = cls._next_catch
        return cls

    def dopreinit(cls, _obj, *args, **kwargs):
        _obj, args, kwargs = \
            super(MetaSigStrategy, cls).dopreinit(_obj, *args, **kwargs)

        _obj._signals = collections.defaultdict(list)

        _datafeed = _obj.p._datafeed
        if _datafeed is None:
            _obj._dtarget = _obj.datafeed0
        elif isinstance(_datafeed, integer_types):
            _obj._dtarget = _obj.datafeeds[_datafeed]
        elif isinstance(_datafeed, string_types):
            _obj._dtarget = _obj.get_datafeed_by_name(_datafeed)
        elif isinstance(_datafeed, bt.LineRoot):
            _obj._dtarget = _datafeed
        else:
            _obj._dtarget = _obj.datafeed0

        return _obj, args, kwargs

    def dopostinit(cls, _obj, *args, **kwargs):
        _obj, args, kwargs = \
            super(MetaSigStrategy, cls).dopostinit(_obj, *args, **kwargs)

        for sigtype, sigcls, sigargs, sigkwargs in _obj.p.signals:
            _obj._signals[sigtype].append(sigcls(*sigargs, **sigkwargs))

        # Record types of signals
        _obj._longshort = bool(_obj._signals[bt.SIGNAL_LONGSHORT])

        _obj._long = bool(_obj._signals[bt.SIGNAL_LONG])
        _obj._short = bool(_obj._signals[bt.SIGNAL_SHORT])

        _obj._longexit = bool(_obj._signals[bt.SIGNAL_LONGEXIT])
        _obj._shortexit = bool(_obj._signals[bt.SIGNAL_SHORTEXIT])

        return _obj, args, kwargs


class SignalStrategy(with_metaclass(MetaSigStrategy, Strategy)):
    '''This subclass of ``Strategy`` is meant to to auto-operate using
    **signals**.

    *Signals* are usually indicators and the expected output values:

      - ``> 0`` is a ``long`` indication

      - ``< 0`` is a ``short`` indication

    There are 5 types of *Signals*, broken in 2 groups.

    **Main Group**:

      - ``LONGSHORT``: both ``long`` and ``short`` indications from this signal
        are taken

      - ``LONG``:
        - ``long`` indications are taken to go long
        - ``short`` indications are taken to *close* the long position. But:

          - If a ``LONGEXIT`` (see below) signal is in the system it will be
            used to exit the long

          - If a ``SHORT`` signal is available and no ``LONGEXIT`` is available
            , it will be used to close a ``long`` before opening a ``short``

      - ``SHORT``:
        - ``short`` indications are taken to go short
        - ``long`` indications are taken to *close* the short position. But:

          - If a ``SHORTEXIT`` (see below) signal is in the system it will be
            used to exit the short

          - If a ``LONG`` signal is available and no ``SHORTEXIT`` is available
            , it will be used to close a ``short`` before opening a ``long``

    **Exit Group**:

      This 2 signals are meant to override others and provide criteria for
      exitins a ``long``/``short`` position

      - ``LONGEXIT``: ``short`` indications are taken to exit ``long``
        positions

      - ``SHORTEXIT``: ``long`` indications are taken to exit ``short``
        positions

    **Order Issuing**

      Orders execution type is ``Market`` and validity is ``None`` (*Good until
      Canceled*)

    Params:

      - ``signals`` (default: ``[]``): a list/tuple of lists/tuples that allows
        the instantiation of the signals and allocation to the right type

        This parameter is expected to be managed through ``cerebro.add_signal``

      - ``_accumulate`` (default: ``False``): allow to enter the market
        (long/short) even if already in the market

      - ``_concurrent`` (default: ``False``): allow orders to be issued even if
        orders are already pending execution

      - ``_datafeed`` (default: ``None``): if multiple datafeeds are present in the
        system which is the target for orders. This can be

        - ``None``: The first datafeed in the system will be used

        - An ``int``: indicating the datafeed that was inserted at that position

        - An ``str``: name given to the datafeed when creating it (parameter
          ``name``) or when adding it cerebro with ``cerebro.add_datafeed(...,
          name=)``

        - A ``datafeed`` instance

    '''

    params = (
        ('signals', []),
        ('_accumulate', False),
        ('_concurrent', False),
        ('_datafeed', None),
    )

    def _start(self):
        self._sentinel = None  # sentinel for order concurrency
        super(SignalStrategy, self)._start()

    def signal_add(self, sigtype, signal):
        self._signals[sigtype].append(signal)

    def _notify(self, qorders=[], qtrades=[]):
        # Nullify the sentinel if done
        procorders = qorders or self._orderspending
        if self._sentinel is not None:
            for order in procorders:
                if order == self._sentinel and not order.alive():
                    self._sentinel = None
                    break

        super(SignalStrategy, self)._notify(qorders=qorders, qtrades=qtrades)

    def _next_catch(self):
        self._next_signal()
        if hasattr(self, '_next_custom'):
            self._next_custom()

    def _next_signal(self):
        if self._sentinel is not None and not self.p._concurrent:
            return  # order active and more than 1 not allowed

        sigs = self._signals
        nosig = [[0.0]]

        # Calculate current status of the signals
        ls_long = all(x[0] > 0.0 for x in sigs[bt.SIGNAL_LONGSHORT] or nosig)
        ls_short = all(x[0] < 0.0 for x in sigs[bt.SIGNAL_LONGSHORT] or nosig)

        l_enter0 = all(x[0] > 0.0 for x in sigs[bt.SIGNAL_LONG] or nosig)
        l_enter1 = all(x[0] < 0.0 for x in sigs[bt.SIGNAL_LONG_INV] or nosig)
        l_enter2 = all(x[0] for x in sigs[bt.SIGNAL_LONG_ANY] or nosig)
        l_enter = l_enter0 or l_enter1 or l_enter2

        s_enter0 = all(x[0] < 0.0 for x in sigs[bt.SIGNAL_SHORT] or nosig)
        s_enter1 = all(x[0] > 0.0 for x in sigs[bt.SIGNAL_SHORT_INV] or nosig)
        s_enter2 = all(x[0] for x in sigs[bt.SIGNAL_SHORT_ANY] or nosig)
        s_enter = s_enter0 or s_enter1 or s_enter2

        l_ex0 = all(x[0] < 0.0 for x in sigs[bt.SIGNAL_LONGEXIT] or nosig)
        l_ex1 = all(x[0] > 0.0 for x in sigs[bt.SIGNAL_LONGEXIT_INV] or nosig)
        l_ex2 = all(x[0] for x in sigs[bt.SIGNAL_LONGEXIT_ANY] or nosig)
        l_exit = l_ex0 or l_ex1 or l_ex2

        s_ex0 = all(x[0] > 0.0 for x in sigs[bt.SIGNAL_SHORTEXIT] or nosig)
        s_ex1 = all(x[0] < 0.0 for x in sigs[bt.SIGNAL_SHORTEXIT_INV] or nosig)
        s_ex2 = all(x[0] for x in sigs[bt.SIGNAL_SHORTEXIT_ANY] or nosig)
        s_exit = s_ex0 or s_ex1 or s_ex2

        # Use oppossite signales to start reversal (by closing)
        # but only if no "xxxExit" exists
        l_rev = not self._longexit and s_enter
        s_rev = not self._shortexit and l_enter

        # Opposite of individual long and short
        l_leav0 = all(x[0] < 0.0 for x in sigs[bt.SIGNAL_LONG] or nosig)
        l_leav1 = all(x[0] > 0.0 for x in sigs[bt.SIGNAL_LONG_INV] or nosig)
        l_leav2 = all(x[0] for x in sigs[bt.SIGNAL_LONG_ANY] or nosig)
        l_leave = l_leav0 or l_leav1 or l_leav2

        s_leav0 = all(x[0] > 0.0 for x in sigs[bt.SIGNAL_SHORT] or nosig)
        s_leav1 = all(x[0] < 0.0 for x in sigs[bt.SIGNAL_SHORT_INV] or nosig)
        s_leav2 = all(x[0] for x in sigs[bt.SIGNAL_SHORT_ANY] or nosig)
        s_leave = s_leav0 or s_leav1 or s_leav2

        # Invalidate long leave if longexit signals are available
        l_leave = not self._longexit and l_leave
        # Invalidate short leave if shortexit signals are available
        s_leave = not self._shortexit and s_leave

        # Take size and start logic
        size = self.get_position(self._dtarget).size
        if not size:
            if ls_long or l_enter:
                self._sentinel = self.buy(self._dtarget)

            elif ls_short or s_enter:
                self._sentinel = self.sell(self._dtarget)

        elif size > 0:  # current long position
            if ls_short or l_exit or l_rev or l_leave:
                # closing position - not relevant for concurrency
                self.close(self._dtarget)

            if ls_short or l_rev:
                self._sentinel = self.sell(self._dtarget)

            if ls_long or l_enter:
                if self.p._accumulate:
                    self._sentinel = self.buy(self._dtarget)

        elif size < 0:  # current short position
            if ls_long or s_exit or s_rev or s_leave:
                # closing position - not relevant for concurrency
                self.close(self._dtarget)

            if ls_long or s_rev:
                self._sentinel = self.buy(self._dtarget)

            if ls_short or s_enter:
                if self.p._accumulate:
                    self._sentinel = self.sell(self._dtarget)
