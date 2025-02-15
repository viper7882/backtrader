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

import collections
from copy import copy
from datetime import date, datetime, timedelta
import threading

from backtrader.feed import DataBase
from backtrader import (TimeFrame, num2date, date2num, Broker_or_Exchange_Base,
                        Order, Buy_Order, Sell_Order, OrderBase, OrderData)
from backtrader.utils.py3 import bytes, with_metaclass, MAXFLOAT
from backtrader.metabase import MetaParams
from backtrader.commission_info import CommInfoBase
from backtrader.position import Position
from backtrader.accounts_or_stores import oandastore
from backtrader.utils import AutoDict, AutoOrderedDict


class OandaCommInfo(CommInfoBase):
    def get_value_size(self, size, price):
        # In real life the margin approaches the price
        return abs(size) * price

    def get_operating_cost(self, size, price):
        '''Returns the needed amount of cash an operation would cost'''
        # Same reasoning as above
        return abs(size) * price


class MetaOandaBroker(Broker_or_Exchange_Base.__class__):
    def __init__(cls, name, bases, dct):
        '''Class has already been created ... register'''
        # Initialize the class
        super(MetaOandaBroker, cls).__init__(name, bases, dct)
        oandastore.OandaStore.Broker_or_Exchange_Cls = cls


class OandaBroker(with_metaclass(MetaOandaBroker, Broker_or_Exchange_Base)):
    '''Broker implementation for Oanda.

    This class maps the orders/positions from Oanda to the
    internal API of ``backtrader``.

    Params:

      - ``use_positions`` (default:``True``): When connecting to the broker_or_exchange
        provider use the existing positions to kickstart the broker_or_exchange.

        Set to ``False`` during instantiation to disregard any existing
        position
    '''
    params = (
        ('use_positions', True),
        ('commission', OandaCommInfo(mult=1.0, stock_like=False)),
    )

    def __init__(self, **kwargs):
        super(OandaBroker, self).__init__()

        self.o = oandastore.OandaStore(**kwargs)

        self.orders = collections.OrderedDict()  # orders by order id
        self.notifs = collections.deque()  # holds orders which are notified

        self.opending = collections.defaultdict(list)  # pending transmission
        self.brackets = dict()  # confirmed brackets

        self.starting_cash = self.cash = 0.0
        self.starting_value = self.value = 0.0
        self.positions = collections.defaultdict(Position)

    def start(self):
        super(OandaBroker, self).start()
        self.o.start(broker_or_exchange=self)
        self.starting_cash = self.cash = cash = self.o.get_cash()
        self.starting_value = self.value = self.o.get_value()

        if self.p.use_positions:
            for p in self.o.get_positions():
                print('position for instrument:', p['instrument'])
                is_sell = p['side'] == 'sell'
                size = p['units']
                if is_sell:
                    size = -size
                price = p['avgPrice']
                self.positions[p['instrument']] = Position(size, price)

    def data_started(self, datafeed):
        pos = self.get_position(datafeed)

        if pos.size < 0:
            order = Sell_Order(datafeed=datafeed,
                               size=pos.size, price=pos.price,
                               execution_type=Order.Market,
                               simulated=True)

            order.add_commission_info(self.get_commission_info(datafeed))
            order.execute(0, pos.size, pos.price,
                          0, 0.0, 0.0,
                          pos.size, 0.0, 0.0,
                          0.0, 0.0,
                          pos.size, pos.price)

            order.completed()
            self.notify(order)

        elif pos.size > 0:
            order = Buy_Order(datafeed=datafeed,
                              size=pos.size, price=pos.price,
                              execution_type=Order.Market,
                              simulated=True)

            order.add_commission_info(self.get_commission_info(datafeed))
            order.execute(0, pos.size, pos.price,
                          0, 0.0, 0.0,
                          pos.size, 0.0, 0.0,
                          0.0, 0.0,
                          pos.size, pos.price)

            order.completed()
            self.notify(order)

    def stop(self):
        super(OandaBroker, self).stop()
        self.o.stop()

    def get_cash(self, force=False):
        # This call cannot block if no answer is available from oanda
        self.cash = cash = self.o.get_cash()
        return cash

    def get_value(self, datafeeds=None):
        self.value = self.o.get_value()
        return self.value

    def get_position(self, datafeed, clone=True):
        # return self.o.getposition(datafeed._dataname, clone=clone)
        pos = self.positions[datafeed._dataname]
        if clone:
            pos = pos.clone()

        return pos

    def orderstatus(self, order):
        o = self.orders[order.ref]
        return o.status

    def _submit(self, oref):
        order = self.orders[oref]
        order.submit(self)
        self.notify(order)
        for o in self._bracketnotif(order):
            o.submit(self)
            self.notify(o)

    def _reject(self, oref):
        order = self.orders[oref]
        order.reject(self)
        self.notify(order)
        self._bracketize(order, cancel=True)

    def _accept(self, oref):
        order = self.orders[oref]
        order.accept()
        self.notify(order)
        for o in self._bracketnotif(order):
            o.accept(self)
            self.notify(o)

    def _cancel(self, oref):
        order = self.orders[oref]
        order.cancel()
        self.notify(order)
        self._bracketize(order, cancel=True)

    def _expire(self, oref):
        order = self.orders[oref]
        order.expire()
        self.notify(order)
        self._bracketize(order, cancel=True)

    def _bracketnotif(self, order):
        pref = getattr(order.parent, 'ref', order.ref)  # parent ref or self
        br = self.brackets.get(pref, None)  # to avoid recursion
        return br[-2:] if br is not None else []

    def _bracketize(self, order, cancel=False):
        pref = getattr(order.parent, 'ref', order.ref)  # parent ref or self
        br = self.brackets.pop(pref, None)  # to avoid recursion
        if br is None:
            return

        if not cancel:
            if len(br) == 3:  # all 3 orders in place, parent was filled
                br = br[1:]  # discard index 0, parent
                for o in br:
                    o.activate()  # simulate activate for children
                self.brackets[pref] = br  # not done - reinsert children

            elif len(br) == 2:  # filling a children
                oidx = br.index(order)  # find index to filled (0 or 1)
                self._cancel(br[1 - oidx].ref)  # cancel remaining (1 - 0 -> 1)
        else:
            # Any cancellation cancel the others
            for o in br:
                if o.alive():
                    self._cancel(o.ref)

    def _fill(self, oref, size, price, ttype, **kwargs):
        order = self.orders[oref]

        if not order.alive():  # can be a bracket
            pref = getattr(order.parent, 'ref', order.ref)
            if pref not in self.brackets:
                msg = ('Order fill received for {}, with price {} and size {} '
                       'but order is no longer alive and is not a bracket. '
                       'Unknown situation')
                msg.format(order.ref, price, size)
                self.put_notification(msg, order, price, size)
                return

            # [main, stopside, takeside], neg idx to array are -3, -2, -1
            if ttype == 'STOP_LOSS_FILLED':
                order = self.brackets[pref][-2]
            elif ttype == 'TAKE_PROFIT_FILLED':
                order = self.brackets[pref][-1]
            else:
                msg = ('Order fill received for {}, with price {} and size {} '
                       'but order is no longer alive and is a bracket. '
                       'Unknown situation')
                msg.format(order.ref, price, size)
                self.put_notification(msg, order, price, size)
                return

        datafeed = order.datafeed
        pos = self.get_position(datafeed, clone=False)
        position_size, position_average_price, opened, closed = pos.update(
            size, price)

        commission_info = self.get_commission_info(datafeed)

        closed_value = closed_commission = 0.0
        opened_value = opened_commission = 0.0
        margin = profit_and_loss_amount = 0.0

        order.execute(datafeed.datetime[0], size, price,
                      closed, closed_value, closed_commission,
                      opened, opened_value, opened_commission,
                      margin, profit_and_loss_amount,
                      position_size, position_average_price)

        if order.executed.remaining_size:
            order.partial()
            self.notify(order)
        else:
            order.completed()
            self.notify(order)
            self._bracketize(order)

    def _transmit(self, order):
        oref = order.ref
        pref = getattr(order.parent, 'ref', oref)  # parent ref or self

        if order.transmit:
            if oref != pref:  # children order
                # Put parent in orders dict, but add stopside and takeside
                # to order creation. Return the takeside order, to have 3s
                takeside = order  # alias for clarity
                parent, stopside = self.opending.pop(pref)
                for o in parent, stopside, takeside:
                    self.orders[o.ref] = o  # write them down

                self.brackets[pref] = [parent, stopside, takeside]
                self.o.order_create(parent, stopside, takeside)
                return takeside  # parent was already returned

            else:  # Parent order, which is not being transmitted
                self.orders[order.ref] = order
                return self.o.order_create(order)

        # Not transmitting
        self.opending[pref].append(order)
        return order

    def buy(self, owner, datafeed,
            size, price=None, price_limit=None,
            execution_type=None, valid=None, tradeid=0, oco=None,
            trailing_amount=None, trailing_percent=None,
            parent=None, transmit=True,
            **kwargs):

        order = Buy_Order(owner=owner, datafeed=datafeed,
                          size=size, price=price, pricelimit=price_limit,
                          execution_type=execution_type, valid=valid, tradeid=tradeid,
                          trailing_amount=trailing_amount, trailing_percent=trailing_percent,
                          parent=parent, transmit=transmit)

        order.add_info(**kwargs)
        order.add_commission_info(self.get_commission_info(datafeed))
        return self._transmit(order)

    def sell(self, owner, datafeed,
             size, price=None, price_limit=None,
             execution_type=None, valid=None, tradeid=0, oco=None,
             trailing_amount=None, trailing_percent=None,
             parent=None, transmit=True,
             **kwargs):

        order = Sell_Order(owner=owner, datafeed=datafeed,
                           size=size, price=price, pricelimit=price_limit,
                           execution_type=execution_type, valid=valid, tradeid=tradeid,
                           trailing_amount=trailing_amount, trailing_percent=trailing_percent,
                           parent=parent, transmit=transmit)

        order.add_info(**kwargs)
        order.add_commission_info(self.get_commission_info(datafeed))
        return self._transmit(order)

    def cancel(self, order):
        o = self.orders[order.ref]
        if order.status == Order.Cancelled:  # already cancelled
            return

        return self.o.order_cancel(order)

    def notify(self, order):
        self.notifs.append(order.clone())

    def get_notification(self):
        if not self.notifs:
            return None

        return self.notifs.popleft()

    def next(self):
        self.notifs.append(None)  # mark notification boundary
