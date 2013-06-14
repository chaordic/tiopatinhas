#!/usr/bin/env python

import boto
from urllib import urlopen
import time
import datetime
import cw
import os
import traceback
import logging
import sys

USER_DATA_TEMPLATE = """\
#chaordic-config
name: %(name)s
aws_key: %(aws_key)s
aws_secret: %(aws_secret)s
load_balancers: %(loadbalancer)s"""

logging.basicConfig(format='%(asctime)s %(name)s %(levelname)s %(message)s')
logger = logging.getLogger("tp")
logger.setLevel(logging.DEBUG)

class AutoScaleInfoException(Exception):
    pass


class AutoScaleInfo:
    def __init__(self, autoscale_group_name):
        self.autoscale = boto.connect_autoscale()
        ags = self.autoscale.get_all_groups()
        self.name = autoscale_group_name

        try:
            self.ag = [x for x in ags if x.name == self.name][0]
        except:
            raise ValueError("Couldn't retrieve autoscale group info for %s" % autoscale_group_name)

        try:
            lcs = self.autoscale.get_all_launch_configurations(names=[self.ag.launch_config_name])
            self.lc = lcs[0]
        except:
            raise ValueError("Couldn't retrive LaunchConfiguration for %s" % autoscale_group_name)

        self.instance_type = self.lc.instance_type
        self.image_id = self.lc.image_id
        self.security_groups = self.lc.security_groups

        self.load_balancers = self.ag.load_balancers
        self.desired_capacity = self.ag.desired_capacity


    def __repr__(self):
        return "<AutoScaleInfo Group:%s>" % self.name


