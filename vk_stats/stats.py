#!/usr/bin/env python3
# coding=utf-8

#  SysRq ScadsStats. Finding active users on VK walls.
#    Copyright (C) 2015-2016  Matvey Vyalkov
#
#    This file is part of SysRq VK Stats.
#
#    SysRq VK Stats is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    SysRq VK Stats is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.


import os
import sys
import csv
import atexit
import shutil
import pickle
import tempfile
import time
import threading
import vk
import vk.exceptions
import requests
import requests.exceptions
import queue
from webbrowser import open as open_url
from vk.utils import stringify_values
from kivy.app import App
from .service import HOME, SCRIPTDIR, _
from .KivyCalendar import DatePicker
from kivy.logger import Logger
from kivy.core.window import Window
from kivy.config import Config
from kivy.uix.tabbedpanel import TabbedPanel
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.actionbar import ActionButton
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.lang import Builder
from kivy.utils import platform
from kivy.clock import Clock
from kivy.properties import ObjectProperty as Object

__author__ = "CyberTailor <cybertailor@gmail.com>"
__version__ = '1.0 "Carboneum"'
v_number = 4
api_ver = "5.44"
infinity = float("inf")

NAME = "ScadsStats: "
CURDIR = os.getcwd()
SAVEDIR = CURDIR + "/results"
TEMP = tempfile.mktemp(prefix="sysrq-")
os.mkdir(TEMP)
atexit.register(shutil.rmtree, TEMP)
mustdie = platform == "win"
# translating strings in _()
Logger.info(NAME + _("Создана временная директория %s"), TEMP)

Builder.load_file(SCRIPTDIR + "/interface.kv")


class Stop(Exception):
    """ Exception to stop thread """
    pass


