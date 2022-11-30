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

from .utils.py3 import with_metaclass

from .metabase import MetaParams

import inspect

class Sizer(with_metaclass(MetaParams, object)):
    '''This is the base class for *Sizers*. Any *sizer* should subclass this
    and override the ``_getsizing`` method

    Member Attribs:

      - ``strategy``: will be set by the strategy in which the sizer is working

        Gives access to the entire api of the strategy, for example if the
        actual data position would be needed in ``_getsizing``::

           position = self.strategy.getposition(data)

      - ``broker_or_exchange``: will be set by the strategy in which the sizer is working

        Gives access to information some complex sizers may need like portfolio
        value, ..
    '''
    strategy = None
    broker_or_exchange = None

    def getsizing(self, datafeeds, is_buy):
        commission_info = self.broker_or_exchange.get_commission_info(datafeeds)
        cash = self.broker_or_exchange.get_cash(force=True)
        return self._getsizing(commission_info, cash, datafeeds, is_buy)

    def _getsizing(self, commission_info, cash, datafeeds, is_buy):
        '''This method has to be overriden by subclasses of Sizer to provide
        the sizing functionality

        Params:
          - ``commission_info``: The CommissionInfo instance that contains
            information about the commission for the data and allows
            calculation of position value, operation cost, commision for the
            operation

          - ``cash``: current available cash in the *broker_or_exchange*

          - ``data``: target of the operation

          - ``is_buy``: will be ``True`` for *buy* operations and ``False``
            for *sell* operations

        The method has to return the actual size (an int) to be executed. If
        ``0`` is returned nothing will be executed.

        The absolute value of the returned value will be used

        '''
        raise NotImplementedError

    def set(self, strategy, broker_or_exchange):
        self.strategy = strategy
        self.broker_or_exchange = broker_or_exchange


SizerBase = Sizer  # alias for old naming