class TPManager:
    # TODO: move to conf
    MAX_PRICE = { "c1.xlarge": "0.900" }

    def __init__(self, side_group):
        self.side_group = side_group
        self.tapping_group = AutoScaleInfo(side_group)

        self.target = None
        self.last_change = 0
        self.previous_as_count = None

        self.bids = []
        self.live = []
        self.emergency = []

        self.ec2 = boto.connect_ec2()
        self.elb = boto.connect_elb()

        self.guesser = cw.CPUTendenceGuesser(self.tapping_group.name, 45, 27)

    def refresh(self):
        self.tapping_group = AutoScaleInfo(self.side_group)
        self.guess_target()
        if self.previous_as_count != self.managed_by_autoscale():
            logger.info(">> refresh(): autoscale instance count changed from %s to %s" % (self.previous_as_count, self.managed_by_autoscale()))
            if self.previous_as_count != None:
                self.last_change = time.time()

            self.previous_as_count = self.managed_by_autoscale()

    def guess_target(self):
        if self.target == None:
            self.target = self.managed_instances()

        previous = self.target
        # How many instances we should keep running
        if time.time() - self.last_change > 360:
            candidate = self.managed_instances()
            bias = self.guesser.guess()
            logger.debug("Bias: " + str(bias))

            if len(self.live) == candidate:
                candidate += bias
            logger.debug("Candidate " + str(candidate))

            # At most one more than autoscale or one less
            if candidate - self.tapping_group.desired_capacity > 1:
                candidate = self.tapping_group.desired_capacity + 1
            elif candidate - self.tapping_group.desired_capacity < -1:
                candidate = self.tapping_group.desired_capacity - 1

            # Never less than one
            if candidate < 1:
                candidate = 1
            if candidate > 6:
                candidate = 6
            logger.debug("Candidate " + str(candidate))

            if candidate != previous:
                logger.debug(">> guess_target(): changed target from %s to %s" % (previous, candidate))
                self.target = candidate

    def get_target(self):
        return self.target

    def managed_by_autoscale(self):
        return int(self.tapping_group.desired_capacity)

    def valid_bids(self):
        return [x for x in self.bids if x.state in ('active', 'open')]

    def managed_instances(self):
        return len(self.valid_bids()) + len(self.live) + len(self.emergency)

    def ready_instances(self):
        return [x for x in self.bids if x.state == 'active']

    def live_instances(self):
        return self.live

    def buy(self, amount=1):
        tapping_group = self.tapping_group

        user_data_fields = {
            "loadbalancer": ",".join(self.tapping_group.load_balancers),
            "name": "OD instance %s" % self.tapping_group.name,
            "aws_key": os.getenv("AWS_ACCESS_KEY_ID"),
            "aws_secret": os.getenv("AWS_SECRET_ACCESS_KEY"),
        }

        user_data = USER_DATA_TEMPLATE % (user_data_fields)

        ami = self.ec2.get_image(tapping_group.image_id)
        for c in range(amount):
            r = ami.run(security_groups = tapping_group.security_groups,
                instance_type = tapping_group.instance_type,
                placement = "us-west-1a",
                user_data = user_data)
            logger.info(">> buy(): purchased 1 on-demand instance")
            time.sleep(3)
            instance = r.instances[0]

            while 1:
                try:
                    instance.add_tag("tp:group", tapping_group.name)
                    break
                except Exception, e:
                    traceback.print_exc()
                    time.sleep(3)

            self.attach_instance(instance)

    def bid(self, force=False):
        if not force and time.time() - self.last_change < 600:
            logger.info("bid(): last change was too recent, skipping bid")
            time.sleep(10)
            return
        tapping_group = self.tapping_group

        user_data_fields = {
            "loadbalancer": ",".join(self.tapping_group.load_balancers),
            "name": "TP instance %s" % self.tapping_group.name,
            "aws_key": os.getenv("AWS_ACCESS_KEY_ID"),
            "aws_secret": os.getenv("AWS_SECRET_ACCESS_KEY"),
        }

        user_data = USER_DATA_TEMPLATE % (user_data_fields)
        request = self.ec2.request_spot_instances(
            price = self.MAX_PRICE[tapping_group.instance_type],
            image_id = tapping_group.image_id,
            count = 1,
            type = "one-time",
            placement = "us-west-1a",
            security_groups = tapping_group.security_groups,
            user_data = user_data,
            instance_type = tapping_group.instance_type)
        while 1:
            try:
                request[0].add_tag('tp:tag', self.side_group)
                break
            except Exception, e:
                traceback.print_exc()
                time.sleep(3)

        logger.info(">> bid(): created 1 bid")
        self.last_change = time.time()

        self.bids.append(request)

    def user_data(self):
        return "SELF-MANAGED\nload_balancers=%s\n" % (",".join(self.tapping_group.load_balancers))

    def check_alive(self, spot_request):
        all_instances = self.ec2.get_all_instances()
        for instance in all_instances:
            inst = instance.instances[0]
            if inst.id == spot_request.instance_id and inst.state == "running":
                try:
                    webob = urlopen("http://%s/" % inst.dns_name)
                    response = webob.getcode()
                    if response == 200:
                        return True
                    return False
                except:
                    return False
        return False

    def attach_instance(self, instance_or_spot):
        lbnames = self.tapping_group.load_balancers
        lbs = self.elb.get_all_load_balancers(load_balancer_names=lbnames)

        instance_id = getattr(instance_or_spot, 'instance_id', None) or instance_or_spot.id

        for lb in lbs:
            lb.register_instances(instance_id)

    def dettach_instance(self, instance_or_spot):
        lbnames = self.tapping_group.load_balancers
        lbs = self.elb.get_all_load_balancers(load_balancer_names=lbnames)

        instance_id = getattr(instance_or_spot, 'instance_id', None) or instance_or_spot.id

        for lb in lbs:
            lb.deregister_instances(instance_id)

    def maybe_promote(self, spot_request):
        if spot_request.state != "active":
            logger.info(">> maybe_promote(): %s not active?" % spot_request)
            return

        if self.check_alive(spot_request):
            logger.info(">> maybe_promote(): %s is alive, promoting" % spot_request)

            self.attach_instance(spot_request)
            self.bids.remove(spot_request)
            self.live.append(spot_request)
            self.last_change = time.time()
            logger.info(">> maybe_promote(): %s promoted, now live" % spot_request)

    def maybe_replace(self):
        for instance in self.emergency:
            logger.info("self.proximity(instance): " + str(self.proximity(instance)))
            if self.proximity(instance) < 10 and self.proximity(instance) > 2 and self.managed_instances() <= self.get_target():
                logger.info(">> maybe_replace(): attempting to replace %s" % (instance.id))
                self.bid(force=True)

            self.load_state()

    def proximity(self, instance_or_spot):
        if hasattr(instance_or_spot, 'instance_id'):
            instance_info = self.ec2.get_all_instances(instance_ids=[instance_or_spot.instance_id])[0]
            instance = instance_info.instances[0]
        else:
            instance = instance_or_spot

        minute = int(instance.launch_time.split(":")[1])
        minute_now = datetime.datetime.now().minute
        o = minute - minute_now
        if o < -1:
            o = (minute + 60) - minute_now
        return o

    def maybe_demote(self):
        # First remove open, unfulfilled bids
        # Then remove open, but not yet live
        # Finally, remove any

        # In case we are in an emergency state:
        # If we have a server in an emergency state and no bids are open, kill a
        # server
        if self.emergency:
            for instance in self.emergency:
                if self.proximity(instance) < 10 and self.proximity(instance) > 3 and not self.valid_bids():
                    logger.info(">> maybe_demote(): removing emergency instance %s" % (instance.id))
                    self.ec2.terminate_instances([instance.id])
                    self.emergency.remove(instance)
                    return True
            return False

        if self.managed_instances() <= self.get_target():
            return False

        for bid in self.valid_bids():
            if bid.state == "open":
                logger.info(">> demote(): %s is open, removing" % bid)
                bid.cancel()
                self.bids.remove(bid)
                return True

        self.live.sort(key=self.proximity)

        if self.proximity(self.live[0]) < 3:
            logger.info(">> demote(): %s is live, removing" % self.live[0])
            self.dettach_instance(self.live[0])
            self.last_change = time.time()
            time.sleep(5)
            self.live[0].cancel()
            self.ec2.terminate_instances([self.live[0].instance_id])
            time.sleep(1)
            self.live = self.live[1:]
            return True
        else:
            logger.info(">> demotion too far off, postponing (%s minutes)" % (self.proximity(self.live[0])))

        return False

    def load_state(self):
        self.bids = []
        self.live = []
        self.emergency = []

        lbnames = self.tapping_group.load_balancers
        reqs = self.ec2.get_all_spot_instance_requests()

        lbs = self.elb.get_all_load_balancers(load_balancer_names=lbnames)
        running_in_lb = []

        for lb in lbs:
            for instance in lb.instances:
                running_in_lb.append(instance.id)

        all_instances_infos = self.ec2.get_all_instances(instance_ids=running_in_lb)
        all_instances_ids = [x.instances[0].id for x in all_instances_infos if x.instances[0].state not in ('terminated', 'shutting-down')]

        for req in reqs:
            tp_name = req.tags.get('tp:name', None)
            if tp_name:
                continue
            if not req.instance_id in running_in_lb:
                self.bids.append(req)
            else:
                self.live.append(req)

        all_r = self.ec2.get_all_instances()
        for r in all_r:
            for instance in r.instances:
                if instance.tags.get('tp:group', None) == self.tapping_group.name and instance.state not in ('terminated', 'shutting-down'):
                    self.emergency.append(instance)
                    self.attach_instance(instance)

    def run(self):
        previous_managed = 0
        while 1:
            self.load_state()
            self.refresh()
            managed = self.managed_instances()
            target = self.get_target()
            logger.debug("Managed by Autoscale: " + str(self.managed_by_autoscale()))
            logger.debug("Managed by TP: " + str(managed))
            logger.debug("Target: " + str(target))
            logger.debug("Live: " +  ", ".join([x.instance_id for x in self.live_instances()]))
            logger.debug("Emergency: " + ", ".join([x.id for x in self.emergency]))
            if previous_managed > 0 and managed == 0:
                logger.warn(">> market crashed! launching %s instances" % previous_managed)
                self.buy(previous_managed)
                self.load_state()
                managed = self.managed_instances()

            if self.emergency:
                self.maybe_replace()

            if managed < target:
                self.bid()
                self.load_state()
                managed = self.managed_instances()

            for new in self.ready_instances():
                self.maybe_promote(new)

            self.maybe_demote()
            previous_managed = managed
            time.sleep(20)