class Partial:
    """
    Ignoring arguments passed to __call__ method
    """

    def __init__(self, func, *args, **kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs.copy()

    def __call__(self, *stuff):
        return self.func(*self.args, **self.kwargs)


class ExcThread(threading.Thread):
    """
    Thread with information about exceptions
    """

    def __init__(self, bucket, after=None, **kwargs):
        threading.Thread.__init__(self, **kwargs)
        self.bucket = bucket
        self.after = after

    def run(self):
        """
        Makes exceptions available for main thread
        """
        try:
            if self._target:
                self._target(*self._args, **self._kwargs)
        except Exception:
            self.bucket.put(sys.exc_info())
        finally:
            del self._target, self._args, self._kwargs
            if self.after is not None:
                self.after()


class FailSafeSession(vk.Session):
    """
    Session with reduced chance of raising error
    """

    def send_api_request(self, request, captcha_response=None):
        """
        Modified method with immunity to timeout and bad internet
        :param request: VK API method
        :param captcha_response: captcha dictionary
        """
        url = self.API_URL + request._method_name
        method_args = request._api._method_default_args.copy()
        method_args.update(stringify_values(request._method_args))
        access_token = self.access_token
        if access_token:
            method_args['access_token'] = access_token
        if captcha_response:
            method_args['captcha_sid'] = captcha_response['sid']
            method_args['captcha_key'] = captcha_response['key']
        timeout = request._api._timeout
        try:
            response = self.requests_session.post(url, method_args, timeout=timeout)
        except requests.exceptions.ReadTimeout:
            Logger.warning(NAME + _("Операция прервана по тайм-ауту"))
            time.sleep(5)
            response = self.send_api_request(request, captcha_response=captcha_response)
        return response


class FailSafeAuthSession(vk.AuthSession, FailSafeSession):
    """ Failsafe AuthSession """
    pass


class SleepAPI(vk.API):
    """
    API class with immunity to 'Too many requests per second' error
    """

    def __getattr__(self, method_name):
        time.sleep(0.33)
        return vk.API.__getattr__(self, method_name)


class AllOk(BoxLayout):
    ok = Object
    message = Object

    def show(self, text, title):
        self.message.text = text
        popup = Popup(title=title,
                      title_size='18sp',
                      content=self,
                      size_hint=(0.85, 0.6))
        self.ok.bind(on_press=popup.dismiss)
        popup.open()


class Info(BoxLayout):
    ok = Object
    message = Object

    def show(self, text, title):
        self.message.text = text
        popup = Popup(title=title,
                      content=self,
                      title_size='18sp',
                      size_hint=(0.85, 0.6))
        self.ok.bind(on_press=popup.dismiss)
        popup.open()


class Alert(BoxLayout):
    ok = Object
    message = Object

    def show(self, text, kill=False):
        self.message.text = text
        popup = Popup(title=_("Предупреждение"),
                      title_size='18sp',
                      content=self,
                      size_hint=(0.85, 0.6),
                      auto_dismiss=False)
        if kill:
            self.ok.bind(on_press=Partial(os._exit, 1))
        else:
            self.ok.bind(on_press=popup.dismiss)
        popup.open()


class Bar:
    def __init__(self, bar, bar_text):
        self.bar = bar
        self.bar.max = 100
        self.bar_text = bar_text

    def set_max(self, max_value):
        self.bar.max = max_value

    def set_value(self, value):
        self.bar.value = value

    def set_text(self, text):
        self.bar_text.text = text

    def finish(self):
        self.set_value(0)


def info(message, title=_("Некоторая информация")):
    Info().show(message, title)


def all_ok(message, title=_("Всё OK")):
    AllOk().show(message, title)


def warning(message, kill=False):
    Alert().show(message, kill)


def results(folder):
    """
    Setting folder for results
    :param folder: path to directory where the program will save results
    """
    global SAVEDIR
    Logger.info(NAME + _("Результаты будут сохранены в %s"), folder)
    SAVEDIR = folder


def write_token(access_token):
    """
    Writing token to file in home directory.
    :param access_token: access_token for VK.com
    """
    token_file = open(HOME + "/token.txt", mode="w")
    token_file.write(access_token)


def upgrade(version, upd_log):
    """
    Upgrading program
    :param upd_log: Label object
    :param version: version name for VK Stats
    """
    upd_log.text = _("Скачиваю новую версию...")
    installer = TEMP + "/VK_Stats.exe"
    with open(installer, 'wb') as file:
        file.write(requests.get(
            "https://github.com/SysRq-Tech/ScadsStats/releases/download/{}/WIN.exe".format(version)).content)
    upd_log.text = _("Запускаю установщик...")
    os.startfile(installer)
    upd_log.text = _("Завершаю работу приложения...")
    time.sleep(1.5)
    os._exit(0)


def upd_check():
    """
    Checking for updates
    """
    latest = requests.get("http://net2ftp.ru/node0/CyberTailor@gmail.com/versions.json").json()["vk_stats"]
    if latest["number"] > v_number:
        return latest["version"]
    else:
        return None


def get_api(api_session=None, access_token=None):
    """
    Providing instance of *SleepAPI* class.
    :param api_session: vk.Session
    :param access_token: token for VKontakte
    """
    global api
    if api_session is not None:
        api = SleepAPI(api_session, v=api_ver)
    if access_token is not None:
        session = FailSafeSession(access_token)
        api = SleepAPI(session, v=api_ver)
        write_token(access_token)
    try:
        api.users.get()
    except vk.exceptions.VkAPIError:
        if "token.txt" in os.listdir(HOME):
            os.remove(HOME + "/token.txt")
        raise vk.exceptions.VkAuthError()
    return api


def login(email, password):
    """
    Authorisation in https://vk.com
    :param password: password for VK.com
    :param email: e-mail address or phone number
    :return: access_token for VK
    """
    global api
    app_id = 4589594
    session = FailSafeAuthSession(user_login=email, user_password=password,
                                  app_id=app_id, scope=["stats", "groups", "wall"])
    get_api(api_session=session)
    write_token(session.get_access_token())


def resolve(url):
    """
    Resolving VKontakte URLs
    :param url: address of group or profile
    :return: {"id": <ID of wall>, "name": <screen name>, "title": <title or name/surname>}
    """
    wall_data = api.utils.resolveScreenName(screen_name=url.split("/")[-1])
    if not wall_data:
        raise Stop(_("Неверный URL"))
    wall_type = wall_data["type"]
    obj_id = wall_data["object_id"]

    if wall_type == "group":
        group_data = api.groups.getById(group_ids=obj_id)[0]
        screen_name = group_data["screen_name"]
        title = group_data["name"]
        wall_id = "-" + str(obj_id)
    else:
        profile = api.users.get(user_ids=obj_id, fields="screen_name")[0]
        screen_name = profile["screen_name"]
        title = "{first_name} {last_name}".format(**profile)
        wall_id = obj_id
    return {"id": wall_id, "name": screen_name, "title": title}


def percents(el, seq):
    """
    Computing progress for sequence.
    :param el: element or first number
    :param seq: sequence or last number
    :return: percent
    """
    if isinstance(seq, int):
        percent = el * 100 / seq
    else:
        percent = (seq.index(el) + 1) * 100 / len(seq)
    return round(percent, 2)


def make_packs(l, num):
    pack_len = len(l) // num
    work_list = l.copy()
    result = []
    for make_packs._ in range(num - 1):
        result.append(work_list[:pack_len])
        del work_list[:pack_len]
    result.append(work_list)
    return result


def list_of_str(seq):
    """
    Converting sequence of integers to list of strings.
    :param seq: any sequence
    :return: list of string
    """
    return [str(el) for el in seq]


class Stats:
    """
    Gathering statistics
    """

    def __init__(self, name, bar, *, posts_lim=0, from_lim="0.0.0", to_lim="0.0.0"):
        """
        Run set_bar() and loggers() functions before calling.
        :param name: ID or screen name
        :param posts_lim: limit for posts
        :param from_lim: date of the earliest post
        :param to_lim: date of the latest post
        """
        self.bar = bar
        self.plist = []
        self.likers_list = []
        self.comm_list = []
        self.id_list = []
        self.screen_name = name
        self.cache = "{}/{}.dat".format(TEMP, self.screen_name)
        self.savedir = os.path.join(SAVEDIR, self.screen_name)

        # ID of a wall
        self.wall = resolve(self.screen_name)["id"]

        # limit for posts
        if not posts_lim:
            self.posts_lim = api.wall.get(owner_id=self.wall, count=1)["count"]
        else:
            self.posts_lim = posts_lim
        Logger.info(NAME + _("Ограничено до %s постов"), self.posts_lim)

        # date limit
        try:
            date_list = [int(num) for num in from_lim.split(".") + to_lim.split(".")]
            assert len(date_list) == 6
            assert date_list[2] > 2000 or not date_list[2]
            assert date_list[-1] > 2000
        except (AssertionError, ValueError):
            raise Stop(_("Неправильный формат даты!"))

        if not sum(date_list[:3]):  # if result is 0
            self.from_lim = 0
        else:
            self.from_lim = time.mktime((date_list[2], date_list[1], date_list[0], 0, 0, 0, 0, 0, -1))
            Logger.info(NAME + _("Будут получены посты с даты %s"), from_lim)
        if not sum(date_list[3:]):
            self.to_lim = infinity
        else:
            self.to_lim = time.mktime((date_list[5], date_list[4], date_list[3], 23, 59, 59, 0, 0, -1))
            Logger.info(NAME + _("Будут получены посты до даты %s"), to_lim)

        if os.path.isfile(self.cache):
            with open(self.cache, "rb") as cache:
                loaded = pickle.load(cache)
                if loaded[3] >= self.from_lim \
                        and loaded[4] <= self.to_lim \
                        and loaded[5] <= self.posts_lim:
                    self.plist, self.likers_list, self.comm_list = loaded[:3]
                    Logger.info(NAME + _("Кэш стены загруженен"))

    def _restore(self):
        self.plist = []
        self.likers_list = []
        self.comm_list = []
        self.id_list = []
        self.bar.set_text("")
        self.bar.finish()

    def _check_limit(self, data):
        date = data["date"]
        if self.from_lim and date < self.from_lim:
            Logger.debug("FROM: " + time.strftime("%d.%m.%y", time.localtime(date)))
            return True
        return False

    def _get_posts(self):
        posts = []
        thousands_range = self.posts_lim // 1000 + self.posts_lim % 1000
        offset = 0
        self.bar.set_text(_("Получение постов"))

        for post in range(thousands_range):
            if offset > 0:
                if self._check_limit(posts[-1]) or len(posts) > self.posts_lim:
                    return posts
            self.bar.set_value(percents(offset, self.posts_lim))
            posts.extend(api.execute.wallGetThousand(owner_id=self.wall, offset=offset))
            offset += 1000
        self.bar.finish()
        return posts

    def _get_likers(self, offset=0, did=0, task=0):
        id_list_copy = self.id_list.copy()
        twenty_five_range = len(self.id_list) // 25 + len(self.id_list) % 25

        for i in range(twenty_five_range):
            self.bar.set_value(percents(did, task))
            count = id_list_copy[:25]
            if not id_list_copy:
                break
            data = api.execute.likesList(wall=self.wall, posts=",".join(list_of_str(count)), offset=offset)
            for index, post in enumerate(data):
                self.likers_list.extend(post["items"])
                if post["count"] - offset <= 1000:
                    self.id_list.remove(count[index])
                    did += 1
            del id_list_copy[:25]

        if self.id_list:
            self._get_likers(offset + 1000, did, task)
        self.bar.finish()

    def _get_comm(self, offset=0, did=0, task=0):
        id_list_copy = self.id_list.copy()
        twenty_five_range = len(self.id_list) // 25 + len(self.id_list) % 25

        for i in range(twenty_five_range):
            self.bar.set_value(percents(did, task))
            count = id_list_copy[:25]
            if not id_list_copy:
                break
            data = api.execute.commList(wall=self.wall, posts=",".join(list_of_str(count)), offset=offset)
            for index, comm in enumerate(data):
                self.comm_list.extend([commentator["from_id"] for commentator in comm["items"]])
                if comm["count"] - offset <= 100:
                    self.id_list.remove(count[index])
                    did += 1
            del id_list_copy[:25]

        if self.id_list:
            self._get_comm(offset + 100, did, task)
        self.bar.finish()

    def _process_post_pack(self, posts):
        for data in posts:
            if self._check_limit(data):
                continue
            if data["date"] > self.to_lim:
                Logger.debug("TO: " + time.strftime("%d.%m.%y", time.localtime(data["date"])))
                continue
            post_id = data["id"]
            from_id = data["from_id"]
            likes = data["likes"]["count"]
            comments = data["comments"]["count"]
            self.plist.append({"data": [from_id, likes, comments], "id": post_id})

    def posts_list(self):
        """
        Making list of posts with senders' IDs and count of likes.
        :return: list of posts
        """
        if self.plist:
            return
        posts = self._get_posts()
        task = len(posts)
        packs = make_packs(posts, 2)
        self.bar.set_text(_("Обработка постов"))
        workers = [threading.Thread(target=self._process_post_pack, args=(pack,)) for pack in packs]
        for w in workers:
            w.start()
        while True:
            alive = [w.is_alive() for w in workers]
            if alive == [False, False]:
                break
            self.bar.set_value(percents(len(self.plist), task))
            time.sleep(0.005)
        Logger.info(NAME + _("Обработано %s постов"), len(self.plist))
        self.plist = self.plist[:self.posts_lim]
        self.bar.finish()

    def users(self, users_list):
        """
        List of information about users
        :param users_list: list of users' IDs
        """
        result = []
        task = len(users_list)
        self.bar.set_text(_("Получение пользователей"))

        while users_list:
            users = ",".join([str(user) for user in users_list[:1000] if user > 0])
            self.bar.set_value(percents(len(result), task))
            data = api.users.get(user_ids=users, fields="screen_name")
            result.extend(data)
            del users_list[:1000]
        self.bar.finish()
        return result

    def likers(self):
        """
        Users who liked posts.
        :return: lists of likers
        """
        if self.likers_list:
            return
        self.id_list = [data["id"] for data in self.plist]
        self.bar.set_text(_("Получение лайкеров"))

        self._get_likers(task=len(self.id_list))

    def commentators(self):
        """
        Users who commented posts.
        :return: lists of posts and commentators
        """
        if self.comm_list:
            return
        self.id_list = [data["id"] for data in self.plist]
        self.bar.set_text(_("Получение комментаторов"))

        self._get_comm(task=len(self.id_list))

    def gather_stats(self):
        """
        Gathering statistics [POSTERS].
        :return: tuple with user's information and count of posts
        """
        self.posts_list()
        self.bar.set_text(_("Обработка пользователей"))

        from_ids = [uid["data"][0] for uid in self.plist]
        from_ids_unique = list({uid for uid in from_ids})
        from_list = []
        data = self.users(from_ids_unique)

        self.bar.set_text(_("Обработка пользователей"))
        for user in data:
            if "deactivated" in user:  # if user is deleted or banned
                user["screen_name"] = user["deactivated"].upper()
            posts_from_user = from_ids.count(user["id"])
            self.bar.set_value(percents(user, data))
            from_list.append((posts_from_user, user))
        self.bar.finish()
        return from_list

    def __call__(self, mode="Writers"):
        """
        Exporting statistics.
        :param mode: prefix for file
        """
        self.bar.set_text(_("Инициализация"))
        api.stats.trackVisitor()

        data = self.gather_stats()
        with open(self.cache, "wb") as cache:
            pickle.dump([self.plist, self.likers_list, self.comm_list,
                         self.from_lim, self.to_lim, self.posts_lim], file=cache)
        self.savedir = os.path.join(SAVEDIR, self.screen_name)
        if not os.path.isdir(self.savedir):
            os.makedirs(self.savedir, exist_ok=True)
        self.bar.set_text(_("Сохранение результатов"))

        res_txt = os.path.join(self.savedir, mode.lower() + ".txt")
        res_csv = os.path.join(self.savedir, mode.lower() + ".csv")
        res_html = os.path.join(self.savedir, mode.lower() + ".html")
        for file in res_txt, res_csv, res_html:
            if os.path.isfile(file):
                os.remove(file)
        txt_file = open(res_txt, mode="a")
        print(_("РЕЖИМ СТАТИСТИКИ:"), mode.upper(), file=txt_file)

        csv_file = open(res_csv, mode="a", newline="")
        writer = csv.writer(csv_file)
        writer.writerow(["URL", _("Имя"), _("Счёт")])

        html_file = open(res_html, mode="a")
        html_header = open(SCRIPTDIR + "/html/stats_header.html").read()
        html_item = open(SCRIPTDIR + "/html/stats_item.html").read()
        html_item_inactive = open(SCRIPTDIR + "/html/stats_item_inactive.html").read()
        html_end = open(SCRIPTDIR + "/html/stats_end.html").read()
        print(html_header.format(title=mode, user=_("Пользователь"), count=_("Счёт")),
              file=html_file)

        Logger.info(NAME + _("Сохранение результатов в %s"), self.savedir)
        task = len(data)
        place = [0, infinity]
        for did in range(1, len(data) + 1):
            if not data:
                break
            max_object = max(data, key=lambda sequence: sequence[0])
            max_count = max_object[0]
            if max_count < place[1]:
                place[1] = max_count
                place[0] += 1
            max_index = data.index(max_object)
            user_data = data.pop(max_index)[1]
            if max_count > 0:
                prefix = "" if user_data["screen_name"] in ["DELETED", "BANNED"] else "https://vk.com/"

                user_string = "{2}. {1}{screen_name} ({first_name} {last_name}): {0}".format(max_count, prefix,
                                                                                             place[0], **user_data)
                print(user_string, file=txt_file)

                writer.writerow([prefix + user_data["screen_name"],
                                 "{first_name} {last_name}".format(**user_data),
                                 max_count])

                if prefix:
                    print(html_item.format(place[0], max_count, **user_data), file=html_file)
                else:
                    print(html_item_inactive.format(place[0], max_count, **user_data), file=html_file)

                if not did % 50:
                    for file in txt_file, csv_file, html_file:
                        file.flush()
            self.bar.set_value(percents(did, task))
            time.sleep(0.005)

        print(html_end.format(_("Получить программу")), file=html_file)
        for file in txt_file, csv_file, html_file:
            file.close()
        self._restore()
        all_ok(_("Сделано!"))
        if mustdie:
            os.startfile(self.savedir)
        elif platform == "linux":
            os.system("xdg-open '{}'".format(self.savedir))


class FavoritesStats(Stats):
    """
    Gather, make and export statistics for liked posts
    """

    def gather_stats(self):
        """
        Gathering statistics for liked posts.
        :return: dictionary with user's information and general count of likes
        """
        self.posts_list()

        self.bar.set_text(_("Обработка пользователей"))
        data = [val["data"] for val in self.plist]
        users = {val[0]: 0 for val in data}
        result = []
        for user, likes, comm in data:
            users[user] += likes
        items_list = list(users.items())
        users_list = [key[0] for key in items_list]
        likes_list = [key[1] for key in items_list]

        users_data = self.users(users_list)
        self.bar.set_text(_("Обработка пользователей"))
        for user, likes in zip(users_data, likes_list):
            if "deactivated" in user:
                user["screen_name"] = user["deactivated"].upper()
            if likes > 0:
                result.append((likes, user))
            self.bar.set_value(percents(likes, likes_list))
        self.bar.finish()
        return result

    def __call__(self, **kwargs):
        """
        Exporting statistics for likes
        :param kwargs: for compatibility
        """
        Stats.__call__(self, mode="Favorites")


class LikersStats(Stats):
    """
    Gather, make and export statistics for likers
    """

    def gather_stats(self):
        """
        Gathering statistics for likers.
        :return: dictionary with user's information and general count of likes
        """
        self.posts_list()
        self.likers()

        self.bar.set_text(_("Обработка пользователей"))
        likers_unique = list({uid for uid in self.likers_list})
        result = []
        did = 0
        task = len(likers_unique)

        users_data = self.users(likers_unique)
        self.bar.set_text(_("Обработка пользователей"))

        for liker in users_data:
            count = self.likers_list.count(liker["id"])
            if "deactivated" in liker:
                liker["screen_name"] = liker["deactivated"].upper()
            self.bar.set_value(percents(did, task))
            result.append((count, liker))
            did += 1
        self.bar.finish()
        return result

    def __call__(self, **kwargs):
        """
        Exporting statistics for likers
        """
        Stats.__call__(self, mode="Likers")


class DiscussedStats(Stats):
    """
    Gather, make and export statistics for likers
    """

    def gather_stats(self):
        """
        Gathering statistics for commented posts.
        :return: dictionary with user's information and general count of comments to his/her posts
        """
        self.posts_list()

        self.bar.set_text(_("Обработка пользователей"))
        data = [val["data"] for val in self.plist]
        users = {val[0]: 0 for val in data}
        result = []
        for user, likes, comments in data:
            users[user] += comments
        items_list = list(users.items())
        users_list = [key[0] for key in items_list]
        comments_list = [key[-1] for key in items_list]

        users_data = self.users(users_list)
        self.bar.set_text(_("Обработка пользователей"))
        for user, likes in zip(users_data, comments_list):
            if "deactivated" in user:
                user["screen_name"] = user["deactivated"].upper()
            self.bar.set_value(percents(likes, comments_list))
            result.append((likes, user))
        self.bar.finish()
        return result

    def __call__(self, **kwargs):
        """
        Exporting statistics for likers
        """
        Stats.__call__(self, mode="Discussed")


class CommentatorsStats(Stats):
    """
    Gather, make and export statistics for commentators
    """

    def gather_stats(self):
        """
        Gathering statistics for likers.
        :return: dictionary with user's information and general count of likes
        """
        self.posts_list()

        self.commentators()
        self.bar.set_text(_("Обработка пользователей"))
        comm_unique = list({uid for uid in self.comm_list})
        result = []
        did = 0
        task = len(comm_unique)

        users_data = self.users(comm_unique)
        self.bar.set_text(_("Обработка пользователей"))

        for commentator in users_data:
            count = self.comm_list.count(commentator["id"])
            if "deactivated" in commentator:
                commentator["screen_name"] = commentator["deactivated"].upper()
            self.bar.set_value(percents(did, task))
            result.append((count, commentator))
            did += 1
        self.bar.finish()
        return result

    def __call__(self, **kwargs):
        """
        Exporting statistics for commentators
        """
        Stats.__call__(self, mode="Commentators")


# =====--- GUI ---===== #


class IconButton(Button):
    pass


class Tooltip(Label):
    pass


class Date(DatePicker):
    pass


class TooltipButton(ActionButton):
    tooltip = Tooltip(text="Hello world")

    def __init__(self, **kwargs):
        Window.bind(mouse_pos=self.on_mouse_pos)
        super(ActionButton, self).__init__(**kwargs)

    def on_mouse_pos(self, *args):
        if not self.get_root_window():
            return
        pos = args[1]
        self.tooltip.pos = pos
        Clock.unschedule(self.show_tooltip)  # cancel scheduled event since I moved the cursor
        self.close_tooltip()  # close if it's opened
        if self.collide_point(*self.to_widget(*pos)):
            Clock.schedule_once(self.show_tooltip, 0.75)

    def close_tooltip(self, *args):
        Window.remove_widget(self.tooltip)

    def show_tooltip(self, *args):
        self.tooltip.text = self.text
        Window.add_widget(self.tooltip)


class Update(BoxLayout):
    no = Object
    yes = Object
    version = Object
    upd_text = Object


class Saveto(BoxLayout):
    select = Object
    chooser = Object

    def save(self, popup):
        selection = self.chooser.selection
        results(selection[0] if selection else HOME)
        popup.dismiss()


class Token(BoxLayout):
    login = Object
    token = Object
    link = Object
    token_manual = _("1) Откройте [color=3366bb][ref=http://vk.cc/3T1J9A]страницу авторизации[/ref][/color]\n" +
                     "2) Войдите и дайте разрешения приложению\n" +
                     "3) Скопируйте текст из адресной строки\n" +
                     "4) Вставьте его ниже!")


class Login(BoxLayout):
    log_in = Object
    by_token = Object
    login = Object
    password = Object

    def token_auth(self, popup):
        try:
            get_api(access_token=self.content.token.text)
        except vk.exceptions.VkAuthError:
            warning(_("Неверный токен!"))
        else:
            popup.dismiss()

    def use_token(self, parent_popup, force=False):
        parent_popup.dismiss()

        self.content = Token()
        popup = Popup(title=_("Вход по токену"),
                      title_size='18sp',
                      content=self.content,
                      size_hint=(0.8, 0.65))
        if force:
            popup.auto_dismiss = False
        self.content.link.bind(on_ref_press=Partial(open_url, "http://vk.cc/3T1J9A"))
        self.content.login.bind(on_press=Partial(self.token_auth, popup))
        popup.open()

    def auth(self, popup):

        try:
            login(self.login.text, self.password.text)
        except vk.exceptions.VkAuthError:
            warning(_("Неверный логин или пароль!"))
        else:
            popup.dismiss()


class Account(BoxLayout):
    relogin = Object


class About(TabbedPanel):
    link = Object
    rst = Object
    about_text = _('[b][size=28]ScadsStats 1.0[/size][/b]\n'
                   'Вычисление активных пользователей на стенах ВКонтакте.[color=3366bb]\n'
                   '[ref=https://vk.com/sysrqtech]Сообщество ВК[/ref][/color]')

    def __init__(self, **kwargs):
        super(About, self).__init__(**kwargs)
        self.bind(current_tab=self.on_current_tab)

    def on_current_tab(self, *args):
        if args[1].text == _("Лицензия"):
            self.rst.text = open(SCRIPTDIR + "/docs/license.rst").read()
        elif args[1].text == _("Помочь нам"):
            open_url("https://github.com/SysRq-Tech/ScadsStats")


class Main(App, BoxLayout):
    bar = Object
    bar_text = Object
    group_input = Object
    from_input = Object
    to_input = Object
    posts_input = Object
    mode = Object
    go = Object
    icon = SCRIPTDIR + "/images/icon.png"
    title = "ScadsStats"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.started = False

    def _restore(self):
        self.started = False

    @staticmethod
    def get_user_photo():
        """
        :return: 200px user photo
        """
        return api.users.get(fields="photo_200")[0]["photo_200"]

    @staticmethod
    def get_user_name():
        """
        :return: user's name and surname for Account menu
        """
        data = api.users.get()[0]
        return _("Вы авторизованы как [b]{first_name} {last_name}[/b]").format(**data)

    @staticmethod
    def update_check():
        """
        Checking for updates
        """
        status = upd_check()
        if status is None:
            all_ok(_("Вы используете последнюю версию!"), title=_("Нечего делать ;)"))
        else:
            if not mustdie:
                warning(_("Используйте пакетный менеджер для обновления"))
            else:
                content = Update()
                content.version.text = _("Найдено обновление до {}!").format(status) + "\n" + _("Обновиться") + "?"
                popup = Popup(title=_("Найдено обновление!"),
                              title_size='18sp',
                              content=content,
                              size_hint=(0.8, 0.7))
                content.no.bind(on_press=popup.dismiss)
                content.yes.bind(on_press=Partial(upgrade, status, content.upd_text))
                popup.open()

    @staticmethod
    def is_dir(directory, filename):
        return os.path.isdir(os.path.join(directory, filename))

    def datepicker(self):
        self.date = None
        content = Date(self.date, self.date_input)
        popup = Popup(title=_("Ограничение по дате"),
                      title_size='18sp',
                      content=content,
                      size_hint=(0.7, 0.9))
        content.ok.bind(
            on_press=Partial(content.set_date, content.from_date.active_date, content.to_date.active_date, popup))
        popup.open()

    @staticmethod
    def saveto():
        content = Saveto()
        popup = Popup(title=_("Выберите папку"),
                      title_size='18sp',
                      content=content,
                      size_hint=(0.9, 0.9))
        content.select.bind(on_press=Partial(content.save, popup))
        popup.open()

    @staticmethod
    def login(force=False, parent=None):
        if parent is not None:
            parent.dismiss()
        content = Login()
        popup = Popup(title=_("Вход по паролю"),
                      title_size='18sp',
                      content=content,
                      size_hint=(0.8, 0.55))
        if force:
            popup.auto_dismiss = False
        content.by_token.bind(on_press=Partial(content.use_token, popup, force=force))
        content.log_in.bind(on_press=Partial(content.auth, popup))
        popup.open()

    def account(self):
        content = Account()
        popup = Popup(title=_("Аккаунт"),
                      title_size='18sp',
                      content=content,
                      size_hint=(0.8, 0.6))
        content.relogin.bind(on_press=Partial(self.login, parent=popup))
        popup.open()

    @staticmethod
    def about():
        content = About()
        popup = Popup(title=_("О ScadsStats"),
                      title_size='18sp',
                      content=content,
                      size_hint=(0.95, 0.95))
        content.link.bind(on_ref_press=Partial(open_url, "https://vk.com/sysrqtech"))
        popup.open()

    def watch(self, bucket):
        while True:
            if not self.started:
                return
            try:
                exc = bucket.get(block=False)
            except queue.Empty:
                pass
            else:
                exc_type, exc_obj, exc_trace = exc
                # deal with the exception
                warning(str(exc_obj))
                self._restore()
                return
            time.sleep(1)

    def start(self):
        """
        Gathering statistics
        """
        if self.started:
            return
        self.started = True
        group = self.group_input.text
        from_date = self.from_input.text
        to_date = self.to_input.text
        posts = self.posts_input.text
        mode = self.mode.text

        if not group:
            warning(_("Укажите стену"))
            self._restore()
            return
        if not posts:
            posts = 0
        else:
            posts = int(posts)
        try:
            if mode == _("Пишущие"):
                method = Stats(group, Bar(self.bar, self.bar_text),
                               posts_lim=posts, from_lim=from_date, to_lim=to_date)
            elif mode == _("Лайкаемые"):
                method = FavoritesStats(group, Bar(self.bar, self.bar_text),
                                        posts_lim=posts, from_lim=from_date, to_lim=to_date)
            elif mode == _("Лайкеры"):
                method = LikersStats(group, Bar(self.bar, self.bar_text),
                                     posts_lim=posts, from_lim=from_date, to_lim=to_date)
            elif mode == _("Обсуждаемые"):
                method = DiscussedStats(group, Bar(self.bar, self.bar_text),
                                        posts_lim=posts, from_lim=from_date, to_lim=to_date)
            else:
                method = CommentatorsStats(group, Bar(self.bar, self.bar_text),
                                           posts_lim=posts, from_lim=from_date, to_lim=to_date)
        except Stop as err:
            warning(err.args[0])
            self._restore()
            return

        bucket = queue.Queue()
        thread = ExcThread(bucket, target=method, after=self._restore).start()
        threading.Thread(target=self.watch, args=(bucket,)).start()

    def check(self, *args):
        """
        Checking for access to VKontakte
        """
        try:
            if "token.txt" in os.listdir(HOME):
                token = open(HOME + "/token.txt").read()
                try:
                    get_api(access_token=token)
                except vk.exceptions.VkAuthError:
                    self.login(force=True)
            else:
                self.login(force=True)
        except requests.exceptions.ConnectionError:
            warning(_("Проверьте Ваше интернет-соединение"), kill=True)

    def build(self):
        """
        Scheduling check for access to vk.com
        """
        Clock.schedule_once(self.check, 1)
        return self


def main():
    Window.size = (700, 400)
    Config.set("kivy", "exit_on_escape", 0)
    Config.set("input", "mouse", "mouse,disable_multitouch")
    Config.set("graphics", "resizable", 0)
    try:
        Main().run()
    except TypeError as err:
        if not err.args[0] == "'NoneType' object is not subscriptable":
            raise


if __name__ == "__main__":
    main()
