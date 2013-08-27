# tiopatinhas #

## Overview ##

tiopatinhas (TP) is a companion for AWS's Auto Scaling. It attaches itself to an
Availability Group and adds resources bought in Amazon's Spot market.

As we can lose those instances at any time (due to market conditions),
tiopatinhas only allows itself to provide about 50% of the total number of
running instances.

Other features include:

* efficient use of resources. tiopatinhas is aware of Amazon's one-hour
billing cycles and has protections against "flapping"
* crash recovery: in case there is a market crash, tiopatinhas can acquire
instances on the regular OnDemand market
* fail-safe design: tiopatinhas fails "up". If the process crashes, the worse
thing that can happen is extra servers being left in the cluster. Amazon's
Autoscaling rules are not modified at all and can take over at any time.

Our theory of operations is that even when the system is live, each server is
actually about 50% idle so that the system can responde to changes in access
patterns. How much you can commit to Spot Instances is correlated to how low you
keep your load during normal system operations. Needless to say, you shouldn't
use Spot Instances in systems which are not fault tolerant.

## Getting Started ##

### Before starting ###

1. Make sure the boto python package is installed in your system. If you're using debian or ubuntu you can install it by typing: 'sudo pip install boto'.
2. Make sure your AWS credentials are specified in a boto configuration file (typically ~/.boto). Instruction on how to setup this file can be found here: https://code.google.com/p/boto/wiki/BotoConfig

### Configuring tio patinhas ###

* Copy the template conf file (tp.conf.template) to tp/tp.conf so that the script can read it and make the changes according to your needs. Tio patinhas currently supports the following properties:

    * *max_price:* A map from instance types to max prices. TP will use the prices specified in this map to bid for instances of that type in the spot market.
    * *max_candidates:* The maximum number of instances TP will manage.
    * *instance_name:* The prefix that will be used by TP to name managed instances.
    * *region:* The AWS region where the AutoScaling instance is located.
    * *placement:* The AWS availability zone where TP instances will be launched.
    * *lower_cpu:* The AutoScaling CPU treshold rule for scaling down.
    * *upper_cpu:* The AutoScaling CPU treshold rule for scaling up.
    * *lower_treshold:* The amount of measurements below the *lower_cpu* TP will consider before scaling down. _(advanced)_
    * *lower_treshold:* The amount of measurements above the *upper_cpu* TP will consider before scaling up. _(advanced)_
    * *tags:* A map containing custom metadata tags that must assigned to TP instances. _(optional)_ (more info: http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/Using_Tags.html) 
    * *user_data_file* An optional script or data that must be supplied to the instance on startup. _(optional)_ (more info: http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/AESDG-chapter-instancedata.html)

### Executing tio patinhas ###

* Once the tp/tp.conf file is ready, execute tiopatinhas issuing the following command:
    * _python tp.py -g \<AutoScalingGroupName\>_ (this command must currently be executed from the "tp" folder)
        * You must additionally supply options "-v" for verbose mode or "-d" for daemon mode.