def daemonize():
    pid = os.fork()
    if pid > 0:
        sys.exit()

    os.chdir("/")
    os.setsid()
    pid = os.fork()
    if pid > 0:
        sys.exit()

    in_ = file("/dev/null", 'r')
    out = file("/dev/null", 'a+')
    err = file("/dev/null", 'a+')

    sys.stdour.flush()
    sys.stderr.flush()

    os.dup2(in_.fileno(), sys.stdin.fileno())
    os.dup2(out.fileno(), sys.stdout.fileno())
    os.dup2(err.fileno(), sys.stderr.fileno())

if __name__ == '__main__':
    import getopt

    def usage():
        print """\
Usage: tp [OPTIONS]

tp is a long-standing process that attaches itself to an availability group on
AWS. It attempts to buy cheap instances on the Spot Market and add those to the
availability's group load balancer.

   -g, --group                     Availability group to attach to
   -d, --daemonize                 Detach from the terminal
"""

    try:
        opts, args = getopt.getopt(sys.argv[1:], "g:d", ["group=", "daemonize"])
    except getopt.GetoptError, err:
        logger.error(str(err))
        usage()
        sys.exit(2)

    group = None
    do_daemonize = False

    for o, a in opts:
        if o in ("-g", "--group"):
            group = a
        elif o in ("-d", "--daemonize"):
            daemonize = True
        else:
            assert False, "Unhandled option"

    if do_daemonize:
        daemonize()

    tp = TPManager(group)
    tp.run()

