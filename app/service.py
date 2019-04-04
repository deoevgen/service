from http import HTTPStatus
import configparser
import subprocess as sp
from time import sleep
import os
import sys
from threading import Thread
import requests
import re
import shutil
import base64
from shutil import unpack_archive
from string import Formatter

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
    |        |             |            | в headers передавать dir_name и       |
    |        |             |            | verbose                               |
    |--------|-------------|------------|---------------------------------------|
    |diag    | sended_diag | error_diag |Отправление диагностики                |
    |--------|-------------|------------|---------------------------------------|
    |wait    | *           | *          | Ожидание команд                       |
    |--------|-------------|------------|---------------------------------------|
    |*       | *           | error_work | Ошибка найденая в ходе работы, по конф|
    |--------|-------------|------------|---------------------------------------|
    |config  |sended_config|error_config|Отправление файла конфигурации         |
    |--------|-------------|------------|---------------------------------------|
    |set_config|config_set|error_set_config|Изменение файла конфигурации        |
    |--------|-------------|------------|---------------------------------------|
    |update  |updated      |not_updated |Получение новых файлов, необходимых    |
    |        |             |            | для запуска                           |
    |--------|-------------|------------|---------------------------------------|
    
    Не забывать указывать в headers dir_name, verbose для определения сервиса в БД по уникальному имени папки.
    
    контроль запуска и контроль файлов для запуска.
   
       Формат ответа на команду state:
        data = {'state': state, 'error': 'text error'}
        state может иметь поле error с тестом об ошибке.
        
       Фрмат ответа на команду diag.
       
