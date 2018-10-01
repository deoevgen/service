#!/usr/bin/env python3
from http.server import HTTPServer
from http.server import BaseHTTPRequestHandler
from http import HTTPStatus
import configparser
import argparse
import subprocess as sp
from time import sleep
import os
import sys
from threading import Thread
import json
import requests
import re
from functools import reduce
'''
urls уточнять у документации по ресту.
Service стартует программу, которую написали в конфиге в app.

Таблица статусов и команд от георге. Схожа с runner-ом. т.к. общая БД со статусами и командами 
    |command |       state |error state | disc                                  |
    |--------|-------------|------------|---------------------------------------|
    |*       | launched    | нет ответов|При запуске service                    |
    |--------|-------------|------------|---------------------------------------|
    |start   | started     | not_started|Запуск service                         |
    |--------|-------------|------------|---------------------------------------|
    |stop    | stopped     | not_stopped|Остановка service                      |
    |--------|-------------|------------|---------------------------------------|
    |state   | *           | *          |Проверка статуса (service return state |
    |        |             |            |   in put, url=/runner/state )         |
    |        |             |            | в headers передавать dir_name         |
    |--------|-------------|------------|---------------------------------------|
    |diag    | sended_diag | error_diag |Отправление диагностики                |
    |--------|-------------|------------|---------------------------------------|
    |wait    | *           | *          | Ожидание команд                       |
    |--------|-------------|------------|---------------------------------------|
    |*       | *           | error_work | Ошибка найденая в ходе работы, по конф|
    |--------|-------------|------------|---------------------------------------|
    |*       | ready_diag  | *          | Ошибка найденая в ходе работы, по конф|
    |--------|-------------|------------|---------------------------------------|
    
    Не забывать указывать в headers dir_name, для определения сервиса в БД по уникальному имени папки.
    
    контроль запуска и контроль файлов для запуска.
   
       Формат ответа на команду state:
        data = {'state': state, 'error': 'text error'}
        state может иметь поле error с тестом об ошибке.
        
       Фрмат ответа на команду diag.
       
'''
API_VERSION = 'api/v1'


class Service(Thread):

    state = 'launched'
    error = ''
    process = None
    controller = None
    buffer = list()

    def __init__(self):
        super(Service, self).__init__()
        config = configparser.ConfigParser()
        config_path = os.path.dirname(sys.argv[0])
        config.read(os.path.join(config_path, 'config.ini'))

        # порт прложения, берется из аргумента при запуске программы
        self.port = None

        # информация о контроллере, куда отпарвлять данные
        self.server_ip = config.get('georg', 'ip')
        self.server_port = config.get('georg', 'port')
        # имя приложения, для контроллера
        self.name = config.get('app', 'name')
        self.app = config.get('app', 'path')
        self.config_errors = config.get('app', 'errors').split(' ')
        self.dir_name = os.path.dirname(sys.modules['__main__'].__file__).split('/')[-1]
        self.session = requests.Session()

    def run(self):
        if self.authorization():
            self.send_state()
            while True:
                self.update_command()
                sleep(1)

    def authorization(self):
        url = 'http://{ip}:{port}/{api}/service'.format(ip=self.server_ip,
                                                       port=self.server_port,
                                                       api=API_VERSION)
        data = {'name': self.name, 'dir_name': self.dir_name}
        json_data = json.dumps(data)
        # ломимся на сервер, пока не получится авторизоваться 1 раз в секунду
        while True:
            try:
                sleep(1)
                res = self.session.post(url=url, data=json_data)
                if res.status_code == HTTPStatus.CONFLICT:
                    self.session.put(url=url, data=json_data)
            except Exception as error:
                print("<runner thread> Нет связи для авторизации\n", error)
                continue
            if res.status_code == HTTPStatus.CREATED:
                return True
            if res.status_code == HTTPStatus.CONFLICT:
                res = self.session.put(url=url, data=json_data)
                if res.status_code == HTTPStatus.ACCEPTED:
                    return True
            else:
                print('<service> Нет авторизации: ', res.status_code)

    def send_state(self):
        url = 'http://{ip}:{port}/{api}/service/state'.format(ip=self.server_ip, port=self.server_port, api=API_VERSION)
        data = {'state': self.state, 'error': self.error}
        print('<send_state>', self.state)
        headers = {'dir_name': self.dir_name}
        json_data = json.dumps(data)
        self.session.put(url, json_data, headers=headers)

    def update_command(self):
        url = 'http://{ip}:{port}/{api}/service/command'.format(ip=self.server_ip, port=self.server_port,
                                                               api=API_VERSION)
        headers = {'dir_name': self.dir_name}
        try:
            res = self.session.get(url, headers=headers)
            if res.status_code == HTTPStatus.ACCEPTED:
                command = res.json().get('command')
                print('<service> command: ', command)
                self.start_command(command)
            else:
                print('<service> Ошибка получения команды, код ошибки: ', res.status_code)

        except Exception as error:
            print(error)

    def start_command(self, command):

        if self.state == 'started':
            self.control_app()

        if command == 'start':
            self.start_app()
            self.send_state()

        if command == 'stop':
            self.stop_app()
            self.send_state()

    def start_app(self):
        self.state = 'not_started'
        if not self.process:
            proc = sp.Popen([self.app], stdout=sp.PIPE, stderr=sp.PIPE)
            sleep(1)
            if proc.poll() is None:
                self.state = 'started'
                self.process = proc
                # поток проверки конслольного приложения
                self.controller = Controller(proc, self.buffer, self.config_errors)
                self.controller.start()
                return
        else:
            # TODO: заглушка, если два раза нажали на кнопку старта
            self.state = 'started'

    def stop_app(self):
        self.state = 'not_stopped'
        if self.process:
            self.process.kill()
            self.controller.stop()
            sleep(1)

            if self.process.poll() is None:
                self.error = 'Процесс не завершился.'
                self.state = 'not_stopped'
            else:
                self.process = None
                self.state = 'stopped'
        else:
            # TODO: заглушка, если два раза нажали на кнопку stop
            self.state = 'stopped'

    def control_app(self):
        # вот тут проверка на работоспособность из буфера
        for mes in self.buffer:
            if mes == 'ready_diag':
                self.state = 'ready_diag'
            else:
                self.state = 'error_work'
            self.error = mes
            self.send_state()
            sleep(1)
        self.buffer.clear()


class Controller(Thread):
    buff = None
    process = None
    _stop = False
    re_list = list()
    errors = ''

    def __init__(self, proc, buff, errors):
        super(Controller, self).__init__()
        self.process = proc
        self.buff = buff
        self.errors = errors

    def run(self):
        re_list = list(map(self.gen_re, self.errors))

        for _line in iter(self.process.stdout.readline, ''):
            self.line = _line.rstrip().decode('utf-8')

            result = list(map(self.find_error, re_list))
            if any(result):
                self.buff.append(self.line)
                self.stop()

            if self._stop:
                return

    def stop(self):
        self.buff.append('ready_diag')
        self._stop = True

    def gen_re(self, text):
        return re.compile(text)

    def find_error(self, _re):
        return _re.search(self.line)


if __name__ == '__main__':
    serv = Service()
    serv.start_command('start')

