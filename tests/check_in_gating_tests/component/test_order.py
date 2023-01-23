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

import backtrader as bt
from backtrader import Order, Position


class FakeCommInfo(object):
    def get_value_size(self, size, price):
        return 0

    def profit_and_loss(self, size, price, newprice):
        return 0

    def get_operating_cost(self, size, price):
        return 0.0

    def get_commission_rate(self, size, price):
        return 0.0


class FakeData(object):
    '''
    Minimal interface to avoid errors when trade tries to get information from
    the data during the test
    '''

    def __len__(self):
        return 0

    @property
    def datetime(self):
        return [0.0]

    @property
    def close(self):
        return [0.0]


def _execute(position, order, size, price, partial):
    spread_in_ticks = 1

    # Find position and do a real update - accounting happens here
    pprice_orig = position.price
    position_size, position_average_price, opened, closed = position.update(
        size, price)

    comm_info = order.commission_info
    closed_value = comm_info.get_operating_cost(closed, pprice_orig)
    closed_commission = comm_info.get_commission_rate(closed, price)

    opened_value = comm_info.get_operating_cost(opened, price)
    opened_commission = comm_info.get_commission_rate(opened, price)

    profit_and_loss_amount = comm_info.profit_and_loss(
        -closed, pprice_orig, price)
    margin = comm_info.get_value_size(size, price)

    order.execute(order.datafeed.datetime[0],
                  size, price,
                  closed, closed_value, closed_commission,
                  opened, opened_value, opened_commission,
                  margin, profit_and_loss_amount, spread_in_ticks,
                  position_size, position_average_price)  # profit_and_loss_amount

    if partial:
        order.partial()
    else:
        order.completed()


def test_run(main=False):
    position = Position()
    comm_info = FakeCommInfo()
    order = bt.Buy_Order(datafeed=FakeData(),
                         size=100, price=1.0,
                         execution_type=bt.Order.Market,
                         simulated=True)
    order.add_commission_info(comm_info)

    # Test that partially updating order will maintain correct iterpending sequence
    # (Orders are cloned for each notification. The pending bits should be reported
    # related to the previous notification (clone))

    # Add two bits and validate we have two pending bits
    _execute(position, order, 10, 1.0, True)
    _execute(position, order, 20, 1.1, True)

    clone = order.clone()
    pending = clone.executed.get_pending()
    assert len(pending) == 2
    assert pending[0].size == 10
    assert pending[0].price == 1.0
    assert pending[1].size == 20
    assert pending[1].price == 1.1

    # Add additional two bits and validate we still have two pending bits after clone
    _execute(position, order, 30, 1.2, True)
    _execute(position, order, 40, 1.3, False)

    clone = order.clone()
    pending = clone.executed.get_pending()
    assert len(pending) == 2
    assert pending[0].size == 30
    assert pending[0].price == 1.2
    assert pending[1].size == 40
    assert pending[1].price == 1.3


if __name__ == '__main__':
    test_run(main=False)