'''
API_VERSION = 'api/v1'


class Service(Thread):

    state = 'launched'
    verbose = '0000'
    update_attempt = 0
    error = ''
    process = None
    controller = None
    buffer = list()
    name_console_log = 'console_log.log'

    def __init__(self):
        super(Service, self).__init__()
        config = configparser.ConfigParser()
        config_path = os.path.abspath(os.path.dirname(sys.argv[0]))
        config.read(os.path.join(config_path, 'config.ini'))

        # порт прложения, берется из аргумента при запуске программы
        self.port = None

        # информация о контроллере, куда отпарвлять данные
        self.server_ip = config.get('georg', 'ip')
        self.server_port = config.get('georg', 'port')
        # имя приложения, для контроллера
        self.name = config.get('app', 'name')
        self.app = config.get('app', 'path')
        self.start_command_line = config.get('app', 'start_command')
        self.config_errors = config.get('control', 'errors').split(' ')
        self.dir_name = os.path.abspath(sys.modules['__main__'].__file__).split('/')[-2]
        self.session = requests.Session()

        try:
            self.diag = config.get('app', 'diag').format(name=self.name)
        except:
            self.diag = os.path.abspath('diag')

    def run(self):
        self.init_diag()
        if self.authorization():
            self.send_state()
            while True:
                self.update_command()
                sleep(1)

    def authorization(self):
        url = 'http://{ip}:{port}/{api}/service'.format(ip=self.server_ip,
                                                       port=self.server_port,
                                                       api=API_VERSION)
        headers = {'dir_name': self.dir_name, }
        data = {'name': self.name}
        # ломимся на сервер, пока не получится авторизоваться 1 раз в секунду
        while True:
            try:
                sleep(1)
                res = self.session.post(url=url, json=data, headers=headers)
                if res.status_code == HTTPStatus.CONFLICT:
                    self.session.put(url=url, json=data, headers=headers)
            except Exception as error:
                print("<runner thread> Нет связи для авторизации\n", error)
                continue
            if res.status_code == HTTPStatus.CREATED:
                return True
            if res.status_code == HTTPStatus.CONFLICT:
                res = self.session.put(url=url, json=data, headers=headers)
                if res.status_code == HTTPStatus.ACCEPTED:
                    return True
            else:
                print('<service> Нет авторизации: ', res.status_code)

    def send_state(self):
        url = 'http://{ip}:{port}/{api}/service/state'.format(ip=self.server_ip, port=self.server_port, api=API_VERSION)
        data = {'state': self.state, 'error': self.error}
        print('<send_state>', self.state)
        headers = {'dir_name': self.dir_name}
        self.session.put(url, json=data, headers=headers)

    def update_command(self):
        url = 'http://{ip}:{port}/{api}/service/command'.format(ip=self.server_ip, port=self.server_port,
                                                               api=API_VERSION)
        headers = {'dir_name': self.dir_name}
        try:
            res = self.session.get(url, headers=headers)
            if res.status_code == HTTPStatus.ACCEPTED:
                data = res.json()
                command = data.get('command')
                print('<service> command: ', command)
                self.start_command(command, data)
            else:
                print('<service> Ошибка получения команды, код ошибки: ', res.status_code)

        except Exception as error:
            print('error', error)

    def init_diag(self):
        if os.path.isdir(self.diag):
            self.clear_diag()

        os.makedirs(self.diag)

    def start_command(self, command, data):

        # выполняется каждый раз, при выполнии функции
        if self.state == 'started':
            self.control_app()

        if command == 'start':
            self.start_app(data)

        if command == 'stop':
            self.stop_app()
            self.send_log()

        if command == 'diag':
            self.send_diag()

        if command == 'config':
            self.send_config()

        if command == 'set_config':
            self.save_config()

        if command == 'update':
            self.update_attempt = self.update_attempt + 1
            print('update_attempt', self.update_attempt)
            if self.update_attempt == 4:
                self.state = 'error_update'
                self.send_state()
                return
            self.update_files()

        self.send_state()

    def start_app(self, kwargs, count_starts=0):
        self.state = 'starting'
        self.send_state()
        print('count_starts', count_starts)
        if not self.process:
            kwargs['path'] = self.app

            #  поиск файлов в параметрах и подставление абсолюдного пути в kwargs
            for key, val in kwargs.items():
                if 'comf_' in key:
                    if os.path.isfile(os.path.join('files', kwargs.get('mode'), val)):
                        file_abs = os.path.abspath(os.path.join('files', kwargs.get('mode'), val))
                        kwargs[key] = file_abs

            fmt = UnseenFormatter()
            start_command_line = fmt.format(self.start_command_line, **kwargs)
            print('[start_app] start_command_line', start_command_line)
            try:
                proc = sp.Popen([self.app], stdout=sp.PIPE, stderr=sp.PIPE)
            except:
                proc = None
            sleep(1)

            # првоерка запуска процесса
            if proc is not None:
                if proc.poll() is None:
                    self.state = 'started'
                    self.process = proc
                    # поток проверки конслольного приложения
                    self.controller = Controller(proc,
                                                 self.buffer,
                                                 self.config_errors,
                                                 os.path.join(self.diag, self.name_console_log))
                    self.controller.start()
                    return
            else:
                if count_starts == 3:
                    self.state = 'not_started'
                    return
                self.start_app(kwargs, count_starts+1)
        else:
            # заглушка, если два раза нажали на кнопку старт
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
            # заглушка, если два раза нажали на кнопку stop
            self.state = 'stopped'

    def control_app(self):
        # вот тут проверка на работоспособность из буфера
        for mes in self.buffer:
            if mes == 'stopped':
                self.state = 'stopped'
            else:
                self.state = 'error_work'
            self.error = mes
            self.send_state()
            sleep(1)
        self.buffer.clear()

    def send_diag(self):

        self.state = 'error_diag'
        url = 'http://{ip}:{port}/{api}/service/diag'.format(ip=self.server_ip, port=self.server_port,
                                                                api=API_VERSION)
        headers = {'dir_name': self.dir_name}

        if not os.path.isdir(self.diag):
            self.error = 'Неправильный путь к диагностике, {diag}'.format(diag=self.diag)
            return

        archive_name = shutil.make_archive(base_name='diag', base_dir=self.diag, format='tar')
        files = {archive_name: open(archive_name, 'rb')}

        res = self.session.post(url, files=files, headers=headers)

        if res.status_code == HTTPStatus.ACCEPTED:
            self.state = 'sended_diag'

        os.remove(archive_name)

    def clear_diag(self):
        shutil.rmtree(self.diag)

    def send_config(self):
        self.state = 'error_config'
        url = 'http://{ip}:{port}/{api}/service/config'.format(ip=self.server_ip, port=self.server_port,
                                                                api=API_VERSION)
        headers = {'dir_name': self.dir_name}
        config_path = os.path.dirname(sys.argv[0])
        config_file = os.path.join(config_path, 'config.ini')
        with open(config_file, 'r') as file:
            text = file.read()
            res = self.session.put(url, json={'config': text}, headers=headers)

        if res.status_code == HTTPStatus.ACCEPTED:
            self.state = 'sended_config'

    def save_config(self):
        self.state = 'error_config'
        url = 'http://{ip}:{port}/{api}/service/config'.format(ip=self.server_ip, port=self.server_port,
                                                                api=API_VERSION)
        headers = {'dir_name': self.dir_name}
        res = self.session.get(url, headers=headers)

        config_path = os.path.dirname(sys.argv[0])
        config_file = os.path.join(config_path, 'config.ini')
        config = res.json().get('config')
        with open(config_file, 'w+') as file:
            file.write(config)
        self.send_config()
        self.send_state()

    def update_files(self):
        self.state = 'not_updated'
        url = 'http://{ip}:{port}/{api}/service/update'.format(ip=self.server_ip, port=self.server_port,
                                                                api=API_VERSION)
        headers = {'dir_name': self.dir_name}
        res = self.session.get(url, headers=headers)
        if res.ok:
            data = res.json()

            if data.get('file') == 'not_found':  # признак отсутствия файлов, возможно они не нужны.
                self.state = 'not_found_file'
                return
            file_name = data.get('file_name')
            abspath_file = os.path.join('/tmp', file_name)
            content = data.get('data')
            decoded_content = base64.b64decode(content)
            with open(abspath_file, 'wb+') as archive:
                archive.write(decoded_content)
                archive.close()

            if data.get('md5sum') != self.md5(abspath_file):
                os.remove(abspath_file)
                return

            if os.path.isdir('files'):
                shutil.rmtree('files/')
            unpack_archive(abspath_file, extract_dir='files/', format="tar")
            self.state = 'updated'

    @staticmethod
    def md5(filename):
        import hashlib
        with open(filename, 'rb') as f:
            m = hashlib.md5()
            for chank in iter(lambda: f.read(4096), b""):
                m.update(chank)
            return m.hexdigest()

    def send_log(self):
        headers = {'dir_name': self.dir_name}

        url = 'http://{ip}:{port}/{api}/service/log'.format(ip=self.server_ip, port=self.server_port,
                                                                api=API_VERSION)

        with open(os.path.join(self.diag, self.name_console_log), 'r') as log_file:
            data = log_file.read()

            res = self.session.put(url, json={'log': data}, headers=headers)

        if res.status_code == HTTPStatus.ACCEPTED:
            print('Успешно отправлены логи')
        else:
            print('Ошибка управления')


class Controller(Thread):
    buff = None
    process = None
    _stop = False
    re_list = list()
    errors = ''
    line = ''
    path_log_file = None

    def __init__(self, proc, buff, errors, path_log_file):
        super(Controller, self).__init__()
        self.process = proc
        self.buff = buff
        self.errors = errors
        self.path_log_file = path_log_file

    def run(self):
        re_list = list(map(self.gen_re, self.errors))
        with open(self.path_log_file, 'w+') as file_log:
            for _line in iter(self.process.stdout.readline, ''):
                sleep(1)
                # бывают пустые прерывания о записи в программах
                if _line.rstrip() != '' or _line != b'':
                    file_log.write(self.line + '\n')
                    self.line = _line.rstrip().decode('utf-8')

                    result = list(map(self.find_error, re_list))
                    if any(result):
                        self.buff.append(self.line)
                        self.stop()

                    if self._stop:
                        return

    def stop(self):
        self.buff.append('stopped')
        self._stop = True

    def gen_re(self, text):
        return re.compile(text)

    def find_error(self, _re):
        return _re.search(self.line)


class UnseenFormatter(Formatter):
    # расширенный формат строки, при котором убираем отсутствующие элементы в словаре из строки, заменяя их на ''
    def get_value(self, key, args, kwargs):
        if isinstance(key, str):
            try:
                return kwargs[key]
            except KeyError:
                return ''
        else:
            return Formatter.get_value(key, args, kwargs)


if __name__ == '__main__':
    serv = Service()
    serv.send_config()


