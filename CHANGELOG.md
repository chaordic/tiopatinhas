## 1.0.2 (, 2016)
    - Added cool down and bid threshold times in the configuration file
    - Refresh state doesn't affect tiopatinhas' actions anymore

## 1.0.1 (November 29, 2016)
    - Added support to get user data from Launch Configuration Group if not provided

## 1.0.0 (October 11, 2016)
    - Added Monitoring enabled option
    - Added submodule support
    - Added VPC support
    - Added instance IAM role/profile support
    - Removed CPU checks from tiopatinhas and added weight factor (now you decide the ratio of machines that tiopatinhas will handle and the ASG handles everything else)
    - Fixes on Market crashed handlers and LB bugs
    - Instances marked-for-termination are now considered already down

## 0.1.1 (November 21, 2013)

Features:
    - Added spot and emergency type configuration (advanced feature that allows to use instance types different from the ASG)
    - Enable cloudwatch spot instances monitoring

Bugfixes:
    - Added fault tolerance to HTTP request errors (will now log error instead of crashing)

## 0.1.0 (August 27, 2013)

Features:

    - Configured logging per TPManager instance (instead of global logging)
    - Added ability to stop a TPManager instance
    - Enabled region-awareness (specified via config file or parameter)
    - Added support to tags (specified via config file)
    - Extracted user data to configuration file (or parameter)
    - Enabled verbose (debug) mode

Bugfixes:

    - Fixed bug that was preventing market crash to be detected when there were active/open bids.
    - Dettaching emergency instances from Load Balancer when they are demoted.
