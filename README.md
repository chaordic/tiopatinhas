tiopatinhas
===========

tiopatinhas is a companion for AWS's Auto Scaling. It attaches itself to an
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

