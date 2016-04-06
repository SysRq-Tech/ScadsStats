#SysRq ScadsStats
Finding active users on VK walls.

##Requirements
* Python >= 3.3
* Kivy >= 1.8.0
* [VK.com API Python Wrapper](https://github.com/dimka665/vk)
* [Requests](http://python-requests.org)

##Installing
###Debian
```bash
# echo 'deb http://ppa.launchpad.net/cybertailor/sysrq/ubuntu trusty main' >> /etc/apt/sources.list
# apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys 5919086F 
# apt-get update && apt-get install vk-stats
```
###Ubuntu
```bash
# add-apt-repository ppa:cybertailor/sysrq
# apt-get update && apt-get install vk-stats
```
###Other Linux
```bash
# python3 -m pip install ScadsStats
$ vk-stats
```

##Used libs
* [gettext_windows](https://launchpad.net/gettext-py-windows)
* [KivyCalendar](https://bitbucket.org/xxblx/kivycalendar) _(my modification)_

##Help us
* [Translate](https://poeditor.com/join/project/cq07DODUUL) program to your language
* [Join](http://vk.com/sysrqint) our VK community