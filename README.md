# tiopatinhas #

## Overview ##

*tiopatinhas* (tp) is a companion for AWS's Auto Scaling. It attaches itself to an
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

1. Make sure the boto python package is installed in your system. If you
use debian or ubuntu you can install it by typing: 'sudo pip install boto'.
2. Make sure your AWS credentials are specified in a boto configuration file
(typically ~/.boto). Instruction on how to setup this file can be found [here](https://code.google.com/p/boto/wiki/BotoConfig).
3. To run the setup, you may need to install [setuptools](https://setuptools.readthedocs.io/en/latest/)

### Configuring tiopatinhas ###

* Copy the template conf file (tp.conf.template) to tp/tp.conf so that the
script can read it and make the changes according to your needs. Tio patinhas
currently supports the following properties:

#### Mandatory Properties

* *max_price:* A map that specifies the maximum bid prices for each type
  of EC2 instance. TP will use the prices specified in this map to bid for
  instances of that type in the spot market.
* *max_candidates:* The maximum number of instances TP will manage.
* *instance_name:* The prefix that will be used by TP to name managed instances.
* *region:* The AWS region where the AutoScaling group is located.
* *placement:* The AWS availability zone where TP instances will be launched.

#### Advanced properties

* *spot_type:* The instance type to bid for in the spot market (recommended: the same instance from the ASG)
* *emergency_type:* The instance type to buy in case of market crash (recommended: the same instance from the ASG)
* *bid_threshold:* Time to wait before doing another spot bid to AWS. Defaults to 300 seconds.
    * More information can be found [here](https://aws.amazon.com/ec2/spot/pricing/).
* *cool_down_threshold:* Time to wait before doing another scale action again. Defaults to 360 seconds.

#### Optional properties
* *tags:* A map containing custom metadata tags that must assigned to TP instances. *(optional)*
    * More information can be found [here](http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/Using_Tags.html).
* *user_data_file:* An optional script or data that will be supplied to the instance on startup.
  If not provided, it will try to get from the Launch Configuration Group. *(optional)*
    * More information can be found [here](http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/AESDG-chapter-instancedata.html).
* *subnet_id:* The VPC's subnet id that will be used by instances TP will manage. *(optional)*
    * More information can be found [here](http://docs.aws.amazon.com/AmazonVPC/latest/UserGuide/VPC_Subnets.html).
* *monitoring_enabled:* There are two types of Monitoring: basic and detailed.
  You can enable or disable the detailed monitoring by setting this field to True or False. *(optional)*
    * More information can be found [here](https://aws.amazon.com/cloudwatch/details/#amazon-ec2-monitoring).

### Coding with tiopatinhas  ###

To install the latest version directly from [GitHub](https://github.com/chaordic/tiopatinhas):

```bash
$ git clone https://github.com/chaordic/tiopatinhas.git
$ python tiopatinhas/setup.py install
```

You may need to use `sudo` depending on your environment setup.

Then:

```python
from tp import tp

t = tp.TPManager("auto scaling group name", debug=verbose)
t.run()
```

### Executing tiopatinhas ###

To install the latest version directly from [GitHub](https://github.com/chaordic/tiopatinhas):

```bash
$ git clone https://github.com/chaordic/tiopatinhas.git
$ python tiopatinhas/setup.py install
```

You may need to use `sudo` depending on your environment setup.

* Once the tp/tp.conf file is ready, execute tiopatinhas with the following command:
    * _python tp.py -g \<AutoScalingGroupName\>_ (this command must currently be executed from within the "tp" folder)
* You must optionally supply options "-v" for verbose mode or "-d" for daemon mode.

## License

tiopatinhas is available under the [MIT license](LICENSE).