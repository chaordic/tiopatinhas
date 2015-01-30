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
import simplejson as json
from collections import defaultdict
from boto import ec2
from boto.ec2 import autoscale
from boto.ec2 import elb
from boto.exception import EC2ResponseError

logging.basicConfig(format='%(asctime)s %(name)s %(levelname)s %(message)s')
logger = logging.getLogger("main")
logger.setLevel(logging.DEBUG)

class AutoScaleInfoException(Exception):
    pass

class AutoScaleInfo:
    def __init__(self, autoscale_group_name, region):
        self.autoscale = boto.ec2.autoscale.connect_to_region(region)
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
    def __init__(self, side_group, debug=False, region=None, user_data=None, conf_file="tp.conf", az=None):
        self.logger = logging.getLogger(side_group)
        if debug:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)

        self.conf = defaultdict(dict)
        try:
            with open(conf_file, 'r') as f:
                self.conf = json.loads(f.read())
        except IOError:
            self.logger.error("Configuration file " + conf_file + " not found.")
            sys.exit(2)

        self.max_price = self.conf.get("max_price", {"c1.xlarge": "0.750"})
        self.spot_type = self.conf.get("spot_type", "c1.xlarge")
        self.emergency_type = self.conf.get("emergency_type", "c1.xlarge")
        self.tags = self.conf.get("tags", {})
        self.region = region or self.conf.get("region", "us-east-1") #parameter has precedence over config file

        if az:
            self.placement = self.region + az 
        else:
            self.placement = self.conf.get("placement", "us-east-1c")
        self.side_group = side_group
        self.tapping_group = AutoScaleInfo(self.side_group, self.region)

        self.started = False
        self.target = None
        self.last_change = 0
        self.previous_as_count = None

        self.bids = []
        self.live = []
        self.emergency = []

        self.ec2 = boto.ec2.connect_to_region(self.region)
        self.elb = boto.ec2.elb.connect_to_region(self.region)

        self.guesser = cw.CPUTendenceGuesser(self.tapping_group.name, self.conf.get("lower_cpu", 30), self.conf.get("upper_cpu", 50), self.conf.get("lower_threshold", 2), self.conf.get("upper_threshold", 2))

        self.user_data = user_data
        user_data_file = self.conf.get("user_data_file", None)
        if not user_data and user_data_file:
            try:
                with open(user_data_file) as f:
                    self.user_data = f.read()
            except IOError:
                self.logger.warn("Could not read user data file: %s. Will launch instances without user data." % (user_data_file))

    def refresh(self):
        self.tapping_group = AutoScaleInfo(self.side_group, self.region)
        self.guess_target()
        if self.previous_as_count != self.managed_by_autoscale():
            self.logger.info(">> refresh(): autoscale instance count changed from %s to %s" % (self.previous_as_count, self.managed_by_autoscale()))
            if self.previous_as_count != None:
                self.last_change = time.time()
            self.previous_as_count = self.managed_by_autoscale()

    def guess_target(self):
        if not self.started:
            self.target = min(self.managed_instances(), self.managed_by_autoscale()) # follow autoscale if stopped :)
            return

        if self.target == None:
            self.target = self.managed_instances()
        previous = self.target

        # How many instances we should keep running
        if time.time() - self.last_change > 360:
            candidate = self.managed_instances()
            bias = self.guesser.guess()
            self.logger.debug("Bias: " + str(bias))

            if len(self.live) == candidate:
                candidate += bias

            # At most one more than autoscale or one less
            if candidate - self.tapping_group.desired_capacity > 1:
                candidate = self.tapping_group.desired_capacity + 1
            elif candidate - self.tapping_group.desired_capacity < -1:
                candidate = self.tapping_group.desired_capacity - 1

            # Never less than one
            if candidate < 1:
                candidate = 1

            max_candidates = self.conf.get("max_candidates", 6)
            if candidate > max_candidates:
                candidate = max_candidates

            self.logger.debug("Current candidate for target instances: " + str(candidate))

            if candidate != previous:
                self.logger.debug(">> guess_target(): changed target from %s to %s" % (previous, candidate))
                self.target = candidate



    def get_target(self):
        return self.target

    def managed_by_autoscale(self):
        return int(self.tapping_group.desired_capacity)

    def valid_bids(self):
        return [x for x in self.bids if x.state in ('active', 'open')]

    def managed_instances(self):
        return len(self.valid_bids()) + len(self.live) + len(self.emergency)

    def live_or_emergency(self):
        return len(self.live) + len(self.emergency)

    def ready_instances(self):
        return [x for x in self.bids if x.state == 'active']

    def live_instances(self):
        return self.live

    def buy(self, amount=1):
        tapping_group = self.tapping_group

        ami = self.ec2.get_image(tapping_group.image_id)
        for c in range(amount):
            r = ami.run(security_groups = tapping_group.security_groups,
                    instance_type = self.emergency_type,
                    placement = self.placement,
                    user_data = self.user_data)
            self.logger.info(">> buy(): purchased 1 on-demand instance")
            time.sleep(3)
            instance = r.instances[0]

            while 1:
                try:
                    instance.add_tag("tp:group", tapping_group.name)
                    break
                except Exception, e:
                    traceback.print_exc()
                    time.sleep(3)

            self.attach_instance(instance, "OD")

    def bid(self, force=False):
        if not force and time.time() - self.last_change < 600:
            self.logger.info("bid(): last change was too recent, skipping bid")
            time.sleep(10)
            return

        tapping_group = self.tapping_group

        request = self.ec2.request_spot_instances(
                price = self.max_price[self.spot_type],
                image_id = tapping_group.image_id,
                count = 1,
                type = "one-time",
                placement = self.placement,
                security_groups = tapping_group.security_groups,
                user_data = self.user_data,
                instance_type = self.spot_type,
                monitoring_enabled = True)
        while 1:
            try:
                request[0].add_tag('tp:tag', self.side_group)
                break
            except Exception, e:
                traceback.print_exc()
                time.sleep(3)

        self.logger.info(">> bid(): created 1 bid of %s for %s" % (self.spot_type, self.max_price[self.spot_type]))
        self.last_change = time.time()

        self.bids.append(request)

    def check_alive(self, spot_request):
        all_instances = self.ec2.get_all_instances()
        for instance in all_instances:
            inst = instance.instances[0]

            if inst.id == spot_request.instance_id and inst.state == "running":
                try:
                    health_check_url = "https://%s/%s" % (inst.dns_name, self.conf.get("health_check_path", "")) 
                    webob = urlopen(health_check_url)
                    response = webob.getcode()
                    self.logger.debug("Checking instance %s health on url %s. Response: %d" % (inst.id, health_check_url, response))
                    if response == 200:
                        return True
                    return False
                except:
                    return False
        return False

    def attach_instance(self, instance_or_spot, infix):
        lbnames = self.tapping_group.load_balancers
        lbs = self.elb.get_all_load_balancers(load_balancer_names=lbnames)

        instance_id = getattr(instance_or_spot, 'instance_id', None) or instance_or_spot.id

        tags = self.tags.copy()
        tags['Name'] = "%s %s %s" % (self.conf.get("instance_name", "instance"), infix, self.side_group)
        self.ec2.create_tags([instance_id], tags)

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
            self.logger.info(">> maybe_promote(): %s not active?" % spot_request)
            return

        if self.check_alive(spot_request):
            self.logger.info(">> maybe_promote(): %s is alive, promoting" % spot_request)

            self.attach_instance(spot_request, "TP")
            self.bids.remove(spot_request)
            self.live.append(spot_request)
            self.last_change = time.time()
            self.logger.info(">> maybe_promote(): %s promoted, now live" % spot_request)

    def maybe_replace(self):
        for instance in self.emergency:
            self.logger.debug("self.proximity(instance): " + str(self.proximity(instance)))
            if self.proximity(instance) < 10 and self.proximity(instance) > 2 and self.managed_instances() <= self.get_target():
                self.logger.info(">> maybe_replace(): attempting to replace %s" % (instance.id))
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
                    self.logger.info(">> maybe_demote(): removing emergency instance %s" % (instance.id))
                    self.dettach_instance(instance)
                    self.ec2.terminate_instances([instance.id])
                    self.emergency.remove(instance)
                    return True
            return False

        if self.managed_instances() <= self.get_target():
            return False

        for bid in self.valid_bids():
            if bid.state == "open":
                self.logger.info(">> demote(): %s is open, removing" % bid)
                bid.cancel()
                self.bids.remove(bid)
                return True

        self.live.sort(key=self.proximity)

        if self.proximity(self.live[0]) < 3 or not self.started:
            self.logger.info(">> demote(): %s is live, removing" % self.live[0])
            self.dettach_instance(self.live[0])
            self.last_change = time.time()
            time.sleep(5)
            self.live[0].cancel()
            self.ec2.terminate_instances([self.live[0].instance_id])
            time.sleep(1)
            self.live = self.live[1:]
            return True
        else:
            self.logger.info(">> demotion too far off, postponing (%s minutes)" % (self.proximity(self.live[0])))

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
                try:
                    # Some times some dead instances get stuck on LB and boto lib doesn't know how to treat it
                    # This make sure that instance is alive and avoid bug on get_all_instances method
                    instance_status = self.ec2.get_all_instance_status(instance_ids=[instance.id])
                    if len(instance_status) > 0 and instance_status[0].state_name == u'running':
                        running_in_lb.append(instance.id)
                    else:
                        self.dettach_instance(instance)
                except EC2ResponseError as inst:
                    if inst.error_code == "InvalidInstanceID.NotFound":
                        self.logger.warn("LB with invalid instance: %s" + instance.id)
                        self.dettach_instance(instance)



        all_instances_infos = self.ec2.get_all_instances(instance_ids=running_in_lb)
        all_instances_ids = [x.instances[0].id for x in all_instances_infos if x.instances[0].state not in ('terminated', 'shutting-down')]

        for req in reqs:
            tp_tag = req.tags.get('tp:tag', None)
            if not tp_tag or tp_tag != self.side_group:
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
                    self.attach_instance(instance, "OD")

    ''' Prepares this TPManager to stop by not launching new machines
        and gradually remove old machines.
        
        This manager loop will only stop when both the autoscaling group
        and the TP manager has zero instances running.
    '''
    def stop(self):
        self.started = False

    def start(self):
        self.started = True

    def print_state(self):
        self.logger.debug("*** Current state:")
        self.logger.debug("Managed by Autoscale: " + str(self.managed_by_autoscale()))
        self.logger.debug("Managed by TP: " + str(self.managed_instances()))
        self.logger.debug("Target: " + str(self.get_target()))
        self.logger.debug("Live: " +  ", ".join([x.instance_id for x in self.live_instances()]))
        self.logger.debug("Emergency: " + ", ".join([x.id for x in self.emergency]))
 
    def run(self):
        self.start()
        self.previous_managed = 0
        self.logger.info("Starting Tio Patinhas")
        while self.started or self.managed_instances() > 0:
            try:
                self.save_money()
            except Exception, e:
                logger.exception(e)
                time.sleep(10) # protect if Amazon f...ails us

            flush_output()
            time.sleep(20)
        self.logger.debug("Stopped running.")

    def save_money(self):
        self.logger.debug("Refreshing state...")
        self.load_state()
        self.refresh()
        self.print_state()

        if self.started and self.previous_managed > 0 and self.live_or_emergency() == 0:
            self.logger.warn(">> market crashed! launching %s %s instances" % (self.previous_managed, self.emergency_type))
            self.buy(self.previous_managed)
            self.load_state()

        if self.emergency:
            self.maybe_replace()

        if self.managed_instances() < self.get_target():
            self.bid()
            self.load_state()

        for new in self.ready_instances():
            self.maybe_promote(new)

        self.maybe_demote()
        self.previous_managed = self.live_or_emergency()

def flush_output():
    sys.stdout.flush()
    sys.stderr.flush()

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

    flush_output()

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
   -v, --verbose                   Verbose mode
"""

    try:
        opts, args = getopt.getopt(sys.argv[1:], "g:dv", ["group=", "daemonize", "verbose"])
    except getopt.GetoptError, err:
        logger.error(str(err))
        usage()
        sys.exit(2)

    group = None
    do_daemonize = False
    verbose = False

    for o, a in opts:
        if o in ("-g", "--group"):
            group = a
        elif o in ("-v", "--verbose"):
            verbose = True
        elif o in ("-d", "--daemonize"):
            daemonize = True
        else:
            assert False, "Unhandled option"

    if do_daemonize:
        daemonize()

    if not group:
        logger.error("no autoscale group defined")
        usage()
        sys.exit(2)

    tp = TPManager(group, verbose)
    tp.run()
