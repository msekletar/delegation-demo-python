# Cgroup delegation demo

This repo contains very simple python application (script) that show-cases
cgroup delegation concept with systemd. To run the demo start `bin/demo.py` as
`root`.

Script will create a scope unit and it will turn on delegation flag on
the scope, i.e. you are able to freely create sub-cgroups under the cgroup
that belongs to scope. Next, it creates couple of dummy processes and puts
them in sub-cgroups. At last we print the respective part of the cgroup tree.

Notice that we delegate only CPU, Memory, BlkIO and PIDs cgroup controllers.

## Requirements
- RHEL/CentOS 7 or newer
- python-3.6 or newer

## Dependencies
- [psutil](https://github.com/giampaolo/psutil)
- [dbus-python](https://www.freedesktop.org/wiki/Software/DBusBindings/#python)

Install the dependencies either using distro package (i.e. python3-dbus python3-psutil packages on RHEL-8) manager or using pip.
```
$ python3 -m pip install --user .
```
