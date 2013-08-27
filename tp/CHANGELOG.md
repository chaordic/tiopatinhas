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
