#!/usr/bin/env python

import datetime
import boto


class TendenceGuesser:
    def __init__(self):
        pass

    def guess(self):
        pass

class CPUTendenceGuesser:
    def __init__(self, ag_name, lower, upper):
        self.cloudwatch = boto.connect_cloudwatch()
        self.upper = upper - 3
        self.lower = lower + 3
        self.ag_name = ag_name

    def avg(self, l):
        return sum(l) / len(l)

    def guess(self, last_action=None):
        end = datetime.datetime.utcnow()
        start = end - datetime.timedelta(minutes=10)

        stats = self.cloudwatch.get_metric_statistics(60, start, end, 'CPUUtilization', 'AWS/EC2', 'Maximum', {'AutoScalingGroupName': self.ag_name})
        raw_stats = [x['Maximum'] for x in stats]

        half = len(raw_stats) / 2
        old = raw_stats[:half]
        new = raw_stats[half:]

        if len(filter(lambda x: x > self.upper, new)) > 2:
            return 1

        if len(filter(lambda x: x < self.lower, new)) > 2:
            return -1

        return 0
